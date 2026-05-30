from __future__ import annotations

from datetime import UTC
from datetime import datetime
from datetime import timedelta
from http import HTTPStatus

import pytest
from django.conf import settings
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from chattersift.alerts.models import EmailNotificationPreference
from chattersift.alerts.models import EmailNotificationSchedule
from chattersift.alerts.models import NotificationCadence
from chattersift.tracking.models import Match
from chattersift.tracking.models import MatchDismissal
from chattersift.tracking.models import MatchRetentionPreference
from chattersift.tracking.models import Monitor
from chattersift.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

EXPECTED_CREATED_MONITOR_COUNT = 2
EXPECTED_MATCH_KEYWORD_TAGS = 2
DEFAULT_MATCHES_PAGE_SIZE = 25
RETENTION_NINETY_DAYS = 90


def test_dashboard_requires_login(client) -> None:
    response = client.get(reverse("tracking:dashboard"))

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == f"{reverse(settings.LOGIN_URL)}?next=/dash/"


def test_dashboard_route_renders_for_authenticated_user(client, user) -> None:
    client.force_login(user)

    response = client.get(reverse("tracking:dashboard"))

    assert response.status_code == HTTPStatus.OK
    assert "tracking/dashboard.html" in [template.name for template in response.templates]


def test_dashboard_shows_current_user_data_only(client, user) -> None:
    other_user = UserFactory()
    Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    Monitor.objects.create(user=other_user, subreddit="python", keyword="fastapi")
    client.force_login(user)

    response = client.get(reverse("tracking:dashboard"))

    content = response.content.decode()
    assert "r/django" in content
    assert "postgres" in content
    assert "r/python" not in content
    assert "fastapi" not in content


def test_htmx_create_response_creates_monitors_and_returns_dashboard_content(client, user) -> None:
    client.force_login(user)

    response = client.post(
        reverse("tracking:monitor_create"),
        {"subreddit": "r/django", "keywords": "postgres\nhtmx", "cadence": "off"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == HTTPStatus.OK
    assert (
        Monitor.objects.filter(user=user, subreddit="django", is_active=True).count() == EXPECTED_CREATED_MONITOR_COUNT
    )
    content = response.content.decode()
    assert 'id="dashboard-content"' in content
    assert "postgres" in content
    assert "htmx" in content


def test_create_monitor_with_periodic_cadence_creates_email_schedule(client, user) -> None:
    client.force_login(user)

    response = client.post(
        reverse("tracking:monitor_create"),
        {"subreddit": "r/django", "keywords": "postgres", "cadence": NotificationCadence.THIRTY_MINUTES},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == HTTPStatus.OK
    assert EmailNotificationPreference.objects.filter(user=user, started_at__isnull=False).exists()
    assert EmailNotificationSchedule.objects.filter(
        user=user,
        cadence=NotificationCadence.THIRTY_MINUTES,
    ).exists()


def test_htmx_create_response_keeps_form_open_for_validation_errors(client, user) -> None:
    client.force_login(user)

    response = client.post(
        reverse("tracking:monitor_create"),
        {"subreddit": "r/django", "keywords": ","},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == HTTPStatus.OK
    assert not Monitor.objects.filter(user=user).exists()
    content = response.content.decode()
    assert "Enter at least one keyword." in content
    assert "showForm: true" in content


def test_deactivate_is_owner_scoped(client, user) -> None:
    other_user = UserFactory()
    monitor = Monitor.objects.create(user=other_user, subreddit="django", keyword="postgres")
    client.force_login(user)

    response = client.post(reverse("tracking:monitor_deactivate", kwargs={"pk": monitor.pk}))

    assert response.status_code == HTTPStatus.NOT_FOUND
    monitor.refresh_from_db()
    assert monitor.is_active


def test_deactivate_hides_monitor_without_deleting_history(client, user) -> None:
    monitor = Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    _create_match(monitor, reddit_item_id="t3_postgres")
    client.force_login(user)

    response = client.post(reverse("tracking:monitor_deactivate", kwargs={"pk": monitor.pk}))

    assert response.status_code == HTTPStatus.OK
    monitor.refresh_from_db()
    assert not monitor.is_active
    assert Match.objects.filter(monitor=monitor).exists()
    assert reverse("tracking:monitor_deactivate", kwargs={"pk": monitor.pk}) not in response.content.decode()


def test_dashboard_template_contains_htmx_controls(client, user) -> None:
    Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    client.force_login(user)

    response = client.get(reverse("tracking:dashboard"))

    content = response.content.decode()
    assert 'hx-post="/dash/monitors/"' in content
    assert 'hx-indicator="#global-loading"' in content


def test_settings_page_does_not_show_notifications_section(client, user) -> None:
    client.force_login(user)

    response = client.get(reverse("tracking:dashboard_settings"))

    content = response.content.decode()
    assert "Notifications" not in content
    assert "Profile" not in content
    assert "Display name" not in content
    assert "Manage your account." in content


def test_settings_page_requires_login(client) -> None:
    response = client.get(reverse("tracking:dashboard_settings"))

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == f"{reverse(settings.LOGIN_URL)}?next=/dash/settings/"


def test_settings_page_renders_match_retention_control(client, user) -> None:
    client.force_login(user)

    response = client.get(reverse("tracking:dashboard_settings"))

    content = response.content.decode()
    assert "Matched items" in content
    assert 'name="retention_days"' in content
    SimpleTestCase().assertInHTML('<option value="30" selected>30 days</option>', content)


def test_match_retention_htmx_save_updates_preference_and_renders_inline_indicator(client, user) -> None:
    client.force_login(user)

    response = client.post(
        reverse("tracking:match_retention_update"),
        {"retention_days": "90"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == HTTPStatus.OK
    assert MatchRetentionPreference.objects.get(user=user).retention_days == RETENTION_NINETY_DAYS
    content = response.content.decode()
    assert 'hx-indicator="#match-retention-saving"' in content
    assert 'hx-indicator="#global-loading"' not in content
    SimpleTestCase().assertInHTML('<option value="90" selected>90 days</option>', content)


def test_match_retention_save_shows_validation_errors(client, user) -> None:
    client.force_login(user)

    response = client.post(
        reverse("tracking:match_retention_update"),
        {"retention_days": "14"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == HTTPStatus.OK
    assert not MatchRetentionPreference.objects.filter(user=user).exists()
    assert "Select a valid choice" in response.content.decode()


def test_match_retention_save_prunes_current_user_matches_immediately(client, user) -> None:
    other_user = UserFactory()
    user_monitor = Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    other_monitor = Monitor.objects.create(user=other_user, subreddit="django", keyword="postgres")
    user_match = _create_match(user_monitor, reddit_item_id="t3_user_old")
    other_match = _create_match(other_monitor, reddit_item_id="t3_other_old")
    Match.objects.filter(pk__in=[user_match.pk, other_match.pk]).update(created_at=timezone.now() - timedelta(days=31))
    client.force_login(user)

    response = client.post(
        reverse("tracking:match_retention_update"),
        {"retention_days": "7"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == HTTPStatus.OK
    assert not Match.objects.filter(pk=user_match.pk).exists()
    assert Match.objects.filter(pk=other_match.pk).exists()


def test_dashboard_does_not_show_match_content(client, user) -> None:
    monitor = Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    _create_match(monitor, reddit_item_id="t3_shared", title="Django Postgres deployment")
    client.force_login(user)

    response = client.get(reverse("tracking:dashboard"))

    content = response.content.decode()
    assert "Django Postgres deployment" not in content


def test_matches_page_requires_login(client) -> None:
    response = client.get(reverse("tracking:matches"))

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == f"{reverse(settings.LOGIN_URL)}?next=/dash/matches/"


def test_matches_page_shows_matched_content(client, user) -> None:
    postgres = Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    htmx = Monitor.objects.create(user=user, subreddit="django", keyword="htmx")
    _create_match(postgres, reddit_item_id="t3_shared", title="Django Postgres deployment")
    _create_match(htmx, reddit_item_id="t3_shared", title="Django Postgres deployment")
    client.force_login(user)

    response = client.get(reverse("tracking:matches"))

    content = response.content.decode()
    assert "Django <mark>Postgres</mark> deployment" in content
    assert "https://www.reddit.com/r/django/comments/t3_shared/example/" in content
    assert '<span class="cs-match__sub">r/django</span>' in content
    assert content.count('class="cs-match__tag"') == EXPECTED_MATCH_KEYWORD_TAGS


def test_matches_page_labels_posts_and_comments(client, user) -> None:
    monitor = Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    _create_match(monitor, reddit_item_id="t3_postgres", title="Django Postgres deployment")
    _create_match(monitor, reddit_item_id="t1_postgres", title="", body="Comment about Postgres")
    client.force_login(user)

    response = client.get(reverse("tracking:matches"))

    content = response.content.decode()
    assert 'data-type="post">Post</span>' in content
    assert 'data-type="comment">Comment</span>' in content


def test_matches_page_shows_empty_state(client, user) -> None:
    Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    client.force_login(user)

    response = client.get(reverse("tracking:matches"))

    assert "No matches yet" in response.content.decode()


def test_match_dismiss_records_dismissal_and_hides_item(client, user) -> None:
    """POST to match_dismiss persists a MatchDismissal and removes the item from the feed."""
    monitor = Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    _create_match(monitor, reddit_item_id="t3_hideme", title="Django Postgres deployment")
    client.force_login(user)

    response = client.post(reverse("tracking:match_dismiss", kwargs={"reddit_item_id": "t3_hideme"}))

    assert response.status_code == HTTPStatus.OK
    assert MatchDismissal.objects.filter(user=user, reddit_item_id="t3_hideme").exists()

    feed_response = client.get(reverse("tracking:matches"))
    assert "Django <mark>Postgres</mark> deployment" not in feed_response.content.decode()


def test_match_dismiss_requires_login(client) -> None:
    response = client.post(reverse("tracking:match_dismiss", kwargs={"reddit_item_id": "t3_x"}))

    assert response.status_code == HTTPStatus.FOUND


def test_match_dismiss_rejects_get(client, user) -> None:
    client.force_login(user)

    response = client.get(reverse("tracking:match_dismiss", kwargs={"reddit_item_id": "t3_x"}))

    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED


def test_matches_page_renders_subreddit_filter_options(client, user) -> None:
    Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    Monitor.objects.create(user=user, subreddit="python", keyword="asyncio")
    client.force_login(user)

    response = client.get(reverse("tracking:matches"))

    content = response.content.decode()
    assert 'name="subreddit"' in content
    assert "All subreddits" in content
    assert '<option value="django"' in content
    assert '<option value="python"' in content


def test_matches_page_selected_subreddit_filter_is_applied(client, user) -> None:
    django_monitor = Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    python_monitor = Monitor.objects.create(user=user, subreddit="python", keyword="asyncio")
    _create_match(django_monitor, reddit_item_id="t3_django", title="Django Postgres deployment")
    _create_match(python_monitor, reddit_item_id="t3_python", title="Python asyncio news")
    client.force_login(user)

    response = client.get(reverse("tracking:matches"), {"subreddit": "python"})

    content = response.content.decode()
    assert "Python <mark>asyncio</mark> news" in content
    assert "Django <mark>Postgres</mark> deployment" not in content
    SimpleTestCase().assertInHTML('<option value="python" selected>r/python</option>', content)


def test_matches_page_unknown_subreddit_filter_resets_to_all(client, user) -> None:
    monitor = Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    _create_match(monitor, reddit_item_id="t3_django", title="Django Postgres deployment")
    client.force_login(user)

    response = client.get(reverse("tracking:matches"), {"subreddit": "missing"})

    content = response.content.decode()
    assert "Django <mark>Postgres</mark> deployment" in content
    assert '<option value="missing" selected>' not in content


def test_matches_page_pagination_preserves_subreddit_filter(client, user) -> None:
    monitor = Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    for index in range(DEFAULT_MATCHES_PAGE_SIZE + 1):
        _create_match(
            monitor,
            reddit_item_id=f"t3_item_{index}",
            title=f"Django item {index}",
            body="postgres mention",
        )
    client.force_login(user)

    response = client.get(reverse("tracking:matches"), {"subreddit": "django"})

    content = response.content.decode()
    assert "?subreddit=django&amp;page=2" in content


def test_matches_page_htmx_returns_partial(client, user) -> None:
    monitor = Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    _create_match(monitor, reddit_item_id="t3_partial", title="Django Postgres deployment")
    client.force_login(user)

    response = client.get(reverse("tracking:matches"), HTTP_HX_REQUEST="true")

    templates = [template.name for template in response.templates]
    assert response.status_code == HTTPStatus.OK
    assert "tracking/_matches_content.html" in templates
    assert "tracking/matches.html" not in templates


def test_matches_page_no_matches_for_selected_subreddit_state(client, user) -> None:
    django_monitor = Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    Monitor.objects.create(user=user, subreddit="python", keyword="asyncio")
    _create_match(django_monitor, reddit_item_id="t3_django", title="Django Postgres deployment")
    client.force_login(user)

    response = client.get(reverse("tracking:matches"), {"subreddit": "python"})

    assert "No matches for this subreddit" in response.content.decode()


def test_monitor_add_creates_keyword_monitor(client, user) -> None:
    Monitor.objects.create(user=user, subreddit="django", match_mode="keyword", keyword="postgres")
    client.force_login(user)

    response = client.post(
        reverse("tracking:monitor_add", kwargs={"subreddit": "django"}),
        {"match_mode": "keyword", "keyword": "htmx"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == HTTPStatus.OK
    assert Monitor.objects.filter(user=user, subreddit="django", keyword="htmx").exists()


def test_monitor_add_creates_semantic_monitor(client, user, settings) -> None:
    settings.CHATTERSIFT_SEMANTIC_LLM_MODEL = "openai/gpt-4o-mini"
    Monitor.objects.create(user=user, subreddit="django", match_mode="keyword", keyword="postgres")
    client.force_login(user)

    response = client.post(
        reverse("tracking:monitor_add", kwargs={"subreddit": "django"}),
        {"match_mode": "semantic", "semantic_description": "Posts about deployment pain"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == HTTPStatus.OK
    semantic = Monitor.objects.get(user=user, subreddit="django", match_mode="semantic")
    assert semantic.semantic_description == "Posts about deployment pain"


def test_monitor_add_creates_hybrid_monitor(client, user, settings) -> None:
    settings.CHATTERSIFT_SEMANTIC_LLM_MODEL = "openai/gpt-4o-mini"
    Monitor.objects.create(user=user, subreddit="django", match_mode="keyword", keyword="postgres")
    client.force_login(user)

    response = client.post(
        reverse("tracking:monitor_add", kwargs={"subreddit": "django"}),
        {
            "match_mode": "keyword_semantic",
            "keyword": "payments",
            "semantic_description": "Refund complaints",
        },
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == HTTPStatus.OK
    hybrid = Monitor.objects.get(user=user, subreddit="django", match_mode="keyword_semantic")
    assert hybrid.keyword == "payments"
    assert hybrid.semantic_description == "Refund complaints"


def test_monitor_add_shows_inline_error_on_duplicate(client, user) -> None:
    Monitor.objects.create(user=user, subreddit="django", match_mode="keyword", keyword="htmx")
    client.force_login(user)

    response = client.post(
        reverse("tracking:monitor_add", kwargs={"subreddit": "django"}),
        {"match_mode": "keyword", "keyword": "htmx"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == HTTPStatus.OK
    assert Monitor.objects.filter(user=user, subreddit="django", keyword="htmx").count() == 1
    assert "already exists" in response.content.decode()


def test_monitor_edit_renames_keyword(client, user) -> None:
    monitor = Monitor.objects.create(user=user, subreddit="django", match_mode="keyword", keyword="htmx")
    client.force_login(user)

    response = client.post(
        reverse("tracking:monitor_edit", kwargs={"pk": monitor.pk}),
        {"match_mode": "keyword", "keyword": "postgres"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == HTTPStatus.OK
    monitor.refresh_from_db()
    assert monitor.keyword == "postgres"


def test_monitor_edit_updates_semantic_description(client, user, settings) -> None:
    settings.CHATTERSIFT_SEMANTIC_LLM_MODEL = "openai/gpt-4o-mini"
    monitor = Monitor.objects.create(
        user=user,
        subreddit="django",
        match_mode="semantic",
        semantic_description="old prompt",
        semantic_fingerprint="oldfp",
    )
    client.force_login(user)

    response = client.post(
        reverse("tracking:monitor_edit", kwargs={"pk": monitor.pk}),
        {"match_mode": "semantic", "semantic_description": "new prompt about caches"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == HTTPStatus.OK
    monitor.refresh_from_db()
    assert monitor.semantic_description == "new prompt about caches"
    assert monitor.semantic_fingerprint != "oldfp"


def test_monitor_edit_inline_error_on_duplicate_keyword(client, user) -> None:
    Monitor.objects.create(user=user, subreddit="django", match_mode="keyword", keyword="postgres")
    target = Monitor.objects.create(user=user, subreddit="django", match_mode="keyword", keyword="htmx")
    client.force_login(user)

    response = client.post(
        reverse("tracking:monitor_edit", kwargs={"pk": target.pk}),
        {"match_mode": "keyword", "keyword": "postgres"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == HTTPStatus.OK
    target.refresh_from_db()
    assert target.keyword == "htmx"
    assert "already exists" in response.content.decode()


def test_monitor_edit_rejects_other_users_monitor(client, user) -> None:
    other = UserFactory()
    other_monitor = Monitor.objects.create(user=other, subreddit="django", match_mode="keyword", keyword="htmx")
    client.force_login(user)

    response = client.post(
        reverse("tracking:monitor_edit", kwargs={"pk": other_monitor.pk}),
        {"match_mode": "keyword", "keyword": "postgres"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == HTTPStatus.NOT_FOUND
    other_monitor.refresh_from_db()
    assert other_monitor.keyword == "htmx"


def _create_match(
    monitor: Monitor,
    *,
    reddit_item_id: str,
    title: str = "Django thread",
    body: str = "Body mentioning a keyword.",
) -> Match:
    return Match.objects.create(
        monitor=monitor,
        reddit_item_id=reddit_item_id,
        title=title,
        body=body,
        permalink=f"https://www.reddit.com/r/{monitor.subreddit}/comments/{reddit_item_id}/example/",
        occurred_at=datetime(2026, 5, 5, tzinfo=UTC),
    )
