"""Terminal entry point: ``python -m helpdesk <command>``.

Commands
--------
part1      run the rule-based Part 1 graph on one message and print its trace
chat       talk to the model-and-tools helpdesk (interactive, or with -m messages)
tool       call one helpdesk tool directly, without the agent or a model
graph      print a Mermaid drawing of a graph
reset      delete the saved conversation and user memory
scenarios  run S01-S14 from data/scenarios.json and save logs in outputs/
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

from .data import PROJECT_ROOT, scenarios
from .tools import DEFAULT_TICKET_DIR

STATUS_PROFILES = ["normal", "wifi_outage", "recovery_outage", "status_unavailable"]


def _json(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json(obj) + "\n", encoding="utf-8")


def _rel(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


# ---------------------------------------------------------------- part1


def cmd_part1(args) -> None:
    from .part1 import run_with_trace

    trace = run_with_trace(args.message, args.variant)
    print("route:", " -> ".join(trace["route"]))
    for step in trace["steps"]:
        print(f"  [{step['node']}] update={_json(step['update'])}")
    print("reply:", trace["reply"])
    if args.log:
        _write(Path(args.log), trace)


# ---------------------------------------------------------------- chat


def print_turn(result, show_trace: bool) -> None:
    trace = result.trace
    mem = trace["conversation_memory_read"]
    print(f"  · conversation memory: {mem['messages_loaded_from_checkpoint']} earlier messages loaded")
    print(f"  · user memory read: {trace['sources']['user_memory_read'] or 'nothing saved'}")
    for req in trace["model_tool_requests"]:
        print(f"  · model requested {req['tool']}({json.dumps(req['args'], ensure_ascii=False)})")
    for res in trace["tool_results"]:
        r = res["result"]
        short = {k: r[k] for k in ("status", "instruction_id", "file", "created", "error", "saved") if isinstance(r, dict) and k in r}
        print(f"  · tool {res['tool']} returned {json.dumps(short, ensure_ascii=False)}")
    print("  · route:", " -> ".join(trace["route"]), "| loop limit reached:", trace["loop_limit_reached"])
    if show_trace:
        print(_json(trace))
    print(f"Helpdesk: {result.reply}\n")


def cmd_chat(args) -> None:
    from .agent import HelpdeskSession, make_model
    from .memory import Storage
    from .tools import SessionContext

    model = make_model(args.model)
    ticket_dir = Path(os.environ.get("HELPDESK_TICKET_DIR", DEFAULT_TICKET_DIR))
    ctx = SessionContext(args.user, args.thread, args.status, ticket_dir)
    turns = []
    with Storage(args.storage) as storage:
        session = HelpdeskSession(ctx, model, storage, args.max_tool_rounds)
        print(f"[user={ctx.user_id} thread={ctx.thread_id} status={ctx.status_profile} model={args.model} storage={_rel(storage.dir)}]")
        print(f"[{len(session.history())} messages already saved in this conversation]\n")

        def handle(text: str) -> None:
            print(f"You: {text}")
            result = session.send(text)
            turns.append(result.trace)
            print_turn(result, args.trace)

        if args.message:
            for text in args.message:
                handle(text)
        else:
            print("Type a message. Commands: /history, /quit\n")
            while True:
                try:
                    text = input("You: ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if not text:
                    continue
                if text in ("/quit", "/exit"):
                    break
                if text == "/history":
                    for m in session.history():
                        print(f"  {m.type}: {str(m.content)[:200]}")
                    continue
                result = session.send(text)
                turns.append(result.trace)
                print_turn(result, args.trace)
    if args.log:
        _write(Path(args.log), {"process_pid": os.getpid(), "turns": turns})


# ---------------------------------------------------------------- tool


def cmd_tool(args) -> None:
    from .tools import TicketError, check_service_status, find_instructions, prepare_ticket

    if args.name == "find_instructions":
        result = find_instructions(args.topic)
    elif args.name == "check_service_status":
        result = check_service_status(args.topic, args.status)
    else:
        try:
            result = prepare_ticket(
                category=args.topic,
                summary=args.summary or "",
                steps_tried=args.step or [],
                user_id=args.user,
                thread_id=args.thread,
                status_profile=args.status,
                service_status=args.service_status,
                reference_ids=args.ref or [],
                ticket_dir=Path(os.environ.get("HELPDESK_TICKET_DIR", DEFAULT_TICKET_DIR)),
            )
        except TicketError as exc:
            result = {"created": False, "error": str(exc)}
    print(_json(result))


# ---------------------------------------------------------------- graph / reset


def cmd_graph(args) -> None:
    if args.which in ("part1", "part1-clarify"):
        from .part1 import mermaid

        print(mermaid("original" if args.which == "part1" else "with_clarification"))
        return
    from .agent import build_agent_graph
    from .fake_model import FakeHelpdeskModel
    from .memory import Storage
    from .tools import SessionContext

    with tempfile.TemporaryDirectory() as tmp, Storage(tmp) as storage:
        graph = build_agent_graph(FakeHelpdeskModel(), SessionContext("demo", "demo"), storage)
        print(graph.get_graph().draw_mermaid())


def cmd_reset(args) -> None:
    from .memory import reset_storage

    print(f"Deleted conversation and user memory in {_rel(reset_storage(args.storage))}")


# ---------------------------------------------------------------- scenarios


def cmd_segment(args) -> None:
    """Internal: run a list of message events in ONE process (between two restarts)."""
    from .agent import HelpdeskSession, make_model
    from .memory import Storage
    from .tools import SessionContext

    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    model = make_model(spec["model"])
    out = []
    with Storage(spec["storage"]) as storage:
        for event in spec["events"]:
            ctx = SessionContext(event["user_id"], event["thread_id"], spec["status_profile"], Path(spec["ticket_dir"]))
            result = HelpdeskSession(ctx, model, storage, spec["max_tool_rounds"]).send(event["message"])
            out.append({"action": "message", "process_pid": os.getpid(), "trace": result.trace})
    Path(args.result).write_text(_json(out), encoding="utf-8")


def run_part1_scenario(sc: dict, command: str) -> dict:
    from .part1 import run_with_trace

    variant = sc.get("graph_variant", "original")
    events = []
    for ev in sc["events"]:
        events.append({"action": "message", "process_pid": os.getpid(), "user_id": ev["user_id"], "thread_id": ev["thread_id"],
                       "trace": run_with_trace(ev["message"], variant)})
    return {"scenario": sc["id"], "title": sc["title"], "part": 1, "command": command, "status_profile": sc["status_profile"],
            "graph_variant": variant, "model": "none (Part 1 has no model)", "events": events,
            "final_reply": events[-1]["trace"]["reply"], "ticket_files": [], "loop_limit_reached": False}


def run_agent_scenario(sc: dict, args, command: str, ticket_dir: Path) -> dict:
    from .memory import reset_storage

    storage = Path(args.storage)
    if sc.get("reset_before"):
        reset_storage(storage)
    segments: list[list[dict]] = [[]]
    for ev in sc["events"]:
        if ev["action"] == "restart_process":
            segments.append([])
        else:
            segments[-1].append(ev)
    events: list[dict] = []
    previous_pid = None
    for i, seg in enumerate(segments):
        with tempfile.TemporaryDirectory() as tmp:
            spec, result = Path(tmp) / "spec.json", Path(tmp) / "result.json"
            spec.write_text(_json({"model": args.model, "storage": str(storage), "status_profile": sc["status_profile"],
                                   "ticket_dir": str(ticket_dir), "max_tool_rounds": args.max_tool_rounds, "events": seg}),
                            encoding="utf-8")
            # A NEW Python process for every segment: a restart really terminates the program.
            proc = subprocess.run([sys.executable, "-m", "helpdesk", "_segment", str(spec), str(result)],
                                  cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8")
            if proc.returncode != 0:
                raise SystemExit(f"{sc['id']} segment {i} failed:\n{proc.stderr}")
            seg_events = json.loads(result.read_text(encoding="utf-8"))
        if i > 0:
            events.append({"action": "restart_process", "preserve_local_storage": True,
                           "previous_pid": previous_pid, "next_pid": seg_events[0]["process_pid"] if seg_events else None})
        events.extend(seg_events)
        previous_pid = seg_events[-1]["process_pid"] if seg_events else previous_pid
    traces = [e["trace"] for e in events if e["action"] == "message"]
    return {"scenario": sc["id"], "title": sc["title"], "part": sc["part"], "command": command,
            "status_profile": sc["status_profile"], "storage_dir": _rel(storage), "reset_before": sc.get("reset_before"),
            "model": traces[0]["model"] if traces else args.model, "events": events,
            "final_reply": traces[-1]["reply"] if traces else None,
            "ticket_files": [f for t in traces for f in t["ticket_files"]],
            "loop_limit_reached": any(t["loop_limit_reached"] for t in traces)}


def _summary_row(log: dict) -> str:
    def cell(text: str) -> str:
        return text.replace("|", "\\|").replace("\n", " ")

    steps = []
    for ev in log["events"]:
        if ev["action"] == "restart_process":
            steps.append(f"**restart** (pid {ev['previous_pid']}→{ev['next_pid']})")
            continue
        t = ev["trace"]
        if log["part"] == 1:
            steps.append(" → ".join(t["route"]))
        else:
            tools = ", ".join(f"{r['tool']}" for r in t["model_tool_requests"]) or "no tools"
            steps.append(f"{t['user_id']}/{t['thread_id']}: {tools}")
    reply = (log["final_reply"] or "")[:160]
    return f"| {log['scenario']} | {log['status_profile']} | {cell('; '.join(steps))} | {cell(reply)} | {', '.join(log['ticket_files']) or '-'} | {log['loop_limit_reached']} |"


# Extra demonstrations required by the brief but not in data/scenarios.json.
EXTRA_DEMOS = [
    {
        "id": "D01",
        "part": 3,
        "title": "Part 3 situation 1 (extra, not in scenarios.json): 'I already tried that' refers to earlier messages",
        "status_profile": "normal",
        "reset_before": True,
        "events": [
            {"action": "message", "user_id": "demo-user-a", "thread_id": "refer-a", "message": "I cannot connect to Wi-Fi."},
            {"action": "message", "user_id": "demo-user-a", "thread_id": "refer-a", "message": "I already tried that."},
        ],
    }
]


def direct_tool_calls(ticket_dir: Path) -> dict:
    """Part 2: every tool called directly, without the agent or any model."""
    from .tools import TicketError, check_service_status, find_instructions, prepare_ticket

    calls = [
        ("find_instructions", {"topic": "wifi"}, lambda: find_instructions("wifi")),
        ("find_instructions", {"topic": "password"}, lambda: find_instructions("password")),
        ("find_instructions", {"topic": "printer"}, lambda: find_instructions("printer")),
    ]
    for profile in STATUS_PROFILES:
        calls.append(("check_service_status", {"service": "wifi", "status_profile": profile},
                      lambda p=profile: check_service_status("wifi", p)))
    ticket_args = dict(category="wifi", summary="Campus-Demo still will not connect.",
                       steps_tried=["Enabled Wi-Fi", "Forgot the saved network"], user_id="demo-user-a",
                       thread_id="direct-tool-call", status_profile="normal", service_status="operational",
                       reference_ids=["GUIDE-WIFI"], ticket_dir=ticket_dir)
    missing_args = {**ticket_args, "steps_tried": []}

    def safe(kwargs):
        try:
            return prepare_ticket(**kwargs)
        except TicketError as exc:
            return {"created": False, "error": str(exc)}

    calls.append(("prepare_ticket", {k: v for k, v in ticket_args.items() if k != "ticket_dir"}, lambda: safe(ticket_args)))
    calls.append(("prepare_ticket", {k: v for k, v in missing_args.items() if k != "ticket_dir"}, lambda: safe(missing_args)))
    return {"description": "Direct tool calls, no agent and no model (python -m helpdesk scenarios)",
            "calls": [{"tool": name, "args": a, "result": fn()} for name, a, fn in calls]}


def cmd_scenarios(args) -> None:
    import shutil

    out = Path(args.out or PROJECT_ROOT / "outputs" / ("fake-model" if args.model == "fake" else "claude"))
    ticket_dir = out / "tickets"
    selected = [s for s in scenarios() if not args.only or s["id"] in args.only]
    selected += [d for d in EXTRA_DEMOS if not args.only or d["id"] in args.only]
    if not args.only:
        direct_dir = PROJECT_ROOT / "outputs" / "direct-tool-tickets"
        for folder in (ticket_dir, direct_dir):
            shutil.rmtree(folder, ignore_errors=True)  # a full run starts with no old drafts
        _write(PROJECT_ROOT / "outputs" / "direct-tool-calls.json", direct_tool_calls(direct_dir))
    command = "python -m helpdesk scenarios " + " ".join(sys.argv[2:])
    logs = []
    for sc in selected:
        if sc["part"] == 1:
            log = run_part1_scenario(sc, command)
            path = PROJECT_ROOT / "outputs" / "part1" / f"{sc['id']}.json"
        else:
            log = run_agent_scenario(sc, args, command, ticket_dir)
            path = out / f"{sc['id']}.json"
        _write(path, log)
        logs.append(log)
        print(f"{sc['id']}: {(log['final_reply'] or '')[:110]!r} -> {_rel(path)}")
    if not args.only:
        header = ("| Scenario | Snapshot | Route / tools per event | Final reply (start) | Tickets | Loop limit |\n"
                  "| --- | --- | --- | --- | --- | --- |")
        model = next((l["model"] for l in logs if l["part"] != 1), args.model)
        text = f"# Scenario run summary\n\nModel: {model}\n\nCommand: `{command}`\n\n{header}\n" + "\n".join(map(_summary_row, logs)) + "\n"
        (out / "SUMMARY.md").write_text(text, encoding="utf-8")
        print(f"summary -> {_rel(out / 'SUMMARY.md')}")


# ---------------------------------------------------------------- main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m helpdesk", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    storage_default = os.environ.get("HELPDESK_STORAGE_DIR", "local-storage")

    p = sub.add_parser("part1", help="run the Part 1 graph on one message")
    p.add_argument("message")
    p.add_argument("--variant", choices=["original", "with_clarification"], default="original")
    p.add_argument("--log", help="save the trace as JSON")
    p.set_defaults(func=cmd_part1)

    p = sub.add_parser("chat", help="talk to the model-and-tools helpdesk")
    p.add_argument("--user", required=True, help="invented user id, e.g. demo-user-a")
    p.add_argument("--thread", required=True, help="conversation id, e.g. t1")
    p.add_argument("--status", choices=STATUS_PROFILES, default="normal", help="service-status snapshot")
    p.add_argument("--model", choices=["anthropic", "fake"], default=os.environ.get("HELPDESK_MODEL", "anthropic"))
    p.add_argument("--storage", default=storage_default)
    p.add_argument("--max-tool-rounds", type=int, default=4)
    p.add_argument("-m", "--message", action="append", help="send this message (repeatable); omit for interactive mode")
    p.add_argument("--trace", action="store_true", help="print the full JSON trace of every turn")
    p.add_argument("--log", help="save all turn traces as JSON")
    p.set_defaults(func=cmd_chat)

    p = sub.add_parser("tool", help="call one tool directly")
    p.add_argument("name", choices=["find_instructions", "check_service_status", "prepare_ticket"])
    p.add_argument("topic", help="topic (find_instructions), service (check_service_status) or category (prepare_ticket)")
    p.add_argument("--status", choices=STATUS_PROFILES, default="normal")
    p.add_argument("--summary")
    p.add_argument("--step", action="append", help="a step already tried (repeatable)")
    p.add_argument("--service-status", default="not_checked", choices=["operational", "outage", "unknown", "not_checked"])
    p.add_argument("--ref", action="append")
    p.add_argument("--user", default="demo-user-a")
    p.add_argument("--thread", default="direct-tool-call")
    p.set_defaults(func=cmd_tool)

    p = sub.add_parser("graph", help="print a Mermaid diagram")
    p.add_argument("which", choices=["part1", "part1-clarify", "agent"])
    p.set_defaults(func=cmd_graph)

    p = sub.add_parser("reset", help="delete saved memory")
    p.add_argument("--storage", default=storage_default)
    p.set_defaults(func=cmd_reset)

    p = sub.add_parser("scenarios", help="run S01-S14 and save logs")
    p.add_argument("--model", choices=["anthropic", "fake"], default=os.environ.get("HELPDESK_MODEL", "anthropic"))
    p.add_argument("--only", nargs="+", metavar="SID")
    p.add_argument("--out", help="log folder (default outputs/claude or outputs/fake-model)")
    p.add_argument("--storage", default=str(Path(storage_default) / "scenarios"))
    p.add_argument("--max-tool-rounds", type=int, default=4)
    p.set_defaults(func=cmd_scenarios)

    p = sub.add_parser("_segment")  # internal, used by `scenarios` for real process restarts
    p.add_argument("spec")
    p.add_argument("result")
    p.set_defaults(func=cmd_segment)
    return parser


def main(argv: list[str] | None = None) -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    load_dotenv(PROJECT_ROOT / ".env")
    args = build_parser().parse_args(argv)
    args.func(args)
