from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING
from typing import cast

from allauth.account.models import EmailAddress
from celery import current_app
from django.conf import settings
from django.db import transaction
from django.db.models import Exists
from django.db.models import OuterRef
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import conditional_escape
from django.utils.safestring import SafeString
from django.utils.safestring import mark_safe

from chattersift.tracking.models import Match

from .models import EmailMatchDelivery
from .models import EmailNotificationPreference
from .models import NotificationCadence

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from chattersift.users.models import User


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


@dataclass(frozen=True, kw_only=True)
class RenderedUserMatchAlert:
    """Interface: display-safe email content for one aggregated Reddit item."""

    user_id: int
    subreddit: str
    reddit_item_id: str
    matched_keywords: tuple[str, ...]
    match_ids: tuple[int, ...]
    monitor_ids: tuple[int, ...]
    title: str
    body: str
    highlighted_title: SafeString
    highlighted_body: SafeString
    permalink: str
    occurred_at: datetime


CADENCE_INTERVALS: dict[str, timedelta] = {
    NotificationCadence.TEN_MINUTES: timedelta(minutes=10),
    NotificationCadence.THIRTY_MINUTES: timedelta(minutes=30),
    NotificationCadence.ONE_HOUR: timedelta(hours=1),
    NotificationCadence.DAILY: timedelta(days=1),
}


def update_email_notification_preference(*, user: User, cadence: str) -> EmailNotificationPreference:
    """Interface: updates the user's cadence while preserving the first opt-in baseline."""

    now = timezone.now()
    preference, _ = EmailNotificationPreference.objects.get_or_create(user=user)
    preference.cadence = cadence
    if cadence != NotificationCadence.OFF and preference.started_at is None:
        preference.started_at = now
    preference.next_send_at = _next_send_at(cadence, now=now)
    preference.save(update_fields=["cadence", "started_at", "next_send_at", "updated_at"])
    return preference


def enqueue_immediate_match_notifications(match_ids: Iterable[int]) -> None:
    """Interface: enqueues one immediate delivery task after the current transaction commits."""

    ids = sorted(set(match_ids))
    if not ids:
        return

    transaction.on_commit(
        lambda: current_app.send_task("chattersift.alerts.tasks.send_immediate_match_notifications", args=[ids]),
    )


def send_immediate_email_digests(match_ids: Iterable[int]) -> int:
    """Send grouped immediate digests for newly created matches from one ingest batch."""

    matches = Match.objects.filter(pk__in=match_ids).select_related("monitor", "monitor__user")
    user_ids = {match.monitor.user_id for match in matches if match.monitor.user_id is not None}
    sent_count = 0
    for preference in _eligible_preferences(user_ids=user_ids, cadences=[NotificationCadence.IMMEDIATE]):
        pending_matches = _pending_matches_for_user(
            preference,
            match_ids=match_ids,
        )
        sent_count += int(_send_preference_digest(preference, pending_matches))
    return sent_count


def send_due_email_digests() -> int:
    """Send due periodic digests and retry any pending immediate notifications."""

    now = timezone.now()
    due_preferences = EmailNotificationPreference.objects.exclude(cadence=NotificationCadence.OFF).filter(
        started_at__isnull=False,
    )
    sent_count = 0
    for preference in due_preferences.select_related("user"):
        if preference.cadence != NotificationCadence.IMMEDIATE and (
            preference.next_send_at is None or preference.next_send_at > now
        ):
            continue

        pending_matches = _pending_matches_for_user(preference)
        sent_count += int(_send_preference_digest(preference, pending_matches, now=now))
        if preference.cadence != NotificationCadence.IMMEDIATE:
            preference.next_send_at = _next_send_at(preference.cadence, now=now)
            preference.save(update_fields=["next_send_at", "updated_at"])
    return sent_count


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


def render_user_match_alerts(alerts: Iterable[UserMatchAlert]) -> list[RenderedUserMatchAlert]:
    """Interface: adds HTML-safe keyword highlighting for email rendering."""

    return [
        RenderedUserMatchAlert(
            user_id=alert.user_id,
            subreddit=alert.subreddit,
            reddit_item_id=alert.reddit_item_id,
            matched_keywords=alert.matched_keywords,
            match_ids=alert.match_ids,
            monitor_ids=alert.monitor_ids,
            title=alert.title,
            body=alert.body,
            highlighted_title=_highlight_keywords(alert.title, alert.matched_keywords),
            highlighted_body=_highlight_keywords(alert.body, alert.matched_keywords),
            permalink=alert.permalink,
            occurred_at=alert.occurred_at,
        )
        for alert in alerts
    ]


def _eligible_preferences(*, user_ids: set[int], cadences: list[str]) -> list[EmailNotificationPreference]:
    return list(
        EmailNotificationPreference.objects.filter(
            user_id__in=user_ids,
            cadence__in=cadences,
            started_at__isnull=False,
        ).select_related("user"),
    )


def _pending_matches_for_user(
    preference: EmailNotificationPreference,
    *,
    match_ids: Iterable[int] | None = None,
):
    delivered_items = EmailMatchDelivery.objects.filter(
        user_id=preference.user_id,
        reddit_item_id=OuterRef("reddit_item_id"),
    )
    matches = Match.objects.filter(
        monitor__user_id=preference.user_id,
        created_at__gte=preference.started_at,
    )
    if match_ids is not None:
        matches = matches.filter(pk__in=match_ids)
    return (
        matches.annotate(already_delivered=Exists(delivered_items))
        .filter(already_delivered=False)
        .select_related("monitor")
    )


def _send_preference_digest(
    preference: EmailNotificationPreference,
    matches,
    *,
    now: datetime | None = None,
) -> bool:
    alerts = build_user_match_alerts(matches)
    if not alerts or not _has_verified_account_email(preference):
        return False

    rendered_alerts = render_user_match_alerts(alerts)
    subject = _digest_subject(len(rendered_alerts))
    body = render_to_string("alerts/emails/match_digest.txt", {"alerts": rendered_alerts})
    html_body = render_to_string("alerts/emails/match_digest.html", {"alerts": rendered_alerts})
    sent_at = now or timezone.now()
    send_signature = current_app.signature(
        "chattersift.alerts.tasks.send_mail",
        kwargs={
            "subject": subject,
            "message": body,
            "from_email": settings.DEFAULT_FROM_EMAIL,
            "recipient_list": [preference.user.email],
            "html_message": html_body,
        },
    )
    delivery_signature = current_app.signature(
        "chattersift.alerts.tasks.record_match_email_delivery",
        kwargs={
            "user_id": preference.user_id,
            "reddit_item_ids": [alert.reddit_item_id for alert in alerts],
            "preference_id": preference.pk,
            "sent_at": sent_at.isoformat(),
        },
    )
    send_signature.apply_async(link=delivery_signature)
    return True


def _has_verified_account_email(preference: EmailNotificationPreference) -> bool:
    return EmailAddress.objects.filter(
        user_id=preference.user_id,
        email=preference.user.email,
        verified=True,
    ).exists()


def _digest_subject(alert_count: int) -> str:
    item_label = "match" if alert_count == 1 else "matches"
    return f"ChatterSift: {alert_count} new Reddit {item_label}"


def _next_send_at(cadence: str, *, now: datetime) -> datetime | None:
    interval = CADENCE_INTERVALS.get(cadence)
    if interval is None:
        return None
    return now + interval


def _highlight_keywords(text: str, keywords: Iterable[str]) -> SafeString:
    if not text:
        return mark_safe("")

    normalized_keywords = sorted(
        {str(keyword) for keyword in keywords if keyword},
        key=_keyword_length,
        reverse=True,
    )
    if not normalized_keywords:
        # Source text is escaped before intentionally returning safe email HTML.
        return mark_safe(conditional_escape(text))  # noqa: S308

    pattern = re.compile("|".join(re.escape(keyword) for keyword in normalized_keywords), flags=re.IGNORECASE)
    highlighted_parts: list[str] = []
    cursor = 0
    for match in pattern.finditer(text):
        highlighted_parts.append(str(conditional_escape(text[cursor : match.start()])))
        highlighted_parts.append(f"<mark>{conditional_escape(match.group(0))}</mark>")
        cursor = match.end()
    highlighted_parts.append(str(conditional_escape(text[cursor:])))
    # All source text is escaped; only the controlled mark tags are introduced here.
    return mark_safe("".join(highlighted_parts))  # noqa: S308


def _keyword_length(keyword: str) -> int:
    return len(keyword)
