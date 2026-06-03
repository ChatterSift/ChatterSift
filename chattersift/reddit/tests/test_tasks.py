from __future__ import annotations

from chattersift.reddit.clients import RedditClient
from chattersift.reddit.contracts import IngestionResult
from chattersift.reddit.tasks import fetch_due_reddit_feeds
from chattersift.reddit.tasks import fetch_subreddit
from chattersift.reddit.tasks import prune_unmatched_reddit_items

CUSTOM_RETENTION_DAYS = 7
FREE_TEST_LIMIT = 5


class StubClient(RedditClient):
    def fetch_feed(self, spec):  # pragma: no cover
        return []


def test_fetch_due_reddit_feeds_passes_lane_and_limit(monkeypatch) -> None:
    expected = IngestionResult(
        attempted_count=1,
        succeeded_count=1,
        failed_count=0,
        fetched_count=2,
        cached_count=2,
        matched_count=1,
    )

    def fake_fetch_due_feeds(*, limit: int | None = None, lane: str = "default") -> IngestionResult:
        assert limit == FREE_TEST_LIMIT
        assert lane == "free"
        return expected

    monkeypatch.setattr("chattersift.reddit.tasks.fetch_due_feeds", fake_fetch_due_feeds)

    assert fetch_due_reddit_feeds(limit=FREE_TEST_LIMIT, lane="free") == {
        "attempted_count": 1,
        "succeeded_count": 1,
        "failed_count": 0,
        "fetched_count": 2,
        "cached_count": 2,
        "matched_count": 1,
    }


def test_fetch_subreddit_uses_default_client_factory(monkeypatch) -> None:
    expected_result = 3
    calls = {"factory": 0, "service": 0}

    def fake_build_default_reddit_client() -> RedditClient:
        calls["factory"] += 1
        return StubClient()

    def fake_fetch_normalize_and_match(subreddit: str, *, client: RedditClient) -> int:
        calls["service"] += 1
        assert subreddit == "django"
        assert isinstance(client, StubClient)
        return expected_result

    monkeypatch.setattr(
        "chattersift.reddit.tasks.build_default_reddit_client",
        fake_build_default_reddit_client,
    )
    monkeypatch.setattr(
        "chattersift.reddit.tasks.fetch_normalize_and_match",
        fake_fetch_normalize_and_match,
    )

    assert fetch_subreddit("django") == expected_result
    assert calls == {"factory": 1, "service": 1}


def test_prune_unmatched_reddit_items_delegates_to_reddit_item_manager(monkeypatch) -> None:
    expected_result = 4
    calls = {"manager": 0}

    def fake_prune_unmatched_reddit_items(*, retention_days: int | None = None) -> int:
        calls["manager"] += 1
        assert retention_days == CUSTOM_RETENTION_DAYS
        return expected_result

    monkeypatch.setattr(
        "chattersift.reddit.tasks.RedditItem.objects.prune_expired",
        fake_prune_unmatched_reddit_items,
    )

    assert prune_unmatched_reddit_items(retention_days=CUSTOM_RETENTION_DAYS) == expected_result
    assert calls == {"manager": 1}
