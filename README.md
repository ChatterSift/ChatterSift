# ChatterSift — Open-source Reddit monitoring

> Before going further, take 30 seconds to head to **[chattersift.com](https://chattersift.com)** and register a free account to see if it's useful to you. The hosted SaaS is the fastest way to find out — self-hosting is documented below if you'd rather run it yourself.

**Reddit monitoring** for keywords and topics you care about — open source and self-hostable.

![ChatterSift matches view — Reddit posts and comments matching your keyword monitors](docs/images/matches.png)

ChatterSift is an open-source Reddit monitoring app: define keyword monitors across subreddits and get matching posts and comments delivered as alerts. Built as a Django app, HTMX/server-rendered first.

## Features

- **Keyword matching** — exact phrases, word boundaries, or regex across post titles, bodies, and comments, with negative filters to kill false positives.
- **Multi-subreddit monitoring** — one monitor configuration covers every community on its list. Scale from five subreddits to five hundred without rewriting a rule.
- **Instant email alerts** — matches delivered to your inbox within minutes. Per-keyword rate limits keep things usable.
- **Your data, your control** — use the hosted SaaS or self-host the open source. Either way, your keywords and match history stay in your stack.
- **Background processing** — Celery workers with retries and back-pressure. The monitor doesn't sleep, and alerts don't pile up.
- **Open source, MIT-licensed** — read it, fork it, extend it. No lock-in.

## Self-Hosted Deployment

ChatterSift is designed to run on a single VPS with Docker Compose. Caddy terminates HTTPS, Postgres and Redis run as internal services on named volumes, and migrations run automatically before Django and Celery start.

### Requirements

You only need these on the VPS itself — everything else (Python, Node, Postgres, Redis) runs inside containers.

- **VPS** with at least **2 GB RAM** and **15 GB disk** (Postgres, Redis, Django, Celery worker, Celery beat, and Caddy all run on the same host).
- **GNU Make**
- **Docker** with the Compose v2 plugin (`docker compose`, not `docker-compose`)
- **Python 3** — stdlib only, used by `scripts/bootstrap-deploy-env`
- **git** — to clone the repo and pull upgrades

### First deploy

```bash
make deploy-init      # generates .env.production with internal secrets
```

Edit `.env.production` and set at minimum:

- `CHATTERSIFT_SITE_DOMAIN`
- `CADDY_SITE_ADDRESS`
- `CADDY_ACME_EMAIL`
- `DJANGO_ALLOWED_HOSTS`
- `DJANGO_CSRF_TRUSTED_ORIGINS`
- `DJANGO_DEFAULT_FROM_EMAIL` / `DJANGO_SERVER_EMAIL`
- `CHATTERSIFT_EMAIL_PROVIDER` and the matching provider credentials

Then bring up the production stack:

```bash
make deploy           # alias for `make up production` — build + start
make deploy-logs      # follow production logs
```

The production stack includes Postgres, Redis, Django (Gunicorn + Uvicorn workers), Celery worker, Celery beat, and Caddy. Health check: `/healthz/`.

### Upgrades

```bash
git pull
make deploy
```

The `migrate` service runs `migrate --noinput` and syncs `django_site` from `CHATTERSIFT_SITE_DOMAIN` before Django and Celery start.

### Production management

```bash
make deploy-manage shell                 # Django shell in production container
make deploy-manage createsuperuser
make ps production                       # list running containers
make logs production [service]           # follow logs for a single service
make down production                     # stop the stack
```

### Backups

```bash
make backup                              # snapshot the production database
make backups                             # list snapshots
make restore <backup-file>               # restore from a snapshot
```

See [docs/deployment.md](docs/deployment.md) for the full reference, including email provider configuration, LLM credentials, and backup retention.

## Local Development

Install Python dependencies and run the local stack:

```bash
uv sync
make shell            # serve Django on http://127.0.0.1:8000 (runs migrations + collectstatic)
```

Or run everything in Docker:

```bash
make up               # start the local Docker stack
make manage migrate   # run management commands in the Docker django service
```

`make help` lists every target. All Make targets accept an optional `local` / `production` mode argument (default: `local`).

### Tailwind CSS

```bash
npm install
npm run build:css     # one-off build
npm run watch:css     # rebuild on template / style changes
```

Source: `chattersift/static/src/project.css`. Compiled output: `chattersift/static/css/project.css` (already linked from the base template).

### Tests, lint, types

```bash
make test             # uv run pytest
make lint             # uv run ruff check .
make type             # uv run ty check
make template-lint    # djlint
make migration-check  # detect missing migrations
```

Tests use `pytest` + `pytest-django` and read `DATABASE_URL`; use Postgres locally.

### Users

- Create a normal account through the Sign Up form; email verification shows up in the console (or Mailpit at `http://127.0.0.1:8025` when running Docker).
- Create a superuser with `uv run python manage.py createsuperuser` (or `make manage createsuperuser` in Docker).

### Celery

```bash
cd chattersift
uv run celery -A config.celery_app worker -l info
uv run celery -A config.celery_app beat        # periodic tasks
```

Run `celery` from the directory containing `manage.py` so Celery's import magic resolves correctly. The Docker stacks run a worker and beat container automatically.
