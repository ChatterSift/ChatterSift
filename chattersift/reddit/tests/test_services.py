from __future__ import annotations

from datetime import UTC
from datetime import datetime
from datetime import timedelta

import pytest
from django.utils import timezone

from chattersift.reddit.models import RedditItem
from chattersift.tracking.models import Match
from chattersift.tracking.models import Monitor
from chattersift.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db
EXPIRED_REDDIT_ITEM_COUNT = 2


def test_prune_unmatched_reddit_items_deletes_old_cache_rows() -> None:
    old_unmatched = create_reddit_item("t3_old_unmatched")
    old_matched = create_reddit_item("t3_old_matched")
    recent_unmatched = create_reddit_item("t3_recent_unmatched")
    set_fetched_at(old_unmatched, timezone.now() - timedelta(days=15))
    set_fetched_at(old_matched, timezone.now() - timedelta(days=15))
    set_fetched_at(recent_unmatched, timezone.now() - timedelta(days=1))
    monitor = Monitor.objects.create(user=UserFactory(), subreddit="django", keyword="postgres")
    Match.objects.create(
        monitor=monitor,
        reddit_item_id=old_matched.reddit_id,
        title="Persisted match title",
        body="Persisted match body",
        permalink=old_matched.permalink,
        occurred_at=old_matched.occurred_at,
    )

    deleted_count = RedditItem.objects.prune_expired(retention_days=14)

    assert deleted_count == EXPIRED_REDDIT_ITEM_COUNT
    assert not RedditItem.objects.filter(reddit_id=old_unmatched.reddit_id).exists()
    assert not RedditItem.objects.filter(reddit_id=old_matched.reddit_id).exists()
    assert RedditItem.objects.filter(reddit_id=recent_unmatched.reddit_id).exists()
    assert Match.objects.get(reddit_item_id=old_matched.reddit_id).title == "Persisted match title"


def test_prune_unmatched_reddit_items_rejects_negative_retention() -> None:
    with pytest.raises(ValueError, match="retention_days"):
        RedditItem.objects.prune_expired(retention_days=-1)


def create_reddit_item(reddit_id: str) -> RedditItem:
    """Create a deterministic fetched item for prune service tests."""
    return RedditItem.objects.create(
        reddit_id=reddit_id,
        item_type=RedditItem.RedditItemType.POST,
        subreddit="django",
        author="example",
        title=f"{reddit_id} title",
        body=f"{reddit_id} body",
        permalink=f"https://www.reddit.com/r/django/comments/{reddit_id}/example/",
        occurred_at=datetime(2026, 5, 5, tzinfo=UTC),
    )


def set_fetched_at(item: RedditItem, fetched_at: datetime) -> None:
    """Set auto-managed fetched_at values for age-based pruning tests."""
    RedditItem.objects.filter(pk=item.pk).update(fetched_at=fetched_at)
