from __future__ import annotations

import pytest

from chattersift.reddit.contracts import MonitorIntent
from chattersift.reddit.contracts import MonitorMatchMode
from chattersift.reddit.contracts import RedditFeedFormat
from chattersift.reddit.contracts import RedditFeedKind
from chattersift.reddit.planning import build_feed_specs_for_monitor_intents
from chattersift.reddit.planning import build_monitor_intents_for_active_monitors
from chattersift.reddit.planning import build_search_query_groups_for_monitor_intents
from chattersift.tracking.models import Monitor
from chattersift.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_build_monitor_intents_for_active_monitors() -> None:
    user = UserFactory()
    active_monitor = Monitor.objects.create(
        user=user,
        subreddit="r/django",
        keyword="  Django   Ninja  ",
    )
    Monitor.objects.create(
        user=user,
        subreddit="django",
        keyword="ignored",
        is_active=False,
    )

    intents = build_monitor_intents_for_active_monitors()

    assert intents == [
        MonitorIntent(
            subreddit="django",
            keywords=("Django Ninja",),
            match_mode=MonitorMatchMode.KEYWORD,
            monitor_id=active_monitor.pk,
            user_id=user.pk,
        ),
    ]


def test_active_monitor_specs_combine_same_subreddit_across_users() -> None:
    first_user = UserFactory()
    second_user = UserFactory()
    Monitor.objects.create(user=first_user, subreddit="r/Django", keyword="postgres")
    Monitor.objects.create(
        user=second_user,
        subreddit="/r/django",
        match_mode=MonitorMatchMode.KEYWORD_SEMANTIC,
        keyword="htmx",
        semantic_description="frontend integration issues",
    )

    specs = build_feed_specs_for_monitor_intents(
        build_monitor_intents_for_active_monitors(),
        preferred_format=RedditFeedFormat.JSON,
    )

    assert [(spec.kind, spec.format, spec.subreddit) for spec in specs] == [
        (RedditFeedKind.COMMENT_STREAM, RedditFeedFormat.RSS, "django"),
        (RedditFeedKind.POST_SEARCH, RedditFeedFormat.JSON, "django"),
    ]
    search_spec = next(spec for spec in specs if spec.kind == RedditFeedKind.POST_SEARCH)
    assert search_spec.query == '"htmx" OR "postgres"'


def test_build_rss_feed_specs_for_keyword_intents() -> None:
    intents = [
        MonitorIntent(subreddit="django", keywords=("postgres",), monitor_id=1),
        MonitorIntent(subreddit="django", keywords=("htmx",), monitor_id=2),
    ]

    specs = build_feed_specs_for_monitor_intents(
        intents,
        preferred_format=RedditFeedFormat.RSS,
    )

    assert [(spec.kind, spec.format) for spec in specs] == [
        (RedditFeedKind.COMMENT_STREAM, RedditFeedFormat.RSS),
        (RedditFeedKind.POST_SEARCH, RedditFeedFormat.RSS),
    ]
    search_spec = next(spec for spec in specs if spec.kind == RedditFeedKind.POST_SEARCH)
    assert search_spec.query == '"htmx" OR "postgres"'
    assert search_spec.query_fingerprint


def test_build_json_feed_specs_for_keyword_intents_uses_rss_comment_stream() -> None:
    intents = [MonitorIntent(subreddit="django", keywords=("postgres",), monitor_id=1)]

    specs = build_feed_specs_for_monitor_intents(
        intents,
        preferred_format=RedditFeedFormat.JSON,
    )

    assert [(spec.kind, spec.format) for spec in specs] == [
        (RedditFeedKind.COMMENT_STREAM, RedditFeedFormat.RSS),
        (RedditFeedKind.POST_SEARCH, RedditFeedFormat.JSON),
    ]
    search_spec = next(spec for spec in specs if spec.kind == RedditFeedKind.POST_SEARCH)
    assert search_spec.query == '"postgres"'


def test_build_semantic_feed_specs_use_streams() -> None:
    intents = [
        MonitorIntent(
            subreddit="django",
            keywords=(),
            match_mode=MonitorMatchMode.SEMANTIC,
            semantic_description="Django performance issues",
            monitor_id=1,
        ),
    ]

    specs = build_feed_specs_for_monitor_intents(
        intents,
        preferred_format=RedditFeedFormat.JSON,
    )

    assert [(spec.kind, spec.format, spec.query) for spec in specs] == [
        (RedditFeedKind.COMMENT_STREAM, RedditFeedFormat.RSS, ""),
        (RedditFeedKind.POST_STREAM, RedditFeedFormat.JSON, ""),
    ]


def test_build_search_query_groups_do_not_include_semantic_intents() -> None:
    intents = [
        MonitorIntent(subreddit="django", keywords=("postgres",), monitor_id=1),
        MonitorIntent(
            subreddit="django",
            keywords=(),
            match_mode=MonitorMatchMode.SEMANTIC,
            semantic_description="database discussions",
            monitor_id=2,
        ),
    ]

    groups = build_search_query_groups_for_monitor_intents(
        intents,
        preferred_format=RedditFeedFormat.JSON,
    )

    assert [group.kind for group in groups] == [
        RedditFeedKind.POST_SEARCH,
    ]
    assert all(group.query == '"postgres"' for group in groups)


def test_keyword_semantic_intents_use_keyword_search_specs() -> None:
    intents = [
        MonitorIntent(
            subreddit="django",
            keywords=("postgres",),
            match_mode=MonitorMatchMode.KEYWORD_SEMANTIC,
            semantic_description="deployment incident reports",
            monitor_id=1,
        ),
    ]

    specs = build_feed_specs_for_monitor_intents(
        intents,
        preferred_format=RedditFeedFormat.JSON,
    )

    assert [(spec.kind, spec.query) for spec in specs] == [
        (RedditFeedKind.COMMENT_STREAM, ""),
        (RedditFeedKind.POST_SEARCH, '"postgres"'),
    ]


def test_keyword_and_pure_semantic_intents_use_separate_post_feeds() -> None:
    intents = [
        MonitorIntent(subreddit="r/Django", keywords=("postgres",), monitor_id=1),
        MonitorIntent(
            subreddit="/r/django",
            keywords=(),
            match_mode=MonitorMatchMode.SEMANTIC,
            semantic_description="database outage reports",
            monitor_id=2,
        ),
    ]

    specs = build_feed_specs_for_monitor_intents(
        intents,
        preferred_format=RedditFeedFormat.JSON,
    )

    assert [(spec.kind, spec.format, spec.subreddit, spec.query) for spec in specs] == [
        (RedditFeedKind.COMMENT_STREAM, RedditFeedFormat.RSS, "django", ""),
        (RedditFeedKind.POST_SEARCH, RedditFeedFormat.JSON, "django", '"postgres"'),
        (RedditFeedKind.POST_STREAM, RedditFeedFormat.JSON, "django", ""),
    ]
