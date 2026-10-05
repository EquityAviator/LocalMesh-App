"""WP-05 integration tests — adapters + registry against the WP-03 fake
Backends (FR-MOD-01 AC: "Fake backends detected in integration tests").

The fakes' response shapes are UNVERIFIED-marked (no real fixtures yet); these
tests exercise the adapter/registry plumbing (probe, list, stream, error
mapping, cancel), not real-Backend field semantics (that is the contract
tests' job once recordings exist).
"""

import sys
import threading
from pathlib import Path
from typing import Any

import httpx
import pytest

TOOLS_FAKE = Path(__file__).resolve().parents[3] / "tools" / "fake-backends"
if str(TOOLS_FAKE) not in sys.path:
    sys.path.insert(0, str(TOOLS_FAKE))  # test asset import (§21.5 shared fixture)

from fake_core import SCENARIO_HEADER  # noqa: E402
from fake_lmstudio import DEFAULT_MODEL as LMS_MODEL  # noqa: E402
from fake_lmstudio import FakeLMStudio  # noqa: E402
from fake_ollama import DEFAULT_ON_DISK as OLLAMA_ON_DISK  # noqa: E402
from fake_ollama import FakeOllama  # noqa: E402

from localmesh_agent.adapters.backends.lmstudio import LMStudioBackend  # noqa: E402
from localmesh_agent.adapters.backends.ollama import OllamaBackend  # noqa: E402
from localmesh_agent.adapters.ports import (  # noqa: E402
    CancelToken,
    ChatMessage,
    ChatRequest,
)
from localmesh_agent.core.errors import MeshError  # noqa: E402
from localmesh_agent.core.registry import CapabilityRegistry  # noqa: E402
from localmesh_agent.store.sqlite import Store  # noqa: E402


@pytest.fixture()
def fake_lmstudio() -> Any:
    server = FakeLMStudio(("127.0.0.1", 0), cold_load_ms=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.fixture()
def fake_ollama() -> Any:
    server = FakeOllama(("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def make_chat_request(backend_model_id: str) -> ChatRequest:
    return ChatRequest(
        model=f"backend::{backend_model_id}",
        backend_model_id=backend_model_id,
        messages=(ChatMessage(role="user", content="Hi"),),
    )


async def test_probe_detects_fake_lmstudio(fake_lmstudio: str) -> None:
    backend = LMStudioBackend("lmstudio", fake_lmstudio)
    status = await backend.probe()
    assert status.status == "up"
    await backend.aclose()


async def test_probe_detects_fake_ollama(fake_ollama: str) -> None:
    backend = OllamaBackend("ollama", fake_ollama)
    status = await backend.probe()
    assert status.status == "up"
    await backend.aclose()


async def test_lmstudio_list_models_normalized(fake_lmstudio: str) -> None:
    """§6.1: native list parsed to id-only entries (fields UNVERIFIED)."""
    backend = LMStudioBackend("lmstudio", fake_lmstudio)
    models = await backend.list_models()
    assert [m.backend_model_id for m in models] == [
        LMS_MODEL,
        "llama-fake-3-8b",
    ]
    # No metadata extracted from UNVERIFIED shapes (never guessed, §13.5):
    assert all(m.context_length is None for m in models)
    assert all(m.quantization is None for m in models)
    assert all(m.state == "unknown" for m in models)
    await backend.aclose()


async def test_ollama_list_models_normalized(fake_ollama: str) -> None:
    """§6.2: tags+ps+show — default fake variant sends name-only tag entries;
    state comes from /api/ps presence; missing metadata stays null (never
    guessed, §13.5)."""
    backend = OllamaBackend("ollama", fake_ollama)
    models = await backend.list_models()
    names = [m.backend_model_id for m in models]
    assert names == list(OLLAMA_ON_DISK)
    by_name = {m.backend_model_id: m for m in models}
    # Fake /api/ps holds qwen-fake:7b only -> loaded; the rest unloaded.
    assert by_name["qwen-fake:7b"].state == "loaded"
    assert by_name["llama-fake:8b"].state == "unloaded"
    # /api/ps carries size_vram for the in-memory model (§6.2 VRAM footprint).
    assert by_name["qwen-fake:7b"].vram_estimate_bytes == 5_000_000_000
    # Name-only tag entries: metadata stays null (drift tolerance, §10.3 rule 2).
    assert by_name["qwen-fake:7b"].parameter_size is None
    assert by_name["qwen-fake:7b"].quantization is None
    await backend.aclose()


async def test_ollama_show_details_cached(fake_ollama: str) -> None:
    """Shape-variant-b tags carry details + size; /api/show cached per model."""
    import httpx as _httpx
    from fake_core import SCENARIO_HEADER as _SCENARIO

    client = _httpx.AsyncClient(headers={_SCENARIO: "shape-variant-b"})
    backend = OllamaBackend("ollama", fake_ollama, client=client)
    models = await backend.list_models()
    by_name = {m.backend_model_id: m for m in models}
    assert by_name["qwen-fake:7b"].parameter_size == "7B"
    assert by_name["qwen-fake:7b"].quantization == "Q4_K_M"
    assert by_name["qwen-fake:7b"].size_bytes == 4_700_000_000
    # context_length arrives via POST /api/show (variant-b default body has no
    # model_info here — defensive None, no guessing):
    assert by_name["qwen-fake:7b"].context_length is None
    await backend.aclose()


async def test_registry_merges_both_fakes(
    fake_lmstudio: str, fake_ollama: str, tmp_path: Path
) -> None:
    """FR-MOD-01: both Backends detected; snapshot carries both model sets."""
    store = Store(tmp_path / "agent.db")
    registry = CapabilityRegistry(
        "ag_test",
        [
            LMStudioBackend("lmstudio", fake_lmstudio),
            OllamaBackend("ollama", fake_ollama),
        ],
        store,
    )
    await registry.refresh()
    snapshot = registry.snapshot()
    model_ids = [m["mesh_model_id"] for m in snapshot["models"]]  # type: ignore[index]
    assert f"lmstudio::{LMS_MODEL}" in model_ids
    assert any(mid.startswith("ollama::") for mid in model_ids)
    statuses = {b["id"]: b["status"] for b in snapshot["backends"]}  # type: ignore[index]
    assert statuses == {"lmstudio": "up", "ollama": "up"}
    store.close()


async def test_chat_stream_via_fake_lmstudio(fake_lmstudio: str) -> None:
    backend = LMStudioBackend("lmstudio", fake_lmstudio)
    chunks = []
    async for chunk in backend.stream_chat(make_chat_request(LMS_MODEL), CancelToken()):
        chunks.append(chunk)
    text = "".join(c.delta_content or "" for c in chunks)
    assert text == "Hello from fake LM Studio."
    assert chunks[-1].finish_reason == "stop"
    await backend.aclose()


async def test_backend_500_maps_to_mesh_error(fake_lmstudio: str) -> None:
    """§10.3 rule 3: backend errors -> MeshError, raw body not forwarded."""
    client = httpx.AsyncClient(headers={SCENARIO_HEADER: "http-500"})
    backend = LMStudioBackend("lmstudio", fake_lmstudio, client=client)
    with pytest.raises(MeshError) as excinfo:
        async for _ in backend.stream_chat(make_chat_request(LMS_MODEL), CancelToken()):
            pass
    assert excinfo.value.code == "BACKEND_UNAVAILABLE"
    assert excinfo.value.retryable
    await backend.aclose()


async def test_mid_stream_disconnect_maps_to_protocol_error(fake_lmstudio: str) -> None:
    """§10.7: stream cut without [DONE] -> terminal BACKEND_PROTOCOL."""
    client = httpx.AsyncClient(
        headers={SCENARIO_HEADER: "mid-stream-disconnect"},
        timeout=httpx.Timeout(5.0, read=5.0),
    )
    backend = LMStudioBackend("lmstudio", fake_lmstudio, client=client)
    with pytest.raises(MeshError) as excinfo:
        async for _ in backend.stream_chat(make_chat_request(LMS_MODEL), CancelToken()):
            pass
    assert excinfo.value.code == "BACKEND_PROTOCOL"
    await backend.aclose()


async def test_cancel_stops_streaming(fake_lmstudio: str) -> None:
    """Cancel token: adapter stops consuming (abort ≤ 1 s verified in WP-06)."""
    backend = LMStudioBackend("lmstudio", fake_lmstudio)
    token = CancelToken()
    token.cancel()
    received: list[str] = []
    with pytest.raises(MeshError) as excinfo:
        async for chunk in backend.stream_chat(make_chat_request(LMS_MODEL), token):
            received.append(chunk.delta_content or "")
    assert excinfo.value.code == "CANCELLED"
    assert received == []  # cancelled before the first chunk was consumed
    await backend.aclose()
