from __future__ import annotations

from datetime import UTC
from datetime import datetime

import pytest

from chattersift.reddit.clients import RedditClient
from chattersift.reddit.contracts import RedditFeedFormat
from chattersift.reddit.contracts import RedditFeedKind
from chattersift.reddit.contracts import RedditFeedSpec
from chattersift.reddit.contracts import RedditItemPayload
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
    assert second_result.matched_count == 0
    assert Match.objects.count() == 1


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
