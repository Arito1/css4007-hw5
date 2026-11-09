"""A clearly labelled FAKE chat model for tests and offline dry runs.

It is NOT an LLM.  It follows a few hand-written keyword rules so that tests and
CI can exercise the real LangGraph wiring (tool requests, ToolNode execution,
loop back to the model, checkpointer, user store) without an API key.

It behaves like a model in one important way: it only *returns* an
``AIMessage`` - either with ``tool_calls`` (a request) or with text (an answer).
It never executes a tool itself.  Its decisions after a tool result depend on
the ToolMessage content it receives, exactly like a real model's would.

Real demonstrations for Part 2 use Claude (``--model anthropic``).
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from .data import helpdesk

FAILURE_HINTS = ("still", "fails", "will not connect", "won't connect", "cannot connect", "can't connect", "unavailable", "does not work")


def _text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content if isinstance(b, dict))


def detect_topic(text: str) -> str | None:
    lower = text.lower()
    if "wi-fi" in lower or "wifi" in lower:
        return "wifi"
    if "password" in lower:
        return "password"
    return None


def extract_steps(text: str) -> list[str]:
    """Steps the user *said* they tried.  Nothing is added that the user did not write."""
    lower = text.lower()
    steps = []
    if re.search(r"\benabled\b", lower):
        steps.append("Enabled Wi-Fi")
    if "forgot the saved network" in lower or "forgot the network" in lower:
        steps.append("Forgot the saved network")
    if re.search(r"reconnect", lower):
        steps.append("Tried reconnecting")
    return steps


def problem_sentence(text: str) -> str | None:
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        if any(h in sentence.lower() for h in FAILURE_HINTS):
            return sentence.strip()
    return None


def _call(name: str, **args: Any) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call_{uuid.uuid4().hex[:12]}", "type": "tool_call"}])


SERVICE_FOR_TOPIC = {"wifi": "wifi", "password": "account_recovery"}
TOPIC_LABEL = {"wifi": "Wi-Fi", "password": "password / account recovery"}


class FakeHelpdeskModel(BaseChatModel):
    """Deterministic keyword rules standing in for an LLM.  See module docstring."""

    @property
    def _llm_type(self) -> str:
        return "fake-helpdesk-rules"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "FakeHelpdeskModel":
        return self

    def _generate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self.decide(messages))])

    # ------------------------------------------------------------------ rules

    def decide(self, messages: list[BaseMessage]) -> AIMessage:
        memory_notes = [_text(m) for m in messages if isinstance(m, SystemMessage) and _text(m).startswith("USER_MEMORY:")]
        match = re.search(r"USER_MEMORY: (\{.*?\})", memory_notes[-1]) if memory_notes else None
        memory = json.loads(match.group(1)) if match else {}
        conv = [m for m in messages if not isinstance(m, SystemMessage)]
        last_human = max(i for i, m in enumerate(conv) if isinstance(m, HumanMessage))
        text = _text(conv[last_human])
        lower = text.lower()
        earlier = conv[:last_human]
        this_turn = conv[last_human + 1 :]
        requested = {c["name"] for m in this_turn if isinstance(m, AIMessage) for c in m.tool_calls}
        results = {m.name: json.loads(m.content) for m in this_turn if isinstance(m, ToolMessage)}
        earlier_user = [_text(m) for m in earlier if isinstance(m, HumanMessage)]
        last_ai = next((_text(m) for m in reversed(earlier) if isinstance(m, AIMessage) and _text(m)), "")

        # 1. Explicit request to remember a language -> write user memory.
        pref = re.search(r"(?:prefer|want|use)\s+(?:replies|answers|responses)?\s*in\s+([A-Z][a-z]+)", text)
        if "remember" in lower and pref and "save_user_preference" not in requested:
            return _call("save_user_preference", language=pref.group(1))

        parts: list[str] = []
        language = memory.get("language")
        if "save_user_preference" in results:
            parts.append(f"I saved your preference in user memory: replies in {results['save_user_preference']['user_memory']['language']}.")

        # 2. Questions about memory.
        if "which language" in lower:
            parts.append(
                f"You asked me to reply in {language} (read from your saved user memory)."
                if language
                else "No language preference has been recorded for you."
            )
            if "help with" in lower:
                parts.append("I can help with: " + ", ".join(helpdesk()["scope"]) + ".")
            return self._answer(parts, language)

        if "have i told you" in lower:
            topics = {t for t in map(detect_topic, earlier_user) if t}
            if not language and not topics:
                parts.append(
                    "No preferred language and no previous problem have been recorded for you. "
                    "Tell me your problem and, if you like, the language you prefer."
                )
            else:
                if language:
                    parts.append(f"Your saved language preference is {language}.")
                if topics:
                    parts.append("In this conversation you mentioned: " + ", ".join(TOPIC_LABEL[t] for t in sorted(topics)) + ".")
            return self._answer(parts, language)

        if re.search(r"which (steps|problem)|did we discuss|already try", lower):
            history = " ".join(earlier_user)
            topic = detect_topic(history)
            steps = extract_steps(history)
            if not topic and not steps:
                parts.append("Nothing about a problem or steps has been recorded in this conversation yet.")
            else:
                if topic:
                    parts.append(f"You reported a {TOPIC_LABEL[topic]} problem.")
                if steps:
                    parts.append("Steps you said you already tried: " + "; ".join(steps) + ", and it still did not work.")
            return self._answer(parts, language)

        if re.search(r"(already )?tried (that|those|them|it)\b", lower):
            guide = re.search(r"\((GUIDE-[A-Z]+)\)", " ".join(_text(m) for m in earlier if isinstance(m, AIMessage)))
            if guide:
                parts.append(
                    f'"That" refers to the {guide.group(1)} steps I gave you earlier in this conversation. '
                    "Since they did not solve it, the next step is to check the service status; "
                    "I can check it and, if needed, prepare a local ticket draft with those steps."
                )
            else:
                parts.append("I am not sure what you tried. Which steps did you follow?")
            return self._answer(parts, language)

        # 3. Helpdesk work: instructions, status, tickets.
        topic = detect_topic(text) or next((t for t in map(detect_topic, reversed(earlier_user)) if t), None)
        answering_ticket_question = "what problem are you having" in last_ai.lower()
        wants_ticket = "ticket" in lower or answering_ticket_question
        conditional = bool(re.search(r"if it is (operating|working|operational)", lower))
        wants_status = bool(re.search(r"\b(status|down|known problem|outage)\b", lower))
        wants_instructions = bool(re.search(r"troubleshooting|instructions|\bsteps\b|cannot connect|can't connect", lower))
        if topic and not (wants_ticket or wants_status):
            wants_instructions = True

        if wants_instructions and topic and "find_instructions" not in requested:
            return _call("find_instructions", topic=topic)
        if (wants_status or conditional) and topic and "check_service_status" not in requested:
            return _call("check_service_status", service=SERVICE_FOR_TOPIC[topic])

        if "find_instructions" in results and results["find_instructions"].get("found"):
            guide = results["find_instructions"]
            steps = "\n".join(f"{i}. {s}" for i, s in enumerate(guide["steps"], 1))
            parts.append(f"Here are the instructions from the local guide ({guide['instruction_id']}):\n{steps}")
            tried = extract_steps(text)
            if tried and not (wants_ticket or wants_status):
                parts.append("You said you already tried: " + "; ".join(tried) + ". Next I can check the service status or prepare a local ticket draft.")

        status = results.get("check_service_status")
        if status:
            name = "Wi-Fi" if status["service"] == "wifi" else "account recovery"
            if status["status"] == "operational":
                parts.append(f"The demo status source reports {name} is operating ({status['message']})")
            elif status["status"] == "outage":
                note = "" if "repair time" in status["message"] else " The data does not give a repair time."
                parts.append(f"The demo status source reports an outage of {name}: {status['message']}{note}")
            else:
                parts.append(f"I could not determine the {name} status ({status['message']}). I cannot confirm that it is operating.")

        if wants_ticket:
            details = " ".join([*earlier_user, text]) if answering_ticket_question else text
            steps = extract_steps(details)
            if not topic or not steps:
                parts.append("What problem are you having, and what have you already tried?")
                return self._answer(parts, language)
            if conditional and status and status["status"] != "operational":
                if status["status"] == "outage":
                    parts.append("Your request said to prepare a ticket only if the service was operating, so I have not prepared that ticket.")
                else:
                    parts.append("Would you like a ticket draft explaining that the status could not be checked?")
                return self._answer(parts, language)
            if "prepare_ticket" not in requested:
                sentence = problem_sentence(details)
                summary = f"{TOPIC_LABEL[topic]} problem: {sentence}" if sentence else f"{TOPIC_LABEL[topic]} problem"
                refs = [results["find_instructions"]["instruction_id"]] if "find_instructions" in results else []
                if not refs and any("GUIDE-" in _text(m) for m in earlier if isinstance(m, (AIMessage, ToolMessage))):
                    refs = [helpdesk()["instructions"][topic]["instruction_id"]]
                return _call(
                    "prepare_ticket",
                    category=topic,
                    summary=summary,
                    steps_tried=steps,
                    service_status=status["status"] if status else "not_checked",
                    reference_ids=refs,
                )
            ticket = results["prepare_ticket"]
            if ticket.get("created"):
                shown = "known: " + ticket["ticket"]["service_status"] if ticket["ticket"]["service_status"] != "not_checked" else "not checked"
                parts.append(
                    f"I prepared a local ticket draft {ticket['ticket']['ticket_id']} ({ticket['file']}) "
                    f"with the steps you stated: {'; '.join(ticket['ticket']['steps_tried'])}. "
                    f"Service status: {shown}. Nothing has been sent."
                )
            else:
                parts.append(f"I could not prepare the ticket: {ticket.get('error')}")
            return self._answer(parts, language)

        if status and status["status"] == "outage":
            parts.append("If you want, I can prepare a local ticket draft describing the error.")
        if not parts:
            parts.append("I can help with Wi-Fi and password problems in this demo. Does your problem concern Wi-Fi or a password?")
        return self._answer(parts, language)

    @staticmethod
    def _answer(parts: list[str], language: str | None) -> AIMessage:
        body = "\n".join(parts)
        if language and language.lower() != "english":
            body = (
                f"[Reply language from user memory: {language}. This FAKE model cannot translate; "
                f"the real model answers in {language}.]\n" + body
            )
        return AIMessage(content=body)
