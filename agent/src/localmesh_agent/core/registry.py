"""CapabilityRegistry — merge/normalize/refresh (§10.4, §16.3, §13.5).

§16.3 algorithm (normative):
```
every poll_interval (15 s) and on demand:
  for each enabled adapter (concurrently, timeout 3 s):
     status = adapter.probe()
     if up: models = adapter.list_models() else models = previous entries with state='unknown'
  entries = []
  for m in models: entries.append(normalize(m))     # fields null if absent; set source
  apply user overrides from config (source='user')
  sort by (backend_id, display_name)
  store snapshot in model_cache; bump generated_at
```
`normalize` MUST NOT parse names to guess params/quantization/capabilities
(§16.3; §13.5: a value appears only if the Backend reports it or a user
override sets it).
"""

from __future__ import annotations

import asyncio
from datetime import UTC
from typing import TYPE_CHECKING

from localmesh_agent.adapters.ports import (
    BackendModel,
    BackendStatus,
    Clock,
    InferenceBackend,
    Store,
    SystemClock,
)
from localmesh_agent.core.entities import ModelEntry
from localmesh_agent.observability.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from localmesh_agent.config import ModelOverrideConfig

log = get_logger("registry")

# §16.3: poll default 15 s; per-adapter probe+list timeout 3 s.
DEFAULT_POLL_INTERVAL_S = 15.0
ADAPTER_TIMEOUT_S = 3.0


class CapabilityRegistry:
    """Normalized list of Models with metadata and provenance (§3, §16.3)."""

    def __init__(
        self,
        agent_id: str,
        backends: list[InferenceBackend],
        store: Store,
        *,
        clock: Clock | None = None,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        overrides: list[ModelOverrideConfig] | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._backends = list(backends)
        self._store = store
        self._clock = clock or SystemClock()
        self._poll_interval_s = poll_interval_s
        self._overrides = {o.mesh_model_id: o for o in (overrides or [])}
        self._entries: dict[str, ModelEntry] = {}
        self._backend_status: dict[str, BackendStatus] = {}
        self._generated_at = 0
        self._poll_task: asyncio.Task[None] | None = None

    # -- lifecycle -----------------------------------------------------------

    def start_polling(self) -> None:
        """Start the background poll loop (§16.3 'every poll_interval')."""
        if self._poll_task is None or self._poll_task.done():
            self._poll_task = asyncio.create_task(self._poll_loop(), name="registry-poll")

    async def stop_polling(self) -> None:
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None

    async def _poll_loop(self) -> None:
        while True:
            try:
                await self.refresh()
            except Exception:  # noqa: BLE001 — registry must survive anything
                log.error("registry_refresh_failed")
            await asyncio.sleep(self._poll_interval_s)

    # -- refresh (§16.3) ------------------------------------------------------

    async def refresh(self) -> None:
        """One merge pass: probe adapters concurrently, normalize, override,
        sort, snapshot (§16.3)."""
        statuses = await asyncio.gather(*(self._probe_one(backend) for backend in self._backends))
        for status in statuses:
            self._backend_status[status.backend_id] = status

        previous = self._entries
        entries: list[ModelEntry] = []
        for backend, status in zip(self._backends, statuses, strict=True):
            if status.status == "up":
                try:
                    models = await self._list_models_timed(backend)
                except Exception:  # noqa: BLE001 — adapter errors -> down path
                    log.warning(
                        "backend_list_models_failed",
                        backend_id=backend.id,
                        error_code="BACKEND_UNAVAILABLE",
                    )
                    models = None
                if models is not None:
                    for model in models:
                        entries.append(ModelEntry.from_backend(backend.id, model))
                    continue
            # Backend down (or list failed): previous entries demoted to
            # state='unknown' (§16.3 'previous entries with state=unknown').
            for entry in previous.values():
                if entry.backend_id == backend.id:
                    entries.append(entry.with_state("unknown"))

        entries = [self._apply_override(e) for e in entries]
        # §16.3 sort by (backend_id, display_name); backend_model_id appended
        # as a deterministic tiebreak for None display names [DESIGN].
        entries.sort(key=lambda e: (e.backend_id, e.display_name or "", e.backend_model_id))
        self._entries = {e.mesh_model_id: e for e in entries}
        self._generated_at = self._clock.now_wall()
        self._snapshot_to_store()

    async def _probe_one(self, backend: InferenceBackend) -> BackendStatus:
        try:
            return await asyncio.wait_for(backend.probe(), ADAPTER_TIMEOUT_S)
        except (TimeoutError, Exception):  # noqa: BLE001 — down is a status
            return BackendStatus(backend_id=backend.id, status="down")

    async def _list_models_timed(self, backend: InferenceBackend) -> list[BackendModel] | None:
        try:
            return await asyncio.wait_for(backend.list_models(), ADAPTER_TIMEOUT_S)
        except TimeoutError:
            return None

    def _apply_override(self, entry: ModelEntry) -> ModelEntry:
        """User overrides — the ONLY non-backend metadata source (§13.5)."""
        override = self._overrides.get(entry.mesh_model_id)
        if override is None:
            return entry
        if override.capabilities:
            entry = ModelEntry(
                mesh_model_id=entry.mesh_model_id,
                backend_id=entry.backend_id,
                backend_model_id=entry.backend_model_id,
                display_name=entry.display_name,
                state=entry.state,
                modalities_input=entry.modalities_input,
                modalities_output=entry.modalities_output,
                modalities_source=entry.modalities_source,
                capabilities=tuple(override.capabilities),
                capabilities_source="user",
                context_length=entry.context_length,
                quantization=entry.quantization,
                parameter_size=entry.parameter_size,
                size_bytes=entry.size_bytes,
                vram_estimate_bytes=entry.vram_estimate_bytes,
                tags=entry.tags,
            )
        return entry

    def _snapshot_to_store(self) -> None:
        """'store snapshot in model_cache; bump generated_at' (§16.3)."""
        self._store.replace_model_cache(
            [
                (entry.mesh_model_id, _json_dumps(entry.to_api_json()))
                for entry in self._entries.values()
            ],
            self._generated_at,
        )

    # -- read access (API-MODEL-01 §13.5 envelope) -----------------------------

    @property
    def generated_at(self) -> int:
        return self._generated_at

    def backend_status(self, backend_id: str) -> BackendStatus | None:
        return self._backend_status.get(backend_id)

    def snapshot(self) -> dict[str, object]:
        """§13.5 envelope: `{agent_id, generated_at, backends[], models[]}`.

        `generated_at` is an ISO-8601 UTC timestamp (§13.5 shows a timestamp
        string); backends carry id/kind/status/caps per the envelope shape.
        """
        from datetime import datetime

        backends_json: list[dict[str, object]] = []
        for backend in self._backends:
            status = self._backend_status.get(backend.id)
            backends_json.append(
                {
                    "id": backend.id,
                    "kind": backend.kind,
                    "status": status.status if status else "unknown",
                    "caps": {
                        "load_unload": backend.caps["load_unload"],
                        "keep_warm": backend.caps["keep_warm"],
                    },
                }
            )
        models_json = [
            entry.to_api_json()
            for entry in sorted(
                self._entries.values(), key=lambda e: (e.backend_id, e.display_name or "")
            )
        ]
        return {
            "agent_id": self._agent_id,
            "generated_at": datetime.fromtimestamp(self._generated_at, tz=UTC)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z"),
            "backends": backends_json,
            "models": models_json,
        }

    def get(self, mesh_model_id: str) -> ModelEntry | None:
        """Exact mesh_model_id lookup (split on the FIRST '::', §14.3)."""
        return self._entries.get(mesh_model_id)

    def entries(self) -> list[ModelEntry]:
        return list(self._entries.values())


def _json_dumps(payload: dict[str, object]) -> str:
    import json

    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
