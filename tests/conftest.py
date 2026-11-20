import json
import os
import stat
import sys
import textwrap

import pytest

FAKE_TOK = textwrap.dedent(
    """\
    #!{python}
    # Stand-in tok: records argv and stdin, answers from $FAKE_RESPONSES
    # keyed by the first non-flag argument (the subcommand).
    import json, os, sys
    args = sys.argv[1:]
    stdin = sys.stdin.read()
    with open(os.environ["FAKE_LOG"], "a") as f:
        f.write(json.dumps({{"argv": args, "stdin": stdin}}) + "\\n")
    words = [a for a in args if not a.startswith("-")]
    if "--base" in args:
        words.remove(args[args.index("--base") + 1])
    responses = json.loads(os.environ.get("FAKE_RESPONSES", "{{}}"))
    r = responses.get(words[0] if words else "", {{"stdout": "{{}}"}})
    sys.stdout.write(r.get("stdout", ""))
    sys.stderr.write(r.get("stderr", ""))
    sys.exit(r.get("exit", 0))
    """
)


class FakeTok:
    def __init__(self, tmp_path, monkeypatch):
        self.log = tmp_path / "fake-tok.log"
        self.path = tmp_path / "bin" / "tok"
        self.path.parent.mkdir()
        self.path.write_text(FAKE_TOK.format(python=sys.executable))
        self.path.chmod(self.path.stat().st_mode | stat.S_IEXEC)
        self.monkeypatch = monkeypatch
        self.responses = {}
        monkeypatch.setenv("TOKIMEKI_BIN", str(self.path))
        monkeypatch.setenv("FAKE_LOG", str(self.log))
        self._sync()

    def respond(self, sub, stdout="", stderr="", exit=0):
        if not isinstance(stdout, str):
            stdout = json.dumps(stdout)
        self.responses[sub] = {"stdout": stdout, "stderr": stderr, "exit": exit}
        self._sync()

    def _sync(self):
        self.monkeypatch.setenv("FAKE_RESPONSES", json.dumps(self.responses))

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]


@pytest.fixture
def fake_tok(tmp_path, monkeypatch):
    for var in ("TOKIMEKI_GROUP", "TOKIMEKI_JOB_ID"):
        monkeypatch.delenv(var, raising=False)
    return FakeTok(tmp_path, monkeypatch)
