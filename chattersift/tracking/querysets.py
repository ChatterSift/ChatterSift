from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from hashlib import sha256
from typing import TYPE_CHECKING
from typing import cast

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db import models
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from chattersift.alerts.models import NotificationCadence
from chattersift.alerts.schedules import ensure_email_delivery_state
from chattersift.core.extension_points import get_monitor_policy
from chattersift.core.text_snippets import highlighted_snippet
from chattersift.reddit.contracts import MonitorMatchMode

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.utils.safestring import SafeString

    from .models import Match
    from .models import MatchDismissal
    from .models import MatchRetentionPreference
    from .models import Monitor

User = get_user_model()
DEFAULT_MATCH_RETENTION_DAYS = 30


class MonitorAlreadyExistsError(Exception):
    """Raised when an add or edit would create a duplicate monitor in a group."""


@dataclass(frozen=True)
class DashboardMatch:
    """Presents one Reddit item with all active matched monitor labels."""

    reddit_item_id: str
    item_type_label: str
    title: str
    body: str
    permalink: str
    occurred_at: object
    keywords: tuple[str, ...]
    monitor_labels: tuple[str, ...]


@dataclass(frozen=True)
class DashboardSubredditGroup:
    """Presents active monitors and recent matches for one subreddit."""

    subreddit: str
    monitors: tuple[Monitor, ...]
    keyword_monitors: tuple[Monitor, ...]
    semantic_monitors: tuple[Monitor, ...]
    hybrid_monitors: tuple[Monitor, ...]
    matches: tuple[DashboardMatch, ...]
    notification_cadence: str
    is_paused: bool


@dataclass(frozen=True)
class MatchesFeedItem:
    """Presents one unique Reddit item for the matches feed."""

    subreddit: str
    reddit_item_id: str
    item_type_label: str
    permalink: str
    occurred_at: object
    keywords: tuple[str, ...]
    monitor_labels: tuple[str, ...]
    title_html: SafeString
    body_html: SafeString


@dataclass(frozen=True)
class MatchesFeedResult:
    """Paginated matches feed scoped to one user and optional subreddit."""

    subreddit_options: tuple[str, ...]
    selected_subreddit: str | None
    items: tuple[MatchesFeedItem, ...]
    page: int
    total_pages: int
    has_previous: bool
    has_next: bool


class MonitorQuerySet(models.QuerySet):
    """Interface: own Monitor creation, group mutation, and dashboard grouping."""

    @transaction.atomic
    def upsert_keywords(
        self,
        *,
        user: User,
        subreddit: str,
        keywords: Iterable[str],
        cadence: str = NotificationCadence.THIRTY_MINUTES,
    ) -> list[Monitor]:
        """Creates or reactivates one Monitor row for each keyword."""
        monitors: list[Monitor] = []
        normalized_subreddit = subreddit.casefold()
        keyword_list = list(keywords)
        _validate_monitor_policy(
            action="create",
            user=user,
            subreddit=normalized_subreddit,
            match_mode=MonitorMatchMode.KEYWORD,
            keywords=keyword_list,
            semantic_description="",
            cadence=cadence,
        )

        for keyword in keyword_list:
            monitor = (
                self.select_for_update()
                .filter(
                    user=user,
                    subreddit=normalized_subreddit,
                    match_mode=MonitorMatchMode.KEYWORD,
                    keyword__iexact=keyword,
                    semantic_fingerprint="",
                )
                .first()
            )
            if monitor is None:
                monitor = self.create(
                    user=user,
                    subreddit=normalized_subreddit,
                    match_mode=MonitorMatchMode.KEYWORD,
                    keyword=keyword,
                    notification_cadence=cadence,
                )
                ensure_email_delivery_state(user=user, cadence=cadence)
            elif not monitor.is_active:
                monitor.is_active = True
                monitor.notification_cadence = cadence
                monitor.save(update_fields=["is_active", "notification_cadence", "updated_at"])
                ensure_email_delivery_state(user=user, cadence=cadence)
            monitors.append(monitor)

        return monitors

    @transaction.atomic
    def upsert_from_intent(  # noqa: PLR0913
        self,
        *,
        user: User,
        subreddit: str,
        match_mode: str,
        keywords: Iterable[str],
        semantic_description: str,
        cadence: str = NotificationCadence.THIRTY_MINUTES,
    ) -> list[Monitor]:
        """Creates or reactivates monitors for one submitted dashboard intent."""
        mode = MonitorMatchMode(match_mode)
        if mode == MonitorMatchMode.KEYWORD:
            return self.upsert_keywords(user=user, subreddit=subreddit, keywords=keywords, cadence=cadence)

        normalized_subreddit = subreddit.casefold()
        normalized_description = normalize_semantic_description(semantic_description)
        semantic_fingerprint = semantic_description_fingerprint(normalized_description)
        monitor_keywords = [""] if mode == MonitorMatchMode.SEMANTIC else list(keywords)
        monitors: list[Monitor] = []
        _validate_monitor_policy(
            action="create",
            user=user,
            subreddit=normalized_subreddit,
            match_mode=mode,
            keywords=monitor_keywords,
            semantic_description=normalized_description,
            cadence=cadence,
        )

        for keyword in monitor_keywords:
            monitor = (
                self.select_for_update()
                .filter(
                    user=user,
                    subreddit=normalized_subreddit,
                    match_mode=mode,
                    keyword__iexact=keyword,
                    semantic_fingerprint=semantic_fingerprint,
                )
                .first()
            )
            if monitor is None:
                monitor = self.create(
                    user=user,
                    subreddit=normalized_subreddit,
                    match_mode=mode,
                    keyword=keyword,
                    semantic_description=normalized_description,
                    semantic_fingerprint=semantic_fingerprint,
                    notification_cadence=cadence,
                )
                ensure_email_delivery_state(user=user, cadence=cadence)
            elif not monitor.is_active:
                monitor.is_active = True
                monitor.notification_cadence = cadence
                monitor.semantic_description = normalized_description
                monitor.save(
                    update_fields=[
                        "is_active",
                        "notification_cadence",
                        "semantic_description",
                        "updated_at",
                    ],
                )
                ensure_email_delivery_state(user=user, cadence=cadence)
            monitors.append(monitor)

        return monitors

    @transaction.atomic
    def add_to_subreddit(
        self,
        *,
        user: User,
        subreddit: str,
        match_mode: str,
        keyword: str = "",
        semantic_description: str = "",
    ) -> Monitor:
        """Adds one monitor of any type to an existing subreddit group."""
        mode = MonitorMatchMode(match_mode)
        normalized_subreddit = subreddit.casefold()
        normalized_description = normalize_semantic_description(semantic_description)
        fingerprint = semantic_description_fingerprint(normalized_description)
        effective_keyword = "" if mode == MonitorMatchMode.SEMANTIC else keyword

        existing = (
            self.select_for_update()
            .filter(
                user=user,
                subreddit=normalized_subreddit,
                match_mode=mode,
                keyword__iexact=effective_keyword,
                semantic_fingerprint=fingerprint,
            )
            .first()
        )
        if existing is not None:
            if existing.is_active:
                raise MonitorAlreadyExistsError
            _validate_monitor_policy(
                action="reactivate",
                user=user,
                subreddit=normalized_subreddit,
                match_mode=mode,
                keywords=[effective_keyword],
                semantic_description=normalized_description,
                cadence=existing.notification_cadence,
                monitor=existing,
            )
            existing.is_active = True
            if mode != MonitorMatchMode.KEYWORD:
                existing.semantic_description = normalized_description
            existing.save(update_fields=["is_active", "semantic_description", "updated_at"])
            return existing

        other = self.filter(user=user, subreddit=normalized_subreddit).first()
        cadence = other.notification_cadence if other else NotificationCadence.THIRTY_MINUTES
        _validate_monitor_policy(
            action="add",
            user=user,
            subreddit=normalized_subreddit,
            match_mode=mode,
            keywords=[effective_keyword],
            semantic_description=normalized_description,
            cadence=cadence,
        )
        monitor = self.create(
            user=user,
            subreddit=normalized_subreddit,
            match_mode=mode,
            keyword=effective_keyword,
            semantic_description=normalized_description,
            semantic_fingerprint=fingerprint,
            notification_cadence=cadence,
        )
        ensure_email_delivery_state(user=user, cadence=cadence)
        return monitor

    @transaction.atomic
    def update_for_user(
        self,
        *,
        user: User,
        pk: int,
        match_mode: str,
        keyword: str = "",
        semantic_description: str = "",
    ) -> Monitor:
        """Updates one monitor's mode and content."""
        monitor = self.select_for_update().filter(pk=pk, user=user).first()
        if monitor is None:
            raise self.model.DoesNotExist

        mode = MonitorMatchMode(match_mode)
        normalized_description = normalize_semantic_description(semantic_description)
        fingerprint = semantic_description_fingerprint(normalized_description)
        effective_keyword = "" if mode == MonitorMatchMode.SEMANTIC else keyword

        clash = (
            self.filter(
                user=user,
                subreddit=monitor.subreddit,
                match_mode=mode,
                keyword__iexact=effective_keyword,
                semantic_fingerprint=fingerprint,
            )
            .exclude(pk=pk)
            .exists()
        )
        if clash:
            raise MonitorAlreadyExistsError

        _validate_monitor_policy(
            action="edit",
            user=user,
            subreddit=monitor.subreddit,
            match_mode=mode,
            keywords=[effective_keyword],
            semantic_description=normalized_description,
            cadence=monitor.notification_cadence,
            monitor=monitor,
        )
        monitor.match_mode = mode
        monitor.keyword = effective_keyword
        monitor.semantic_description = normalized_description
        monitor.semantic_fingerprint = fingerprint
        monitor.save(
            update_fields=[
                "match_mode",
                "keyword",
                "semantic_description",
                "semantic_fingerprint",
                "updated_at",
            ],
        )
        return monitor

    def delete_for_user(self, *, user: User, pk: int) -> None:
        """Permanently deletes one monitor and its match history."""
        self.filter(pk=pk, user=user).delete()

    def delete_subreddit_group(self, *, user: User, subreddit: str) -> None:
        """Permanently deletes all monitors for a subreddit."""
        self.filter(user=user, subreddit=subreddit.casefold()).delete()

    @transaction.atomic
    def toggle_subreddit_group(self, *, user: User, subreddit: str) -> bool:
        """Pauses or resumes all monitors for a subreddit. Returns new is_active state."""
        normalized = subreddit.casefold()
        monitors = list(self.select_for_update().filter(user=user, subreddit=normalized))
        if not monitors:
            return False

        any_active = any(monitor.is_active for monitor in monitors)
        new_state = not any_active
        if new_state:
            _validate_monitor_policy(
                action="reactivate",
                user=user,
                subreddit=normalized,
                match_mode=MonitorMatchMode.KEYWORD,
                keywords=[],
                semantic_description="",
                cadence=None,
            )
        self.filter(user=user, subreddit=normalized).update(is_active=new_state)
        return new_state

    @transaction.atomic
    def update_group_cadence(self, *, user: User, subreddit: str, cadence: str) -> None:
        """Sets the notification cadence for all monitors in a subreddit group."""
        normalized_subreddit = subreddit.casefold()
        _validate_monitor_policy(
            action="cadence",
            user=user,
            subreddit=normalized_subreddit,
            match_mode=MonitorMatchMode.KEYWORD,
            keywords=[],
            semantic_description="",
            cadence=cadence,
        )
        self.filter(user=user, subreddit=normalized_subreddit).update(notification_cadence=cadence)
        ensure_email_delivery_state(user=user, cadence=cadence)

    def dashboard_groups_for_user(
        self,
        user: User,
        *,
        include_matches: bool = True,
        match_limit_per_subreddit: int = 25,
    ) -> list[DashboardSubredditGroup]:
        """Returns current-user active monitor groups with aggregate matches."""
        all_monitors = list(self.filter(user=user).order_by("subreddit", "match_mode", "keyword"))
        monitors_by_subreddit: dict[str, list[Monitor]] = {}
        for monitor in all_monitors:
            monitors_by_subreddit.setdefault(monitor.subreddit, []).append(monitor)

        if include_matches:
            matches_by_subreddit = _build_dashboard_matches_by_subreddit(
                user=user,
                subreddits=monitors_by_subreddit.keys(),
                match_limit_per_subreddit=match_limit_per_subreddit,
            )
        else:
            matches_by_subreddit = {}

        return [
            DashboardSubredditGroup(
                subreddit=subreddit,
                monitors=tuple(monitors),
                keyword_monitors=tuple(m for m in monitors if m.match_mode == MonitorMatchMode.KEYWORD),
                semantic_monitors=tuple(m for m in monitors if m.match_mode == MonitorMatchMode.SEMANTIC),
                hybrid_monitors=tuple(m for m in monitors if m.match_mode == MonitorMatchMode.KEYWORD_SEMANTIC),
                matches=tuple(matches_by_subreddit.get(subreddit, [])),
                notification_cadence=cast("str", monitors[0].notification_cadence)
                if monitors
                else NotificationCadence.OFF,
                is_paused=all(not m.is_active for m in monitors),
            )
            for subreddit, monitors in monitors_by_subreddit.items()
        ]


class MatchQuerySet(models.QuerySet):
    """Interface: expose reusable Match scoping, feed, and pruning helpers."""

    def active_monitors(self) -> MatchQuerySet:
        """Return matches attached to active monitors."""
        return self.filter(monitor__is_active=True)

    def for_user(self, user: User) -> MatchQuerySet:
        """Return matches owned by one monitor user."""
        return self.filter(monitor__user=user)

    def undismissed_by(self, user: User) -> MatchQuerySet:
        """Return matches not hidden by one user."""
        return self.exclude(
            reddit_item_id__in=_match_dismissal_model().objects.filter(user=user).values("reddit_item_id"),
        )

    def feed_for_user(
        self,
        user: User,
        *,
        subreddit: str | None,
        page: int = 1,
        page_size: int = 25,
    ) -> MatchesFeedResult:
        """Returns paginated unique Reddit matches for current-user active monitors."""
        subreddit_options = tuple(
            _monitor_model()
            .objects.filter(user=user)
            .order_by("subreddit")
            .values_list("subreddit", flat=True)
            .distinct(),
        )
        selected_subreddit = subreddit if subreddit in subreddit_options else None

        group_rows = self.for_user(user).active_monitors().undismissed_by(user)
        if selected_subreddit:
            group_rows = group_rows.filter(monitor__subreddit=selected_subreddit)

        grouped = (
            group_rows.values("monitor__subreddit", "reddit_item_id")
            .annotate(latest_occurred_at=Max("occurred_at"))
            .order_by("-latest_occurred_at", "monitor__subreddit", "reddit_item_id")
        )

        paginator = Paginator(grouped, page_size)
        page_obj = paginator.get_page(page)
        page_groups = list(page_obj.object_list)

        if not page_groups:
            return MatchesFeedResult(
                subreddit_options=subreddit_options,
                selected_subreddit=selected_subreddit,
                items=(),
                page=page_obj.number,
                total_pages=paginator.num_pages or 1,
                has_previous=page_obj.has_previous(),
                has_next=page_obj.has_next(),
            )

        group_keys = {
            (row["monitor__subreddit"], row["reddit_item_id"]): row["latest_occurred_at"] for row in page_groups
        }
        matches = list(
            group_rows.filter(
                monitor__subreddit__in={key[0] for key in group_keys},
                reddit_item_id__in={key[1] for key in group_keys},
            )
            .select_related("monitor")
            .order_by(
                "-occurred_at",
                "monitor__subreddit",
                "reddit_item_id",
                "monitor__keyword",
            ),
        )

        grouped_matches: dict[tuple[str, str], list[Match]] = {key: [] for key in group_keys}
        for match in matches:
            group_key = (match.monitor.subreddit, cast("str", match.reddit_item_id))
            if group_key in grouped_matches:
                grouped_matches[group_key].append(match)

        items = tuple(
            _build_matches_feed_item(grouped_matches[(row["monitor__subreddit"], row["reddit_item_id"])])
            for row in page_groups
            if grouped_matches[(row["monitor__subreddit"], row["reddit_item_id"])]
        )

        return MatchesFeedResult(
            subreddit_options=subreddit_options,
            selected_subreddit=selected_subreddit,
            items=items,
            page=page_obj.number,
            total_pages=paginator.num_pages or 1,
            has_previous=page_obj.has_previous(),
            has_next=page_obj.has_next(),
        )

    def prune_expired_for_user(self, *, user: User, now: datetime | None = None) -> int:
        """Delete expired Match rows for one user based on Match.created_at."""
        retention_days = _match_retention_preference_model().objects.get_days_for_user(user)
        if retention_days is None:
            return 0

        reference_time = now or timezone.now()
        cutoff = reference_time - timedelta(days=retention_days)
        deleted_count, _ = self.filter(monitor__user=user, created_at__lt=cutoff).delete()
        return deleted_count

    def prune_expired(self, *, now: datetime | None = None) -> int:
        """Delete expired Match rows for every user with default or explicit retention."""
        reference_time = now or timezone.now()
        total_deleted = 0
        for user in User.objects.all().iterator():
            total_deleted += self.prune_expired_for_user(user=user, now=reference_time)
        return total_deleted


class MatchDismissalQuerySet(models.QuerySet):
    """Interface: own idempotent dismissal of Reddit items."""

    def dismiss(self, *, user: User, reddit_item_id: str) -> None:
        """Hide one Reddit item from the user's matches feed."""
        self.get_or_create(user=user, reddit_item_id=reddit_item_id)


class MatchRetentionPreferenceQuerySet(models.QuerySet):
    """Interface: own matched-item retention preference persistence."""

    def get_days_for_user(self, user: User) -> int | None:
        """Return the user's matched-item retention days, defaulting missing rows to 30 days."""
        preference = self.filter(user=user).first()
        if preference is None:
            return DEFAULT_MATCH_RETENTION_DAYS
        return preference.retention_days

    @transaction.atomic
    def update_days_for_user(self, *, user: User, retention_days: int | None) -> MatchRetentionPreference:
        """Persist one user's matched-item retention preference."""
        preference, _ = self.select_for_update().update_or_create(
            user=user,
            defaults={"retention_days": retention_days},
        )
        return preference


def normalize_semantic_description(value: str) -> str:
    """Return compact semantic description text for persistence and matching."""
    return re.sub(r"\s+", " ", value).strip()


def semantic_description_fingerprint(value: str) -> str:
    """Return stable monitor dedupe fingerprint for a semantic description."""
    normalized = normalize_semantic_description(value).casefold()
    if not normalized:
        return ""
    return sha256(normalized.encode()).hexdigest()


def _validate_monitor_policy(  # noqa: PLR0913
    *,
    action: str,
    user: User,
    subreddit: str,
    match_mode: str,
    keywords: Iterable[str],
    semantic_description: str,
    cadence: str | None,
    monitor: Monitor | None = None,
) -> None:
    """Validate a monitor mutation against the configured extension policy."""
    get_monitor_policy().validate_monitor_intent(
        action=action,
        user=user,
        subreddit=subreddit,
        match_mode=match_mode,
        keywords=list(keywords),
        semantic_description=semantic_description,
        cadence=cadence,
        monitor=monitor,
    )


def _build_dashboard_matches_by_subreddit(
    *,
    user: User,
    subreddits: Iterable[str],
    match_limit_per_subreddit: int,
) -> dict[str, list[DashboardMatch]]:
    """Group recent matches by subreddit and Reddit item for dashboard display."""
    subreddit_set = set(subreddits)
    if not subreddit_set:
        return {}

    matches = (
        _match_model()
        .objects.filter(
            monitor__user=user,
            monitor__is_active=True,
            monitor__subreddit__in=subreddit_set,
        )
        .select_related("monitor")
        .order_by("monitor__subreddit", "-occurred_at", "reddit_item_id", "monitor__keyword")
    )
    grouped_matches: dict[str, dict[str, list[Match]]] = {subreddit: {} for subreddit in subreddit_set}

    for match in matches:
        subreddit = match.monitor.subreddit
        item_groups = grouped_matches[subreddit]
        if match.reddit_item_id not in item_groups and len(item_groups) >= match_limit_per_subreddit:
            continue
        item_groups.setdefault(match.reddit_item_id, []).append(match)

    return {
        subreddit: [_build_dashboard_match(item_matches) for item_matches in item_groups.values()]
        for subreddit, item_groups in grouped_matches.items()
    }


def _build_dashboard_match(matches: list[Match]) -> DashboardMatch:
    """Convert one Reddit item's grouped Match rows into a dashboard payload."""
    first_match = matches[0]
    keywords = _keyword_terms(matches)
    monitor_labels = _monitor_labels(matches)
    return DashboardMatch(
        reddit_item_id=cast("str", first_match.reddit_item_id),
        item_type_label=_reddit_item_type_label(cast("str", first_match.reddit_item_id)),
        title=cast("str", first_match.title),
        body=cast("str", first_match.body),
        permalink=cast("str", first_match.permalink),
        occurred_at=first_match.occurred_at,
        keywords=keywords,
        monitor_labels=monitor_labels,
    )


def _build_matches_feed_item(matches: list[Match]) -> MatchesFeedItem:
    """Build one matches-feed item with keyword highlights from grouped matches."""
    first_match = matches[0]
    keywords = _keyword_terms(matches)
    monitor_labels = _monitor_labels(matches)
    return MatchesFeedItem(
        subreddit=cast("str", first_match.monitor.subreddit),
        reddit_item_id=cast("str", first_match.reddit_item_id),
        item_type_label=_reddit_item_type_label(cast("str", first_match.reddit_item_id)),
        permalink=cast("str", first_match.permalink),
        occurred_at=first_match.occurred_at,
        keywords=keywords,
        monitor_labels=monitor_labels,
        title_html=highlighted_snippet(cast("str", first_match.title), keywords=keywords, max_length=180),
        body_html=highlighted_snippet(cast("str", first_match.body), keywords=keywords, max_length=260),
    )


def _reddit_item_type_label(reddit_item_id: str) -> str:
    """Returns a user-facing Reddit item type from a fullname."""
    if reddit_item_id.startswith("t1_"):
        return "Comment"
    if reddit_item_id.startswith("t3_"):
        return "Post"
    return "Reddit item"


def _keyword_terms(matches: Iterable[Match]) -> tuple[str, ...]:
    """Return real keyword terms only, excluding semantic-only monitors."""
    return tuple(
        sorted(
            {
                str(match.monitor.keyword)
                for match in matches
                if match.monitor.keyword and match.monitor.match_mode != MonitorMatchMode.SEMANTIC
            },
            key=str.casefold,
        ),
    )


def _monitor_labels(matches: Iterable[Match]) -> tuple[str, ...]:
    """Return display labels for all monitors that matched an item."""
    return tuple(sorted({match.monitor.label for match in matches if match.monitor.label}, key=str.casefold))


def _monitor_model() -> type[Monitor]:
    """Return the Monitor model after Django has registered app models."""
    return apps.get_model("tracking", "Monitor")


def _match_model() -> type[Match]:
    """Return the Match model after Django has registered app models."""
    return apps.get_model("tracking", "Match")


def _match_dismissal_model() -> type[MatchDismissal]:
    """Return the MatchDismissal model after Django has registered app models."""
    return apps.get_model("tracking", "MatchDismissal")


def _match_retention_preference_model() -> type[MatchRetentionPreference]:
    """Return the MatchRetentionPreference model after Django has registered app models."""
    return apps.get_model("tracking", "MatchRetentionPreference")
