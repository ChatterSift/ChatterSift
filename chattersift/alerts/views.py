from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from .forms import EmailNotificationPreferenceForm
from .models import EmailNotificationPreference
from .services import update_email_notification_preference

if TYPE_CHECKING:
    from django.http import HttpRequest
    from django.http import HttpResponse


@login_required
@require_http_methods(["GET", "POST"])
def notification_settings(request: HttpRequest) -> HttpResponse:
    """Interface: renders and updates the current user's email notification cadence."""

    preference, _ = EmailNotificationPreference.objects.get_or_create(user=request.user)
    if request.method == "POST":
        form = EmailNotificationPreferenceForm(request.POST)
        if form.is_valid():
            preference = update_email_notification_preference(
                user=request.user,
                cadence=form.cleaned_data["cadence"],
            )
            form = EmailNotificationPreferenceForm(initial={"cadence": preference.cadence})
    else:
        form = EmailNotificationPreferenceForm(initial={"cadence": preference.cadence})

    return render(
        request,
        "alerts/notification_settings.html",
        {
            "form": form,
            "preference": preference,
        },
    )
