from __future__ import annotations

from datetime import UTC
from datetime import datetime
from datetime import timedelta

import pytest
from django.utils import timezone

from chattersift.alerts.models import EmailMatchDelivery
from chattersift.reddit.models import RedditItem
from chattersift.tracking.models import Match
from chattersift.tracking.models import MatchDismissal
from chattersift.tracking.models import MatchRetentionPreference
from chattersift.tracking.models import Monitor
from chattersift.tracking.services import MonitorAlreadyExistsError
from chattersift.tracking.services import add_monitor_to_subreddit
from chattersift.tracking.services import build_dashboard_groups
from chattersift.tracking.services import build_matches_feed
from chattersift.tracking.services import dismiss_match
from chattersift.tracking.services import get_match_retention_days
from chattersift.tracking.services import prune_expired_matches
from chattersift.tracking.services import prune_expired_matches_for_user
from chattersift.tracking.services import update_match_retention_days
from chattersift.tracking.services import update_monitor
from chattersift.tracking.services import upsert_keyword_monitors
from chattersift.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

EXPECTED_CREATED_MONITOR_COUNT = 2
EXPECTED_SELF_HOST_POLICY_MONITOR_COUNT = 3
DEFAULT_MATCHES_PAGE_SIZE = 25
SECOND_PAGE_NUMBER = 2
DEFAULT_MATCH_RETENTION_DAYS = 30


def test_upsert_keyword_monitors_creates_one_monitor_per_keyword(user) -> None:
    monitors = upsert_keyword_monitors(user=user, subreddit="Django", keywords=["postgres", "htmx"])

    assert [monitor.keyword for monitor in monitors] == ["postgres", "htmx"]
    assert (
        Monitor.objects.filter(user=user, subreddit="django", is_active=True).count() == EXPECTED_CREATED_MONITOR_COUNT
    )


def test_default_monitor_policy_preserves_self_host_monitor_creation(user) -> None:
    monitors = upsert_keyword_monitors(
        user=user,
        subreddit="Django",
        keywords=["postgres", "htmx", "celery"],
        cadence="10m",
    )

    assert len(monitors) == EXPECTED_SELF_HOST_POLICY_MONITOR_COUNT


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


def test_dismiss_match_hides_item_from_feed_across_all_monitors(user) -> None:
    """Dismissing one Reddit item drops it from the feed even if multiple monitors caught it."""
    postgres = Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    htmx = Monitor.objects.create(user=user, subreddit="django", keyword="htmx")
    _create_match(postgres, reddit_item_id="t3_dismissed", body="postgres htmx")
    _create_match(htmx, reddit_item_id="t3_dismissed", body="postgres htmx")
    _create_match(postgres, reddit_item_id="t3_kept", body="postgres only")

    dismiss_match(user=user, reddit_item_id="t3_dismissed")

    feed = build_matches_feed(user, subreddit=None)
    assert [item.reddit_item_id for item in feed.items] == ["t3_kept"]


def test_dismiss_match_is_idempotent(user) -> None:
    monitor = Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    _create_match(monitor, reddit_item_id="t3_dup", body="postgres")

    dismiss_match(user=user, reddit_item_id="t3_dup")
    dismiss_match(user=user, reddit_item_id="t3_dup")

    assert MatchDismissal.objects.filter(user=user, reddit_item_id="t3_dup").count() == 1


def test_dismiss_match_is_scoped_per_user(user) -> None:
    """One user's dismissal must not hide the same item from another user's feed."""
    other_user = UserFactory()
    monitor_a = Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    monitor_b = Monitor.objects.create(user=other_user, subreddit="django", keyword="postgres")
    _create_match(monitor_a, reddit_item_id="t3_shared", body="postgres")
    _create_match(monitor_b, reddit_item_id="t3_shared", body="postgres")

    dismiss_match(user=user, reddit_item_id="t3_shared")

    assert build_matches_feed(user, subreddit=None).items == ()
    assert [item.reddit_item_id for item in build_matches_feed(other_user, subreddit=None).items] == ["t3_shared"]


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


def test_get_match_retention_days_defaults_missing_preference_to_thirty_days(user) -> None:
    assert get_match_retention_days(user) == DEFAULT_MATCH_RETENTION_DAYS


def test_update_match_retention_days_persists_keep_forever(user) -> None:
    preference = update_match_retention_days(user=user, retention_days=None)

    assert preference.retention_days is None
    assert MatchRetentionPreference.objects.get(user=user).retention_days is None


def test_prune_expired_matches_for_user_deletes_by_match_created_at(user) -> None:
    monitor = Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    now = timezone.now()
    old_match = _create_match(monitor, reddit_item_id="t3_old", occurred_at=now)
    fresh_match = _create_match(monitor, reddit_item_id="t3_fresh", occurred_at=now - timedelta(days=365))
    Match.objects.filter(pk=old_match.pk).update(created_at=now - timedelta(days=31))
    Match.objects.filter(pk=fresh_match.pk).update(created_at=now - timedelta(days=29))

    deleted_count = prune_expired_matches_for_user(user=user, now=now)

    assert deleted_count == 1
    assert list(Match.objects.values_list("reddit_item_id", flat=True)) == ["t3_fresh"]


def test_prune_expired_matches_skips_keep_forever(user) -> None:
    monitor = Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    match = _create_match(monitor, reddit_item_id="t3_forever")
    Match.objects.filter(pk=match.pk).update(created_at=timezone.now() - timedelta(days=400))
    MatchRetentionPreference.objects.create(user=user, retention_days=None)

    assert prune_expired_matches_for_user(user=user) == 0
    assert Match.objects.filter(pk=match.pk).exists()


def test_prune_expired_matches_isolates_users(user) -> None:
    other_user = UserFactory()
    user_monitor = Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    other_monitor = Monitor.objects.create(user=other_user, subreddit="django", keyword="postgres")
    now = timezone.now()
    user_match = _create_match(user_monitor, reddit_item_id="t3_user")
    other_match = _create_match(other_monitor, reddit_item_id="t3_other")
    Match.objects.filter(pk__in=[user_match.pk, other_match.pk]).update(created_at=now - timedelta(days=31))

    deleted_count = prune_expired_matches_for_user(user=user, now=now)

    assert deleted_count == 1
    assert Match.objects.filter(pk=other_match.pk).exists()


def test_prune_expired_matches_preserves_related_monitor_reddit_cache_and_email_rows(user) -> None:
    monitor = Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    match = _create_match(monitor, reddit_item_id="t3_old")
    now = timezone.now()
    Match.objects.filter(pk=match.pk).update(created_at=now - timedelta(days=31))
    reddit_item = RedditItem.objects.create(
        reddit_id="t3_old",
        item_type=RedditItem.RedditItemType.POST,
        subreddit="django",
        title="Django thread",
        body="postgres",
        permalink="https://www.reddit.com/r/django/comments/t3_old/example/",
        occurred_at=now,
    )
    delivery = EmailMatchDelivery.objects.create(user=user, reddit_item_id="t3_old", sent_at=now)

    deleted_count = prune_expired_matches_for_user(user=user, now=now)

    assert deleted_count == 1
    assert Monitor.objects.filter(pk=monitor.pk).exists()
    assert RedditItem.objects.filter(pk=reddit_item.pk).exists()
    assert EmailMatchDelivery.objects.filter(pk=delivery.pk).exists()


def test_prune_expired_matches_applies_default_to_users_without_preference(user) -> None:
    monitor = Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    match = _create_match(monitor, reddit_item_id="t3_default")
    now = timezone.now()
    Match.objects.filter(pk=match.pk).update(created_at=now - timedelta(days=31))

    assert prune_expired_matches(now=now) == 1
    assert not Match.objects.filter(pk=match.pk).exists()


def test_add_monitor_to_subreddit_creates_keyword_monitor(user) -> None:
    monitor = add_monitor_to_subreddit(
        user=user,
        subreddit="Django",
        match_mode="keyword",
        keyword="htmx",
    )

    assert monitor.subreddit == "django"
    assert monitor.match_mode == "keyword"
    assert monitor.keyword == "htmx"
    assert monitor.semantic_description == ""
    assert monitor.semantic_fingerprint == ""


def test_add_monitor_to_subreddit_creates_semantic_monitor(user, settings) -> None:
    settings.CHATTERSIFT_SEMANTIC_LLM_MODEL = "openai/gpt-4o-mini"

    monitor = add_monitor_to_subreddit(
        user=user,
        subreddit="django",
        match_mode="semantic",
        semantic_description="Posts about deployment pain",
    )

    assert monitor.match_mode == "semantic"
    assert monitor.keyword == ""
    assert monitor.semantic_description == "Posts about deployment pain"
    assert monitor.semantic_fingerprint != ""


def test_add_monitor_to_subreddit_creates_hybrid_monitor(user) -> None:
    monitor = add_monitor_to_subreddit(
        user=user,
        subreddit="django",
        match_mode="keyword_semantic",
        keyword="payments",
        semantic_description="Refund-related complaints",
    )

    assert monitor.match_mode == "keyword_semantic"
    assert monitor.keyword == "payments"
    assert monitor.semantic_description == "Refund-related complaints"
    assert monitor.semantic_fingerprint != ""


def test_add_monitor_to_subreddit_reactivates_inactive_duplicate(user) -> None:
    existing = Monitor.objects.create(
        user=user,
        subreddit="django",
        match_mode="keyword",
        keyword="htmx",
        is_active=False,
    )

    monitor = add_monitor_to_subreddit(user=user, subreddit="django", match_mode="keyword", keyword="HTMX")

    existing.refresh_from_db()
    assert monitor.pk == existing.pk
    assert existing.is_active


def test_add_monitor_to_subreddit_raises_on_active_duplicate(user) -> None:
    Monitor.objects.create(user=user, subreddit="django", match_mode="keyword", keyword="htmx")

    with pytest.raises(MonitorAlreadyExistsError):
        add_monitor_to_subreddit(user=user, subreddit="django", match_mode="keyword", keyword="htmx")


def test_update_monitor_renames_keyword(user) -> None:
    monitor = Monitor.objects.create(user=user, subreddit="django", match_mode="keyword", keyword="htmx")

    updated = update_monitor(user=user, pk=monitor.pk, match_mode="keyword", keyword="postgres")

    assert updated.pk == monitor.pk
    assert updated.keyword == "postgres"


def test_update_monitor_changes_semantic_description_refingerprints(user) -> None:
    monitor = Monitor.objects.create(
        user=user,
        subreddit="django",
        match_mode="semantic",
        semantic_description="old prompt",
        semantic_fingerprint="oldfp",
    )

    updated = update_monitor(
        user=user,
        pk=monitor.pk,
        match_mode="semantic",
        semantic_description="new prompt about deployments",
    )

    assert updated.semantic_description == "new prompt about deployments"
    assert updated.semantic_fingerprint != "oldfp"
    assert updated.semantic_fingerprint != ""


def test_update_monitor_changes_mode_clears_semantic_fields(user) -> None:
    monitor = Monitor.objects.create(
        user=user,
        subreddit="django",
        match_mode="keyword_semantic",
        keyword="payments",
        semantic_description="refunds",
        semantic_fingerprint="abc",
    )

    updated = update_monitor(user=user, pk=monitor.pk, match_mode="keyword", keyword="payments")

    assert updated.match_mode == "keyword"
    assert updated.keyword == "payments"
    assert updated.semantic_description == ""
    assert updated.semantic_fingerprint == ""


def test_update_monitor_raises_on_duplicate_after_edit(user) -> None:
    Monitor.objects.create(user=user, subreddit="django", match_mode="keyword", keyword="postgres")
    target = Monitor.objects.create(user=user, subreddit="django", match_mode="keyword", keyword="htmx")

    with pytest.raises(MonitorAlreadyExistsError):
        update_monitor(user=user, pk=target.pk, match_mode="keyword", keyword="postgres")

    target.refresh_from_db()
    assert target.keyword == "htmx"


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
