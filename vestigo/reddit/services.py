from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.utils import timezone

from vestigo.tracking.services import match_reddit_items

from .models import RedditItem
from .models import SubredditFetchState

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(frozen=True, kw_only=True)
class RedditItemPayload:
    reddit_id: str
    item_type: str
    subreddit: str
    permalink: str
    occurred_at: datetime
    author: str = ""
    title: str = ""
    body: str = ""


class RedditClient:
    def fetch_subreddit(self, subreddit: str) -> list[RedditItemPayload]:
        msg = "Configure a concrete Reddit client before fetching subreddits."
        raise NotImplementedError(msg)


def fetch_normalize_and_match(subreddit: str, *, client: RedditClient) -> int:
    payloads = client.fetch_subreddit(subreddit)
    items = [_upsert_item(payload) for payload in payloads]

    SubredditFetchState.objects.update_or_create(
        subreddit=subreddit,
        defaults={"last_fetched_at": timezone.now()},
    )

    return match_reddit_items(items)


def _upsert_item(payload: RedditItemPayload) -> RedditItem:
    item, _ = RedditItem.objects.update_or_create(
        reddit_id=payload.reddit_id,
        defaults={
            "item_type": payload.item_type,
            "subreddit": payload.subreddit,
            "author": payload.author,
            "title": payload.title,
            "body": payload.body,
            "permalink": payload.permalink,
            "occurred_at": payload.occurred_at,
        },
    )
    return item
