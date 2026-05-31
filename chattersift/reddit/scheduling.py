from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING
from typing import cast

from django.conf import settings
from django.utils import timezone

from .contracts import RedditFeedFormat
from .models import SubredditFetchState
from .planning import build_feed_specs_for_active_monitors
from .planning import normalize_subreddit

if TYPE_CHECKING:
    from datetime import datetime

    from .contracts import FetchResult
    from .contracts import RedditFeedSpec

ERROR_MESSAGE_LIMIT = 1000


@dataclass(frozen=True, kw_only=True)
class _FeedStateIdentity:
    """Stable key for matching planned feed specs to persisted fetch state."""

    kind: str
    format: str
    subreddit: str
    query_fingerprint: str


def get_due_feed_specs(*, limit: int | None = None) -> list[RedditFeedSpec]:
    """Return feed specs that are eligible to fetch according to core state.

    Input:
        Optional maximum number of feed specs.

    Output:
        Feed specs whose persisted fetch state says they are due. The state
        model should be keyed by kind, format, subreddit, and
        query_fingerprint.
    """
    preferred_format = RedditFeedFormat(settings.CHATTERSIFT_REDDIT_FEED_FORMAT)
    planned_specs = build_feed_specs_for_active_monitors(
        preferred_format=preferred_format,
    )
    identities = [_state_identity(spec) for spec in planned_specs]
    states = {
        _state_identity_from_state(state): state
        for state in SubredditFetchState.objects.filter(
            kind__in={identity.kind for identity in identities},
            format__in={identity.format for identity in identities},
        )
    }
    now = timezone.now()

    due_specs: list[RedditFeedSpec] = []
    for spec in planned_specs:
        state = states.get(_state_identity(spec))
        if state is not None and state.next_fetch_at is not None and state.next_fetch_at > now:
            continue

        due_specs.append(spec)
        if limit is not None and len(due_specs) >= limit:
            break

    return due_specs


def mark_feed_success(spec: RedditFeedSpec, result: FetchResult) -> None:
    """Record successful fetch state for a feed spec.

    Input:
        Feed spec plus its successful FetchResult.

    Output:
        Persisted success state, including last success time, last seen item,
        cleared or reduced failure state, and next eligible fetch time.
    """
    defaults = {
        "last_fetched_at": timezone.now(),
        "next_fetch_at": calculate_next_fetch_at(spec, failed=False),
        "consecutive_failures": 0,
        "last_error": "",
    }
    if result.last_seen_fullname:
        defaults["last_seen_fullname"] = result.last_seen_fullname

    SubredditFetchState.objects.update_or_create(
        **_state_lookup(spec),
        defaults=defaults,
    )


def mark_feed_failure(spec: RedditFeedSpec, error: Exception) -> None:
    """Record failed fetch state and advance backoff for a feed spec.

    Input:
        Feed spec plus fetch, parse, HTTP, timeout, or rate-limit exception.

    Output:
        Persisted failure state, consecutive failure count, last error, and next
        eligible fetch time.
    """
    state = SubredditFetchState.objects.filter(**_state_lookup(spec)).first()
    consecutive_failures = 1 if state is None else state.consecutive_failures + 1
    SubredditFetchState.objects.update_or_create(
        **_state_lookup(spec),
        defaults={
            "next_fetch_at": _calculate_next_fetch_at(
                failed=True,
                consecutive_failures=consecutive_failures,
            ),
            "consecutive_failures": consecutive_failures,
            "last_error": str(error)[:ERROR_MESSAGE_LIMIT],
        },
    )


def calculate_next_fetch_at(
    spec: RedditFeedSpec,
    *,
    failed: bool,
) -> datetime:
    """Return the next eligible fetch time, including jitter and backoff.

    Input:
        Feed spec and whether the previous attempt failed.

    Output:
        Timestamp used by core scheduling to decide when the feed is due again.
        Backoff and jitter are core responsibilities even when an extension
        wraps this interface with distributed locks.
    """
    state = SubredditFetchState.objects.filter(**_state_lookup(spec)).first()
    consecutive_failures = 1 if state is None else state.consecutive_failures + 1
    return _calculate_next_fetch_at(
        failed=failed,
        consecutive_failures=consecutive_failures,
    )


def _calculate_next_fetch_at(*, failed: bool, consecutive_failures: int) -> datetime:
    """Return next run time using normal interval or exponential failure backoff."""
    if not failed:
        return timezone.now() + timedelta(
            seconds=settings.CHATTERSIFT_REDDIT_FETCH_INTERVAL_SECONDS,
        )

    base_seconds = settings.CHATTERSIFT_REDDIT_FAILURE_BACKOFF_BASE_SECONDS
    max_seconds = settings.CHATTERSIFT_REDDIT_FAILURE_BACKOFF_MAX_SECONDS
    backoff_seconds = min(
        base_seconds * (2 ** max(consecutive_failures - 1, 0)),
        max_seconds,
    )
    return timezone.now() + timedelta(seconds=backoff_seconds)


def _state_lookup(spec: RedditFeedSpec) -> dict[str, str]:
    """Build ORM lookup kwargs for a feed spec's persisted scheduling state."""
    return cast("dict[str, str]", asdict(_state_identity(spec)))


def _state_identity(spec: RedditFeedSpec) -> _FeedStateIdentity:
    """Project a feed spec into the dataclass identity used across scheduling helpers."""
    return _FeedStateIdentity(
        kind=spec.kind,
        format=spec.format,
        subreddit=normalize_subreddit(spec.subreddit),
        query_fingerprint=spec.query_fingerprint,
    )


def _state_identity_from_state(state: SubredditFetchState) -> _FeedStateIdentity:
    """Project a persisted fetch-state row into its comparable identity tuple."""
    return _FeedStateIdentity(
        kind=cast("str", state.kind),
        format=cast("str", state.format),
        subreddit=normalize_subreddit(cast("str", state.subreddit)),
        query_fingerprint=cast("str", state.query_fingerprint),
    )
