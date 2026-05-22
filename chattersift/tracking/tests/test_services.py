from __future__ import annotations

from datetime import UTC
from datetime import datetime

import pytest

from chattersift.tracking.models import Match
from chattersift.tracking.models import Monitor
from chattersift.tracking.services import build_dashboard_groups
from chattersift.tracking.services import build_matches_feed
from chattersift.tracking.services import upsert_keyword_monitors
from chattersift.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

EXPECTED_CREATED_MONITOR_COUNT = 2
DEFAULT_MATCHES_PAGE_SIZE = 25
SECOND_PAGE_NUMBER = 2


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


def test_build_matches_feed_returns_user_tracked_subreddit_options(user) -> None:
    other_user = UserFactory()
    Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    Monitor.objects.create(user=user, subreddit="python", keyword="fastapi")
    Monitor.objects.create(user=other_user, subreddit="golang", keyword="gin")

    feed = build_matches_feed(user, subreddit=None)

    assert feed.subreddit_options == ("django", "python")


def test_build_matches_feed_unknown_subreddit_resets_to_all(user) -> None:
    monitor = Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    _create_match(monitor, reddit_item_id="t3_django")

    feed = build_matches_feed(user, subreddit="missing")

    assert feed.selected_subreddit is None
    assert [item.reddit_item_id for item in feed.items] == ["t3_django"]


def test_build_matches_feed_aggregates_duplicate_matches_for_same_item(user) -> None:
    postgres = Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    htmx = Monitor.objects.create(user=user, subreddit="django", keyword="htmx")
    _create_match(postgres, reddit_item_id="t3_shared", title="Postgres + HTMX", body="postgres htmx")
    _create_match(htmx, reddit_item_id="t3_shared", title="Postgres + HTMX", body="postgres htmx")

    feed = build_matches_feed(user, subreddit=None)

    assert len(feed.items) == 1
    assert feed.items[0].keywords == ("htmx", "postgres")


def test_build_matches_feed_orders_items_chronologically(user) -> None:
    monitor = Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    _create_match(monitor, reddit_item_id="t3_older", occurred_at=datetime(2026, 5, 4, tzinfo=UTC))
    _create_match(monitor, reddit_item_id="t3_newer", occurred_at=datetime(2026, 5, 5, tzinfo=UTC))

    feed = build_matches_feed(user, subreddit=None)

    assert [item.reddit_item_id for item in feed.items] == ["t3_newer", "t3_older"]


def test_build_matches_feed_excludes_inactive_monitor_matches(user) -> None:
    active_monitor = Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    inactive_monitor = Monitor.objects.create(user=user, subreddit="django", keyword="htmx", is_active=False)
    _create_match(active_monitor, reddit_item_id="t3_active", body="postgres")
    _create_match(inactive_monitor, reddit_item_id="t3_inactive", body="htmx")

    feed = build_matches_feed(user, subreddit=None)

    assert [item.reddit_item_id for item in feed.items] == ["t3_active"]


def test_build_matches_feed_returns_second_page_with_default_page_size(user) -> None:
    monitor = Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    for index in range(DEFAULT_MATCHES_PAGE_SIZE + 1):
        _create_match(
            monitor,
            reddit_item_id=f"t3_item_{index}",
            occurred_at=datetime(2026, 5, 5, 0, index, tzinfo=UTC),
        )

    first_page = build_matches_feed(user, subreddit=None)
    second_page = build_matches_feed(user, subreddit=None, page=SECOND_PAGE_NUMBER)

    assert len(first_page.items) == DEFAULT_MATCHES_PAGE_SIZE
    assert first_page.has_next
    assert second_page.page == SECOND_PAGE_NUMBER
    assert len(second_page.items) == 1
    assert second_page.has_previous


def test_build_matches_feed_highlights_keywords_case_insensitively(user) -> None:
    monitor = Monitor.objects.create(user=user, subreddit="django", keyword="Postgres")
    _create_match(monitor, reddit_item_id="t3_case", title="POSTGRES tips", body="postgres setup")

    feed = build_matches_feed(user, subreddit=None)

    assert "<mark>POSTGRES</mark>" in str(feed.items[0].title_html)
    assert "<mark>postgres</mark>" in str(feed.items[0].body_html)


def test_build_matches_feed_highlighting_prefers_longer_overlapping_keywords(user) -> None:
    monitor_short = Monitor.objects.create(user=user, subreddit="django", keyword="post")
    monitor_long = Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    _create_match(monitor_short, reddit_item_id="t3_overlap", title="postgres", body="postgres")
    _create_match(monitor_long, reddit_item_id="t3_overlap", title="postgres", body="postgres")

    feed = build_matches_feed(user, subreddit=None)

    assert str(feed.items[0].title_html) == "<mark>postgres</mark>"


def test_build_matches_feed_highlighting_escapes_html(user) -> None:
    monitor = Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    _create_match(monitor, reddit_item_id="t3_escape", title="<script>postgres</script>", body="<b>postgres</b>")

    feed = build_matches_feed(user, subreddit=None)

    assert "&lt;script&gt;<mark>postgres</mark>&lt;/script&gt;" in str(feed.items[0].title_html)
    assert "&lt;b&gt;<mark>postgres</mark>&lt;/b&gt;" in str(feed.items[0].body_html)


def _create_match(
    monitor: Monitor,
    *,
    reddit_item_id: str,
    title: str = "Django thread",
    body: str = "Body mentioning a keyword.",
    occurred_at: datetime | None = None,
) -> Match:
    return Match.objects.create(
        monitor=monitor,
        reddit_item_id=reddit_item_id,
        title=title,
        body=body,
        permalink=f"https://www.reddit.com/r/{monitor.subreddit}/comments/{reddit_item_id}/example/",
        occurred_at=occurred_at or datetime(2026, 5, 5, tzinfo=UTC),
    )
