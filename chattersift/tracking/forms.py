from __future__ import annotations

import re

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from chattersift.alerts.models import NotificationCadence
from chattersift.core.extension_points import MonitorPolicyError
from chattersift.core.extension_points import get_monitor_policy
from chattersift.core.extension_points import get_semantic_credentials
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

    def __init__(self, *args, user=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.user = user
        policy = get_monitor_policy()
        self.fields["match_mode"].choices = policy.filter_match_mode_choices(
            user=user,
            choices=MonitorMatchMode.choices,
        )
        self.fields["cadence"].choices = policy.filter_cadence_choices(
            user=user,
            choices=NotificationCadence.choices,
        )

    def clean_subreddit(self) -> str:
        return normalize_subreddit(self.cleaned_data["subreddit"])

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
        _apply_match_mode_validation(
            self,
            match_mode=cleaned_data.get("match_mode") or MonitorMatchMode.KEYWORD,
            has_keyword=bool(cleaned_data.get("keywords")),
            semantic_description=cleaned_data.get("semantic_description") or "",
            keyword_field="keywords",
            user=self.user,
        )
        _apply_monitor_policy_validation(
            self,
            action="create",
            user=self.user,
            subreddit=cleaned_data.get("subreddit") or "",
            match_mode=cleaned_data.get("match_mode") or MonitorMatchMode.KEYWORD,
            keywords=cleaned_data.get("keywords") or [],
            semantic_description=cleaned_data.get("semantic_description") or "",
            cadence=cleaned_data.get("cadence") or NotificationCadence.THIRTY_MINUTES,
        )
        return cleaned_data


class MonitorAddForm(forms.Form):
    """Validates one monitor (any type) added inline to an existing group."""

    match_mode = forms.ChoiceField(
        choices=MonitorMatchMode.choices,
        initial=MonitorMatchMode.KEYWORD,
    )
    keyword = forms.CharField(max_length=KEYWORD_MAX_LENGTH, required=False)
    semantic_description = forms.CharField(
        max_length=SEMANTIC_DESCRIPTION_MAX_LENGTH,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, user=None, subreddit: str = "", monitor=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.user = user
        self.subreddit = subreddit
        self.monitor = monitor
        self.fields["match_mode"].choices = get_monitor_policy().filter_match_mode_choices(
            user=user,
            choices=MonitorMatchMode.choices,
        )

    def clean_keyword(self) -> str:
        keyword = (self.cleaned_data.get("keyword") or "").strip()
        if len(keyword) > KEYWORD_MAX_LENGTH:
            raise ValidationError(
                _("Keywords must be %(limit_value)d characters or fewer."),
                params={"limit_value": KEYWORD_MAX_LENGTH},
            )
        return keyword

    def clean_semantic_description(self) -> str:
        description = (self.cleaned_data.get("semantic_description") or "").strip()
        if len(description) > SEMANTIC_DESCRIPTION_MAX_LENGTH:
            raise ValidationError(
                _("Semantic descriptions must be %(limit_value)d characters or fewer."),
                params={"limit_value": SEMANTIC_DESCRIPTION_MAX_LENGTH},
            )
        return description

    def clean(self) -> dict[str, object]:
        cleaned_data = super().clean()
        _apply_match_mode_validation(
            self,
            match_mode=cleaned_data.get("match_mode") or MonitorMatchMode.KEYWORD,
            has_keyword=bool(cleaned_data.get("keyword")),
            semantic_description=cleaned_data.get("semantic_description") or "",
            keyword_field="keyword",
            user=self.user,
        )
        _apply_monitor_policy_validation(
            self,
            action="edit" if self.monitor is not None else "add",
            user=self.user,
            subreddit=self.subreddit,
            match_mode=cleaned_data.get("match_mode") or MonitorMatchMode.KEYWORD,
            keywords=[cleaned_data.get("keyword") or ""],
            semantic_description=cleaned_data.get("semantic_description") or "",
            cadence=None,
            monitor=self.monitor,
        )
        return cleaned_data


class MonitorEditForm(MonitorAddForm):
    """Same fields as MonitorAddForm; distinct class for edit-endpoint typing."""


def normalize_subreddit(raw_subreddit: str) -> str:
    """Interface: normalize user- or URL-provided subreddit tokens for Monitor writes."""

    subreddit = raw_subreddit.strip().removeprefix("/").removeprefix("r/").removeprefix("R/")

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


def _apply_match_mode_validation(  # noqa: PLR0913
    form: forms.Form,
    *,
    match_mode: str,
    has_keyword: bool,
    semantic_description: str,
    keyword_field: str,
    user,
) -> None:
    """Apply cross-field rules shared by all monitor-intent forms."""

    if match_mode in {MonitorMatchMode.KEYWORD, MonitorMatchMode.KEYWORD_SEMANTIC} and not has_keyword:
        message = _("Enter at least one keyword.") if keyword_field == "keywords" else _("Enter a keyword.")
        form.add_error(keyword_field, ValidationError(message))
    if match_mode in {MonitorMatchMode.SEMANTIC, MonitorMatchMode.KEYWORD_SEMANTIC}:
        if not semantic_description:
            form.add_error(
                "semantic_description",
                ValidationError(_("Describe what should match semantically.")),
            )
        if not get_semantic_credentials(user=user).model:
            form.add_error(
                "semantic_description",
                ValidationError(_("Semantic monitoring is not configured yet.")),
            )


def _apply_monitor_policy_validation(  # noqa: PLR0913
    form: forms.Form,
    *,
    action: str,
    user,
    subreddit: str,
    match_mode: str,
    keywords: list[str],
    semantic_description: str,
    cadence: str | None,
    monitor=None,
) -> None:
    """Apply extension-provided monitor policy validation to a form."""

    if not user or not subreddit:
        return
    try:
        get_monitor_policy().validate_monitor_intent(
            action=action,
            user=user,
            subreddit=subreddit,
            match_mode=match_mode,
            keywords=keywords,
            semantic_description=semantic_description,
            cadence=cadence,
            monitor=monitor,
        )
    except MonitorPolicyError as error:
        form.add_error(error.field, ValidationError(str(error)))


class CadenceForm(forms.Form):
    """Validates a notification cadence selection."""

    cadence = forms.ChoiceField(choices=NotificationCadence)

    def __init__(self, *args, user=None, subreddit: str = "", **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.user = user
        self.subreddit = subreddit
        self.fields["cadence"].choices = get_monitor_policy().filter_cadence_choices(
            user=user,
            choices=NotificationCadence.choices,
        )

    def clean(self) -> dict[str, object]:
        cleaned_data = super().clean()
        _apply_monitor_policy_validation(
            self,
            action="cadence",
            user=self.user,
            subreddit=self.subreddit,
            match_mode=MonitorMatchMode.KEYWORD,
            keywords=[],
            semantic_description="",
            cadence=cleaned_data.get("cadence"),
        )
        return cleaned_data


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
