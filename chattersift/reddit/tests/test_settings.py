from __future__ import annotations

from django.conf import settings


def test_fetch_due_reddit_feeds_is_scheduled() -> None:
    schedule_entry = settings.CELERY_BEAT_SCHEDULE["fetch-due-reddit-feeds"]

    assert schedule_entry["task"] == "chattersift.reddit.tasks.fetch_due_reddit_feeds"
    assert schedule_entry["schedule"] == settings.CHATTERSIFT_REDDIT_SCHEDULER_INTERVAL_SECONDS


def test_send_due_match_notifications_is_scheduled() -> None:
    schedule_entry = settings.CELERY_BEAT_SCHEDULE["send-due-match-notifications"]

    assert schedule_entry["task"] == "chattersift.alerts.tasks.send_due_match_notifications"
    assert schedule_entry["schedule"] == settings.CHATTERSIFT_ALERT_DISPATCH_INTERVAL_SECONDS
