from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .interfaces import RedditFeedSpec
    from .interfaces import RedditItemPayload


class RedditClient:
    """Interface for fetching normalized items from a Reddit feed spec.

    Implementations receive a RedditFeedSpec describing one internal collection
    unit, including whether RSS or JSON should be requested, and return parsed
    RedditItemPayload rows. Implementations may raise typed fetch, HTTP,
    timeout, rate-limit, or parse exceptions.
    """

    def fetch_feed(self, spec: RedditFeedSpec) -> list[RedditItemPayload]:
        """Return feed entries normalized as Reddit item payloads."""
        raise NotImplementedError


class RssRedditClient(RedditClient):
    """RSS-backed Reddit client interface for the public core implementation.

    POST_SEARCH specs map to subreddit search RSS URLs. POST_STREAM specs map to
    subreddit post listing RSS URLs. COMMENT_STREAM specs map to subreddit
    comments RSS URLs. COMMENT_SEARCH is not supported here because Reddit does
    not expose comment search as RSS. This class defines the conservative
    deployable public-core transport contract, but contains no implementation in
    this interface-only pass.
    """

    def fetch_feed(self, spec: RedditFeedSpec) -> list[RedditItemPayload]:
        """Fetch and parse the Reddit RSS URL represented by the feed spec."""
        raise NotImplementedError


class JsonRedditClient(RedditClient):
    """JSON-backed Reddit client interface for the public core implementation.

    JSON uses the same RedditItemPayload contract as the RSS client. It is
    included in the v1 interface so parser and transport choices can vary
    without changing planner, scheduler, or matcher contracts. For keyword
    matching, JSON can use both POST_SEARCH and COMMENT_SEARCH specs.
    """

    def fetch_feed(self, spec: RedditFeedSpec) -> list[RedditItemPayload]:
        """Fetch and parse the Reddit JSON URL represented by the feed spec."""
        raise NotImplementedError
