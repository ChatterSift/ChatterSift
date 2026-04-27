---
name: fix
description: Run project code quality tools and fix detected issues. Use when Codex is asked to fix linting, formatting, type-checking, or template quality problems; run the required Python backend checks in order, repair failures instead of suppressing them unless suppression is necessary, and report any remaining errors.
---

# Fix

## Workflow

Run all backend commands from the project root. Complete the backend sequence before doing any frontend work.

1. Run `ruff check . --fix` to lint and auto-fix Python code.
2. Run `ruff format .` to format Python code.
3. Run `ty check` for Python type checking. Do not use an auto-fix mode for type errors.
4. Run `djlint .` to check Django templates.

## Fixing Failures

- If a command fails after auto-fixes, inspect the reported files and fix the underlying issue.
- Prefer code or template corrections over suppressions. Suppress only when the diagnostic is incorrect or the local pattern clearly requires it.
- Re-run the relevant failing command after each fix. When multiple tools could be affected by the edit, re-run the full sequence.
- Treat `ty check` errors as issues to repair manually, not as a reason to skip the later checks.

## Reporting

- If all tools pass cleanly, say that the code quality checks are clean.
- If any issue cannot be fixed, report the exact command, the remaining diagnostic, and the reason it remains.
