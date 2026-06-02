from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db import transaction
from django.utils import timezone

from .contracts import RedditFeedFormat
from .contracts import RedditFeedKind


class SubredditFetchState(models.Model):
    kind = models.CharField(max_length=32, choices=RedditFeedKind)
    format = models.CharField(max_length=16, choices=RedditFeedFormat)
    subreddit = models.CharField(max_length=100)
    query_fingerprint = models.CharField(max_length=64, blank=True)
    last_seen_fullname = models.CharField(max_length=255, blank=True)
    last_fetched_at = models.DateTimeField(null=True, blank=True)
    next_fetch_at = models.DateTimeField(null=True, blank=True, db_index=True)
    consecutive_failures = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["subreddit", "kind", "format", "query_fingerprint"]
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "format", "subreddit", "query_fingerprint"],
                name="unique_reddit_fetch_state_feed",
            ),
        ]
        indexes = [
            models.Index(
                fields=["kind", "format", "subreddit"],
                name="reddit_subr_kind_eb52e6_idx",
            ),
        ]

    def __str__(self) -> str:
        suffix = f":{self.query_fingerprint}" if self.query_fingerprint else ""
        return f"{self.kind}/{self.format}:r/{self.subreddit}{suffix}"


class RedditItemQuerySet(models.QuerySet):
    """Interface: own bounded Reddit item cache pruning."""

    @transaction.atomic
    def prune_expired(self, *, retention_days: int | None = None) -> int:
        """Delete fetched Reddit items older than the configured cache window."""
        configured_retention_days = (
            settings.CHATTERSIFT_REDDIT_ITEM_RETENTION_DAYS if retention_days is None else retention_days
        )
        if configured_retention_days < 0:
            msg = "retention_days must be greater than or equal to zero."
            raise ValueError(msg)

        cutoff = timezone.now() - timedelta(days=configured_retention_days)
        deleted_count, _ = self.filter(fetched_at__lt=cutoff).delete()
        return deleted_count


class RedditItem(models.Model):
    class RedditItemType(models.TextChoices):
        POST = "post", "Post"
        COMMENT = "comment", "Comment"

    reddit_id = models.CharField(max_length=255, unique=True)
    item_type = models.CharField(max_length=20, choices=RedditItemType)
    subreddit = models.CharField(max_length=100)
    author = models.CharField(max_length=255, blank=True)
    title = models.TextField(blank=True)
    body = models.TextField(blank=True)
    permalink = models.URLField()
    occurred_at = models.DateTimeField()
    fetched_at = models.DateTimeField(auto_now_add=True)

    objects = RedditItemQuerySet.as_manager()  # ty: ignore[missing-argument]

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["subreddit", "-occurred_at"]),
        ]

    def __str__(self) -> str:
        return self.reddit_id
