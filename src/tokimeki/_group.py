"""Groups: submit Python functions as jobs, read and wait on the group."""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Callable, Iterable, List, Optional, Union

from ._cli import TokimekiError, run
from ._types import GroupReport, Job, Submitted

ENV_GROUP = "TOKIMEKI_GROUP"
ENV_JOB_ID = "TOKIMEKI_JOB_ID"
ENV_EXECUTOR = "TK_EXECUTOR"

EXECUTORS = ("python-uv", "python-conda")

JobLike = Union[str, Job, Submitted]


def get_executor() -> str:
    """Return the execute type that runs jobs in this Python's environment.

    ``$TK_EXECUTOR`` decides when set. Otherwise a conda environment (one
    with ``conda-meta/`` under ``sys.prefix``) gives ``"python-conda"`` and
    anything else ``"python-uv"``.

    Returns
    -------
    str
        ``"python-uv"`` or ``"python-conda"``.

    Raises
    ------
    ValueError
        If ``$TK_EXECUTOR`` is set to anything else.
    """
    override = os.environ.get(ENV_EXECUTOR)
    if override:
        if override not in EXECUTORS:
            raise ValueError(f"{ENV_EXECUTOR}={override!r}; want one of {', '.join(EXECUTORS)}")
        return override
    return "python-conda" if _in_conda_env() else "python-uv"


def _in_conda_env() -> bool:
    return os.path.isdir(os.path.join(sys.prefix, "conda-meta"))


def get_job_entry_from_func(fn: Callable) -> str:
    """Return the job entry that names ``fn`` for the job runtime.

    Parameters
    ----------
    fn : callable
        A top-level function of an importable module, or of the script
        being run.

    Returns
    -------
    str
        ``"module:function"``, or ``"/abs/path/script.py:function"`` for a
        function defined in the script being run (``__main__``).

    Raises
    ------
    TypeError
        If ``fn`` is not a function.
    ValueError
        If ``fn`` is a lambda, a method, a nested function, or was defined
        in an interactive session: a job could not import it.

    Examples
    --------
    >>> from evident.train import run_experiment
    >>> tk.get_job_entry_from_func(run_experiment)
    'evident.train:run_experiment'
    """
    name = getattr(fn, "__qualname__", None)
    module = getattr(fn, "__module__", None)
    if not callable(fn) or not name or not module:
        raise TypeError(f"{fn!r} is not a function")
    if "." in name or "<" in name:
        raise ValueError(f"{name} must be a top-level function of its module (no lambdas, methods or nested functions)")
    if module == "__main__":
        path = getattr(sys.modules.get("__main__"), "__file__", None)
        if not path:
            raise ValueError(f"{name} is defined in an interactive session; define it in a module or script file")
        return f"{os.path.abspath(path)}:{name}"
    return f"{module}:{name}"


def _job_id(job: JobLike) -> str:
    if isinstance(job, Job):
        return job.id
    if isinstance(job, Submitted):
        return job.job_id
    return job


class Group:
    """The jobs carrying one group label.

    A group is only a label: it exists while jobs carrying it exist, until
    ``tok gc`` removes them. Every method is one call to the ``tokimeki``
    CLI.

    Parameters
    ----------
    name : str
        The group label.
    home : str, optional
        The tokimeki state directory. Defaults to ``$TOKIMEKI_HOME`` (or
        the CLI's default).

    Raises
    ------
    ValueError
        If ``name`` is empty.

    See Also
    --------
    current_group : The group of the running job.

    Examples
    --------
    >>> group = tk.Group("c100-redl")
    >>> report = group.report()
    >>> report.compute.completed
    10
    """

    def __init__(self, name: str, *, home: Optional[str] = None):
        if not name:
            raise ValueError("group name required")
        self.name = name
        self.home = home

    def __repr__(self) -> str:
        return f"Group({self.name!r})"

    def submit(
        self,
        fn: Callable,
        arg: Any = None,
        *,
        desc: Optional[str] = None,
        priority: Optional[int] = None,
        cpus: Optional[int] = None,
        mem_mb: Optional[int] = None,
        retries: Optional[int] = None,
        backoff: Optional[str] = None,
        after: Iterable[JobLike] = (),
        project: Optional[str] = None,
        cwd: Optional[str] = None,
        worker: Optional[str] = None,
    ) -> Submitted:
        """Queue ``fn(arg)`` as a compute job in this group.

        The job runs ``fn`` in the same kind of environment as this
        process (see :func:`get_executor`) on whichever runner has a free
        compute slot: in the uv project ``project``, or through
        ``conda run`` in this conda environment. Its return value can be read with
        :meth:`result`.

        Parameters
        ----------
        fn : callable
            A top-level function of an importable module, or of the script
            being run. See :func:`get_job_entry_from_func`.
        arg : object, optional
            The single argument passed to ``fn``. Must be JSON-serializable
            and at most 64 KiB as JSON. ``fn`` receives ``None`` when
            omitted.
        desc : str, optional
            A free-text description, e.g. a run ID. A coordinator uses it to
            find configs that already have a job.
        priority : int, optional
            Higher runs sooner. Default 0.
        cpus : int, optional
            Required CPU count (a scheduling hint).
        mem_mb : int, optional
            Required memory in MB (a scheduling hint).
        retries : int, optional
            How many times to rerun the job if it fails or crashes.
        backoff : str, optional
            Delay between retries as a Go duration, e.g. ``"30s"``.
        after : iterable of str, Job or Submitted, optional
            Jobs that must complete before this one starts.
        project : str, optional
            uv only: the uv project directory (with ``pyproject.toml``) to
            run in. Defaults to the current directory. The project's
            environment must already be synced and must depend on
            ``tokimeki``. A conda job always runs in this process's conda
            environment (``sys.prefix``, or ``$CONDA_PREFIX`` when
            ``$TK_EXECUTOR`` forces conda outside one), which must have
            ``tokimeki`` installed; giving ``project`` is rejected.
        cwd : str, optional
            The job's working directory. Defaults to the current directory.
        worker : str, optional
            Run only on this runner.

        Returns
        -------
        Submitted
            The queued job's ID and queue position.

        Raises
        ------
        TypeError
            If ``arg`` is not JSON-serializable, or ``fn`` is not a function.
        ValueError
            If ``fn`` cannot be imported by a job (see
            :func:`get_job_entry_from_func`), or ``$TK_EXECUTOR`` is
            invalid.
        TokimekiError
            If tokimeki rejects the request (code ``invalid_argument``),
            e.g. ``arg`` is too large, or ``project`` is given for a conda
            job.

        Examples
        --------
        >>> for cfg in expand_sweep(grid):
        ...     group.submit(run_experiment, cfg, desc=cfg["run_id"], retries=1)
        """
        executor = get_executor()
        req = {"abi": 2, "type": executor, "entry": get_job_entry_from_func(fn), "group": self.name}
        if executor == "python-conda" and _in_conda_env():
            req["env"] = sys.prefix
        if arg is not None:
            req["arg"] = arg
        optional = {
            "desc": desc, "priority": priority, "cpus": cpus, "mem_mb": mem_mb, "retries": retries,
            "backoff": backoff, "project": project, "cwd": cwd, "worker": worker,
        }
        req.update({k: v for k, v in optional.items() if v is not None})
        deps = [_job_id(j) for j in after]
        if deps:
            req["after"] = deps
        try:
            body = json.dumps(req)
        except (TypeError, ValueError) as e:
            raise TypeError(f"arg is not JSON-serializable: {e}") from None
        return Submitted.from_json(run(["submit", "--from-json", "-"], stdin=body, home=self.home))

    def report(self) -> GroupReport:
        """Return the group's job counts and jobs.

        Returns
        -------
        GroupReport
            Counts by status, separately for coordinators and compute jobs,
            the failed and stopped jobs, and every job.

        Raises
        ------
        TokimekiError
            Code ``not_found`` if no job carries the label.

        See Also
        --------
        jobs : The jobs only, empty when the group has none.
        """
        return GroupReport.from_json(run(["group", self.name], home=self.home))

    def jobs(self) -> List[Job]:
        """Return every job in the group.

        Returns
        -------
        list of Job
            Active jobs in dispatch order, then the rest by submission. Empty
            when no job carries the label yet.

        Examples
        --------
        Skip configs that already have a job, e.g. in a restarted
        coordinator:

        >>> taken = {job.desc for job in group.jobs() if job.status != "failed"}
        """
        try:
            return self.report().jobs
        except TokimekiError as e:
            if e.code == "not_found":
                return []
            raise

    def wait(self, poll: float = 60) -> GroupReport:
        """Block until the group's jobs are done, then return its report.

        Waits until no job in the group is queued, running or retrying,
        other than the job calling it, so a coordinator can wait on its own
        group. Jobs on a runner that is gone count as stopped, not active.

        Parameters
        ----------
        poll : float, default 60
            Seconds between checks.

        Returns
        -------
        GroupReport
            The report once nothing is active.

        Raises
        ------
        TokimekiError
            Code ``not_found`` if no job carries the label.
        """
        return GroupReport.from_json(run(["group", self.name, "--wait", "--poll", f"{poll}s"], home=self.home))

    def result(self, job: JobLike) -> Any:
        """Return the value the job's function returned.

        Parameters
        ----------
        job : str, Job or Submitted
            The job, or its ID.

        Returns
        -------
        object
            The return value, decoded from JSON.

        Raises
        ------
        TokimekiError
            Code ``not_found`` if the job doesn't exist, hasn't finished,
            failed, or its function returned ``None``.
        """
        return run(["result", _job_id(job)], home=self.home)


def current_job_id() -> Optional[str]:
    """Return the ID of the tokimeki job this code runs in.

    Returns
    -------
    str or None
        ``$TOKIMEKI_JOB_ID``, or ``None`` outside a tokimeki job.
    """
    return os.environ.get(ENV_JOB_ID) or None


def current_group(*, home: Optional[str] = None) -> Group:
    """Return the group of the tokimeki job this code runs in.

    In a coordinator this is its own group; jobs it submits join it.

    Parameters
    ----------
    home : str, optional
        The tokimeki state directory. Defaults to ``$TOKIMEKI_HOME``, which
        the runner sets for every job.

    Returns
    -------
    Group
        The group named by ``$TOKIMEKI_GROUP``.

    Raises
    ------
    TokimekiError
        Code ``invalid_state`` outside a tokimeki job, or in a job without a
        group.

    Examples
    --------
    >>> group = tk.current_group()
    >>> group.name
    'c100-redl'
    """
    name = os.environ.get(ENV_GROUP)
    if not name:
        raise TokimekiError("invalid_state", f"not inside a tokimeki job with a group (${ENV_GROUP} is unset)")
    return Group(name, home=home)
