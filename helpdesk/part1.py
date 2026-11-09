"""Part 1: a helpdesk graph with fixed routing rules and no LLM.

Original graph::

    START -> read_request -> route_by_category ─┬─ wifi_help     -> END
                                                ├─ password_help -> END
                                                └─ other_help    -> END

Changed graph (variant ``with_clarification``) adds one more branch::

                                                └─ clarify_problem -> END

``read_request`` is a node: it reads ``message`` and returns an *update*
(``category`` and ``topics``).  ``route_by_category`` is not a node: it is the
function behind the conditional edge.  It reads the current state and only
returns the *name* of the next node; it never changes the state.
"""

from __future__ import annotations

from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from .data import helpdesk

GraphVariant = Literal["original", "with_clarification"]


class HelpdeskState(TypedDict, total=False):
    message: str  # the user's original message, never modified
    topics: list[str]  # every supported topic found in the message
    category: str  # wifi | password | multiple | other, set by read_request
    reply: str  # the answer produced by one help node


def detect_topics(message: str) -> list[str]:
    """Return the supported topics mentioned in ``message`` (case-insensitive).

    The aliases come from ``topic_aliases`` in data/helpdesk.json:
    ``wifi``/``wi-fi`` for Wi-Fi and ``password`` for passwords.
    """
    text = message.lower()
    aliases = helpdesk()["topic_aliases"]
    return [topic for topic in ("wifi", "password") if any(a in text for a in aliases[topic])]


def format_instructions(topic: str) -> str:
    guide = helpdesk()["instructions"][topic]
    steps = "\n".join(f"{i}. {step}" for i, step in enumerate(guide["steps"], start=1))
    return f"{guide['title']} ({guide['instruction_id']}):\n{steps}"


# ---------------------------------------------------------------- nodes


def make_read_request(variant: GraphVariant):
    def read_request(state: HelpdeskState) -> HelpdeskState:
        topics = detect_topics(state["message"])
        if variant == "with_clarification" and len(topics) > 1:
            category = "multiple"
        elif "wifi" in topics:  # rule 1: Wi-Fi is checked first
            category = "wifi"
        elif "password" in topics:  # rule 2: only reached when Wi-Fi is absent
            category = "password"
        else:
            category = "other"
        return {"topics": topics, "category": category}

    return read_request


def wifi_help(state: HelpdeskState) -> HelpdeskState:
    return {"reply": format_instructions("wifi")}


def password_help(state: HelpdeskState) -> HelpdeskState:
    return {"reply": format_instructions("password")}


def other_help(state: HelpdeskState) -> HelpdeskState:
    return {
        "reply": "I can only help with Wi-Fi and password problems in this demo. "
        "Does your problem concern Wi-Fi or a password?"
    }


def clarify_problem(state: HelpdeskState) -> HelpdeskState:
    return {
        "reply": "Your message mentions both Wi-Fi and a password. "
        "Is the problem connecting to Wi-Fi, or recovering your account password? "
        "Which one should we solve first?"
    }


# ---------------------------------------------------------------- edge


ROUTES = {
    "wifi": "wifi_help",
    "password": "password_help",
    "other": "other_help",
    "multiple": "clarify_problem",
}


def route_by_category(state: HelpdeskState) -> str:
    """Conditional edge: read ``category`` from the state, name the next node."""
    return ROUTES[state["category"]]


def build_part1_graph(variant: GraphVariant = "original"):
    builder = StateGraph(HelpdeskState)
    builder.add_node("read_request", make_read_request(variant))
    builder.add_node("wifi_help", wifi_help)
    builder.add_node("password_help", password_help)
    builder.add_node("other_help", other_help)
    targets = ["wifi_help", "password_help", "other_help"]
    if variant == "with_clarification":
        builder.add_node("clarify_problem", clarify_problem)
        targets.append("clarify_problem")

    builder.add_edge(START, "read_request")
    builder.add_conditional_edges("read_request", route_by_category, targets)
    for node in targets:
        builder.add_edge(node, END)
    return builder.compile()


def run_with_trace(message: str, variant: GraphVariant = "original") -> dict:
    """Run the graph once and record each node, its update and the full state after it."""
    graph = build_part1_graph(variant)
    state: dict = {"message": message}
    steps = []
    for chunk in graph.stream({"message": message}, stream_mode="updates"):
        for node, update in chunk.items():
            state = {**state, **(update or {})}
            steps.append({"node": node, "update": update, "state_after": dict(state)})
    return {
        "graph_variant": variant,
        "input": {"message": message},
        "route": ["START", *[s["node"] for s in steps], "END"],
        "steps": steps,
        "final_state": state,
        "reply": state.get("reply"),
    }


def mermaid(variant: GraphVariant = "original") -> str:
    return build_part1_graph(variant).get_graph().draw_mermaid()
