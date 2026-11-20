# Tokimeki for Python — Usage Guide

What you can do with the `tokimeki` Python package, and how. For why it
exists and a full walkthrough of a sweep, see the [README](../README.md); for
the CLI and how Tokimeki works underneath, see the
[CLI usage guide](https://github.com/hungngocphat01/tokimeki-cli/blob/main/docs/USAGE.md).
Every function and method also has a docstring (`help(tk.Group.submit)`).

## Contents

- [Setup](#setup)
- [API at a glance](#api-at-a-glance)
- [Writing a job function](#writing-a-job-function)
- [Submitting jobs](#submitting-jobs)
- [A sweep from a coordinator job](#a-sweep-from-a-coordinator-job)
- [A coordinator on the login node](#a-coordinator-on-the-login-node)
- [Waiting and collecting results](#waiting-and-collecting-results)
- [When jobs fail or a runner disappears](#when-jobs-fail-or-a-runner-disappears)
- [Restarting a coordinator without duplicates](#restarting-a-coordinator-without-duplicates)
- [Errors and warnings](#errors-and-warnings)

---

## Setup

```bash
cd /shared/projects/model_trainer
uv add "tokimeki @ git+ssh://git@github.com/hungngocphat01/tokimeki-py@v0.5.0"
uv sync
```

- The `tokimeki` binary must be on `PATH` (or set `TOKIMEKI_BIN`), at the
  same version as the package. Inside a job, the runner's own binary is used.
- The project must be on the shared filesystem, and its environment synced
  before you submit: runners start jobs with `--no-sync`, so they never
  install anything.

```python
import tokimeki as tk
```

---

## API at a glance

| Python | What it does |
|---|---|
| `tk.current_group()` | The group of the job this code runs in (inside a coordinator) |
| `tk.Group(name)` | A group by name, from anywhere |
| `group.submit(fn, arg, ...)` | Queue `fn(arg)` as a job in the group |
| `group.wait(poll=60)` | Block until nothing in the group is queued, running or retrying |
| `group.result(job)` | The value the job's function returned |
| `group.report()` | Counts by status, failed and stopped jobs, every job |
| `group.jobs()` | Every job in the group (empty if none) |
| `tk.current_job_id()` | The ID of the job this code runs in, or `None` |
| `tk.TokimekiError` | Raised when the CLI reports an error; has a `code` |

Every call runs one `tokimeki` command and parses its JSON output; the
package never reads Tokimeki's files itself.

---

## Writing a job function

A job runs one function with one argument, on whichever runner takes it:

```python
# model_trainer/jobs.py
from model_trainer.training import train_model


def train_trial(config):
    score = train_model(config["backbone"], config["lr"])
    return {"lr": config["lr"], "score": score}
```

- It must be a **top-level function** that the runner can import: from a
  module in your project, or from the script you run (then it is loaded from
  that file's absolute path, and the script's `if __name__ == "__main__":`
  block does not run again). Lambdas, methods and nested functions are
  rejected at submit.
- The **argument** must be JSON-serializable and at most 64 KiB. The
  **return value** must be JSON-serializable too; returning `None` means there
  is no result to read.
- Write large outputs, such as checkpoints, to files in your project and
  return their paths instead.
- If the function raises, the job fails and the exception's type and message
  are recorded on the job (see [below](#when-jobs-fail-or-a-runner-disappears)).

---

## Submitting jobs

```python
group = tk.current_group()            # inside a coordinator job
job = group.submit(train_trial, {"backbone": "alexnet", "lr": 0.01})
job.job_id                            # its ID, also usable with the CLI (tok logs <id>)
```

`submit` takes the same options as `tok submit`:

| Option | Effect |
|---|---|
| `desc="lr=0.01"` | A free-text note; useful to recognise a trial later |
| `retries=2, backoff="30s"` | Rerun on failure or crash, as a new job |
| `priority=10` | Higher runs sooner |
| `after=[job1, job2]` | Start only after these jobs completed |
| `cpus=8, mem_mb=16384` | Resource hints, checked against runners' capacity |
| `worker="gpu01"` | Run only on that runner |
| `project=..., cwd=...` | The uv project and working directory (default: the current directory) |

Chaining two steps, e.g. evaluating after training:

```python
trained = group.submit(train_trial, cfg)
group.submit(evaluate, cfg, after=[trained])
```

---

## A sweep from a coordinator job

The usual pattern, covered step by step in the
[README](../README.md#running-a-hyperparameter-sweep): one coordinator per
sweep, submitted as a job, one group per sweep.

```python
# scripts/sweep_alexnet.py
import tokimeki as tk
from model_trainer.jobs import train_trial

group = tk.current_group()
jobs = [group.submit(train_trial, {"backbone": "alexnet", "lr": lr}, desc=f"lr={lr}")
        for lr in (0.01, 0.001, 0.0001)]
group.wait()
results = [group.result(job) for job in jobs]
```

```bash
# sweep_alexnet.sh
#!/bin/bash
set -e
cd /shared/projects/model_trainer
uv run --no-sync python scripts/sweep_alexnet.py
```

```bash
tok submit -C -g alexnet-lr-01 sweep_alexnet.sh
```

The CLI submits scripts, so the coordinator goes in through a short shell
wrapper; the trials it submits are Python jobs. Each sweep gets its own group
name, and a new name each time it runs.

---

## A coordinator on the login node

A coordinator only submits jobs and waits, so it can also run directly on the
login node. Open the group by name instead of `tk.current_group()`:

```python
group = tk.Group("alexnet-lr-01")
```

and run the script from your project directory, so the trials use that
project:

```bash
cd /shared/projects/model_trainer
uv run python scripts/sweep_alexnet.py
```

Keep it running until the trials finish, e.g. inside `tmux`. You give up what
a coordinator job gets: retries, and `tok kill` / `tok cancel` stopping the
whole group.

---

## Waiting and collecting results

```python
report = group.wait(poll=60)          # checks every 60 s, returns a GroupReport
report.compute.completed, report.compute.failed
result = group.result(job)            # job as returned by submit, a Job, or an ID
```

- `wait()` ignores the job calling it, so a coordinator can wait on its own
  group.
- `result()` raises `TokimekiError` (code `not_found`) if the job hasn't
  finished, failed, or returned `None`.
- `report()` gives the same report without waiting: `coordinators` and
  `compute` counts (`active`, `queued`, `running`, `completed`, `failed`,
  `stopped`, ...), and the lists `failed`, `stopped` and `jobs`. Each `Job` has
  `id`, `status`, `desc`, `arg` (what it was submitted with), `worker`,
  `exit_code` and `error`.

Collecting only what succeeded:

```python
done = [j for j in group.report().jobs if j.kind == "compute" and j.status == "completed"]
results = {j.desc: group.result(j) for j in done}
```

---

## When jobs fail or a runner disappears

A function that raised leaves a failed job with the reason attached:

```python
for job in group.report().failed:
    print(job.desc, job.error.type, job.error.message)   # e.g. "lr=0.01 ValueError loss is NaN"
```

`job.error.stage` says where it failed: `load` (the function couldn't be
imported), `run` (it raised) or `result` (its return value couldn't be
recorded). `tok logs <id>` shows the full traceback.

A job that was running on a runner that disappeared is **stopped**: it no
longer counts as active, so `wait()` can return while it is in that state.
List them with `group.report().stopped`. They are retried (if submitted with
`retries`) when a runner with the same ID starts again. Since `result()`
raises for them, a coordinator that reads every result never writes a
summary that is silently incomplete.

---

## Restarting a coordinator without duplicates

Tokimeki does not deduplicate. A coordinator that is retried, or that you run
again, should skip trials that already have a job, using `desc` to recognise
them:

```python
group = tk.current_group()
taken = {job.desc for job in group.jobs() if job.status not in ("failed", "crashed", "killed")}
for lr in (0.01, 0.001, 0.0001):
    if f"lr={lr}" not in taken:
        group.submit(train_trial, {"backbone": "alexnet", "lr": lr}, desc=f"lr={lr}")
group.wait()
```

---

## Errors and warnings

- `tk.TokimekiError` carries the CLI's error `code`: `not_found`,
  `invalid_state` (e.g. `tk.current_group()` outside a job), `invalid_argument`
  (e.g. an argument over 64 KiB), `timeout`, `runner_rejected`,
  `runner_not_running`, `internal`. Branch on `e.code`.
- Submitting a function that can't be imported by a job raises `ValueError`;
  an argument that isn't JSON-serializable raises `TypeError`. Both happen
  before anything is queued.
- Warnings from the CLI, e.g. about jobs from an older version, become
  `tk.TokimekiWarning` warnings. Set the `tokimeki` logger to `DEBUG` to see
  the CLI's debug log as well.
