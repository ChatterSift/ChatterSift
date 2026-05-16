from __future__ import annotations

from http import HTTPStatus

import pytest
from django.conf import settings
from django.urls import reverse

from chattersift.alerts.models import EmailNotificationPreference
from chattersift.alerts.models import NotificationCadence

pytestmark = pytest.mark.django_db


def test_notification_settings_requires_login(client) -> None:
    response = client.get(reverse("alerts:notification_settings"))

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == f"{reverse(settings.LOGIN_URL)}?next=/notifications/"


def test_notification_settings_renders_account_email(client, user) -> None:
    client.force_login(user)

    response = client.get(reverse("alerts:notification_settings"))

    assert response.status_code == HTTPStatus.OK
    assert user.email in response.content.decode()
    assert EmailNotificationPreference.objects.get(user=user).cadence == NotificationCadence.OFF


def test_notification_settings_updates_cadence(client, user) -> None:
    client.force_login(user)

    response = client.post(
        reverse("alerts:notification_settings"),
        {"cadence": NotificationCadence.THIRTY_MINUTES},
    )

    assert response.status_code == HTTPStatus.OK
    preference = EmailNotificationPreference.objects.get(user=user)
    assert preference.cadence == NotificationCadence.THIRTY_MINUTES
    assert preference.started_at is not None
    assert preference.next_send_at is not None
