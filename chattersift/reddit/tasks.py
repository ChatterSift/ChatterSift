from __future__ import annotations

from dataclasses import asdict

from celery import shared_task

from .clients import RedditClient
from .ingestion import fetch_due_feeds
from .services import fetch_normalize_and_match


@shared_task()
def fetch_due_reddit_feeds(limit: int | None = None) -> dict:
    """Fetch currently due Reddit feeds through the synchronous core pipeline."""
    return asdict(fetch_due_feeds(limit=limit))


@shared_task()
def fetch_subreddit(subreddit: str) -> int:
    """Compatibility task for the legacy subreddit fetch entrypoint."""
    return fetch_normalize_and_match(subreddit, client=RedditClient())
