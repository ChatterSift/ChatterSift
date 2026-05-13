from __future__ import annotations

from pathlib import Path

import pytest

from chattersift.reddit.models import RedditItem
from chattersift.reddit.parsers import parse_reddit_atom_response
from chattersift.reddit.parsers import parse_reddit_json_response

FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "reddit" / "raw"
FIXTURE_ITEM_LIMIT = 5


def read_fixture(name: str) -> str:
    return (FIXTURE_ROOT / name).read_text()


def test_parse_json_post_listing() -> None:
    payloads = parse_reddit_json_response(
        read_fixture("single_subreddit_django_new.json"),
    )

    assert len(payloads) == FIXTURE_ITEM_LIMIT
    assert all(payload.item_type == RedditItem.RedditItemType.POST for payload in payloads)
    assert payloads[0].reddit_id.startswith("t3_")
    assert payloads[0].subreddit == "django"
    assert payloads[0].permalink.startswith("https://www.reddit.com/r/django/")


def test_parse_json_comment_stream() -> None:
    payloads = parse_reddit_json_response(
        read_fixture("single_subreddit_django_comments.json"),
    )

    assert len(payloads) == FIXTURE_ITEM_LIMIT
    assert all(payload.item_type == RedditItem.RedditItemType.COMMENT for payload in payloads)
    assert all(payload.title for payload in payloads)
    assert all(payload.body for payload in payloads)


def test_parse_json_comment_tree_flattens_post_and_comments() -> None:
    payloads = parse_reddit_json_response(read_fixture("post_comment_tree_django.json"))
    item_types = {payload.item_type for payload in payloads}

    assert RedditItem.RedditItemType.POST in item_types
    assert RedditItem.RedditItemType.COMMENT in item_types


def test_parse_json_comment_search_keeps_returned_post_objects() -> None:
    payloads = parse_reddit_json_response(
        read_fixture("comment_search_sitewide_django.json"),
    )

    assert payloads
    assert all(payload.item_type == RedditItem.RedditItemType.POST for payload in payloads)


@pytest.mark.parametrize(
    ("fixture_name", "item_type"),
    [
        ("single_subreddit_django_new.atom", RedditItem.RedditItemType.POST),
        ("single_subreddit_django_comments.atom", RedditItem.RedditItemType.COMMENT),
        ("keyword_subreddit_django_postgres.atom", RedditItem.RedditItemType.POST),
    ],
)
def test_parse_atom_feeds(fixture_name: str, item_type: str) -> None:
    payloads = parse_reddit_atom_response(read_fixture(fixture_name))

    assert len(payloads) == FIXTURE_ITEM_LIMIT
    assert all(payload.item_type == item_type for payload in payloads)
    assert all(payload.subreddit == "django" for payload in payloads)
    assert all(payload.permalink.startswith("https://www.reddit.com/") for payload in payloads)


def test_parse_atom_does_not_expand_xml_entities() -> None:
    malicious_feed = """\
<?xml version="1.0"?>
<!DOCTYPE feed [
  <!ENTITY unsafe "expanded">
]>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>t3_abc123</id>
    <link href="https://www.reddit.com/r/django/comments/abc123/example/"/>
    <category term="django"/>
    <published>2026-05-06T12:00:00+00:00</published>
    <author>
      <name>/u/example</name>
    </author>
    <title>&unsafe;</title>
  </entry>
</feed>
"""

    payloads = parse_reddit_atom_response(malicious_feed)

    assert len(payloads) == 1
    assert payloads[0].title == ""
