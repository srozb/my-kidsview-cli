# Repository Guidelines

This repo hosts `kidsview-cli`, a Python command-line tool used by humans or automation to interact with the Kidsview platform (attendance, assessments, meals, tuition, and related school data). Keep changes small, tested, and automation-friendly.

## Project Structure & Module Organization
- `src/` — CLI entrypoint and reusable modules (API client, commands, config).
- `tests/` — unit/integration tests mirroring `src/` layout.
- `scripts/` — helper scripts (release, data fixtures).
- `docs/` — supplementary design notes or API references.
- Prefer package-first layout (`src/kidsview_cli/...`), keep command groups isolated per file (e.g., `attendance.py`, `meals.py`).

## Build, Test, and Development Commands
- Install tooling: `uv sync` (resolves deps from `pyproject.toml`; includes dev deps).
- Run CLI locally: `uv run kidsview-cli --help`.
- Format/lint: `uv run ruff check --fix` and `uv run ruff format`.
- Type-check: `uv run mypy src`.
- Tests: `uv run pytest`.
- Pre-commit (one-shot): `uv run pre-commit run --all-files`.

## Coding Style & Naming Conventions
- Target Python 3.11+; prefer dataclasses, `pathlib`, `typing` (use `list[str]` not `List[str]`), `httpx`/`pydantic` for API and models.
- Indent with 4 spaces; keep lines ≤ 100 chars.
- CLI: use `typer` for commands, `rich` for output; keep side effects behind `if __name__ == "__main__":`.
- Modules and files: `snake_case`; classes: `PascalCase`; constants: `UPPER_SNAKE_CASE`.
- Configuration via env vars or config file under `~/.config/kidsview-cli/`.

## Testing Guidelines
- Use `pytest` with descriptive test names (`test_command_returns_error_on_missing_token`).
- Mirror package structure under `tests/` with fixtures in `tests/conftest.py`.
- Include HTTP mocks (e.g., `respx`) for API calls; avoid live network in tests.
- Aim for coverage on new logic; add regression tests for bug fixes.

## Commit & Pull Request Guidelines
- Follow conventional-style messages where practical: `feat: add attendance sync`, `fix: handle meal prices`, `chore: update deps`.
- Keep commits scoped and reviewable; include CLI usage notes in PR descriptions.
- PRs should describe intent, testing performed (`pytest`, `ruff`, `mypy`, `pre-commit`), and any user-facing changes (flags, config keys, examples).
- Add screenshots or terminal snippets for notable CLI UX changes.

## Security & Configuration Tips
- Never commit secrets; prefer `.env` (excluded via `.gitignore`) or platform secrets.
- Validate inputs and API responses; fail fast with clear error messages.
- Ensure commands are idempotent for automation/agent use; avoid destructive defaults.
