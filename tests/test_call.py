import json
import os
import textwrap

import pytest

from tokimeki import call


def job_json(entry, arg=None, cwd=None, type_="python-uv", abi=2):
    execute = {"abi": abi, "type": type_, "entry": entry, "cwd": cwd or os.getcwd()}
    if arg is not None:
        execute["arg"] = arg
    return {"job_id": "j1", "status": "running", "execute": execute}


@pytest.fixture
def job(fake_tok, monkeypatch):
    """Run call.main for a job; returns (exit code, reports sent)."""
    monkeypatch.setenv("TOKIMEKI_JOB_ID", "j1")
    fake_tok.respond("report", stdout={"job_id": "j1", "kind": "result"})

    def run(entry, arg=None, argv_entry=None, **kw):
        fake_tok.respond("job", stdout=job_json(entry, arg, **kw))
        code = call.main([argv_entry or entry])
        reports = [json.loads(c["stdin"]) for c in fake_tok.calls() if c["argv"][0] == "report"]
        return code, reports

    return run


def test_result_is_reported(job, fake_tok):
    code, reports = job("tests.helpers:square", {"x": 4})
    assert code == call.EXIT_OK
    assert reports == [{"result": {"x": 4, "square": 16}}]
    assert fake_tok.calls()[0]["argv"] == ["job", "j1", "--json"]


def test_conda_job_runs(job):
    code, reports = job("tests.helpers:square", {"x": 3}, type_="python-conda")
    assert code == call.EXIT_OK and reports == [{"result": {"x": 3, "square": 9}}]


def test_none_result_reports_nothing(job):
    assert job("tests.helpers:nothing", {"x": 1}) == (call.EXIT_OK, [])


def test_missing_arg_is_none(job):
    code, reports = job("tests.helpers:nothing")
    assert code == call.EXIT_OK and reports == []


def test_exception_is_reported_as_run_error(job, capsys):
    code, reports = job("tests.helpers:boom", {"x": 7})
    assert code == call.EXIT_FUNCTION_FAILED
    error = reports[0]["error"]
    assert (error["stage"], error["type"], error["message"]) == ("run", "ValueError", "bad x 7")
    assert "Traceback" in error["traceback"] and "bad x 7" in capsys.readouterr().err


def test_unserializable_result_is_an_error(job):
    code, reports = job("tests.helpers:unserializable", {"x": 1})
    assert code == call.EXIT_FUNCTION_FAILED
    assert reports[0]["error"]["stage"] == "result" and "JSON-serializable" in reports[0]["error"]["message"]


@pytest.mark.parametrize(
    "entry, argv_entry, kw, message",
    [
        ("no_such_module:f", None, {}, "No module named 'no_such_module'"),
        ("tests.helpers:missing", None, {}, "has no function missing"),
        ("tests.helpers:square", "tests.helpers:boom", {}, "does not match"),
        ("tests.helpers:square", None, {"type_": "bash"}, "runs python-uv and python-conda jobs"),
        ("tests.helpers:square", None, {"abi": 3}, "runs python-uv and python-conda jobs"),
        ("square", None, {}, "must be module:function"),
    ],
)
def test_load_failures(job, entry, argv_entry, kw, message):
    code, reports = job(entry, {"x": 1}, argv_entry=argv_entry, **kw)
    assert code == call.EXIT_LOAD_FAILED
    assert reports[0]["error"]["stage"] == "load" and message in reports[0]["error"]["message"]


def test_usage(capsys):
    assert call.main([]) == call.EXIT_LOAD_FAILED
    assert "usage:" in capsys.readouterr().err


def test_not_in_a_job(fake_tok, monkeypatch):
    monkeypatch.delenv("TOKIMEKI_JOB_ID", raising=False)
    fake_tok.respond("report", stdout={})
    assert call.main(["tests.helpers:square"]) == call.EXIT_LOAD_FAILED


def test_script_entry_does_not_rerun_main_block(job, tmp_path):
    script = tmp_path / "sweep.py"
    marker = tmp_path / "main-ran"
    script.write_text(textwrap.dedent(f"""\
        def run_one(arg):
            return arg * 2

        if __name__ == "__main__":
            open({str(marker)!r}, "w").close()
        """))
    code, reports = job(f"{script}:run_one", 21, cwd=str(tmp_path))
    assert code == call.EXIT_OK and reports == [{"result": 42}]
    assert not marker.exists()


def test_cwd_modules_are_importable(job, tmp_path):
    (tmp_path / "local_tasks.py").write_text("def triple(arg):\n    return arg * 3\n")
    code, reports = job("local_tasks:triple", 5, cwd=str(tmp_path))
    assert code == call.EXIT_OK and reports == [{"result": 15}]


def test_report_failure_fails_the_job(job, fake_tok):
    fake_tok.respond("report", stdout={"error": {"code": "invalid_state", "message": "job j1 is completed, not running"}}, exit=1)
    code, _ = job("tests.helpers:square", {"x": 2})
    assert code == call.EXIT_FUNCTION_FAILED


def test_writes_no_files(job, tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    before = sorted(os.listdir(work))
    job("tests.helpers:square", {"x": 3}, cwd=str(work))
    job("tests.helpers:boom", {"x": 3}, cwd=str(work))
    assert sorted(os.listdir(work)) == before
