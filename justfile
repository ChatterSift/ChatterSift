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

# build: Build Docker images. Use `local` or `production`.
build mode="local" *args:
    @echo "Building python image..."
    @if [ "{{mode}}" = "local" ]; then \
        {{load-local-postgres}} docker compose -f docker-compose.local.yml build {{args}}; \
    elif [ "{{mode}}" = "production" ]; then \
        {{load-production-env}} docker compose -f docker-compose.production.yml build {{args}}; \
    else \
        echo "Unknown mode '{{mode}}'. Use 'local' or 'production'."; \
        exit 2; \
    fi

# up: Start Docker containers. Use `local` or `production`.
up mode="local":
    @npm install
    @npm run build:css
    @if [ "{{mode}}" = "local" ]; then \
        echo "Starting local Docker containers..." && \
        {{load-local-postgres}} docker compose -f docker-compose.local.yml up -d --remove-orphans && \
        {{load-local-postgres}} docker compose -f docker-compose.local.yml run --rm django python ./manage.py collectstatic --noinput; \
    elif [ "{{mode}}" = "production" ]; then \
        echo "Starting production Docker containers..." && \
        {{load-production-env}} docker compose -f docker-compose.production.yml up -d --build --remove-orphans; \
    else \
        echo "Unknown mode '{{mode}}'. Use 'local' or 'production'."; \
        exit 2; \
    fi

# down: Stop Docker containers. Use `local` or `production`.
down mode="local":
    @if [ "{{mode}}" = "local" ]; then \
        echo "Stopping local Docker containers..." && \
        docker compose -f docker-compose.local.yml down; \
    elif [ "{{mode}}" = "production" ]; then \
        echo "Stopping production Docker containers..." && \
        docker compose -f docker-compose.production.yml down; \
    else \
        echo "Unknown mode '{{mode}}'. Use 'local' or 'production'."; \
        exit 2; \
    fi

# prune: Remove containers and their volumes.
prune mode="local" *args:
    @if [ "{{mode}}" = "local" ]; then \
        echo "Killing local containers and removing volumes..." && \
        docker compose -f docker-compose.local.yml down -v {{args}}; \
    elif [ "{{mode}}" = "production" ]; then \
        echo "Killing production containers and removing volumes..." && \
        docker compose -f docker-compose.production.yml down -v {{args}}; \
    else \
        echo "Unknown mode '{{mode}}'. Use 'local' or 'production'."; \
        exit 2; \
    fi

# logs: View container logs
logs mode="local" *args:
    @if [ "{{mode}}" = "local" ]; then \
        docker compose -f docker-compose.local.yml logs -f {{args}}; \
    elif [ "{{mode}}" = "production" ]; then \
        docker compose -f docker-compose.production.yml logs -f {{args}}; \
    else \
        echo "Unknown mode '{{mode}}'. Use 'local' or 'production'."; \
        exit 2; \
    fi

# manage: Execute `manage.py` in local Docker.
manage +args:
    @just manage-local {{args}}

# manage-local: Execute `manage.py` in local Docker.
manage-local +args:
    @{{load-local-postgres}} docker compose -f docker-compose.local.yml run --rm django python ./manage.py {{args}}

# manage-production: Execute `manage.py` in production Docker.
manage-production +args:
    @{{load-production-env}} docker compose -f docker-compose.production.yml run --rm django python ./manage.py {{args}}

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
