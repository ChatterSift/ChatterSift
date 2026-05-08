from __future__ import annotations

from datetime import UTC
from datetime import datetime

import pytest

from chattersift.alerts.services import build_user_match_alerts
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


def _create_match(monitor: Monitor, *, reddit_item_id: str) -> Match:
    return Match.objects.create(
        monitor=monitor,
        reddit_item_id=reddit_item_id,
        title="Django deployment",
        body="Postgres and HTMX notes.",
        permalink="https://www.reddit.com/r/django/comments/shared/example/",
        occurred_at=datetime(2026, 5, 5, tzinfo=UTC),
    )
