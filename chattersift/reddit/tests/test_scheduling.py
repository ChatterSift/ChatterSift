from __future__ import annotations

import pytest

from chattersift.reddit.contracts import FetchResult
from chattersift.reddit.contracts import RedditFeedFormat
from chattersift.reddit.contracts import RedditFeedKind
from chattersift.reddit.scheduling import get_due_feed_specs
from chattersift.reddit.scheduling import mark_feed_success
from chattersift.tracking.models import Monitor
from chattersift.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_get_due_feed_specs_returns_unseen_planned_specs(settings) -> None:
    settings.CHATTERSIFT_REDDIT_FEED_FORMAT = "rss"
    user = UserFactory()
    Monitor.objects.create(user=user, subreddit="django", keyword="postgres")

    specs = get_due_feed_specs()

    assert [(spec.kind, spec.format) for spec in specs] == [
        (RedditFeedKind.COMMENT_STREAM, RedditFeedFormat.RSS),
        (RedditFeedKind.POST_SEARCH, RedditFeedFormat.RSS),
    ]


def test_mark_feed_success_delays_next_fetch(settings) -> None:
    settings.CHATTERSIFT_REDDIT_FEED_FORMAT = "rss"
    user = UserFactory()
    Monitor.objects.create(user=user, subreddit="django", keyword="postgres")
    spec = next(due_spec for due_spec in get_due_feed_specs() if due_spec.kind == RedditFeedKind.POST_SEARCH)

    mark_feed_success(
        spec,
        FetchResult(
            spec=spec,
            fetched_count=1,
            cached_count=1,
            matched_count=0,
            skipped_count=0,
            status_code=None,
            last_seen_fullname="t3_latest",
        ),
    )

    specs = get_due_feed_specs()

    assert [due_spec.kind for due_spec in specs] == [RedditFeedKind.COMMENT_STREAM]


def test_post_search_success_does_not_delay_post_or_comment_streams(settings) -> None:
    settings.CHATTERSIFT_REDDIT_FEED_FORMAT = "json"
    user = UserFactory()
    Monitor.objects.create(user=user, subreddit="r/Django", keyword="postgres")
    Monitor.objects.create(
        user=user,
        subreddit="/r/django",
        match_mode="semantic",
        keyword="",
        semantic_description="database outage reports",
    )
    search_spec = next(due_spec for due_spec in get_due_feed_specs() if due_spec.kind == RedditFeedKind.POST_SEARCH)

    mark_feed_success(
        search_spec,
        FetchResult(
            spec=search_spec,
            fetched_count=1,
            cached_count=1,
            matched_count=0,
            skipped_count=0,
            status_code=None,
            last_seen_fullname="t3_latest",
        ),
    )

    specs = get_due_feed_specs()

    assert [(due_spec.kind, due_spec.format) for due_spec in specs] == [
        (RedditFeedKind.COMMENT_STREAM, RedditFeedFormat.RSS),
        (RedditFeedKind.POST_STREAM, RedditFeedFormat.JSON),
    ]


def test_comment_stream_success_suppresses_only_comment_stream(settings) -> None:
    settings.CHATTERSIFT_REDDIT_FEED_FORMAT = "json"
    user = UserFactory()
    Monitor.objects.create(user=user, subreddit="Django", keyword="postgres")
    Monitor.objects.create(
        user=user,
        subreddit="django",
        match_mode="semantic",
        keyword="",
        semantic_description="database outage reports",
    )
    comment_spec = next(due_spec for due_spec in get_due_feed_specs() if due_spec.kind == RedditFeedKind.COMMENT_STREAM)

    mark_feed_success(
        comment_spec,
        FetchResult(
            spec=comment_spec,
            fetched_count=1,
            cached_count=1,
            matched_count=0,
            skipped_count=0,
            status_code=None,
            last_seen_fullname="t1_latest",
        ),
    )

    specs = get_due_feed_specs()

    assert [(due_spec.kind, due_spec.format) for due_spec in specs] == [
        (RedditFeedKind.POST_SEARCH, RedditFeedFormat.JSON),
        (RedditFeedKind.POST_STREAM, RedditFeedFormat.JSON),
    ]
