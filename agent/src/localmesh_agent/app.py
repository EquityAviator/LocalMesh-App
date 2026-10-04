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

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from localmesh_agent.adapters.backends.lmstudio import LMStudioBackend
from localmesh_agent.adapters.backends.ollama import OllamaBackend
from localmesh_agent.adapters.backends.openai_compat import OpenAICompatBackend
from localmesh_agent.adapters.backends.whisper import WhisperBackend
from localmesh_agent.adapters.controlplane import SupabaseControlPlaneClient
from localmesh_agent.adapters.discovery.mdns import (
    build_mdns_advertiser,
    build_service_ad,
    resolve_advertise_addresses,
)
from localmesh_agent.adapters.hardware.nvidia_probe import NvmlGpuProbe
from localmesh_agent.adapters.hardware.psutil_probe import (
    CompositeHardwareProbe,
    PsutilHardwareProbe,
)
from localmesh_agent.adapters.ports import InferenceBackend, SystemClock
from localmesh_agent.adapters.tailscale import TailscaleCliProbe
from localmesh_agent.api.errors import mesh_error_handler
from localmesh_agent.api.v1 import auth, chat, device, health, info, models, pair, requests, tasks
from localmesh_agent.api.v1.auth import ChallengeStore
from localmesh_agent.config import Settings
from localmesh_agent.core.control_plane import (
    ControlPlaneService,
    registration_codec,
)
from localmesh_agent.core.entities import new_uuid7
from localmesh_agent.core.errors import MeshError
from localmesh_agent.core.rag import RagService
from localmesh_agent.core.registry import CapabilityRegistry
from localmesh_agent.core.router import Router
from localmesh_agent.core.scheduler import Scheduler
from localmesh_agent.core.tasks import TaskService
from localmesh_agent.core.tools import ToolRegistry
from localmesh_agent.core.warm import KeepWarmScheduler
from localmesh_agent.observability.logging import configure_logging, get_logger
from localmesh_agent.observability.metrics import MetricsRegistry
from localmesh_agent.security import task_crypto
from localmesh_agent.security.devices import DeviceService
from localmesh_agent.security.pairing import PairingService
from localmesh_agent.security.ratelimit import SlidingWindowLimiter
from localmesh_agent.security.tls import load_or_create_identity, public_spki_der
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
    # Appendix E [limits] knobs — §10.3 rule 4 says these ARE configurable:
    # before this wiring the config keys existed but never reached the
    # adapters (operators' `first_token_timeout_seconds` / `max_stream_seconds`
    # were silently ignored).
    first_token_timeout_s = float(settings.limits.first_token_timeout_seconds)
    total_stream_cap_s = float(settings.limits.max_stream_seconds)
    for backend in settings.backends:
        if not backend.enabled:
            continue
        auth_token: str | None = None
        if backend.auth_ref:
            auth_token = keyring.get_password("localmesh", backend.auth_ref)
        if backend.kind == "lmstudio":
            adapters.append(
                LMStudioBackend(
                    backend.id,
                    backend.base_url,
                    auth_token=auth_token,
                    first_token_timeout_s=first_token_timeout_s,
                    total_stream_cap_s=total_stream_cap_s,
                )
            )
        elif backend.kind == "ollama":
            adapters.append(
                OllamaBackend(
                    backend.id,
                    backend.base_url,
                    first_token_timeout_s=first_token_timeout_s,
                    total_stream_cap_s=total_stream_cap_s,
                )
            )
        elif backend.kind == "whisper":
            # M7 (FR-MM-02): the separate Whisper-class STT service. Keyring
            # auth mirrors the other adapters (§17.6); never used for chat.
            adapters.append(
                WhisperBackend(
                    backend.id,
                    backend.base_url,
                    auth_token=auth_token,
                )
            )
        else:
            adapters.append(
                OpenAICompatBackend(
                    backend.id,
                    backend.base_url,
                    auth_token=auth_token,
                    first_token_timeout_s=first_token_timeout_s,
                    total_stream_cap_s=total_stream_cap_s,
                )
            )
    return adapters


def _build_control_plane(
    settings: Settings,
    store: Store,
    agent_id: str,
    tls_identity: Any,
    clock: Any,
) -> ControlPlaneService | None:
    """M6 (§12): build the optional Control Plane service, or None.

    The CP key is read from the OS keyring (§17.6); a missing entry yields an
    empty key so every CP call fails → the service reports "offline" (§12.3
    failure mode) instead of half-configured silence.
    """
    cp_settings = settings.control_plane
    if not cp_settings.enabled:
        return None
    import keyring

    api_key = keyring.get_password("localmesh", cp_settings.auth_ref) or ""
    client = SupabaseControlPlaneClient(cp_settings.url, api_key)
    load_reg, save_reg, clear_reg = registration_codec(store)

    def _device_public_key(device_id: str) -> bytes | None:
        row = store.get_device(device_id)
        raw = row.get("public_key_spki") if row is not None else None
        return bytes(raw) if isinstance(raw, (bytes, bytearray)) else None

    return ControlPlaneService(
        client,
        agent_id=agent_id,
        display_name=settings.agent.display_name,
        public_key_spki=public_spki_der(tls_identity.cert_pem),
        clock=clock,
        load_registration=load_reg,
        save_registration=save_reg,
        clear_registration=clear_reg,
        device_public_key=_device_public_key,
        heartbeat_interval_s=cp_settings.heartbeat_interval_s,
    )


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
    """App factory (§10.5: all services created here; no global mutable state).

    The §10.6 startup/shutdown sequence runs through ONE FastAPI **lifespan**
    handler. The deprecated `@app.on_event` decorators (FastAPI ≥ 0.103) are
    deliberately not used — they emitted 228 suite-wide DeprecationWarnings
    before the migration; this factory must stay warning-free.
    """
    configure_logging(settings.logging.level)
    import time

    clock = SystemClock()  # §10.2 Clock: injectable; one instance per app

    # §10.6 step 2-3: migrations + identity (agent_id + TLS identity, WP-07).
    data_dir = settings.ensure_data_dir()
    store = Store(data_dir / "agent.db")
    identity = store.get_identity()
    if identity is None:
        agent_id = f"ag_{new_uuid7()}"
        store.set_identity(agent_id, settings.agent.display_name, _now())
        identity = store.get_identity()
    assert identity is not None
    agent_id = str(identity["agent_id"])
    # §10.6 step 3 (WP-07): ECDSA P-256 self-signed identity; spki_sha256 is
    # the pin the App will verify against the QR `fp` (§17.3/§17.5, M2).
    tls_identity = load_or_create_identity(data_dir / "tls")

    # §10.6 step 4: adapters, registry, scheduler, router.
    adapters = build_adapters(settings)
    registry = CapabilityRegistry(
        agent_id,
        adapters,
        store,
        overrides=list(settings.models.overrides),
    )
    metrics = MetricsRegistry()  # §20.1 (shared with the admin scrape)
    scheduler = Scheduler(
        {backend.id: backend.concurrency for backend in settings.backends},
        per_device_active=settings.limits.per_device_active,
        max_queued=settings.limits.max_queued,
        metrics=metrics,  # §20.1 cancel_latency_ms
    )
    # -- M8 (§16.6, FR-RTE-01/02): auto-routing providers. quality_rank
    #    comes from the Appendix E model overrides (default 3, §16.6);
    #    speed_norm reads recent tokens/s per model (null → 0.5, §16.6);
    #    queue_load reads the scheduler's per-backend job count.
    speed_by_model: dict[str, float] = {}

    def _record_speed(mesh_model_id: str, tokens_per_sec: float) -> None:
        if tokens_per_sec > 0:
            speed_by_model[mesh_model_id] = tokens_per_sec

    router = Router(
        registry,
        {a.id: a for a in adapters},
        quality_ranks={
            override.mesh_model_id: override.quality_rank
            for override in settings.models.overrides
            if override.quality_rank is not None
        },
        speed_fn=lambda mesh_model_id: speed_by_model.get(mesh_model_id),
        queue_fn=scheduler.backend_load,
        weights=(
            settings.routing.weight_quality,
            settings.routing.weight_warmth,
            settings.routing.weight_speed,
            settings.routing.weight_queue,
        ),
    )
    app_speed_recorder = _record_speed

    # -- WP-15 part 2 (§16.5, FR-MOD-05): keep-warm policy. The warm set comes
    #    ONLY from the Appendix E override (`models.overrides[].keep_warm`);
    #    pings go through the §10.2 keep_warm port (Ollama native ping; LM
    #    Studio keep-warm is n/a per §10.3 and is never pinged). The
    #    device-activity gate reads §14.1 last_seen_at via the Store —
    #    non-revoked devices only (a revoked row must never count as active).
    def _device_active_since(epoch_s: int) -> bool:
        for row in store.list_devices():
            if row.get("revoked_at") is not None:
                continue
            last_seen = row.get("last_seen_at")
            if isinstance(last_seen, int) and last_seen >= epoch_s:
                return True
        return False

    keep_warm = KeepWarmScheduler(
        registry,
        {a.id: a for a in adapters},
        frozenset(
            override.mesh_model_id for override in settings.models.overrides if override.keep_warm
        ),
        _device_active_since,
        clock=clock,
    )
    # §14.3 dev-mode Device identity (M1 loopback only; token auth is WP-08).
    dev_device_id = f"dv_{new_uuid7()}"

    # -- M7 (§13.9, FR-MM-01..04): durable Tasks + local RAG. Content lives
    #    only as AES-256-GCM ciphertext (task_crypto; ADR-011 exception with
    #    hard expiry), the sweeper enforces the ≤ 1 h retention, and
    #    chat/vision tasks run through the SAME §16 Scheduler as chat.
    tasks_key = task_crypto.load_or_create_key(data_dir)
    task_service = TaskService(
        store,
        key=tasks_key,
        retention_s=settings.tasks.result_retention_s,
        max_concurrent=settings.tasks.max_concurrent,
        scheduler=scheduler,
        router=router,
        transcriber=next(  # FR-MM-02: the (optional) Whisper-class adapter
            (a for a in adapters if getattr(a, "kind", None) == "whisper"), None
        ),
        embedder=None,  # wired at lifespan-start from the Capability Registry
        embed_model_backend_id=None,
        new_task_id=lambda: f"tk_{new_uuid7()}",
        clock=clock,
    )
    rag_service = RagService(store, None, None, tasks_key)
    task_service.set_rag(rag_service)

    # -- M8 (FR-AGENT-RT, ADR-020): the tool registry exists always (it is
    #    the allow-list); EXECUTION is denied until the operator sets
    #    [agent_runtime] enabled=true (API-layer gate). `list_models` is
    #    registered lazily against the live Capability Registry.
    tool_registry = ToolRegistry()
    tool_registry.register_models_tool(
        lambda: [entry.mesh_model_id for entry in registry.entries()]
    )

    # FR-RTE-03: the classifier hook is wired ONLY when enabled (it stays
    # experimental and off by default — S-21); failure degrades to the pure
    # rule engine (chat.py swallows classifier exceptions).
    classifier_fn = None
    if settings.routing.classifier_enabled and settings.routing.classifier_model:

        def classifier_fn(messages: list[dict[str, Any]]) -> frozenset[str]:
            return _classify_intent(
                registry,
                {a.id: a for a in adapters},
                scheduler,
                settings.routing.classifier_model,
                messages,
            )

    def _wire_embedder() -> None:
        """FR-MM-03: pick the first embedding-capable Registry entry (source
        = backend report or user override, §13.5) once backends answered."""
        adapter_by_id = {a.id: a for a in adapters}
        for entry in registry.entries():
            if "embedding" not in entry.capabilities:
                continue
            candidate = adapter_by_id.get(entry.backend_id)
            if candidate is not None and hasattr(candidate, "embed"):
                rag_service.configure_embedder(candidate, entry.backend_model_id)
                return

    # -- WP-08 security services (§10.4 PairingService/TokenService/
    #    DeviceService; §13.8 limiter; all state lives on app.state, §10.5) --
    # M6 (§12): the Control Plane service is OPTIONAL and off by default.
    # It is Metadata-only (§12.1, ADR-001/FR-CP-04) and never blocks the
    # Agent: revocation mirror failures are swallowed after logging, the
    # heartbeat degrades to "offline" (§12.3 failure mode).
    control_plane = _build_control_plane(settings, store, agent_id, tls_identity, clock)

    # The revoke hook fans out: local authority (cancel streams) ALWAYS runs;
    # the CP mirror (FR-CP-03) is a best-effort fire-and-forget side task.
    _cp_mirror_tasks: set[asyncio.Task[None]] = set()

    def _on_device_revoked(device_id: str) -> int:
        cancelled = scheduler.cancel_by_device(device_id)
        if control_plane is not None:
            mirror = asyncio.create_task(
                control_plane.mirror_device_revocation(device_id, clock.now_wall())
            )
            _cp_mirror_tasks.add(mirror)
            mirror.add_done_callback(_cp_mirror_tasks.discard)
        return cancelled

    devices_service = DeviceService(store, on_revoke=_on_device_revoked)
    tokens = TokenService(store, clock)
    pairing = PairingService(
        store=store,
        devices=devices_service,
        clock=clock,
        ttl_seconds=settings.pairing.ttl_seconds,
        require_confirmation=settings.pairing.require_confirmation,
        agent_id=agent_id,
        display_name=settings.agent.display_name,
        spki_pin=tls_identity.spki_sha256,
        endpoints=advertised_endpoints(settings, dev_insecure=dev_insecure),
        listen_port=settings.listen.port,  # T2 candidate URLs (WP-14, §16.1)
    )

    # -- WP-14 (§6.3/§18.6): TailnetProbe port implementation. The probe runs
    #    at lifespan-startup (subprocess in a thread pool, 2 s timeout per
    #    §10.5); its snapshot feeds the §10.6 step-7 ready log, the pairing
    #    QR/status tailnet block (§13.2/§18.6) and `GET /device` (WP-15).
    #    Detection only: never authorization (SEC-N4), never a login manager
    #    (§18.6). Failures degrade to state="unknown"/None, never block start
    #    (T-21 spirit: untrusted hints must not take the Agent down).
    tailnet_probe = TailscaleCliProbe()

    # -- WP-15 (§10.2 HardwareProbe, §22.2 M5): best-effort hardware snapshot
    #    for API-DEV-01 `GET /device` (FR-STAT-01). psutil provides OS/CPU/
    #    RAM; the optional pynvml probe appends NVIDIA GPUs when a driver is
    #    present (§21.2). Both run blocking reads in a thread pool with 2 s
    #    timeouts (§10.5) and degrade to null/empty fields — never raise.
    hardware = CompositeHardwareProbe(
        PsutilHardwareProbe(),
        gpu_probes=(NvmlGpuProbe(),),
    )

    # -- WP-11 discovery (§10.6 step 5, FR-AGT-04, §16.2): the advertiser
    #    is created here but STARTED at lifespan-startup, after the registry
    #    is warm (§10.6 step order). `po` mirrors API-INFO-01 pairing_open.
    mdns_advertiser = None
    if settings.mdns.enabled:
        mdns_advertiser = build_mdns_advertiser(
            settings.mdns.interfaces,
            pairing_open_fn=pairing.pairing_open,
        )

    # -- §10.6 lifespan: startup (steps 4-7) + symmetric shutdown. Captures the
    #    locals above; registered on the FastAPI instance below (lifespan=).
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # §10.6 step 4: probe Backends and build the registry BEFORE serving;
        # §16.3 background polling continues afterwards.
        await registry.refresh()
        registry.start_polling()
        _wire_embedder()  # M7 (FR-MM-03): needs a refreshed registry
        # M7 (§13.9): the retention sweeper starts with the Agent; chat and
        # pairing NEVER wait on it (fire-and-forget background loop).
        task_service.start()
        # WP-14 (§10.6 step 7): Tailnet status is part of the ready report.
        # Detection is best effort — any unexpected failure degrades to None
        # (LAN-only), never blocks the Agent from serving (§18.6, T-21).
        try:
            tailnet_info = await tailnet_probe.status()
        except Exception:  # noqa: BLE001 — detection degrades, never blocks
            tailnet_info = None
        app.state.tailnet = tailnet_info
        pairing.tailnet = tailnet_info  # §13.2/§18.6 pairing block
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
        if mdns_advertiser is not None:
            ad = build_service_ad(
                agent_id,
                settings.agent.display_name,
                settings.listen.port,
                tls_identity.spki_sha256,
                pairing_open=pairing.pairing_open(),
            )
            try:
                await mdns_advertiser.start(ad)
            except Exception:  # noqa: BLE001 — discovery degrades, never blocks
                app.state.mdns = None
                log.warning("mdns_start_failed", extra={"component": "mdns", "status": "error"})
        log.info(
            "agent_ready",
            extra={
                "agent_id": agent_id,
                "backend_id": ",".join(a.id for a in adapters) or None,
            },
        )
        # WP-15 part 2 (§16.5, §10.6 order): the warm loop starts AFTER the
        # registry is built/warm — it reads registry entries each tick.
        keep_warm.start()
        # M6 (§12.3): CP heartbeat starts last — it is optional Metadata sync
        # and must never delay the Agent's core startup.
        if control_plane is not None:
            control_plane.start()
        yield
        # Shutdown is the exact reverse (§10.6 symmetry).
        await task_service.stop()
        if control_plane is not None:
            await control_plane.stop()
        if _cp_mirror_tasks:  # drain in-flight mirrors before store closes
            await asyncio.gather(*_cp_mirror_tasks, return_exceptions=True)
            _cp_mirror_tasks.clear()
        await keep_warm.stop()
        if app.state.mdns is not None:
            await app.state.mdns.stop()
            app.state.mdns = None
        await registry.stop_polling()
        for adapter in adapters:
            close = getattr(adapter, "aclose", None)
            if close is not None:
                await close()
        store.close()

    app = FastAPI(
        title="LocalMesh Agent",
        version=AGENT_VERSION,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.metrics = metrics  # §20.1 (instrumentation + admin scrape)
    app.state.dev_insecure = dev_insecure  # SEC-N6: default OFF (§17.9)
    app.state.agent_version = AGENT_VERSION
    app.state.started_mono = time.monotonic()
    app.state.clock = clock
    app.state.store = store
    app.state.agent_id = agent_id
    app.state.spki_pin = tls_identity.spki_sha256
    app.state.adapters = adapters
    app.state.registry = registry
    app.state.scheduler = scheduler
    app.state.router = router
    app.state.keep_warm = keep_warm
    app.state.dev_device_id = dev_device_id
    app.state.limiter = SlidingWindowLimiter()
    app.state.devices = devices_service
    app.state.tokens = tokens
    app.state.challenges = ChallengeStore()
    app.state.pairing = pairing
    app.state.tailnet_probe = tailnet_probe
    app.state.tailnet = None
    app.state.hardware = hardware
    app.state.mdns = mdns_advertiser
    app.state.control_plane = control_plane  # M6 (§12): None when disabled
    app.state.tasks = task_service  # M7 (§13.9)
    app.state.tasks_key = tasks_key  # M7: at-rest key (never leaves the process)
    app.state.rag = rag_service
    app.state.tool_registry = tool_registry  # M8 (ADR-020 allow-list)
    app.state.speed_recorder = app_speed_recorder  # M8 (§16.6 speed_norm)
    app.state.classifier_fn = classifier_fn  # M8 (FR-RTE-03): None when off

    # Routers (§13.1): M1 scope (models/chat/requests/health) + WP-08 scope
    # (info/pair/auth) + WP-15 scope (device, §22.2 M5) + M7 scope (tasks,
    # §13.9).
    app.include_router(info.router)
    app.include_router(pair.router)
    app.include_router(auth.router)
    app.include_router(models.router)
    app.include_router(health.router)
    app.include_router(device.router)
    app.include_router(chat.router)
    app.include_router(requests.router)
    app.include_router(tasks.router)

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
        # M7 (§13.9): task attachment uploads use the dedicated attachment cap
        # (`tasks.max_attachment_bytes`) — voice notes/documents are bigger.
        declared = request.headers.get("Content-Length")
        limit = app.state.settings.limits.max_body_bytes
        if request.url.path.startswith("/mesh/v1/tasks/") and "/attachments/" in request.url.path:
            limit = app.state.settings.tasks.max_attachment_bytes
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

    return app


def _now() -> int:
    import time

    return int(time.time())


def _classify_intent(
    registry: CapabilityRegistry,
    backends: dict[str, Any],
    scheduler: Scheduler,
    classifier_model: str,
    messages: list[dict[str, Any]],
) -> asyncio.Future[frozenset[str]] | None:
    """FR-RTE-03 (EXPERIMENTAL, off by default): schedule ONE classification
    generation on the running loop; returns the future (the API layer awaits
    it) or None when the model is unavailable. Failures degrade to the pure
    rule engine — the classifier can only REFINE the required set."""
    from localmesh_agent.adapters.ports import ChatMessage, ChatRequest

    entry = registry.get(classifier_model)
    if entry is None:
        return None
    backend = backends.get(entry.backend_id)
    if backend is None:
        return None
    prompt = " ".join(
        str(message.get("content", ""))[:500]
        for message in messages
        if isinstance(message.get("content"), str)
    )[-1000:]

    async def _run() -> frozenset[str]:
        job = scheduler.admit(
            request_id=f"classifier-{id(messages):x}",
            device_id="ag_internal",
            backend_id=entry.backend_id,
        )
        try:
            await scheduler.await_running(job)
            text = ""
            async for chunk in backend.stream_chat(
                ChatRequest(
                    model=entry.mesh_model_id,
                    backend_model_id=entry.backend_model_id,
                    messages=(
                        ChatMessage(
                            role="user",
                            content=(
                                "Classify the request into exactly one category "
                                "(vision|code|reasoning|chat). Answer with the "
                                "category word only.\n\n" + prompt
                            ),
                        ),
                    ),
                    stream=False,
                ),
                job.token,
            ):
                if chunk.delta_content is not None:
                    text += chunk.delta_content
        finally:
            job.token.cancel()
            scheduler.release(job)
        word = text.strip().lower()
        if word in ("vision", "code", "reasoning", "chat"):
            return frozenset({word})
        return frozenset()

    # Handlers always run inside a loop; ensure_future schedules the
    # classification there and chat.py awaits it (FR-RTE-03).
    return asyncio.ensure_future(_run())
