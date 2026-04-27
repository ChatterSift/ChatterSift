from celery import shared_task

from .services import RedditClient
from .services import fetch_normalize_and_match


@shared_task()
def fetch_subreddit(subreddit: str) -> int:
    return fetch_normalize_and_match(subreddit, client=RedditClient())
