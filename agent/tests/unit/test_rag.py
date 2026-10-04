"""M7 unit tests — RAG pipeline (FR-MM-03)."""

from __future__ import annotations

import pytest

from localmesh_agent.core.errors import MeshError
from localmesh_agent.core.rag import (
    RagService,
    chunk_text,
    cosine,
    pack_vector,
    unpack_vector,
)
from localmesh_agent.store.sqlite import Store


class FakeEmbedder:
    """Deterministic 4-dim embedding keyed on the LAST token (test scaffold)."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], str]] = []

    async def embed(self, texts: tuple[str, ...], backend_model_id: str) -> list[list[float]]:
        self.calls.append((texts, backend_model_id))
        out: list[list[float]] = []
        for text in texts:
            marker = text[-6:].ljust(6)
            out.append([c / 255.0 for c in marker.encode("utf-8")][:4])
        return out


@pytest.fixture()
def store(tmp_path):
    s = Store(tmp_path / "agent.db")
    yield s
    s.close()


def test_chunking_windows_and_no_empties() -> None:
    text = "abcdefghij" * 300  # 3000 chars
    chunks = chunk_text(text, max_chars=100, overlap=10)
    assert all(chunks)
    assert all(len(chunk) <= 100 for chunk in chunks)
    # overlap actually overlaps
    assert chunks[0][-10:] in chunks[1]
    assert chunk_text("   ") == []
    assert chunk_text("tiny") == ["tiny"]


def test_pack_unpack_roundtrip() -> None:
    vector = [0.25, -0.5, 0.0, 0.75]
    blob = pack_vector(vector)
    assert unpack_vector(blob) == vector


def test_cosine_edges() -> None:
    assert cosine([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine([1.0, 0.0], [-1.0, 0.0]) == -1.0
    assert cosine([], [1.0]) == 0.0
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


@pytest.mark.asyncio
async def test_index_and_retrieve_roundtrip(store: Store) -> None:
    embedder = FakeEmbedder()
    service = RagService(store, embedder, "fake-embed-model", key=b"k" * 32)
    document = ("The kitchen fuse box is behind the door. " * 40).strip()
    result = await service.index_document("manual.txt", document.encode("utf-8"))
    assert result["sections"] >= 2
    assert result["model"] == "fake-embed-model"
    hits = await service.retrieve("kitchen fuse box is", k=2)
    assert hits, "identical text must retrieve itself"
    assert hits[0]["score"] > 0.9
    # The stored text is ciphertext at rest — plaintext never on disk rows.
    rows = store.list_rag_vectors()
    assert rows and all(b"kitchen fuse" not in bytes(row["enc_text"]) for row in rows)


@pytest.mark.asyncio
async def test_unavailable_embedder_is_unsupported(store: Store) -> None:
    service = RagService(store, None, None, key=b"k" * 32)
    with pytest.raises(MeshError) as excinfo:
        await service.index_document("a.txt", b"hello world")
    assert excinfo.value.code == "UNSUPPORTED_CAPABILITY"
    with pytest.raises(MeshError):
        await service.retrieve("hello")


@pytest.mark.asyncio
async def test_non_text_document_rejected(store: Store) -> None:
    service = RagService(store, FakeEmbedder(), "m", key=b"k" * 32)
    with pytest.raises(MeshError) as excinfo:
        await service.index_document("photo.png", b"\x89PNG...")
    assert excinfo.value.code == "UNSUPPORTED_CAPABILITY"  # v1 scope: .txt/.md only
