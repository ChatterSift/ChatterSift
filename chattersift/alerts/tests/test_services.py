from __future__ import annotations

from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import cast

import pytest
from allauth.account.models import EmailAddress
from django.utils import timezone

from chattersift.alerts.models import NotificationCadence
from chattersift.alerts.services import build_user_match_alerts
from chattersift.alerts.services import render_user_match_alerts
from chattersift.alerts.services import send_due_email_digests
from chattersift.alerts.services import send_immediate_email_digests
from chattersift.alerts.services import update_email_notification_preference
from chattersift.tracking.models import Match
from chattersift.tracking.models import Monitor
from chattersift.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

EXPECTED_SEPARATE_ALERT_COUNT = 2


def test_build_user_match_alerts_groups_keywords_for_same_user_and_item() -> None:
    user = UserFactory()
    postgres_monitor = Monitor.objects.create(
        user=user,
        subreddit="django",
        keyword="postgres",
    )
    htmx_monitor = Monitor.objects.create(
        user=user,
        subreddit="Django",
        keyword="htmx",
    )
    postgres_match = _create_match(postgres_monitor, reddit_item_id="t3_shared")
    htmx_match = _create_match(htmx_monitor, reddit_item_id="t3_shared")

    alerts = build_user_match_alerts(
        Match.objects.filter(pk__in=[postgres_match.pk, htmx_match.pk]).select_related(
            "monitor",
        ),
    )

    assert len(alerts) == 1
    assert alerts[0].user_id == user.pk
    assert alerts[0].reddit_item_id == "t3_shared"
    assert alerts[0].matched_keywords == ("htmx", "postgres")
    assert alerts[0].monitor_ids == tuple(
        sorted([postgres_monitor.pk, htmx_monitor.pk]),
    )
    assert alerts[0].match_ids == tuple(sorted([postgres_match.pk, htmx_match.pk]))


def test_build_user_match_alerts_keeps_different_users_separate() -> None:
    first_user = UserFactory()
    second_user = UserFactory()
    first_monitor = Monitor.objects.create(
        user=first_user,
        subreddit="django",
        keyword="postgres",
    )
    second_monitor = Monitor.objects.create(
        user=second_user,
        subreddit="django",
        keyword="htmx",
    )
    _create_match(first_monitor, reddit_item_id="t3_shared")
    _create_match(second_monitor, reddit_item_id="t3_shared")

    alerts = build_user_match_alerts(Match.objects.select_related("monitor"))

    assert len(alerts) == EXPECTED_SEPARATE_ALERT_COUNT
    assert {alert.user_id for alert in alerts} == {first_user.pk, second_user.pk}
    assert {alert.matched_keywords for alert in alerts} == {("postgres",), ("htmx",)}


def test_render_user_match_alerts_highlights_keywords_case_insensitively() -> None:
    user = UserFactory()
    monitor = Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    match = _create_match(monitor, reddit_item_id="t3_highlight")
    alerts = build_user_match_alerts([match])

    rendered_alerts = render_user_match_alerts(alerts)

    assert "<mark>Postgres</mark>" in rendered_alerts[0].highlighted_body


def test_update_preference_sets_first_opt_in_baseline_once(user) -> None:
    first = update_email_notification_preference(user=user, cadence=NotificationCadence.TEN_MINUTES)
    baseline = first.started_at

    update_email_notification_preference(user=user, cadence=NotificationCadence.OFF)
    second = update_email_notification_preference(user=user, cadence=NotificationCadence.THIRTY_MINUTES)

    assert second.started_at == baseline
    assert second.next_send_at is not None


def test_send_immediate_email_digests_queues_new_item_once(monkeypatch, user) -> None:
    _verify_email(user)
    update_email_notification_preference(user=user, cadence=NotificationCadence.IMMEDIATE)
    monitor = Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    match = _create_match(monitor, reddit_item_id="t3_immediate")
    queued_signatures = []
    monkeypatch.setattr("chattersift.alerts.services.current_app.signature", _signature_factory(queued_signatures))

    first_sent = send_immediate_email_digests([match.pk])

    assert first_sent == 1
    assert len(queued_signatures) == 1
    assert queued_signatures[0][0].name == "chattersift.alerts.tasks.send_mail"
    assert "<mark>Postgres</mark>" in queued_signatures[0][0].kwargs["html_message"]
    assert queued_signatures[0][1].name == "chattersift.alerts.tasks.record_match_email_delivery"
    assert queued_signatures[0][1].kwargs["reddit_item_ids"] == ["t3_immediate"]


def test_send_due_email_digests_respects_first_opt_in_baseline(monkeypatch, user) -> None:
    _verify_email(user)
    monitor = Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    historical_match = _create_match(monitor, reddit_item_id="t3_old")
    preference = update_email_notification_preference(user=user, cadence=NotificationCadence.TEN_MINUTES)
    assert preference.started_at is not None
    started_at = cast("datetime", preference.started_at)
    Match.objects.filter(pk=historical_match.pk).update(
        created_at=started_at - timedelta(minutes=1),
    )
    _create_match(monitor, reddit_item_id="t3_new")
    preference.next_send_at = timezone.now() - timedelta(seconds=1)
    preference.save(update_fields=["next_send_at", "updated_at"])
    queued_signatures = []
    monkeypatch.setattr("chattersift.alerts.services.current_app.signature", _signature_factory(queued_signatures))

    sent_count = send_due_email_digests()

    assert sent_count == 1
    assert "t3_old" not in queued_signatures[0][0].kwargs["message"]
    assert "t3_new" in queued_signatures[0][0].kwargs["message"]


def test_off_preference_keeps_pending_matches_for_reenable(monkeypatch, user) -> None:
    _verify_email(user)
    preference = update_email_notification_preference(user=user, cadence=NotificationCadence.TEN_MINUTES)
    monitor = Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    _create_match(monitor, reddit_item_id="t3_pending")
    update_email_notification_preference(user=user, cadence=NotificationCadence.OFF)

    assert send_due_email_digests() == 0

    preference = update_email_notification_preference(user=user, cadence=NotificationCadence.TEN_MINUTES)
    preference.next_send_at = timezone.now() - timedelta(seconds=1)
    preference.save(update_fields=["next_send_at", "updated_at"])
    queued_signatures = []
    monkeypatch.setattr("chattersift.alerts.services.current_app.signature", _signature_factory(queued_signatures))

    assert send_due_email_digests() == 1
    assert queued_signatures[0][1].kwargs["reddit_item_ids"] == ["t3_pending"]


def _create_match(monitor: Monitor, *, reddit_item_id: str) -> Match:
    return Match.objects.create(
        monitor=monitor,
        reddit_item_id=reddit_item_id,
        title="Django deployment",
        body="Postgres and HTMX notes.",
        permalink=f"https://www.reddit.com/r/django/comments/{reddit_item_id}/example/",
        occurred_at=datetime(2026, 5, 5, tzinfo=UTC),
    )


def _verify_email(user) -> None:
    EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)


class FakeSignature:
    def __init__(
        self,
        name: str,
        kwargs: dict,
        queued_signatures: list[tuple[FakeSignature, FakeSignature]],
    ) -> None:
        self.name = name
        self.kwargs = kwargs
        self.queued_signatures = queued_signatures

    def apply_async(self, *, link) -> None:
        self.queued_signatures.append((self, link))


def _signature_factory(queued_signatures: list[tuple[FakeSignature, FakeSignature]]):
    def fake_signature(name: str, *, kwargs: dict) -> FakeSignature:
        return FakeSignature(name, kwargs, queued_signatures)

    return fake_signature
