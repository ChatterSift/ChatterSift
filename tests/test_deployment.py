import importlib
import sys
from http import HTTPStatus

import pytest
from django.contrib.sites.models import Site
from django.core.management import call_command
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_healthz_endpoint(client):
    response = client.get(reverse("healthz"))

    assert response.status_code == HTTPStatus.OK
    assert response.content == b"ok"


def test_sync_site_domain_command(settings):
    settings.CHATTERSIFT_SITE_DOMAIN = "deploy.example.com"

    call_command("sync_site_domain")

    site = Site.objects.get(id=settings.SITE_ID)
    assert site.domain == "deploy.example.com"
    assert site.name == "deploy.example.com"


def test_production_defaults_use_site_domain(monkeypatch):
    settings_module = _import_production_settings(
        monkeypatch,
        CHATTERSIFT_SITE_DOMAIN="deploy.example.com",
        CHATTERSIFT_EMAIL_PROVIDER="smtp",
    )

    assert settings_module.ALLOWED_HOSTS == ["deploy.example.com", "www.deploy.example.com"]
    assert settings_module.CSRF_TRUSTED_ORIGINS == [
        "https://deploy.example.com",
        "https://www.deploy.example.com",
    ]
    assert settings_module.DEFAULT_FROM_EMAIL == "Chattersift <noreply@deploy.example.com>"
    assert settings_module.COMPRESS_ENABLED is False


def test_production_postmark_email_provider(monkeypatch):
    provider_token = "test-value"  # noqa: S105
    settings_module = _import_production_settings(
        monkeypatch,
        CHATTERSIFT_SITE_DOMAIN="deploy.example.com",
        CHATTERSIFT_EMAIL_PROVIDER="postmark",
        ANYMAIL_POSTMARK_SERVER_TOKEN=provider_token,
    )

    assert settings_module.EMAIL_BACKEND == "anymail.backends.postmark.EmailBackend"
    assert "anymail" in settings_module.INSTALLED_APPS
    assert settings_module.ANYMAIL["POSTMARK_SERVER_TOKEN"] == provider_token


def test_production_rejects_unknown_email_provider(monkeypatch):
    with pytest.raises(ValueError, match="CHATTERSIFT_EMAIL_PROVIDER"):
        _import_production_settings(
            monkeypatch,
            CHATTERSIFT_SITE_DOMAIN="deploy.example.com",
            CHATTERSIFT_EMAIL_PROVIDER="unknown",
        )


def _import_production_settings(monkeypatch, **env):
    """Interface: import production settings with a minimal deterministic environment."""
    for module_name in ["config.settings.production", "config.settings.base"]:
        sys.modules.pop(module_name, None)

    required_env = {
        "DATABASE_URL": "postgres://user:password@localhost:5432/chattersift",
        "DJANGO_SECRET_KEY": "test-secret",
        "DJANGO_ADMIN_URL": "admin-test/",
    }
    for key, value in {**required_env, **env}.items():
        monkeypatch.setenv(key, value)

    return importlib.import_module("config.settings.production")
