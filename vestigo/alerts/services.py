from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vestigo.tracking.models import Match


def deliver_match_alert(match: Match) -> None:
    # Public core deliberately keeps delivery minimal; SaaS can add channels.
    return None
