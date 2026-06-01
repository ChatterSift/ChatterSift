from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.conf import settings
from litellm import completion

from chattersift.core.extension_points import get_semantic_credentials

from .contracts import MatchDecision
from .contracts import MatchRequest
from .contracts import MonitorMatchMode

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .contracts import MonitorIntent
    from .contracts import RedditItemPayload

logger = logging.getLogger(__name__)


class SemanticMatchError(RuntimeError):
    """Raised when a semantic decision cannot be completed safely."""


@dataclass(frozen=True, kw_only=True)
class SemanticEvaluationProblem:
    """Diagnostic for a semantic decision skipped during ingestion."""

    monitor_id: int
    reddit_id: str
    error_type: str
    message: str


@dataclass(frozen=True, kw_only=True)
class SemanticEvaluationContext:
    """Shared semantic evaluator state for one feed pass."""

    decisions: list[MatchDecision]
    semantic_evaluator: RedditMatcher
    problem_collector: list[SemanticEvaluationProblem] | None
    max_semantic_calls: int


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

    Keyword requests use normalized keyword containment to produce a
    MatchDecision. Posts match against title and body; comments match against
    only the comment body so post context cannot create false comment matches.
    """

    def evaluate(self, request: MatchRequest) -> MatchDecision:
        """Return whether any monitor keyword appears in the Reddit item."""
        monitor_id = request.intent.monitor_id
        if monitor_id is None:
            missing_monitor_id = "Match requests must include a persisted monitor id."
            raise ValueError(missing_monitor_id)

        searchable_text = _keyword_searchable_text(request.item)
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
            match_mode=MonitorMatchMode.KEYWORD,
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
        monitor_id = request.intent.monitor_id
        if monitor_id is None:
            missing_monitor_id = "Match requests must include a persisted monitor id."
            raise ValueError(missing_monitor_id)
        credentials = get_semantic_credentials(user_id=request.intent.user_id)
        if not credentials.model:
            missing_model = "CHATTERSIFT_SEMANTIC_LLM_MODEL is required for semantic matching."
            raise SemanticMatchError(missing_model)

        text = _semantic_searchable_text(request.item)
        if not text.strip():
            return MatchDecision(
                monitor_id=monitor_id,
                reddit_id=request.item.reddit_id,
                matched=False,
                confidence=0.0,
                match_mode=request.intent.match_mode,
                reason="semantic:no_text",
            )

        try:
            response = completion(
                model=credentials.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a strict binary classifier for Reddit monitoring intents. "
                            "Return exactly one JSON object with these top-level keys: "
                            "matched, confidence, and reason. "
                            "matched must be a boolean true or false for the entire Reddit item. "
                            "confidence must be a number from 0 to 1. "
                            "reason must be a short string. "
                            "Do not return arrays, nested decision objects, a matches key, or per-match results."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            "Decide whether the Reddit content satisfies the monitoring intent.\n"
                            "Respond only with JSON in this exact shape: "
                            '{"matched": false, "confidence": 0.0, "reason": "short reason"}\n\n'
                            f"Monitoring intent:\n{request.intent.semantic_description}\n\n"
                            f"Reddit content:\n{_truncate_text(text)}"
                        ),
                    },
                ],
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=settings.CHATTERSIFT_SEMANTIC_LLM_MAX_TOKENS,
                timeout=settings.CHATTERSIFT_SEMANTIC_LLM_TIMEOUT_SECONDS,
                api_base=credentials.base_url or None,
                api_key=credentials.api_key or None,
            )
        except Exception as error:
            raise SemanticMatchError(str(error)) from error

        content = _completion_content(response)
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as error:
            invalid_json = "Semantic matcher returned invalid JSON."
            raise SemanticMatchError(invalid_json) from error

        if not isinstance(parsed, dict):
            invalid_shape = "Semantic matcher returned an invalid decision shape: expected a JSON object."
            raise SemanticMatchError(invalid_shape)

        matched = _semantic_matched_value(parsed)

        confidence = _bounded_confidence(parsed.get("confidence"))
        reason = str(parsed.get("reason") or "semantic:decision")[:500]
        return MatchDecision(
            monitor_id=monitor_id,
            reddit_id=request.item.reddit_id,
            matched=matched,
            confidence=confidence,
            match_mode=request.intent.match_mode,
            reason=reason,
        )


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
    semantic_problem_collector: list[SemanticEvaluationProblem] | None = None,
    semantic_max_calls: int | None = None,
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
    max_semantic_calls = (
        settings.CHATTERSIFT_SEMANTIC_MATCH_MAX_CALLS_PER_FEED if semantic_max_calls is None else semantic_max_calls
    )
    semantic_call_count = 0

    decisions: list[MatchDecision] = []
    semantic_context = SemanticEvaluationContext(
        decisions=decisions,
        semantic_evaluator=semantic_evaluator,
        problem_collector=semantic_problem_collector,
        max_semantic_calls=max_semantic_calls,
    )
    for request in requests:
        if request.intent.match_mode == MonitorMatchMode.KEYWORD:
            decisions.append(keyword_evaluator.evaluate(request))
        elif request.intent.match_mode == MonitorMatchMode.SEMANTIC:
            semantic_call_count = _evaluate_semantic_request(
                request,
                context=semantic_context,
                semantic_call_count=semantic_call_count,
            )
        elif request.intent.match_mode == MonitorMatchMode.KEYWORD_SEMANTIC:
            keyword_decision = keyword_evaluator.evaluate(request)
            if not keyword_decision.matched:
                decisions.append(
                    MatchDecision(
                        monitor_id=keyword_decision.monitor_id,
                        reddit_id=keyword_decision.reddit_id,
                        matched=False,
                        confidence=0.0,
                        match_mode=MonitorMatchMode.KEYWORD_SEMANTIC,
                        reason="keyword_semantic:keyword_not_found",
                    ),
                )
                continue
            semantic_call_count = _evaluate_semantic_request(
                request,
                context=semantic_context,
                semantic_call_count=semantic_call_count,
            )

    return decisions


def _keyword_searchable_text(item: RedditItemPayload) -> str:
    """Return normalized item text used by keyword matching evaluators."""
    if item.item_type == "comment":
        return item.body.casefold()
    return f"{item.title}\n{item.body}".casefold()


def _evaluate_semantic_request(
    request: MatchRequest,
    *,
    context: SemanticEvaluationContext,
    semantic_call_count: int,
) -> int:
    """Evaluate one semantic request, recording diagnostics instead of raising."""
    monitor_id = request.intent.monitor_id
    if monitor_id is None:
        return semantic_call_count
    if semantic_call_count >= context.max_semantic_calls:
        _record_semantic_problem(
            context.problem_collector,
            monitor_id=monitor_id,
            reddit_id=request.item.reddit_id,
            error_type="budget_exhausted",
            message="Semantic match call budget exhausted for this feed.",
        )
        return semantic_call_count

    try:
        context.decisions.append(context.semantic_evaluator.evaluate(request))
        return semantic_call_count + 1
    except Exception as error:  # noqa: BLE001
        logger.warning(
            "Semantic Reddit match failed; monitor_id=%s reddit_id=%s error_type=%s error=%s",
            monitor_id,
            request.item.reddit_id,
            error.__class__.__name__,
            error,
            exc_info=True,
        )
        _record_semantic_problem(
            context.problem_collector,
            monitor_id=monitor_id,
            reddit_id=request.item.reddit_id,
            error_type=error.__class__.__name__,
            message=str(error),
        )
        return semantic_call_count + 1


def _record_semantic_problem(
    problem_collector: list[SemanticEvaluationProblem] | None,
    *,
    monitor_id: int,
    reddit_id: str,
    error_type: str,
    message: str,
) -> None:
    """Append a semantic diagnostic when the caller wants feed-level reporting."""
    if problem_collector is None:
        return
    problem_collector.append(
        SemanticEvaluationProblem(
            monitor_id=monitor_id,
            reddit_id=reddit_id,
            error_type=error_type,
            message=message[:1000],
        ),
    )


def _semantic_searchable_text(item: RedditItemPayload) -> str:
    """Return item content supplied to semantic matching."""
    if item.item_type == "comment":
        return item.body
    return f"Title: {item.title}\n\nBody: {item.body}"


def _truncate_text(value: str) -> str:
    """Bound semantic matcher input to configured character limits."""
    max_chars = settings.CHATTERSIFT_SEMANTIC_MATCH_MAX_INPUT_CHARS
    if len(value) <= max_chars:
        return value
    return value[:max_chars].rstrip()


def _completion_content(response) -> str:
    """Extract JSON text from a LiteLLM completion response."""
    if isinstance(response, dict):
        try:
            content = response["choices"][0]["message"]["content"]
        except (IndexError, KeyError, TypeError) as error:
            no_content = "Semantic matcher returned no content."
            raise SemanticMatchError(no_content) from error
        if not isinstance(content, str):
            non_text_content = "Semantic matcher returned non-text content."
            raise SemanticMatchError(non_text_content)
        return content

    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, KeyError, TypeError) as error:
        no_content = "Semantic matcher returned no content."
        raise SemanticMatchError(no_content) from error
    if not isinstance(content, str):
        non_text_content = "Semantic matcher returned non-text content."
        raise SemanticMatchError(non_text_content)
    return content


def _semantic_matched_value(parsed: dict[str, object]) -> bool:
    """Return the semantic match boolean from a model decision object."""
    if "matched" not in parsed:
        keys = ", ".join(sorted(str(key) for key in parsed)) or "-"
        invalid_shape = f"Semantic matcher returned an invalid decision shape: missing 'matched' key; keys={keys}."
        raise SemanticMatchError(invalid_shape)

    matched = parsed["matched"]
    if isinstance(matched, bool):
        return matched
    if isinstance(matched, str):
        normalized = matched.strip().casefold()
        if normalized == "true":
            return True
        if normalized == "false":
            return False

    invalid_shape = (
        "Semantic matcher returned an invalid decision shape: "
        f"'matched' must be a boolean; got {type(matched).__name__}."
    )
    raise SemanticMatchError(invalid_shape)


def _bounded_confidence(value: object) -> float | None:
    """Coerce model confidence to the persisted 0.0-1.0 range."""
    if value is None or not isinstance(value, int | float | str):
        return None
    try:
        confidence = float(value)
    except TypeError, ValueError:
        return None
    return max(0.0, min(confidence, 1.0))
