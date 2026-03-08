# Contributing to Traxx

Thanks for taking the time to contribute.

## Before You Start

- Open an issue first for significant changes (new feature, architecture change, behavior change).
- Keep pull requests focused: one concern per PR.
- Never commit secrets (`.env`, cookies, tokens, personal IDs).

## Local Setup

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
python -m pip install -r requirements.txt
```

3. Create your local `.env` from project documentation in `README.md`.

## Development Workflow

1. Create a branch from `main`.
2. Implement your change with clear, small commits.
3. Run checks before opening a PR.
4. Open a PR with context, rationale, and test notes.

## Quality Bar

### Code style

- Prefer small, single-responsibility functions.
- Avoid hidden side effects.
- Use explicit names over short/ambiguous names.
- Keep constants in `traxx_core/constants.py`.
- Add short comments only when logic is non-obvious.

### Type hints and structure

- Add type hints for new public/internal APIs.
- Use dataclasses for grouped runtime options/config when appropriate.
- Avoid long argument lists; prefer typed option objects.

### Error handling

- Fail with actionable messages.
- Keep user-facing messages readable (what failed, what to do next).
- Preserve existing behavior unless your PR explicitly changes it.

## Validation Before PR

At minimum, run:

```bash
.\.venv\Scripts\python.exe -m py_compile traxx_core\app.py traxx_core\constants.py traxx_core\csv_store.py traxx_core\downloader.py traxx_core\spotify.py traxx_core\utils.py traxx_core\__init__.py traxx.py
```

If your change impacts runtime behavior, also run at least one manual scenario:

- `python traxx.py --no-download`
- `python traxx.py --dry-run --limit 3`

## Pull Request Checklist

- [ ] My branch is up to date with `main`.
- [ ] I kept the scope focused.
- [ ] I added/updated docs when behavior changed.
- [ ] I validated the code locally (compile + relevant manual run).
- [ ] I did not commit secrets or generated personal data.

## Project Map (Quick Reference)

- `traxx.py`: executable entrypoint
- `traxx_core/app.py`: CLI orchestration
- `traxx_core/spotify.py`: Spotify OAuth and API fetching
- `traxx_core/csv_store.py`: CSV merge/read/write behavior
- `traxx_core/downloader.py`: YouTube selection/download workflow
- `traxx_core/utils.py`: cross-module helpers
- `traxx_core/constants.py`: shared constants
