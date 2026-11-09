"""Parts 2 and 3: the model-and-tools helpdesk with memory.

Graph::

    START -> load_user_memory -> agent ─┬─ (tool calls, round <= limit) -> tools -> agent
                                        ├─ (tool calls, round  > limit) -> loop_limit -> END
                                        └─ (no tool calls: final answer) -> END

* ``agent`` asks the model for the next message.  The model can only *request*
  tools (``AIMessage.tool_calls``); it never runs them.
* ``tools`` is LangGraph's ``ToolNode``: our program executes the requested
  Python functions and appends one ``ToolMessage`` per call.
* ``route_after_agent`` is the conditional edge.  It looks at the last
  message and at ``tool_rounds`` and decides: run tools, stop at the limit, or end.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from .data import helpdesk
from .memory import Storage, checkpoint_thread_id, make_memory_tools
from .tools import SessionContext, make_tools

DEFAULT_MAX_TOOL_ROUNDS = 4


class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]  # conversation memory
    user_id: str
    thread_id: str
    status_profile: str
    user_memory: dict  # copy of the user's saved preferences, read at the start of each turn
    tool_rounds: int  # model requests that asked for tools in the current turn
    loop_limit_reached: bool


USER_MEMORY_PREFIX = "USER_MEMORY:"


def system_prompt(ctx: SessionContext) -> str:
    """The top-level system prompt.  It is FROZEN for the whole conversation.

    Claude's thinking blocks are bound to the exact prefix (system prompt, tools,
    earlier messages) that produced them, so nothing that changes between turns
    may live here.  Changing facts - the user's saved preferences - are appended
    to the history as a mid-conversation system message instead
    (see ``user_memory_message``).
    """
    data = helpdesk()
    return f"""You are the assistant of a FICTIONAL university IT helpdesk used for a homework exercise.
Scope: {', '.join(data['scope'])}. You have no access to real university systems.

Session (chosen by the application, not by you): user_id={ctx.user_id}, thread_id={ctx.thread_id}.
At the start of every turn the application adds a system message beginning with "{USER_MEMORY_PREFIX}".
It contains this user's saved long-term preferences (the newest one is current). If it names a language,
reply in that language. If it is empty, reply in the language of the user's message.

Rules:
- Use find_instructions for Wi-Fi or password instructions and quote them from the tool result. Do not invent steps.
- Use check_service_status before saying anything about whether a service is down. Wi-Fi -> "wifi",
  password problems -> "account_recovery". "unknown" means the status could not be determined: it is
  NOT operational and NOT a confirmed outage. The data never gives repair times; never invent one.
- Follow conditional requests exactly. If the user says "if it is operating, prepare a ticket", only prepare
  the ticket when the status result is "operational". On an outage, explain that you did not prepare it.
  On "unknown", do not prepare it; ask whether they want a draft explaining the status could not be checked.
- prepare_ticket needs a problem description and the steps the user said they already tried. Use only what the
  user stated in this conversation. If either is missing, ask the user instead of calling the tool.
  Pass service_status exactly as returned by check_service_status in this conversation, or "not_checked".
  A ticket is only a local draft; say that nothing was sent and give its file name.
- Call save_user_preference only when the user explicitly asks you to remember a language preference.
- Earlier messages in this conversation are available to you; use them to resolve references such as "that".
  You only know what is in this conversation and in the USER_MEMORY messages. If the user asks about a preference
  or a previous problem that is not there, say that nothing has been recorded.
- Never ask for or store passwords, recovery codes or API keys.
- Keep answers short."""


def user_memory_message(prefs: dict) -> SystemMessage:
    shown = {k: v for k, v in prefs.items() if not k.startswith("_")}
    return SystemMessage(
        f"{USER_MEMORY_PREFIX} {json.dumps(shown, ensure_ascii=False)}"
        + ("" if shown else " (nothing saved for this user)"),
        additional_kwargs={"helpdesk": "user_memory"},
    )


def build_agent_graph(
    model: BaseChatModel,
    ctx: SessionContext,
    storage: Storage,
    max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
):
    tools = make_tools(ctx) + make_memory_tools(storage, ctx.user_id, ctx.thread_id)
    model_with_tools = model.bind_tools(tools)

    frozen_prompt = SystemMessage(system_prompt(ctx))

    def load_user_memory(state: AgentState) -> AgentState:
        # Read user memory for the user chosen by the application (never by the model),
        # append it after the new user message, and reset the per-turn counters.
        prefs = storage.get_preferences(ctx.user_id)
        return {
            "messages": [user_memory_message(prefs)],
            "user_memory": prefs,
            "tool_rounds": 0,
            "loop_limit_reached": False,
        }

    def agent(state: AgentState) -> AgentState:
        response = model_with_tools.invoke([frozen_prompt, *state["messages"]])
        update: AgentState = {"messages": [response]}
        if getattr(response, "tool_calls", None):
            update["tool_rounds"] = state.get("tool_rounds", 0) + 1
        return update

    def route_after_agent(state: AgentState) -> str:
        last = state["messages"][-1]
        if not getattr(last, "tool_calls", None):
            return END
        if state.get("tool_rounds", 0) > max_tool_rounds:
            return "loop_limit"
        return "tools"

    def loop_limit(state: AgentState) -> AgentState:
        # The last AI message requested tools we will not run.  Answer every pending call
        # so the history stays valid for the next model request, then stop.
        last = state["messages"][-1]
        skipped = [
            ToolMessage(
                content=json.dumps({"executed": False, "reason": f"tool loop limit of {max_tool_rounds} rounds reached"}),
                tool_call_id=call["id"],
                name=call["name"],
            )
            for call in last.tool_calls
        ]
        final = AIMessage(
            content=f"I stopped after {max_tool_rounds} rounds of tool use without reaching an answer. "
            "Please rephrase or narrow the request."
        )
        return {"messages": [*skipped, final], "loop_limit_reached": True}

    builder = StateGraph(AgentState)
    builder.add_node("load_user_memory", load_user_memory)
    builder.add_node("agent", agent)
    builder.add_node("tools", ToolNode(tools))
    builder.add_node("loop_limit", loop_limit)
    builder.add_edge(START, "load_user_memory")
    builder.add_edge("load_user_memory", "agent")
    builder.add_conditional_edges("agent", route_after_agent, ["tools", "loop_limit", END])
    builder.add_edge("tools", "agent")
    builder.add_edge("loop_limit", END)
    return builder.compile(checkpointer=storage.checkpointer, store=storage.store)


# ---------------------------------------------------------------- model choice


def make_model(name: str) -> BaseChatModel:
    """``fake`` -> scripted offline model; ``anthropic`` -> Claude via langchain-anthropic."""
    if name == "fake":
        from .fake_model import FakeHelpdeskModel

        return FakeHelpdeskModel()
    if name == "anthropic":
        from langchain_anthropic import ChatAnthropic

        model_name = os.environ.get("MODEL_NAME")
        if not os.environ.get("ANTHROPIC_API_KEY") or not model_name:
            raise SystemExit("Set ANTHROPIC_API_KEY and MODEL_NAME in .env (see .env.example), or use --model fake.")
        # No temperature: current Claude models reject non-default sampling parameters.
        kwargs: dict[str, Any] = {"model": model_name, "max_tokens": 16000}
        if os.environ.get("HELPDESK_EFFORT", "medium"):
            kwargs["effort"] = os.environ.get("HELPDESK_EFFORT", "medium")
        fallback_ok = model_name.startswith(("claude-opus-5", "claude-sonnet-5-5", "claude-fable"))
        if fallback_ok and os.environ.get("HELPDESK_REFUSAL_FALLBACK", "1") == "1":
            # Server-side refusal fallback: if a safety classifier declines, the API
            # re-runs the request on a fallback model inside the same call.
            kwargs["betas"] = ["server-side-fallback-2026-07-01"]
            kwargs["model_kwargs"] = {"extra_body": {"fallbacks": "default"}}
        return ChatAnthropic(**kwargs)
    raise SystemExit(f"Unknown model {name!r}; use 'anthropic' or 'fake'.")


def model_label(model: BaseChatModel) -> str:
    from .fake_model import FakeHelpdeskModel

    if isinstance(model, FakeHelpdeskModel):
        return "FAKE scripted model (helpdesk/fake_model.py) - not an LLM"
    return f"Anthropic Claude via langchain-anthropic, model={getattr(model, 'model', '?')}"


# ---------------------------------------------------------------- session + trace


def message_text(message: AnyMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text")


def _parse(content: Any) -> Any:
    try:
        return json.loads(content)
    except (TypeError, ValueError):
        return content


@dataclass
class TurnResult:
    reply: str
    trace: dict = field(default_factory=dict)


class HelpdeskSession:
    """One conversation (user + thread + status snapshot) against saved storage."""

    def __init__(
        self,
        ctx: SessionContext,
        model: BaseChatModel,
        storage: Storage,
        max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
    ):
        self.ctx = ctx
        self.model = model
        self.storage = storage
        self.max_tool_rounds = max_tool_rounds
        self.graph = build_agent_graph(model, ctx, storage, max_tool_rounds)
        self.config = {
            "configurable": {"thread_id": checkpoint_thread_id(ctx.user_id, ctx.thread_id)},
            # Second safety net on top of max_tool_rounds: LangGraph's own step limit.
            "recursion_limit": 4 * max_tool_rounds + 10,
        }

    def history(self) -> list[AnyMessage]:
        return list(self.graph.get_state(self.config).values.get("messages", []))

    def send(self, text: str) -> TurnResult:
        before = self.history()
        trace: dict = {
            "user_id": self.ctx.user_id,
            "thread_id": self.ctx.thread_id,
            "checkpoint_thread_id": self.config["configurable"]["thread_id"],
            "status_profile": self.ctx.status_profile,
            "model": model_label(self.model),
            "user_message": text,
            "conversation_memory_read": {
                "messages_loaded_from_checkpoint": len(before),
                "earlier_user_messages": [message_text(m) for m in before if isinstance(m, HumanMessage)],
            },
            "nodes": [],
            "model_tool_requests": [],
            "tool_results": [],
            "sources": {"reference_file": [], "service_status": [], "user_memory_read": None, "user_memory_written": []},
            "ticket_files": [],
        }
        inputs = {
            "messages": [HumanMessage(text)],
            "user_id": self.ctx.user_id,
            "thread_id": self.ctx.thread_id,
            "status_profile": self.ctx.status_profile,
        }
        model_round = 0
        for chunk in self.graph.stream(inputs, self.config, stream_mode="updates"):
            for node, update in chunk.items():
                update = update or {}
                entry: dict = {"node": node}
                if node == "load_user_memory":
                    prefs = {k: v for k, v in update.get("user_memory", {}).items() if not k.startswith("_")}
                    trace["sources"]["user_memory_read"] = prefs
                    entry["state_update"] = {"user_memory": prefs, "tool_rounds": 0}
                for msg in update.get("messages", []):
                    if isinstance(msg, AIMessage) and msg.tool_calls:
                        model_round += 1
                        for call in msg.tool_calls:
                            trace["model_tool_requests"].append({"round": model_round, "tool": call["name"], "args": call["args"]})
                        entry.setdefault("requested_tools", []).extend(c["name"] for c in msg.tool_calls)
                        if message_text(msg):
                            entry["model_text"] = message_text(msg)
                    elif isinstance(msg, AIMessage):
                        entry["final_answer"] = message_text(msg)
                    elif isinstance(msg, ToolMessage):
                        result = _parse(msg.content)
                        trace["tool_results"].append({"tool": msg.name, "result": result})
                        entry.setdefault("executed_tools", []).append(msg.name)
                        self._record_source(trace, msg.name, result)
                if "tool_rounds" in update and node == "agent":
                    entry["state_update"] = {"tool_rounds": update["tool_rounds"]}
                if update.get("loop_limit_reached"):
                    entry["state_update"] = {"loop_limit_reached": True}
                trace["nodes"].append(entry)
        state = self.graph.get_state(self.config).values
        reply = message_text(state["messages"][-1])
        trace["route"] = ["START", *[n["node"] for n in trace["nodes"]], "END"]
        trace["loop_limit_reached"] = bool(state.get("loop_limit_reached"))
        trace["tool_rounds"] = state.get("tool_rounds", 0)
        trace["messages_in_checkpoint_after"] = len(state["messages"])
        trace["reply"] = reply
        return TurnResult(reply=reply, trace=trace)

    @staticmethod
    def _record_source(trace: dict, tool: str, result: Any) -> None:
        if not isinstance(result, dict):
            return
        if tool == "find_instructions":
            trace["sources"]["reference_file"].append(result.get("source"))
        elif tool == "check_service_status":
            trace["sources"]["service_status"].append(
                {"service": result.get("service"), "status": result.get("status"), "source": result.get("source")}
            )
        elif tool == "prepare_ticket" and result.get("created"):
            trace["ticket_files"].append(result["file"])
        elif tool == "save_user_preference":
            trace["sources"]["user_memory_written"].append(result.get("user_memory"))
