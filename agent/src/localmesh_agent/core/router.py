"""Model resolution (§10.4 Router) + M8 auto-routing (§16.6, FR-RTE-01..03).

`mesh_model_id` splits on the FIRST '::' (§14.3): "<backend_id>::<backend_model_id>".

M8 (§16.6, verbatim algorithm — `[DESIGN — tunable]`):

    required = { modalities from request parts, capabilities from request }
    candidates = { m in registry | m.state != unknown_backend_down
                                and required.modalities ⊆ m.modalities.input
                                and required.capabilities ⊆ m.capabilities.values }
    fit(m) = 1   if est_tokens(prompt)+max_tokens ≤ m.context_length.value
             0.5 if context_length unknown
             0   (excluded) otherwise
    score(m) = 0.40*quality_rank(m)/5 + 0.25*warm(m) + 0.20*speed_norm(m)
               + 0.15*(1 - queue_load(m)),  multiplied by fit(m)
    choose argmax score; ties → lexicographic mesh_model_id
    return decision + reason in mesh.meta.routing

- `quality_rank` default 3, user-editable per model (Appendix E overrides).
- `speed_norm` from recent tokens/s per model (null → 0.5).
- `est_tokens` = ceil(chars/4), flagged as estimate.
- Weights live in config (§16.6; RoutingConfig).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from localmesh_agent.adapters.ports import InferenceBackend
from localmesh_agent.core.entities import ModelEntry
from localmesh_agent.core.errors import MeshError
from localmesh_agent.core.registry import CapabilityRegistry

AUTO_MODEL = "auto"  # FR-RTE-01: `model: "auto"` (M8)

# §16.6: quality_rank default 3, user-editable per model.
DEFAULT_QUALITY_RANK = 3

# §16.6: speed_norm default when no recent tokens/s are known.
DEFAULT_SPEED_NORM = 0.5


@dataclass(frozen=True)
class RoutingCandidate:
    """One scored candidate — exposed in mesh.meta.routing (explainability)."""

    mesh_model_id: str
    backend_id: str
    score: float
    fit: float
    quality_rank: int
    warm: float
    speed_norm: float
    queue_load: float


@dataclass(frozen=True)
class RoutingDecision:
    """§16.6 gate: "Routing decisions explained in mesh.meta"."""

    mode: str  # "auto" | "pinned"
    mesh_model_id: str
    backend_id: str
    reason: str
    est_tokens: int | None = None  # §16.6: flagged as estimate
    candidates: tuple[RoutingCandidate, ...] = field(default=())

    def to_meta(self) -> dict[str, Any]:
        """The `mesh.meta.routing` value (additive §13.10 field)."""
        payload: dict[str, Any] = {
            "mode": self.mode,
            "mesh_model_id": self.mesh_model_id,
            "backend_id": self.backend_id,
            "reason": self.reason,
        }
        if self.est_tokens is not None:
            payload["est_tokens"] = self.est_tokens
        if self.candidates:
            payload["candidates"] = [
                {
                    "mesh_model_id": candidate.mesh_model_id,
                    "score": round(candidate.score, 4),
                    "fit": candidate.fit,
                    "quality_rank": candidate.quality_rank,
                    "warm": candidate.warm,
                    "speed_norm": candidate.speed_norm,
                    "queue_load": round(candidate.queue_load, 4),
                }
                for candidate in self.candidates
            ]
        return payload


def est_tokens(messages: list[dict[str, Any]], max_tokens: int | None) -> int:
    """§16.6: ceil(chars/4) over the serialised prompt + max_tokens.

    Flagged as an estimate in the routing decision (§16.6)."""
    chars = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            chars += len(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    chars += len(part["text"])
    return math.ceil(chars / 4) + (max_tokens or 0)


class Router:
    """Resolves `model` -> `(backend, backend_model_id)`; rejects unknown
    ids with `MODEL_NOT_FOUND` (§10.4). M8 adds `model: "auto"` (§16.6)."""

    def __init__(
        self,
        registry: CapabilityRegistry,
        backends: dict[str, InferenceBackend],
        *,
        quality_ranks: dict[str, int] | None = None,  # Appendix E overrides
        speed_fn: Callable[[str], float | None] | None = None,  # model -> recent tok/s
        queue_fn: Callable[[str], float] | None = None,  # backend_id -> 0..1 load
        weights: tuple[float, float, float, float] = (0.40, 0.25, 0.20, 0.15),
    ) -> None:
        self._registry = registry
        self._backends = backends
        self._quality_ranks = quality_ranks or {}
        self._speed_fn = speed_fn
        self._queue_fn = queue_fn
        self._w_quality, self._w_warmth, self._w_speed, self._w_queue = weights

    def resolve(self, mesh_model_id: str) -> tuple[InferenceBackend, str, ModelEntry]:
        """Return (backend, backend_model_id, registry entry).

        Raises MODEL_NOT_FOUND for unknown ids (Appendix D; §10.4).
        """
        entry = self._registry.get(mesh_model_id)
        if entry is None:
            raise MeshError("MODEL_NOT_FOUND", "Unknown mesh_model_id.")
        backend = self._backends.get(entry.backend_id)
        if backend is None:  # pragma: no cover — registry and adapters share ids
            raise MeshError("MODEL_NOT_FOUND", "Unknown mesh_model_id.")
        return backend, entry.backend_model_id, entry

    # -- M8: §16.6 auto-routing ------------------------------------------------

    def resolve_auto(
        self,
        *,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
        required_modalities: frozenset[str] = frozenset(),
        required_capabilities: frozenset[str] = frozenset(),
    ) -> tuple[InferenceBackend, str, ModelEntry, RoutingDecision]:
        """§16.6 rule engine (FR-RTE-01/02). Raises MODEL_NOT_FOUND when no
        registry entry satisfies the required modalities/capabilities."""
        prompt_tokens = est_tokens(messages, max_tokens)  # §16.6 estimate
        scored: list[RoutingCandidate] = []
        fit_reasons: dict[str, str] = {}
        for entry in self._registry.entries():
            backend = self._backends.get(entry.backend_id)
            if backend is None:
                continue
            # §16.6: state != unknown_backend_down (exclude entries whose
            # state is unknown AND whose backend is not answering).
            if entry.state == "unknown":
                status = self._registry.backend_status(entry.backend_id)
                if status is None or status.status != "up":
                    continue
            # §16.6: required.modalities ⊆ m.modalities.input (unknown never matches).
            if not required_modalities <= set(entry.modalities_input):
                continue
            # §16.6: required.capabilities ⊆ m.capabilities.values (unknown ≠ match).
            if not required_capabilities <= set(entry.capabilities):
                continue
            fit, fit_reason = self._fit(entry, prompt_tokens)
            if fit == 0.0:
                continue  # §16.6: context too small → excluded
            fit_reasons[entry.mesh_model_id] = fit_reason
            warm = 1.0 if entry.state == "loaded" else 0.0
            speed_norm = self._speed_norm(entry.mesh_model_id)
            queue_load = self._queue_fn(entry.backend_id) if self._queue_fn else 0.0
            score = (
                self._w_quality * self._quality_rank(entry) / 5
                + self._w_warmth * warm
                + self._w_speed * speed_norm
                + self._w_queue * (1 - queue_load)
            ) * fit
            scored.append(
                RoutingCandidate(
                    mesh_model_id=entry.mesh_model_id,
                    backend_id=entry.backend_id,
                    score=score,
                    fit=fit,
                    quality_rank=self._quality_rank(entry),
                    warm=warm,
                    speed_norm=speed_norm,
                    queue_load=queue_load,
                )
            )
        if not scored:
            raise MeshError(
                "MODEL_NOT_FOUND",
                "No model satisfies the required modalities/capabilities (§16.6).",
                details={"auto": "no_candidate"},
            )
        # §16.6: argmax score; ties → lexicographic mesh_model_id.
        scored.sort(key=lambda c: (-c.score, c.mesh_model_id))
        winner = scored[0]
        backend, backend_model_id, entry = self.resolve(winner.mesh_model_id)
        reason = self._reason(winner, prompt_tokens, fit_reasons.get(winner.mesh_model_id, ""))
        decision = RoutingDecision(
            mode="auto",
            mesh_model_id=winner.mesh_model_id,
            backend_id=winner.backend_id,
            reason=reason,
            est_tokens=prompt_tokens,
            candidates=tuple(scored[:5]),
        )
        return backend, backend_model_id, entry, decision

    def _fit(self, entry: ModelEntry, prompt_tokens: int) -> tuple[float, str]:
        """§16.6 fit(): 1 / 0.5 (unknown context) / 0 (excluded)."""
        context = entry.context_length
        if context.value is None:
            return 0.5, "context_length unknown → fit=0.5 (§16.6)"
        if prompt_tokens <= int(context.value):
            return 1.0, "fits context (§16.6)"
        return 0.0, "context too small"

    def _quality_rank(self, entry: ModelEntry) -> int:
        """§16.6: default 3, user-editable per model (Appendix E override)."""
        return int(self._quality_ranks.get(entry.mesh_model_id, DEFAULT_QUALITY_RANK))

    def _speed_norm(self, mesh_model_id: str) -> float:
        """§16.6: speed_norm from recent tokens/s (null → 0.5)."""
        if self._speed_fn is None:
            return DEFAULT_SPEED_NORM
        recent = self._speed_fn(mesh_model_id)
        if recent is None:
            return DEFAULT_SPEED_NORM
        # Normalise against a 100 tok/s reference [DESIGN — tunable]: the
        # spec names the input (recent tokens/s) but not the scale.
        return max(0.0, min(1.0, recent / 100.0))

    def _reason(self, winner: RoutingCandidate, prompt_tokens: int, why_fit: str) -> str:
        return (
            f"score={winner.score:.3f} (quality={winner.quality_rank}/5, "
            f"warm={winner.warm:.0f}, speed_norm={winner.speed_norm:.2f}, "
            f"queue_load={winner.queue_load:.2f}); {why_fit}; "
            f"est_tokens={prompt_tokens} (estimate, §16.6)"
        )
