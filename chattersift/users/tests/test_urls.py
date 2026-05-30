from __future__ import annotations

import pytest
from django.urls import Resolver404
from django.urls import resolve
from django.urls import reverse
from django.urls.exceptions import NoReverseMatch


def test_cookiecutter_user_routes_are_not_registered(user):
    with pytest.raises(NoReverseMatch):
        reverse("users:detail", kwargs={"pk": user.pk})
    with pytest.raises(NoReverseMatch):
        reverse("users:redirect")
    with pytest.raises(Resolver404):
        resolve(f"/users/{user.pk}/")
    with pytest.raises(Resolver404):
        resolve("/users/~redirect/")
