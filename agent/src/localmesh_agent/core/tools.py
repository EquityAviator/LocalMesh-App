"""Agent-runtime tool registry (M8, FR-AGENT-RT; ADR-020).

ADR-020 (tool sandboxing, written because the spec GATES tool execution on a
security ADR — T-14/SEC-11): tools are DEFAULT-DENY and the only built-ins
are deterministic, no-I/O, Metadata-only functions:

- `time_now`   — Agent wall-clock (ISO-8601 UTC).
- `uuid_v4`    — CSPRNG UUID.
- `list_models`— Capability Registry ids (§13.5 Metadata).

No shell, no filesystem, no network, no browser automation — the spec
explicitly forbids those before a dedicated security ADR (§4.4 line 192) and
ADR-020 keeps them forbidden in v1. Unknown tool names are DENIED (never
guessed). Tool output is size-capped by the runtime (AgentRuntimeConfig).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from localmesh_agent.core.errors import MeshError
from localmesh_agent.observability.logging import get_logger

log = get_logger("tools")

MAX_TOOL_OUTPUT_BYTES = 4096  # ADR-020 bound (config may only RAISE awareness,
# not exceed the runtime cap enforced here per call — see execute()).


@dataclass(frozen=True)
class ToolSpec:
    """One allow-listed tool (OpenAI function semantics, §13.6 M8 shape)."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema
    fn: Callable[[dict[str, Any]], str]


def _time_now(args: dict[str, Any]) -> str:
    _ = args
    return datetime.now(tz=UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _uuid_v4(args: dict[str, Any]) -> str:
    _ = args
    return str(uuid.uuid4())


class ToolRegistry:
    """Allow-listed tools only; unknown names are denied (ADR-020)."""

    def __init__(self, extra: list[ToolSpec] | None = None) -> None:
        self._tools: dict[str, ToolSpec] = {spec.name: spec for spec in self._builtins()}
        for spec in extra or []:
            if spec.name in self._tools:  # pragma: no cover — defensive
                raise MeshError("INTERNAL", "Duplicate tool name.")
            self._tools[spec.name] = spec

    @staticmethod
    def _builtins() -> list[ToolSpec]:
        return [
            ToolSpec(
                name="time_now",
                description="Returns the Agent's current wall-clock time (ISO-8601 UTC).",
                parameters={"type": "object", "properties": {}, "required": []},
                fn=_time_now,
            ),
            ToolSpec(
                name="uuid_v4",
                description="Returns a random UUIDv4 string.",
                parameters={"type": "object", "properties": {}, "required": []},
                fn=_uuid_v4,
            ),
        ]

    def register_models_tool(self, model_ids_fn: Callable[[], list[str]]) -> None:
        """Register `list_models` over the Capability Registry (Metadata only)."""

        def _list_models(args: dict[str, Any]) -> str:
            _ = args
            return json.dumps({"models": model_ids_fn()})

        self._tools["list_models"] = ToolSpec(
            name="list_models",
            description="Lists the mesh_model_ids currently in the Capability Registry.",
            parameters={"type": "object", "properties": {}, "required": []},
            fn=_list_models,
        )

    def specs(self) -> list[dict[str, Any]]:
        """OpenAI `tools` wire shape for the declared (allow-listed) set."""
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            }
            for spec in sorted(self._tools.values(), key=lambda s: s.name)
        ]

    def has(self, name: str) -> bool:
        return name in self._tools

    def execute(self, name: str, arguments: dict[str, Any] | str) -> str:
        """Run one allow-listed tool; DENY unknown names (fail closed)."""
        spec = self._tools.get(name)
        if spec is None:
            log.warning(
                "tool_denied",
                extra={"component": "tools", "status": "denied", "error_code": "TOOL_UNKNOWN"},
            )
            return json.dumps({"error": f"tool {name!r} is not allow-listed (ADR-020)."})
        if isinstance(arguments, str):
            try:
                parsed = json.loads(arguments) if arguments else {}
            except json.JSONDecodeError:
                return json.dumps({"error": "arguments were not valid JSON."})
            arguments = parsed if isinstance(parsed, dict) else {}
        try:
            output = spec.fn(arguments)
        except Exception:  # noqa: BLE001 — tool failures are results, not crashes
            return json.dumps({"error": "tool execution failed."})
        encoded = output.encode("utf-8")
        if len(encoded) > MAX_TOOL_OUTPUT_BYTES:  # ADR-020 output cap
            return json.dumps({"error": "tool output exceeded the size cap."})
        return output
