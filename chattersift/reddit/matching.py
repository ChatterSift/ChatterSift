from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .interfaces import MatchDecision
    from .interfaces import MatchRequest
    from .interfaces import MonitorIntent
    from .interfaces import RedditItemPayload


class RedditMatcher:
    """Interface for evaluating monitor intents against fetched Reddit items.

    Implementations evaluate a MatchRequest containing one MonitorIntent and one
    RedditItemPayload, then return a MatchDecision indicating whether a Match row
    should be created.
    """

    def evaluate(self, request: MatchRequest) -> MatchDecision:
        """Return the match decision for one intent/item pair."""
        raise NotImplementedError


class KeywordRedditMatcher(RedditMatcher):
    """Deterministic matcher for keyword-based monitor intents.

    Keyword requests use normalized keyword containment in the fetched title/body
    text to produce a MatchDecision.
    """

    def evaluate(self, request: MatchRequest) -> MatchDecision:
        """Return whether any monitor keyword appears in the Reddit item."""
        raise NotImplementedError


class SemanticRedditMatcher(RedditMatcher):
    """Semantic matcher interface for LLM-backed monitor intents.

    Semantic requests use MonitorIntent.semantic_description and normalized
    RedditItemPayload content to produce a MatchDecision with matched status,
    optional confidence, and a short diagnostic reason. Implementations may call
    an LLM, embeddings service, or a local semantic model.
    """

    def evaluate(self, request: MatchRequest) -> MatchDecision:
        """Return whether the item semantically satisfies the monitor intent."""
        raise NotImplementedError


def build_match_requests(
    intents: Iterable[MonitorIntent],
    items: Iterable[RedditItemPayload],
) -> list[MatchRequest]:
    """Return matcher requests for active intents and fetched items.

    Input:
        Active monitor intents and normalized Reddit items.

    Output:
        MatchRequest list filtered to plausible subreddit/item pairs. The
        implementation should not require users to choose post or comment
        matching; every fetched item is evaluated against relevant intents.
    """
    raise NotImplementedError


def evaluate_match_requests(
    requests: Iterable[MatchRequest],
    *,
    keyword_matcher: RedditMatcher | None = None,
    semantic_matcher: RedditMatcher | None = None,
) -> list[MatchDecision]:
    """Evaluate match requests with the appropriate matching strategy.

    Input:
        MatchRequest rows plus optional matcher overrides.

    Output:
        MatchDecision rows ready for persistence. KEYWORD requests use the
        keyword matcher; SEMANTIC requests use the semantic matcher.
    """
    raise NotImplementedError
