"""Local RAG pipeline (M7, FR-MM-03): document upload → embedding → retrieval.

FR-MM-03: "Document upload + embedding + retrieval (RAG) on the Agent host."
Design [DESIGN where §13.9 is silent]:

- Documents arrive as task attachments (`doc_qa` / `PUT /tasks/{id}/
  attachments/{name}`); text is extracted for `.txt`/`.md` verbatim; other
  types are stored but NOT parsed in v1 (honest scope — no OCR before a
  milestone that names it, §4.4 non-goals).
- Chunking: fixed-size sliding window (chars), `ceil(chars/4)` token
  estimate only for prompts — never quality claims (§16.6 est_tokens rule).
- Embeddings come from the §6-documented OpenAI-compatible `/v1/embeddings`
  surface (LM Studio / Ollama) — the same Backend adapters, no new model
  inference in the Agent.
- Retrieval: cosine top-k over stored vectors (in-process scan; v1 scale is
  a household, §21.5).
- Document text at rest is ciphertext (§13.9 + ADR-011; see task_crypto).
"""

from __future__ import annotations

import hashlib
import math
import struct
from typing import Any

from localmesh_agent.adapters.ports import EmbeddingBackend
from localmesh_agent.core.errors import MeshError
from localmesh_agent.observability.logging import get_logger

log = get_logger("rag")

CHUNK_CHARS = 1200
CHUNK_OVERLAP_CHARS = 150
TOP_K = 4

TEXT_SUFFIXES = (".txt", ".md")  # v1 parses plain text only (honest scope)


def chunk_text(
    text: str, max_chars: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP_CHARS
) -> list[str]:
    """Sliding-window chunking; never returns empty chunks."""
    if max_chars <= overlap:
        raise ValueError("max_chars must exceed overlap")
    cleaned = text.strip()
    if not cleaned:
        return []
    chunks: list[str] = []
    start = 0
    n = len(cleaned)
    while start < n:
        piece = cleaned[start : start + max_chars].strip()
        if piece:
            chunks.append(piece)
        if start + max_chars >= n:
            break
        start += max_chars - overlap
    return chunks


def pack_vector(values: list[float]) -> bytes:
    return struct.pack(f"<{len(values)}f", *values)


def unpack_vector(blob: bytes) -> list[float]:
    count = len(blob) // 4
    return list(struct.unpack(f"<{count}f", blob[: count * 4]))


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class RagService:
    """Embedding + retrieval over the encrypted section store."""

    def __init__(
        self,
        store: Any,  # Store port surface (M7 methods); core cannot import store
        embedder: EmbeddingBackend | None,
        embed_model_backend_id: str | None,
        key: bytes,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._embed_model = embed_model_backend_id
        self._key = key

    @property
    def available(self) -> bool:
        return self._embedder is not None and self._embed_model is not None

    def configure_embedder(self, embedder: EmbeddingBackend, backend_model_id: str) -> None:
        """Wire the embedding-capable adapter (app factory, after the registry
        refresh — §10.6: the embedder comes from the Capability Registry, so
        it can only be resolved once backends have answered)."""
        self._embedder = embedder
        self._embed_model = backend_model_id

    def extract_text(self, name: str, data: bytes) -> str | None:
        """Parse an attachment into text; None when the type is out of v1 scope."""
        lowered = name.lower()
        if lowered.endswith(TEXT_SUFFIXES):
            try:
                return data.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    return data.decode("latin-1")
                except UnicodeDecodeError:
                    return None
        return None

    async def index_document(self, name: str, data: bytes) -> dict[str, Any]:
        """Chunk → embed → persist (ciphertext at rest). Returns the source row."""
        text = self.extract_text(name, data)
        if text is None:
            raise MeshError(
                "UNSUPPORTED_CAPABILITY",
                "Only .txt/.md documents are indexed in v1 (FR-MM-03 scope).",
            )
        if not self.available or self._embedder is None or self._embed_model is None:
            raise MeshError(
                "UNSUPPORTED_CAPABILITY",
                "No embedding-capable Backend is configured/online (FR-MM-03).",
                details={"required_capability": "embedding"},
            )
        chunks = chunk_text(text)
        if not chunks:
            raise MeshError("INVALID_REQUEST", "Document contains no indexable text.")
        vectors = await self._embedder.embed(tuple(chunks), self._embed_model)
        import time as _time

        source_id = f"doc_{int(_time.time() * 1000):x}"  # monotonic id, no Content
        self._store.insert_rag_source(
            source_id,
            name,
            hashlib.sha256(data).digest(),
            len(data),
            int(_time.time()),
        )
        from localmesh_agent.security.task_crypto import encrypt

        for seq, (chunk, vector) in enumerate(zip(chunks, vectors, strict=False)):
            nonce, ciphertext = encrypt(self._key, chunk.encode("utf-8"))
            row_id = self._store.insert_rag_section(source_id, seq, ciphertext, nonce)
            self._store.insert_rag_vector(
                row_id, self._embed_model, len(vector), pack_vector(vector)
            )
        log.info(
            "rag_indexed",
            extra={"component": "rag", "status": "ok", "sections": len(chunks)},
        )
        return {
            "source_id": source_id,
            "name": name,
            "sections": len(chunks),
            "model": self._embed_model,
        }

    async def retrieve(self, query: str, k: int = TOP_K) -> list[dict[str, Any]]:
        """Cosine top-k over indexed sections; decrypts hits in memory only."""
        if not self.available or self._embedder is None or self._embed_model is None:
            raise MeshError(
                "UNSUPPORTED_CAPABILITY",
                "No embedding-capable Backend is configured/online (FR-MM-03).",
                details={"required_capability": "embedding"},
            )
        if not query.strip():
            raise MeshError("INVALID_REQUEST", "Query must not be empty.")
        (query_vector,) = await self._embedder.embed((query,), self._embed_model)
        from localmesh_agent.security.task_crypto import decrypt

        scored: list[tuple[float, dict[str, Any]]] = []
        for row in self._store.list_rag_vectors():
            vector = unpack_vector(bytes(row["vector"]))
            score = cosine(query_vector, vector)
            if score <= 0.0:
                continue
            try:
                text = decrypt(self._key, bytes(row["text_nonce"]), bytes(row["enc_text"])).decode(
                    "utf-8"
                )
            except Exception:  # noqa: BLE001 — tampered/unreadable section: skip, never crash
                continue
            scored.append(
                (
                    score,
                    {
                        "source_id": str(row["source_id"]),
                        "seq": int(row["seq"]),
                        "score": round(score, 4),
                        "text": text,
                    },
                )
            )
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [entry for _score, entry in scored[:k]]
