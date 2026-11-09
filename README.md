# HW5: University IT helpdesk with LangGraph

CSS-4007 Artificial Intelligence. The original assignment brief is in [ASSIGNMENT.md](ASSIGNMENT.md).
My explanations, drawings and results are in [SUBMISSION.md](SUBMISSION.md).

This is a terminal helpdesk for a **fictional** university. It uses only the JSON files in `data/`.
It connects to no real system and never sends a ticket. It only saves local JSON drafts.

| Part | What | Code |
| --- | --- | --- |
| 1 | Rule-based graph, no LLM: `read_request` → `wifi_help` / `password_help` / `other_help` (+ `clarify_problem` variant) | [helpdesk/part1.py](helpdesk/part1.py) |
| 2 | Claude chooses tools: `find_instructions`, `check_service_status`, `prepare_ticket`, with a loop limit | [helpdesk/tools.py](helpdesk/tools.py), [helpdesk/agent.py](helpdesk/agent.py) |
| 3 | Conversation memory (LangGraph `SqliteSaver`) and user memory (LangGraph `SqliteStore`) | [helpdesk/memory.py](helpdesk/memory.py) |
| 4 | CLI, scenario runner, tests with a fake model, GitHub Actions | [helpdesk/cli.py](helpdesk/cli.py), [tests/](tests), [.github/workflows/tests.yml](.github/workflows/tests.yml) |

## Requirements

- **Python 3.13** (tested with 3.13.15 on Windows 11; CI uses Python 3.13 on Ubuntu).
- Exact package versions are in [requirements.txt](requirements.txt): LangGraph 1.2.20,
  langgraph-checkpoint-sqlite 3.1.3, langchain-anthropic 1.7.10, anthropic 2.6.0.
- Model provider: **Anthropic Claude** through `langchain-anthropic` (the starter's OpenAI adapter
  was replaced; the course allowed the Claude API). Default model: `claude-opus-5-5`.

## Install

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

macOS / Linux:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

> On Windows 11 with Smart App Control, the newest `ormsgpack` and `jiter` wheels were blocked
> ("DLL load failed ... Application Control policy"). That is why `requirements.txt` pins them
> one release back.

## Configure the model (Parts 2–3 only)

Copy `.env.example` to `.env` and put in your key. `.env` is ignored by git.

```bash
cp .env.example .env
```

```ini
ANTHROPIC_API_KEY=sk-ant-...
MODEL_NAME=claude-opus-5-5     # or claude-sonnet-5-5 / claude-haiku-5-5
HELPDESK_EFFORT=medium
```

Part 1, the direct tool calls and all tests need **no key**. Every model command also accepts
`--model fake`, which uses a scripted rule-based stand-in ([helpdesk/fake_model.py](helpdesk/fake_model.py)).
It is **not an LLM** and its logs are always labelled `FAKE`.

## Run

All commands run from the repository root.

```bash
# Part 1: rule-based graph (no key)
python -m helpdesk part1 "I cannot connect to Wi-Fi."
python -m helpdesk part1 "My Wi-Fi password does not work." --variant original
python -m helpdesk part1 "My Wi-Fi password does not work." --variant with_clarification
python -m helpdesk graph part1            # Mermaid drawing; also: part1-clarify, agent

# Part 2: tools called directly, without the agent (no key)
python -m helpdesk tool find_instructions wifi
python -m helpdesk tool check_service_status wifi --status wifi_outage
python -m helpdesk tool prepare_ticket wifi --summary "Campus-Demo will not connect" --step "Enabled Wi-Fi" --service-status not_checked

# Parts 2-3: chat with Claude. The application chooses the user, thread and status snapshot.
python -m helpdesk chat --user demo-user-a --thread t1 --status normal
python -m helpdesk chat --user demo-user-a --thread t1 -m "I cannot connect to Wi-Fi." -m "I already tried that."
```

Status snapshots: `normal`, `wifi_outage`, `recovery_outage`, `status_unavailable`.
In interactive mode, type `/history` to see the saved conversation and `/quit` to exit.
Add `--trace` to print the full JSON trace of each turn, and `--log file.json` to save it.

### Run the supplied scenarios S01–S14

```bash
python -m helpdesk scenarios --model anthropic     # real Claude run -> outputs/claude/
python -m helpdesk scenarios --model fake          # offline dry run -> outputs/fake-model/
python -m helpdesk scenarios --model anthropic --only S07 S08
```

The runner follows `data/scenarios.json`:

- If `reset_before` is true, it deletes the scenario storage (`local-storage/scenarios/`) first.
- Every group of messages between two `restart_process` events runs in a **new Python process**
  against the same storage. Each log records the process IDs.

It writes:

| File | Content |
| --- | --- |
| `outputs/part1/S01.json` … `S05.json` | Part 1 traces: nodes in order and the state after each node |
| `outputs/<model>/S06.json` … `S14.json` | Nodes, model tool requests, tool results, memory reads and writes, reply |
| `outputs/<model>/D01.json` | Extra Part 3 demo: "I already tried that" |
| `outputs/<model>/SUMMARY.md` | One-line summary per scenario |
| `outputs/<model>/tickets/` | Ticket drafts created during the run |
| `outputs/direct-tool-calls.json` | Each tool called directly, without a model |

## Where memory is saved and how to clear it

The folder is `HELPDESK_STORAGE_DIR` (default `local-storage/`, ignored by git):

| File | What it holds |
| --- | --- |
| `local-storage/conversations.sqlite` | LangGraph checkpoints: the full state of every conversation, keyed by `user_id::thread_id` |
| `local-storage/user_memory.sqlite` | LangGraph store: long-term user preferences, namespace `("user_memory", user_id)` |
| `local-storage/scenarios/` | The same two files, used only by the scenario runner |

Clear the memory:

```bash
python -m helpdesk reset                                   # local-storage/
python -m helpdesk reset --storage local-storage/scenarios
```

Or just delete the folder. Ticket drafts from `chat` go to `outputs/tickets/`
(set `HELPDESK_TICKET_DIR` to change this).

## Tests

```bash
python -m pytest -v
```

51 tests. They use temporary folders and the fake model, so they need no API key.
The same command runs in GitHub Actions on every push ([workflow](.github/workflows/tests.yml)).
[SUBMISSION.md](SUBMISSION.md#part-4--running-and-checking-my-work) lists what each test file catches.

## Privacy

- Only invented identifiers are used (`demo-user-a`, `demo-user-b`).
- No passwords are requested. `prepare_ticket` refuses text that looks like a password or code.
- API keys stay in `.env`. Memory databases stay in `local-storage/`. Both are ignored by git.
