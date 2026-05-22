from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import EmailNotificationPreference
from .models import EmailNotificationSchedule
from .models import NotificationCadence

if TYPE_CHECKING:
    from datetime import datetime

User = get_user_model()


CADENCE_INTERVALS: dict[str, timedelta] = {
    NotificationCadence.TEN_MINUTES: timedelta(minutes=10),
    NotificationCadence.THIRTY_MINUTES: timedelta(minutes=30),
    NotificationCadence.ONE_HOUR: timedelta(hours=1),
    NotificationCadence.DAILY: timedelta(days=1),
}


def ensure_email_notifications_started(*, user: User) -> EmailNotificationPreference:
    """Interface: creates the user's email baseline when a monitor opts into email."""

    now = timezone.now()
    preference, _ = EmailNotificationPreference.objects.get_or_create(user=user)
    if preference.started_at is None:
        preference.started_at = now
        preference.save(update_fields=["started_at", "updated_at"])
    return preference


def ensure_email_notification_schedule(*, user: User, cadence: str) -> EmailNotificationSchedule | None:
    """Interface: creates the due schedule for one periodic monitor cadence."""

    if cadence not in CADENCE_INTERVALS:
        return None

    now = timezone.now()
    schedule, _ = EmailNotificationSchedule.objects.get_or_create(
        user=user,
        cadence=cadence,
        defaults={"next_send_at": next_send_at(cadence, now=now)},
    )
    return schedule


def ensure_email_delivery_state(*, user: User, cadence: str) -> None:
    """Interface: ensures delivery state exists when a monitor cadence enables email."""

    if cadence == NotificationCadence.OFF:
        return

    ensure_email_notifications_started(user=user)
    ensure_email_notification_schedule(user=user, cadence=cadence)


def next_send_at(cadence: str, *, now: datetime) -> datetime:
    """Interface: returns the next due time for a periodic notification cadence."""

    return now + CADENCE_INTERVALS[cadence]
