from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .clients import RedditClient
    from .interfaces import FetchResult
    from .interfaces import IngestionResult
    from .interfaces import RedditFeedSpec
    from .matching import RedditMatcher


def fetch_feed_normalize_and_match(
    spec: RedditFeedSpec,
    *,
    client: RedditClient | None = None,
    keyword_matcher: RedditMatcher | None = None,
    semantic_matcher: RedditMatcher | None = None,
) -> FetchResult:
    """Fetch one feed, normalize items, upsert them, and match monitors.

    Input:
        One feed spec plus optional client and matcher overrides.

    Output:
        FetchResult for the attempted feed. The implementation owns fetch-state
        success/failure updates. Matching should evaluate normalized content
        against relevant MonitorIntent rows, regardless of whether the source
        feed produced posts or comments.
    """
    raise NotImplementedError


def fetch_due_feeds(
    *,
    client: RedditClient | None = None,
    keyword_matcher: RedditMatcher | None = None,
    semantic_matcher: RedditMatcher | None = None,
    limit: int | None = None,
) -> IngestionResult:
    """Fetch due feeds using the public core scheduler and state model.

    Input:
        Optional client override, optional matcher overrides, and optional feed
        limit.

    Output:
        Aggregate IngestionResult for all attempted due feeds. This is the main
        public-core loop for a self-hosted deployment and remains deployable
        without managed infrastructure.
    """
    raise NotImplementedError
