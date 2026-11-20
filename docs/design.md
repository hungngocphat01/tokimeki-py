# tokimeki (Python package) — design

Python-specific design for the `tokimeki` package. The engine side of the
contract (submit request, `meta.json` `execute`, job environment, result and
error files, notices) is specified in the engine repo,
`tokimeki-engine/docs/protocol.md`; the JSON request format users see is in
`tokimeki-cli/docs/USAGE.md` ("Submit from JSON").

Status: engine and CLI side implemented in v0.5.0 (job schema 2, execute ABI
2); this package is design only, no code yet.

## Principle

The package is a shim like the CLI: argument conversion, calling
`tok … --json`, parsing results. Business logic (job accounting, input and
result storage, failure classification, waiting, command construction, ABI
validation) lives in the engine.

## Binding

- Exec the `tokimeki` binary with `--json` (fork-safe with `multiprocessing`,
  one static binary, same schema as the CLI). Binary found via `TOKIMEKI_BIN`
  (exported by the runner), then `PATH`.
- Notices arrive on stderr as NDJSON `{"notice": {...}}`: `warning` →
  `warnings.warn(TokimekiWarning(...))`, `debug` → `logging.debug`.
- Errors arrive as the `{"error": {"code", "message"}}` envelope →
  `TokimekiError(code, message)`.

## Job targets

- Callables in importable modules (`module:function`), or a function in a
  script file (`/abs/file.py:function`, loaded under a name other than
  `__main__`). One JSON-serializable argument: `fn(arg)`.
- Jobs are submitted as `python-uv` (`execute.abi` 2); `tokimeki` must be a
  dependency of the user's uv project.

## API

Each call maps to one `tok … --json` call; results become dataclasses
mirroring the `--json` schema.

| Python | `tok` call |
|---|---|
| `Group.submit(fn, arg, *, desc, priority, cpus, mem_mb, retries, backoff, after, project, cwd)` | resolve `fn` to `entry`, build `{"abi": 2, "type": "python-uv", "entry", "arg", "group", ...}`, pipe it to `tok submit --json --from-json -` |
| `Group.jobs()` | `tok ps -a --name <g> --json`, keeping exact group matches (or `group --json` → `jobs`) |
| `Group.report()` | `tok group <g> --json` |
| `Group.wait(poll=60)` | `tok group <g> --wait --poll <poll>s --json` (blocks in the engine until no job but the caller is active) |
| `Group.result(job)` | `tok result <id> --json`; `not_found` → `None` or `NoResult`, decided at implementation |
| `Group.stop()` | `kill`/`cancel` of the group's coordinator, or a group stop command if one is added |
| `tk.current_group()`, `tk.current_job_id()` | `TOKIMEKI_GROUP`, `TOKIMEKI_JOB_ID` |

- `Job.error` (failed jobs) is `{stage, type, message}` from the job's
  `error.json`.
- Submit validation (abi, type, entry format, arg size 64 KiB) is the
  engine's; the package only maps `invalid_argument` to `TokimekiError`.

## Job runtime: `python -m tokimeki.call <entry>`

The only code here that is not a wrapper. The runner starts it as
`uv run --project <project> --no-sync python -m tokimeki.call <entry>` in
`execute.cwd`, with the environment in `tokimeki-engine/docs/protocol.md`.

1. Read `meta.json` from `$TOKIMEKI_JOB_META`; take `execute`. Refuse an
   `execute.abi` other than 2 or an `entry` that differs from argv
   (load failure).
2. Add `cwd` to `sys.path`; import `module`, or load `/abs/file.py` under a
   name other than `__main__`; get `function`.
3. Call `function(arg)` (`arg` absent → `None`).
4. Return value not `None` → JSON to `$TOKIMEKI_JOB_RESULT`; exit 0.
5. Exception in the function → `{"stage": "run", "type", "message",
   "traceback"}` to `$TOKIMEKI_JOB_ERROR`, traceback on stderr, exit 1.
6. Load failure (bad envelope, import error, missing function) →
   `{"stage": "load", ...}` to `$TOKIMEKI_JOB_ERROR`, exit 2.
7. Kill/cancel signals reach the whole process group (runner side).


