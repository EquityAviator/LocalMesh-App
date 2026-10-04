"""Durable Tasks service (M7, §13.9, FR-MM-04).

Contract (§13.9, shape fixed at the M0 stub — this is the delivery):
- `POST /tasks {type: chat|vision|transcribe|doc_qa, input, options}` →
  `202 {task_id, status: "queued"}`
- `GET /tasks/{id}` → `{status, progress, result?, error?}`
- `GET /tasks/{id}/events` (SSE)
- `DELETE /tasks/{id}` (cancel running / fetch-ack delete)
- Attachments: `PUT /tasks/{id}/attachments/{name}` with size caps.
- "Results retained ≤ 1 h, encrypted at rest, deleted on fetch-ack or
  expiry (ADR-011)."

Semantics:
- chat/vision tasks ARE generations: they run through the §16 Scheduler
  (concurrency, queue, cancel) exactly like a chat request — non-streamed,
  with the same Appendix D error mapping.
- transcribe tasks call the FR-MM-02 Whisper-class adapter directly (not a
  generation; no scheduler slot).
- doc_qa = FR-MM-03 retrieval (top-k sections) + a chat generation with the
  retrieved context inlined; the answer cites source ids (Metadata).
- Results and attachments are AES-256-GCM ciphertext at rest
  (security.task_crypto); the expiry sweep purges rows past `expires_at`.
- Local notifications (FR-MM-04): the SSE event stream + status polling IS
  the v1 surface; a native OS notification is a Phone-side concern (WP-13).

Layer position: core. Depends on ports + injected services only (no httpx,
no store import — the store arrives via the app factory).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from localmesh_agent.adapters.ports import (
    CancelToken,
    ChatMessage,
    ChatRequest,
    EmbeddingBackend,
    TranscriptionBackend,
)
from localmesh_agent.core.errors import MeshError
from localmesh_agent.observability.logging import get_logger
from localmesh_agent.security import task_crypto

log = get_logger("tasks")

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}


class TaskService:
    """Owns task execution, SSE fan-out and the §13.9 retention sweep."""

    def __init__(
        self,
        store: Any,
        *,
        key: bytes,
        retention_s: int,
        max_concurrent: int,
        scheduler: Any,
        router: Any,
        transcriber: TranscriptionBackend | None,
        embedder: EmbeddingBackend | None,
        embed_model_backend_id: str | None,
        new_task_id: Any,  # callable -> 'tk_' + UUIDv7
        clock: Any,
    ) -> None:
        self._store = store
        self._key = key
        self._retention_s = retention_s
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._scheduler = scheduler
        self._router = router
        self._transcriber = transcriber
        self._rag: Any = None  # wired by the app factory (RagService)
        self._new_task_id = new_task_id
        self._clock = clock
        self._jobs: dict[str, asyncio.Task[None]] = {}
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}
        self._sweeper: asyncio.Task[None] | None = None

    # -- wiring --------------------------------------------------------------

    def set_rag(self, rag: Any) -> None:
        self._rag = rag

    # -- lifecycle -------------------------------------------------------------

    def start(self) -> None:
        if self._sweeper is None or self._sweeper.done():
            self._sweeper = asyncio.create_task(self._sweep_loop(), name="task-retention")

    async def stop(self) -> None:
        sweeper = self._sweeper
        self._sweeper = None
        if sweeper is not None:
            sweeper.cancel()
            try:
                await sweeper
            except asyncio.CancelledError:
                pass
        for task_id, job in list(self._jobs.items()):
            job.cancel()
            try:
                await job
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 — shutdown best effort
                pass
            _ = task_id
        self._jobs.clear()

    async def _sweep_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            try:
                purged = self._store.purge_expired_tasks(self._clock.now_wall())
                if purged:
                    log.info(
                        "tasks_purged",
                        extra={"component": "tasks", "status": "ok", "count": purged},
                    )
            except Exception:  # noqa: BLE001 — retention must never crash the loop
                log.warning(
                    "tasks_purge_failed",
                    extra={"component": "tasks", "status": "error"},
                )

    # -- creation (§13.9 POST /tasks) -------------------------------------------

    async def create_task(
        self, device_id: str, task_type: str, payload_input: dict[str, Any], options: dict[str, Any]
    ) -> dict[str, Any]:
        task_id = self._new_task_id()
        input_blob = json.dumps(payload_input, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
        input_nonce, enc_input = task_crypto.encrypt(
            self._key, input_blob, aad=task_id.encode("utf-8")
        )
        enc_options: bytes | None = None
        options_nonce: bytes | None = None
        if options:
            options_blob = json.dumps(options, separators=(",", ":"), ensure_ascii=False).encode(
                "utf-8"
            )
            options_nonce, enc_options = task_crypto.encrypt(
                self._key, options_blob, aad=task_id.encode("utf-8")
            )
        self._store.create_task(
            task_id,
            device_id,
            task_type,
            enc_input,
            input_nonce,
            enc_options,
            options_nonce,
            self._clock.now_wall(),
        )
        job = asyncio.create_task(self._run(task_id, task_type))
        self._jobs[task_id] = job
        self._publish(task_id, {"status": "queued", "progress": 0})
        return {"task_id": task_id, "status": "queued"}

    # -- execution ----------------------------------------------------------------

    async def _run(self, task_id: str, task_type: str) -> None:
        async with self._semaphore:
            row = self._store.get_task(task_id)
            if row is None or row["status"] != "queued":
                return  # cancelled/deleted before start (fetch-ack race)
            device_id = str(row["device_id"])
            try:
                payload_input, options = self._decode_task(task_id, row)
            except MeshError as error:
                # The runner must never die with a stuck-queued row (QA fix):
                # decode failures map to a terminal failed task.
                self._finish(task_id, "failed", None, error, error_code=error.code)
                return
            self._store.set_task_status(task_id, "running", started_at=self._clock.now_wall())
            self._publish(task_id, {"status": "running", "progress": 5})
            try:
                if task_type in ("chat", "vision"):
                    await self._run_chat(task_id, task_type, payload_input, device_id)
                elif task_type == "transcribe":
                    await self._run_transcribe(task_id, payload_input)
                elif task_type == "doc_qa":
                    await self._run_doc_qa(task_id, payload_input, options, device_id)
                else:  # defensive; policy validation already rejected
                    raise MeshError("INVALID_REQUEST", f"Unknown task type {task_type!r}.")
            except asyncio.CancelledError:
                self._finish(task_id, "cancelled", None, None)
                raise
            except MeshError as error:
                self._finish(task_id, "failed", None, error, error_code=error.code)
            except Exception:  # noqa: BLE001 — INTERNAL envelope, details never leak
                self._finish(
                    task_id, "failed", None, MeshError("INTERNAL", "Task failed internally.")
                )

    def _decode_task(
        self, task_id: str, row: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Decrypt the task definition in memory (ciphertext at rest only)."""
        from cryptography.exceptions import InvalidTag

        try:
            input_blob = task_crypto.decrypt(
                self._key,
                bytes(row["input_nonce"]),
                bytes(row["enc_input"]),
                aad=task_id.encode("utf-8"),
            )
            payload_input = json.loads(input_blob)
            options: dict[str, Any] = {}
            if row["enc_options"] is not None:
                options_blob = task_crypto.decrypt(
                    self._key,
                    bytes(row["options_nonce"]),
                    bytes(row["enc_options"]),
                    aad=task_id.encode("utf-8"),
                )
                options = json.loads(options_blob)
        except (InvalidTag, ValueError) as exc:
            raise MeshError("INTERNAL", "Task definition could not be recovered.") from exc
        if not isinstance(payload_input, dict):
            raise MeshError("INTERNAL", "Task definition could not be recovered.")
        return payload_input, options if isinstance(options, dict) else {}

    async def _run_chat(
        self, task_id: str, task_type: str, payload_input: dict[str, Any], device_id: str
    ) -> None:
        backend, backend_model_id, entry = self._router.resolve(str(payload_input["model"]))
        if task_type == "vision" and "vision" not in entry.capabilities:
            raise MeshError(
                "UNSUPPORTED_CAPABILITY",
                "The selected model does not report vision (§13.5).",
                details={"required_capability": "vision"},
            )
        messages = tuple(
            ChatMessage(
                role=message["role"],  # Literal — policy-validated (§13.6)
                content=message["content"],  # str | parts tuple (policy-validated)
            )
            for message in payload_input["messages"]
        )
        text = await self._collect(
            backend,
            ChatRequest(
                model=entry.mesh_model_id,
                backend_model_id=backend_model_id,
                messages=messages,
                stream=False,
                temperature=payload_input.get("temperature"),
                max_tokens=payload_input.get("max_tokens"),
            ),
            device_id,
        )
        self._store.set_task_progress(task_id, 90)
        self._finish(task_id, "succeeded", {"type": task_type, "message": text}, None)

    async def _run_transcribe(self, task_id: str, payload_input: dict[str, Any]) -> None:
        if self._transcriber is None:
            raise MeshError(
                "UNSUPPORTED_CAPABILITY",
                "No whisper-class Backend is configured (FR-MM-02).",
                details={"required_capability": "speech_to_text"},
            )
        attachment_name = str(payload_input.get("audio", ""))
        audio = await self._read_attachment(task_id, attachment_name)
        self._store.set_task_progress(task_id, 40)
        request = _build_transcription_request(
            model=str(payload_input.get("model", "")),
            audio=audio,
            filename=attachment_name,
            language=payload_input.get("language"),
        )
        text = await self._transcriber.transcribe(request)
        self._finish(task_id, "succeeded", {"type": "transcribe", "text": text}, None)

    async def _run_doc_qa(
        self,
        task_id: str,
        payload_input: dict[str, Any],
        options: dict[str, Any],
        device_id: str,
    ) -> None:
        if self._rag is None or not self._rag.available:
            raise MeshError(
                "UNSUPPORTED_CAPABILITY",
                "RAG is unavailable: no embedding-capable Backend (FR-MM-03).",
                details={"required_capability": "embedding"},
            )
        question = str(payload_input.get("question", ""))
        sources = options.get("source_ids") if isinstance(options.get("source_ids"), list) else None
        hits = await self._rag.retrieve(question)
        if sources is not None:
            allowed = {str(s) for s in sources}
            hits = [hit for hit in hits if hit["source_id"] in allowed]
        self._store.set_task_progress(task_id, 60)
        chat_model = str(payload_input.get("model", ""))
        context = "\n\n".join(f"[{hit['source_id']}#{hit['seq']}] {hit['text']}" for hit in hits)
        backend, backend_model_id, entry = self._router.resolve(chat_model)
        messages = (
            ChatMessage(
                role="user",
                content=(
                    f"Answer using ONLY the provided context.\n\n"
                    f"Context:\n{context}\n\nQuestion: {question}"
                ),
            ),
        )
        text = await self._collect(
            backend,
            ChatRequest(
                model=entry.mesh_model_id,
                backend_model_id=backend_model_id,
                messages=messages,
                stream=False,
                max_tokens=payload_input.get("max_tokens"),
            ),
            device_id,
        )
        self._finish(
            task_id,
            "succeeded",
            {
                "type": "doc_qa",
                "answer": text,
                "sources": [
                    {"source_id": hit["source_id"], "seq": hit["seq"], "score": hit["score"]}
                    for hit in hits
                ],
            },
            None,
        )

    async def _collect(self, backend: Any, request: ChatRequest, device_id: str) -> str:
        """Run a non-stream generation through the §16 Scheduler (a task chat
        IS a generation: concurrency caps + cancel semantics apply)."""
        job = self._scheduler.admit(
            request_id=self._new_task_id(), device_id=device_id, backend_id=backend.id
        )
        collected: list[str] = []
        try:
            await self._scheduler.await_running(job)
            async for chunk in backend.stream_chat(request, job.token):
                if chunk.delta_content is not None:
                    collected.append(chunk.delta_content)
        finally:
            job.token.cancel()
            self._scheduler.release(job)
        return "".join(collected)

    async def _read_attachment(self, task_id: str, name: str, *, wait_s: float = 5.0) -> bytes:
        """Decrypt one attachment; the client uploads AFTER the 202, so the
        runner tolerates a short arrival window (§13.9 flow ordering)."""
        deadline = self._clock.now_monotonic() + wait_s
        while True:
            for row in self._store.list_task_files(task_id):
                if row["name"] == name:
                    from localmesh_agent.security.task_crypto import decrypt

                    return decrypt(
                        self._key,
                        bytes(row["file_nonce"]),
                        bytes(row["enc_data"]),
                        aad=task_id.encode("utf-8"),
                    )
            if self._clock.now_monotonic() >= deadline:
                break
            await asyncio.sleep(0.05)
        raise MeshError(
            "INVALID_REQUEST",
            "Referenced attachment does not exist for this task.",
            details={"attachment_missing": True},
        )

    def _finish(
        self,
        task_id: str,
        status: str,
        result: dict[str, Any] | None,
        error: MeshError | None,
        *,
        error_code: str | None = None,
    ) -> None:
        now = self._clock.now_wall()
        enc_result: bytes | None = None
        nonce: bytes | None = None
        if result is not None:
            nonce, enc_result = task_crypto.encrypt(
                self._key,
                json.dumps(result, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
            )
        code = error_code or (error.code if error is not None else None)
        message = error.message if error is not None else None
        self._store.finish_task(
            task_id,
            status,
            now,
            now + self._retention_s,  # §13.9: retained ≤ 1 h
            enc_result=enc_result,
            result_nonce=nonce,
            error_code=code,
            error_text=message,
        )
        self._jobs.pop(task_id, None)
        event: dict[str, Any] = {"status": status, "progress": 100}
        if code is not None:
            event["error_code"] = code
        self._publish(task_id, event)
        # Durable wake-up for SSE waiters: a terminal marker queue item.

    # -- read/delete/events (§13.9) ------------------------------------------------

    def task_view(self, task_id: str, device_id: str) -> dict[str, Any]:
        row = self._store.get_task(task_id)
        if row is None or row["device_id"] != device_id:
            # 404 per API-REQ-01 semantics: never disclose other devices' ids.
            raise MeshError("INVALID_REQUEST", "No such task.", status_override=404)
        view: dict[str, Any] = {
            "task_id": row["task_id"],
            "type": row["type"],
            "status": row["status"],
            "progress": int(row["progress"]),
            "created_at": int(row["created_at"]),
        }
        if row["status"] in TERMINAL_STATUSES:
            view["expires_at"] = row["expires_at"]
            if row["enc_result"] is not None:
                result = json.loads(
                    task_crypto.decrypt(
                        self._key, bytes(row["result_nonce"]), bytes(row["enc_result"])
                    )
                )
                view["result"] = result
            if row["error_code"] is not None:
                view["error"] = {
                    "code": row["error_code"],
                    "message": row["error_text"],
                }
        return view

    def delete_task(self, task_id: str, device_id: str) -> bool:
        row = self._store.get_task(task_id)
        if row is None or row["device_id"] != device_id:
            return False
        job = self._jobs.get(task_id)
        if job is not None and not job.done():
            job.cancel()  # runner _finish()es the row as cancelled
            return True
        deleted: bool = bool(self._store.delete_task(task_id))  # fetch-ack delete
        self._publish(task_id, {"status": "deleted", "progress": 0})
        return deleted

    def subscribe(self, task_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=64)
        self._subscribers.setdefault(task_id, set()).add(queue)
        return queue

    def unsubscribe(self, task_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        listeners = self._subscribers.get(task_id)
        if listeners is not None:
            listeners.discard(queue)
            if not listeners:
                self._subscribers.pop(task_id, None)

    def _publish(self, task_id: str, event: dict[str, Any]) -> None:
        for queue in list(self._subscribers.get(task_id, ())):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:  # slow consumer: drop best effort
                pass


def task_id_token(token: CancelToken) -> str:
    """Scheduler request-id shim (kept for API-REQ-01 correlation tests)."""
    return f"task-{id(token):x}"


def _build_transcription_request(
    *, model: str, audio: bytes, filename: str, language: str | None
) -> Any:
    from localmesh_agent.adapters.ports import TranscriptionRequest

    return TranscriptionRequest(model=model, audio=audio, filename=filename, language=language)
