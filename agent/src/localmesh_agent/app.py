"""FastAPI app factory — public listener (§10.1, §10.5, §10.6).

M1 scope (§22.1 "Agent core (loopback)"): config, store, adapters, registry,
scheduler, `GET /models`, `POST /chat/completions` SSE, cancel, `/health`,
CLI `run` — **dev-insecure loopback listener only** (§17.9). TLS, pairing and
tokens arrive with WP-07/08 (M2); mDNS with WP-11 (M3).

Startup sequence subset (§10.6): load config → init logging with redaction →
run DB migrations → load/create identity (`agent_id`, UUIDv7, `ag_` prefix;
TLS identity is WP-07) → init adapters, probe Backends, build registry →
listeners are started by the CLI (`uvicorn`), not here.

Wire rules (§13): every response carries `X-Mesh-Api-Version: 1` and
`X-Mesh-Request-Id` (`rq_` + UUIDv7); JSON responses carry
`Cache-Control: no-store`; request bodies over the configured limit get
413 `PAYLOAD_TOO_LARGE` (§13.8).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from localmesh_agent.adapters.backends.lmstudio import LMStudioBackend
from localmesh_agent.adapters.backends.ollama import OllamaBackend
from localmesh_agent.adapters.backends.openai_compat import OpenAICompatBackend
from localmesh_agent.adapters.discovery.mdns import (
    build_mdns_advertiser,
    build_service_ad,
    resolve_advertise_addresses,
)
from localmesh_agent.adapters.ports import InferenceBackend, SystemClock, TailnetInfo
from localmesh_agent.adapters.tailscale import TailscaleCliProbe
from localmesh_agent.api.errors import mesh_error_handler
from localmesh_agent.api.v1 import auth, chat, health, info, models, pair, requests
from localmesh_agent.api.v1.auth import ChallengeStore
from localmesh_agent.config import Settings
from localmesh_agent.core.entities import new_uuid7
from localmesh_agent.core.errors import MeshError
from localmesh_agent.core.registry import CapabilityRegistry
from localmesh_agent.core.router import Router
from localmesh_agent.core.scheduler import Scheduler
from localmesh_agent.observability.logging import configure_logging, get_logger
from localmesh_agent.security.devices import DeviceService
from localmesh_agent.security.pairing import PairingService
from localmesh_agent.security.ratelimit import SlidingWindowLimiter
from localmesh_agent.security.tls import load_or_create_identity
from localmesh_agent.security.tokens import TokenService
from localmesh_agent.store.sqlite import Store

log = get_logger("app")

AGENT_VERSION = "0.1.0"  # NFR-COMP-02 semantic version (surfaced via /info)


def build_adapters(settings: Settings) -> list[InferenceBackend]:
    """Instantiate one adapter per enabled `[[backends]]` entry (§10.3).

    `auth_ref` names a keyring entry (§17.6): the secret is read from the OS
    keyring at startup, never from config; when the entry is absent the
    adapter runs unauthenticated (LM Studio default accepts local requests,
    §6.1).
    """
    import keyring

    adapters: list[InferenceBackend] = []
    for backend in settings.backends:
        if not backend.enabled:
            continue
        auth_token: str | None = None
        if backend.auth_ref:
            auth_token = keyring.get_password("localmesh", backend.auth_ref)
        if backend.kind == "lmstudio":
            adapters.append(LMStudioBackend(backend.id, backend.base_url, auth_token=auth_token))
        elif backend.kind == "ollama":
            adapters.append(OllamaBackend(backend.id, backend.base_url))
        else:
            adapters.append(
                OpenAICompatBackend(backend.id, backend.base_url, auth_token=auth_token)
            )
    return adapters


def advertised_endpoints(settings: Settings, *, dev_insecure: bool) -> tuple[str, ...]:
    """https endpoint(s) advertised in the pairing QR (§17.4 `ep` param).

    WP-11: when a LAN IPv4 can be resolved on the selected interfaces
    (§16.2 interface selection), `https://<lan-ip>:<port>` leads the list
    (QUESTION-103 item 5 resolved on the implementation side; the reading
    still awaits owner confirmation). The hostname form remains a fallback
    candidate when resolution fails; dev-insecure keeps the loopback URL
    the §17.9 flag actually binds (cleartext, dev-only).
    """
    endpoints: list[str] = []
    port = settings.listen.port
    if not dev_insecure:
        # §16.2 interface selection — same addresses mDNS will advertise,
        # even when advertisement itself is disabled (`[mdns] enabled=false`).
        for ip in resolve_advertise_addresses(settings.mdns.interfaces)[:1]:
            endpoints.append(f"https://{ip}:{port}")
        import socket

        try:
            hostname = socket.gethostname()
            if hostname:
                endpoints.append(f"https://{hostname}:{port}")
        except OSError:  # pragma: no cover - defensive
            pass
    else:
        endpoints.append(f"http://127.0.0.1:{port}")
    return tuple(endpoints)


def create_app(settings: Settings, *, dev_insecure: bool = False) -> FastAPI:
    """App factory (§10.5: all services created here; no global mutable state)."""
    configure_logging(settings.logging.level)
    app = FastAPI(title="LocalMesh Agent", version=AGENT_VERSION, docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.dev_insecure = dev_insecure  # SEC-N6: default OFF (§17.9)
    app.state.agent_version = AGENT_VERSION
    app.state.started_mono = __import__("time").monotonic()
    clock = SystemClock()  # §10.2 Clock: injectable; one instance per app
    app.state.clock = clock

    # §10.6 step 2-3: migrations + identity (agent_id + TLS identity, WP-07).
    data_dir = settings.ensure_data_dir()
    store = Store(data_dir / "agent.db")
    app.state.store = store
    identity = store.get_identity()
    if identity is None:
        agent_id = f"ag_{new_uuid7()}"
        store.set_identity(agent_id, settings.agent.display_name, _now())
        identity = store.get_identity()
    assert identity is not None
    app.state.agent_id = str(identity["agent_id"])
    # §10.6 step 3 (WP-07): ECDSA P-256 self-signed identity; spki_sha256 is
    # the pin the App will verify against the QR `fp` (§17.3/§17.5, M2).
    tls_identity = load_or_create_identity(data_dir / "tls")
    app.state.spki_pin = tls_identity.spki_sha256

    # §10.6 step 4: adapters, registry, scheduler, router.
    adapters = build_adapters(settings)
    app.state.adapters = adapters
    registry = CapabilityRegistry(
        app.state.agent_id,
        adapters,
        store,
        overrides=list(settings.models.overrides),  # type: ignore[arg-type]
    )
    app.state.registry = registry
    app.state.scheduler = Scheduler(
        {backend.id: backend.concurrency for backend in settings.backends},
        per_device_active=settings.limits.per_device_active,
        max_queued=settings.limits.max_queued,
    )
    app.state.router = Router(registry, {a.id: a for a in adapters})
    # §14.3 dev-mode Device identity (M1 loopback only; token auth is WP-08).
    app.state.dev_device_id = f"dv_{new_uuid7()}"

    # -- WP-08 security services (§10.4 PairingService/TokenService/
    #    DeviceService; §13.8 limiter; all state lives on app.state, §10.5) --
    app.state.limiter = SlidingWindowLimiter()
    app.state.devices = DeviceService(store, on_revoke=app.state.scheduler.cancel_by_device)
    app.state.tokens = TokenService(store, clock)
    app.state.challenges = ChallengeStore()
    app.state.pairing = PairingService(
        store=store,
        devices=app.state.devices,
        clock=clock,
        ttl_seconds=settings.pairing.ttl_seconds,
        require_confirmation=settings.pairing.require_confirmation,
        agent_id=str(app.state.agent_id),
        display_name=settings.agent.display_name,
        spki_pin=tls_identity.spki_sha256,
        endpoints=advertised_endpoints(settings, dev_insecure=dev_insecure),
        listen_port=settings.listen.port,  # T2 candidate URLs (WP-14, §16.1)
    )

    # -- WP-14 (§6.3/§18.6): TailnetProbe port implementation. The probe runs
    #    at lifespan-startup (subprocess in a thread pool, 2 s timeout per
    #    §10.5); its snapshot feeds the §10.6 step-7 ready log, the pairing
    #    QR/status tailnet block (§13.2/§18.6) and — with WP-15 — /device.
    #    Detection only: never authorization (SEC-N4), never a login manager
    #    (§18.6). Failures degrade to state="unknown"/None, never block start
    #    (T-21 spirit: untrusted hints must not take the Agent down).
    app.state.tailnet_probe = TailscaleCliProbe()
    app.state.tailnet: TailnetInfo | None = None

    # -- WP-11 discovery (§10.6 step 5, FR-AGT-04, §16.2): the advertiser
    #    is created here but STARTED at lifespan-startup, after the registry
    #    is warm (§10.6 step order). `po` mirrors API-INFO-01 pairing_open.
    app.state.mdns = None
    if settings.mdns.enabled:
        app.state.mdns = build_mdns_advertiser(
            settings.mdns.interfaces,
            pairing_open_fn=app.state.pairing.pairing_open,
        )

    # Routers (§13.1): M1 scope (models/chat/requests/health) + WP-08 scope
    # (info/pair/auth). device.py arrives with WP-15 (hardware probes,
    # §22.2); tasks.py with M7 (§13.9) — not registered here (scope fence).
    app.include_router(info.router)
    app.include_router(pair.router)
    app.include_router(auth.router)
    app.include_router(models.router)
    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(requests.router)

    # §13.4 envelope for every MeshError.
    app.add_exception_handler(MeshError, mesh_error_handler)  # type: ignore[arg-type]

    @app.middleware("http")
    async def mesh_headers(request: Request, call_next: Callable[[Request], Awaitable[Any]]) -> Any:
        # §13.3: X-Mesh-Request-Id on every response; JSON gets no-store.
        request.state.mesh_request_id = f"rq_{new_uuid7()}"
        response = await call_next(request)
        response.headers["X-Mesh-Request-Id"] = request.state.mesh_request_id
        response.headers["X-Mesh-Api-Version"] = "1"
        content_type = response.headers.get("Content-Type", "")
        if "text/event-stream" not in content_type and "Cache-Control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.middleware("http")
    async def body_limit(request: Request, call_next: Callable[[Request], Awaitable[Any]]) -> Any:
        # §13.8: request body (JSON) default 2 MiB → 413 PAYLOAD_TOO_LARGE.
        declared = request.headers.get("Content-Length")
        limit = app.state.settings.limits.max_body_bytes
        if declared is not None and declared.isdigit() and int(declared) > limit:
            return JSONResponse(
                status_code=413,
                content={
                    "error": {
                        "code": "PAYLOAD_TOO_LARGE",
                        "message": "Request body exceeds the size limit.",
                        "retryable": False,
                        "request_id": getattr(request.state, "mesh_request_id", None),
                        "details": {"limit_bytes": limit},
                    }
                },
            )
        return await call_next(request)

    @app.on_event("startup")
    async def _startup() -> None:
        # §10.6 step 4: probe Backends and build the registry BEFORE serving;
        # §16.3 background polling continues afterwards.
        await registry.refresh()
        registry.start_polling()
        # WP-14 (§10.6 step 7): Tailnet status is part of the ready report.
        # Detection is best effort — any unexpected failure degrades to None
        # (LAN-only), never blocks the Agent from serving (§18.6, T-21).
        try:
            tailnet_info = await app.state.tailnet_probe.status()
        except Exception:  # noqa: BLE001 — detection degrades, never blocks
            tailnet_info = None
        app.state.tailnet = tailnet_info
        app.state.pairing.tailnet = tailnet_info  # §13.2/§18.6 pairing block
        # §17.10 allow-listed keys only (component/status); DNS name and IPs
        # are NOT logged (no allow-listed key, NFR-SEC-02 — QUESTION-102).
        log.info(
            "tailscale_status",
            extra={
                "component": "tailscale",
                "status": tailnet_info.state.lower() if tailnet_info is not None else "absent",
            },
        )
        # §10.6 step 5 (WP-11): start the mDNS advertisement on the selected
        # interfaces. Failure/degradation must not block Agent start (T-21:
        # advertisements are untrusted hints; MdnsAdvertiser logs, not raises).
        if app.state.mdns is not None:
            ad = build_service_ad(
                str(app.state.agent_id),
                settings.agent.display_name,
                settings.listen.port,
                tls_identity.spki_sha256,
                pairing_open=app.state.pairing.pairing_open(),
            )
            try:
                await app.state.mdns.start(ad)
            except Exception:  # noqa: BLE001 — discovery degrades, never blocks
                app.state.mdns = None
                log.warning("mdns_start_failed", extra={"component": "mdns", "status": "error"})
        log.info(
            "agent_ready",
            extra={
                "agent_id": str(app.state.agent_id),
                "backend_id": ",".join(a.id for a in adapters) or None,
            },
        )

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        if app.state.mdns is not None:
            await app.state.mdns.stop()
            app.state.mdns = None
        await registry.stop_polling()
        for adapter in adapters:
            close = getattr(adapter, "aclose", None)
            if close is not None:
                await close()
        store.close()

    return app


def _now() -> int:
    import time

    return int(time.time())
