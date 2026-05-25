# Self-Hosted Docker Deployment

This deployment path targets one VPS running Docker Compose. Caddy terminates HTTPS, Postgres and Redis run as internal services with named Docker volumes, and migrations run automatically before Django and Celery start.

## First Deploy

```bash
uv sync
just deploy-init
```

Edit `.env.production`. The bootstrap command generates internal secrets for `DJANGO_SECRET_KEY`, `DJANGO_ADMIN_URL`, and `POSTGRES_PASSWORD`; do not share those values.

Required user-edited values:

- `CHATTERSIFT_SITE_DOMAIN`: bare public domain, for example `chattersift.example.com`.
- `CADDY_SITE_ADDRESS`: Caddy site label, for example `chattersift.example.com` or `example.com, www.example.com`.
- `CADDY_ACME_EMAIL`: email address used for Let's Encrypt notices.
- `DJANGO_ALLOWED_HOSTS`: comma-separated public hosts.
- `DJANGO_CSRF_TRUSTED_ORIGINS`: comma-separated `https://` origins.
- `DJANGO_DEFAULT_FROM_EMAIL` and `DJANGO_SERVER_EMAIL`: sender addresses.
- `CHATTERSIFT_EMAIL_PROVIDER` plus the provider credentials below.

Start the stack:

```bash
just deploy
```

Django is served behind Caddy. The health endpoint is available at `/healthz/`.

## Common Commands

```bash
just deploy                 # build, migrate, and start
just deploy-logs            # follow logs
just deploy-manage shell    # run a Django management command
just deploy-manage createsuperuser
docker compose --env-file .env.production -f docker-compose.production.yml ps
```

## Upgrades

Pull the new code, review any new variables in `.env.production.example`, update `.env.production`, then run:

```bash
just deploy
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
ANYMAIL_AMAZON_SES_CLIENT_PARAMS={"region_name":"us-east-1"}
```

SendGrid is not a first-tier provider because current Anymail support warns that official support was dropped. Use SMTP for SendGrid unless a dedicated integration is added later.

## Optional Semantic Matching

Semantic matching is disabled by default. Enable it by setting:

```dotenv
CHATTERSIFT_SEMANTIC_LLM_MODEL=gpt-4.1-mini
CHATTERSIFT_SEMANTIC_LLM_API_KEY=secret
```

You can also use provider-native LiteLLM variables such as:

```dotenv
OPENAI_API_KEY=secret
ANTHROPIC_API_KEY=secret
GEMINI_API_KEY=secret
```

## Backups And Restore

Postgres data lives in the `production_postgres_data` Docker volume. Backup files are written to `production_postgres_data_backups`.

Create a database backup:

```bash
docker compose --env-file .env.production -f docker-compose.production.yml run --rm postgres backup
```

List backup files:

```bash
docker compose --env-file .env.production -f docker-compose.production.yml run --rm postgres backups
```

Restore using the cookiecutter maintenance command:

```bash
docker compose --env-file .env.production -f docker-compose.production.yml run --rm postgres restore <backup-file>
```

Test restores on a separate host before relying on a backup process.

## Troubleshooting

If HTTPS certificates fail, check that DNS points to the VPS and that `CADDY_SITE_ADDRESS` matches the public hostnames.

If Django returns `DisallowedHost`, update `DJANGO_ALLOWED_HOSTS`.

If forms fail CSRF checks, update `DJANGO_CSRF_TRUSTED_ORIGINS` with full `https://` origins.

If email is not delivered, verify `CHATTERSIFT_EMAIL_PROVIDER`, provider credentials, and sender domain verification with the provider.

If the app starts without styling, rebuild the image with `just deploy`; the production Dockerfile runs `npm ci && npm run build:css`.
