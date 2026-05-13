from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import transaction

from chattersift.tracking.models import Match

from .clients import RedditClient
from .clients import build_default_reddit_client
from .contracts import FetchResult
from .contracts import IngestionResult
from .matching import KeywordRedditMatcher
from .matching import build_match_requests
from .matching import evaluate_match_requests
from .models import RedditItem
from .planning import build_monitor_intents_for_active_monitors
from .scheduling import get_due_feed_specs
from .scheduling import mark_feed_failure
from .scheduling import mark_feed_success

if TYPE_CHECKING:
    from .contracts import RedditFeedSpec
    from .matching import RedditMatcher

MISSING_PAYLOAD_FIELD = "Payload is missing a required RedditItem field."


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
    upserted_count = 0
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
        except Exception:  # noqa: BLE001
            failed_count += 1
            continue

        succeeded_count += 1
        fetched_count += result.fetched_count
        upserted_count += result.upserted_count
        matched_count += result.matched_count

    return IngestionResult(
        attempted_count=attempted_count,
        succeeded_count=succeeded_count,
        failed_count=failed_count,
        fetched_count=fetched_count,
        upserted_count=upserted_count,
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
    valid_payloads = []
    upserted_count = 0
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
        upserted_count += int(did_upsert)

    intents = build_monitor_intents_for_active_monitors()
    requests = build_match_requests(intents, valid_payloads)
    decisions = evaluate_match_requests(
        requests,
        keyword_matcher=keyword_matcher or KeywordRedditMatcher(),
        semantic_matcher=semantic_matcher,
    )
    matched_count = _persist_match_decisions(decisions, valid_payloads)

    return FetchResult(
        spec=spec,
        fetched_count=len(payloads),
        upserted_count=upserted_count,
        matched_count=matched_count,
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


def _persist_match_decisions(decisions, payloads: list) -> int:
    payloads_by_id = {payload.reddit_id: payload for payload in payloads}
    created_count = 0

    for decision in decisions:
        if not decision.matched:
            continue

        payload = payloads_by_id.get(decision.reddit_id)
        if payload is None:
            continue

        _, created = Match.objects.get_or_create(
            monitor_id=decision.monitor_id,
            reddit_item_id=decision.reddit_id,
            defaults={
                "title": payload.title,
                "body": payload.body,
                "permalink": payload.permalink,
                "occurred_at": payload.occurred_at,
            },
        )
        created_count += int(created)

    return created_count


def _validate_payload(payload) -> None:
    required_values = (
        payload.reddit_id,
        payload.item_type,
        payload.subreddit,
        payload.permalink,
        payload.occurred_at,
    )
    if not all(required_values):
        raise ValueError(MISSING_PAYLOAD_FIELD)
