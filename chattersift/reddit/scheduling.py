from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from .interfaces import FetchResult
    from .interfaces import RedditFeedSpec


def get_due_feed_specs(*, limit: int | None = None) -> list[RedditFeedSpec]:
    """Return feed specs that are eligible to fetch according to core state.

    Input:
        Optional maximum number of feed specs.

    Output:
        Feed specs whose persisted fetch state says they are due. The state
        model should be keyed by kind, format, subreddit, and
        query_fingerprint.
    """
    raise NotImplementedError


def mark_feed_success(spec: RedditFeedSpec, result: FetchResult) -> None:
    """Record successful fetch state for a feed spec.

    Input:
        Feed spec plus its successful FetchResult.

    Output:
        Persisted success state, including last success time, last seen item,
        cleared or reduced failure state, and next eligible fetch time.
    """
    raise NotImplementedError


def mark_feed_failure(spec: RedditFeedSpec, error: Exception) -> None:
    """Record failed fetch state and advance backoff for a feed spec.

    Input:
        Feed spec plus fetch, parse, HTTP, timeout, or rate-limit exception.

    Output:
        Persisted failure state, consecutive failure count, last error, and next
        eligible fetch time.
    """
    raise NotImplementedError


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
    raise NotImplementedError
