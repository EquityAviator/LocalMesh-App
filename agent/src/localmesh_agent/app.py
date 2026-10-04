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
from localmesh_agent.adapters.ports import InferenceBackend, SystemClock
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

    [DESIGN — recorded in OPEN_QUESTIONS QUESTION-103]: the Agent's own LAN
    IP advertisement arrives with WP-11 (mDNS). Until then the QR carries
    the best non-invented endpoint available: `https://<hostname>:<port>`
    when the OS hostname resolves; in dev-insecure mode additionally the
    loopback URL the §17.9 flag actually binds (cleartext, dev-only).
    """
    endpoints: list[str] = []
    port = settings.listen.port
    if not dev_insecure:
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
        log.info(
            "agent_ready",
            extra={
                "agent_id": str(app.state.agent_id),
                "backend_id": ",".join(a.id for a in adapters) or None,
            },
        )

    @app.on_event("shutdown")
    async def _shutdown() -> None:
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
