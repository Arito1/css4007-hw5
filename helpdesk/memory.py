"""Part 3: where memory lives.

Two different kinds of memory are stored in two SQLite files under the storage
directory (``HELPDESK_STORAGE_DIR``, default ``local-storage/``):

* ``conversations.sqlite`` - a LangGraph :class:`SqliteSaver` checkpointer.
  It saves the whole graph state (all messages of a conversation, the tool
  results, the counters) after every step, keyed by the checkpoint thread id.
* ``user_memory.sqlite`` - a LangGraph :class:`SqliteStore`.  It holds
  long-term facts about one user (here: the preferred reply language) under
  the namespace ``("user_memory", <user_id>)``.  It is shared by all threads of
  that user and by no other user.

The application, never the model, chooses ``user_id`` and ``thread_id``.
The checkpoint key is ``"<user_id>::<thread_id>"`` so that two users who happen
to type the same thread name still get separate conversations.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.tools import StructuredTool
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.sqlite import SqliteStore

from .data import PROJECT_ROOT

CONVERSATIONS_FILE = "conversations.sqlite"
USER_MEMORY_FILE = "user_memory.sqlite"
PREFERENCES_KEY = "preferences"


def default_storage_dir() -> Path:
    path = Path(os.environ.get("HELPDESK_STORAGE_DIR", "local-storage"))
    return path if path.is_absolute() else PROJECT_ROOT / path


def checkpoint_thread_id(user_id: str, thread_id: str) -> str:
    return f"{user_id}::{thread_id}"


def user_namespace(user_id: str) -> tuple[str, str]:
    return ("user_memory", user_id)


class Storage:
    """Opens the checkpointer and the user-memory store on disk."""

    def __init__(self, storage_dir: Path | str | None = None):
        self.dir = Path(storage_dir) if storage_dir else default_storage_dir()
        self.dir.mkdir(parents=True, exist_ok=True)
        self._conv_conn = sqlite3.connect(self.dir / CONVERSATIONS_FILE, check_same_thread=False)
        self._user_conn = sqlite3.connect(self.dir / USER_MEMORY_FILE, check_same_thread=False, isolation_level=None)
        self.checkpointer = SqliteSaver(self._conv_conn)
        self.checkpointer.setup()
        self.store = SqliteStore(self._user_conn)
        self.store.setup()

    # -- user memory -------------------------------------------------------

    def get_preferences(self, user_id: str) -> dict:
        item = self.store.get(user_namespace(user_id), PREFERENCES_KEY)
        return dict(item.value) if item else {}

    def save_preference(self, user_id: str, name: str, value: str, source_thread: str | None = None) -> dict:
        prefs = self.get_preferences(user_id)
        prefs[name] = value
        prefs["_updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if source_thread:
            prefs["_source_thread"] = source_thread
        self.store.put(user_namespace(user_id), PREFERENCES_KEY, prefs)
        return prefs

    def close(self) -> None:
        self._conv_conn.close()
        self._user_conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def reset_storage(storage_dir: Path | str | None = None) -> Path:
    """Delete both memory databases (conversation and user memory)."""
    path = Path(storage_dir) if storage_dir else default_storage_dir()
    if path.exists():
        shutil.rmtree(path)
    return path


def make_memory_tools(storage: Storage, user_id: str, thread_id: str) -> list[StructuredTool]:
    """The one memory-writing tool.  It is bound to the session's user."""

    def save_user_preference(language: str) -> str:
        """Save the user's preferred reply language in long-term user memory.

        Only call this when the user explicitly asks you to remember a language preference.
        language: the language name in English, e.g. "Kazakh".
        """
        prefs = storage.save_preference(user_id, "language", language.strip(), source_thread=thread_id)
        return json.dumps({"saved": True, "user_memory": {"language": prefs["language"]}})

    return [StructuredTool.from_function(save_user_preference, name="save_user_preference")]
