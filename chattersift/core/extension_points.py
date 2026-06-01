from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any

from django.conf import settings


def import_string(dotted_path: str) -> Any:
    module_path, _, attribute = dotted_path.rpartition(".")
    if not module_path or not attribute:
        msg = f"{dotted_path!r} is not a valid dotted import path"
        raise ImportError(msg)

    module = import_module(module_path)
    return getattr(module, attribute)


@dataclass(frozen=True, kw_only=True)
class SemanticCredentials:
    """Provider-neutral semantic LLM configuration for one matching request."""

    model: str
    base_url: str = ""
    api_key: str = ""


class MonitorPolicyError(Exception):
    """Raised when an extension policy rejects a monitor mutation."""

    def __init__(self, message: str, *, field: str | None = None) -> None:
        self.field = field
        super().__init__(message)


class DefaultMonitorPolicy:
    """No-op monitor policy used by self-hosted core deployments."""

    def filter_match_mode_choices(self, *, user, choices):
        """Return match-mode choices visible to a user."""
        return choices

    def filter_cadence_choices(self, *, user, choices):
        """Return notification cadence choices visible to a user."""
        return choices

    def validate_monitor_intent(self, **kwargs) -> None:
        """Validate one monitor mutation intent."""


def default_semantic_credentials_provider(*, user=None, user_id: int | None = None) -> SemanticCredentials:
    """Return semantic credentials from the public core settings."""

    return SemanticCredentials(
        model=settings.CHATTERSIFT_SEMANTIC_LLM_MODEL,
        base_url=settings.CHATTERSIFT_SEMANTIC_LLM_BASE_URL,
        api_key=settings.CHATTERSIFT_SEMANTIC_LLM_API_KEY,
    )


def default_dashboard_settings_context_provider(request) -> dict[str, object]:
    """Return extra dashboard settings context for core deployments."""

    return {}


def get_monitor_policy():
    """Return the configured monitor policy object."""

    policy_path = settings.CHATTERSIFT_MONITOR_POLICY
    policy = import_string(policy_path)
    if isinstance(policy, type):
        return policy()
    return policy


def get_semantic_credentials(*, user=None, user_id: int | None = None) -> SemanticCredentials:
    """Return semantic LLM credentials for a user or monitor owner id."""

    provider = import_string(settings.CHATTERSIFT_SEMANTIC_CREDENTIALS_PROVIDER)
    return provider(user=user, user_id=user_id)


def get_dashboard_settings_context(request) -> dict[str, object]:
    """Return extension-provided dashboard settings context."""

    provider = import_string(settings.CHATTERSIFT_DASHBOARD_SETTINGS_CONTEXT_PROVIDER)
    return provider(request)
