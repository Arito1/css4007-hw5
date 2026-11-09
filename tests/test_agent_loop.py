"""Part 2: the model/tool loop, using the FAKE model (no API key)."""

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

S06_SECOND = (
    "I enabled Wi-Fi and forgot the saved network, but Campus-Demo still will not connect. "
    "Check whether Wi-Fi is down. If it is operating, prepare a ticket about this problem."
)


def tools_requested(trace):
    return [r["tool"] for r in trace["model_tool_requests"]]


def test_tool_results_return_to_the_model_before_answering(open_session):
    trace = open_session().send("Show me the Wi-Fi troubleshooting steps.").trace
    assert trace["route"] == ["START", "load_user_memory", "agent", "tools", "agent", "END"]
    assert trace["tool_results"][0]["result"]["instruction_id"] == "GUIDE-WIFI"
    assert trace["sources"]["reference_file"] == ["data/helpdesk.json#GUIDE-WIFI"]


def test_operational_status_leads_to_ticket(open_session, tmp_path):
    result = open_session(status="normal").send(S06_SECOND)
    assert tools_requested(result.trace) == ["check_service_status", "prepare_ticket"]
    ticket = result.trace["tool_results"][-1]["result"]["ticket"]
    assert ticket["service_status"] == "operational"
    assert ticket["steps_tried"] == ["Enabled Wi-Fi", "Forgot the saved network"]  # only the user's own steps
    assert len(list((tmp_path / "tickets").glob("*.json"))) == 1
    assert "Nothing has been sent" in result.reply


def test_outage_means_no_ticket(open_session, tmp_path):
    result = open_session(status="wifi_outage").send(S06_SECOND)
    assert tools_requested(result.trace) == ["check_service_status"]
    assert not (tmp_path / "tickets").exists()
    assert "not prepared" in result.reply and "repair time" in result.reply


def test_unknown_status_is_not_treated_as_operating(open_session, tmp_path):
    result = open_session(status="status_unavailable").send(S06_SECOND)
    assert "prepare_ticket" not in tools_requested(result.trace)
    assert "could not determine" in result.reply.lower()


def test_missing_details_lead_to_a_question(open_session):
    session = open_session()
    first = session.send("Prepare a support ticket.")
    assert first.trace["model_tool_requests"] == []
    assert "what have you already tried" in first.reply
    second = session.send("The issue is Wi-Fi. I enabled it and tried reconnecting, but it still fails.")
    ticket = second.trace["tool_results"][-1]["result"]["ticket"]
    assert ticket["service_status"] == "not_checked"


def test_password_topic_checks_account_recovery(open_session):
    trace = open_session(status="recovery_outage").send(
        "My password recovery page is unavailable. Check the service status. Is there a known problem?"
    ).trace
    assert trace["model_tool_requests"][0]["args"] == {"service": "account_recovery"}
    assert trace["tool_results"][0]["result"]["status"] == "outage"


class AlwaysWantsATool(BaseChatModel):
    """A broken model that never stops requesting tools."""

    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "always-tool"

    def bind_tools(self, tools: Any, **kwargs: Any):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        msg = AIMessage(content="", tool_calls=[{"name": "find_instructions", "args": {"topic": "wifi"}, "id": f"c{self.calls}", "type": "tool_call"}])
        return ChatResult(generations=[ChatGeneration(message=msg)])


def test_loop_limit_stops_a_model_that_never_answers(open_session):
    model = AlwaysWantsATool()
    session = open_session(model=model, max_tool_rounds=3)
    result = session.send("Wi-Fi?")
    assert result.trace["loop_limit_reached"] is True
    assert result.trace["route"][-2] == "loop_limit"
    assert result.trace["route"].count("tools") == 3  # tools ran exactly max_tool_rounds times
    assert model.calls == 4  # the 4th request was refused
    # Every tool_use has a matching tool result, so the saved history stays valid.
    history = session.history()
    asked = {c["id"] for m in history if isinstance(m, AIMessage) for c in m.tool_calls}
    answered = {m.tool_call_id for m in history if m.type == "tool"}
    assert asked == answered
    # The next turn starts with a fresh counter.
    model.calls = 0
    assert session.send("again").trace["tool_rounds"] == 4
