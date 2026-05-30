from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.http import QueryDict
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_POST

from chattersift.alerts.models import NotificationCadence
from chattersift.reddit.contracts import MonitorMatchMode

from .forms import MATCH_RETENTION_FOREVER_VALUE
from .forms import CadenceForm
from .forms import MatchRetentionForm
from .forms import MonitorAddForm
from .forms import MonitorBatchForm
from .forms import MonitorEditForm
from .models import Monitor
from .services import MonitorAlreadyExistsError
from .services import add_monitor_to_subreddit
from .services import build_dashboard_groups
from .services import build_matches_feed
from .services import delete_single_monitor
from .services import delete_subreddit_group
from .services import dismiss_match
from .services import get_match_retention_days
from .services import prune_expired_matches_for_user
from .services import toggle_subreddit_group
from .services import update_group_cadence
from .services import update_match_retention_days
from .services import update_monitor
from .services import upsert_monitors

if TYPE_CHECKING:
    from django.http import HttpRequest


@login_required
@require_GET
def dashboard(request: HttpRequest) -> HttpResponse:
    """Renders the authenticated Reddit keyword dashboard."""

    context = _dashboard_context(request)
    context["dash_active_nav"] = "monitors"
    if request.headers.get("HX-Request"):
        return render(request, "tracking/_dashboard_content.html", context)
    return render(request, "tracking/dashboard.html", context)


@login_required
@require_POST
def monitor_create(request: HttpRequest) -> HttpResponse:
    """Creates or reactivates keyword monitors for one subreddit."""

    form = MonitorBatchForm(request.POST)
    is_valid = form.is_valid()
    if is_valid:
        upsert_monitors(
            user=request.user,
            subreddit=form.cleaned_data["subreddit"],
            match_mode=form.cleaned_data["match_mode"],
            keywords=form.cleaned_data["keywords"],
            semantic_description=form.cleaned_data["semantic_description"],
            cadence=form.cleaned_data["cadence"],
        )
        form = MonitorBatchForm()

    return _render_dashboard_content(request, form=form)


@login_required
@require_POST
def monitor_add(request: HttpRequest, subreddit: str) -> HttpResponse:
    """Adds one monitor (keyword, semantic, or hybrid) to an existing group."""

    form = MonitorAddForm(request.POST)
    inline_error: dict[str, object] | None = None
    if form.is_valid():
        try:
            add_monitor_to_subreddit(
                user=request.user,
                subreddit=subreddit,
                match_mode=form.cleaned_data["match_mode"],
                keyword=form.cleaned_data["keyword"],
                semantic_description=form.cleaned_data["semantic_description"],
            )
        except MonitorAlreadyExistsError:
            inline_error = {
                "kind": "add",
                "subreddit": subreddit.casefold(),
                "match_mode": form.cleaned_data["match_mode"],
                "message": "A monitor with these settings already exists for this subreddit.",
            }
    else:
        inline_error = {
            "kind": "add",
            "subreddit": subreddit.casefold(),
            "match_mode": form.cleaned_data.get("match_mode") or "",
            "message": _form_first_error(form),
        }

    return _render_dashboard_content(
        request,
        form=MonitorBatchForm(),
        inline_error=inline_error,
    )


@login_required
@require_POST
def monitor_edit(request: HttpRequest, pk: int) -> HttpResponse:
    """Edits one monitor's mode and content in place."""

    monitor = get_object_or_404(Monitor, pk=pk, user=request.user)
    form = MonitorEditForm(request.POST)
    inline_error: dict[str, object] | None = None
    if form.is_valid():
        try:
            update_monitor(
                user=request.user,
                pk=monitor.pk,
                match_mode=form.cleaned_data["match_mode"],
                keyword=form.cleaned_data["keyword"],
                semantic_description=form.cleaned_data["semantic_description"],
            )
        except MonitorAlreadyExistsError:
            inline_error = {
                "kind": "edit",
                "monitor_pk": monitor.pk,
                "message": "A monitor with these settings already exists for this subreddit.",
            }
    else:
        inline_error = {
            "kind": "edit",
            "monitor_pk": monitor.pk,
            "message": _form_first_error(form),
        }

    return _render_dashboard_content(
        request,
        form=MonitorBatchForm(),
        inline_error=inline_error,
    )


@login_required
@require_POST
def monitor_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """Permanently deletes one keyword monitor."""

    delete_single_monitor(user=request.user, pk=pk)
    return _render_dashboard_content(request, form=MonitorBatchForm())


@login_required
@require_POST
def monitor_deactivate(request: HttpRequest, pk: int) -> HttpResponse:
    """Deactivates one current-user monitor without deleting history."""

    monitor = get_object_or_404(Monitor, pk=pk, user=request.user)
    if monitor.is_active:
        monitor.is_active = False
        monitor.save(update_fields=["is_active", "updated_at"])

    return _render_dashboard_content(request, form=MonitorBatchForm())


@login_required
@require_POST
def monitor_toggle_group(request: HttpRequest, subreddit: str) -> HttpResponse:
    """Pauses or resumes all monitors for a subreddit."""

    toggle_subreddit_group(user=request.user, subreddit=subreddit)
    return _render_dashboard_content(request, form=MonitorBatchForm())


@login_required
@require_POST
def monitor_delete_group(request: HttpRequest, subreddit: str) -> HttpResponse:
    """Permanently deletes all monitors for a subreddit."""

    delete_subreddit_group(user=request.user, subreddit=subreddit)
    return _render_dashboard_content(request, form=MonitorBatchForm())


@login_required
@require_POST
def monitor_update_cadence(request: HttpRequest, subreddit: str) -> HttpResponse:
    """Updates notification cadence for all monitors in a subreddit group."""

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
    """Renders the matched content page."""

    selected_subreddit = request.GET.get("subreddit")
    page = _positive_int_or_default(request.GET.get("page"), default=1)
    feed = build_matches_feed(request.user, subreddit=selected_subreddit, page=page)

    previous_page_url = _matches_query_url(
        subreddit=feed.selected_subreddit,
        page=feed.page - 1,
    )
    next_page_url = _matches_query_url(
        subreddit=feed.selected_subreddit,
        page=feed.page + 1,
    )

    context = {
        "feed": feed,
        "has_matches": bool(feed.items),
        "has_monitors": bool(feed.subreddit_options),
        "previous_page_url": previous_page_url,
        "next_page_url": next_page_url,
        "dash_active_nav": "matches",
    }
    if request.headers.get("HX-Request"):
        return render(request, "tracking/_matches_content.html", context)
    return render(request, "tracking/matches.html", context)


@login_required
@require_POST
def match_dismiss(request: HttpRequest, reddit_item_id: str) -> HttpResponse:
    """Dismiss one Reddit item from the user's matches feed; HTMX removes the row."""

    dismiss_match(user=request.user, reddit_item_id=reddit_item_id)
    # Empty body so hx-swap="outerHTML" removes the matched row.
    return HttpResponse(status=200)


@login_required
@require_GET
def dashboard_settings(request: HttpRequest) -> HttpResponse:
    """Renders the consolidated dashboard settings page."""

    context = _settings_context(request)
    if request.headers.get("HX-Request"):
        return render(request, "dash/_settings_content.html", context)
    return render(request, "dash/settings.html", context)


@login_required
@require_POST
def match_retention_update(request: HttpRequest) -> HttpResponse:
    """Updates matched-item retention and prunes newly expired current-user matches."""

    form = MatchRetentionForm(request.POST)
    if form.is_valid():
        update_match_retention_days(user=request.user, retention_days=form.cleaned_data["retention_days"])
        prune_expired_matches_for_user(user=request.user)
        form = _match_retention_form(request)

    return render(request, "dash/_settings_content.html", _settings_context(request, match_retention_form=form))


def _dashboard_context(
    request: HttpRequest,
    *,
    form: MonitorBatchForm | None = None,
    inline_error: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build the dashboard template context for full-page and partial renders."""
    subreddit_groups = build_dashboard_groups(request.user, include_matches=False)
    form = form or MonitorBatchForm()
    return {
        "form": form,
        "show_monitor_form": form.is_bound and bool(form.errors),
        "subreddit_groups": subreddit_groups,
        "cadence_choices": NotificationCadence.choices,
        "match_mode_choices": MonitorMatchMode.choices,
        "inline_error": inline_error,
    }


def _settings_context(
    request: HttpRequest,
    *,
    match_retention_form: MatchRetentionForm | None = None,
) -> dict[str, object]:
    """Build the settings template context for full-page and partial renders."""

    return {
        "dash_active_nav": "settings",
        "match_retention_form": match_retention_form or _match_retention_form(request),
    }


def _match_retention_form(request: HttpRequest) -> MatchRetentionForm:
    """Return the current user's matched-item retention form."""

    retention_days = get_match_retention_days(request.user)
    initial = MATCH_RETENTION_FOREVER_VALUE if retention_days is None else str(retention_days)
    return MatchRetentionForm(initial={"retention_days": initial})


def _render_dashboard_content(
    request: HttpRequest,
    *,
    form: MonitorBatchForm,
    inline_error: dict[str, object] | None = None,
) -> HttpResponse:
    """Render just the dashboard content fragment used by HTMX updates."""
    html = render_to_string(
        "tracking/_dashboard_content.html",
        _dashboard_context(request, form=form, inline_error=inline_error),
        request=request,
    )
    return HttpResponse(html)


def _form_first_error(form: MonitorAddForm | MonitorEditForm) -> str:
    """Return the first error message from a bound form for inline display."""
    for errors in form.errors.values():
        if errors:
            return str(errors[0])
    return "Invalid input."


def _matches_query_url(*, subreddit: str | None, page: int) -> str:
    """Build a stable query string for matches filters and pagination links."""
    params = QueryDict(mutable=True)
    if subreddit:
        params["subreddit"] = subreddit
    if page > 1:
        params["page"] = str(page)
    query_string = params.urlencode()
    if not query_string:
        return ""
    return f"?{query_string}"


def _positive_int_or_default(raw_value: str | None, *, default: int) -> int:
    """Parse a positive integer, or fall back to the provided default value."""
    if raw_value is None:
        return default
    try:
        parsed = int(raw_value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default
