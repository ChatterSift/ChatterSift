from __future__ import annotations

from datetime import UTC
from datetime import datetime

import pytest
from django.core import mail

from chattersift.alerts.models import EmailMatchDelivery
from chattersift.alerts.models import EmailNotificationPreference
from chattersift.alerts.models import EmailNotificationSchedule
from chattersift.alerts.models import NotificationCadence
from chattersift.alerts.tasks import record_match_email_delivery
from chattersift.alerts.tasks import send_mail

pytestmark = pytest.mark.django_db


def test_send_mail_wraps_django_send_mail(user) -> None:
    sent_count = send_mail(
        subject="Subject",
        message="Text body",
        from_email="noreply@example.com",
        recipient_list=[user.email],
        html_message="<p>HTML body</p>",
    )

    assert sent_count == 1
    assert len(mail.outbox) == 1


def test_record_match_email_delivery_records_successful_send(user) -> None:
    preference = EmailNotificationPreference.objects.create(
        user=user,
        started_at=datetime(2026, 5, 15, tzinfo=UTC),
    )
    schedule = EmailNotificationSchedule.objects.create(
        user=user,
        cadence=NotificationCadence.TEN_MINUTES,
        next_send_at=datetime(2026, 5, 16, tzinfo=UTC),
    )
    sent_at = datetime(2026, 5, 16, tzinfo=UTC)

    record_match_email_delivery(
        1,
        user_id=user.pk,
        reddit_item_ids=["t3_match"],
        preference_id=preference.pk,
        schedule_id=schedule.pk,
        sent_at=sent_at.isoformat(),
    )

    preference.refresh_from_db()
    schedule.refresh_from_db()
    assert preference.last_sent_at == sent_at
    assert schedule.last_sent_at == sent_at
    assert EmailMatchDelivery.objects.filter(user=user, reddit_item_id="t3_match").exists()
