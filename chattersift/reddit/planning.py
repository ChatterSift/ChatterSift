from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .interfaces import MonitorIntent
    from .interfaces import RedditFeedFormat
    from .interfaces import RedditFeedSpec
    from .interfaces import SearchQueryGroup


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
    raise NotImplementedError


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
    raise NotImplementedError


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
    raise NotImplementedError


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
    raise NotImplementedError
