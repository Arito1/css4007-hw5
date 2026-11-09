import pytest

from helpdesk.agent import HelpdeskSession
from helpdesk.fake_model import FakeHelpdeskModel
from helpdesk.memory import Storage
from helpdesk.tools import SessionContext


@pytest.fixture
def storage_dir(tmp_path):
    return tmp_path / "storage"


@pytest.fixture
def open_session(tmp_path, storage_dir):
    """Factory: open a session with the FAKE model on a temporary storage folder."""
    opened = []

    def _open(user="demo-user-a", thread="t1", status="normal", model=None, storage=None, **kw):
        store = storage or Storage(storage_dir)
        if storage is None:
            opened.append(store)
        ctx = SessionContext(user, thread, status, tmp_path / "tickets")
        return HelpdeskSession(ctx, model or FakeHelpdeskModel(), store, **kw)

    yield _open
    for store in opened:
        store.close()
