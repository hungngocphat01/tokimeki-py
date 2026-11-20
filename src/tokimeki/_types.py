"""Results of CLI calls, mirroring the ``--json`` schema (tokimeki-cli
docs/USAGE.md, "Scripting with --json"). Each keeps the full JSON in ``raw``."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class JobError:
    """Why a job failed, as its runtime reported it.

    Attributes
    ----------
    stage : str
        ``"load"`` if the job's function could not be imported, ``"run"``
        if it raised, ``"result"`` if its return value could not be
        reported.
    type : str
        The exception class name, e.g. ``"ValueError"``.
    message : str
        The exception message.
    """

    stage: str = ""
    type: str = ""
    message: str = ""

    @classmethod
    def from_json(cls, d: Optional[dict]) -> Optional["JobError"]:
        if not d:
            return None
        return cls(stage=d.get("stage", ""), type=d.get("type", ""), message=d.get("message", ""))


@dataclass(frozen=True)
class Job:
    """One job, as ``tok ps --json`` reports it.

    Attributes
    ----------
    id : str
        The job ID.
    status : str
        As stored: ``queued``, ``running``, ``completed``, ``failed``,
        ``killed`` or ``crashed``.
    effective_status : str
        ``status``, or ``"stopped"`` when it is running on a runner that is
        gone.
    kind : str
        ``"compute"`` or ``"coordinator"``.
    group : str
        The group label.
    desc : str
        The free-text description given at submit.
    worker : str
        The runner it ran (or runs) on.
    exit_code : int or None
        The exit code, ``None`` until it finishes.
    attempts : int
        Attempts so far, 1 for the first run.
    retries : int
        The retries it was submitted with.
    parent : str
        The coordinator that submitted it, if any.
    label : str
        What it runs, for display, e.g. ``"python-uv evident.train:run"``.
    error : JobError or None
        Why it failed, for a failed job whose runtime reported it.
    raw : dict
        The full JSON object from the CLI.
    """

    id: str
    status: str
    effective_status: str
    kind: str
    group: str
    desc: str
    worker: str
    exit_code: Optional[int]
    attempts: int
    retries: int
    parent: str
    label: str
    error: Optional[JobError]
    raw: Dict[str, Any] = field(repr=False, compare=False, default_factory=dict)

    @classmethod
    def from_json(cls, d: dict) -> "Job":
        return cls(
            id=d.get("job_id", ""),
            status=d.get("status", ""),
            effective_status=d.get("effective_status", d.get("status", "")),
            kind=d.get("kind", "compute"),
            group=d.get("name", ""),
            desc=d.get("desc", ""),
            worker=d.get("worker_id", ""),
            exit_code=d.get("exit_code"),
            attempts=d.get("attempts", 0),
            retries=d.get("retries", 0),
            parent=d.get("parent", ""),
            label=(d.get("execute") or {}).get("label", ""),
            error=JobError.from_json(d.get("error")),
            raw=d,
        )

    @property
    def arg(self) -> Any:
        """object: The argument the job was submitted with, or ``None``."""
        return (self.raw.get("execute") or {}).get("arg")


@dataclass(frozen=True)
class Counts:
    """Number of jobs of one kind in a group, by effective status.

    Attributes
    ----------
    total : int
        All jobs of this kind.
    active : int
        ``queued + running + retrying``.
    retrying : int
        Failed or crashed jobs whose retry is due but not visible yet.
    queued, running, completed, failed, killed, crashed : int
        Jobs in that status.
    stopped : int
        Jobs running on a runner that is gone; not active.
    """

    total: int = 0
    active: int = 0
    retrying: int = 0
    queued: int = 0
    running: int = 0
    stopped: int = 0
    completed: int = 0
    failed: int = 0
    killed: int = 0
    crashed: int = 0

    @classmethod
    def from_json(cls, d: Optional[dict]) -> "Counts":
        d = d or {}
        return cls(**{k: d.get(k, 0) for k in cls.__dataclass_fields__})


@dataclass(frozen=True)
class GroupReport:
    """A group's state, as ``tok group --json`` reports it.

    Attributes
    ----------
    group : str
        The group label.
    coordinators : Counts
        Coordinator jobs by status.
    compute : Counts
        Compute jobs by status.
    failed : list of Job
        Jobs that failed, crashed or were killed, in submission order.
    stopped : list of Job
        Jobs running on a runner that is gone, in submission order.
    jobs : list of Job
        Every job: active ones in dispatch order, then the rest by
        submission.
    raw : dict
        The full JSON object from the CLI.
    """

    group: str
    coordinators: Counts
    compute: Counts
    failed: List[Job]
    stopped: List[Job]
    jobs: List[Job]
    raw: Dict[str, Any] = field(repr=False, compare=False, default_factory=dict)

    @classmethod
    def from_json(cls, d: dict) -> "GroupReport":
        return cls(
            group=d.get("group", ""),
            coordinators=Counts.from_json(d.get("coordinators")),
            compute=Counts.from_json(d.get("compute")),
            failed=[Job.from_json(j) for j in d.get("failed") or []],
            stopped=[Job.from_json(j) for j in d.get("stopped") or []],
            jobs=[Job.from_json(j) for j in d.get("jobs") or []],
            raw=d,
        )


@dataclass(frozen=True)
class Submitted:
    """A job that was just queued.

    Attributes
    ----------
    job_id : str
        The new job's ID.
    position : int
        Its position in the queue at submit time.
    """

    job_id: str
    position: int

    @classmethod
    def from_json(cls, d: dict) -> "Submitted":
        return cls(job_id=d.get("job_id", ""), position=d.get("position", 0))
