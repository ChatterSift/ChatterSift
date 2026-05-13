from __future__ import annotations

from datetime import UTC
from datetime import datetime

import pytest

from chattersift.tracking.models import Match
from chattersift.tracking.models import Monitor
from chattersift.tracking.services import build_dashboard_groups
from chattersift.tracking.services import upsert_keyword_monitors
from chattersift.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

EXPECTED_CREATED_MONITOR_COUNT = 2


def test_upsert_keyword_monitors_creates_one_monitor_per_keyword(user) -> None:
    monitors = upsert_keyword_monitors(user=user, subreddit="Django", keywords=["postgres", "htmx"])

    assert [monitor.keyword for monitor in monitors] == ["postgres", "htmx"]
    assert (
        Monitor.objects.filter(user=user, subreddit="django", is_active=True).count() == EXPECTED_CREATED_MONITOR_COUNT
    )


def test_upsert_keyword_monitors_reactivates_inactive_monitor(user) -> None:
    monitor = Monitor.objects.create(user=user, subreddit="django", keyword="Postgres", is_active=False)

    monitors = upsert_keyword_monitors(user=user, subreddit="django", keywords=["postgres"])

    monitor.refresh_from_db()
    assert monitors == [monitor]
    assert monitor.is_active
    assert Monitor.objects.count() == 1


def test_upsert_keyword_monitors_handles_duplicate_keywords(user) -> None:
    upsert_keyword_monitors(user=user, subreddit="django", keywords=["Postgres", "postgres"])

    assert Monitor.objects.count() == 1
    assert Monitor.objects.get().keyword == "Postgres"


def test_build_dashboard_groups_scopes_monitors_to_user(user) -> None:
    other_user = UserFactory()
    Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    Monitor.objects.create(user=other_user, subreddit="python", keyword="postgres")

    groups = build_dashboard_groups(user)

    assert [group.subreddit for group in groups] == ["django"]


def test_build_dashboard_groups_aggregates_duplicate_matches_for_same_reddit_item(user) -> None:
    postgres = Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    htmx = Monitor.objects.create(user=user, subreddit="django", keyword="htmx")
    occurred_at = datetime(2026, 5, 5, tzinfo=UTC)
    _create_match(postgres, reddit_item_id="t3_shared", title="Django with Postgres", occurred_at=occurred_at)
    _create_match(htmx, reddit_item_id="t3_shared", title="Django with Postgres", occurred_at=occurred_at)

    groups = build_dashboard_groups(user)

    assert len(groups) == 1
    assert len(groups[0].matches) == 1
    assert groups[0].matches[0].keywords == ("htmx", "postgres")


def test_build_dashboard_groups_excludes_inactive_monitor_matches(user) -> None:
    active_monitor = Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    inactive_monitor = Monitor.objects.create(user=user, subreddit="django", keyword="htmx", is_active=False)
    _create_match(active_monitor, reddit_item_id="t3_active")
    _create_match(inactive_monitor, reddit_item_id="t3_inactive")

    groups = build_dashboard_groups(user)

    assert [match.reddit_item_id for match in groups[0].matches] == ["t3_active"]


def _create_match(
    monitor: Monitor,
    *,
    reddit_item_id: str,
    title: str = "Django thread",
    occurred_at: datetime | None = None,
) -> Match:
    return Match.objects.create(
        monitor=monitor,
        reddit_item_id=reddit_item_id,
        title=title,
        body="Body mentioning a keyword.",
        permalink=f"https://www.reddit.com/r/{monitor.subreddit}/comments/{reddit_item_id}/example/",
        occurred_at=occurred_at or datetime(2026, 5, 5, tzinfo=UTC),
    )
