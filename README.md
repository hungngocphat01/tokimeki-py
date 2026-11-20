# tokimeki (Python)

The `tokimeki` package, imported as `tk` by convention:

```python
import tokimeki as tk
```

Submit Python functions as tokimeki jobs from Python, wait on their group and
read their return values. The package is a thin layer over the `tokimeki`
CLI: every call runs one `tok ... --json` command, and the package writes no
files.

How jobs, runners, groups and coordinators work is described once, in the CLI
docs:

- [How Tokimeki works](https://github.com/hungngocphat01/tokimeki-cli/blob/main/docs/HOW-IT-WORKS.md): the job life
  cycle, runners and slots, groups and coordinators, results, and the files
  behind them, including how Python jobs flow.
- [Usage](https://github.com/hungngocphat01/tokimeki-cli/blob/main/docs/USAGE.md): every command, the `--from-json`
  request format, the JSON output and the job environment.

## Install

In your uv project (e.g. evident):

```bash
uv add "tokimeki @ git+ssh://git@github.com/hungngocphat01/tokimeki-py@v0.5.0"
uv sync
```

Use the same version as the `tokimeki` binary on your cluster.

Requirements: the `tokimeki` binary (v0.5.0+) on `PATH` or named by
`$TOKIMEKI_BIN` (the runner sets it inside jobs), and Python 3.9+.

## Example: a sweep coordinator

```python
# scripts/sweep.py, submitted once:
#   tok submit -C -g c100-redl -c "cd ~/evident && uv run python scripts/sweep.py grid.yaml"
import sys
import tokimeki as tk

from evident.sweep import expand_sweep, load_grid
from evident.train import run_experiment


def main(grid_path):
    configs = expand_sweep(load_grid(grid_path))
    group = tk.current_group()

    # A restarted coordinator skips configs that already have a job.
    taken = {job.desc for job in group.jobs() if job.kind == "compute" and job.status != "failed"}
    for cfg in configs:
        if cfg["run_id"] not in taken:
            group.submit(run_experiment, cfg, desc=cfg["run_id"], retries=1)

    report = group.wait(poll=60)
    return {
        job.desc: group.result(job)
        for job in report.jobs
        if job.kind == "compute" and job.status == "completed"
    }


if __name__ == "__main__":
    main(sys.argv[1])
```

## API

Each function maps to one CLI command; the docstrings (`help(tk.Group)`)
give the parameters.

| Python | CLI |
|---|---|
| `tk.Group(name, home=None)` | a group label (`-g`); `home` is `--base` |
| `Group.submit(fn, arg, ...)` | `tok submit --from-json -` with type `python-uv` |
| `Group.report()`, `Group.jobs()` | `tok group NAME --json` |
| `Group.wait(poll=60)` | `tok group NAME --wait --poll ...` |
| `Group.result(job)` | `tok result ID` |
| `tk.current_group()`, `tk.current_job_id()` | `$TOKIMEKI_GROUP`, `$TOKIMEKI_JOB_ID` |
| `tk.TokimekiError` (`.code`) | the CLI's `{"error": {"code", "message"}}` |
| `tk.TokimekiWarning` | the CLI's warnings (`{"notice": ...}` on stderr) |

With the `tokimeki` logger at DEBUG level, calls pass `--verbose` and the
CLI's debug lines go to `logging`.

## The job runtime: `python -m tokimeki.call`

The runner starts every Python job as

```
uv run --project <project> --no-sync python -m tokimeki.call <entry>
```

in the job's working directory, with the uv on the runner's `PATH`.
`tokimeki.call` then:

1. reads the job with `tok job $TOKIMEKI_JOB_ID --json` and checks it is a
   `python-uv` job (execute ABI 2) for this entry;
2. imports the function: `module:function` from the project (or from the
   working directory), or `/abs/path/script.py:function` from a script file;
3. calls `function(arg)` with the job's argument (`None` if none was given);
4. reports the outcome with `tok report --from-json -`:
   - the return value as the job's result, unless it is `None`;
   - an exception as the job's error: stage, exception type, message and
     traceback (the traceback also goes to the job's stderr log).

| Exit code | Meaning | Reported error stage |
|---|---|---|
| 0 | the function returned | |
| 1 | the function raised, or its return value isn't JSON-serializable or couldn't be reported | `run` / `result` |
| 2 | the function couldn't be loaded (bad entry, import error, not a python-uv job) | `load` |

What this means for your code:

- **Your project must be ready before you submit.** `tokimeki` must be one
  of its dependencies, and its environment must be synced (`uv sync`). Jobs
  run with `--no-sync`, so many jobs starting at once don't fight over one
  `.venv`.
- **The function must be importable on the runner's node:** a top-level
  function of your installed package, of a module in the job's working
  directory, or of the script you submitted from. Lambdas, methods and
  nested functions are rejected at submit.
- **Scripts are imported, not run.** For a function defined in a script, the
  script is loaded under another module name, so its
  `if __name__ == "__main__":` block doesn't run again. Its top-level code
  does run, as on any import, so keep work inside functions or that block.
- **Arguments and results are JSON.** `arg` must be JSON-serializable and at
  most 64 KiB; return something JSON-serializable, or `None` for no result.
  Large outputs (checkpoints, CSVs) belong in files your code writes itself.
- **Killing works on the whole job.** `tok kill`, or a kill cascading from
  the coordinator, signals uv, Python and anything they started.

## Development

```bash
uv run --group dev pytest                                   # unit tests (a stand-in tok)
TOKIMEKI_TEST_BIN=/path/to/tok uv run --group dev pytest    # plus end-to-end tests with a real runner
```

Design notes: [docs/design.md](docs/design.md).
