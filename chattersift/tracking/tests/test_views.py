from __future__ import annotations

from datetime import UTC
from datetime import datetime
from http import HTTPStatus

import pytest
from django.conf import settings
from django.urls import reverse

from chattersift.tracking.models import Match
from chattersift.tracking.models import Monitor
from chattersift.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

EXPECTED_CREATED_MONITOR_COUNT = 2
EXPECTED_MATCH_BADGE_COUNT = 2


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
        {"subreddit": "r/django", "keywords": "postgres\nhtmx"},
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
    assert "Django Postgres deployment" in content
    assert "https://www.reddit.com/r/django/comments/t3_shared/example/" in content
    assert content.count("badge badge-accent badge-outline") == EXPECTED_MATCH_BADGE_COUNT


def test_matches_page_labels_posts_and_comments(client, user) -> None:
    monitor = Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    _create_match(monitor, reddit_item_id="t3_postgres", title="Django Postgres deployment")
    _create_match(monitor, reddit_item_id="t1_postgres", title="", body="Comment about Postgres")
    client.force_login(user)

    response = client.get(reverse("tracking:matches"))

    content = response.content.decode()
    assert '<span class="badge badge-info badge-outline">Post</span>' in content
    assert '<span class="badge badge-info badge-outline">Comment</span>' in content


def test_matches_page_shows_empty_state(client, user) -> None:
    Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    client.force_login(user)

    response = client.get(reverse("tracking:matches"))

    assert "No matches yet" in response.content.decode()


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
