from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from chattersift.users.tests.factories import UserFactory

User = get_user_model()


@pytest.fixture(autouse=True)
def _media_storage(settings, tmpdir) -> None:
    settings.MEDIA_ROOT = tmpdir.strpath


@pytest.fixture
def user(db) -> User:
    return UserFactory.create()
