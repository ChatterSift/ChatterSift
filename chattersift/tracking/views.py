from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_POST

from chattersift.alerts.models import NotificationCadence
from chattersift.users.forms import UserProfileForm

from .forms import CadenceForm
from .forms import KeywordAddForm
from .forms import MonitorBatchForm
from .models import Monitor
from .services import add_keyword_to_subreddit
from .services import build_dashboard_groups
from .services import delete_single_monitor
from .services import delete_subreddit_group
from .services import toggle_subreddit_group
from .services import update_group_cadence
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
            cadence=form.cleaned_data["cadence"],
        )
        form = MonitorBatchForm()

    return _render_dashboard_content(request, form=form)


@login_required
@require_POST
def monitor_add_keyword(request: HttpRequest, subreddit: str) -> HttpResponse:
    """Interface: adds a single keyword to an existing subreddit group."""

    form = KeywordAddForm(request.POST)
    if form.is_valid():
        add_keyword_to_subreddit(
            user=request.user,
            subreddit=subreddit,
            keyword=form.cleaned_data["keyword"],
        )

    return _render_dashboard_content(request, form=MonitorBatchForm())


@login_required
@require_POST
def monitor_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """Interface: permanently deletes one keyword monitor."""

    delete_single_monitor(user=request.user, pk=pk)
    return _render_dashboard_content(request, form=MonitorBatchForm())


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
@require_POST
def monitor_toggle_group(request: HttpRequest, subreddit: str) -> HttpResponse:
    """Interface: pauses or resumes all monitors for a subreddit."""

    toggle_subreddit_group(user=request.user, subreddit=subreddit)
    return _render_dashboard_content(request, form=MonitorBatchForm())


@login_required
@require_POST
def monitor_delete_group(request: HttpRequest, subreddit: str) -> HttpResponse:
    """Interface: permanently deletes all monitors for a subreddit."""

    delete_subreddit_group(user=request.user, subreddit=subreddit)
    return _render_dashboard_content(request, form=MonitorBatchForm())


@login_required
@require_POST
def monitor_update_cadence(request: HttpRequest, subreddit: str) -> HttpResponse:
    """Interface: updates notification cadence for all monitors in a subreddit group."""

    form = CadenceForm(request.POST)
    if form.is_valid():
        update_group_cadence(
            user=request.user,
            subreddit=subreddit,
            cadence=form.cleaned_data["cadence"],
        )

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

    context = {
        "dash_active_nav": "settings",
        "profile_form": profile_form,
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


def _dashboard_context(request: HttpRequest, *, form: MonitorBatchForm | None = None) -> dict[str, object]:
    subreddit_groups = build_dashboard_groups(request.user, include_matches=False)
    form = form or MonitorBatchForm()
    return {
        "form": form,
        "show_monitor_form": form.is_bound and bool(form.errors),
        "subreddit_groups": subreddit_groups,
        "cadence_choices": NotificationCadence.choices,
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
