"""LM Studio Backend adapter (§6.1, §10.3).

Verified surface (§6.1, `[VERIFIED 2026-10-03]`):
- native REST API `/api/v1/*`: `GET /api/v1/models`,
  `POST /api/v1/models/load`, `POST /api/v1/models/unload`;
- OpenAI-compatible `GET /v1/models`, `POST /v1/chat/completions` (SSE);
- optional Bearer token (configured via keyring `auth_ref`).

Known-unknown handling (§6.1 "Unknown", R-03):
- Exact JSON field names of `/api/v1/models` are `[UNVERIFIED]` — this adapter
  extracts only the verified `id`; every other §13.5 field stays null and a
  schema-drift warning is logged (§10.3 rule 2). Extending the mapping is
  gated on recorded fixtures (docs/fixtures/CAPTURE.md; contract tests).
- Load/unload request/response shapes are `[UNVERIFIED]`; the adapter sends
  `{"model": <id>}` and tolerates any 2xx response.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

from localmesh_agent.adapters.backends.openai_compat import (
    OpenAICompatBackend,
    as_str,
    warn_schema_drift,
)
from localmesh_agent.adapters.ports import (
    BackendCaps,
    BackendModel,
    BackendStatus,
    CancelToken,
    ChatChunk,
    ChatRequest,
)
from localmesh_agent.core.errors import MeshError

_NATIVE_MODEL_LIST_KEYS = {"id"}  # §6.1: only `id` is verified


def parse_native_model_list(data: list[Any]) -> tuple[list[BackendModel], bool]:
    """Pure parse of a native `/api/v1/models` `data` list (§6.1 Unknown).

    Extracts the verified `id` only; any other/missing field marks drift so
    callers log a schema-drift warning (§10.3 rule 2). Returns (models, drift).
    Contract tests run this against recorded fixtures when they exist.
    """
    models: list[BackendModel] = []
    drift = False
    for item in data:
        if not isinstance(item, dict):
            drift = True
            continue
        model_id = as_str(item, "id")
        if model_id is None:
            drift = True
            continue
        if set(item) - _NATIVE_MODEL_LIST_KEYS:
            drift = True  # unmapped native fields exist (§6.1 Unknown)
        models.append(BackendModel(backend_model_id=model_id))
    return models, drift


class LMStudioBackend(OpenAICompatBackend):
    """LM Studio adapter (§10.3 column 1). Caps: list, stream, load_unload."""

    kind = "lmstudio"

    def __init__(
        self,
        backend_id: str,
        base_url: str,
        *,
        auth_token: str | None = None,
        client: httpx.AsyncClient | None = None,
        first_token_timeout_s: float | None = None,
        total_stream_cap_s: float | None = None,
    ) -> None:
        kwargs: dict[str, Any] = {"auth_token": auth_token, "client": client}
        if first_token_timeout_s is not None:
            kwargs["first_token_timeout_s"] = first_token_timeout_s
        if total_stream_cap_s is not None:
            kwargs["total_stream_cap_s"] = total_stream_cap_s
        super().__init__(backend_id, base_url, **kwargs)
        self.caps = BackendCaps(
            {
                "list_models": True,
                "stream_chat": True,
                "load_unload": True,  # §10.3: native load/unload [VERIFIED]
                "keep_warm": False,  # §10.3: keep-warm n/a for LM Studio
                "embeddings": False,
                "vision": False,
                "audio_in": False,
            }
        )

    async def probe(self) -> BackendStatus:
        """Probe with `GET /v1/models` (cheap) — §10.3."""
        return await super().probe()

    async def list_models(self) -> list[BackendModel]:
        """Native `GET /api/v1/models` first (fields UNVERIFIED — parse
        defensively), fallback to OpenAI `GET /v1/models` (§10.3)."""
        native = await self._get_json("/api/v1/models")
        if native is not None:
            data = native.get("data")
            if isinstance(data, list) and data:
                models, drift = parse_native_model_list(data)
                if drift:
                    warn_schema_drift(self.id, "/api/v1/models")
                return models
        return await super().list_models()  # OpenAI fallback (§10.3)

    async def load_model(self, backend_model_id: str) -> None:
        """`POST /api/v1/models/load` — request/response shapes UNVERIFIED
        (§6.1); tolerate any 2xx, map failures to MeshError (§10.3 rule 3)."""
        await self._load_unload("/api/v1/models/load", backend_model_id)

    async def unload_model(self, backend_model_id: str) -> None:
        await self._load_unload("/api/v1/models/unload", backend_model_id)

    async def _load_unload(self, path: str, backend_model_id: str) -> None:
        try:
            response = await self._client.post(
                self._url(path),
                json={"model": backend_model_id},  # [UNVERIFIED] shape (§6.1)
                headers=self._headers(),
            )
        except httpx.HTTPError as exc:
            raise MeshError("BACKEND_UNAVAILABLE", "Backend transport failed during load.") from exc
        if response.status_code >= 500:
            raise MeshError("BACKEND_UNAVAILABLE", "Backend returned a server error.")
        if response.status_code in (401, 403):
            raise MeshError("BACKEND_UNAVAILABLE", "Backend rejected credentials.")
        if response.status_code == 404:
            raise MeshError("MODEL_NOT_FOUND", "Model is unknown to the Backend.")
        if response.status_code >= 400:
            raise MeshError("BACKEND_PROTOCOL", "Backend rejected the load/unload request.")
        # Any 2xx accepted; body shape UNVERIFIED — not parsed (§6.1).

    def stream_chat(  # noqa: D102  # async generator (PEP 525)
        self, req: ChatRequest, cancel: CancelToken
    ) -> AsyncIterator[ChatChunk]:
        return super().stream_chat(req, cancel)
