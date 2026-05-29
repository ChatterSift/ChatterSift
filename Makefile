SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

export DJANGO_READ_DOT_ENV_FILE := True

LOCAL_COMPOSE_FILE := docker-compose.local.yml
PRODUCTION_COMPOSE_FILE := docker-compose.production.yml
DOCS_COMPOSE_FILE := docker-compose.docs.yml
LOCAL_POSTGRES_ENV := .envs/.local/.postgres
PRODUCTION_ENV_FILE := .env.production

LOCAL_COMPOSE := docker compose -f $(LOCAL_COMPOSE_FILE)
PRODUCTION_COMPOSE := docker compose --env-file $(PRODUCTION_ENV_FILE) -f $(PRODUCTION_COMPOSE_FILE)
DOCS_COMPOSE := docker compose -f $(DOCS_COMPOSE_FILE)

MODE_NAMES := local production
FIRST_ARG := $(word 2,$(MAKECMDGOALS))
PRIMARY_GOAL := $(firstword $(MAKECMDGOALS))
MODE := $(if $(filter $(FIRST_ARG),$(MODE_NAMES)),$(FIRST_ARG),local)
GOAL_ARGS = $(filter-out $@ $(MODE_NAMES),$(MAKECMDGOALS))
CMD_ARGS = $(strip $(GOAL_ARGS) $(ARGS))
RESTORE_BACKUP = $(strip $(or $(BACKUP),$(firstword $(GOAL_ARGS))))

define require_known_mode
	if [[ "$(MODE)" != "local" && "$(MODE)" != "production" ]]; then \
		echo "Unknown mode '$(MODE)'. Use 'local' or 'production'."; \
		exit 2; \
	fi
endef

define local_compose_with_postgres_env
	set -a; . ./$(LOCAL_POSTGRES_ENV); set +a; $(LOCAL_COMPOSE) $(1)
endef

define production_shell_env
	set -a; . ./$(PRODUCTION_ENV_FILE); set +a; $(1)
endef

define setup_for_mode
	npm install
	npm run build:css
	if [[ "$(MODE)" == "production" ]]; then \
		$(call production_shell_env,DJANGO_SETTINGS_MODULE=config.settings.production uv run python manage.py migrate --noinput); \
		$(call production_shell_env,DJANGO_SETTINGS_MODULE=config.settings.production uv run python manage.py collectstatic --noinput); \
	else \
		DJANGO_SETTINGS_MODULE=config.settings.local uv run python manage.py migrate --noinput; \
		DJANGO_SETTINGS_MODULE=config.settings.local uv run python manage.py collectstatic --noinput; \
	fi
endef

.PHONY: help
help: ## List available commands.
	@awk 'BEGIN {FS = ":.*##"; printf "Available commands:\n"} /^[a-zA-Z0-9_-]+:.*##/ {printf "  %-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: sync install
sync install: ## Install locked Python dependencies.
	uv sync

.PHONY: build
build: ## Build Docker images. Use `make build [local|production] ARGS="--no-cache"`.
	@$(call require_known_mode)
	@echo "Building $(MODE) Docker images..."
	@if [[ "$(MODE)" == "production" ]]; then \
		$(PRODUCTION_COMPOSE) build $(CMD_ARGS); \
	else \
		$(call local_compose_with_postgres_env,build $(CMD_ARGS)); \
	fi

.PHONY: deploy-init
deploy-init: ## Generate .env.production with internal secrets.
	scripts/bootstrap-deploy-env $(CMD_ARGS)

.PHONY: deploy
deploy: ## Alias for `make up production`.
	$(MAKE) up production $(CMD_ARGS)

.PHONY: deploy-logs
deploy-logs: ## Follow production Docker logs.
	$(PRODUCTION_COMPOSE) logs -f $(CMD_ARGS)

.PHONY: deploy-manage
deploy-manage: ## Run manage.py in production Docker.
	$(PRODUCTION_COMPOSE) run --rm django python ./manage.py $(CMD_ARGS)

.PHONY: up
up: ## Start Docker containers. Use `make up [local|production]`.
	@$(call require_known_mode)
	@if [[ "$(MODE)" == "production" ]]; then \
		echo "Starting production Docker containers..."; \
		$(PRODUCTION_COMPOSE) up -d --build --remove-orphans $(CMD_ARGS); \
	else \
		echo "Starting local Docker containers..."; \
		npm install; \
		npm run build:css; \
		$(call local_compose_with_postgres_env,up -d --remove-orphans $(CMD_ARGS)); \
		$(call local_compose_with_postgres_env,run --rm django python ./manage.py collectstatic --noinput); \
	fi

.PHONY: down
down: ## Stop Docker containers. Use `make down [local|production]`.
	@$(call require_known_mode)
	@if [[ "$(MODE)" == "production" ]]; then \
		echo "Stopping production Docker containers..."; \
		$(PRODUCTION_COMPOSE) down $(CMD_ARGS); \
	else \
		echo "Stopping local Docker containers..."; \
		$(LOCAL_COMPOSE) down $(CMD_ARGS); \
	fi

.PHONY: prune
prune: ## Remove containers and their volumes. Use `make prune [local|production]`.
	@$(call require_known_mode)
	@if [[ "$(MODE)" == "production" ]]; then \
		echo "Killing production containers and removing volumes..."; \
		$(PRODUCTION_COMPOSE) down -v $(CMD_ARGS); \
	else \
		echo "Killing local containers and removing volumes..."; \
		$(LOCAL_COMPOSE) down -v $(CMD_ARGS); \
	fi

.PHONY: logs
logs: ## Follow container logs. Use `make logs [local|production] [service]`.
	@$(call require_known_mode)
	@if [[ "$(MODE)" == "production" ]]; then \
		$(PRODUCTION_COMPOSE) logs -f $(CMD_ARGS); \
	else \
		$(LOCAL_COMPOSE) logs -f $(CMD_ARGS); \
	fi

.PHONY: ps
ps: ## Show Docker containers. Use `make ps [local|production]`.
	@$(call require_known_mode)
	@if [[ "$(MODE)" == "production" ]]; then \
		$(PRODUCTION_COMPOSE) ps $(CMD_ARGS); \
	else \
		$(LOCAL_COMPOSE) ps $(CMD_ARGS); \
	fi

.PHONY: manage
manage: ## Run manage.py in local Docker.
	$(call local_compose_with_postgres_env,run --rm django python ./manage.py $(CMD_ARGS))

.PHONY: manage-local
manage-local: ## Run manage.py in local Docker.
	$(call local_compose_with_postgres_env,run --rm django python ./manage.py $(CMD_ARGS))

.PHONY: manage-production
manage-production: ## Run manage.py in production Docker.
	$(PRODUCTION_COMPOSE) run --rm django python ./manage.py $(CMD_ARGS)

.PHONY: setup
setup: ## Prepare a shell run. Use `make setup [local|production]`.
	@$(call require_known_mode)
	@$(call setup_for_mode)

.PHONY: run
run: ## Run Chattersift locally or with production settings.
	@$(call require_known_mode)
	@$(call setup_for_mode)
	@if [[ "$(MODE)" == "production" ]]; then \
		$(call production_shell_env,DJANGO_SETTINGS_MODULE=config.settings.production uv run gunicorn config.asgi --bind 0.0.0.0:5000 -k uvicorn_worker.UvicornWorker); \
	else \
		DJANGO_SETTINGS_MODULE=config.settings.local uv run python manage.py runserver 127.0.0.1:8000; \
	fi

.PHONY: shell
shell: ## Alias for `make run local`.
	@if [[ "$(PRIMARY_GOAL)" == "$@" ]]; then \
		$(MAKE) run local; \
	fi

.PHONY: css
css: ## Build Tailwind CSS.
	npm run build:css

.PHONY: css-watch
css-watch: ## Rebuild Tailwind CSS when templates or source styles change.
	npm run watch:css

.PHONY: check
check: ## Validate Django configuration.
	@if [[ "$(PRIMARY_GOAL)" == "$@" ]]; then uv run python manage.py check; fi

.PHONY: test
test: ## Run the test suite.
	@if [[ "$(PRIMARY_GOAL)" == "$@" ]]; then uv run pytest $(CMD_ARGS); fi

.PHONY: lint
lint: ## Run Ruff lint checks.
	@if [[ "$(PRIMARY_GOAL)" == "$@" ]]; then uv run ruff check .; fi

.PHONY: lint-fix
lint-fix: ## Run Ruff lint checks and apply safe fixes.
	@if [[ "$(PRIMARY_GOAL)" == "$@" ]]; then uv run ruff check . --fix; fi

.PHONY: format
format: ## Format Python code with Ruff.
	@if [[ "$(PRIMARY_GOAL)" == "$@" ]]; then uv run ruff format .; fi

.PHONY: type
type: ## Run ty type checks.
	@if [[ "$(PRIMARY_GOAL)" == "$@" ]]; then uv run ty check; fi

.PHONY: template-lint
template-lint: ## Run Django template lint checks.
	@if [[ "$(PRIMARY_GOAL)" == "$@" ]]; then uv run djlint .; fi

.PHONY: migration-check
migration-check: ## Check for missing Django migrations.
	@if [[ "$(PRIMARY_GOAL)" == "$@" ]]; then uv run python manage.py makemigrations --check --dry-run; fi

.PHONY: pre-commit
pre-commit: ## Run the configured pre-commit hooks.
	@if [[ "$(PRIMARY_GOAL)" == "$@" ]]; then uv run pre-commit run --all-files; fi

.PHONY: backup
backup: ## Create a production database backup.
	@if [[ "$(PRIMARY_GOAL)" == "$@" ]]; then $(PRODUCTION_COMPOSE) run --rm postgres backup; fi

.PHONY: backups
backups: ## List production database backups.
	@if [[ "$(PRIMARY_GOAL)" == "$@" ]]; then $(PRODUCTION_COMPOSE) run --rm postgres backups; fi

.PHONY: restore
restore: ## Restore a production database backup. Use `make restore <backup-file>` or `make restore BACKUP=<backup-file>`.
	@if [[ -z "$(RESTORE_BACKUP)" ]]; then \
		echo "Missing backup file. Use 'make restore <backup-file>' or 'make restore BACKUP=<backup-file>'."; \
		exit 2; \
	fi
	$(PRODUCTION_COMPOSE) run --rm postgres restore $(RESTORE_BACKUP)

.PHONY: local production
local production:
	@:

%:
	@:
