from __future__ import annotations

from chattersift.tracking.tasks import prune_expired_matches


def test_prune_expired_matches_delegates_to_service(monkeypatch) -> None:
    expected_result = 5
    calls = {"service": 0}

    def fake_prune_expired_matches_service() -> int:
        calls["service"] += 1
        return expected_result

    monkeypatch.setattr(
        "chattersift.tracking.tasks.prune_expired_matches_service",
        fake_prune_expired_matches_service,
    )

    assert prune_expired_matches() == expected_result
    assert calls == {"service": 1}
