from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .contracts import RedditFeedFormat
from .contracts import RedditFeedKind
from .contracts import RedditFeedSpec
from .ingestion import fetch_feed_normalize_and_match
from .models import RedditItem

if TYPE_CHECKING:
    from .clients import RedditClient


def fetch_normalize_and_match(subreddit: str, *, client: RedditClient) -> int:
    """Compatibility wrapper for fetching one subreddit post stream.

    New code should call ``fetch_feed_normalize_and_match`` with an explicit
    RedditFeedSpec. This wrapper remains synchronous and delegates through the
    same client interface.
    """
    result = fetch_feed_normalize_and_match(
        RedditFeedSpec(
            kind=RedditFeedKind.POST_STREAM,
            format=RedditFeedFormat.RSS,
            subreddit=subreddit,
        ),
        client=client,
    )
    return result.matched_count


@transaction.atomic
def prune_unmatched_reddit_items(*, retention_days: int | None = None) -> int:
    """Delete fetched Reddit items older than the configured cache window.

    Matched Reddit content remains durable through Match's denormalized title,
    body, permalink, and occurred_at fields. RedditItem is only a bounded recent
    ingestion cache, so expired rows can be removed without changing the
    user-facing match feed or notifications.
    """
    configured_retention_days = (
        settings.CHATTERSIFT_REDDIT_ITEM_RETENTION_DAYS if retention_days is None else retention_days
    )
    if configured_retention_days < 0:
        msg = "retention_days must be greater than or equal to zero."
        raise ValueError(msg)

    cutoff = timezone.now() - timedelta(days=configured_retention_days)
    deleted_count, _ = RedditItem.objects.filter(fetched_at__lt=cutoff).delete()
    return deleted_count
