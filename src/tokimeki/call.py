"""Job runtime: ``python -m tokimeki.call <entry>``.

The runner starts every python-uv job as::

    uv run --project <project> --no-sync python -m tokimeki.call <entry>

in the job's working directory. This module then:

1. reads the job through the CLI (``tok job <id>``),
2. imports the job's function,
3. calls it with the job's argument,
4. reports the return value, or the exception, through the CLI
   (``tok report``).

It writes no files itself.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sys
import traceback
from types import ModuleType
from typing import Any, Callable, Optional

from ._cli import TokimekiError, run

USAGE = "usage: python -m tokimeki.call <module:function | /abs/file.py:function>"

# Exit codes: the job's own status in tokimeki.
EXIT_OK = 0
EXIT_FUNCTION_FAILED = 1  # the function raised, or its result could not be reported
EXIT_LOAD_FAILED = 2  # the function could not be found or imported

# Module name for a function loaded from a script file. It is not
# "__main__", so the script's `if __name__ == "__main__":` block does not
# run again inside the job.
SCRIPT_MODULE_NAME = "__tokimeki_entry__"


class LoadError(Exception):
    """The job's function could not be found."""


def main(argv: Optional[list] = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(USAGE, file=sys.stderr)
        return EXIT_LOAD_FAILED
    entry = args[0]

    try:
        execute = _read_job_execute(entry)
        func = _load_function(entry, execute.get("cwd"))
    except Exception as error:
        _report_error("load", error)
        return EXIT_LOAD_FAILED

    try:
        result = func(execute.get("arg"))
    except Exception as error:
        _report_error("run", error)
        return EXIT_FUNCTION_FAILED

    return _report_result(result)


def _read_job_execute(entry: str) -> dict:
    """Return the ``execute`` part of this job's record, checking that it is
    a python-uv job for ``entry``."""
    job_id = os.environ.get("TOKIMEKI_JOB_ID")
    if not job_id:
        raise LoadError("TOKIMEKI_JOB_ID is not set; tokimeki.call only runs inside a tokimeki job")

    job = run(["job", job_id])
    execute = job.get("execute") or {}

    if execute.get("type") != "python-uv" or execute.get("abi") != 2:
        raise LoadError(
            f"job {job_id} is a {execute.get('type')!r} job with abi {execute.get('abi')}; "
            "this runtime runs python-uv jobs with abi 2"
        )
    if execute.get("entry") != entry:
        raise LoadError(f"entry {entry!r} does not match job {job_id}'s entry {execute.get('entry')!r}")
    return execute


def _load_function(entry: str, cwd: Optional[str]) -> Callable:
    """Import the function named by ``entry``: ``module:function`` or
    ``/abs/file.py:function``."""
    module_name, _, function_name = entry.rpartition(":")
    if not module_name or not function_name:
        raise LoadError(f"entry {entry!r} must be module:function or /abs/file.py:function")

    # Modules next to the job's working directory are importable, as when
    # running `python script.py` from there.
    if cwd and cwd not in sys.path:
        sys.path.insert(0, cwd)

    if module_name.startswith("/"):
        module = _load_script(module_name)
    else:
        module = importlib.import_module(module_name)

    func = getattr(module, function_name, None)
    if not callable(func):
        raise LoadError(f"{module_name} has no function {function_name}")
    return func


def _load_script(path: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(SCRIPT_MODULE_NAME, path)
    if spec is None or spec.loader is None:
        raise LoadError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[SCRIPT_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


def _report_result(result: Any) -> int:
    """Report the function's return value; a function returning None has no
    result to report."""
    if result is None:
        return EXIT_OK

    try:
        report = json.dumps({"result": result})
    except (TypeError, ValueError) as error:
        _report_error("result", TypeError(f"the return value is not JSON-serializable: {error}"))
        return EXIT_FUNCTION_FAILED

    if not _send_report(report):
        return EXIT_FUNCTION_FAILED
    return EXIT_OK


def _report_error(stage: str, error: BaseException) -> None:
    """Print the traceback to the job's stderr and report the error, so
    ``tok group`` and ``Job.error`` show why the job failed."""
    trace = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    print(trace, end="", file=sys.stderr)

    report = {
        "error": {
            "stage": stage,
            "type": type(error).__name__,
            "message": str(error) or type(error).__name__,
            "traceback": trace,
        }
    }
    _send_report(json.dumps(report))


def _send_report(report: str) -> bool:
    try:
        run(["report", "--from-json", "-"], stdin=report)
    except TokimekiError as error:
        print(f"tokimeki.call: could not report to tokimeki: {error}", file=sys.stderr)
        return False
    return True


if __name__ == "__main__":
    sys.exit(main())
