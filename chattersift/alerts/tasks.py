from __future__ import annotations

from celery import shared_task
from django.core.mail import send_mail as django_send_mail
from django.utils.dateparse import parse_datetime

from .models import EmailMatchDelivery
from .models import EmailNotificationPreference
from .services import send_due_email_digests
from .services import send_immediate_email_digests


@shared_task()
def send_mail(  # noqa: PLR0913
    subject: str,
    message: str,
    from_email: str,
    recipient_list: list[str],
    fail_silently: bool = False,  # noqa: FBT001, FBT002
    auth_user: str | None = None,
    auth_password: str | None = None,
    html_message: str | None = None,
) -> int:
    """Async wrapper around Django's ``send_mail`` helper."""

    return django_send_mail(
        subject=subject,
        message=message,
        from_email=from_email,
        recipient_list=recipient_list,
        fail_silently=fail_silently,
        auth_user=auth_user,
        auth_password=auth_password,
        html_message=html_message,
    )


@shared_task()
def record_match_email_delivery(
    sent_count: int,
    *,
    user_id: int,
    reddit_item_ids: list[str],
    preference_id: int,
    sent_at: str,
) -> None:
    """Finalize match-delivery state after the async mail task succeeds."""

    if not sent_count:
        return

    parsed_sent_at = parse_datetime(sent_at)
    if parsed_sent_at is None:
        return

    EmailMatchDelivery.objects.bulk_create(
        [
            EmailMatchDelivery(
                user_id=user_id,
                reddit_item_id=reddit_item_id,
                sent_at=parsed_sent_at,
            )
            for reddit_item_id in reddit_item_ids
        ],
        ignore_conflicts=True,
    )
    EmailNotificationPreference.objects.filter(pk=preference_id).update(last_sent_at=parsed_sent_at)


@shared_task()
def send_immediate_match_notifications(match_ids: list[int]) -> int:
    """Send immediate email digests for one ingestion batch of new matches."""
    return send_immediate_email_digests(match_ids)


@shared_task()
def send_due_match_notifications() -> int:
    """Send due batched email digests and retry pending immediate work."""
    return send_due_email_digests()
