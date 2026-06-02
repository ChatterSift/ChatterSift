from __future__ import annotations

from typing import TYPE_CHECKING

from .contracts import RedditFeedFormat
from .contracts import RedditFeedKind
from .contracts import RedditFeedSpec
from .ingestion import fetch_feed_normalize_and_match
from .planning import normalize_subreddit

if TYPE_CHECKING:
    from .clients import RedditClient


def fetch_normalize_and_match(subreddit: str, *, client: RedditClient) -> int:
    """Compatibility wrapper for fetching one subreddit post stream.

    New code should call ``fetch_feed_normalize_and_match`` with an explicit
    RedditFeedSpec. This wrapper remains synchronous and delegates through the
    same client interface.
    """
    result = fetch_feed_normalize_and_match(
        RedditFeedSpec(
            kind=RedditFeedKind.POST_STREAM,
            format=RedditFeedFormat.RSS,
            subreddit=normalize_subreddit(subreddit),
        ),
        client=client,
    )
    return result.matched_count
