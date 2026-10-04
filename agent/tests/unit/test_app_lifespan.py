"""App lifecycle construction pin — `create_app` must be warning-free.

The §10.6 startup/shutdown sequence runs through a single FastAPI **lifespan**
handler. The deprecated `@app.on_event` decorators (FastAPI ≥ 0.103) must
never come back: before the migration they emitted 228 suite-wide
DeprecationWarnings (every TestClient app build registered two handlers).

This test fails closed — ANY DeprecationWarning raised while building the
app (decorator registration time for `on_event`) turns into an error.
"""

from __future__ import annotations

import warnings
from pathlib import Path

from localmesh_agent.app import create_app
from localmesh_agent.config import Settings


def test_create_app_emits_no_deprecation_warning(tmp_path: Path) -> None:
    settings = Settings(
        agent={"data_dir": str(tmp_path / "data")},
        mdns={"enabled": False},  # hermetic: no zeroconf sockets at build time
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        app = create_app(settings)
    # Services are on app.state immediately (§10.5), before the lifespan runs.
    assert app.state.agent_id.startswith("ag_")
    assert app.state.spki_pin  # WP-07 pin computed at build time
    assert app.state.mdns is None  # advertiser absent (mDNS disabled)
