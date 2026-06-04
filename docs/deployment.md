# Self-Hosted Docker Deployment

This deployment path targets one VPS running Docker Compose. Caddy terminates HTTPS, Postgres and Redis run as internal services with named Docker volumes, and migrations run automatically before Django and Celery start.

## First Deploy

```bash
uv sync
make deploy-init
```

Edit `.env.production`. The bootstrap command generates internal secrets for `DJANGO_SECRET_KEY`, `DJANGO_ADMIN_URL`, and `POSTGRES_PASSWORD`; do not share those values.

Required user-edited values:

- `CHATTERSIFT_SITE_DOMAIN`: bare public domain, for example `chattersift.example.com`.
- `CADDY_SITE_ADDRESS`: Caddy site label, for example `chattersift.example.com` or `example.com, www.example.com`.
- `CADDY_ACME_EMAIL`: email address used for Let's Encrypt notices.
- `DJANGO_ALLOWED_HOSTS`: comma-separated public hosts.
- `DJANGO_CSRF_TRUSTED_ORIGINS`: comma-separated `https://` origins.
- `DJANGO_DEFAULT_FROM_EMAIL` and `DJANGO_SERVER_EMAIL`: sender addresses.
- `DJANGO_ADMIN_EMAIL`: address that receives error notifications.
- `CHATTERSIFT_EMAIL_PROVIDER` plus the provider credentials below.

Optional toggles:

- `DJANGO_ACCOUNT_ALLOW_REGISTRATION`: set to `False` to disable public signups.
- `WEB_CONCURRENCY`: Gunicorn worker count (default `1`).
- `CELERY_WORKER_CONCURRENCY`: Celery worker concurrency (default `1`).

Start the stack:

```bash
make deploy
```

Django is served behind Caddy. The health endpoint is available at `/healthz/`.

## Common Commands

```bash
make deploy                 # build, migrate, and start
make deploy-logs            # follow logs
make deploy-manage shell    # run a Django management command
make deploy-manage createsuperuser
make ps production
```

## Upgrades

Pull the new code, review any new variables in `.env.production.example`, update `.env.production`, then run:

```bash
make deploy
```

The `migrate` service runs `migrate --noinput` and syncs `django_site` from `CHATTERSIFT_SITE_DOMAIN` before Django and Celery start.

## Email Providers

Set `CHATTERSIFT_EMAIL_PROVIDER` to one of:

`smtp`, `amazon_ses`, `mailgun`, `postmark`, `brevo`, `resend`, `mailjet`, `mailersend`.

SMTP example:

```dotenv
CHATTERSIFT_EMAIL_PROVIDER=smtp
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_HOST_USER=apikey
EMAIL_HOST_PASSWORD=secret
EMAIL_USE_TLS=True
EMAIL_USE_SSL=False
```

Postmark example:

```dotenv
CHATTERSIFT_EMAIL_PROVIDER=postmark
ANYMAIL_POSTMARK_SERVER_TOKEN=secret
```

Resend example:

```dotenv
CHATTERSIFT_EMAIL_PROVIDER=resend
ANYMAIL_RESEND_API_KEY=secret
```

Mailgun example:

```dotenv
CHATTERSIFT_EMAIL_PROVIDER=mailgun
ANYMAIL_MAILGUN_API_KEY=secret
ANYMAIL_MAILGUN_SENDER_DOMAIN=mg.example.com
```

Amazon SES uses Anymail's SES backend:

```dotenv
CHATTERSIFT_EMAIL_PROVIDER=amazon_ses
ANYMAIL_AMAZON_SES_REGION_NAME=us-east-1
```

`ANYMAIL_AMAZON_SES_CLIENT_PARAMS` remains available for advanced boto3 client options that need a JSON object.

SendGrid is not a first-tier provider because current Anymail support warns that official support was dropped. Use SMTP for SendGrid unless a dedicated integration is added later.

## Optional Semantic Matching

Semantic matching is disabled by default. Enable it by setting:

```dotenv
CHATTERSIFT_SEMANTIC_LLM_MODEL=gpt-4.1-mini
CHATTERSIFT_SEMANTIC_LLM_API_KEY=secret
```

Set `CHATTERSIFT_SEMANTIC_LLM_BASE_URL` to point at an OpenAI-compatible endpoint (for example a self-hosted gateway or Azure deployment).

You can also use provider-native LiteLLM variables such as:

```dotenv
OPENAI_API_KEY=secret
ANTHROPIC_API_KEY=secret
GEMINI_API_KEY=secret
```

## Error Reporting (Optional)

Sentry is wired in but disabled until a DSN is set:

```dotenv
SENTRY_DSN=https://...ingest.sentry.io/...
SENTRY_ENVIRONMENT=production
SENTRY_TRACES_SAMPLE_RATE=0.0
```

Raise `SENTRY_TRACES_SAMPLE_RATE` to sample performance traces; leave at `0.0` to capture errors only.

## Backups And Restore

Postgres data lives in the `production_postgres_data` Docker volume. Backup files are written to `production_postgres_data_backups`.

Create a database backup:

```bash
make backup
```

List backup files:

```bash
make backups
```

Restore a backup:

```bash
make restore <backup-file>
```

Test restores on a separate host before relying on a backup process.

## Troubleshooting

If HTTPS certificates fail, check that DNS points to the VPS and that `CADDY_SITE_ADDRESS` matches the public hostnames.

If Django returns `DisallowedHost`, update `DJANGO_ALLOWED_HOSTS`.

If forms fail CSRF checks, update `DJANGO_CSRF_TRUSTED_ORIGINS` with full `https://` origins.

If email is not delivered, verify `CHATTERSIFT_EMAIL_PROVIDER`, provider credentials, and sender domain verification with the provider.

If the app starts without styling, rebuild the image with `make deploy`; the production Dockerfile runs `npm ci && npm run build:css`.
