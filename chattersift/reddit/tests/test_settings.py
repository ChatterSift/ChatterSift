from __future__ import annotations

from django.conf import settings


def test_fetch_due_reddit_feeds_is_scheduled() -> None:
    schedule_entry = settings.CELERY_BEAT_SCHEDULE["fetch-due-reddit-feeds"]

    assert schedule_entry["task"] == "chattersift.reddit.tasks.fetch_due_reddit_feeds"
    assert schedule_entry["schedule"] == settings.CHATTERSIFT_REDDIT_SCHEDULER_INTERVAL_SECONDS
