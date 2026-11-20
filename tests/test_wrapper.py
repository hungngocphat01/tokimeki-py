import json
import logging
import os
import sys

import pytest

import tokimeki as tk
from tokimeki import _cli
from tests import helpers

GROUP_JSON = {
    "group": "g",
    "coordinators": {"total": 1, "active": 1, "running": 1},
    "compute": {"total": 2, "active": 0, "completed": 1, "failed": 1},
    "failed": [{"job_id": "f1", "status": "failed", "effective_status": "failed", "kind": "compute", "name": "g",
                "exit_code": 1, "execute": {"label": "python-uv m:f", "arg": {"x": 2}},
                "error": {"stage": "run", "type": "ValueError", "message": "bad"}}],
    "stopped": [],
    "jobs": [{"job_id": "c1", "status": "running", "effective_status": "running", "kind": "coordinator", "name": "g"},
             {"job_id": "d1", "status": "completed", "effective_status": "completed", "kind": "compute", "name": "g", "desc": "cfg1"}],
}


def test_run_appends_json_and_parses(fake_tok):
    fake_tok.respond("ps", stdout=[{"job_id": "a"}])
    assert _cli.run(["ps", "-a"]) == [{"job_id": "a"}]
    assert fake_tok.calls()[0]["argv"] == ["ps", "-a", "--json"]


def test_home_passed_as_base(fake_tok):
    fake_tok.respond("group", stdout=GROUP_JSON)
    tk.Group("g", home="/shared/h").report()
    assert fake_tok.calls()[0]["argv"] == ["--base", "/shared/h", "group", "g", "--json"]


def test_error_envelope_raises(fake_tok):
    fake_tok.respond("group", stdout={"error": {"code": "not_found", "message": 'group "g" has no jobs'}}, exit=1)
    with pytest.raises(tk.TokimekiError) as e:
        tk.Group("g").report()
    assert e.value.code == "not_found" and e.value.message == 'group "g" has no jobs'


def test_failure_without_envelope_is_internal(fake_tok):
    fake_tok.respond("ps", stderr="panic: boom\n", exit=2)
    with pytest.raises(tk.TokimekiError) as e:
        _cli.run(["ps"])
    assert e.value.code == "internal" and "panic: boom" in e.value.message


def test_notices_become_warnings_and_debug_logs(fake_tok, caplog):
    notices = "\n".join(json.dumps({"notice": n}) for n in [
        {"level": "warning", "code": "legacy_schema", "message": "3 jobs use a deprecated meta.json schema (1)", "count": 3},
        {"level": "debug", "message": "dequeue a1"},
    ])
    fake_tok.respond("ps", stdout=[], stderr=notices + "\n")
    caplog.set_level(logging.DEBUG, logger="tokimeki")
    with pytest.warns(tk.TokimekiWarning, match="3 jobs use a deprecated") as rec:
        _cli.run(["ps"])
    assert rec[0].message.code == "legacy_schema"
    assert "dequeue a1" in caplog.text


def test_verbose_only_when_debug_logging(fake_tok, caplog):
    fake_tok.respond("ps", stdout=[])
    _cli.run(["ps"])
    caplog.set_level(logging.DEBUG, logger="tokimeki")
    _cli.run(["ps"])
    calls = fake_tok.calls()
    assert "--verbose" not in calls[0]["argv"] and calls[1]["argv"][0] == "--verbose"


def test_binary_lookup(tmp_path, monkeypatch):
    monkeypatch.delenv("TOKIMEKI_BIN", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(tk.TokimekiError) as e:
        _cli.binary()
    assert e.value.code == "not_found"
    tok = tmp_path / "tok"
    tok.write_text("#!/bin/sh\n")
    tok.chmod(0o755)
    assert _cli.binary() == str(tok)
    monkeypatch.setenv("TOKIMEKI_BIN", "/opt/tok")
    assert _cli.binary() == "/opt/tok"


def test_get_job_entry_from_func():
    assert tk.get_job_entry_from_func(helpers.square) == "tests.helpers:square"
    with pytest.raises(ValueError):
        tk.get_job_entry_from_func(lambda a: a)

    def nested(a):
        return a

    with pytest.raises(ValueError):
        tk.get_job_entry_from_func(nested)
    with pytest.raises(TypeError):
        tk.get_job_entry_from_func(3)


def test_get_job_entry_from_func_main_script(monkeypatch, tmp_path):
    script = tmp_path / "sweep.py"
    script.write_text("")
    fake_main = type(sys)("__main__")
    fake_main.__file__ = str(script)
    monkeypatch.setitem(sys.modules, "__main__", fake_main)

    def run_one(arg):
        return arg

    run_one.__module__ = "__main__"
    run_one.__qualname__ = "run_one"
    assert tk.get_job_entry_from_func(run_one) == f"{script}:run_one"


def test_submit_request(fake_tok):
    fake_tok.respond("submit", stdout={"job_id": "j9", "position": 4})
    sub = tk.Group("g").submit(helpers.square, {"x": 3}, desc="cfg3", retries=1, priority=2,
                               after=[tk.Submitted("a1", 1), "a2"], project="/p", cwd="/w")
    assert sub == tk.Submitted("j9", 4)
    call = fake_tok.calls()[0]
    assert call["argv"] == ["submit", "--from-json", "-", "--json"]
    assert json.loads(call["stdin"]) == {
        "abi": 2, "type": "python-uv", "entry": "tests.helpers:square", "group": "g", "arg": {"x": 3},
        "desc": "cfg3", "retries": 1, "priority": 2, "after": ["a1", "a2"], "project": "/p", "cwd": "/w",
    }


def test_submit_rejects_unserializable_arg(fake_tok):
    with pytest.raises(TypeError, match="JSON-serializable"):
        tk.Group("g").submit(helpers.square, {"x": {1, 2}})
    assert fake_tok.calls() == []


def test_report_and_jobs(fake_tok):
    fake_tok.respond("group", stdout=GROUP_JSON)
    rep = tk.Group("g").report()
    assert rep.compute.completed == 1 and rep.coordinators.running == 1
    assert rep.failed[0].error == tk.JobError("run", "ValueError", "bad") and rep.failed[0].arg == {"x": 2}
    assert [j.desc for j in tk.Group("g").jobs()] == ["", "cfg1"]
    fake_tok.respond("group", stdout={"error": {"code": "not_found", "message": "no jobs"}}, exit=1)
    assert tk.Group("g").jobs() == []


def test_wait_and_result(fake_tok):
    fake_tok.respond("group", stdout=GROUP_JSON)
    fake_tok.respond("result", stdout={"acc": 0.9})
    g = tk.Group("g")
    assert g.wait(poll=2.5).group == "g"
    assert g.result("d1") == {"acc": 0.9}
    argvs = [c["argv"] for c in fake_tok.calls()]
    assert argvs == [["group", "g", "--wait", "--poll", "2.5s", "--json"], ["result", "d1", "--json"]]


def test_current_group(monkeypatch):
    monkeypatch.delenv("TOKIMEKI_GROUP", raising=False)
    monkeypatch.delenv("TOKIMEKI_JOB_ID", raising=False)
    with pytest.raises(tk.TokimekiError):
        tk.current_group()
    assert tk.current_job_id() is None
    monkeypatch.setenv("TOKIMEKI_GROUP", "sweep")
    monkeypatch.setenv("TOKIMEKI_JOB_ID", "c1")
    assert tk.current_group().name == "sweep" and tk.current_job_id() == "c1"
