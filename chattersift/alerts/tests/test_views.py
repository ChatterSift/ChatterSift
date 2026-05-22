from __future__ import annotations

from http import HTTPStatus

import pytest
from django.conf import settings
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_notification_settings_requires_login(client) -> None:
    response = client.get(reverse("alerts:notification_settings"))

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == f"{reverse(settings.LOGIN_URL)}?next=/notifications/"


def test_notification_settings_redirects_to_dashboard(client, user) -> None:
    client.force_login(user)

    response = client.get(reverse("alerts:notification_settings"))

    assert response.status_code == HTTPStatus.OK
    content = response.content.decode()
    assert "Go to Settings" in content
    assert reverse("tracking:dashboard_settings") in content


def test_notification_settings_post_renders_legacy_redirect(client, user) -> None:
    client.force_login(user)

    response = client.post(
        reverse("alerts:notification_settings"),
        {},
    )

    assert response.status_code == HTTPStatus.OK
    assert reverse("tracking:dashboard_settings") in response.content.decode()
