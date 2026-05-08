from __future__ import annotations

import json
import re
from datetime import UTC
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any

from lxml import etree

from .contracts import RedditItemPayload
from .models import RedditItem

REDDIT_ORIGIN = "https://www.reddit.com"
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
JsonItem = tuple[str, dict[str, Any]]


class _PlainTextHTMLParser(HTMLParser):
    """HTMLParser adapter that extracts readable text from Reddit HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "p", "li", "blockquote", "pre"}:
            self.parts.append("\n")

    def get_text(self) -> str:
        return _collapse_whitespace(" ".join(self.parts))


def parse_reddit_json_response(
    raw_response: str | bytes | bytearray | Any,
) -> list[RedditItemPayload]:
    """Normalize a raw Reddit JSON response into Reddit item payloads.

    Input:
        A decoded Reddit JSON object, JSON text, or bytes.

    Output:
        Payloads for post and comment objects found in listings, searches, and
        comment-tree responses. Unknown Reddit child kinds are ignored.
    """
    document = _load_json_document(raw_response)
    payloads: list[RedditItemPayload] = []
    seen_ids: set[str] = set()

    for kind, child_data in _iter_json_items(document):
        payload = _payload_from_json_child(kind, child_data)
        if payload is None or payload.reddit_id in seen_ids:
            continue

        seen_ids.add(payload.reddit_id)
        payloads.append(payload)

    return payloads


def parse_reddit_atom_response(
    raw_response: str | bytes | bytearray,
) -> list[RedditItemPayload]:
    """Normalize a raw Reddit Atom response into Reddit item payloads."""
    root = _load_atom_document(raw_response)
    payloads: list[RedditItemPayload] = []

    for entry in root.findall("atom:entry", ATOM_NS):
        payload = _payload_from_atom_entry(entry)
        if payload is not None:
            payloads.append(payload)

    return payloads


def _load_atom_document(raw_response: str | bytes | bytearray) -> etree.Element:
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        huge_tree=False,
    )
    if isinstance(raw_response, bytearray):
        document = bytes(raw_response)
    elif isinstance(raw_response, str):
        document = raw_response.encode()
    else:
        document = raw_response
    return etree.fromstring(document, parser=parser)


def _load_json_document(raw_response: str | bytes | bytearray | Any) -> Any:
    if isinstance(raw_response, bytes | bytearray):
        return json.loads(raw_response.decode())
    if isinstance(raw_response, str):
        return json.loads(raw_response)
    return raw_response


def _iter_json_items(document: Any) -> list[JsonItem]:
    """Return raw Reddit post/comment records from supported JSON envelopes.

    Reddit JSON endpoints use the same shape in several places:
    `{"kind": "t3", "data": {...}}` for posts, `{"kind": "t1", "data": {...}}`
    for comments, and `{"kind": "Listing", "data": {"children": [...]}}` for
    paginated collections. Comment trees can also be returned as a top-level
    list where one listing contains the post and another contains comments.

    Each returned tuple is `(kind, data)`: `kind` is Reddit's object kind
    string (`"t3"` for posts or `"t1"` for comments), and `data` is the raw
    dictionary from that object's `data` member. Listing wrappers and unknown
    object kinds are traversal structure only and are not returned.
    """
    if isinstance(document, list):
        return _iter_json_document_list(document)
    if isinstance(document, dict):
        return _iter_json_node(document)
    return []


def _iter_json_document_list(documents: list[Any]) -> list[JsonItem]:
    """Flatten top-level Reddit document lists, such as comment-tree responses."""
    items: list[JsonItem] = []
    for document in documents:
        items.extend(_iter_json_items(document))
    return items


def _iter_json_node(node: dict[str, Any]) -> list[JsonItem]:
    """Dispatch one Reddit JSON object by its `kind` wrapper."""
    kind = _as_str(node.get("kind"))
    data = node.get("data")
    if kind in {"t1", "t3"} and isinstance(data, dict):
        return _iter_json_post_or_comment(kind, data)

    if kind == "Listing" and isinstance(data, dict):
        return _iter_json_listing(data)

    return []


def _iter_json_post_or_comment(kind: str, data: dict[str, Any]) -> list[JsonItem]:
    """Return one post/comment node plus nested comment replies, if present."""
    items: list[JsonItem] = [(kind, data)]
    replies = data.get("replies")
    if isinstance(replies, dict):
        items.extend(_iter_json_node(replies))
    return items


def _iter_json_listing(data: dict[str, Any]) -> list[JsonItem]:
    """Flatten a Reddit Listing object's `data.children` nodes."""
    raw_children = data.get("children", [])
    if not isinstance(raw_children, list):
        return []

    items: list[JsonItem] = []
    for child in raw_children:
        if isinstance(child, dict):
            items.extend(_iter_json_node(child))
    return items


def _payload_from_json_child(
    kind: str,
    data: dict[str, Any],
) -> RedditItemPayload | None:
    """Build a normalized payload from one raw Reddit JSON post/comment record.

    `kind` is the Reddit object kind (`t3` post or `t1` comment). `data` is the
    object payload emitted by Reddit and still uses endpoint-specific field
    names, so this function accepts equivalent fields from listings, search
    results, and comment streams before applying the required local payload
    contract.
    """
    reddit_id = _as_str(data.get("name")) or f"{kind}_{_as_str(data.get('id'))}"
    item_type = _item_type_from_fullname(reddit_id)
    if item_type is None:
        return None

    subreddit = _normalize_subreddit(
        _as_str(data.get("subreddit")) or _as_str(data.get("subreddit_name_prefixed")),
    )
    permalink = _canonical_permalink(
        _as_str(data.get("permalink")) or _as_str(data.get("link_permalink")),
    )
    occurred_at = _timestamp_to_datetime(data.get("created_utc") or data.get("created"))

    if not reddit_id or not subreddit or not permalink or occurred_at is None:
        return None

    return RedditItemPayload(
        reddit_id=reddit_id,
        item_type=item_type,
        subreddit=subreddit,
        permalink=permalink,
        occurred_at=occurred_at,
        author=_as_str(data.get("author")),
        title=_json_title(item_type, data),
        body=_json_body(item_type, data),
    )


def _payload_from_atom_entry(entry: etree.Element) -> RedditItemPayload | None:
    """Build a normalized payload from one Atom `<entry>` node."""
    reddit_id = _entry_text(entry, "atom:id")
    item_type = _item_type_from_fullname(reddit_id)
    if item_type is None:
        return None

    link = entry.find("atom:link", ATOM_NS)
    href = "" if link is None else _as_str(link.get("href"))
    subreddit = _atom_subreddit(entry, href)
    occurred_at = _parse_datetime(
        _entry_text(entry, "atom:published") or _entry_text(entry, "atom:updated"),
    )
    permalink = _canonical_permalink(href)

    if not reddit_id or not subreddit or not permalink or occurred_at is None:
        return None

    author = _entry_text(entry, "atom:author/atom:name").removeprefix("/u/")
    return RedditItemPayload(
        reddit_id=reddit_id,
        item_type=item_type,
        subreddit=subreddit,
        permalink=permalink,
        occurred_at=occurred_at,
        author=author,
        title=_entry_text(entry, "atom:title"),
        body=_atom_body(entry),
    )


def _entry_text(entry: etree.Element, path: str) -> str:
    node = entry.find(path, ATOM_NS)
    return "" if node is None or node.text is None else _collapse_whitespace(node.text)


def _atom_subreddit(entry: etree.Element, href: str) -> str:
    category = entry.find("atom:category", ATOM_NS)
    if category is not None:
        subreddit = _normalize_subreddit(
            _as_str(category.get("term")) or _as_str(category.get("label")),
        )
        if subreddit:
            return subreddit

    match = re.search(r"/r/([^/]+)/", href)
    return _normalize_subreddit(match.group(1) if match else "")


def _atom_body(entry: etree.Element) -> str:
    """Extract entry content while dropping Reddit's appended Atom footer."""
    content = _entry_text(entry, "atom:content")
    if not content:
        return ""

    text = _strip_html(content)
    footer_marker = " submitted by "
    footer_index = text.find(footer_marker)
    return text if footer_index == -1 else text[:footer_index].strip()


def _json_title(item_type: str, data: dict[str, Any]) -> str:
    if item_type == RedditItem.RedditItemType.COMMENT:
        return _collapse_whitespace(_as_str(data.get("link_title")))
    return _collapse_whitespace(_as_str(data.get("title")))


def _json_body(item_type: str, data: dict[str, Any]) -> str:
    if item_type == RedditItem.RedditItemType.COMMENT:
        return _collapse_whitespace(_as_str(data.get("body")))
    return _collapse_whitespace(
        _as_str(data.get("selftext")) or _as_str(data.get("body")),
    )


def _item_type_from_fullname(reddit_id: str) -> str | None:
    """Map Reddit fullname prefixes to local item type constants."""
    if reddit_id.startswith("t3_"):
        return RedditItem.RedditItemType.POST
    if reddit_id.startswith("t1_"):
        return RedditItem.RedditItemType.COMMENT
    return None


def _timestamp_to_datetime(value: Any) -> datetime | None:
    if value is None:
        return None

    try:
        return datetime.fromtimestamp(float(value), tz=UTC)
    except TypeError, ValueError, OSError:
        return None


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _canonical_permalink(value: str) -> str:
    """Return an absolute Reddit URL for absolute, root-relative, or bare paths."""
    if not value:
        return ""
    if value.startswith(("http://", "https://")):
        return value
    if value.startswith("/"):
        return f"{REDDIT_ORIGIN}{value}"
    return f"{REDDIT_ORIGIN}/{value}"


def _normalize_subreddit(value: str) -> str:
    """Return a subreddit name without Reddit path or display prefixes."""
    return value.strip().removeprefix("/r/").removeprefix("r/").strip()


def _strip_html(value: str) -> str:
    """Decode HTML entities and return readable text from Reddit HTML content."""
    parser = _PlainTextHTMLParser()
    parser.feed(unescape(value))
    parser.close()
    return parser.get_text()


def _collapse_whitespace(value: str) -> str:
    """Decode HTML entities and collapse whitespace runs to single spaces."""
    return " ".join(unescape(value).split())


def _as_str(value: Any) -> str:
    """Coerce optional Reddit field values to strings for parser normalization."""
    return "" if value is None else str(value)
