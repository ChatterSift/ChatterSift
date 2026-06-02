from __future__ import annotations

from chattersift.tracking.tasks import prune_expired_matches


def test_prune_expired_matches_delegates_to_match_manager(monkeypatch) -> None:
    expected_result = 5
    calls = {"manager": 0}

    def fake_prune_expired_matches() -> int:
        calls["manager"] += 1
        return expected_result

    monkeypatch.setattr("chattersift.tracking.tasks.Match.objects.prune_expired", fake_prune_expired_matches)

    assert prune_expired_matches() == expected_result
    assert calls == {"manager": 1}
