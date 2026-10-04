"""FastAPI app factory (loopback admin listener, 127.0.0.1:8444) (§10.1, ADR-014).

Implements the WP-08 admin surface (M2) per §22.2 "(+ admin API)":
Pairing Mode open/pending/approve/deny, device list/revoke, TLS rotate.

ADR-014 (normative): `127.0.0.1:8444` (HTTP), **per-install admin token
file**, **strict `Host` check** (anti DNS-rebinding), **no CORS** — never
reachable from LAN/Tailnet (the listener binds loopback AND the Host
middleware rejects rebinding attempts, §17.13 TC-SEC-06).

§17.6 secret matrix: the admin token lives in `admin.token` (owner-only,
0600) and must never appear in URLs/query strings — the only accepted
transport is the `Authorization: Bearer` header compared constant-time.

Route names beyond the spec-named `POST /admin/tls/rotate` (§17.5) are
[DESIGN]: §15.4/§15.6 name the operator ACTIONS (open pairing, pending
device + SAS, approve, deny, devices, revoke) without fixing paths; they are
recorded in docs/OPEN_QUESTIONS.md (QUESTION-103) and are loopback-only
surface, so they can be renamed without contract impact.
"""

from __future__ import annotations

import hmac
import secrets
import stat
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from localmesh_agent.api.errors import mesh_error_handler
from localmesh_agent.core.errors import MeshError
from localmesh_agent.observability.logging import get_logger
from localmesh_agent.security.pairing import PairingError, SessionState

log = get_logger("admin")

ADMIN_TOKEN_FILENAME = "admin.token"
ADMIN_TOKEN_BYTES = 32  # CSPRNG 256-bit per-install token (ADR-014)

# ADR-014 "strict Host check": only these Host headers are accepted
# (loopback with the admin port appended by the caller at wiring time).
_LOOPBACK_HOST_SUFFIXES = ("127.0.0.1", "localhost", "[::1]")


def load_or_create_admin_token(data_dir: Path) -> str:
    """Per-install admin token (ADR-014): create once, persist owner-only."""
    path = data_dir / ADMIN_TOKEN_FILENAME
    if path.exists():
        token = path.read_text(encoding="utf-8").strip()
        if not token:
            raise RuntimeError(f"{path} exists but is empty; delete it to regenerate.")
        return token
    token = secrets.token_urlsafe(ADMIN_TOKEN_BYTES)
    path.write_text(token + "\n", encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600 (§17.6: owner-only)
    return token


async def _envelope(request: Request, error: MeshError) -> JSONResponse:
    """§13.4 envelope for admin errors too (consistency; loopback-only)."""
    request.state.mesh_request_id = getattr(request.state, "mesh_request_id", "admin")
    return await mesh_error_handler(request, error)  # type: ignore[arg-type, return-value]


def create_admin_app(
    *,
    pairing: Any,
    devices: Any,
    tls_rotate: Callable[[], str],
    admin_token: str,
    admin_port: int,
) -> FastAPI:
    """Admin app factory (§10.5: all state created here; no globals).

    `pairing`/`devices` are the WP-08 services; `tls_rotate` performs §17.5
    Rotate (explicit only) and returns the NEW SPKI pin.
    """
    app = FastAPI(title="LocalMesh Agent Admin", version="0.1.0", docs_url=None, redoc_url=None)
    app.state.admin_token = admin_token
    app.add_exception_handler(MeshError, _envelope)  # type: ignore[arg-type]

    allowed_hosts = {f"{suffix}:{admin_port}" for suffix in _LOOPBACK_HOST_SUFFIXES}

    @app.middleware("http")
    async def admin_guard(request: Request, call_next: Callable[[Request], Awaitable[Any]]) -> Any:
        # 1. Strict Host check (ADR-014, anti DNS-rebinding / TC-SEC-06).
        host = request.headers.get("Host", "")
        if host not in allowed_hosts:
            return JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "code": "FORBIDDEN_SCOPE",
                        "message": "Admin listener is loopback-only (ADR-014).",
                        "retryable": False,
                        "request_id": getattr(request.state, "mesh_request_id", None),
                        "details": {},
                    }
                },
            )
        # 2. Admin token — header ONLY, constant-time compare (§17.6).
        header = request.headers.get("Authorization", "")
        expected = f"Bearer {admin_token}"
        if not hmac.compare_digest(header.encode("utf-8"), expected.encode("utf-8")):
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "code": "AUTH_REQUIRED",
                        "message": "Admin token required (Authorization: Bearer).",
                        "retryable": False,
                        "request_id": getattr(request.state, "mesh_request_id", None),
                        "details": {},
                    }
                },
            )
        return await call_next(request)

    # -- pairing (§15.4 operator flow) ----------------------------------------

    @app.post("/admin/pair/open")
    async def pair_open() -> dict[str, object]:
        try:
            opened = pairing.open()
        except PairingError as error:
            raise MeshError(error.code.value, str(error)) from None
        # §17.4: the QR contains the only intentional secret exposure — it is
        # returned here for LOCAL rendering and never logged (§17.6).
        return {"pair_id": opened.pair_id, "qr": opened.qr, "expires_in": opened.expires_in}

    @app.get("/admin/pair/pending")
    async def pair_pending() -> dict[str, object]:
        state, pending = pairing.pending()
        result: dict[str, object] = {"state": state.value}
        if state is SessionState.CLAIMED and pending is not None:
            result["device_name"] = pending.name
            result["platform"] = pending.platform
            result["sas"] = pending.sas  # shown to the operator (§15.4)
        return result

    @app.post("/admin/pair/approve")
    async def pair_approve() -> dict[str, str]:
        try:
            device_id = pairing.approve()
        except PairingError as error:
            raise MeshError(error.code.value, str(error)) from None
        return {"status": "approved", "device_id": device_id}

    @app.post("/admin/pair/deny")
    async def pair_deny() -> dict[str, str]:
        try:
            pairing.deny()
        except PairingError as error:
            raise MeshError(error.code.value, str(error)) from None
        return {"status": "denied"}

    @app.post("/admin/pair/close")
    async def pair_close() -> dict[str, str]:
        """Operator closes Pairing Mode (§15.2 OPEN → CLOSED)."""
        pairing.close()
        return {"status": "closed"}

    # -- devices (§15.6) -------------------------------------------------------

    @app.get("/admin/devices")
    async def admin_devices() -> dict[str, object]:
        # §14.1 fields for the operator — the raw DER public key is NOT
        # operator-display data (and would not JSON-serialize); it stays in
        # the store only.
        rows = [
            {k: v for k, v in device.items() if k != "public_key_spki"} for device in devices.list()
        ]
        return {"devices": rows}

    @app.post("/admin/devices/{device_id}/revoke")
    async def admin_revoke(device_id: str) -> dict[str, object]:
        revoked, cancelled = devices.revoke(device_id)
        if not revoked:
            raise MeshError("INVALID_REQUEST", "Unknown device.", status_override=404)
        return {"status": "revoked", "device_id": device_id, "cancelled_requests": cancelled}

    # -- TLS identity (§17.5: explicit rotate only) ----------------------------

    @app.post("/admin/tls/rotate")
    async def admin_tls_rotate() -> dict[str, str]:
        new_pin = tls_rotate()
        return {"spki_pin": new_pin, "note": "Phones must re-pair (PIN_MISMATCH, §17.5)."}

    return app
