# ruff: noqa: ERA001
"""Base settings to build other settings files upon."""

import ssl
from pathlib import Path
from typing import Any

import environ

BASE_DIR = Path(__file__).resolve(strict=True).parent.parent.parent
# chattersift/
APPS_DIR = BASE_DIR / "chattersift"
env = environ.Env()

READ_DOT_ENV_FILE = env.bool("DJANGO_READ_DOT_ENV_FILE", default=False)
if READ_DOT_ENV_FILE:
    # OS environment variables take precedence over variables from .env
    env.read_env(str(BASE_DIR / ".env"))

# GENERAL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#debug
DEBUG = env.bool("DJANGO_DEBUG", False)
# Local time zone. Choices are
# http://en.wikipedia.org/wiki/List_of_tz_zones_by_name
# though not all of them may be available with every OS.
# In Windows, this must be set to your system time zone.
TIME_ZONE = "UTC"
# https://docs.djangoproject.com/en/dev/ref/settings/#language-code
LANGUAGE_CODE = "en-us"
# https://docs.djangoproject.com/en/dev/ref/settings/#languages
# from django.utils.translation import gettext_lazy as _
# LANGUAGES = [
#     ('en', _('English')),
#     ('fr-fr', _('French')),
#     ('pt-br', _('Portuguese')),
# ]
# https://docs.djangoproject.com/en/dev/ref/settings/#site-id
SITE_ID = 1
# https://docs.djangoproject.com/en/dev/ref/settings/#use-i18n
USE_I18N = True
# https://docs.djangoproject.com/en/dev/ref/settings/#use-tz
USE_TZ = True
# https://docs.djangoproject.com/en/dev/ref/settings/#locale-paths
LOCALE_PATHS = [str(BASE_DIR / "locale")]

# DATABASES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#databases
DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["ATOMIC_REQUESTS"] = True
# https://docs.djangoproject.com/en/stable/ref/settings/#std:setting-DEFAULT_AUTO_FIELD
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

# URLS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#root-urlconf
ROOT_URLCONF = "config.urls"
# https://docs.djangoproject.com/en/dev/ref/settings/#wsgi-application
WSGI_APPLICATION = "config.wsgi.application"

# APPS
# ------------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.sites",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # "django.contrib.humanize", # Handy template tags
    "django.contrib.admin",
    "django.forms",
]
THIRD_PARTY_APPS = [
    "crispy_forms",
    "crispy_bootstrap5",
    "allauth",
    "allauth.account",
    "allauth.mfa",
    "allauth.socialaccount",
    "django_celery_beat",
    "widget_tweaks",
    "corsheaders",
]

LOCAL_APPS = [
    "chattersift.users",
    "chattersift.core",
    "chattersift.tracking",
    "chattersift.reddit",
    "chattersift.alerts",
]
# https://docs.djangoproject.com/en/dev/ref/settings/#installed-apps
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# Chattersift extension points
# ------------------------------------------------------------------------------
CHATTERSIFT_URLCONFS = []
CHATTERSIFT_HOME_TEMPLATE: str = "pages/home.html"
CHATTERSIFT_ENABLE_API = env.bool("CHATTERSIFT_ENABLE_API", default=False)
CHATTERSIFT_SITE_DOMAIN = env("CHATTERSIFT_SITE_DOMAIN", default="localhost")
CHATTERSIFT_API_ROUTERS = [
    ("/users/", "chattersift.users.api.views.router"),
]
CHATTERSIFT_REDDIT_FEED_FORMAT = env("CHATTERSIFT_REDDIT_FEED_FORMAT", default="rss")
CHATTERSIFT_REDDIT_USER_AGENT = env(
    "CHATTERSIFT_REDDIT_USER_AGENT",
    default=f"chattersift-bot/0.1 (+https://{CHATTERSIFT_SITE_DOMAIN})",
)
CHATTERSIFT_REDDIT_FETCH_LIMIT = env.int("CHATTERSIFT_REDDIT_FETCH_LIMIT", default=100)
CHATTERSIFT_REDDIT_HTTP_TIMEOUT_SECONDS = env.float(
    "CHATTERSIFT_REDDIT_HTTP_TIMEOUT_SECONDS",
    default=10.0,
)
CHATTERSIFT_REDDIT_FETCH_INTERVAL_SECONDS = env.int(
    "CHATTERSIFT_REDDIT_FETCH_INTERVAL_SECONDS",
    default=300,
)
CHATTERSIFT_REDDIT_SCHEDULER_INTERVAL_SECONDS = env.int(
    "CHATTERSIFT_REDDIT_SCHEDULER_INTERVAL_SECONDS",
    default=60,
)
CHATTERSIFT_REDDIT_ITEM_RETENTION_DAYS = env.int(
    "CHATTERSIFT_REDDIT_ITEM_RETENTION_DAYS",
    default=14,
)
CHATTERSIFT_REDDIT_ITEM_PRUNE_INTERVAL_SECONDS = env.int(
    "CHATTERSIFT_REDDIT_ITEM_PRUNE_INTERVAL_SECONDS",
    default=86400,
)
CHATTERSIFT_MATCH_PRUNE_INTERVAL_SECONDS = env.int(
    "CHATTERSIFT_MATCH_PRUNE_INTERVAL_SECONDS",
    default=86400,
)
CHATTERSIFT_ALERT_DISPATCH_INTERVAL_SECONDS = env.int(
    "CHATTERSIFT_ALERT_DISPATCH_INTERVAL_SECONDS",
    default=60,
)
CHATTERSIFT_REDDIT_FAILURE_BACKOFF_BASE_SECONDS = env.int(
    "CHATTERSIFT_REDDIT_FAILURE_BACKOFF_BASE_SECONDS",
    default=300,
)
CHATTERSIFT_REDDIT_FAILURE_BACKOFF_MAX_SECONDS = env.int(
    "CHATTERSIFT_REDDIT_FAILURE_BACKOFF_MAX_SECONDS",
    default=3600,
)
CHATTERSIFT_SEMANTIC_LLM_MODEL = env("CHATTERSIFT_SEMANTIC_LLM_MODEL", default="")
CHATTERSIFT_SEMANTIC_LLM_TIMEOUT_SECONDS = env.float(
    "CHATTERSIFT_SEMANTIC_LLM_TIMEOUT_SECONDS",
    default=20.0,
)
CHATTERSIFT_SEMANTIC_LLM_MAX_TOKENS = env.int(
    "CHATTERSIFT_SEMANTIC_LLM_MAX_TOKENS",
    default=256,
)
CHATTERSIFT_SEMANTIC_MATCH_MAX_CALLS_PER_FEED = env.int(
    "CHATTERSIFT_SEMANTIC_MATCH_MAX_CALLS_PER_FEED",
    default=1000,
)
CHATTERSIFT_SEMANTIC_MATCH_MAX_INPUT_CHARS = env.int(
    "CHATTERSIFT_SEMANTIC_MATCH_MAX_INPUT_CHARS",
    default=8000,
)
CHATTERSIFT_SEMANTIC_LLM_BASE_URL = env("CHATTERSIFT_SEMANTIC_LLM_BASE_URL", default="")
CHATTERSIFT_SEMANTIC_LLM_API_KEY = env("CHATTERSIFT_SEMANTIC_LLM_API_KEY", default="")

# MIGRATIONS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#migration-modules
MIGRATION_MODULES = {"sites": "chattersift.contrib.sites.migrations"}

# AUTHENTICATION
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#authentication-backends
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
# https://docs.djangoproject.com/en/dev/ref/settings/#auth-user-model
AUTH_USER_MODEL = "users.User"
# https://docs.djangoproject.com/en/dev/ref/settings/#login-redirect-url
LOGIN_REDIRECT_URL = "tracking:dashboard"
# https://docs.djangoproject.com/en/dev/ref/settings/#login-url
LOGIN_URL = "account_login"

# PASSWORDS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#password-hashers
PASSWORD_HASHERS = [
    # https://docs.djangoproject.com/en/dev/topics/auth/passwords/#using-argon2-with-django
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
]
# https://docs.djangoproject.com/en/dev/ref/settings/#auth-password-validators
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# MIDDLEWARE
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#middleware
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

# STATIC
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#static-root
STATIC_ROOT = str(BASE_DIR / "staticfiles")
# https://docs.djangoproject.com/en/dev/ref/settings/#static-url
STATIC_URL: str = "/static/"
# https://docs.djangoproject.com/en/dev/ref/contrib/staticfiles/#std:setting-STATICFILES_DIRS
STATICFILES_DIRS = [str(APPS_DIR / "static")]
# https://docs.djangoproject.com/en/dev/ref/contrib/staticfiles/#staticfiles-finders
STATICFILES_FINDERS = [
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
]

# MEDIA
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#media-root
MEDIA_ROOT = str(APPS_DIR / "media")
# https://docs.djangoproject.com/en/dev/ref/settings/#media-url
MEDIA_URL: str = "/media/"

# TEMPLATES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#templates
TEMPLATES: list[dict[str, Any]] = [
    {
        # https://docs.djangoproject.com/en/dev/ref/settings/#std:setting-TEMPLATES-BACKEND
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # https://docs.djangoproject.com/en/dev/ref/settings/#dirs
        "DIRS": [str(APPS_DIR / "templates")],
        # https://docs.djangoproject.com/en/dev/ref/settings/#app-dirs
        "APP_DIRS": True,
        "OPTIONS": {
            # https://docs.djangoproject.com/en/dev/ref/settings/#template-context-processors
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.template.context_processors.i18n",
                "django.template.context_processors.media",
                "django.template.context_processors.static",
                "django.template.context_processors.tz",
                "django.contrib.messages.context_processors.messages",
                "chattersift.users.context_processors.allauth_settings",
            ],
        },
    },
]

# https://docs.djangoproject.com/en/dev/ref/settings/#form-renderer
FORM_RENDERER = "django.forms.renderers.TemplatesSetting"

# http://django-crispy-forms.readthedocs.io/en/latest/install.html#template-packs
CRISPY_TEMPLATE_PACK = "bootstrap5"
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"

# FIXTURES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#fixture-dirs
FIXTURE_DIRS = (str(APPS_DIR / "fixtures"),)

# SECURITY
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#session-cookie-httponly
SESSION_COOKIE_HTTPONLY = True
# https://docs.djangoproject.com/en/dev/ref/settings/#csrf-cookie-httponly
CSRF_COOKIE_HTTPONLY = True
# https://docs.djangoproject.com/en/dev/ref/settings/#x-frame-options
X_FRAME_OPTIONS = "DENY"

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#email-backend
EMAIL_BACKEND = env(
    "DJANGO_EMAIL_BACKEND",
    default="django.core.mail.backends.smtp.EmailBackend",
)
DEFAULT_FROM_EMAIL = env(
    "DJANGO_DEFAULT_FROM_EMAIL",
    default=f"noreply@{CHATTERSIFT_SITE_DOMAIN}",
)
# https://docs.djangoproject.com/en/dev/ref/settings/#email-timeout
EMAIL_TIMEOUT = 5

# ADMIN
# ------------------------------------------------------------------------------
# Django Admin URL.
ADMIN_URL = "admin/"
# https://docs.djangoproject.com/en/dev/ref/settings/#admins
ADMINS = [env("DJANGO_ADMIN_EMAIL", default=f"admin@{CHATTERSIFT_SITE_DOMAIN}")]
# https://docs.djangoproject.com/en/dev/ref/settings/#managers
MANAGERS = ADMINS
# https://cookiecutter-django.readthedocs.io/en/latest/settings.html#other-environment-settings
# Force the `admin` sign in process to go through the `django-allauth` workflow
DJANGO_ADMIN_FORCE_ALLAUTH = env.bool("DJANGO_ADMIN_FORCE_ALLAUTH", default=False)

# LOGGING
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#logging
# See https://docs.djangoproject.com/en/dev/topics/logging for
# more details on how to customize your logging configuration.
LOGGING: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(levelname)s %(asctime)s %(module)s %(process)d %(thread)d %(message)s",
        },
    },
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {"level": "INFO", "handlers": ["console"]},
}

REDIS_URL = env("REDIS_URL", default="redis://redis:6379/0")
REDIS_SSL = REDIS_URL.startswith("rediss://")

# Celery
# ------------------------------------------------------------------------------
if USE_TZ:
    # https://docs.celeryq.dev/en/stable/userguide/configuration.html#std:setting-timezone
    CELERY_TIMEZONE = TIME_ZONE
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std:setting-broker_url
CELERY_BROKER_URL = REDIS_URL
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#redis-backend-use-ssl
CELERY_BROKER_USE_SSL = {"ssl_cert_reqs": ssl.CERT_NONE} if REDIS_SSL else None
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std:setting-result_backend
CELERY_RESULT_BACKEND = REDIS_URL
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#redis-backend-use-ssl
CELERY_REDIS_BACKEND_USE_SSL = CELERY_BROKER_USE_SSL
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#result-extended
CELERY_RESULT_EXTENDED = True
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#result-backend-always-retry
# https://github.com/celery/celery/pull/6122
CELERY_RESULT_BACKEND_ALWAYS_RETRY = True
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#result-backend-max-retries
CELERY_RESULT_BACKEND_MAX_RETRIES = 10
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std:setting-accept_content
CELERY_ACCEPT_CONTENT = ["json"]
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std:setting-task_serializer
CELERY_TASK_SERIALIZER = "json"
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std:setting-result_serializer
CELERY_RESULT_SERIALIZER = "json"
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#task-time-limit
# TODO: set to whatever value is adequate in your circumstances
CELERY_TASK_TIME_LIMIT = 5 * 60
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#task-soft-time-limit
# TODO: set to whatever value is adequate in your circumstances
CELERY_TASK_SOFT_TIME_LIMIT = 60
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#beat-scheduler
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_BEAT_SCHEDULE = {
    "fetch-due-reddit-feeds": {
        "task": "chattersift.reddit.tasks.fetch_due_reddit_feeds",
        "schedule": CHATTERSIFT_REDDIT_SCHEDULER_INTERVAL_SECONDS,
    },
    "prune-unmatched-reddit-items": {
        "task": "chattersift.reddit.tasks.prune_unmatched_reddit_items",
        "schedule": CHATTERSIFT_REDDIT_ITEM_PRUNE_INTERVAL_SECONDS,
    },
    "prune-expired-matches": {
        "task": "chattersift.tracking.tasks.prune_expired_matches",
        "schedule": CHATTERSIFT_MATCH_PRUNE_INTERVAL_SECONDS,
    },
    "send-due-match-notifications": {
        "task": "chattersift.alerts.tasks.send_due_match_notifications",
        "schedule": CHATTERSIFT_ALERT_DISPATCH_INTERVAL_SECONDS,
    },
}
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#worker-send-task-events
CELERY_WORKER_SEND_TASK_EVENTS = True
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std-setting-task_send_sent_event
CELERY_TASK_SEND_SENT_EVENT = True
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#worker-hijack-root-logger
CELERY_WORKER_HIJACK_ROOT_LOGGER = False
# django-allauth
# ------------------------------------------------------------------------------
ACCOUNT_ALLOW_REGISTRATION = env.bool("DJANGO_ACCOUNT_ALLOW_REGISTRATION", True)
# https://docs.allauth.org/en/latest/account/configuration.html
ACCOUNT_LOGIN_METHODS = {"email"}
# https://docs.allauth.org/en/latest/account/configuration.html
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
# https://docs.allauth.org/en/latest/account/configuration.html
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
# https://docs.allauth.org/en/latest/account/configuration.html
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
# https://docs.allauth.org/en/latest/account/rate_limits.html
# Interface: allauth consumes these by action name to protect account workflows.
ACCOUNT_RATE_LIMITS = {
    "change_password": "3/10m/user",
    "change_phone": "1/10m/user",
    "manage_email": "5/10m/user",
    "reset_password": "5/10m/ip,3/h/key",
    "reauthenticate": "5/10m/user",
    "reset_password_from_key": "5/10m/ip",
    "signup": "5/h/ip,20/d/ip",
    "login": "10/5m/ip",
    "login_failed": "5/10m/ip,3/10m/key",
    "confirm_email": "1/10m/key",
    "request_login_code": "5/10m/ip,3/h/key",
    "verify_phone": "1/2m/key,3/10m/ip",
}
# https://docs.allauth.org/en/latest/account/configuration.html
ACCOUNT_ADAPTER = "chattersift.users.adapters.AccountAdapter"
# https://docs.allauth.org/en/latest/account/forms.html
ACCOUNT_FORMS = {"signup": "chattersift.users.forms.UserSignupForm"}
# https://docs.allauth.org/en/latest/socialaccount/configuration.html
SOCIALACCOUNT_ADAPTER = "chattersift.users.adapters.SocialAccountAdapter"
# https://docs.allauth.org/en/latest/socialaccount/configuration.html
SOCIALACCOUNT_FORMS = {"signup": "chattersift.users.forms.UserSocialSignupForm"}
# django-compressor
# ------------------------------------------------------------------------------
# https://django-compressor.readthedocs.io/en/latest/quickstart/#installation
INSTALLED_APPS += ["compressor"]
STATICFILES_FINDERS += ["compressor.finders.CompressorFinder"]

# Your stuff...
# ------------------------------------------------------------------------------
