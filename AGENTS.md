# AGENTS.md — tokimeki-py

Python package for Tokimeki (`import tokimeki as tk`): coordinators submit
Python functions as compute jobs, wait on their group and read results. It
also provides the job runtime the runner starts, `python -m tokimeki.call`.
Design notes: `docs/design.md`; the engine-side contract (execute types, job
environment, `tok report`) is `tokimeki-engine/docs/protocol.md`.

## Principles

- **A thin shim over the CLI.** Every call runs one `tok ... --json`
  process. Business logic (job accounting, result storage, failure
  classification, waiting, command construction, validation) belongs in the
  engine, not here.
- **It writes no files.** Requests go on stdin (`--from-json -`); results
  and errors go through `tok report`.

## Layout

| Module | Responsibility |
|---|---|
| `_cli.py` | Runs the binary (`$TOKIMEKI_BIN`, else `tokimeki`/`tok` on `PATH`); error envelope → `TokimekiError`, notices → warnings/logging |
| `_group.py` | `Group` (submit, report, jobs, wait, result), `current_group`, `get_executor` (uv or conda, `$TK_EXECUTOR` override), `get_job_entry_from_func` |
| `_types.py` | Typed views of the CLI's JSON |
| `call.py` | Job runtime for `python-uv` and `python-conda` jobs |

## Commands

```bash
uv run pytest -q
TOKIMEKI_TEST_BIN=/path/to/tokimeki uv run pytest -q   # also the integration tests
```

## Versioning and releases

The version is in `pyproject.toml` and `src/tokimeki/__init__.py`; release
tags are `vX.Y.Z` on `main`, and the README's install lines name the tag.

- **Follow the engine and CLI.** When an engine/CLI release changes the
  protocol and this package must be updated for it, release this package
  with the same version as the engine and CLI (e.g. engine v0.8.0 →
  tokimeki-py v0.8.0). Engine releases that need no change here get no
  tokimeki-py release.
- **Package-only changes** (no engine or CLI change) get a numbered suffix
  on the engine version they follow: `0.8.0-1`, `0.8.0-2`, ... (tag
  `v0.8.0-1`). Python normalizes `0.8.0-1` to `0.8.0.post1`.

## Commits

Conventional-style subjects (`feat:`, `fix:`, `refactor:`, `docs:`),
imperative mood. Commit or push only when asked.
