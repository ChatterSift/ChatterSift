from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

if TYPE_CHECKING:
    from django.http import HttpRequest
    from django.http import HttpResponse


@login_required
@require_http_methods(["GET", "POST"])
def notification_settings(request: HttpRequest) -> HttpResponse:
    """Interface: renders the legacy notification settings route."""

    return render(
        request,
        "alerts/notification_settings.html",
    )
