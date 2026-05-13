from __future__ import annotations

import re
from pathlib import Path

import pytest

from chattersift.reddit.clients import RedditClient
from chattersift.reddit.contracts import RedditFeedFormat
from chattersift.reddit.contracts import RedditFeedKind
from chattersift.reddit.contracts import RedditFeedSpec
from chattersift.reddit.contracts import RedditItemPayload
from chattersift.reddit.ingestion import fetch_feed_normalize_and_match
from chattersift.reddit.models import RedditItem
from chattersift.reddit.models import SubredditFetchState
from chattersift.reddit.parsers import parse_reddit_atom_response
from chattersift.reddit.parsers import parse_reddit_json_response
from chattersift.tracking.models import Match
from chattersift.tracking.models import Monitor
from chattersift.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "reddit" / "raw"
EXPECTED_RAW_FIXTURE_NAMES = {
    "comment_search_multi_subreddit_django_python_htmx.json",
    "comment_search_sitewide_django.json",
    "comment_search_subreddit_django_postgres.json",
    "comment_tree_source_permalink.txt",
    "keyword_multi_subreddit_django_python_postgres.atom",
    "keyword_multi_subreddit_django_python_postgres.json",
    "keyword_sitewide_htmx.atom",
    "keyword_sitewide_htmx.json",
    "keyword_subreddit_django_postgres.atom",
    "keyword_subreddit_django_postgres.json",
    "keywords_sitewide_django_htmx_postgres.atom",
    "keywords_sitewide_django_htmx_postgres.json",
    "multi_subreddit_django_python_comments.atom",
    "multi_subreddit_django_python_comments.json",
    "multi_subreddit_django_python_new.atom",
    "multi_subreddit_django_python_new.json",
    "post_comment_tree_django.atom",
    "post_comment_tree_django.json",
    "single_subreddit_django_comments.atom",
    "single_subreddit_django_comments.json",
    "single_subreddit_django_new.atom",
    "single_subreddit_django_new.json",
    "single_subreddit_python_new.atom",
    "single_subreddit_python_new.json",
}
RAW_RESPONSE_FIXTURES = sorted(path for path in FIXTURE_ROOT.iterdir() if path.suffix in {".atom", ".json"})
PAIRED_JSON_RESPONSE_FIXTURES = sorted(
    path for path in FIXTURE_ROOT.glob("*.json") if path.with_suffix(".atom").exists()
)
PAIRED_POST_JSON_RESPONSE_FIXTURES = [
    path
    for path in PAIRED_JSON_RESPONSE_FIXTURES
    if "new" in path.name or path.name.startswith(("keyword_", "keywords_", "post_comment_tree_"))
]
PAIRED_COMMENT_JSON_RESPONSE_FIXTURES = [
    path
    for path in PAIRED_JSON_RESPONSE_FIXTURES
    if "comments" in path.name or path.name.startswith("post_comment_tree_")
]
EXPECTED_JSON_ONLY_IDS_BY_FIXTURE = {
    "keyword_sitewide_htmx.json": {"t3_1t2fsop"},
    "keywords_sitewide_django_htmx_postgres.json": {"t3_1t4vhs9"},
}
COMMENT_TREE_SOURCE_FIXTURE = FIXTURE_ROOT / "comment_tree_source_permalink.txt"
WORD_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_]{3,}")


class FixtureRedditClient(RedditClient):
    """Reddit client adapter that parses one checked-in raw response fixture."""

    def __init__(self, fixture_path: Path) -> None:
        self.fixture_path = fixture_path

    def fetch_feed(self, spec: RedditFeedSpec) -> list[RedditItemPayload]:
        """Return normalized payloads from the configured fixture."""
        return parse_fixture_payloads(self.fixture_path)


def test_reddit_fixture_inventory_is_fully_covered() -> None:
    """Document the raw fixture set covered by ingestion integration tests."""
    fixture_names = {path.name for path in FIXTURE_ROOT.iterdir()}

    assert fixture_names == EXPECTED_RAW_FIXTURE_NAMES
    assert {path.name for path in RAW_RESPONSE_FIXTURES} == {
        name for name in EXPECTED_RAW_FIXTURE_NAMES if name.endswith((".atom", ".json"))
    }


@pytest.mark.parametrize(
    "fixture_path",
    RAW_RESPONSE_FIXTURES,
    ids=lambda fixture_path: fixture_path.name,
)
def test_fetch_feed_normalize_and_match_ingests_raw_fixture(
    fixture_path: Path,
) -> None:
    """Run each raw Reddit response through parser, ingestion, DB, and matching."""
    payloads = parse_fixture_payloads(fixture_path)
    target_payload, keyword = select_match_target(payloads)
    user = UserFactory()
    monitor = Monitor.objects.create(
        user=user,
        subreddit=target_payload.subreddit,
        keyword=keyword,
    )
    spec = build_fixture_spec(fixture_path)

    result = fetch_feed_normalize_and_match(
        spec,
        client=FixtureRedditClient(fixture_path),
    )

    reddit_ids = {payload.reddit_id for payload in payloads}
    assert result.fetched_count == len(payloads)
    assert result.upserted_count == len(payloads)
    assert result.skipped_count == 0
    assert result.last_seen_fullname == payloads[0].reddit_id
    assert RedditItem.objects.filter(reddit_id__in=reddit_ids).count() == len(
        reddit_ids,
    )
    assert RedditItem.objects.filter(
        reddit_id=target_payload.reddit_id,
        item_type=target_payload.item_type,
        subreddit=target_payload.subreddit,
        permalink=target_payload.permalink,
        occurred_at=target_payload.occurred_at,
    ).exists()
    assert result.matched_count >= 1
    assert Match.objects.filter(
        monitor=monitor,
        reddit_item_id=target_payload.reddit_id,
    ).exists()

    state = SubredditFetchState.objects.get(
        kind=spec.kind,
        format=spec.format,
        subreddit=spec.subreddit,
        query_fingerprint=spec.query_fingerprint,
    )
    assert state.consecutive_failures == 0
    assert state.last_error == ""
    assert state.last_seen_fullname == payloads[0].reddit_id
    assert state.last_fetched_at is not None
    assert state.next_fetch_at is not None


def test_fetch_feed_normalize_and_match_is_idempotent_with_raw_fixture() -> None:
    """Re-ingesting the same raw fixture updates items without duplicating matches."""
    fixture_path = FIXTURE_ROOT / "keyword_subreddit_django_postgres.json"
    payloads = parse_fixture_payloads(fixture_path)
    target_payload, keyword = select_match_target(payloads)
    user = UserFactory()
    Monitor.objects.create(
        user=user,
        subreddit=target_payload.subreddit,
        keyword=keyword,
    )
    spec = build_fixture_spec(fixture_path)
    client = FixtureRedditClient(fixture_path)

    first_result = fetch_feed_normalize_and_match(spec, client=client)
    second_result = fetch_feed_normalize_and_match(spec, client=client)

    assert first_result.upserted_count == len(payloads)
    assert second_result.upserted_count == 0
    assert first_result.matched_count >= 1
    assert second_result.matched_count == 0
    assert RedditItem.objects.count() == len(
        {payload.reddit_id for payload in payloads},
    )
    assert Match.objects.count() == first_result.matched_count


@pytest.mark.parametrize(
    "json_fixture_path",
    PAIRED_JSON_RESPONSE_FIXTURES,
    ids=lambda fixture_path: fixture_path.stem,
)
def test_json_and_atom_fixture_ingestion_produce_same_core_items(
    json_fixture_path: Path,
) -> None:
    """Compare persisted core item fields after processing JSON vs Atom fixtures."""
    atom_fixture_path = json_fixture_path.with_suffix(".atom")

    json_snapshot = ingest_fixture_and_snapshot_items(json_fixture_path)
    reset_reddit_ingestion_tables()
    atom_snapshot = ingest_fixture_and_snapshot_items(atom_fixture_path)

    json_ids = set(json_snapshot)
    atom_ids = set(atom_snapshot)
    expected_json_only_ids = EXPECTED_JSON_ONLY_IDS_BY_FIXTURE.get(
        json_fixture_path.name,
        set(),
    )
    common_ids = json_ids & atom_ids

    assert json_ids - atom_ids == expected_json_only_ids
    assert atom_ids - json_ids == set()
    assert common_ids
    for reddit_id in common_ids:
        assert json_snapshot[reddit_id] == atom_snapshot[reddit_id]


@pytest.mark.parametrize(
    ("item_type", "json_fixture_paths"),
    [
        (RedditItem.RedditItemType.POST, PAIRED_POST_JSON_RESPONSE_FIXTURES),
        (RedditItem.RedditItemType.COMMENT, PAIRED_COMMENT_JSON_RESPONSE_FIXTURES),
    ],
    ids=["posts", "comments"],
)
def test_json_and_atom_fixture_ingestion_upserts_same_item_fields_by_type(
    item_type: str,
    json_fixture_paths: list[Path],
) -> None:
    """Verify JSON and Atom fixtures upsert identical post and comment rows."""
    assert json_fixture_paths
    for json_fixture_path in json_fixture_paths:
        reset_reddit_ingestion_tables()
        atom_fixture_path = json_fixture_path.with_suffix(".atom")

        json_snapshot = ingest_fixture_and_snapshot_full_items(
            json_fixture_path,
            item_type=item_type,
        )
        reset_reddit_ingestion_tables()
        atom_snapshot = ingest_fixture_and_snapshot_full_items(
            atom_fixture_path,
            item_type=item_type,
        )

        json_ids = set(json_snapshot)
        atom_ids = set(atom_snapshot)
        expected_json_only_ids = (
            EXPECTED_JSON_ONLY_IDS_BY_FIXTURE.get(
                json_fixture_path.name,
                set(),
            )
            & json_ids
        )
        common_ids = json_ids & atom_ids

        assert json_ids - atom_ids == expected_json_only_ids
        assert atom_ids - json_ids == set()
        assert common_ids, f"{json_fixture_path.name} must include {item_type} rows"
        for reddit_id in common_ids:
            assert json_snapshot[reddit_id] == atom_snapshot[reddit_id]


def test_comment_tree_source_permalink_fixture_matches_tree_payloads() -> None:
    """Use the source permalink fixture to verify both comment-tree responses."""
    source_permalink = COMMENT_TREE_SOURCE_FIXTURE.read_text().strip()

    assert source_permalink
    for fixture_name in (
        "post_comment_tree_django.atom",
        "post_comment_tree_django.json",
    ):
        payloads = parse_fixture_payloads(FIXTURE_ROOT / fixture_name)

        assert any(source_permalink in payload.permalink for payload in payloads)


def ingest_fixture_and_snapshot_items(
    fixture_path: Path,
) -> dict[str, tuple[str, str, str, str, object]]:
    """Ingest one fixture and return persisted fields common to JSON and Atom."""
    payloads = parse_fixture_payloads(fixture_path)
    spec = build_fixture_spec(fixture_path)

    result = fetch_feed_normalize_and_match(
        spec,
        client=FixtureRedditClient(fixture_path),
    )

    assert result.fetched_count == len(payloads)
    assert result.upserted_count == len(payloads)
    return {
        item.reddit_id: (
            item.item_type,
            item.subreddit,
            item.author,
            item.permalink,
            item.occurred_at,
        )
        for item in RedditItem.objects.filter(
            reddit_id__in={payload.reddit_id for payload in payloads},
        )
    }


def ingest_fixture_and_snapshot_full_items(
    fixture_path: Path,
    *,
    item_type: str,
) -> dict[str, tuple[str, str, str, str, str, str, object]]:
    """Ingest one fixture and return all deterministic RedditItem upsert fields."""
    payloads = parse_fixture_payloads(fixture_path)
    spec = build_fixture_spec(fixture_path)

    result = fetch_feed_normalize_and_match(
        spec,
        client=FixtureRedditClient(fixture_path),
    )

    assert result.fetched_count == len(payloads)
    assert result.upserted_count == len(payloads)
    return {
        item.reddit_id: (
            item.item_type,
            item.subreddit,
            item.author,
            item.title,
            item.body,
            item.permalink,
            item.occurred_at,
        )
        for item in RedditItem.objects.filter(
            reddit_id__in={payload.reddit_id for payload in payloads},
            item_type=item_type,
        )
    }


def reset_reddit_ingestion_tables() -> None:
    """Clear ingestion-owned rows so JSON and Atom snapshots are independent."""
    Match.objects.all().delete()
    RedditItem.objects.all().delete()
    SubredditFetchState.objects.all().delete()


def parse_fixture_payloads(fixture_path: Path) -> list[RedditItemPayload]:
    """Parse a raw JSON or Atom fixture into normalized Reddit item payloads."""
    raw_response = fixture_path.read_text()
    if fixture_path.suffix == ".json":
        return parse_reddit_json_response(raw_response)
    if fixture_path.suffix == ".atom":
        return parse_reddit_atom_response(raw_response)

    msg = f"Unsupported Reddit fixture format: {fixture_path.name}"
    raise ValueError(msg)


def select_match_target(
    payloads: list[RedditItemPayload],
) -> tuple[RedditItemPayload, str]:
    """Return a payload and keyword guaranteed to match production keyword text."""
    assert payloads
    for payload in payloads:
        if payload.item_type == RedditItem.RedditItemType.COMMENT:
            searchable_value = payload.body
        else:
            searchable_value = f"{payload.title} {payload.body}"
        keyword = first_searchable_word(searchable_value)
        if keyword:
            return payload, keyword

    msg = "Fixture payloads must include at least one searchable production keyword word."
    raise AssertionError(msg)


def first_searchable_word(value: str) -> str:
    """Return a stable keyword token from normalized Reddit title/body content."""
    match = WORD_PATTERN.search(value)
    return "" if match is None else match.group(0)


def build_fixture_spec(fixture_path: Path) -> RedditFeedSpec:
    """Build a feed spec that gives each raw fixture a stable fetch-state key."""
    kind = infer_feed_kind(fixture_path.name)
    feed_format = RedditFeedFormat.JSON if fixture_path.suffix == ".json" else RedditFeedFormat.RSS
    query = infer_query(fixture_path.name)
    return RedditFeedSpec(
        kind=kind,
        format=feed_format,
        subreddit=infer_spec_subreddit(fixture_path.name),
        query=query,
        query_fingerprint=fixture_path.stem if query else "",
    )


def infer_feed_kind(fixture_name: str) -> RedditFeedKind:
    """Map fixture naming conventions to internal feed kinds."""
    if fixture_name.startswith("comment_search_"):
        return RedditFeedKind.COMMENT_SEARCH
    if "comments" in fixture_name or fixture_name.startswith("post_comment_tree_"):
        return RedditFeedKind.COMMENT_STREAM
    if fixture_name.startswith(("keyword_", "keywords_")):
        return RedditFeedKind.POST_SEARCH
    return RedditFeedKind.POST_STREAM


def infer_query(fixture_name: str) -> str:
    """Return a representative Reddit search query for search fixtures."""
    query_by_name_part = {
        "django_python_htmx": '"htmx"',
        "django_python_postgres": '"postgres"',
        "django_htmx_postgres": '"django" OR "htmx" OR "postgres"',
        "django_postgres": '"postgres"',
        "sitewide_django": '"django"',
        "sitewide_htmx": '"htmx"',
    }
    for name_part, query in query_by_name_part.items():
        if name_part in fixture_name:
            return query

    return ""


def infer_spec_subreddit(fixture_name: str) -> str:
    """Return the feed-state subreddit token represented by a fixture name."""
    if "sitewide" in fixture_name:
        return "all"
    if "multi_subreddit_django_python" in fixture_name:
        return "django+Python"
    if "single_subreddit_python" in fixture_name:
        return "Python"
    return "django"
