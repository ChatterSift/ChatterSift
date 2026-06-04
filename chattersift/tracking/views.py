from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.http import QueryDict
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_POST

from chattersift.alerts.models import NotificationCadence
from chattersift.core.extension_points import MonitorPolicyError
from chattersift.core.extension_points import get_dashboard_settings_context
from chattersift.core.extension_points import get_monitor_policy
from chattersift.reddit.contracts import MonitorMatchMode

from .forms import MATCH_RETENTION_FOREVER_VALUE
from .forms import CadenceForm
from .forms import MatchRetentionForm
from .forms import MonitorAddForm
from .forms import MonitorBatchForm
from .forms import MonitorEditForm
from .forms import normalize_subreddit
from .models import Match
from .models import MatchDismissal
from .models import MatchRetentionPreference
from .models import Monitor
from .querysets import MonitorAlreadyExistsError

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

    form = MonitorBatchForm(request.POST, user=request.user)
    is_valid = form.is_valid()
    if is_valid:
        try:
            Monitor.objects.upsert_from_intent(
                user=request.user,
                subreddit=form.cleaned_data["subreddit"],
                match_mode=form.cleaned_data["match_mode"],
                keywords=form.cleaned_data["keywords"],
                semantic_description=form.cleaned_data["semantic_description"],
                cadence=form.cleaned_data["cadence"],
            )
        except MonitorPolicyError as error:
            form.add_error(error.field, str(error))
        else:
            form = MonitorBatchForm(user=request.user)

    return _render_dashboard_content(request, form=form)


@login_required
@require_POST
def monitor_add(request: HttpRequest, subreddit: str) -> HttpResponse:
    """Adds one monitor (keyword, semantic, or hybrid) to an existing group."""

    try:
        normalized_subreddit = normalize_subreddit(subreddit)
    except ValidationError as error:
        inline_error = {
            "kind": "add",
            "subreddit": subreddit.casefold(),
            "match_mode": request.POST.get("match_mode") or "",
            "message": _validation_first_error(error),
        }
        return _render_dashboard_content(
            request,
            form=MonitorBatchForm(user=request.user),
            inline_error=inline_error,
        )

    form = MonitorAddForm(request.POST, user=request.user, subreddit=normalized_subreddit)
    inline_error: dict[str, object] | None = None
    if form.is_valid():
        try:
            Monitor.objects.add_to_subreddit(
                user=request.user,
                subreddit=normalized_subreddit,
                match_mode=form.cleaned_data["match_mode"],
                keyword=form.cleaned_data["keyword"],
                semantic_description=form.cleaned_data["semantic_description"],
            )
        except MonitorAlreadyExistsError:
            inline_error = {
                "kind": "add",
                "subreddit": normalized_subreddit,
                "match_mode": form.cleaned_data["match_mode"],
                "message": "A monitor with these settings already exists for this subreddit.",
            }
        except MonitorPolicyError as error:
            inline_error = {
                "kind": "add",
                "subreddit": normalized_subreddit,
                "match_mode": form.cleaned_data["match_mode"],
                "message": str(error),
            }
    else:
        inline_error = {
            "kind": "add",
            "subreddit": normalized_subreddit,
            "match_mode": form.cleaned_data.get("match_mode") or "",
            "message": _form_first_error(form),
        }

    return _render_dashboard_content(
        request,
        form=MonitorBatchForm(user=request.user),
        inline_error=inline_error,
    )


@login_required
@require_POST
def monitor_edit(request: HttpRequest, pk: int) -> HttpResponse:
    """Edits one monitor's mode and content in place."""

    monitor = get_object_or_404(Monitor, pk=pk, user=request.user)
    form = MonitorEditForm(request.POST, user=request.user, subreddit=monitor.subreddit, monitor=monitor)
    inline_error: dict[str, object] | None = None
    if form.is_valid():
        try:
            Monitor.objects.update_for_user(
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
        except MonitorPolicyError as error:
            inline_error = {
                "kind": "edit",
                "monitor_pk": monitor.pk,
                "message": str(error),
            }
    else:
        inline_error = {
            "kind": "edit",
            "monitor_pk": monitor.pk,
            "message": _form_first_error(form),
        }

    return _render_dashboard_content(
        request,
        form=MonitorBatchForm(user=request.user),
        inline_error=inline_error,
    )


@login_required
@require_POST
def monitor_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """Permanently deletes one keyword monitor."""

    Monitor.objects.delete_for_user(user=request.user, pk=pk)
    return _render_dashboard_content(request, form=MonitorBatchForm(user=request.user))


@login_required
@require_POST
def monitor_deactivate(request: HttpRequest, pk: int) -> HttpResponse:
    """Deactivates one current-user monitor without deleting history."""

    monitor = get_object_or_404(Monitor, pk=pk, user=request.user)
    if monitor.is_active:
        monitor.is_active = False
        monitor.save(update_fields=["is_active", "updated_at"])

    return _render_dashboard_content(request, form=MonitorBatchForm(user=request.user))


@login_required
@require_POST
def monitor_toggle_group(request: HttpRequest, subreddit: str) -> HttpResponse:
    """Pauses or resumes all monitors for a subreddit."""

    inline_error: dict[str, object] | None = None
    try:
        Monitor.objects.toggle_subreddit_group(user=request.user, subreddit=subreddit)
    except MonitorPolicyError as error:
        inline_error = {
            "kind": "group",
            "subreddit": subreddit.casefold(),
            "message": str(error),
        }
    return _render_dashboard_content(request, form=MonitorBatchForm(user=request.user), inline_error=inline_error)


@login_required
@require_POST
def monitor_delete_group(request: HttpRequest, subreddit: str) -> HttpResponse:
    """Permanently deletes all monitors for a subreddit."""

    Monitor.objects.delete_subreddit_group(user=request.user, subreddit=subreddit)
    return _render_dashboard_content(request, form=MonitorBatchForm(user=request.user))


@login_required
@require_POST
def monitor_update_cadence(request: HttpRequest, subreddit: str) -> HttpResponse:
    """Updates notification cadence for all monitors in a subreddit group."""

    form = CadenceForm(request.POST, user=request.user, subreddit=subreddit.casefold())
    inline_error: dict[str, object] | None = None
    if form.is_valid():
        try:
            Monitor.objects.update_group_cadence(
                user=request.user,
                subreddit=subreddit,
                cadence=form.cleaned_data["cadence"],
            )
        except MonitorPolicyError as error:
            inline_error = {
                "kind": "cadence",
                "subreddit": subreddit.casefold(),
                "message": str(error),
            }
    else:
        inline_error = {
            "kind": "cadence",
            "subreddit": subreddit.casefold(),
            "message": _form_first_error(form),
        }

    return _render_dashboard_content(
        request,
        form=MonitorBatchForm(user=request.user),
        inline_error=inline_error,
    )


@login_required
@require_GET
def matches(request: HttpRequest) -> HttpResponse:
    """Renders the matched content page."""

    selected_subreddit = request.GET.get("subreddit")
    page = _positive_int_or_default(request.GET.get("page"), default=1)
    feed = Match.objects.feed_for_user(request.user, subreddit=selected_subreddit, page=page)

    previous_page_url = _matches_query_url(
        subreddit=feed.selected_subreddit,
        page=feed.page - 1,
    )
    next_page_url = _matches_query_url(
        subreddit=feed.selected_subreddit,
        page=feed.page + 1,
    )
    page_links = _matches_page_links(
        subreddit=feed.selected_subreddit,
        current_page=feed.page,
        total_pages=feed.total_pages,
    )

    context = {
        "feed": feed,
        "has_matches": bool(feed.items),
        "has_monitors": bool(feed.subreddit_options),
        "previous_page_url": previous_page_url,
        "next_page_url": next_page_url,
        "page_links": page_links,
        "dash_active_nav": "matches",
    }
    if request.headers.get("HX-Request"):
        return render(request, "tracking/_matches_content.html", context)
    return render(request, "tracking/matches.html", context)


@login_required
@require_POST
def match_dismiss(request: HttpRequest, reddit_item_id: str) -> HttpResponse:
    """Dismiss one Reddit item from the user's matches feed; HTMX removes the row."""

    MatchDismissal.objects.dismiss(user=request.user, reddit_item_id=reddit_item_id)
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
        MatchRetentionPreference.objects.update_days_for_user(
            user=request.user,
            retention_days=form.cleaned_data["retention_days"],
        )
        Match.objects.prune_expired_for_user(user=request.user)
        form = _match_retention_form(request)

    return render(request, "dash/_settings_content.html", _settings_context(request, match_retention_form=form))


def _dashboard_context(
    request: HttpRequest,
    *,
    form: MonitorBatchForm | None = None,
    inline_error: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build the dashboard template context for full-page and partial renders."""
    subreddit_groups = Monitor.objects.dashboard_groups_for_user(request.user, include_matches=False)
    form = form or MonitorBatchForm(user=request.user)
    policy = get_monitor_policy()
    cadence_choices = policy.filter_cadence_choices(
        user=request.user,
        choices=NotificationCadence.choices,
    )
    match_mode_choices = policy.filter_match_mode_choices(
        user=request.user,
        choices=MonitorMatchMode.choices,
    )
    return {
        "form": form,
        "show_monitor_form": form.is_bound and bool(form.errors),
        "subreddit_groups": subreddit_groups,
        "cadence_choices": cadence_choices,
        "match_mode_choices": match_mode_choices,
        "allowed_match_modes": tuple(value for value, _ in match_mode_choices),
        "inline_error": inline_error,
    }


def _settings_context(
    request: HttpRequest,
    *,
    match_retention_form: MatchRetentionForm | None = None,
) -> dict[str, object]:
    """Build the settings template context for full-page and partial renders."""

    context = {
        "dash_active_nav": "settings",
        "match_retention_form": match_retention_form or _match_retention_form(request),
        "dashboard_settings_extension_template": settings.CHATTERSIFT_DASHBOARD_SETTINGS_EXTENSION_TEMPLATE,
    }
    context.update(get_dashboard_settings_context(request))
    return context


def _match_retention_form(request: HttpRequest) -> MatchRetentionForm:
    """Return the current user's matched-item retention form."""

    retention_days = MatchRetentionPreference.objects.get_days_for_user(request.user)
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


def _form_first_error(form: CadenceForm | MonitorAddForm | MonitorEditForm) -> str:
    """Return the first error message from a bound form for inline display."""
    for errors in form.errors.values():
        if errors:
            return str(errors[0])
    return "Invalid input."


def _validation_first_error(error: ValidationError) -> str:
    """Return the first message from a standalone validation error."""
    if error.messages:
        return str(error.messages[0])
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


def _matches_page_links(
    *,
    subreddit: str | None,
    current_page: int,
    total_pages: int,
) -> tuple[dict[str, object], ...]:
    """Build numbered pager links with ellipses for jumping across pages.

    Always shows the first and last page, the current page, and one neighbour
    on either side. Inserts ellipsis markers across gaps so the pager stays
    compact regardless of total_pages.
    """
    if total_pages <= 1:
        return ()
    visible = sorted(
        {
            1,
            total_pages,
            current_page - 1,
            current_page,
            current_page + 1,
        },
    )
    visible = [p for p in visible if 1 <= p <= total_pages]
    links: list[dict[str, object]] = []
    previous_page = 0
    for page_number in visible:
        if page_number - previous_page > 1:
            links.append({"is_ellipsis": True})
        links.append(
            {
                "page": page_number,
                "url": _matches_query_url(subreddit=subreddit, page=page_number),
                "is_current": page_number == current_page,
                "is_ellipsis": False,
            },
        )
        previous_page = page_number
    return tuple(links)


def _positive_int_or_default(raw_value: str | None, *, default: int) -> int:
    """Parse a positive integer, or fall back to the provided default value."""
    if raw_value is None:
        return default
    try:
        parsed = int(raw_value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default
