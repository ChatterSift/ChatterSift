from __future__ import annotations

import logging
from datetime import UTC
from datetime import datetime
from unittest.mock import patch

import pytest

from chattersift.reddit.clients import RedditClient
from chattersift.reddit.contracts import FetchResult
from chattersift.reddit.contracts import MatchDecision
from chattersift.reddit.contracts import MatchRequest
from chattersift.reddit.contracts import MonitorMatchMode
from chattersift.reddit.contracts import RedditFeedFormat
from chattersift.reddit.contracts import RedditFeedKind
from chattersift.reddit.contracts import RedditFeedSpec
from chattersift.reddit.contracts import RedditItemPayload
from chattersift.reddit.ingestion import fetch_due_feeds
from chattersift.reddit.ingestion import fetch_feed_normalize_and_match
from chattersift.reddit.matching import RedditMatcher
from chattersift.reddit.models import RedditItem
from chattersift.reddit.models import SubredditFetchState
from chattersift.tracking.models import Match
from chattersift.tracking.models import Monitor
from chattersift.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db
SEMANTIC_TEST_CONFIDENCE = 0.9


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


class MatchingSemanticMatcher(RedditMatcher):
    """Semantic test matcher that always approves the request."""

    def __init__(self) -> None:
        self.call_count = 0

    def evaluate(self, request: MatchRequest) -> MatchDecision:
        self.call_count += 1
        return MatchDecision(
            monitor_id=request.intent.monitor_id or 0,
            reddit_id=request.item.reddit_id,
            matched=True,
            confidence=SEMANTIC_TEST_CONFIDENCE,
            match_mode=request.intent.match_mode,
            reason="semantic:test_match",
        )


class FailingSemanticMatcher(RedditMatcher):
    """Semantic test matcher that exercises fail-closed ingestion."""

    def evaluate(self, request: MatchRequest) -> MatchDecision:
        msg = "provider unavailable"
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
    assert result.cached_count == 1
    assert result.matched_count == 1
    assert result.skipped_count == 0
    assert result.last_seen_fullname == "t3_postgres"
    assert RedditItem.objects.filter(reddit_id="t3_postgres").exists()
    assert Match.objects.filter(monitor=monitor, reddit_item_id="t3_postgres").exists()

    state = SubredditFetchState.objects.get(query_fingerprint="fingerprint")
    assert state.consecutive_failures == 0
    assert state.last_seen_fullname == "t3_postgres"
    assert state.next_fetch_at is not None


def test_fetch_feed_normalize_and_match_enqueues_new_matches_after_commit(monkeypatch) -> None:
    user = UserFactory()
    Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    payload = RedditItemPayload(
        reddit_id="t3_notify",
        item_type=RedditItem.RedditItemType.POST,
        subreddit="django",
        permalink="https://www.reddit.com/r/django/comments/notify/example/",
        occurred_at=datetime(2026, 5, 5, tzinfo=UTC),
        title="Postgres with Django",
    )
    spec = RedditFeedSpec(
        kind=RedditFeedKind.POST_SEARCH,
        format=RedditFeedFormat.RSS,
        subreddit="django",
        query='"postgres"',
        query_fingerprint="notify",
    )
    called = {"match_ids": []}

    def fake_enqueue(match_ids) -> None:
        called["match_ids"] = list(match_ids)

    monkeypatch.setattr("chattersift.reddit.ingestion.enqueue_immediate_match_notifications", fake_enqueue)

    result = fetch_feed_normalize_and_match(spec, client=FakeRedditClient([payload]))

    assert result.matched_count == 1
    assert len(called["match_ids"]) == 1


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
    assert first_result.cached_count == 1
    assert second_result.cached_count == 0
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
    assert result.cached_count == 1
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

    assert result.cached_count == 1
    assert result.matched_count == 0
    assert RedditItem.objects.filter(reddit_id="t1_context_only").exists()
    assert not Match.objects.filter(reddit_item_id="t1_context_only").exists()


def test_keyword_semantic_persists_semantic_match_metadata() -> None:
    user = UserFactory()
    monitor = Monitor.objects.create(
        user=user,
        subreddit="django",
        match_mode=MonitorMatchMode.KEYWORD_SEMANTIC,
        keyword="postgres",
        semantic_description="database outage reports",
        semantic_fingerprint="semantic",
    )
    payload = RedditItemPayload(
        reddit_id="t3_refined",
        item_type=RedditItem.RedditItemType.POST,
        subreddit="django",
        permalink="https://www.reddit.com/r/django/comments/refined/example/",
        occurred_at=datetime(2026, 5, 5, tzinfo=UTC),
        title="Postgres outage",
        body="A Django deployment hit database problems.",
    )
    spec = RedditFeedSpec(
        kind=RedditFeedKind.POST_SEARCH,
        format=RedditFeedFormat.JSON,
        subreddit="django",
        query='"postgres"',
        query_fingerprint="semantic",
    )

    result = fetch_feed_normalize_and_match(
        spec,
        client=FakeRedditClient([payload]),
        semantic_matcher=MatchingSemanticMatcher(),
    )

    match = Match.objects.get(monitor=monitor, reddit_item_id="t3_refined")
    assert result.matched_count == 1
    assert match.match_mode == MonitorMatchMode.KEYWORD_SEMANTIC
    assert match.confidence == SEMANTIC_TEST_CONFIDENCE
    assert match.match_reason == "semantic:test_match"


def test_keyword_semantic_does_not_re_evaluate_unchanged_cached_items() -> None:
    user = UserFactory()
    Monitor.objects.create(
        user=user,
        subreddit="django",
        match_mode=MonitorMatchMode.KEYWORD_SEMANTIC,
        keyword="postgres",
        semantic_description="database outage reports",
        semantic_fingerprint="semantic",
    )
    payload = RedditItemPayload(
        reddit_id="t3_semantic_cached",
        item_type=RedditItem.RedditItemType.POST,
        subreddit="django",
        permalink="https://www.reddit.com/r/django/comments/semantic-cached/example/",
        occurred_at=datetime(2026, 5, 5, tzinfo=UTC),
        title="Postgres outage",
        body="A Django deployment hit database problems.",
    )
    spec = RedditFeedSpec(
        kind=RedditFeedKind.POST_SEARCH,
        format=RedditFeedFormat.JSON,
        subreddit="django",
        query='"postgres"',
        query_fingerprint="semantic-cached",
    )
    matcher = MatchingSemanticMatcher()
    client = FakeRedditClient([payload])

    first_result = fetch_feed_normalize_and_match(spec, client=client, semantic_matcher=matcher)

    with patch("chattersift.reddit.ingestion.send_mail.delay") as send_mail_delay:
        second_result = fetch_feed_normalize_and_match(spec, client=client, semantic_matcher=matcher)

    assert first_result.matched_count == 1
    assert first_result.cached_count == 1
    assert second_result.matched_count == 0
    assert second_result.cached_count == 0
    assert matcher.call_count == 1
    assert Match.objects.count() == 1
    send_mail_delay.assert_not_called()


def test_keyword_semantic_re_evaluates_changed_cached_items() -> None:
    user = UserFactory()
    Monitor.objects.create(
        user=user,
        subreddit="django",
        match_mode=MonitorMatchMode.KEYWORD_SEMANTIC,
        keyword="postgres",
        semantic_description="database outage reports",
        semantic_fingerprint="semantic",
    )
    RedditItem.objects.create(
        reddit_id="t3_semantic_changed",
        item_type=RedditItem.RedditItemType.POST,
        subreddit="django",
        permalink="https://www.reddit.com/r/django/comments/semantic-changed/example/",
        occurred_at=datetime(2026, 5, 5, tzinfo=UTC),
        title="Original Postgres title",
        body="Original body",
    )
    payload = RedditItemPayload(
        reddit_id="t3_semantic_changed",
        item_type=RedditItem.RedditItemType.POST,
        subreddit="django",
        permalink="https://www.reddit.com/r/django/comments/semantic-changed/example/",
        occurred_at=datetime(2026, 5, 5, tzinfo=UTC),
        title="Updated Postgres outage",
        body="A Django deployment hit database problems.",
    )
    spec = RedditFeedSpec(
        kind=RedditFeedKind.POST_SEARCH,
        format=RedditFeedFormat.JSON,
        subreddit="django",
        query='"postgres"',
        query_fingerprint="semantic-changed",
    )
    matcher = MatchingSemanticMatcher()

    result = fetch_feed_normalize_and_match(
        spec,
        client=FakeRedditClient([payload]),
        semantic_matcher=matcher,
    )

    assert result.cached_count == 1
    assert result.matched_count == 1
    assert matcher.call_count == 1


def test_existing_match_skips_semantic_evaluation_for_monitor_item_pair() -> None:
    user = UserFactory()
    monitor = Monitor.objects.create(
        user=user,
        subreddit="django",
        match_mode=MonitorMatchMode.KEYWORD_SEMANTIC,
        keyword="postgres",
        semantic_description="database outage reports",
        semantic_fingerprint="semantic",
    )
    RedditItem.objects.create(
        reddit_id="t3_existing_semantic",
        item_type=RedditItem.RedditItemType.POST,
        subreddit="django",
        permalink="https://www.reddit.com/r/django/comments/existing-semantic/example/",
        occurred_at=datetime(2026, 5, 5, tzinfo=UTC),
        title="Original Postgres title",
        body="Original body",
    )
    Match.objects.create(
        monitor=monitor,
        reddit_item_id="t3_existing_semantic",
        title="Original Postgres title",
        permalink="https://www.reddit.com/r/django/comments/existing-semantic/example/",
        occurred_at=datetime(2026, 5, 5, tzinfo=UTC),
        match_mode=MonitorMatchMode.KEYWORD_SEMANTIC,
        confidence=SEMANTIC_TEST_CONFIDENCE,
        match_reason="semantic:existing",
    )
    payload = RedditItemPayload(
        reddit_id="t3_existing_semantic",
        item_type=RedditItem.RedditItemType.POST,
        subreddit="django",
        permalink="https://www.reddit.com/r/django/comments/existing-semantic/example/",
        occurred_at=datetime(2026, 5, 5, tzinfo=UTC),
        title="Updated Postgres outage",
        body="A Django deployment hit database problems.",
    )
    spec = RedditFeedSpec(
        kind=RedditFeedKind.POST_SEARCH,
        format=RedditFeedFormat.JSON,
        subreddit="django",
        query='"postgres"',
        query_fingerprint="existing-semantic",
    )
    matcher = MatchingSemanticMatcher()

    result = fetch_feed_normalize_and_match(
        spec,
        client=FakeRedditClient([payload]),
        semantic_matcher=matcher,
    )

    assert result.cached_count == 1
    assert result.matched_count == 0
    assert matcher.call_count == 0
    assert Match.objects.count() == 1


def test_semantic_errors_do_not_fail_feed_and_enqueue_one_admin_email() -> None:
    user = UserFactory()
    Monitor.objects.create(
        user=user,
        subreddit="django",
        match_mode=MonitorMatchMode.SEMANTIC,
        keyword="",
        semantic_description="database outage reports",
        semantic_fingerprint="semantic",
    )
    payload = RedditItemPayload(
        reddit_id="t3_error",
        item_type=RedditItem.RedditItemType.POST,
        subreddit="django",
        permalink="https://www.reddit.com/r/django/comments/error/example/",
        occurred_at=datetime(2026, 5, 5, tzinfo=UTC),
        title="Postgres outage",
    )
    spec = RedditFeedSpec(
        kind=RedditFeedKind.POST_STREAM,
        format=RedditFeedFormat.JSON,
        subreddit="django",
    )

    with patch("chattersift.reddit.ingestion.send_mail.delay") as send_mail_delay:
        result = fetch_feed_normalize_and_match(
            spec,
            client=FakeRedditClient([payload]),
            semantic_matcher=FailingSemanticMatcher(),
        )

    assert result.matched_count == 0
    assert not Match.objects.exists()
    send_mail_delay.assert_called_once()
    assert send_mail_delay.call_args.kwargs["subject"] == "Chattersift semantic matching skipped decisions"
    assert send_mail_delay.call_args.kwargs["from_email"]
    assert send_mail_delay.call_args.kwargs["recipient_list"]
    assert "provider unavailable" in send_mail_delay.call_args.kwargs["message"]


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


def test_fetch_due_feeds_logs_failed_feed_attempts(monkeypatch, caplog) -> None:
    spec = RedditFeedSpec(
        kind=RedditFeedKind.POST_STREAM,
        format=RedditFeedFormat.RSS,
        subreddit="django",
    )

    def fake_get_due_feed_specs(*, limit: int | None = None) -> list[RedditFeedSpec]:
        assert limit is None
        return [spec]

    monkeypatch.setattr("chattersift.reddit.ingestion.get_due_feed_specs", fake_get_due_feed_specs)
    caplog.set_level(logging.WARNING, logger="chattersift.reddit.ingestion")

    result = fetch_due_feeds(client=FailingRedditClient())

    assert result.attempted_count == 1
    assert result.failed_count == 1
    assert "Reddit feed fetch failed" in caplog.text
    assert "kind=post_stream" in caplog.text
    assert "format=rss" in caplog.text
    assert "subreddit=django" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "reddit unavailable" in caplog.text
