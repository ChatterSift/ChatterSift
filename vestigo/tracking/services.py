from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import transaction

from .models import Match
from .models import Monitor

if TYPE_CHECKING:
    from collections.abc import Iterable

    from vestigo.reddit.models import RedditItem


@transaction.atomic
def match_reddit_items(items: Iterable[RedditItem]) -> int:
    created_count = 0
    active_monitors = list(Monitor.objects.filter(is_active=True))

    for item in items:
        searchable_text = f"{item.title}\n{item.body}".casefold()
        for monitor in active_monitors:
            if monitor.subreddit.casefold() != item.subreddit.casefold():
                continue
            if monitor.keyword.casefold() not in searchable_text:
                continue

            _, created = Match.objects.get_or_create(
                monitor=monitor,
                reddit_item_id=item.reddit_id,
                defaults={
                    "title": item.title,
                    "body": item.body,
                    "permalink": item.permalink,
                    "occurred_at": item.occurred_at,
                },
            )
            created_count += int(created)

    return created_count
