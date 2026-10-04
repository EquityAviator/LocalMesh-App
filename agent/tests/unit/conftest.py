"""Shared unit-test fixtures (WP-04/05)."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from localmesh_agent.store.sqlite import Store


@pytest.fixture()
def store(tmp_path: Path) -> Iterator[Store]:
    """Fresh SQLite store per test (WP-04 §14.1 migration applied)."""
    s = Store(tmp_path / "agent.db")
    yield s
    s.close()
