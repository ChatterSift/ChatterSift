# Repository Guidelines

## Project Structure & Module Organization

Chattersift is a Django 5.2 project generated from cookiecutter-django and adapted for an extensible setup. Core source lives under `chattersift/`, with Django project configuration in `config/`.

- `chattersift/users/`: authentication and user management.
- `chattersift/tracking/`: monitors, keywords, and match records.
- `chattersift/reddit/`: Reddit fetch state, normalized Reddit items, and ingestion services.
- `chattersift/alerts/`: alert delivery primitives.
- `chattersift/core/`: shared utilities and extension contracts.
- `chattersift/templates/`, `chattersift/static/`: server-rendered UI and assets.
- `tests/` and `chattersift/**/tests/`: pytest suites.

## Build, Test, and Development Commands

Use `uv` for Python environment and dependency management.

```bash
uv sync                         # Install locked dependencies
uv run python manage.py check   # Validate Django configuration
uv run pytest                   # Run the test suite
uv run ruff check .             # Run lint checks
uv run ty check                 # Run type checks
just up                         # Start local Docker services
just manage migrate             # Run Django management commands in Docker
```

Direnv is supported via `.envrc`. Keep local secrets in `.env` or `.envrc.local`; both are gitignored.

## Coding Style & Naming Conventions

Use 4-space indentation for Python. Keep apps small and domain-focused. Prefer explicit service functions in `services.py` for business logic instead of placing orchestration in views or Celery tasks.

Use snake_case for modules, functions, fields, and task names. Use PascalCase for Django models, forms, schemas, and class-based views.

Ruff is the source of truth for linting. Do not hand-format imports against Ruff’s configured ordering.

## Testing Guidelines

Tests use `pytest` and `pytest-django`. Name test files `test_*.py` and colocate app-specific tests under `chattersift/<app>/tests/`.

Run:

```bash
uv run pytest
```

The test settings read `DATABASE_URL`; development should use Postgres.

## Commit & Pull Request Guidelines
- Recent history favors short, imperative commit subjects.
- Keep commits focused; reference issues when relevant.
- PRs should include: clear summary, testing steps/results, and screenshots for UI/extension changes.
- Call out migrations, environment-variable changes, or breaking behavior explicitly in the PR description.
- Keep public core changes independent; this repo must run without importing external overlays.


## Architecture Notes

This is HTMX/server-rendered first. Django Ninja APIs are opt-in via `CHATTERSIFT_ENABLE_API` and should be added only when an API is genuinely required. Extension should happen through Django apps, URLConfs, settings overlays, and explicit service boundaries.

## Project-Specific Engineering Practices
- When fixing bugs, add a regression test in the closest test module before merging.
- Prefer modular code over monolithic code.
- Prefer explicit behavior over hidden magic.
- Use existing code style conventions and patterns.
- All imports must be added on top of the file, NEVER inside the function.
- Do not swallow exceptions unless the scenario calls for fault tolerance.
- Always include interface comments. Include certain inline comments when code is less clear.

## Frontend UX and Style
- Provide inline loading indicators for async operations (e.g., `hx-indicator="#global-loading"`); avoid toasts unless destructive confirmations, external errors, or background task notifications.
- Follow the frontend color system in `COLOR_SYSTEM.md`.
- Use DaisyUI semantic color classes (`bg-primary`, `text-error`, etc.) instead of raw Tailwind colors.
- Use DaisyUI component classes (`btn`, `badge`, `alert`, `loading`, etc.) for consistent styling.
- Do not include CSS classes in `forms.py`; use `render_field` in templates instead.
- Use {# ... #} instead of <!-- ... --> for comments in django templates.
