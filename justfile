export COMPOSE_FILE := "docker-compose.local.yml"
export DJANGO_READ_DOT_ENV_FILE := "True"
load-local-postgres := "set -a; . ./.envs/.local/.postgres; set +a;"
load-production-env := "set -a; . ./.envs/.production/.django; . ./.envs/.production/.postgres; set +a;"

## Just does not yet manage signals for subprocesses reliably, which can lead to unexpected behavior.
## Exercise caution before expanding its usage in production environments.
## For more information, see https://github.com/casey/just/issues/2473 .


# Default command to list all available commands.
default:
    @just --list

# build: Build python image.
build *args:
    @echo "Building python image..."
    @{{load-local-postgres}} docker compose build {{args}}

# up: Start up containers.
up:
    @npm install
    @npm run build:css
    @echo "Starting up containers..."
    @{{load-local-postgres}} docker compose up -d --remove-orphans
    @{{load-local-postgres}} docker compose run --rm django python ./manage.py collectstatic --noinput

# down: Stop containers.
down:
    @echo "Stopping containers..."
    @docker compose down

# prune: Remove containers and their volumes.
prune *args:
    @echo "Killing containers and removing volumes..."
    @docker compose down -v {{args}}

# logs: View container logs
logs *args:
    @docker compose logs -f {{args}}

# manage: Executes `manage.py` command.
manage +args:
    @{{load-local-postgres}} docker compose run --rm django python ./manage.py {{args}}

# setup: Prepare a shell run. Use `local` or `production`.
setup mode="local":
    @if [ "{{mode}}" = "local" ]; then \
        npm install && \
        npm run build:css && \
        DJANGO_SETTINGS_MODULE=config.settings.local uv run python manage.py migrate --noinput && \
        DJANGO_SETTINGS_MODULE=config.settings.local uv run python manage.py collectstatic --noinput; \
    elif [ "{{mode}}" = "production" ]; then \
        npm install && \
        npm run build:css && \
        {{load-production-env}} DJANGO_SETTINGS_MODULE=config.settings.production uv run python manage.py migrate --noinput && \
        {{load-production-env}} DJANGO_SETTINGS_MODULE=config.settings.production uv run python manage.py collectstatic --noinput; \
    else \
        echo "Unknown mode '{{mode}}'. Use 'local' or 'production'."; \
        exit 2; \
    fi

# run: Run chattersift in `local` mode with runserver or `production` mode with gunicorn.
run mode="local": (setup mode)
    @if [ "{{mode}}" = "local" ]; then \
        DJANGO_SETTINGS_MODULE=config.settings.local uv run python manage.py runserver 127.0.0.1:8000; \
    elif [ "{{mode}}" = "production" ]; then \
        {{load-production-env}} DJANGO_SETTINGS_MODULE=config.settings.production uv run gunicorn config.asgi --bind 0.0.0.0:5000 -k uvicorn_worker.UvicornWorker; \
    else \
        echo "Unknown mode '{{mode}}'. Use 'local' or 'production'."; \
        exit 2; \
    fi

# shell: Alias for `just run local`.
shell:
    @just run local

# css: Build Tailwind CSS.
css:
    @npm run build:css

# css-watch: Rebuild Tailwind CSS when templates or source styles change.
css-watch:
    @npm run watch:css

# pre-commit: Run the repo's lint, type, and template checks locally.
pre-commit:
    @uv run ruff check . --fix
    @uv run ruff format .
    @uv run ty check
    @uv run djlint .
