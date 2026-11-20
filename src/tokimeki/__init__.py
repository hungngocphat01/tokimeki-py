"""tokimeki: submit Python functions as tokimeki jobs, wait on groups, read
results. A thin wrapper around the ``tokimeki`` CLI (``tok ... --json``); it
writes no files.

    import tokimeki as tk

    group = tk.current_group()                  # inside a coordinator job
    for cfg in configs:
        group.submit(run_experiment, cfg, desc=cfg["run_id"])
    report = group.wait(poll=60)
    results = [group.result(j) for j in report.jobs if j.status == "completed" and j.kind == "compute"]
"""

from ._cli import TokimekiError, TokimekiWarning
from ._group import Group, current_group, current_job_id, get_job_entry_from_func
from ._types import Counts, GroupReport, Job, JobError, Submitted

__version__ = "0.5.0"

__all__ = [
    "Counts",
    "Group",
    "GroupReport",
    "Job",
    "JobError",
    "Submitted",
    "TokimekiError",
    "TokimekiWarning",
    "current_group",
    "current_job_id",
    "get_job_entry_from_func",
]
