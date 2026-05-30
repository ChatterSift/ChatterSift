from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from chattersift.alerts.models import NotificationCadence
from chattersift.reddit.contracts import MonitorMatchMode


class Monitor(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    subreddit = models.CharField(max_length=100)
    match_mode = models.CharField(
        max_length=32,
        choices=MonitorMatchMode,
        default=MonitorMatchMode.KEYWORD,
    )
    keyword = models.CharField(max_length=255, blank=True)
    semantic_description = models.TextField(blank=True)
    semantic_fingerprint = models.CharField(max_length=64, blank=True)
    is_active = models.BooleanField(default=True)
    notification_cadence = models.CharField(
        max_length=16,
        choices=NotificationCadence,
        default=NotificationCadence.THIRTY_MINUTES,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["subreddit", "match_mode", "keyword", "semantic_fingerprint"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "subreddit", "match_mode", "keyword", "semantic_fingerprint"],
                name="unique_monitor_per_user_subreddit_mode",
            ),
        ]

    def __str__(self) -> str:
        return _("%(label)s in r/%(subreddit)s") % {
            "label": self.label,
            "subreddit": self.subreddit,
        }

    @property
    def label(self) -> str:
        """Return a compact user-facing monitor label."""
        if self.match_mode == MonitorMatchMode.SEMANTIC:
            return self.semantic_description
        if self.match_mode == MonitorMatchMode.KEYWORD_SEMANTIC:
            return f"{self.keyword} + semantic"
        return self.keyword


class Match(models.Model):
    monitor = models.ForeignKey(Monitor, on_delete=models.CASCADE)
    reddit_item_id = models.CharField(max_length=255)
    match_mode = models.CharField(
        max_length=32,
        choices=MonitorMatchMode,
        default=MonitorMatchMode.KEYWORD,
    )
    confidence = models.FloatField(null=True, blank=True)
    match_reason = models.TextField(blank=True)
    title = models.TextField(blank=True)
    body = models.TextField(blank=True)
    permalink = models.URLField()
    occurred_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["monitor", "reddit_item_id"],
                name="unique_match_per_monitor_reddit_item",
            ),
        ]
        indexes = [
            models.Index(fields=["created_at"], name="tracking_match_created_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.monitor_id}:{self.reddit_item_id}"


class MatchDismissal(models.Model):
    """Records that a user has hidden one Reddit item from their matches feed."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    reddit_item_id = models.CharField(max_length=255)
    dismissed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-dismissed_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "reddit_item_id"],
                name="unique_match_dismissal_per_user_item",
            ),
        ]
        indexes = [
            models.Index(
                fields=["user", "reddit_item_id"],
                name="tracking_dismissal_lookup_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user_id}:{self.reddit_item_id}"


class MatchRetentionPreference(models.Model):
    """Stores one user's matched-item retention window."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    retention_days = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user_id"]

    def __str__(self) -> str:
        return str(self.user_id)
