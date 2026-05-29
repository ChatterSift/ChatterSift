from __future__ import annotations

import logging
from email.utils import getaddresses
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import transaction

from chattersift.alerts.services import enqueue_immediate_match_notifications
from chattersift.alerts.tasks import send_mail
from chattersift.tracking.models import Match

from .clients import RedditClient
from .clients import build_default_reddit_client
from .contracts import FetchResult
from .contracts import IngestionResult
from .matching import KeywordRedditMatcher
from .matching import SemanticEvaluationProblem
from .matching import build_match_requests
from .matching import evaluate_match_requests
from .models import RedditItem
from .planning import build_monitor_intents_for_active_monitors
from .scheduling import get_due_feed_specs
from .scheduling import mark_feed_failure
from .scheduling import mark_feed_success

if TYPE_CHECKING:
    from .contracts import MatchRequest
    from .contracts import RedditFeedSpec
    from .matching import RedditMatcher

MISSING_PAYLOAD_FIELD = "Payload is missing a required RedditItem field."
logger = logging.getLogger(__name__)
ADMIN_TUPLE_LENGTH = 2


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
    feed_client = client or build_default_reddit_client()

    try:
        payloads = feed_client.fetch_feed(spec)
        result = _upsert_and_match_payloads(
            spec,
            payloads,
            keyword_matcher=keyword_matcher,
            semantic_matcher=semantic_matcher,
        )
    except Exception as error:
        mark_feed_failure(spec, error)
        raise

    mark_feed_success(spec, result)
    return result


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
    attempted_count = 0
    succeeded_count = 0
    failed_count = 0
    fetched_count = 0
    cached_count = 0
    matched_count = 0

    for spec in get_due_feed_specs(limit=limit):
        attempted_count += 1
        try:
            result = fetch_feed_normalize_and_match(
                spec,
                client=client,
                keyword_matcher=keyword_matcher,
                semantic_matcher=semantic_matcher,
            )
        except Exception as error:  # noqa: BLE001
            logger.warning(
                "Reddit feed fetch failed; kind=%s format=%s subreddit=%s query_fingerprint=%s error_type=%s error=%s",
                spec.kind,
                spec.format,
                spec.subreddit,
                spec.query_fingerprint,
                error.__class__.__name__,
                error,
                exc_info=True,
            )
            failed_count += 1
            continue

        succeeded_count += 1
        fetched_count += result.fetched_count
        cached_count += result.cached_count
        matched_count += result.matched_count

    return IngestionResult(
        attempted_count=attempted_count,
        succeeded_count=succeeded_count,
        failed_count=failed_count,
        fetched_count=fetched_count,
        cached_count=cached_count,
        matched_count=matched_count,
    )


@transaction.atomic
def _upsert_and_match_payloads(
    spec: RedditFeedSpec,
    payloads: list,
    *,
    keyword_matcher: RedditMatcher | None,
    semantic_matcher: RedditMatcher | None,
) -> FetchResult:
    """Upsert fetched payloads, evaluate monitor matches, and enqueue notifications."""
    valid_payloads = []
    matchable_payloads = []
    cached_count = 0
    skipped_count = 0
    last_seen_fullname = ""

    for payload in payloads:
        if not last_seen_fullname:
            last_seen_fullname = payload.reddit_id

        try:
            _, did_upsert = _upsert_item(payload)
        except TypeError, ValueError:
            skipped_count += 1
            continue

        valid_payloads.append(payload)
        cached_count += int(did_upsert)
        if did_upsert:
            matchable_payloads.append(payload)

    intents = build_monitor_intents_for_active_monitors()
    requests = _filter_requests_without_existing_matches(build_match_requests(intents, matchable_payloads))
    semantic_problems: list[SemanticEvaluationProblem] = []
    decisions = evaluate_match_requests(
        requests,
        keyword_matcher=keyword_matcher or KeywordRedditMatcher(),
        semantic_matcher=semantic_matcher,
        semantic_problem_collector=semantic_problems,
    )
    created_match_ids = _persist_match_decisions(decisions, valid_payloads)
    _notify_admins_of_semantic_problems(spec, semantic_problems)
    enqueue_immediate_match_notifications(created_match_ids)

    return FetchResult(
        spec=spec,
        fetched_count=len(payloads),
        cached_count=cached_count,
        matched_count=len(created_match_ids),
        skipped_count=skipped_count,
        status_code=None,
        last_seen_fullname=last_seen_fullname,
    )


def _upsert_item(payload) -> tuple[RedditItem, bool]:
    """Insert or update one item and report whether persisted data changed."""
    _validate_payload(payload)
    defaults = {
        "item_type": payload.item_type,
        "subreddit": payload.subreddit,
        "author": payload.author,
        "title": payload.title,
        "body": payload.body,
        "permalink": payload.permalink,
        "occurred_at": payload.occurred_at,
    }
    item, created = RedditItem.objects.get_or_create(
        reddit_id=payload.reddit_id,
        defaults=defaults,
    )
    if created:
        return item, True

    changed_fields = [field_name for field_name, value in defaults.items() if getattr(item, field_name) != value]
    if not changed_fields:
        return item, False

    for field_name in changed_fields:
        setattr(item, field_name, defaults[field_name])
    item.save(update_fields=changed_fields)
    return item, True


def _filter_requests_without_existing_matches(requests: list[MatchRequest]) -> list[MatchRequest]:
    """Return requests that do not already have a persisted Match row."""
    if not requests:
        return []

    requested_pairs = {
        (request.intent.monitor_id, request.item.reddit_id)
        for request in requests
        if request.intent.monitor_id is not None
    }
    existing_pairs = set(
        Match.objects.filter(
            monitor_id__in={monitor_id for monitor_id, _ in requested_pairs},
            reddit_item_id__in={reddit_id for _, reddit_id in requested_pairs},
        ).values_list("monitor_id", "reddit_item_id"),
    )

    return [request for request in requests if _match_request_pair(request) not in existing_pairs]


def _match_request_pair(request: MatchRequest) -> tuple[int | None, str]:
    """Return the persisted Match identity represented by a match request."""
    return request.intent.monitor_id, request.item.reddit_id


def _persist_match_decisions(decisions, payloads: list) -> list[int]:
    """Persist positive match decisions and return primary keys created this run."""
    payloads_by_id = {payload.reddit_id: payload for payload in payloads}
    created_match_ids: list[int] = []

    for decision in decisions:
        if not decision.matched:
            continue

        payload = payloads_by_id.get(decision.reddit_id)
        if payload is None:
            continue

        match, created = Match.objects.get_or_create(
            monitor_id=decision.monitor_id,
            reddit_item_id=decision.reddit_id,
            defaults={
                "title": payload.title,
                "body": payload.body,
                "permalink": payload.permalink,
                "occurred_at": payload.occurred_at,
                "match_mode": decision.match_mode,
                "confidence": decision.confidence,
                "match_reason": decision.reason,
            },
        )
        if created and match.pk is not None:
            created_match_ids.append(match.pk)

    return created_match_ids


def _validate_payload(payload) -> None:
    """Ensure payload has required fields before any persistence attempt."""
    required_values = (
        payload.reddit_id,
        payload.item_type,
        payload.subreddit,
        payload.permalink,
        payload.occurred_at,
    )
    if not all(required_values):
        raise ValueError(MISSING_PAYLOAD_FIELD)


def _notify_admins_of_semantic_problems(
    spec: RedditFeedSpec,
    problems: list[SemanticEvaluationProblem],
) -> None:
    """Send one admin email for semantic decisions skipped on this feed."""
    if not problems:
        return

    by_type: dict[str, int] = {}
    for problem in problems:
        by_type[problem.error_type] = by_type.get(problem.error_type, 0) + 1
    examples = "\n".join(
        f"- monitor_id={problem.monitor_id} reddit_id={problem.reddit_id} {problem.error_type}: {problem.message}"
        for problem in problems[:5]
    )
    counts = ", ".join(f"{error_type}={count}" for error_type, count in sorted(by_type.items()))
    subject = "Chattersift semantic matching skipped decisions"
    message = (
        "Semantic matching skipped one or more decisions for a Reddit feed.\n\n"
        f"Feed: kind={spec.kind} format={spec.format} subreddit={spec.subreddit} "
        f"query_fingerprint={spec.query_fingerprint or '-'}\n"
        f"Skipped decisions: {len(problems)}\n"
        f"Counts: {counts}\n\n"
        f"Representative errors:\n{examples}"
    )
    try:
        recipients = _admin_email_recipients()
        if not recipients:
            return
        send_mail.delay(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
        )
    except Exception as error:  # noqa: BLE001
        logger.warning(
            "Failed to send semantic matching admin email; kind=%s format=%s subreddit=%s error=%s",
            spec.kind,
            spec.format,
            spec.subreddit,
            error,
            exc_info=True,
        )


def _admin_email_recipients() -> list[str]:
    """Return admin email recipients from tuple or string-style ADMINS settings."""
    recipients: list[str] = []
    for admin in settings.ADMINS:
        if isinstance(admin, tuple) and len(admin) == ADMIN_TUPLE_LENGTH:
            recipients.append(admin[1])
        elif isinstance(admin, str):
            recipients.extend(email for _, email in getaddresses([admin]) if email)
    return recipients
