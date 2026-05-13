from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_POST

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


def _dashboard_context(request: HttpRequest, *, form: MonitorBatchForm | None = None) -> dict[str, object]:
    subreddit_groups = build_dashboard_groups(request.user)
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
