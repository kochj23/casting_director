"""Shared fixtures: a server on a free port with a LOCAL store (never the real Games DB) and the rules brain
(never a real model), so the suite is offline, fast and deterministic."""
import tempfile
import threading
from pathlib import Path

import pytest

from nova.server import ROLES, make_server
from nova.store import GameStore


@pytest.fixture
def store(tmp_path):
    return GameStore(root=tmp_path, remote=False)


@pytest.fixture
def server(store):
    store.set_setting("brains", {r: {"backend": "rules"} for r in ROLES})
    srv = make_server(port=0, store=store)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", srv
    srv.shutdown()


def pytest_configure(config):
    for m in ("unit", "functional", "security", "integration", "performance", "retry", "frame"):
        config.addinivalue_line("markers", f"{m}: test category")
