from __future__ import annotations

import re

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from chattersift.alerts.models import NotificationCadence
from chattersift.reddit.contracts import MonitorMatchMode

SUBREDDIT_TOKEN_RE = re.compile(r"^[A-Za-z0-9_]+$")
KEYWORD_SPLIT_RE = re.compile(r"[\n,]+")
SUBREDDIT_MAX_LENGTH = 100
KEYWORD_MAX_LENGTH = 255
SEMANTIC_DESCRIPTION_MAX_LENGTH = 2000
MATCH_RETENTION_DEFAULT_DAYS = 30
MATCH_RETENTION_FOREVER_VALUE = "forever"
MATCH_RETENTION_CHOICES = [
    ("7", _("7 days")),
    ("30", _("30 days")),
    ("90", _("90 days")),
    ("365", _("365 days")),
    (MATCH_RETENTION_FOREVER_VALUE, _("Keep forever")),
]


class MonitorBatchForm(forms.Form):
    """Validates one subreddit plus keyword and semantic monitor intent fields."""

    subreddit = forms.CharField(max_length=SUBREDDIT_MAX_LENGTH)
    match_mode = forms.ChoiceField(
        choices=MonitorMatchMode.choices,
        initial=MonitorMatchMode.KEYWORD,
        required=False,
    )
    keywords = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    semantic_description = forms.CharField(
        max_length=SEMANTIC_DESCRIPTION_MAX_LENGTH,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    cadence = forms.ChoiceField(
        choices=NotificationCadence,
        initial=NotificationCadence.THIRTY_MINUTES,
        required=False,
    )

    def clean_subreddit(self) -> str:
        raw_subreddit = self.cleaned_data["subreddit"].strip()
        subreddit = raw_subreddit.removeprefix("/").removeprefix("r/").removeprefix("R/")

        if not subreddit:
            raise ValidationError(_("Enter a subreddit."))
        if not SUBREDDIT_TOKEN_RE.fullmatch(subreddit):
            raise ValidationError(_("Use only letters, numbers, and underscores."))

        if len(subreddit) > SUBREDDIT_MAX_LENGTH:
            raise ValidationError(
                _("Subreddit names must be %(limit_value)d characters or fewer."),
                params={"limit_value": SUBREDDIT_MAX_LENGTH},
            )

        return subreddit.casefold()

    def clean_keywords(self) -> list[str]:
        raw_keywords = self.cleaned_data.get("keywords") or ""
        keywords_by_key: dict[str, str] = {}

        for raw_keyword in KEYWORD_SPLIT_RE.split(raw_keywords):
            keyword = raw_keyword.strip()
            if not keyword:
                continue
            if len(keyword) > KEYWORD_MAX_LENGTH:
                raise ValidationError(
                    _("Keywords must be %(limit_value)d characters or fewer."),
                    params={"limit_value": KEYWORD_MAX_LENGTH},
                )
            keywords_by_key.setdefault(keyword.casefold(), keyword)

        return list(keywords_by_key.values())

    def clean_semantic_description(self) -> str:
        description = (self.cleaned_data.get("semantic_description") or "").strip()
        if len(description) > SEMANTIC_DESCRIPTION_MAX_LENGTH:
            raise ValidationError(
                _("Semantic descriptions must be %(limit_value)d characters or fewer."),
                params={"limit_value": SEMANTIC_DESCRIPTION_MAX_LENGTH},
            )
        return description

    def clean_cadence(self) -> str:
        cadence = self.cleaned_data.get("cadence")
        return cadence or NotificationCadence.THIRTY_MINUTES

    def clean_match_mode(self) -> str:
        match_mode = self.cleaned_data.get("match_mode")
        return match_mode or MonitorMatchMode.KEYWORD

    def clean(self) -> dict[str, object]:
        cleaned_data = super().clean()
        match_mode = cleaned_data.get("match_mode") or MonitorMatchMode.KEYWORD
        keywords = cleaned_data.get("keywords") or []
        semantic_description = cleaned_data.get("semantic_description") or ""

        if match_mode in {MonitorMatchMode.KEYWORD, MonitorMatchMode.KEYWORD_SEMANTIC} and not keywords:
            self.add_error("keywords", ValidationError(_("Enter at least one keyword.")))
        if match_mode in {MonitorMatchMode.SEMANTIC, MonitorMatchMode.KEYWORD_SEMANTIC}:
            if not semantic_description:
                self.add_error("semantic_description", ValidationError(_("Describe what should match semantically.")))
            if not settings.CHATTERSIFT_SEMANTIC_LLM_MODEL:
                self.add_error(
                    "semantic_description",
                    ValidationError(_("Semantic monitoring is not configured yet.")),
                )

        return cleaned_data


class KeywordAddForm(forms.Form):
    """Validates a single keyword to add to an existing subreddit group."""

    keyword = forms.CharField(max_length=KEYWORD_MAX_LENGTH)

    def clean_keyword(self) -> str:
        keyword = self.cleaned_data["keyword"].strip()
        if not keyword:
            raise ValidationError(_("Enter a keyword."))
        return keyword


class CadenceForm(forms.Form):
    """Validates a notification cadence selection."""

    cadence = forms.ChoiceField(choices=NotificationCadence)


class MatchRetentionForm(forms.Form):
    """Validates a matched-item retention preset selection."""

    retention_days = forms.ChoiceField(
        choices=MATCH_RETENTION_CHOICES,
        initial=str(MATCH_RETENTION_DEFAULT_DAYS),
    )

    def clean_retention_days(self) -> int | None:
        value = self.cleaned_data["retention_days"]
        if value == MATCH_RETENTION_FOREVER_VALUE:
            return None
        return int(value)
