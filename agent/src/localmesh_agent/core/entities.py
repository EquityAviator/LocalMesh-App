"""Device, BackendModel, ModelEntry, ChatRequest, ChatChunk, Stats (§10.1).

The types referenced by the §10.2 port signatures live in `adapters/ports.py`
(bottom layer; QUESTION-101 interpretation) and are re-exported here so that
`core` keeps the §10.1 vocabulary. `Device` and `ModelEntry` (the §13.5
Capability Registry entry) are defined here — they are core-owned shapes.

§13.5 rule: unknown fields are `null` with provenance; `normalize` MUST NOT
parse model names to guess parameters/quantization/capabilities (§16.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from localmesh_agent.adapters.ports import (
    BackendCaps,
    BackendModel,
    BackendStatus,
    CancelToken,
    ChatChunk,
    ChatMessage,
    ChatRequest,
    ModelState,
    TypedValue,
    ValueSource,
)

__all__ = [
    "BackendCaps",
    "BackendModel",
    "BackendStatus",
    "CancelToken",
    "ChatChunk",
    "ChatMessage",
    "ChatRequest",
    "Device",
    "MeshStats",
    "ModelEntry",
    "ModelState",
    "TypedValue",
    "ValueSource",
]

# §13.5 — closed capability vocabulary (enforced again at the config boundary).
CAPABILITY_VALUES: tuple[str, ...] = (
    "chat",
    "vision",
    "embedding",
    "speech_to_text",
    "tool_calling",
    "reasoning",
    "code",
)


def new_uuid7() -> str:
    """RFC 9562 UUIDv7 (48-bit unix-ms timestamp + random) — §14.3 identifier
    format (`ag_`/`dv_`/`rq_`/`tk_` prefixes are added by callers).

    Python 3.12's `uuid` module has no uuid7; this minimal implementation
    keeps the canonical format without adding a dependency (§1.2 rule 5).
    """
    import os
    import struct
    import time
    import uuid as _uuid

    unix_ms = int(time.time() * 1000) & 0xFFFFFFFFFFFF  # 48 bits
    rand_a = int.from_bytes(os.urandom(2), "big") & 0x0FFF  # 12 bits
    rand_b = int.from_bytes(os.urandom(8), "big") & 0x3FFFFFFFFFFFFFFF  # 62 bits
    value = (unix_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    raw = struct.pack(">QQ", value >> 64, value & 0xFFFFFFFFFFFFFFFF)
    return str(_uuid.UUID(bytes=raw))


@dataclass(frozen=True)
class Device:
    """A paired endpoint holding a device keypair (§3, §14.1 row mirror)."""

    device_id: str  # 'dv_' + UUIDv7 (§14.3)
    name: str
    platform: str
    public_key_spki: bytes  # DER, P-256
    scopes: tuple[str, ...]
    created_at: int
    last_seen_at: int | None = None
    revoked_at: int | None = None

    @property
    def revoked(self) -> bool:
        return self.revoked_at is not None


@dataclass(frozen=True)
class ModelEntry:
    """§13.5 Capability Registry entry (normalized, provenance-carrying)."""

    mesh_model_id: str  # "<backend_id>::<backend_model_id>" (§14.3)
    backend_id: str
    backend_model_id: str
    display_name: str | None
    state: ModelState
    modalities_input: tuple[str, ...]
    modalities_output: tuple[str, ...]
    modalities_source: ValueSource
    capabilities: tuple[str, ...]
    capabilities_source: ValueSource
    context_length: TypedValue
    quantization: TypedValue
    parameter_size: TypedValue
    size_bytes: int | None
    vram_estimate_bytes: int | None
    tags: tuple[str, ...] = ()

    @classmethod
    def from_backend(
        cls, backend_id: str, model: BackendModel, state: ModelState | None = None
    ) -> ModelEntry:
        """Build an entry from a backend-reported model (source='backend';

        every field the Backend did not report becomes null/unknown — §13.5,
        §16.3 normalize MUST NOT guess)."""
        has_mods = model.modalities_input is not None or model.modalities_output is not None
        return cls(
            mesh_model_id=f"{backend_id}::{model.backend_model_id}",
            backend_id=backend_id,
            backend_model_id=model.backend_model_id,
            display_name=model.display_name,
            state=state if state is not None else model.state,
            modalities_input=model.modalities_input or (),
            modalities_output=model.modalities_output or (),
            modalities_source="backend" if has_mods else "unknown",
            capabilities=model.capabilities or (),
            capabilities_source="backend" if model.capabilities is not None else "unknown",
            context_length=(
                TypedValue.backend(model.context_length)
                if model.context_length is not None
                else TypedValue.unknown()
            ),
            quantization=(
                TypedValue.backend(model.quantization)
                if model.quantization is not None
                else TypedValue.unknown()
            ),
            parameter_size=(
                TypedValue.backend(model.parameter_size)
                if model.parameter_size is not None
                else TypedValue.unknown()
            ),
            size_bytes=model.size_bytes,
            vram_estimate_bytes=model.vram_estimate_bytes,
            tags=model.tags,
        )

    def with_state(self, state: ModelState) -> ModelEntry:
        """Return a copy with `state` replaced (backend-down demotion, §16.3)."""
        return ModelEntry(
            mesh_model_id=self.mesh_model_id,
            backend_id=self.backend_id,
            backend_model_id=self.backend_model_id,
            display_name=self.display_name,
            state=state,
            modalities_input=self.modalities_input,
            modalities_output=self.modalities_output,
            modalities_source=self.modalities_source,
            capabilities=self.capabilities,
            capabilities_source=self.capabilities_source,
            context_length=self.context_length,
            quantization=self.quantization,
            parameter_size=self.parameter_size,
            size_bytes=self.size_bytes,
            vram_estimate_bytes=self.vram_estimate_bytes,
            tags=self.tags,
        )

    def to_api_json(self) -> dict[str, Any]:
        """Serialize exactly to the §13.5 `ModelEntry` shape (API-MODEL-01)."""
        return {
            "mesh_model_id": self.mesh_model_id,
            "backend_id": self.backend_id,
            "backend_model_id": self.backend_model_id,
            "display_name": self.display_name,
            "state": self.state,
            "modalities": {
                "input": list(self.modalities_input),
                "output": list(self.modalities_output),
                "source": self.modalities_source,
            },
            "capabilities": {
                "values": list(self.capabilities),
                "source": self.capabilities_source,
            },
            "context_length": {
                "value": self.context_length.value,
                "source": self.context_length.source,
            },
            "quantization": {"value": self.quantization.value, "source": self.quantization.source},
            "parameter_size": {
                "value": self.parameter_size.value,
                "source": self.parameter_size.source,
            },
            "size_bytes": self.size_bytes,
            "vram_estimate_bytes": self.vram_estimate_bytes,
            "tags": list(self.tags),
        }


@dataclass(frozen=True)
class MeshStats:
    """Per-request stats emitted as `mesh.stats` (§13.7; FR-STAT-02 shape)."""

    ttft_ms: int
    tokens_out: int
    tokens_per_sec: float
    duration_ms: int
    finish_reason: str | None
    token_count_source: Literal["backend", "estimated"]

    def to_api_json(self) -> dict[str, Any]:
        return {
            "ttft_ms": self.ttft_ms,
            "tokens_out": self.tokens_out,
            "tokens_per_sec": self.tokens_per_sec,
            "duration_ms": self.duration_ms,
            "finish_reason": self.finish_reason,
            "token_count_source": self.token_count_source,
        }
