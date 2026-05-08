from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import cast

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from chattersift.tracking.models import Match


@dataclass(frozen=True, kw_only=True)
class UserMatchAlert:
    """Aggregated alert payload for one user and one Reddit item.

    Interface:
        Delivery code should use this payload when a user has several monitor
        rows matching the same Reddit item. Match rows stay per monitor for
        persistence, while alert payloads collapse duplicates for display.
    """

    user_id: int
    subreddit: str
    reddit_item_id: str
    matched_keywords: tuple[str, ...]
    match_ids: tuple[int, ...]
    monitor_ids: tuple[int, ...]
    title: str
    body: str
    permalink: str
    occurred_at: datetime


def deliver_match_alert(match: Match) -> None:
    # Public core deliberately keeps delivery minimal; extensions can add channels.
    return None


def build_user_match_alerts(matches: Iterable[Match]) -> list[UserMatchAlert]:
    """Return user/item alert payloads aggregated from per-monitor matches.

    Interface:
        Input matches must have their related Monitor available. Callers with a
        queryset should prefer ``select_related("monitor")`` to avoid per-row
        database lookups. The output groups rows by user, subreddit, and Reddit
        item so delivery can send one alert with all matched keywords.
    """
    grouped_matches: dict[tuple[int, str, str], list[Match]] = {}
    subreddit_labels: dict[tuple[int, str, str], str] = {}

    for match in matches:
        monitor_user_id = cast("int", match.monitor.user_id)
        subreddit = cast("str", match.monitor.subreddit)
        reddit_item_id = cast("str", match.reddit_item_id)
        subreddit_key = subreddit.casefold()
        key = (monitor_user_id, subreddit_key, reddit_item_id)
        if key not in grouped_matches:
            grouped_matches[key] = []
            subreddit_labels[key] = subreddit
        grouped_matches[key].append(match)

    alerts: list[UserMatchAlert] = []
    for key, grouped in grouped_matches.items():
        first_match = grouped[0]
        alerts.append(
            UserMatchAlert(
                user_id=key[0],
                subreddit=subreddit_labels[key],
                reddit_item_id=key[2],
                matched_keywords=_matched_keywords(grouped),
                match_ids=tuple(
                    sorted(match.pk for match in grouped if match.pk is not None),
                ),
                monitor_ids=tuple(sorted(match.monitor_id for match in grouped)),
                title=cast("str", first_match.title),
                body=cast("str", first_match.body),
                permalink=cast("str", first_match.permalink),
                occurred_at=cast("datetime", first_match.occurred_at),
            ),
        )

    return sorted(
        alerts,
        key=lambda alert: (
            alert.user_id,
            alert.subreddit.casefold(),
            alert.reddit_item_id,
        ),
    )


def _matched_keywords(matches: Iterable[Match]) -> tuple[str, ...]:
    """Return display keywords deduplicated case-insensitively."""
    keywords_by_key: dict[str, str] = {}
    for match in matches:
        keyword = match.monitor.keyword
        keywords_by_key.setdefault(keyword.casefold(), keyword)

    return tuple(sorted(keywords_by_key.values(), key=str.casefold))
