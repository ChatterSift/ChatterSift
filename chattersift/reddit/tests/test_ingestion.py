from __future__ import annotations

from datetime import UTC
from datetime import datetime

import pytest

from chattersift.reddit.clients import RedditClient
from chattersift.reddit.contracts import FetchResult
from chattersift.reddit.contracts import RedditFeedFormat
from chattersift.reddit.contracts import RedditFeedKind
from chattersift.reddit.contracts import RedditFeedSpec
from chattersift.reddit.contracts import RedditItemPayload
from chattersift.reddit.ingestion import fetch_due_feeds
from chattersift.reddit.ingestion import fetch_feed_normalize_and_match
from chattersift.reddit.models import RedditItem
from chattersift.reddit.models import SubredditFetchState
from chattersift.tracking.models import Match
from chattersift.tracking.models import Monitor
from chattersift.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


class FakeRedditClient(RedditClient):
    """Sync test client that returns pre-normalized payloads."""

    def __init__(self, payloads: list[RedditItemPayload]) -> None:
        self.payloads = payloads

    def fetch_feed(self, spec: RedditFeedSpec) -> list[RedditItemPayload]:
        return self.payloads


class FailingRedditClient(RedditClient):
    """Sync test client that exercises feed failure state."""

    def fetch_feed(self, spec: RedditFeedSpec) -> list[RedditItemPayload]:
        msg = "reddit unavailable"
        raise RuntimeError(msg)


def test_fetch_feed_normalize_and_match_upserts_and_creates_matches() -> None:
    user = UserFactory()
    monitor = Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    payload = RedditItemPayload(
        reddit_id="t3_postgres",
        item_type=RedditItem.RedditItemType.POST,
        subreddit="django",
        permalink="https://www.reddit.com/r/django/comments/postgres/example/",
        occurred_at=datetime(2026, 5, 5, tzinfo=UTC),
        title="Postgres with Django",
        body="A thread about database tuning.",
    )
    spec = RedditFeedSpec(
        kind=RedditFeedKind.POST_SEARCH,
        format=RedditFeedFormat.RSS,
        subreddit="django",
        query='"postgres"',
        query_fingerprint="fingerprint",
    )

    result = fetch_feed_normalize_and_match(spec, client=FakeRedditClient([payload]))

    assert result.fetched_count == 1
    assert result.upserted_count == 1
    assert result.matched_count == 1
    assert result.skipped_count == 0
    assert result.last_seen_fullname == "t3_postgres"
    assert RedditItem.objects.filter(reddit_id="t3_postgres").exists()
    assert Match.objects.filter(monitor=monitor, reddit_item_id="t3_postgres").exists()

    state = SubredditFetchState.objects.get(query_fingerprint="fingerprint")
    assert state.consecutive_failures == 0
    assert state.last_seen_fullname == "t3_postgres"
    assert state.next_fetch_at is not None


def test_fetch_feed_normalize_and_match_is_idempotent_for_existing_matches() -> None:
    user = UserFactory()
    Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    payload = RedditItemPayload(
        reddit_id="t3_existing",
        item_type=RedditItem.RedditItemType.POST,
        subreddit="django",
        permalink="https://www.reddit.com/r/django/comments/existing/example/",
        occurred_at=datetime(2026, 5, 5, tzinfo=UTC),
        title="Postgres with Django",
    )
    spec = RedditFeedSpec(
        kind=RedditFeedKind.POST_SEARCH,
        format=RedditFeedFormat.RSS,
        subreddit="django",
        query='"postgres"',
        query_fingerprint="existing",
    )
    client = FakeRedditClient([payload])

    first_result = fetch_feed_normalize_and_match(spec, client=client)
    second_result = fetch_feed_normalize_and_match(spec, client=client)

    assert first_result.matched_count == 1
    assert first_result.upserted_count == 1
    assert second_result.upserted_count == 0
    assert second_result.matched_count == 0
    assert Match.objects.count() == 1


def test_fetch_feed_normalize_and_match_counts_changed_existing_items() -> None:
    RedditItem.objects.create(
        reddit_id="t3_changed",
        item_type=RedditItem.RedditItemType.POST,
        subreddit="django",
        permalink="https://www.reddit.com/r/django/comments/changed/example/",
        occurred_at=datetime(2026, 5, 5, tzinfo=UTC),
        title="Original title",
        body="Original body",
    )
    payload = RedditItemPayload(
        reddit_id="t3_changed",
        item_type=RedditItem.RedditItemType.POST,
        subreddit="django",
        permalink="https://www.reddit.com/r/django/comments/changed/example/",
        occurred_at=datetime(2026, 5, 5, tzinfo=UTC),
        title="Updated title",
        body="Original body",
    )
    spec = RedditFeedSpec(
        kind=RedditFeedKind.POST_SEARCH,
        format=RedditFeedFormat.RSS,
        subreddit="django",
        query='"postgres"',
        query_fingerprint="changed",
    )

    result = fetch_feed_normalize_and_match(spec, client=FakeRedditClient([payload]))

    assert result.fetched_count == 1
    assert result.upserted_count == 1
    assert RedditItem.objects.get(reddit_id="t3_changed").title == "Updated title"


def test_fetch_feed_normalize_and_match_does_not_match_comment_context_title() -> None:
    user = UserFactory()
    Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    payload = RedditItemPayload(
        reddit_id="t1_context_only",
        item_type=RedditItem.RedditItemType.COMMENT,
        subreddit="django",
        permalink="https://www.reddit.com/r/django/comments/postgres/example/comment/",
        occurred_at=datetime(2026, 5, 5, tzinfo=UTC),
        title="Postgres with Django",
        body="This comment talks about connection pooling without the tracked keyword.",
    )
    spec = RedditFeedSpec(
        kind=RedditFeedKind.COMMENT_STREAM,
        format=RedditFeedFormat.JSON,
        subreddit="django",
    )

    result = fetch_feed_normalize_and_match(spec, client=FakeRedditClient([payload]))

    assert result.upserted_count == 1
    assert result.matched_count == 0
    assert RedditItem.objects.filter(reddit_id="t1_context_only").exists()
    assert not Match.objects.filter(reddit_item_id="t1_context_only").exists()


def test_fetch_feed_normalize_and_match_records_failure_state() -> None:
    spec = RedditFeedSpec(
        kind=RedditFeedKind.POST_STREAM,
        format=RedditFeedFormat.RSS,
        subreddit="django",
    )

    with pytest.raises(RuntimeError, match="reddit unavailable"):
        fetch_feed_normalize_and_match(spec, client=FailingRedditClient())

    state = SubredditFetchState.objects.get(subreddit="django")
    assert state.consecutive_failures == 1
    assert state.last_error == "reddit unavailable"
    assert state.next_fetch_at is not None


def test_fetch_due_feeds_uses_default_client_factory(monkeypatch, settings) -> None:
    settings.CHATTERSIFT_REDDIT_FEED_FORMAT = "rss"
    user = UserFactory()
    Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    expected_spec = RedditFeedSpec(
        kind=RedditFeedKind.COMMENT_STREAM,
        format=RedditFeedFormat.RSS,
        subreddit="django",
    )
    called = {"factory": 0, "fetch": 0}

    class StubClient(RedditClient):
        def fetch_feed(self, spec: RedditFeedSpec) -> list[RedditItemPayload]:
            called["fetch"] += 1
            assert spec == expected_spec
            return []

    def fake_get_due_feed_specs(*, limit: int | None = None) -> list[RedditFeedSpec]:
        assert limit == 1
        return [expected_spec]

    def fake_build_default_reddit_client() -> RedditClient:
        called["factory"] += 1
        return StubClient()

    def fake_mark_feed_success(feed_spec: RedditFeedSpec, result: FetchResult) -> None:
        assert feed_spec == expected_spec
        assert result.fetched_count == 0

    monkeypatch.setattr("chattersift.reddit.ingestion.get_due_feed_specs", fake_get_due_feed_specs)
    monkeypatch.setattr("chattersift.reddit.ingestion.build_default_reddit_client", fake_build_default_reddit_client)
    monkeypatch.setattr("chattersift.reddit.ingestion.mark_feed_success", fake_mark_feed_success)

    result = fetch_due_feeds(limit=1)

    assert called == {"factory": 1, "fetch": 1}
    assert result.attempted_count == 1
    assert result.succeeded_count == 1
