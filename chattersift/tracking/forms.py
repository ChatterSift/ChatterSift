from __future__ import annotations

import re

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from chattersift.alerts.models import NotificationCadence

SUBREDDIT_TOKEN_RE = re.compile(r"^[A-Za-z0-9_]+$")
KEYWORD_SPLIT_RE = re.compile(r"[\n,]+")
SUBREDDIT_MAX_LENGTH = 100
KEYWORD_MAX_LENGTH = 255


class MonitorBatchForm(forms.Form):
    """Interface: validates one subreddit plus a case-insensitive keyword set."""

    subreddit = forms.CharField(max_length=SUBREDDIT_MAX_LENGTH)
    keywords = forms.CharField()
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
        raw_keywords = self.cleaned_data["keywords"]
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

        if not keywords_by_key:
            raise ValidationError(_("Enter at least one keyword."))

        return list(keywords_by_key.values())

    def clean_cadence(self) -> str:
        cadence = self.cleaned_data.get("cadence")
        return cadence or NotificationCadence.THIRTY_MINUTES


class KeywordAddForm(forms.Form):
    """Interface: validates a single keyword to add to an existing subreddit group."""

    keyword = forms.CharField(max_length=KEYWORD_MAX_LENGTH)

    def clean_keyword(self) -> str:
        keyword = self.cleaned_data["keyword"].strip()
        if not keyword:
            raise ValidationError(_("Enter a keyword."))
        return keyword


class CadenceForm(forms.Form):
    """Interface: validates a notification cadence selection."""

    cadence = forms.ChoiceField(choices=NotificationCadence)
