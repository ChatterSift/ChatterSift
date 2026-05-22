from __future__ import annotations

from django.conf import settings
from django.db import models


class NotificationCadence(models.TextChoices):
    IMMEDIATE = "immediate", "Immediately"
    TEN_MINUTES = "10m", "Every 10 minutes"
    THIRTY_MINUTES = "30m", "Every 30 minutes"
    ONE_HOUR = "1h", "Every hour"
    DAILY = "daily", "Daily"
    OFF = "off", "Off"


class EmailNotificationPreference(models.Model):
    """Interface: stores one user's email notification delivery baseline."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    started_at = models.DateTimeField(null=True, blank=True)
    last_sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user_id"]

    def __str__(self) -> str:
        return str(self.user_id)


class EmailNotificationSchedule(models.Model):
    """Interface: stores one user's due time for one monitor notification cadence."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    cadence = models.CharField(
        max_length=16,
        choices=NotificationCadence,
    )
    next_send_at = models.DateTimeField(db_index=True)
    last_sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user_id", "cadence"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "cadence"],
                name="unique_email_schedule_per_user_cadence",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user_id}:{self.cadence}"


class EmailMatchDelivery(models.Model):
    """Interface: records one successfully emailed Reddit item for one user."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    reddit_item_id = models.CharField(max_length=255)
    sent_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-sent_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "reddit_item_id"],
                name="unique_email_match_delivery_per_user_item",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user_id}:{self.reddit_item_id}"
