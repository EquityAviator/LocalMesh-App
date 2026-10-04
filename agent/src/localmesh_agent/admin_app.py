"""FastAPI app factory (loopback admin listener, 127.0.0.1:8444) (§10.1, ADR-014).

Implements the §13.1 Loopback Admin API verbatim:

    POST /admin/pairing/open|approve|deny|close, GET /admin/pairing,
    GET /admin/devices, PATCH /admin/devices/{id} (scopes, name),
    DELETE /admin/devices/{id}, GET /admin/status, POST /admin/tls/rotate,
    GET /admin/doctor.

Conformance history (QUESTION-103 item 4): WP-08 originally shipped
[DESIGN] route names (`/admin/pair/*`, `POST /admin/devices/{id}/revoke`)
under the reading that §15.4/§15.6 named the operator ACTIONS without
paths — overlooking that §13.1 itself enumerates the paths (line
"Loopback Admin API …"). The spec-named routes are now primary; the
original [DESIGN] names remain as loopback-only aliases (rename-safe per
QUESTION-103 — the owner may drop them with a one-line diff).

ADR-014 (normative): `127.0.0.1:8444` (HTTP), **per-install admin token
file**, **strict `Host` check** (anti DNS-rebinding), **no CORS** — never
reachable from LAN/Tailnet (the listener binds loopback AND the Host
middleware rejects rebinding attempts, §17.13 TC-SEC-06).

Token transport (spec-explicit): the Admin API authenticates with the custom
header **`X-Admin-Token`** (§13.1 "Loopback Admin API (separate listener
`127.0.0.1:8444`, header `X-Admin-Token`)" + §17.13 T-11 "custom header
`X-Admin-Token`"). A drive-by web request cannot set a custom header, so the
custom header is the DNS-rebinding mitigation T-11 names. The token never
appears in URLs/query strings (§17.6) and is compared constant-time.

§17.6 secret matrix: the admin token lives in `admin.token` (owner-only,
0600) and must never be logged.

`GET /admin/doctor` serves the §18.4 findings (WP-13) as JSON. `GET
/admin/metrics` is the §20.1 "optional Prometheus text endpoint on loopback
admin only" (path [DESIGN]; families rendered by observability.metrics).
`GET /admin/status` is spec-named without a detailed contract — the shape is
[DESIGN], composed of Metadata only (§17.6: no tokens, no full pins, no
Content) and injected as `status_fn` so this layer stays free of core/service
imports beyond the WP-08 services it is constructed with.
"""

from __future__ import annotations

import hmac
import secrets
import stat
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from localmesh_agent.api.errors import mesh_error_handler
from localmesh_agent.core.control_plane import ControlPlaneRegistrationError
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
    doctor_fn: Callable[[], list[Any]] | None = None,
    status_fn: Callable[[], dict[str, Any]] | None = None,
    metrics_fn: Callable[[], str] | None = None,
    control_plane: Any = None,
    cp_audit_cb: Callable[[str], None] | None = None,
) -> FastAPI:
    """Admin app factory (§10.5: all state created here; no globals).

    `pairing`/`devices` are the WP-08 services; `tls_rotate` performs §17.5
    Rotate (explicit only) and returns the NEW SPKI pin; `doctor_fn` runs the
    §18.4 ordered checks (WP-13); `status_fn` composes the `GET /admin/status`
    Metadata block and `metrics_fn` renders the §20.1 Prometheus exposition —
    both injected by the CLI wiring so the admin layer stays free of
    core/observability imports.

    `control_plane` (M6, §12) is the optional Control Plane service or None;
    `cp_audit_cb` receives the §20.2 audit event name after a successful
    registration (operator action audit trail).
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
        # 2. Admin token — spec-named custom header ONLY (§13.1/T-11),
        #    constant-time compare (§17.6). A drive-by request cannot set a
        #    custom header, which is exactly the T-11 mitigation.
        header = request.headers.get("X-Admin-Token", "")
        if not hmac.compare_digest(header.encode("utf-8"), admin_token.encode("utf-8")):
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "code": "AUTH_REQUIRED",
                        "message": "Admin token required (X-Admin-Token header).",
                        "retryable": False,
                        "request_id": getattr(request.state, "mesh_request_id", None),
                        "details": {},
                    }
                },
            )
        return await call_next(request)

    # -- pairing (§13.1 `POST /admin/pairing/…`; §15.4 operator flow) ----------

    def _pair_open() -> dict[str, object]:
        try:
            opened = pairing.open()
        except PairingError as error:
            raise MeshError(error.code.value, str(error)) from None
        # §17.4: the QR contains the only intentional secret exposure — it is
        # returned here for LOCAL rendering and never logged (§17.6).
        return {"pair_id": opened.pair_id, "qr": opened.qr, "expires_in": opened.expires_in}

    def _pair_pending() -> dict[str, object]:
        state, pending = pairing.pending()
        result: dict[str, object] = {"state": state.value}
        if state is SessionState.CLAIMED and pending is not None:
            result["device_name"] = pending.name
            result["platform"] = pending.platform
            result["sas"] = pending.sas  # shown to the operator (§15.4)
        return result

    def _pair_approve() -> dict[str, str]:
        try:
            device_id = pairing.approve()
        except PairingError as error:
            raise MeshError(error.code.value, str(error)) from None
        return {"status": "approved", "device_id": device_id}

    def _pair_deny() -> dict[str, str]:
        try:
            pairing.deny()
        except PairingError as error:
            raise MeshError(error.code.value, str(error)) from None
        return {"status": "denied"}

    def _pair_close() -> dict[str, str]:
        """Operator closes Pairing Mode (§15.2 OPEN → CLOSED)."""
        pairing.close()
        return {"status": "closed"}

    @app.post("/admin/pairing/open")
    @app.post("/admin/pair/open")  # [DESIGN] WP-08 alias (QUESTION-103 item 4)
    async def pair_open() -> dict[str, object]:
        return _pair_open()

    @app.get("/admin/pairing")
    @app.get("/admin/pair/pending")  # [DESIGN] WP-08 alias: pending + SAS view
    async def pair_pending() -> dict[str, object]:
        return _pair_pending()

    @app.post("/admin/pairing/approve")
    @app.post("/admin/pair/approve")  # [DESIGN] WP-08 alias
    async def pair_approve() -> dict[str, str]:
        return _pair_approve()

    @app.post("/admin/pairing/deny")
    @app.post("/admin/pair/deny")  # [DESIGN] WP-08 alias
    async def pair_deny() -> dict[str, str]:
        return _pair_deny()

    @app.post("/admin/pairing/close")
    @app.post("/admin/pair/close")  # [DESIGN] WP-08 alias
    async def pair_close() -> dict[str, str]:
        return _pair_close()

    # -- devices (§13.1 `GET|PATCH|DELETE /admin/devices…`; §15.6) --------------

    @app.get("/admin/devices")
    async def admin_devices() -> dict[str, object]:
        # §14.1 fields for the operator — the raw DER public key is NOT
        # operator-display data (and would not JSON-serialize); it stays in
        # the store only.
        rows = [
            {k: v for k, v in device.items() if k != "public_key_spki"} for device in devices.list()
        ]
        return {"devices": rows}

    @app.patch("/admin/devices/{device_id}")
    async def admin_patch_device(device_id: str, request: Request) -> dict[str, object]:
        """§13.1 spec-named operator update: `PATCH /admin/devices/{id}`
        (scopes, name) — the grant mechanism for `models:manage`/`tasks`
        (§13.1 "granted per Device by the operator"). Validation and the
        `device_updated` audit event live in the DeviceService (§10.4)."""
        try:
            payload: Any = await request.json()
        except Exception as exc:  # malformed JSON body
            raise MeshError("INVALID_REQUEST", "Request body must be valid JSON.") from exc
        if not isinstance(payload, dict):
            raise MeshError("INVALID_REQUEST", "Request body must be a JSON object.")
        unknown = sorted(set(payload) - {"name", "scopes"})
        if unknown:
            raise MeshError(
                "INVALID_REQUEST",
                "Unknown fields in PATCH body.",
                details={"unknown_fields": unknown, "allowed": ["name", "scopes"]},
            )
        if "name" not in payload and "scopes" not in payload:
            raise MeshError("INVALID_REQUEST", "Provide at least one of: name, scopes.")
        name = payload.get("name")
        scopes = payload.get("scopes")
        if name is not None and not isinstance(name, str):
            raise MeshError("INVALID_REQUEST", "name must be a string.")
        if scopes is not None:
            if not isinstance(scopes, list) or not all(isinstance(s, str) for s in scopes):
                raise MeshError("INVALID_REQUEST", "scopes must be a list of strings.")
        updated = devices.update(device_id, name=name, scopes=scopes)
        if updated is None:
            raise MeshError("INVALID_REQUEST", "Unknown device.", status_override=404)
        return {"status": "updated", "device": updated}

    def _revoke(device_id: str) -> dict[str, object]:
        revoked, cancelled = devices.revoke(device_id)
        if not revoked:
            raise MeshError("INVALID_REQUEST", "Unknown device.", status_override=404)
        return {"status": "revoked", "device_id": device_id, "cancelled_requests": cancelled}

    @app.delete("/admin/devices/{device_id}")
    async def admin_delete_device(device_id: str) -> dict[str, object]:
        return _revoke(device_id)

    @app.post("/admin/devices/{device_id}/revoke")  # [DESIGN] WP-08 alias
    async def admin_revoke(device_id: str) -> dict[str, object]:
        return _revoke(device_id)

    # -- TLS identity (§17.5: explicit rotate only; §13.1 spec-named) ----------

    @app.post("/admin/tls/rotate")
    async def admin_tls_rotate() -> dict[str, str]:
        new_pin = tls_rotate()
        return {"spki_pin": new_pin, "note": "Phones must re-pair (PIN_MISMATCH, §17.5)."}

    # -- status (§13.1 spec-named; shape [DESIGN], Metadata only) ---------------

    @app.get("/admin/status")
    async def admin_status() -> dict[str, object]:
        if status_fn is None:  # pragma: no cover - wiring always injects it
            raise MeshError("INVALID_REQUEST", "Status is not wired into this agent.")
        return dict(status_fn())

    # -- control plane (M6, §12.3 operator-consented registration) --------------

    @app.post("/admin/control-plane/register")
    async def admin_cp_register(body: dict[str, object]) -> dict[str, object]:
        if control_plane is None:
            raise MeshError(
                "INVALID_REQUEST",
                "Control Plane sync is disabled in config ([control_plane] enabled=false).",
                details={"reason": "control_plane_disabled"},
            )
        code = body.get("code")
        if not isinstance(code, str) or not code.strip():
            raise MeshError(
                "INVALID_REQUEST",
                'Body must be {"code": "<one-time link code from the Phone>"} (§12.3).',
                details={"missing_fields": ["code"]},
            )
        try:
            registration = await control_plane.register(code)
        except ControlPlaneRegistrationError:
            raise MeshError(
                "BACKEND_UNAVAILABLE",
                "Control Plane registration failed; the Agent will keep working "
                "with local data (§12.3).",
                details={"reason": "control_plane_unavailable"},
            ) from None
        if cp_audit_cb is not None:
            cp_audit_cb("control_plane_registered")
        return {
            "state": str(control_plane.state().value),
            "registered": True,
            "registered_at": registration.get("registered_at"),
        }

    @app.get("/admin/control-plane/status")
    async def admin_cp_status() -> dict[str, object]:
        if control_plane is None:
            return {"enabled": False, "state": "disabled", "registered": False}
        return dict(control_plane.status())

    # -- doctor (§13.1 spec-named; findings per §18.4) --------------------------

    @app.get("/admin/doctor")
    async def admin_doctor() -> dict[str, object]:
        if doctor_fn is None:  # pragma: no cover - wiring always injects it
            raise MeshError("INVALID_REQUEST", "Doctor is not wired into this agent.")
        # Probes block (sockets/subprocess); keep the loop free (§10.4 spirit).
        import asyncio

        findings = await asyncio.to_thread(doctor_fn)
        return {"findings": findings}

    # -- metrics (§20.1 optional Prometheus text endpoint, loopback admin ONLY;
    #    route path [DESIGN] — §20.1 names the endpoint type, not a path) -------

    @app.get("/admin/metrics")
    async def admin_metrics() -> Response:
        if metrics_fn is None:  # pragma: no cover - wiring always injects it
            raise MeshError("INVALID_REQUEST", "Metrics are not wired into this agent.")
        return Response(
            content=metrics_fn(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    return app
