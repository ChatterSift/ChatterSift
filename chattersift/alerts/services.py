from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from chattersift.tracking.models import Match


def deliver_match_alert(match: Match) -> None:
    # Public core deliberately keeps delivery minimal; extensions can add channels.
    return None
