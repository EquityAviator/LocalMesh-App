"""Pytest fixtures for the fake-backend self-tests (WP-03).

The servers bind 127.0.0.1:0 (ephemeral, loopback only — SEC-N2 spirit).
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from fake_lmstudio import FakeLMStudio  # noqa: E402
from fake_ollama import FakeOllama  # noqa: E402


@pytest.fixture()
def make_lmstudio() -> Callable[..., FakeLMStudio]:
    servers: list[FakeLMStudio] = []

    def _make(**kwargs: Any) -> FakeLMStudio:
        server = FakeLMStudio(("127.0.0.1", 0), **kwargs)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append(server)
        return server

    yield _make
    for server in servers:
        server.shutdown()
        server.server_close()


@pytest.fixture()
def make_ollama() -> Callable[..., FakeOllama]:
    servers: list[FakeOllama] = []

    def _make(**kwargs: Any) -> FakeOllama:
        server = FakeOllama(("127.0.0.1", 0), **kwargs)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append(server)
        return server

    yield _make
    for server in servers:
        server.shutdown()
        server.server_close()
