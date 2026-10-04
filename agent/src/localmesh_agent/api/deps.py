"""auth dependency, rate-limit dependency (§10.1).

M1 state (§22.1: "dev-insecure loopback listener only"): the public TLS
listener and Device Tokens arrive with WP-07/WP-08 (M2). Until then the API
runs in one of two modes:

- **dev-insecure loopback** (`--dev-insecure-loopback`, §17.9): binds
  127.0.0.1 via HTTP and `get_principal` returns a per-process Device
  identity. This mode is OFF by default (SEC-N6) and is never a release
  configuration.
- **default**: every authenticated request fails closed with 401
  `AUTH_REQUIRED` until token issuance exists (SEC-N4).

Rate limiting (§13.8) applies to token-authenticated milestones; a loopback
in-process limiter arrives with WP-08 where the contract defines it.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from localmesh_agent.core.errors import MeshError


@dataclass(frozen=True)
class Principal:
    """Identity of the caller for one request (M1: dev-loopback Device)."""

    device_id: str
    scopes: frozenset[str]


DEFAULT_SCOPES = frozenset({"models:read", "chat"})  # §13.1 default scopes


def get_principal(request: Request) -> Principal:
    """FastAPI dependency: resolve the caller identity (fail-closed, SEC-N4)."""
    app_state = request.app.state
    if getattr(app_state, "dev_insecure", False):
        return Principal(device_id=str(app_state.dev_device_id), scopes=DEFAULT_SCOPES)
    # No token issuance before WP-08 (M2): fail closed.
    raise MeshError("AUTH_REQUIRED", "Authentication is not available on this listener.")


def require_scope(principal: Principal, scope: str) -> None:
    """Scope gate (§13.1): reject 403 FORBIDDEN_SCOPE when missing."""
    if scope not in principal.scopes:
        raise MeshError("FORBIDDEN_SCOPE", f"Missing required scope: {scope}.")
