"""Whisper-class speech-to-text Backend adapter (M7, FR-MM-02; S-13).

FR-MM-02: "Voice note transcription via a Whisper-class adapter (separate
service)". The spec's S-13 decision row explicitly plans a standalone
Whisper-service adapter and forbids assuming LM Studio provides STT — hence
the dedicated `whisper` backend kind (config.py BACKEND_KINDS, [DESIGN] name
per FR-MM-02).

Wire surface (OpenAI audio API conventions, `[UNVERIFIED_SHAPE]` until a real
service is captured per CAPTURE.md — same fixture rule as every Backend):
- `GET  /v1/models` — model listing (same defensive parse as §10.3).
- `POST /v1/audio/transcriptions` — multipart (file, model, language?);
  response `{ "text": "…" }`.

Adapter rules (§10.3): bounded timeouts, error mapping to Appendix D, raw
backend bodies never surfaced (SEC-N3), no Content in logs (§17.10 — the
transcript itself is Content and is never logged).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx

from localmesh_agent.adapters.backends.openai_compat import (
    OpenAICompatBackend,
    warn_schema_drift,
)
from localmesh_agent.adapters.ports import (
    CONNECT_TIMEOUT_S,
    DEFAULT_FIRST_TOKEN_TIMEOUT_S,
    IDLE_CHUNK_TIMEOUT_S,
    BackendStatus,
    CancelToken,
    ChatChunk,
    ChatRequest,
    TranscriptionRequest,
)
from localmesh_agent.core.errors import MeshError
from localmesh_agent.observability.logging import get_logger

log = get_logger("adapters")

_TRANSCRIBE_TIMEOUT_S = 300.0  # voice notes are short; generous but bounded


class WhisperBackend(OpenAICompatBackend):
    """Dedicated speech-to-text service adapter (kind="whisper", FR-MM-02).

    Inherits the §10.3-rule-5 SSE parser and defensive `/v1/models` listing;
    chat is explicitly NOT supported (a Whisper service does not generate
    chat completions — calling stream_chat here would be a category error).
    """

    kind = "whisper"

    def __init__(
        self,
        backend_id: str,
        base_url: str,
        *,
        auth_token: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            backend_id,
            base_url,
            auth_token=auth_token,
            first_token_timeout_s=DEFAULT_FIRST_TOKEN_TIMEOUT_S,
            total_stream_cap_s=_TRANSCRIBE_TIMEOUT_S,
            idle_chunk_timeout_s=IDLE_CHUNK_TIMEOUT_S,
            client=client
            or httpx.AsyncClient(
                timeout=httpx.Timeout(
                    CONNECT_TIMEOUT_S, read=_TRANSCRIBE_TIMEOUT_S, write=60.0, pool=30.0
                ),
                limits=httpx.Limits(max_connections=2, max_keepalive_connections=1),
            ),
        )
        self.caps["audio_in"] = True
        self.caps["stream_chat"] = False

    async def probe(self) -> BackendStatus:
        status = await super().probe()
        return status

    def stream_chat(  # noqa: D102  # async generator (PEP 525)
        self, req: ChatRequest, cancel: CancelToken
    ) -> AsyncIterator[ChatChunk]:
        raise MeshError(
            "UNSUPPORTED_CAPABILITY",
            "The whisper Backend performs speech-to-text, not chat (FR-MM-02).",
        )
        yield  # pragma: no cover — makes this an async generator, never runs
        _ = req, cancel  # pragma: no cover

    async def transcribe(self, request: TranscriptionRequest) -> str:
        """`POST /v1/audio/transcriptions` (multipart) → transcript text.

        The audio bytes are the request Content; they are streamed to the
        loopback STT service and never logged or persisted here (§17.10).
        """
        fields: dict[str, str] = {"model": request.model}
        if request.language is not None:
            fields["language"] = request.language
        files = {"file": (request.filename, request.audio, "application/octet-stream")}
        try:
            response = await self._client.post(
                self._url("/v1/audio/transcriptions"),
                data=fields,
                files=files,
                headers=self._headers(),
            )
        except httpx.HTTPError as exc:
            raise MeshError("BACKEND_UNAVAILABLE", "Transcription transport failed.") from exc
        if response.status_code != 200:
            raise MeshError("BACKEND_UNAVAILABLE", "Transcription request rejected by Backend.")
        try:
            payload = response.json()
        except ValueError as exc:
            warn_schema_drift(self.id, "/v1/audio/transcriptions")
            raise MeshError("BACKEND_PROTOCOL", "Transcription answer was malformed.") from exc
        text = payload.get("text") if isinstance(payload, dict) else None
        if not isinstance(text, str):
            warn_schema_drift(self.id, "/v1/audio/transcriptions")
            raise MeshError("BACKEND_PROTOCOL", "Transcription answer was malformed.")
        return text
