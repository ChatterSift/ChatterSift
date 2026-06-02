from __future__ import annotations

from celery import shared_task

from .models import Match


@shared_task()
def prune_expired_matches() -> int:
    """Delete Match rows beyond each user's retention preference."""
    return Match.objects.prune_expired()
