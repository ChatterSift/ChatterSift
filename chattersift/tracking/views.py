from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_POST

from chattersift.alerts.forms import EmailNotificationPreferenceForm
from chattersift.alerts.models import EmailNotificationPreference
from chattersift.alerts.services import update_email_notification_preference
from chattersift.users.forms import UserProfileForm

from .forms import MonitorBatchForm
from .models import Monitor
from .services import build_dashboard_groups
from .services import upsert_keyword_monitors

if TYPE_CHECKING:
    from django.http import HttpRequest


@login_required
@require_GET
def dashboard(request: HttpRequest) -> HttpResponse:
    """Interface: renders the authenticated Reddit keyword dashboard."""

    context = _dashboard_context(request)
    context["dash_active_nav"] = "monitors"
    if request.headers.get("HX-Request"):
        return render(request, "tracking/_dashboard_content.html", context)
    return render(request, "tracking/dashboard.html", context)


@login_required
@require_POST
def monitor_create(request: HttpRequest) -> HttpResponse:
    """Interface: creates or reactivates keyword monitors for one subreddit."""

    form = MonitorBatchForm(request.POST)
    is_valid = form.is_valid()
    if is_valid:
        upsert_keyword_monitors(
            user=request.user,
            subreddit=form.cleaned_data["subreddit"],
            keywords=form.cleaned_data["keywords"],
        )
        form = MonitorBatchForm()

    return _render_dashboard_content(request, form=form)


@login_required
@require_POST
def monitor_deactivate(request: HttpRequest, pk: int) -> HttpResponse:
    """Interface: deactivates one current-user monitor without deleting history."""

    monitor = get_object_or_404(Monitor, pk=pk, user=request.user)
    if monitor.is_active:
        monitor.is_active = False
        monitor.save(update_fields=["is_active", "updated_at"])

    return _render_dashboard_content(request, form=MonitorBatchForm())


@login_required
@require_GET
def matches(request: HttpRequest) -> HttpResponse:
    """Interface: renders the matched content page."""

    subreddit_groups = build_dashboard_groups(request.user)
    has_matches = any(group.matches for group in subreddit_groups)
    context = {
        "subreddit_groups": subreddit_groups,
        "has_matches": has_matches,
        "dash_active_nav": "matches",
    }
    if request.headers.get("HX-Request"):
        return render(request, "tracking/_matches_content.html", context)
    return render(request, "tracking/matches.html", context)


@login_required
@require_GET
def dashboard_settings(request: HttpRequest) -> HttpResponse:
    """Interface: renders the consolidated dashboard settings page."""

    profile_form = UserProfileForm(instance=request.user)
    preference, _ = EmailNotificationPreference.objects.get_or_create(user=request.user)
    notification_form = EmailNotificationPreferenceForm(initial={"cadence": preference.cadence})

    context = {
        "dash_active_nav": "settings",
        "profile_form": profile_form,
        "notification_form": notification_form,
    }
    if request.headers.get("HX-Request"):
        return render(request, "dash/_settings_content.html", context)
    return render(request, "dash/settings.html", context)


@login_required
@require_POST
def dashboard_settings_profile(request: HttpRequest) -> HttpResponse:
    """Interface: handles profile name update, returns HTMX partial."""

    form = UserProfileForm(request.POST, instance=request.user)
    saved = False
    if form.is_valid():
        form.save()
        saved = True

    html = render_to_string(
        "dash/_settings_profile.html",
        {
            "profile_form": form,
            "profile_saved": saved,
        },
        request=request,
    )
    return HttpResponse(html)


@login_required
@require_POST
def dashboard_settings_notifications(request: HttpRequest) -> HttpResponse:
    """Interface: handles notification cadence update, returns HTMX partial."""

    form = EmailNotificationPreferenceForm(request.POST)
    saved = False
    if form.is_valid():
        update_email_notification_preference(
            user=request.user,
            cadence=form.cleaned_data["cadence"],
        )
        saved = True
        form = EmailNotificationPreferenceForm(initial={"cadence": form.cleaned_data["cadence"]})

    html = render_to_string(
        "dash/_settings_notifications.html",
        {
            "notification_form": form,
            "notifications_saved": saved,
        },
        request=request,
    )
    return HttpResponse(html)


def _dashboard_context(request: HttpRequest, *, form: MonitorBatchForm | None = None) -> dict[str, object]:
    subreddit_groups = build_dashboard_groups(request.user, include_matches=False)
    return {
        "form": form or MonitorBatchForm(),
        "active_monitor_count": sum(len(group.monitors) for group in subreddit_groups),
        "subreddit_groups": subreddit_groups,
    }


def _render_dashboard_content(
    request: HttpRequest,
    *,
    form: MonitorBatchForm,
) -> HttpResponse:
    html = render_to_string(
        "tracking/_dashboard_content.html",
        _dashboard_context(request, form=form),
        request=request,
    )
    return HttpResponse(html)
