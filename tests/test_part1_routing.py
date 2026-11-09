"""Part 1 routing: fixed rules, no model involved."""

import pytest

from helpdesk.part1 import build_part1_graph, detect_topics, run_with_trace


@pytest.mark.parametrize(
    ("message", "expected_node"),
    [
        ("I cannot connect to Wi-Fi.", "wifi_help"),
        ("I forgot my PASSWORD.", "password_help"),  # uppercase must still match
        ("My laptop screen is broken.", "other_help"),
        ("My Wi-Fi password does not work.", "wifi_help"),  # Wi-Fi rule is checked first
        ("wifi is slow", "wifi_help"),  # alias without hyphen
    ],
)
def test_original_graph_routes(message, expected_node):
    trace = run_with_trace(message, "original")
    assert trace["route"] == ["START", "read_request", expected_node, "END"]


def test_help_nodes_return_fixture_instructions():
    wifi = run_with_trace("I cannot connect to Wi-Fi.")["reply"]
    password = run_with_trace("I forgot my PASSWORD.")["reply"]
    assert "GUIDE-WIFI" in wifi and "Campus-Demo" in wifi
    assert "GUIDE-PASSWORD" in password and "Forgot password" in password


def test_other_help_asks_which_topic():
    reply = run_with_trace("My laptop screen is broken.")["reply"]
    assert "Wi-Fi or a password" in reply


def test_clarification_variant_routes_two_topics_to_new_node():
    trace = run_with_trace("My Wi-Fi password does not work.", "with_clarification")
    assert trace["route"] == ["START", "read_request", "clarify_problem", "END"]
    assert trace["final_state"]["category"] == "multiple"
    assert "Wi-Fi" in trace["reply"] and "password" in trace["reply"]


def test_clarification_variant_keeps_single_topic_routes():
    assert run_with_trace("I forgot my PASSWORD.", "with_clarification")["route"][2] == "password_help"


def test_original_message_is_kept_and_fields_set_in_order():
    steps = run_with_trace("I cannot connect to Wi-Fi.")["steps"]
    first, second = steps
    assert first["node"] == "read_request"
    assert first["state_after"]["category"] == "wifi" and "reply" not in first["state_after"]
    assert second["state_after"]["message"] == "I cannot connect to Wi-Fi."
    assert second["state_after"]["reply"]


def test_detect_topics_is_case_insensitive():
    assert detect_topics("WI-FI and PassWord") == ["wifi", "password"]
    assert detect_topics("nothing relevant") == []


def test_original_graph_has_no_clarify_node():
    assert "clarify_problem" not in build_part1_graph("original").get_graph().nodes
    assert "clarify_problem" in build_part1_graph("with_clarification").get_graph().nodes
