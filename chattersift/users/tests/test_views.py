from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse

from chattersift.users.views import UserRedirectView

if TYPE_CHECKING:
    from django.test import RequestFactory

User = get_user_model()

pytestmark = pytest.mark.django_db


class TestUserRedirectView:
    def test_get_redirect_url(self, user: User, rf: RequestFactory):
        view = UserRedirectView()
        request = rf.get("/fake-url")
        request.user = user

        view.request = request
        assert view.get_redirect_url() == reverse(settings.LOGIN_REDIRECT_URL)
