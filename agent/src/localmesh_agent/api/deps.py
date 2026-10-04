"""auth dependency, rate-limit dependency (§10.1).

WP-08 state (§22.2 M2): Device Tokens are live (ADR-008). The API runs in
one of two modes:

- **token mode** (default, public TLS listener): `get_principal` verifies the
  `Authorization: Bearer` Device Token via `security.tokens.TokenService`
  (§17.7 authorization matrix; fail-closed, SEC-N4):

  - missing/malformed header          → 401 AUTH_REQUIRED (Appendix D)
  - unknown / revoked token           → 401 AUTH_FAILED (uniform, §17.8 —
    revocation deletes hashes so it is indistinguishable)
  - known hash but past TTL           → 401 TOKEN_EXPIRED (retryable:
    client re-auths once, §15.3)
  - success → Principal(device_id, scopes from the devices row) and the
    Device's last_seen_at is refreshed (§14.1).

- **dev-insecure loopback** (`--dev-insecure-loopback`, §17.9): binds
  127.0.0.1 via HTTP and returns a per-process Device identity. This mode is
  OFF by default (SEC-N6) and is never a release configuration.

Scope enforcement is per-endpoint (`require_scope`, §17.7 "each handler
checks scope server-side; the App UI hiding a control is not authorization").
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from localmesh_agent.core.errors import MeshError
from localmesh_agent.security.tokens import TokenRejection


@dataclass(frozen=True)
class Principal:
    """Identity of the caller for one request (§17.7)."""

    device_id: str
    scopes: frozenset[str]


DEFAULT_SCOPES = frozenset({"models:read", "chat"})  # §13.1 default scopes

_BEARER_PREFIX = "Bearer "


def get_principal(request: Request) -> Principal:
    """FastAPI dependency: resolve the caller identity (fail-closed, SEC-N4)."""
    app_state = request.app.state
    if getattr(app_state, "dev_insecure", False):
        return Principal(device_id=str(app_state.dev_device_id), scopes=DEFAULT_SCOPES)

    header = request.headers.get("Authorization")
    if header is None or not header.startswith(_BEARER_PREFIX):
        raise MeshError("AUTH_REQUIRED", "A Bearer Device Token is required.")
    token = header[len(_BEARER_PREFIX) :].strip()
    if not token:
        raise MeshError("AUTH_REQUIRED", "A Bearer Device Token is required.")

    tokens = getattr(app_state, "tokens", None)
    if tokens is None:  # pragma: no cover - app factory always wires it
        raise MeshError("AUTH_REQUIRED", "Authentication is not available.")
    result = tokens.verify(token)
    if isinstance(result, TokenRejection):
        if result.expired:
            raise MeshError("TOKEN_EXPIRED", "The Device Token has expired; re-authenticate.")
        raise MeshError("AUTH_FAILED", "Authentication failed.")
    if result is None:
        raise MeshError("AUTH_FAILED", "Authentication failed.")

    devices = getattr(app_state, "devices", None)
    if devices is not None:
        devices.touch_last_seen(result.device_id)
    return Principal(
        device_id=result.device_id,
        scopes=frozenset(result.scopes.split()) if result.scopes else frozenset(),
    )


def require_scope(principal: Principal, scope: str) -> None:
    """Scope gate (§17.7): reject 403 FORBIDDEN_SCOPE when missing."""
    if scope not in principal.scopes:
        raise MeshError("FORBIDDEN_SCOPE", f"Missing required scope: {scope}.")
