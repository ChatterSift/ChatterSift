from __future__ import annotations

from celery import shared_task

from .services import prune_expired_matches as prune_expired_matches_service


@shared_task()
def prune_expired_matches() -> int:
    """Delete Match rows beyond each user's retention preference."""
    return prune_expired_matches_service()
