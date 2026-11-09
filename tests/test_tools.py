"""The three helpdesk tools, called directly without any agent or model."""

import json

import pytest

from helpdesk.tools import (
    SessionContext,
    TicketError,
    check_service_status,
    find_instructions,
    make_tools,
    prepare_ticket,
)


# ---------------------------------------------------------------- find_instructions


@pytest.mark.parametrize(("topic", "guide"), [("wifi", "GUIDE-WIFI"), ("Wi-Fi", "GUIDE-WIFI"), ("password", "GUIDE-PASSWORD")])
def test_find_instructions_returns_fixture_guide(topic, guide):
    result = find_instructions(topic)
    assert result["found"] is True
    assert result["instruction_id"] == guide
    assert result["source"] == f"data/helpdesk.json#{guide}"
    assert len(result["steps"]) == 4


def test_find_instructions_unknown_topic_is_not_invented():
    result = find_instructions("printer")
    assert result["found"] is False and "steps" not in result


# ---------------------------------------------------------------- check_service_status


@pytest.mark.parametrize(
    ("profile", "service", "expected"),
    [
        ("normal", "wifi", "operational"),
        ("wifi_outage", "wifi", "outage"),
        ("wifi_outage", "account_recovery", "operational"),
        ("recovery_outage", "account_recovery", "outage"),
        ("recovery_outage", "password", "outage"),  # a password topic maps to account_recovery
        ("status_unavailable", "wifi", "unknown"),
    ],
)
def test_check_service_status_uses_selected_snapshot(profile, service, expected):
    result = check_service_status(service, profile)
    assert result["status"] == expected
    assert result["status_profile"] == profile
    assert result["repair_time"] is None


def test_unknown_service_is_unknown_not_operational():
    assert check_service_status("printing", "normal")["status"] == "unknown"


def test_unknown_profile_is_an_error():
    with pytest.raises(ValueError):
        check_service_status("wifi", "sunny_day")


# ---------------------------------------------------------------- prepare_ticket


def _ticket(tmp_path, **overrides):
    args = dict(
        category="wifi",
        summary="Campus-Demo still will not connect.",
        steps_tried=["Enabled Wi-Fi", "Forgot the saved network"],
        user_id="demo-user-a",
        thread_id="t1",
        status_profile="normal",
        service_status="operational",
        reference_ids=["GUIDE-WIFI"],
        ticket_dir=tmp_path,
    )
    args.update(overrides)
    return prepare_ticket(**args)


def test_prepare_ticket_writes_template_shaped_draft(tmp_path):
    result = _ticket(tmp_path)
    files = list(tmp_path.glob("TCK-*.json"))
    assert len(files) == 1 and result["sent"] is False
    saved = json.loads(files[0].read_text(encoding="utf-8"))["ticket"]
    template_fields = {"ticket_id", "status", "user_id", "thread_id", "category", "summary",
                       "steps_tried", "service_status", "status_profile", "reference_ids"}
    assert set(saved) == template_fields
    assert saved["status"] == "draft"
    assert saved["steps_tried"] == ["Enabled Wi-Fi", "Forgot the saved network"]
    assert saved["user_id"] == "demo-user-a" and saved["thread_id"] == "t1"


def test_prepare_ticket_ids_are_unique(tmp_path):
    assert _ticket(tmp_path)["ticket"]["ticket_id"] != _ticket(tmp_path)["ticket"]["ticket_id"]


@pytest.mark.parametrize("overrides", [{"summary": ""}, {"steps_tried": []}, {"steps_tried": ["  "]}])
def test_prepare_ticket_refuses_missing_details(tmp_path, overrides):
    with pytest.raises(TicketError):
        _ticket(tmp_path, **overrides)
    assert not list(tmp_path.glob("*.json"))


def test_prepare_ticket_refuses_secrets(tmp_path):
    with pytest.raises(TicketError):
        _ticket(tmp_path, summary="My password is hunter2 and it fails")


def test_not_checked_status_has_no_profile(tmp_path):
    ticket = _ticket(tmp_path, service_status="not_checked")["ticket"]
    assert ticket["service_status"] == "not_checked" and ticket["status_profile"] is None


# ---------------------------------------------------------------- tool wrappers


def test_session_tools_are_bound_to_application_context(tmp_path):
    ctx = SessionContext("demo-user-b", "thread-x", "wifi_outage", tmp_path)
    tools = {t.name: t for t in make_tools(ctx)}
    assert set(tools) == {"find_instructions", "check_service_status", "prepare_ticket"}
    # The model cannot pass user_id, thread_id or status_profile: they are not tool arguments.
    for name in ("user_id", "thread_id", "status_profile"):
        assert name not in tools["prepare_ticket"].args
        assert name not in tools["check_service_status"].args
    status = json.loads(tools["check_service_status"].invoke({"service": "wifi"}))
    assert status["status"] == "outage"
    ticket = json.loads(
        tools["prepare_ticket"].invoke({"category": "wifi", "summary": "No connection", "steps_tried": ["Enabled Wi-Fi"]})
    )
    assert ticket["ticket"]["user_id"] == "demo-user-b" and ticket["ticket"]["thread_id"] == "thread-x"


def test_ticket_tool_reports_missing_details_instead_of_raising(tmp_path):
    tool = {t.name: t for t in make_tools(SessionContext("demo-user-a", "t", "normal", tmp_path))}["prepare_ticket"]
    result = json.loads(tool.invoke({"category": "wifi", "summary": "", "steps_tried": []}))
    assert result["created"] is False and "Ask the user" in result["error"]
