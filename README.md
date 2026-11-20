# tokimeki (Python)

Submit Python functions as tokimeki jobs, wait on their group, and read their
results. A thin wrapper around the `tokimeki` CLI: every call runs
`tok ... --json`, and the package writes no files.

Requires the `tokimeki` binary (v0.5.0 or later) on `PATH`, or named by
`$TOKIMEKI_BIN`. Inside a job the runner sets `$TOKIMEKI_BIN` for you.

## A sweep coordinator

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
    results = {
        job.desc: group.result(job)
        for job in report.jobs
        if job.kind == "compute" and job.status == "completed"
    }
    for job in report.failed:
        print(f"{job.desc}: {job.error.type if job.error else job.status}", file=sys.stderr)
    return results


if __name__ == "__main__":
    main(sys.argv[1])
```

Each `submit` queues one compute job: whichever runner has a free compute
slot runs `run_experiment(cfg)` in your uv project. What it returns (any
JSON-serializable value) is read back with `group.result(job)`; if it raises,
the job fails and `job.error` says why.

## How a job runs

The runner starts each job as

```
uv run --project <project> --no-sync python -m tokimeki.call <module:function>
```

in the job's working directory (both default to the directory you submitted
from). So:

- `tokimeki` must be a dependency of your uv project, and the project's
  environment must be synced (`uv sync`) before you submit; jobs don't sync.
- The function must be a top-level function of an importable module, or of
  the script you run (it is then loaded without running its
  `if __name__ == "__main__":` block).
- Its argument and return value must be JSON-serializable; the argument is at
  most 64 KiB.

`python -m tokimeki.call` exits 0 when the function returns, 1 when it raises,
and 2 when it can't be loaded.

## API

| | |
|---|---|
| `tk.Group(name, home=None)` | A group label; `home` overrides `$TOKIMEKI_HOME` |
| `Group.submit(fn, arg, *, desc, priority, cpus, mem_mb, retries, backoff, after, project, cwd, worker)` | Queue `fn(arg)`; returns `Submitted(job_id, position)` |
| `Group.report()` | `GroupReport`: counts for coordinators and compute jobs, failed, stopped and all jobs |
| `Group.jobs()` | Every `Job` in the group (empty if none) |
| `Group.wait(poll=60)` | Block until no job but the caller is queued, running or retrying |
| `Group.result(job)` | The job function's return value |
| `tk.current_group()`, `tk.current_job_id()` | The running job's group and ID |
| `tk.get_job_entry_from_func(fn)` | The `module:function` name a job would run |

Errors raise `tk.TokimekiError` with `.code` (`not_found`,
`invalid_argument`, `invalid_state`, ...). Warnings from tokimeki (for
example about job records from older versions) are issued as
`tk.TokimekiWarning`. With the `tokimeki` logger at DEBUG level, the CLI's
debug log is passed to `logging`.

## Development

```bash
uv run --group dev pytest                                   # unit tests
TOKIMEKI_TEST_BIN=/path/to/tok uv run --group dev pytest    # plus end-to-end tests with a real runner
```
