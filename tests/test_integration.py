"""End to end against a real tokimeki binary and runner.

Set TOKIMEKI_TEST_BIN to a tokimeki binary to run these. The runner gets a
stand-in `uv` that runs `python -m tokimeki.call <entry>` with this
interpreter, so no uv project is needed; the Docker test covers real uv.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import tokimeki as tk
from tests import helpers

TOK = os.environ.get("TOKIMEKI_TEST_BIN")
ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(not TOK, reason="set TOKIMEKI_TEST_BIN to a tokimeki binary")


@pytest.fixture
def cluster(tmp_path, monkeypatch):
    home = tmp_path / "home"
    shim = tmp_path / "shim"
    shim.mkdir()
    uv = shim / "uv"
    uv.write_text(f'#!/bin/sh\nfor last; do :; done\nexec {sys.executable} -m tokimeki.call "$last"\n')
    uv.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{shim}{os.pathsep}{env['PATH']}"
    env["PYTHONPATH"] = f"{ROOT / 'src'}{os.pathsep}{ROOT}"
    runner = subprocess.Popen(
        [TOK, "--base", str(home), "runner", "--id", "it1", "--compute-threads", "3", "--poll", "200ms", "--manner-period", "0"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    monkeypatch.setenv("TOKIMEKI_BIN", TOK)
    monkeypatch.delenv("TOKIMEKI_GROUP", raising=False)
    monkeypatch.delenv("TOKIMEKI_JOB_ID", raising=False)
    monkeypatch.chdir(ROOT)  # jobs run here, so tests.helpers is importable
    yield str(home)
    runner.terminate()
    runner.wait(timeout=10)


def test_sweep_end_to_end(cluster):
    group = tk.Group("it", home=cluster)
    assert group.jobs() == []

    good = [group.submit(helpers.square, {"x": x}, desc=f"x{x}") for x in range(1, 6)]
    bad = group.submit(helpers.boom, {"x": 9}, desc="boom", retries=1, backoff="1s")
    group.submit(helpers.nothing, {"x": 0}, desc="nothing")

    report = group.wait(poll=0.2)
    assert report.compute.active == 0
    assert report.compute.completed == 6 and report.compute.failed == 2  # boom and its retry

    assert [group.result(s) for s in good] == [{"x": x, "square": x * x} for x in range(1, 6)]

    failed = {j.id: j for j in report.failed}
    assert bad.job_id in failed
    for job in report.failed:
        assert job.desc == "boom" and job.exit_code == 1
        assert job.error == tk.JobError("run", "ValueError", "bad x 9")

    with pytest.raises(tk.TokimekiError) as e:
        group.result(bad)
    assert e.value.code == "not_found"

    by_desc = {j.desc: j for j in group.jobs()}
    assert by_desc["x3"].label == "python-uv tests.helpers:square" and by_desc["x3"].arg == {"x": 3}


def test_load_failure_reaches_the_group(cluster, tmp_path, monkeypatch):
    # A module only this process can import: the job runs in / without it.
    (tmp_path / "only_here.py").write_text("def f(arg):\n    return arg\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    import only_here

    group = tk.Group("it-load", home=cluster)
    group.submit(helpers.square, {"x": 1}, desc="ok")
    sub = group.submit(only_here.f, 1, desc="unimportable", cwd="/")
    report = group.wait(poll=0.2)
    (job,) = report.failed
    assert job.id == sub.job_id and job.exit_code == 2
    assert job.error.stage == "load" and job.error.type == "ModuleNotFoundError"


def test_bad_request_is_rejected(cluster):
    with pytest.raises(tk.TokimekiError) as e:
        tk.Group("it", home=cluster).submit(helpers.square, "x" * (64 << 10))
    assert e.value.code == "invalid_argument" and "65536" in e.value.message


def test_legacy_job_warns_once_per_call(cluster):
    legacy = Path(cluster) / "jobs" / "old00001"
    legacy.mkdir(parents=True)
    legacy.joinpath("meta.json").write_text(
        '{"job_id": "old00001", "command": "echo old", "status": "completed", "name": "it-old",'
        ' "submitted_at": "2026-01-01T00:00:00Z", "exit_code": 0}'
    )
    with pytest.warns(tk.TokimekiWarning, match="deprecated meta.json schema") as rec:
        jobs = tk.Group("it-old", home=cluster).jobs()
    assert [j.label for j in jobs] == ["echo old"]
    assert len([w for w in rec if issubclass(w.category, tk.TokimekiWarning)]) == 1
