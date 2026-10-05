"""Ollama Backend adapter (§6.2, §10.3).

Verified surface (§6.2, `[VERIFIED 2026-10-03]`):
- `GET /api/tags` (models on disk), `GET /api/ps` (models in memory, incl.
  VRAM footprint), `POST /api/show` (details incl. context length,
  quantization);
- OpenAI-compatible `POST /v1/chat/completions` stream=true for chat;
- **No authentication** — the adapter never sends Authorization (§6.2;
  Appendix C trap "Ollama has auth / API keys").

Unknown handling (§6.2): whether `keep_alive` is honored on the `/v1` path is
`[UNVERIFIED]` — keep-warm therefore uses the **native** path (§10.3), a
`POST /api/chat` ping with empty messages (the call itself refreshes the
server's idle timer; explicit keep_alive tuning arrives with WP-15/§16.5).

Model state (§13.5): a model present in `/api/ps` is `loaded`, otherwise
`unloaded` (it exists on disk via `/api/tags`). Defensive parsing throughout:
missing/renamed fields -> null + schema-drift warning, never an exception
(§10.3 rule 2). `/api/show` results are cached per model id (§10.3).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from localmesh_agent.adapters.backends.openai_compat import (
    OpenAICompatBackend,
    as_int,
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


def parse_ps_names(ps_payload: dict[str, Any] | None) -> set[str]:
    """Pure parse of `/api/ps`: names of models currently in memory (§6.2)."""
    if ps_payload is None:
        return set()
    entries = ps_payload.get("models")
    if not isinstance(entries, list):
        return set()
    names: set[str] = set()
    for item in entries:
        if isinstance(item, dict):
            name = as_str(item, "name") or as_str(item, "model")
            if name:
                names.add(name)
    return names


def parse_tag_entry(item: dict[str, Any], loaded: bool, vram: int | None) -> BackendModel | None:
    """Pure parse of one `/api/tags` entry (§6.2 field names; defensive)."""
    name = as_str(item, "name") or as_str(item, "model")
    if name is None:
        return None
    details = item.get("details")
    details = details if isinstance(details, dict) else {}
    return BackendModel(
        backend_model_id=name,
        display_name=as_str(item, "model"),
        # §13.5 state via /api/ps presence (§10.3)
        state="loaded" if loaded else "unloaded",
        quantization=as_str(details, "quantization_level"),
        parameter_size=as_str(details, "parameter_size"),
        size_bytes=as_int(item, "size"),
        vram_estimate_bytes=vram,
    )


class OllamaBackend(OpenAICompatBackend):
    """Ollama adapter (§10.3 column 2). Caps: list, stream, keep_warm."""

    kind = "ollama"

    def __init__(
        self,
        backend_id: str,
        base_url: str,
        *,
        client: httpx.AsyncClient | None = None,
        first_token_timeout_s: float | None = None,
        total_stream_cap_s: float | None = None,
    ) -> None:
        kwargs: dict[str, Any] = {"auth_token": None, "client": client}
        if first_token_timeout_s is not None:
            kwargs["first_token_timeout_s"] = first_token_timeout_s
        if total_stream_cap_s is not None:
            kwargs["total_stream_cap_s"] = total_stream_cap_s
        super().__init__(backend_id, base_url, **kwargs)
        self.caps = BackendCaps(
            {
                "list_models": True,
                "stream_chat": True,
                "load_unload": False,  # §10.3: n/a — no explicit load
                "keep_warm": True,  # §10.3: keep-warm via native ping
                "embeddings": False,
                "vision": False,
                "audio_in": False,
            }
        )
        self._show_cache: dict[str, dict[str, Any]] = {}

    def _headers(self, accept: str = "application/json") -> dict[str, str]:
        # Ollama has no auth (§6.2): never send Authorization.
        return {"Accept": accept}

    async def probe(self) -> BackendStatus:
        """Probe with `GET /api/tags` (§10.3)."""
        payload = await self._get_json("/api/tags")
        if payload is None:
            return BackendStatus(backend_id=self.id, status="down")
        return BackendStatus(backend_id=self.id, status="up", version=None)

    async def list_models(self) -> list[BackendModel]:
        """`GET /api/tags` + `GET /api/ps` (loaded) + `POST /api/show` per
        model (cached) — §10.3."""
        tags = await self._get_json("/api/tags")
        if tags is None:
            raise MeshError("BACKEND_UNAVAILABLE", "Backend did not answer /api/tags.")
        entries = tags.get("models")
        if not isinstance(entries, list):
            warn_schema_drift(self.id, "/api/tags")
            return []

        ps = await self._get_json("/api/ps")
        if ps is None:
            warn_schema_drift(self.id, "/api/ps")
        loaded_names = parse_ps_names(ps)

        models: list[BackendModel] = []
        for item in entries:
            if not isinstance(item, dict):
                warn_schema_drift(self.id, "/api/tags")
                continue
            name = as_str(item, "name") or as_str(item, "model")
            if name is None:
                warn_schema_drift(self.id, "/api/tags")
                continue
            vram: int | None = None
            ps_entries = ps.get("models", []) if isinstance(ps, dict) else []
            for ps_item in ps_entries:
                if (
                    isinstance(ps_item, dict)
                    and (as_str(ps_item, "name") or as_str(ps_item, "model")) == name
                ):
                    vram = as_int(ps_item, "size_vram")
                    break
            context_length = await self._context_length_cached(name)
            model = parse_tag_entry(item, name in loaded_names, vram)
            if model is None:
                warn_schema_drift(self.id, "/api/tags")
                continue
            models.append(
                BackendModel(
                    backend_model_id=model.backend_model_id,
                    display_name=model.display_name,
                    state=model.state,
                    context_length=context_length,
                    quantization=model.quantization,
                    parameter_size=model.parameter_size,
                    size_bytes=model.size_bytes,
                    vram_estimate_bytes=model.vram_estimate_bytes,
                )
            )
        return models

    async def _context_length_cached(self, name: str) -> int | None:
        """`POST /api/show` (cached) — context length from `model_info` (§6.2).

        The key is architecture-suffixed (e.g. `qwen2.context_length`);
        a suffix match on `.context_length` is defensive, not name-guessing of
        model metadata (§13.5 applies to model names, not fixed API keys).
        """
        cached = self._show_cache.get(name)
        if cached is None:
            try:
                response = await self._client.post(
                    self._url("/api/show"), json={"model": name}, headers=self._headers()
                )
            except httpx.HTTPError:
                warn_schema_drift(self.id, "/api/show")
                return None
            if response.status_code != 200:
                warn_schema_drift(self.id, "/api/show")
                return None
            try:
                cached = response.json()
            except json.JSONDecodeError:
                warn_schema_drift(self.id, "/api/show")
                return None
            if not isinstance(cached, dict):
                return None
            self._show_cache[name] = cached
        model_info = cached.get("model_info")
        if not isinstance(model_info, dict):
            return None
        for key, value in model_info.items():
            if isinstance(key, str) and key.endswith(".context_length") and isinstance(value, int):
                return value
        return None

    async def keep_warm(self, backend_model_id: str) -> None:
        """Native ping: `POST /api/chat` with empty messages (§10.3, §6.2).

        keep_alive is intentionally omitted — the call itself refreshes the
        server's idle-unload timer; explicit tuning is WP-15 (§16.5).
        """
        if not self.caps["keep_warm"]:
            raise MeshError("UNSUPPORTED_CAPABILITY", "Backend cannot keep models warm.")
        try:
            response = await self._client.post(
                self._url("/api/chat"),
                json={"model": backend_model_id, "messages": []},
                headers=self._headers(),
            )
        except httpx.HTTPError as exc:
            raise MeshError(
                "BACKEND_UNAVAILABLE", "Backend transport failed during keep-warm."
            ) from exc
        if response.status_code >= 500:
            raise MeshError("BACKEND_UNAVAILABLE", "Backend returned a server error.")

    def stream_chat(  # noqa: D102  # async generator (PEP 525)
        self, req: ChatRequest, cancel: CancelToken
    ) -> AsyncIterator[ChatChunk]:
        return super().stream_chat(req, cancel)
