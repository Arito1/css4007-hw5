"""Part 3: conversation memory (checkpointer) and user memory (store)."""

import json
import subprocess
import sys

from helpdesk.data import PROJECT_ROOT
from helpdesk.memory import Storage, reset_storage


def test_same_thread_sees_earlier_messages(open_session):
    session = open_session(thread="refer")
    session.send("I cannot connect to Wi-Fi.")
    result = session.send("I already tried that.")
    # human, USER_MEMORY system note, AI tool request, tool result, AI answer
    assert result.trace["conversation_memory_read"]["messages_loaded_from_checkpoint"] == 5
    assert "GUIDE-WIFI" in result.reply


def test_conversation_survives_reopening_storage(open_session, storage_dir):
    store = Storage(storage_dir)
    open_session(thread="restart-a", storage=store).send(
        "My issue is Wi-Fi. I enabled it and tried reconnecting, but it still fails."
    )
    store.close()  # simulate closing the program
    store = Storage(storage_dir)
    result = open_session(thread="restart-a", storage=store).send("Which problem and steps did we discuss?")
    store.close()
    assert result.trace["conversation_memory_read"]["messages_loaded_from_checkpoint"] > 0
    assert "Wi-Fi" in result.reply and "Tried reconnecting" in result.reply


def test_preference_survives_restart_and_is_shared_across_threads(open_session, storage_dir):
    store = Storage(storage_dir)
    first = open_session(thread="pref-1", storage=store).send(
        "Please remember that I prefer replies in Kazakh. I have a Wi-Fi problem."
    )
    assert first.trace["sources"]["user_memory_written"] == [{"language": "Kazakh"}]
    store.close()
    store = Storage(storage_dir)
    second = open_session(thread="pref-2", storage=store).send("Which language did I ask you to use?")
    store.close()
    assert second.trace["conversation_memory_read"]["messages_loaded_from_checkpoint"] == 0  # new thread, no replay
    assert second.trace["sources"]["user_memory_read"] == {"language": "Kazakh"}
    assert "Kazakh" in second.reply


def test_users_do_not_share_preferences_or_conversations(open_session, storage_dir):
    store = Storage(storage_dir)
    open_session(user="demo-user-a", thread="shared-name", storage=store).send(
        "Please remember that I prefer replies in Kazakh. I have a Wi-Fi problem."
    )
    # Same thread *name* on purpose: it must still be a different conversation.
    result = open_session(user="demo-user-b", thread="shared-name", storage=store).send(
        "Have I told you a preferred language or a previous problem?"
    )
    assert result.trace["sources"]["user_memory_read"] == {}
    assert result.trace["conversation_memory_read"]["messages_loaded_from_checkpoint"] == 0
    assert "Kazakh" not in result.reply
    assert store.get_preferences("demo-user-b") == {}
    assert store.get_preferences("demo-user-a")["language"] == "Kazakh"
    store.close()


def test_new_thread_for_same_user_has_separate_history(open_session, storage_dir):
    store = Storage(storage_dir)
    open_session(thread="one", storage=store).send("I cannot connect to Wi-Fi.")
    other = open_session(thread="two", storage=store)
    assert other.history() == []
    store.close()


def test_reset_deletes_both_databases(storage_dir):
    with Storage(storage_dir) as store:
        store.save_preference("demo-user-a", "language", "Kazakh")
    reset_storage(storage_dir)
    with Storage(storage_dir) as store:
        assert store.get_preferences("demo-user-a") == {}


def _chat(storage, thread, message, log):
    """Run the real CLI in a NEW Python process (a true restart)."""
    subprocess.run(
        [sys.executable, "-m", "helpdesk", "chat", "--model", "fake", "--user", "demo-user-a", "--thread", thread,
         "--storage", str(storage), "-m", message, "--log", str(log)],
        cwd=PROJECT_ROOT, check=True, capture_output=True,
    )
    return json.loads(log.read_text(encoding="utf-8"))


def test_memory_survives_a_real_process_restart(tmp_path):
    storage = tmp_path / "storage"
    first = _chat(storage, "proc", "Please remember that I prefer replies in Kazakh. My issue is Wi-Fi. "
                  "I enabled it and tried reconnecting, but it still fails.", tmp_path / "1.json")
    second = _chat(storage, "proc", "Which problem and steps did we discuss?", tmp_path / "2.json")
    assert first["process_pid"] != second["process_pid"]
    turn = second["turns"][0]
    assert turn["conversation_memory_read"]["messages_loaded_from_checkpoint"] > 0
    assert turn["sources"]["user_memory_read"] == {"language": "Kazakh"}
    assert "Tried reconnecting" in turn["reply"]
