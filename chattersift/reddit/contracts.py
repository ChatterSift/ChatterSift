from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import models

if TYPE_CHECKING:
    from datetime import datetime


class RedditFeedKind(models.TextChoices):
    """Internal Reddit collection units supported by ingestion.

    These are not user-facing choices. A user describes what to monitor at the
    MonitorIntent level; planners decide which feed kinds are required.

    POST_SEARCH uses a generated subreddit search query and returns post
    candidates. COMMENT_SEARCH uses Reddit's JSON-only comment search and
    returns comment candidates. POST_STREAM uses the latest subreddit post
    listing and returns recent posts without a search query. COMMENT_STREAM uses
    the latest subreddit comments listing and returns recent comments without a
    search query.
    """

    POST_SEARCH = "post_search", "Post search"
    COMMENT_SEARCH = "comment_search", "Comment search"
    POST_STREAM = "post_stream", "Post stream"
    COMMENT_STREAM = "comment_stream", "Comment stream"


class RedditFeedFormat(models.TextChoices):
    """Transport format requested from Reddit for one feed.

    RSS is expected to be the conservative default because it is commonly less
    hostile to low-volume unauthenticated use. JSON is part of the v1 interface
    because it is easier to parse and may be preferable for deployments that can
    tolerate its operational behavior.
    """

    RSS = "rss", "RSS"
    JSON = "json", "JSON"


class MonitorMatchMode(models.TextChoices):
    """How fetched Reddit content should be evaluated for a monitor.

    KEYWORD uses deterministic text matching. Posts are matched against title
    and body content; comments are matched against the comment body only.
    SEMANTIC uses a semantic matcher, likely LLM-backed, against the same
    normalized content. The database may start keyword-only; this interface is
    deliberately wider so semantic matching can be added without redesigning
    ingestion.
    """

    KEYWORD = "keyword", "Keyword"
    SEMANTIC = "semantic", "Semantic"
    KEYWORD_SEMANTIC = "keyword_semantic", "Keyword + semantic"


@dataclass(frozen=True, kw_only=True)
class MonitorIntent:
    """User-facing monitoring intent normalized from one monitor row.

    Users should not choose whether Reddit should be searched by posts,
    comments, RSS, or JSON. They specify the subreddit and what they care about;
    planners expand this intent into the feed specs needed to collect candidate
    content. This is consumed by planners and matchers.

    Fields:
        subreddit: Subreddit name without the ``r/`` prefix.
        keywords: Normalized keyword terms for deterministic matching. In v1,
            the existing Monitor.keyword field maps to a one-item tuple.
        match_mode: Matching strategy requested by the monitor.
        semantic_description: Natural-language description of the user's
            interest for semantic matching. Empty for keyword-only monitors.
        monitor_id: Existing Monitor primary key when available. Matching uses
            this to create Match rows.
        user_id: Owning user primary key when available. This is preserved for
            ownership and diagnostics, but feed specs must not include it.
    """

    subreddit: str
    keywords: tuple[str, ...]
    match_mode: MonitorMatchMode = MonitorMatchMode.KEYWORD
    semantic_description: str = ""
    monitor_id: int | None = None
    user_id: int | None = None


@dataclass(frozen=True, kw_only=True)
class RedditFeedSpec:
    """Internal collection unit for one Reddit feed URL.

    Feed specs never contain user identity. Monitor ownership is resolved later
    by matching normalized items against active monitors. The spec provides
    stable identity for clients, planners, schedulers, feed state, locks, and
    ingestion services.

    Fields:
        kind: Internal feed type to collect.
        format: Reddit response format to request.
        subreddit: Subreddit name without the ``r/`` prefix.
        query: Generated Reddit search query for POST_SEARCH and COMMENT_SEARCH
            specs. COMMENT_SEARCH is valid only with JSON because Reddit does
            not provide RSS comment search. Empty for POST_STREAM and
            COMMENT_STREAM specs.
        query_fingerprint: Stable hash of the normalized query for fetch-state
            identity. Empty for stream specs.
    """

    kind: RedditFeedKind
    format: RedditFeedFormat
    subreddit: str
    query: str = ""
    query_fingerprint: str = ""


@dataclass(frozen=True, kw_only=True)
class SearchQueryGroup:
    """Packed keyword terms represented by one search feed.

    This is an internal planning optimization. It does not model monitor
    ownership and does not imply that users selected post-only or comment-only
    monitoring. Planned groups can become search RedditFeedSpec instances.

    Fields:
        kind: Search feed kind that will consume the query. Must be POST_SEARCH
            or COMMENT_SEARCH. COMMENT_SEARCH groups can only become JSON feed
            specs because Reddit does not support comment search through RSS.
        subreddit: Shared subreddit for the grouped keywords.
        keywords: Normalized keyword terms included in the generated query.
        query: Reddit search query, for example ``"mahomes" OR "burrow"``.
        query_fingerprint: Stable hash for dedupe and feed-state identity.
    """

    kind: RedditFeedKind
    subreddit: str
    keywords: tuple[str, ...]
    query: str
    query_fingerprint: str


@dataclass(frozen=True, kw_only=True)
class RedditItemPayload:
    """Normalized in-memory item parsed from Reddit RSS before database upsert.

    The payload is ready for RedditItem upsert after parser normalization.

    Fields:
        reddit_id: Reddit fullname, such as ``t3_...`` or ``t1_...``.
        item_type: Normalized item type compatible with RedditItem choices.
        subreddit: Subreddit name without ``r/``.
        permalink: Canonical Reddit permalink.
        occurred_at: Timestamp from the RSS entry.
        author: Reddit username when present.
        title: Post title or comment context title when present.
        body: Text body extracted from RSS HTML when present.
    """

    reddit_id: str
    item_type: str
    subreddit: str
    permalink: str
    occurred_at: datetime
    author: str = ""
    title: str = ""
    body: str = ""


@dataclass(frozen=True, kw_only=True)
class MatchRequest:
    """One monitor intent evaluated against one normalized Reddit item.

    The request is passed to deterministic or semantic matchers.

    Fields:
        intent: User-facing monitor intent being evaluated.
        item: Normalized Reddit item payload.
    """

    intent: MonitorIntent
    item: RedditItemPayload


@dataclass(frozen=True, kw_only=True)
class MatchDecision:
    """Decision returned by a matcher before Match row persistence.

    This persistence-ready decision is consumed by matching services.

    Fields:
        monitor_id: Monitor primary key that should receive a Match row.
        reddit_id: Reddit item identifier being evaluated.
        matched: Whether the item satisfies the monitor intent.
    confidence: Optional matcher confidence from 0.0 to 1.0. Keyword
            matching can return 1.0 for exact deterministic matches.
        match_mode: Matching strategy that produced this decision.
        reason: Short diagnostic reason suitable for logs/admin views, not a
            user-facing explanation contract.
    """

    monitor_id: int
    reddit_id: str
    matched: bool
    confidence: float | None = None
    match_mode: MonitorMatchMode = MonitorMatchMode.KEYWORD
    reason: str = ""


@dataclass(frozen=True, kw_only=True)
class FetchResult:
    """Result contract for one feed fetch and match pass.

    Public result used by tasks, logs, tests, and extension wrappers.

    Fields:
        spec: Feed spec that was attempted.
        fetched_count: Number of payloads returned by the client.
        cached_count: Number of RedditItem cache rows inserted or updated.
        matched_count: Number of monitor matches created.
        skipped_count: Number of payloads skipped during normalization/upsert.
        status_code: HTTP status code when available.
        last_seen_fullname: Newest Reddit fullname seen during this fetch, used
            by scheduling state.
    """

    spec: RedditFeedSpec
    fetched_count: int
    cached_count: int
    matched_count: int
    skipped_count: int
    status_code: int | None
    last_seen_fullname: str = ""


@dataclass(frozen=True, kw_only=True)
class IngestionResult:
    """Aggregate result contract for a due-feed ingestion run.

    Public aggregate result for periodic tasks and admin views.

    Fields:
        attempted_count: Number of feed specs attempted.
        succeeded_count: Number of successful feed attempts.
        failed_count: Number of failed feed attempts.
        fetched_count: Total fetched payloads.
        cached_count: Total RedditItem cache rows inserted or updated.
        matched_count: Total monitor matches created.
    """

    attempted_count: int
    succeeded_count: int
    failed_count: int
    fetched_count: int
    cached_count: int
    matched_count: int
