from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import cast

from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Max
from django.utils.html import format_html
from django.utils.html import format_html_join

from chattersift.alerts.models import NotificationCadence
from chattersift.alerts.schedules import ensure_email_delivery_state

from .models import Match
from .models import Monitor

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.utils.safestring import SafeString

    from chattersift.reddit.models import RedditItem

User = get_user_model()


@dataclass(frozen=True)
class DashboardMatch:
    """Presents one Reddit item with all active matched keywords."""

    reddit_item_id: str
    item_type_label: str
    title: str
    body: str
    permalink: str
    occurred_at: object
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class DashboardSubredditGroup:
    """Presents active monitors and recent matches for one subreddit."""

    subreddit: str
    monitors: tuple[Monitor, ...]
    matches: tuple[DashboardMatch, ...]
    notification_cadence: str
    is_paused: bool


@dataclass(frozen=True)
class MatchesFeedItem:
    """Presents one unique Reddit item for the matches feed."""

    subreddit: str
    reddit_item_id: str
    item_type_label: str
    permalink: str
    occurred_at: object
    keywords: tuple[str, ...]
    title_html: SafeString
    body_html: SafeString


@dataclass(frozen=True)
class MatchesFeedResult:
    """Paginated matches feed scoped to one user and optional subreddit."""

    subreddit_options: tuple[str, ...]
    selected_subreddit: str | None
    items: tuple[MatchesFeedItem, ...]
    page: int
    total_pages: int
    has_previous: bool
    has_next: bool


@transaction.atomic
def upsert_keyword_monitors(
    *,
    user: User,
    subreddit: str,
    keywords: Iterable[str],
    cadence: str = NotificationCadence.THIRTY_MINUTES,
) -> list[Monitor]:
    """Creates or reactivates one Monitor row for each keyword."""

    monitors: list[Monitor] = []
    normalized_subreddit = subreddit.casefold()

    for keyword in keywords:
        monitor = (
            Monitor.objects.select_for_update()
            .filter(user=user, subreddit=normalized_subreddit, keyword__iexact=keyword)
            .first()
        )
        if monitor is None:
            monitor = Monitor.objects.create(
                user=user,
                subreddit=normalized_subreddit,
                keyword=keyword,
                notification_cadence=cadence,
            )
            ensure_email_delivery_state(user=user, cadence=cadence)
        elif not monitor.is_active:
            monitor.is_active = True
            monitor.notification_cadence = cadence
            monitor.save(update_fields=["is_active", "notification_cadence", "updated_at"])
            ensure_email_delivery_state(user=user, cadence=cadence)
        monitors.append(monitor)

    return monitors


def add_keyword_to_subreddit(*, user: User, subreddit: str, keyword: str) -> Monitor:
    """Adds a single keyword monitor to an existing subreddit group."""

    normalized = subreddit.casefold()
    monitor = Monitor.objects.filter(user=user, subreddit=normalized, keyword__iexact=keyword).first()
    if monitor is None:
        # Copy cadence from existing monitors in this group
        existing = Monitor.objects.filter(user=user, subreddit=normalized).first()
        cadence = existing.notification_cadence if existing else NotificationCadence.THIRTY_MINUTES
        monitor = Monitor.objects.create(
            user=user,
            subreddit=normalized,
            keyword=keyword,
            notification_cadence=cadence,
        )
        ensure_email_delivery_state(user=user, cadence=cadence)
    elif not monitor.is_active:
        monitor.is_active = True
        monitor.save(update_fields=["is_active", "updated_at"])
    return monitor


def delete_single_monitor(*, user: User, pk: int) -> None:
    """Permanently deletes one monitor and its match history."""

    Monitor.objects.filter(pk=pk, user=user).delete()


def delete_subreddit_group(*, user: User, subreddit: str) -> None:
    """Permanently deletes all monitors for a subreddit."""

    Monitor.objects.filter(user=user, subreddit=subreddit.casefold()).delete()


@transaction.atomic
def toggle_subreddit_group(*, user: User, subreddit: str) -> bool:
    """Pauses or resumes all monitors for a subreddit. Returns new is_active state."""

    normalized = subreddit.casefold()
    monitors = list(
        Monitor.objects.select_for_update().filter(user=user, subreddit=normalized),
    )
    if not monitors:
        return False

    # If any are active, pause all; otherwise resume all
    any_active = any(m.is_active for m in monitors)
    new_state = not any_active
    Monitor.objects.filter(user=user, subreddit=normalized).update(
        is_active=new_state,
    )
    return new_state


@transaction.atomic
def update_group_cadence(*, user: User, subreddit: str, cadence: str) -> None:
    """Sets the notification cadence for all monitors in a subreddit group."""

    Monitor.objects.filter(user=user, subreddit=subreddit.casefold()).update(
        notification_cadence=cadence,
    )
    ensure_email_delivery_state(user=user, cadence=cadence)


def build_dashboard_groups(
    user: User,
    *,
    include_matches: bool = True,
    match_limit_per_subreddit: int = 25,
) -> list[DashboardSubredditGroup]:
    """Returns current-user active monitor groups with aggregate matches."""

    all_monitors = list(Monitor.objects.filter(user=user).order_by("subreddit", "keyword"))
    monitors_by_subreddit: dict[str, list[Monitor]] = {}
    for monitor in all_monitors:
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
            notification_cadence=cast("str", monitors[0].notification_cadence) if monitors else NotificationCadence.OFF,
            is_paused=all(not m.is_active for m in monitors),
        )
        for subreddit, monitors in monitors_by_subreddit.items()
    ]


def build_matches_feed(
    user: User,
    *,
    subreddit: str | None,
    page: int = 1,
    page_size: int = 25,
) -> MatchesFeedResult:
    """Returns paginated unique Reddit matches for current-user active monitors."""

    subreddit_options = tuple(
        Monitor.objects.filter(user=user).order_by("subreddit").values_list("subreddit", flat=True).distinct(),
    )
    selected_subreddit = subreddit if subreddit in subreddit_options else None

    group_rows = Match.objects.filter(monitor__user=user, monitor__is_active=True)
    if selected_subreddit:
        group_rows = group_rows.filter(monitor__subreddit=selected_subreddit)

    grouped = (
        group_rows.values("monitor__subreddit", "reddit_item_id")
        .annotate(
            latest_occurred_at=Max("occurred_at"),
        )
        .order_by("-latest_occurred_at", "monitor__subreddit", "reddit_item_id")
    )

    paginator = Paginator(grouped, page_size)
    page_obj = paginator.get_page(page)
    page_groups = list(page_obj.object_list)

    if not page_groups:
        return MatchesFeedResult(
            subreddit_options=subreddit_options,
            selected_subreddit=selected_subreddit,
            items=(),
            page=page_obj.number,
            total_pages=paginator.num_pages or 1,
            has_previous=page_obj.has_previous(),
            has_next=page_obj.has_next(),
        )

    group_keys = {(row["monitor__subreddit"], row["reddit_item_id"]): row["latest_occurred_at"] for row in page_groups}
    matches = list(
        group_rows.filter(
            monitor__subreddit__in={key[0] for key in group_keys},
            reddit_item_id__in={key[1] for key in group_keys},
        )
        .select_related("monitor")
        .order_by(
            "-occurred_at",
            "monitor__subreddit",
            "reddit_item_id",
            "monitor__keyword",
        ),
    )

    grouped_matches: dict[tuple[str, str], list[Match]] = {key: [] for key in group_keys}
    for match in matches:
        group_key = (match.monitor.subreddit, cast("str", match.reddit_item_id))
        if group_key in grouped_matches:
            grouped_matches[group_key].append(match)

    # Preserve paginator order from grouped query.
    items = tuple(
        _build_matches_feed_item(grouped_matches[(row["monitor__subreddit"], row["reddit_item_id"])])
        for row in page_groups
        if grouped_matches[(row["monitor__subreddit"], row["reddit_item_id"])]
    )

    return MatchesFeedResult(
        subreddit_options=subreddit_options,
        selected_subreddit=selected_subreddit,
        items=items,
        page=page_obj.number,
        total_pages=paginator.num_pages or 1,
        has_previous=page_obj.has_previous(),
        has_next=page_obj.has_next(),
    )


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
    """Returns a user-facing Reddit item type from a fullname."""

    if reddit_item_id.startswith("t1_"):
        return "Comment"
    if reddit_item_id.startswith("t3_"):
        return "Post"
    return "Reddit item"


def _build_matches_feed_item(matches: list[Match]) -> MatchesFeedItem:
    first_match = matches[0]
    keywords = tuple(sorted({str(match.monitor.keyword) for match in matches}, key=str.casefold))
    return MatchesFeedItem(
        subreddit=cast("str", first_match.monitor.subreddit),
        reddit_item_id=cast("str", first_match.reddit_item_id),
        item_type_label=_reddit_item_type_label(cast("str", first_match.reddit_item_id)),
        permalink=cast("str", first_match.permalink),
        occurred_at=first_match.occurred_at,
        keywords=keywords,
        title_html=_highlighted_snippet(cast("str", first_match.title), keywords=keywords, max_length=180),
        body_html=_highlighted_snippet(cast("str", first_match.body), keywords=keywords, max_length=260),
    )


def _highlighted_snippet(text: str, *, keywords: tuple[str, ...], max_length: int) -> SafeString:
    normalized = text.strip()
    if not normalized:
        return format_html("{}", "")

    snippet = _snippet_window(normalized, keywords=keywords, max_length=max_length)
    pattern = _keyword_pattern(keywords)
    if pattern is None:
        return format_html("{}", snippet)

    chunks: list[SafeString] = []
    last_end = 0
    for match in pattern.finditer(snippet):
        chunks.append(format_html("{}", snippet[last_end : match.start()]))
        chunks.append(format_html("<mark>{}</mark>", match.group(0)))
        last_end = match.end()
    chunks.append(format_html("{}", snippet[last_end:]))
    return format_html_join("", "{}", ((chunk,) for chunk in chunks))


def _snippet_window(text: str, *, keywords: tuple[str, ...], max_length: int) -> str:
    if len(text) <= max_length:
        return text

    pattern = _keyword_pattern(keywords)
    if pattern is None:
        return f"{text[: max_length - 1].rstrip()}…"

    matched = pattern.search(text)
    if matched is None:
        return f"{text[: max_length - 1].rstrip()}…"

    match_start = matched.start()
    half = max_length // 2
    start = max(match_start - half, 0)
    end = min(start + max_length, len(text))
    if end - start < max_length:
        start = max(end - max_length, 0)

    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{text[start:end].strip()}{suffix}"


def _keyword_pattern(keywords: tuple[str, ...]) -> re.Pattern[str] | None:
    non_blank_keywords = [keyword.strip() for keyword in keywords if keyword.strip()]
    if not non_blank_keywords:
        return None

    deduped = sorted(set(non_blank_keywords), key=lambda value: (-len(value), value.casefold()))
    return re.compile("|".join(re.escape(keyword) for keyword in deduped), flags=re.IGNORECASE)
