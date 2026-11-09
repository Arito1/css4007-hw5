"""Offline checks of the request we would send to Claude (no network, no real key).

The real model is never called here.  We record what the graph passes to the
model (using the fake model) and format it with langchain-anthropic's own
payload builder.  This catches mistakes that would only show up in a paid run:
a system prompt that changes between turns, rewritten history, or sampling
parameters that current Claude models reject.
"""

import pytest
from langchain_core.messages import HumanMessage

from helpdesk.agent import make_model
from helpdesk.fake_model import FakeHelpdeskModel


class RecordingFakeModel(FakeHelpdeskModel):
    requests: list = []

    def decide(self, messages):
        self.requests.append(list(messages))
        return super().decide(messages)


@pytest.fixture
def claude(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-a-real-key")
    monkeypatch.setenv("MODEL_NAME", "claude-opus-5-5")
    return make_model("anthropic")


def test_request_settings(claude):
    payload = claude._get_request_payload([HumanMessage("hi")])
    assert "temperature" not in payload and "top_p" not in payload
    assert payload["max_tokens"] >= 16000
    assert payload["output_config"]["effort"] == "medium"


def test_system_prompt_frozen_and_history_append_only(open_session, claude):
    model = RecordingFakeModel()
    model.requests = []
    session = open_session(thread="restart-a", model=model)
    session.send("Please remember that I prefer replies in Kazakh. My issue is Wi-Fi. "
                 "I enabled it and tried reconnecting, but it still fails.")
    session.send("Which problem and steps did we discuss?")
    payloads = [claude._get_request_payload(r) for r in model.requests]
    assert len(payloads) >= 3

    # 1. The top-level system prompt is byte-identical in every request.
    assert len({str(p["system"]) for p in payloads}) == 1
    # 2. Each request only appends to the previous one (no rewritten or dropped turns).
    for before, after in zip(payloads, payloads[1:]):
        assert after["messages"][: len(before["messages"])] == before["messages"]
    # 3. User memory is a system message kept in place, after the user's message.
    last = payloads[-1]["messages"]
    memory_turns = [i for i, m in enumerate(last) if m["role"] == "system"]
    assert memory_turns and all(last[i - 1]["role"] == "user" for i in memory_turns)
    assert "Kazakh" in str(last[memory_turns[-1]]["content"])
    assert "Kazakh" not in str(payloads[-1]["system"])
