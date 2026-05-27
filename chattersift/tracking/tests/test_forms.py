from __future__ import annotations

from chattersift.alerts.models import NotificationCadence
from chattersift.tracking.forms import MATCH_RETENTION_DEFAULT_DAYS
from chattersift.tracking.forms import MatchRetentionForm
from chattersift.tracking.forms import MonitorBatchForm


def test_monitor_batch_form_normalizes_subreddit_prefix() -> None:
    form = MonitorBatchForm(data={"subreddit": "r/Django", "keywords": "postgres"})

    assert form.is_valid()
    assert form.cleaned_data["subreddit"] == "django"
    assert form.cleaned_data["cadence"] == NotificationCadence.THIRTY_MINUTES


def test_monitor_batch_form_rejects_unsafe_subreddit_tokens() -> None:
    form = MonitorBatchForm(data={"subreddit": "django/new", "keywords": "postgres"})

    assert not form.is_valid()
    assert "subreddit" in form.errors


def test_monitor_batch_form_rejects_empty_keywords() -> None:
    form = MonitorBatchForm(data={"subreddit": "django", "keywords": "\n,  "})

    assert not form.is_valid()
    assert "keywords" in form.errors


def test_monitor_batch_form_dedupes_keywords_case_insensitively() -> None:
    form = MonitorBatchForm(data={"subreddit": "django", "keywords": "Postgres\npostgres\nHTMX", "cadence": "off"})

    assert form.is_valid()
    assert form.cleaned_data["keywords"] == ["Postgres", "HTMX"]


def test_monitor_batch_form_enforces_model_field_lengths() -> None:
    form = MonitorBatchForm(data={"subreddit": "a" * 101, "keywords": "b" * 256})

    assert not form.is_valid()
    assert "subreddit" in form.errors
    assert "keywords" in form.errors


def test_monitor_batch_form_accepts_semantic_only_without_keywords(settings) -> None:
    settings.CHATTERSIFT_SEMANTIC_LLM_MODEL = "openai/gpt-4o-mini"
    form = MonitorBatchForm(
        data={
            "subreddit": "django",
            "match_mode": "semantic",
            "keywords": "",
            "semantic_description": "Django performance problems",
        },
    )

    assert form.is_valid()
    assert form.cleaned_data["keywords"] == []


def test_monitor_batch_form_rejects_semantic_when_model_missing(settings) -> None:
    settings.CHATTERSIFT_SEMANTIC_LLM_MODEL = ""
    form = MonitorBatchForm(
        data={
            "subreddit": "django",
            "match_mode": "semantic",
            "semantic_description": "Django performance problems",
        },
    )

    assert not form.is_valid()
    assert "semantic_description" in form.errors


def test_match_retention_form_accepts_preset_values() -> None:
    expected_values = {
        "7": 7,
        "30": 30,
        "90": 90,
        "365": 365,
        "forever": None,
    }

    for raw_value, expected_value in expected_values.items():
        form = MatchRetentionForm(data={"retention_days": raw_value})

        assert form.is_valid()
        assert form.cleaned_data["retention_days"] == expected_value


def test_match_retention_form_defaults_to_thirty_days() -> None:
    form = MatchRetentionForm()

    assert form["retention_days"].value() == str(MATCH_RETENTION_DEFAULT_DAYS)


def test_match_retention_form_rejects_tampered_value() -> None:
    form = MatchRetentionForm(data={"retention_days": "14"})

    assert not form.is_valid()
    assert "retention_days" in form.errors
