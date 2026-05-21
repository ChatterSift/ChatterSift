from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import cast

from django.db import transaction

from .models import Match
from .models import Monitor

if TYPE_CHECKING:
    from collections.abc import Iterable

    from chattersift.reddit.models import RedditItem
    from chattersift.users.models import User


@dataclass(frozen=True)
class DashboardMatch:
    """Interface: presents one Reddit item with all active matched keywords."""

    reddit_item_id: str
    item_type_label: str
    title: str
    body: str
    permalink: str
    occurred_at: object
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class DashboardSubredditGroup:
    """Interface: presents active monitors and recent matches for one subreddit."""

    subreddit: str
    monitors: tuple[Monitor, ...]
    matches: tuple[DashboardMatch, ...]


@transaction.atomic
def upsert_keyword_monitors(*, user: User, subreddit: str, keywords: Iterable[str]) -> list[Monitor]:
    """Interface: creates or reactivates one Monitor row for each keyword."""

    monitors: list[Monitor] = []
    normalized_subreddit = subreddit.casefold()

    for keyword in keywords:
        monitor = (
            Monitor.objects.select_for_update()
            .filter(user=user, subreddit=normalized_subreddit, keyword__iexact=keyword)
            .first()
        )
        if monitor is None:
            monitor = Monitor.objects.create(user=user, subreddit=normalized_subreddit, keyword=keyword)
        elif not monitor.is_active:
            monitor.is_active = True
            monitor.save(update_fields=["is_active", "updated_at"])
        monitors.append(monitor)

    return monitors


def build_dashboard_groups(
    user: User,
    *,
    include_matches: bool = True,
    match_limit_per_subreddit: int = 25,
) -> list[DashboardSubredditGroup]:
    """Interface: returns current-user active monitor groups with aggregate matches."""

    active_monitors = list(Monitor.objects.filter(user=user, is_active=True).order_by("subreddit", "keyword"))
    monitors_by_subreddit: dict[str, list[Monitor]] = {}
    for monitor in active_monitors:
        monitors_by_subreddit.setdefault(monitor.subreddit, []).append(monitor)

    if include_matches:
        matches_by_subreddit = _build_dashboard_matches_by_subreddit(
            user=user,
            subreddits=monitors_by_subreddit.keys(),
            match_limit_per_subreddit=match_limit_per_subreddit,
        )
    else:
        matches_by_subreddit = {}

    return [
        DashboardSubredditGroup(
            subreddit=subreddit,
            monitors=tuple(monitors),
            matches=tuple(matches_by_subreddit.get(subreddit, [])),
        )
        for subreddit, monitors in monitors_by_subreddit.items()
    ]


@transaction.atomic
def match_reddit_items(items: Iterable[RedditItem]) -> int:
    created_count = 0
    active_monitors = list(Monitor.objects.filter(is_active=True))

    for item in items:
        searchable_text = _keyword_searchable_text(item)
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


def _keyword_searchable_text(item: RedditItem) -> str:
    if item.item_type == "comment":
        return item.body.casefold()
    return f"{item.title}\n{item.body}".casefold()


def _build_dashboard_matches_by_subreddit(
    *,
    user: User,
    subreddits: Iterable[str],
    match_limit_per_subreddit: int,
) -> dict[str, list[DashboardMatch]]:
    subreddit_set = set(subreddits)
    if not subreddit_set:
        return {}

    matches = (
        Match.objects.filter(
            monitor__user=user,
            monitor__is_active=True,
            monitor__subreddit__in=subreddit_set,
        )
        .select_related("monitor")
        .order_by("monitor__subreddit", "-occurred_at", "reddit_item_id", "monitor__keyword")
    )
    grouped_matches: dict[str, dict[str, list[Match]]] = {subreddit: {} for subreddit in subreddit_set}

    for match in matches:
        subreddit = match.monitor.subreddit
        item_groups = grouped_matches[subreddit]
        if match.reddit_item_id not in item_groups and len(item_groups) >= match_limit_per_subreddit:
            continue
        item_groups.setdefault(match.reddit_item_id, []).append(match)

    return {
        subreddit: [_build_dashboard_match(item_matches) for item_matches in item_groups.values()]
        for subreddit, item_groups in grouped_matches.items()
    }


def _build_dashboard_match(matches: list[Match]) -> DashboardMatch:
    first_match = matches[0]
    keywords = tuple(sorted({str(match.monitor.keyword) for match in matches}, key=str.casefold))
    return DashboardMatch(
        reddit_item_id=cast("str", first_match.reddit_item_id),
        item_type_label=_reddit_item_type_label(cast("str", first_match.reddit_item_id)),
        title=cast("str", first_match.title),
        body=cast("str", first_match.body),
        permalink=cast("str", first_match.permalink),
        occurred_at=first_match.occurred_at,
        keywords=keywords,
    )


def _reddit_item_type_label(reddit_item_id: str) -> str:
    """Interface: returns a user-facing Reddit item type from a fullname."""

    if reddit_item_id.startswith("t1_"):
        return "Comment"
    if reddit_item_id.startswith("t3_"):
        return "Post"
    return "Reddit item"
