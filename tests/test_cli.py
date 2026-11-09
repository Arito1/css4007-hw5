"""The command-line runner, with the FAKE model."""

import json
import subprocess
import sys

import pytest

from helpdesk.agent import make_model
from helpdesk.data import PROJECT_ROOT


def test_scenario_runner_restarts_a_real_process(tmp_path):
    out, storage = tmp_path / "out", tmp_path / "storage"
    subprocess.run(
        [sys.executable, "-m", "helpdesk", "scenarios", "--model", "fake", "--only", "S11",
         "--out", str(out), "--storage", str(storage)],
        cwd=PROJECT_ROOT, check=True, capture_output=True,
    )
    log = json.loads((out / "S11.json").read_text(encoding="utf-8"))
    actions = [e["action"] for e in log["events"]]
    assert actions == ["message", "restart_process", "message"]
    restart = log["events"][1]
    assert restart["previous_pid"] != restart["next_pid"]
    assert "FAKE" in log["model"]
    assert "Wi-Fi" in log["final_reply"]


def test_real_model_needs_key_but_tests_do_not(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        make_model("anthropic")
    assert make_model("fake") is not None
