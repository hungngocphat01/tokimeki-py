# tokimeki (Python package): design notes

Why the package looks the way it does. For using it, see the
[README](../README.md); for how tokimeki works, the CLI docs
(`tokimeki-cli/docs/HOW-IT-WORKS.md`, `USAGE.md`). The engine-side contract
(the `python-uv` and `python-conda` execute types, the job environment, `tok report`) is
specified in `tokimeki-engine/docs/protocol.md`.

Status: implemented for v0.8.0 (execute ABI 2). Versioning: see `AGENTS.md`.

## Principles (from the user)

- **A shim, like the CLI.** The package converts arguments, runs
  `tok ... --json` and parses the output. Everything that is business logic
  (job accounting, storing inputs and results, classifying failures,
  waiting, building the job's command, validating requests) is the engine's.
- **It writes no files.** Results and errors go through `tok report`; the
  job's argument comes from `tok job`. (Writing a temporary JSON file to pass
  with `--from-json` would be allowed; stdin made it unnecessary.)

## Choices

- **Binding: run the binary**, not a cgo library: fork-safe with
  `multiprocessing`, one static binary, and the same JSON schema as the CLI.
  The binary is `$TOKIMEKI_BIN` (the runner sets it inside jobs, so a job
  uses its runner's version), then `tokimeki` or `tok` on `PATH`.
- **Requests go on stdin** (`--from-json -`), so nothing needs cleaning up.
- **Notices.** `{"notice": ...}` lines on stderr become
  `TokimekiWarning` warnings (level `warning`) or `logging` debug records
  (level `debug`); `--verbose` is passed only when the `tokimeki` logger is
  at DEBUG.
- **Errors.** The `{"error": {"code", "message"}}` envelope becomes
  `TokimekiError(code, message)`; scripts branch on `code`.
- **Job targets.** A top-level function of an importable module
  (`module:function`) or of the running script (`/abs/file.py:function`,
  loaded under another module name so its `__main__` block doesn't rerun).
  `get_job_entry_from_func` rejects lambdas, methods and nested functions at
  submit, before any CLI call. One JSON argument: `fn(arg)`.
- **No dedup.** Skipping configs that already have a job is user code
  (`group.jobs()` + `desc`), as decided for coordinators in phase 2.
- **No `Group.stop()`** yet: there is no CLI command to stop a group by name;
  killing the coordinator stops its group.
- **uv or conda: detected, overridable.** `group.submit` sends the
  execute type of the coordinator's own environment: `python-conda` (with
  `env=sys.prefix`) when `sys.prefix` has `conda-meta/`, else `python-uv`.
  `TK_EXECUTOR=python-uv|python-conda`, set in the script that launches the
  coordinator, overrides it (`get_executor`). Forcing conda outside a conda
  environment sends no `env`, so the engine uses `$CONDA_PREFIX`. The
  runner uses `conda run`, so the env's activation scripts run.
- **`Group.result` raises `not_found`** for a job without a result, rather
  than returning `None`, so a `None` return and a missing result can't be
  confused.

## The runtime (`tokimeki.call`)

The only part that isn't a wrapper; see the README for its behaviour and
exit codes. It depends on three CLI shapes, pinned by execute ABI 2: the
runner's command line, `tok job --json` (`execute.entry`, `execute.arg`,
`execute.cwd`), and `tok report --from-json` (`{"result"}` or
`{"error": {"stage", "type", "message", "traceback"}}`).

## Testing

- Unit tests run against a stand-in `tok` (`tests/conftest.py`) that records
  each call and answers from a table.
- `tests/test_integration.py` runs a real `tok` runner (set
  `TOKIMEKI_TEST_BIN`), with a stand-in `uv` that execs
  `python -m tokimeki.call`.
- Docker (2026-11-20, recorded in the engine roadmap memo): a three-runner
  cluster with real `uv` and an evident-like sweep project; again on
  2026-11-23 with real conda (miniforge) for `python-conda`.
