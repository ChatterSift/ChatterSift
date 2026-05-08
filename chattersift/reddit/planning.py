from __future__ import annotations

import hashlib
import re

from chattersift.tracking.models import Monitor

from .contracts import MonitorIntent
from .contracts import MonitorMatchMode
from .contracts import RedditFeedFormat
from .contracts import RedditFeedKind
from .contracts import RedditFeedSpec
from .contracts import SearchQueryGroup


def build_monitor_intents_for_active_monitors() -> list[MonitorIntent]:
    """Return normalized user-facing intents from active core monitors.

    Input:
        Active Monitor rows in the public core deployment. The core deployment
        may contain one or many Django users; user identity belongs to the
        MonitorIntent, not to feed planning.

    Output:
        MonitorIntent rows that preserve ownership while hiding Reddit feed
        mechanics from users.
    """
    intents: list[MonitorIntent] = []
    active_monitors = Monitor.objects.filter(is_active=True).select_related("user")
    for monitor in active_monitors:
        subreddit = normalize_subreddit(monitor.subreddit)
        keyword = normalize_keyword(monitor.keyword)
        if not subreddit or not keyword:
            continue

        intents.append(
            MonitorIntent(
                subreddit=subreddit,
                keywords=(keyword,),
                match_mode=MonitorMatchMode.KEYWORD,
                monitor_id=monitor.pk,
                user_id=monitor.user_id,
            ),
        )

    return intents


def build_search_query_groups_for_monitor_intents(
    intents: list[MonitorIntent],
    *,
    preferred_format: RedditFeedFormat,
) -> list[SearchQueryGroup]:
    """Return keyword search groups derived from monitor intents.

    Input:
        MonitorIntent rows with keyword terms and preferred Reddit response
        format.

    Output:
        SearchQueryGroup rows packed by subreddit for efficient search feeds.
        For RSS keyword matching, planners should produce POST_SEARCH groups
        only because Reddit does not support comment search through RSS, so
        comments are collected through COMMENT_STREAM. For JSON keyword
        matching, planners should produce POST_SEARCH and COMMENT_SEARCH groups.
        Semantic-only intents should not produce search groups because
        natural-language descriptions are not reliable Reddit search queries.
    """
    feed_format = normalize_feed_format(preferred_format)
    grouped_keywords: dict[str, set[str]] = {}  # subreddit -> keywords

    for intent in intents:
        if intent.match_mode != MonitorMatchMode.KEYWORD:
            continue

        subreddit = normalize_subreddit(intent.subreddit)
        keywords = {normalize_keyword(keyword) for keyword in intent.keywords}
        keywords.discard("")
        if not subreddit or not keywords:
            continue

        grouped_keywords.setdefault(subreddit, set()).update(keywords)

    groups: list[SearchQueryGroup] = []
    for subreddit in sorted(grouped_keywords):
        keywords = tuple(sorted(grouped_keywords[subreddit], key=str.casefold))
        query = build_reddit_search_query(keywords)
        if not query:
            continue

        groups.append(
            SearchQueryGroup(
                kind=RedditFeedKind.POST_SEARCH,
                subreddit=subreddit,
                keywords=keywords,
                query=query,
                query_fingerprint=fingerprint_query(query),
            ),
        )
        if feed_format.value == "json":
            groups.append(
                SearchQueryGroup(
                    kind=RedditFeedKind.COMMENT_SEARCH,
                    subreddit=subreddit,
                    keywords=keywords,
                    query=query,
                    query_fingerprint=fingerprint_query(query),
                ),
            )

    return groups


def build_feed_specs_for_monitor_intents(
    intents: list[MonitorIntent],
    *,
    preferred_format: RedditFeedFormat,
) -> list[RedditFeedSpec]:
    """Return internal feed specs required to satisfy monitor intents.

    Input:
        MonitorIntent rows and the preferred Reddit feed format.

    Output:
        RedditFeedSpec rows with no user identity. The required matrix is:
        KEYWORD + RSS -> POST_SEARCH + COMMENT_STREAM.
        KEYWORD + JSON -> POST_SEARCH + COMMENT_SEARCH.
        SEMANTIC + RSS -> POST_STREAM + COMMENT_STREAM.
        SEMANTIC + JSON -> POST_STREAM + COMMENT_STREAM.
    """
    feed_format = normalize_feed_format(preferred_format)
    specs_by_identity: dict[tuple[str, str, str, str], RedditFeedSpec] = {}

    for group in build_search_query_groups_for_monitor_intents(
        intents,
        preferred_format=feed_format,
    ):
        spec = RedditFeedSpec(
            kind=group.kind,
            format=feed_format,
            subreddit=group.subreddit,
            query=group.query,
            query_fingerprint=group.query_fingerprint,
        )
        specs_by_identity[_feed_spec_identity(spec)] = spec

    for subreddit, needs_post_stream, needs_comment_stream in _stream_requirements(
        intents,
        feed_format,
    ):
        if needs_post_stream:
            spec = RedditFeedSpec(
                kind=RedditFeedKind.POST_STREAM,
                format=feed_format,
                subreddit=subreddit,
            )
            specs_by_identity[_feed_spec_identity(spec)] = spec
        if needs_comment_stream:
            spec = RedditFeedSpec(
                kind=RedditFeedKind.COMMENT_STREAM,
                format=feed_format,
                subreddit=subreddit,
            )
            specs_by_identity[_feed_spec_identity(spec)] = spec

    return [specs_by_identity[key] for key in sorted(specs_by_identity)]


def build_feed_specs_for_active_monitors(
    *,
    preferred_format: RedditFeedFormat,
) -> list[RedditFeedSpec]:
    """Return internal feed specs planned from active core monitors.

    Input:
        Active Monitor rows and preferred Reddit response format.

    Output:
        Feed specs for the public core scheduler. The core does not expose feed
        combining as a multi-user feature, but feed specs still omit user
        identity so duplicate work can be reduced within one deployment.
    """
    intents = build_monitor_intents_for_active_monitors()
    return build_feed_specs_for_monitor_intents(
        intents,
        preferred_format=preferred_format,
    )


def normalize_feed_format(feed_format: RedditFeedFormat) -> RedditFeedFormat:
    """Return a RedditFeedFormat enum value from string-like settings input."""
    return (
        feed_format
        if isinstance(feed_format, RedditFeedFormat)
        else RedditFeedFormat(feed_format)
    )


def normalize_subreddit(value: str) -> str:
    """Return a stable subreddit token without a user-facing r/ prefix."""
    return value.strip().removeprefix("/r/").removeprefix("r/").strip()


def normalize_keyword(value: str) -> str:
    """Return a compact keyword value suitable for matching and search."""
    return re.sub(r"\s+", " ", value).strip()


def build_reddit_search_query(keywords: tuple[str, ...]) -> str:
    """Return one Reddit OR query for normalized keyword terms."""
    quoted_terms = [_quote_query_term(keyword) for keyword in keywords if keyword]
    return " OR ".join(quoted_terms)


def fingerprint_query(query: str) -> str:
    """Return a stable short fingerprint for a generated Reddit query."""
    normalized_query = normalize_keyword(query).casefold()
    return hashlib.sha256(normalized_query.encode()).hexdigest()[:16]


def _stream_requirements(
    intents: list[MonitorIntent],
    feed_format: RedditFeedFormat,
) -> list[tuple[str, bool, bool]]:
    requirements: dict[str, tuple[bool, bool]] = {}

    for intent in intents:
        subreddit = normalize_subreddit(intent.subreddit)
        if not subreddit:
            continue

        needs_post_stream, needs_comment_stream = requirements.get(
            subreddit,
            (False, False),
        )
        if intent.match_mode == MonitorMatchMode.SEMANTIC:
            needs_post_stream = True
            needs_comment_stream = True
        elif (
            intent.match_mode == MonitorMatchMode.KEYWORD and feed_format.value == "rss"
        ):
            needs_comment_stream = True

        requirements[subreddit] = (needs_post_stream, needs_comment_stream)

    return [
        (subreddit, needs_post_stream, needs_comment_stream)
        for subreddit, (needs_post_stream, needs_comment_stream) in sorted(
            requirements.items(),
        )
    ]


def _feed_spec_identity(spec: RedditFeedSpec) -> tuple[str, str, str, str]:
    return (spec.kind, spec.format, spec.subreddit.casefold(), spec.query_fingerprint)


def _quote_query_term(keyword: str) -> str:
    escaped_keyword = keyword.replace('"', '\\"')
    return f'"{escaped_keyword}"'
