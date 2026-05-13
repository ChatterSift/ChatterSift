from __future__ import annotations

from datetime import UTC
from datetime import datetime

from chattersift.reddit.contracts import MatchRequest
from chattersift.reddit.contracts import MonitorIntent
from chattersift.reddit.contracts import RedditItemPayload
from chattersift.reddit.matching import KeywordRedditMatcher
from chattersift.reddit.matching import build_match_requests
from chattersift.reddit.models import RedditItem

MONITOR_ID = 42


def test_keyword_matcher_matches_title_and_body() -> None:
    intent = MonitorIntent(
        subreddit="django",
        keywords=("postgres",),
        monitor_id=MONITOR_ID,
    )
    item = RedditItemPayload(
        reddit_id="t3_match",
        item_type=RedditItem.RedditItemType.POST,
        subreddit="django",
        permalink="https://www.reddit.com/r/django/comments/match/example/",
        occurred_at=datetime(2026, 5, 5, tzinfo=UTC),
        title="Django deployment",
        body="Postgres connection pooling details.",
    )

    decision = KeywordRedditMatcher().evaluate(MatchRequest(intent=intent, item=item))

    assert decision.matched is True
    assert decision.monitor_id == MONITOR_ID
    assert decision.reddit_id == "t3_match"
    assert decision.confidence == 1.0
    assert decision.reason == "keyword:postgres"


def test_keyword_matcher_does_not_match_comment_context_title() -> None:
    intent = MonitorIntent(
        subreddit="django",
        keywords=("postgres",),
        monitor_id=MONITOR_ID,
    )
    item = RedditItemPayload(
        reddit_id="t1_comment_context",
        item_type=RedditItem.RedditItemType.COMMENT,
        subreddit="django",
        permalink="https://www.reddit.com/r/django/comments/match/example/comment/",
        occurred_at=datetime(2026, 5, 5, tzinfo=UTC),
        title="Postgres with Django",
        body="This comment only talks about connection pooling.",
    )

    decision = KeywordRedditMatcher().evaluate(MatchRequest(intent=intent, item=item))

    assert decision.matched is False
    assert decision.confidence == 0.0
    assert decision.reason == "keyword:not_found"


def test_keyword_matcher_matches_comment_body() -> None:
    intent = MonitorIntent(
        subreddit="django",
        keywords=("postgres",),
        monitor_id=MONITOR_ID,
    )
    item = RedditItemPayload(
        reddit_id="t1_comment_body",
        item_type=RedditItem.RedditItemType.COMMENT,
        subreddit="django",
        permalink="https://www.reddit.com/r/django/comments/match/example/comment/",
        occurred_at=datetime(2026, 5, 5, tzinfo=UTC),
        title="Django deployment",
        body="This comment mentions Postgres directly.",
    )

    decision = KeywordRedditMatcher().evaluate(MatchRequest(intent=intent, item=item))

    assert decision.matched is True
    assert decision.reason == "keyword:postgres"


def test_build_match_requests_filters_by_subreddit() -> None:
    """Build match requests filters by subreddit, ignoring case."""
    intents = [
        MonitorIntent(subreddit="django", keywords=("postgres",), monitor_id=1),
        MonitorIntent(subreddit="python", keywords=("postgres",), monitor_id=2),
    ]
    item = RedditItemPayload(
        reddit_id="t3_match",
        item_type=RedditItem.RedditItemType.POST,
        subreddit="Django",
        permalink="https://www.reddit.com/r/django/comments/match/example/",
        occurred_at=datetime(2026, 5, 5, tzinfo=UTC),
    )

    requests = build_match_requests(intents, [item])

    assert len(requests) == 1
    assert requests[0].intent.monitor_id == 1
