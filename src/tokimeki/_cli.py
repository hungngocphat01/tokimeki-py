"""Running the tokimeki CLI: every call is one ``tok ... --json`` process.

The package never touches TOKIMEKI_HOME itself; the engine (behind the CLI)
does all reading, writing and validation.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import warnings
from typing import Any, Optional, Sequence

logger = logging.getLogger("tokimeki")

ENV_BIN = "TOKIMEKI_BIN"


class TokimekiError(Exception):
    """A tokimeki call that failed.

    Parameters
    ----------
    code : str
        The engine's error code: ``not_found``, ``invalid_state``,
        ``invalid_argument``, ``timeout``, ``runner_rejected``,
        ``runner_not_running`` or ``internal``. Branch on this, not on the
        message.
    message : str
        What went wrong, for people.

    Attributes
    ----------
    code : str
    message : str
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return f"{self.message} ({self.code})"


class TokimekiWarning(UserWarning):
    """A warning from tokimeki, e.g. about job records from an older version.

    Parameters
    ----------
    message : str
        The warning text.
    code : str, optional
        The engine's notice code, e.g. ``"legacy_schema"``.

    Attributes
    ----------
    code : str
    """

    def __init__(self, message: str, code: str = ""):
        super().__init__(message)
        self.code = code


def binary() -> str:
    """The tokimeki binary: $TOKIMEKI_BIN (set inside jobs), else tokimeki
    or tok on PATH."""
    path = os.environ.get(ENV_BIN)
    if path:
        return path
    for name in ("tokimeki", "tok"):
        found = shutil.which(name)
        if found:
            return found
    raise TokimekiError("not_found", "tokimeki binary not found: set TOKIMEKI_BIN or put tokimeki on PATH")


def run(args: Sequence[str], *, stdin: Optional[str] = None, home: Optional[str] = None) -> Any:
    """Run ``tok [--base home] args... --json`` and return its parsed JSON
    output. Engine notices on stderr become TokimekiWarning warnings and
    debug log records; an error envelope becomes TokimekiError."""
    cmd = [binary()]
    if logger.isEnabledFor(logging.DEBUG):
        cmd.append("--verbose")
    if home:
        cmd += ["--base", home]
    cmd += list(args) + ["--json"]
    proc = subprocess.run(cmd, input=stdin, capture_output=True, text=True)
    other = _relay_notices(proc.stderr)
    out = proc.stdout.strip()
    data = None
    if out:
        try:
            data = json.loads(out)
        except ValueError:
            raise TokimekiError("internal", f"{' '.join(cmd)}: unexpected output: {out[:200]}") from None
    if proc.returncode != 0:
        if isinstance(data, dict) and isinstance(data.get("error"), dict):
            err = data["error"]
            raise TokimekiError(err.get("code", "internal"), err.get("message", ""))
        detail = "; ".join(other) or f"exit status {proc.returncode}"
        raise TokimekiError("internal", f"{' '.join(cmd)}: {detail}")
    return data


def _relay_notices(stderr: str) -> list:
    """Turn {"notice": ...} lines into warnings / debug logs; return the
    other lines."""
    other = []
    for line in stderr.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            notice = json.loads(line)["notice"]
        except (ValueError, KeyError, TypeError):
            other.append(line)
            continue
        message = notice.get("message", "")
        if notice.get("level") == "warning":
            warnings.warn(TokimekiWarning(message, notice.get("code", "")), stacklevel=4)
        else:
            logger.debug("%s", message)
    return other
