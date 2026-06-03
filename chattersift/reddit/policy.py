from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings

from chattersift.core.extension_points import import_string

if TYPE_CHECKING:
    from collections.abc import Iterable

DEFAULT_REDDIT_COLLECTION_LANE = "default"


class DefaultRedditCollectionPolicy:
    """Interface: classifies monitors and cadence for Reddit collection lanes."""

    def planning_scope(self, lane: str) -> tuple[str, ...]:
        """Return collection lanes allowed to plan Reddit requests for this run."""
        return (lane,)

    def matching_scope(self, lane: str) -> tuple[str, ...]:
        """Return collection lanes allowed to match items fetched by this run."""
        return (lane,)

    def monitor_lane(self, monitor) -> str:
        """Return the collection lane for one active monitor."""
        return DEFAULT_REDDIT_COLLECTION_LANE

    def filter_monitors(self, monitors: Iterable, *, scope_lanes: Iterable[str]) -> list:
        """Return monitors whose collection lane is included in the requested scope."""
        allowed_lanes = set(scope_lanes)
        return [monitor for monitor in monitors if self.monitor_lane(monitor) in allowed_lanes]

    def fetch_interval_seconds(self, lane: str) -> int:
        """Return successful-fetch cadence in seconds for one lane."""
        return settings.CHATTERSIFT_REDDIT_FETCH_INTERVAL_SECONDS

    def search_query_max_terms(self, lane: str) -> int | None:
        """Return the maximum keyword terms per Reddit search query, or no limit."""
        configured_limit = getattr(settings, "CHATTERSIFT_REDDIT_SEARCH_QUERY_MAX_TERMS", 0)
        return configured_limit if configured_limit > 0 else None


def get_reddit_collection_policy():
    """Return the configured Reddit collection policy object."""
    policy_path = settings.CHATTERSIFT_REDDIT_COLLECTION_POLICY
    policy = import_string(policy_path)
    if isinstance(policy, type):
        return policy()
    return policy
