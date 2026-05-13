from __future__ import annotations

from typing import TYPE_CHECKING

from .contracts import MatchDecision
from .contracts import MatchRequest
from .contracts import MonitorMatchMode

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .contracts import MonitorIntent
    from .contracts import RedditItemPayload


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
        monitor_id = request.intent.monitor_id
        if monitor_id is None:
            missing_monitor_id = "Match requests must include a persisted monitor id."
            raise ValueError(missing_monitor_id)

        searchable_text = f"{request.item.title}\n{request.item.body}".casefold()
        matched_keyword = next(
            (keyword for keyword in request.intent.keywords if keyword and keyword.casefold() in searchable_text),
            "",
        )
        matched = bool(matched_keyword)
        return MatchDecision(
            monitor_id=monitor_id,
            reddit_id=request.item.reddit_id,
            matched=matched,
            confidence=1.0 if matched else 0.0,
            reason=f"keyword:{matched_keyword}" if matched else "keyword:not_found",
        )


class SemanticRedditMatcher(RedditMatcher):
    """Semantic matcher interface for LLM-backed monitor intents.

    Semantic requests use MonitorIntent.semantic_description and normalized
    RedditItemPayload content to produce a MatchDecision with matched status,
    optional confidence, and a short diagnostic reason. Implementations may call
    an LLM, embeddings service, or a local semantic model.
    """

    def evaluate(self, request: MatchRequest) -> MatchDecision:
        """Return whether the item semantically satisfies the monitor intent."""
        msg = "Configure a concrete semantic Reddit matcher before evaluating semantic requests."
        raise NotImplementedError(msg)


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
    requests: list[MatchRequest] = []
    intent_list = [intent for intent in intents if intent.monitor_id is not None]

    for item in items:
        item_subreddit = item.subreddit.casefold()
        for intent in intent_list:
            if intent.subreddit.casefold() != item_subreddit:
                continue

            requests.append(MatchRequest(intent=intent, item=item))

    return requests


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
    keyword_evaluator = keyword_matcher or KeywordRedditMatcher()
    semantic_evaluator = semantic_matcher or SemanticRedditMatcher()

    decisions: list[MatchDecision] = []
    for request in requests:
        if request.intent.match_mode == MonitorMatchMode.KEYWORD:
            decisions.append(keyword_evaluator.evaluate(request))
        elif request.intent.match_mode == MonitorMatchMode.SEMANTIC:
            decisions.append(semantic_evaluator.evaluate(request))

    return decisions
