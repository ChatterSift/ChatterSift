from __future__ import annotations

from django import forms

from .models import NotificationCadence


class EmailNotificationPreferenceForm(forms.Form):
    """Interface: validates the account-level email notification cadence."""

    cadence = forms.ChoiceField(choices=NotificationCadence.choices)
