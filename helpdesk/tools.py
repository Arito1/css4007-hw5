"""Part 2 tools.

Each helpdesk operation exists twice:

* a plain Python function (``find_instructions``, ``check_service_status``,
  ``prepare_ticket``) that can be called directly, without any agent or model;
* a LangChain tool built by :func:`make_tools` for one session.  The session
  (user, thread, status snapshot, ticket folder) is fixed by the application
  when the session starts, so the model can never choose which user's data or
  which status snapshot is used.  The model only fills in the problem details.
"""

from __future__ import annotations

import copy
import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from langchain_core.tools import StructuredTool

from .data import PROJECT_ROOT, helpdesk, service_status, ticket_template

DEFAULT_TICKET_DIR = PROJECT_ROOT / "outputs" / "tickets"

SERVICE_ALIASES = {
    "wifi": "wifi",
    "wi-fi": "wifi",
    "password": "account_recovery",
    "account_recovery": "account_recovery",
    "account recovery": "account_recovery",
    "password recovery": "account_recovery",
}

StatusValue = Literal["operational", "outage", "unknown", "not_checked"]

# Very small guard for the ticket policy "do not store passwords or codes".
SECRET_PATTERN = re.compile(
    r"(password|passcode|recovery code|api key)\s*(is|was|:|=)\s*\S+", re.IGNORECASE
)


@dataclass
class SessionContext:
    """Everything the application (not the model) decides when a session starts."""

    user_id: str
    thread_id: str
    status_profile: str = "normal"
    ticket_dir: Path = field(default_factory=lambda: Path(os.environ.get("HELPDESK_TICKET_DIR", DEFAULT_TICKET_DIR)))


# ---------------------------------------------------------------- plain functions


def normalise_topic(topic: str) -> str | None:
    text = topic.strip().lower()
    for name, aliases in helpdesk()["topic_aliases"].items():
        if text == name or text in aliases or any(a in text for a in aliases):
            return name
    return None


def find_instructions(topic: str) -> dict:
    """Retrieve Wi-Fi or password instructions from data/helpdesk.json."""
    name = normalise_topic(topic)
    if name is None:
        return {
            "found": False,
            "topic": topic,
            "message": "No local instructions for this topic. Supported topics: wifi, password.",
            "source": "data/helpdesk.json",
        }
    guide = helpdesk()["instructions"][name]
    return {
        "found": True,
        "topic": name,
        "instruction_id": guide["instruction_id"],
        "title": guide["title"],
        "steps": guide["steps"],
        "source": f"data/helpdesk.json#{guide['instruction_id']}",
    }


def resolve_service(service: str) -> str | None:
    text = service.strip().lower()
    if text in SERVICE_ALIASES:
        return SERVICE_ALIASES[text]
    topic = normalise_topic(text)
    return helpdesk()["topic_services"].get(topic) if topic else None


def check_service_status(service: str, status_profile: str = "normal") -> dict:
    """Look up a service in one fictional snapshot of data/service_status.json.

    ``unknown`` means the status source could not tell us anything: it is
    neither "operational" nor a confirmed outage.
    """
    profiles = service_status()["profiles"]
    if status_profile not in profiles:
        raise ValueError(f"Unknown status profile {status_profile!r}; choose one of {sorted(profiles)}")
    name = resolve_service(service)
    if name is None or name not in profiles[status_profile]:
        return {
            "service": service,
            "status": "unknown",
            "message": "This service is not listed in the demo status data.",
            "status_profile": status_profile,
            "source": "data/service_status.json",
        }
    entry = profiles[status_profile][name]
    return {
        "service": name,
        "status": entry["status"],
        "message": entry["message"],
        "repair_time": None,  # the fixtures never give one; do not invent it
        "status_profile": status_profile,
        "source": f"data/service_status.json#{status_profile}.{name}",
    }


class TicketError(ValueError):
    """Raised when a ticket draft cannot be prepared from the given details."""


def prepare_ticket(
    *,
    category: str,
    summary: str,
    steps_tried: list[str],
    user_id: str,
    thread_id: str,
    status_profile: str | None = None,
    service_status: StatusValue = "not_checked",
    reference_ids: list[str] | None = None,
    ticket_dir: Path | str = DEFAULT_TICKET_DIR,
) -> dict:
    """Write a local ticket draft (JSON) following data/ticket_template.json.

    Nothing is sent anywhere.  Missing details are refused rather than invented.
    """
    steps = [s.strip() for s in (steps_tried or []) if s and s.strip()]
    missing = []
    if not summary or not summary.strip():
        missing.append("problem description")
    if not steps:
        missing.append("steps already tried")
    if missing:
        raise TicketError(
            "Cannot prepare the ticket: missing " + " and ".join(missing) + ". Ask the user; do not invent them."
        )
    if SECRET_PATTERN.search(summary) or any(SECRET_PATTERN.search(s) for s in steps):
        raise TicketError("The details look like they contain a password or code. Remove secrets before drafting.")
    if service_status not in ("operational", "outage", "unknown", "not_checked"):
        raise TicketError(f"service_status must be operational, outage, unknown or not_checked, not {service_status!r}")

    topic = normalise_topic(category) or category.strip().lower()
    ticket = copy.deepcopy(ticket_template()["ticket"])
    created = datetime.now(timezone.utc)
    ticket.update(
        {
            "ticket_id": f"TCK-{created:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6].upper()}",
            "status": "draft",
            "user_id": user_id,
            "thread_id": thread_id,
            "category": topic,
            "summary": summary.strip(),
            "steps_tried": steps,
            "service_status": service_status,
            "status_profile": status_profile if service_status != "not_checked" else None,
            "reference_ids": list(reference_ids or []),
        }
    )
    ticket_dir = Path(ticket_dir)
    ticket_dir.mkdir(parents=True, exist_ok=True)
    path = ticket_dir / f"{ticket['ticket_id']}.json"
    path.write_text(json.dumps({"ticket": ticket, "delivery": "local draft only, not sent"}, indent=2), encoding="utf-8")
    try:
        shown = path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        shown = str(path)
    return {"created": True, "ticket": ticket, "file": shown, "sent": False}


# ---------------------------------------------------------------- tools for the model


def make_tools(ctx: SessionContext) -> list[StructuredTool]:
    """Build the three helpdesk tools bound to one application-chosen session."""

    def find_instructions_tool(topic: str) -> str:
        """Look up the local helpdesk instructions for a topic: "wifi" or "password"."""
        return json.dumps(find_instructions(topic))

    def check_service_status_tool(service: str) -> str:
        """Check whether a demo service is operational, has an outage, or its status is unknown.

        service: "wifi" for Wi-Fi problems, "account_recovery" for password problems.
        """
        return json.dumps(check_service_status(service, ctx.status_profile))

    def prepare_ticket_tool(
        category: str,
        summary: str,
        steps_tried: list[str],
        service_status: StatusValue = "not_checked",
        reference_ids: list[str] | None = None,
    ) -> str:
        """Save a LOCAL ticket draft (nothing is sent).

        Only use details the user actually stated. category: "wifi" or "password".
        summary: the user's problem. steps_tried: the steps the user said they tried.
        service_status: the status returned by check_service_status in this conversation,
        or "not_checked" if it was not checked. reference_ids: instruction ids used, e.g. GUIDE-WIFI.
        """
        try:
            result = prepare_ticket(
                category=category,
                summary=summary,
                steps_tried=steps_tried,
                user_id=ctx.user_id,
                thread_id=ctx.thread_id,
                status_profile=ctx.status_profile,
                service_status=service_status,
                reference_ids=reference_ids,
                ticket_dir=ctx.ticket_dir,
            )
        except TicketError as exc:
            result = {"created": False, "error": str(exc)}
        return json.dumps(result)

    return [
        StructuredTool.from_function(find_instructions_tool, name="find_instructions"),
        StructuredTool.from_function(check_service_status_tool, name="check_service_status"),
        StructuredTool.from_function(prepare_ticket_tool, name="prepare_ticket"),
    ]
