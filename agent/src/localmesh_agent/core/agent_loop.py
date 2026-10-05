"""Agent runtime loop (M8, FR-AGENT-RT; ADR-020).

Bounded tool-calling loop over an OpenAI-compatible Backend:

    while iterations < max_iterations:
        completion = backend non-stream chat(conversation)
        if completion carries tool_calls:
            execute each via the allow-listed ToolRegistry (ADR-020)
            append tool results to the conversation
        else:
            return the assistant text

Fences (ADR-020): max iterations (default 5, config ≤ 10), output-size cap,
default-deny tools, no shell/filesystem/network tools, and every executed
call is audit-logged WITHOUT arguments (they may carry Content — §17.10).
`tools` requests stream over SSE only after the loop's final message is
known, so in v1 tools require `stream: false` [DESIGN, documented in the
API layer]; the App renders the final text plus the Metadata-only trace.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from localmesh_agent.adapters.ports import ChatMessage, ChatRequest
from localmesh_agent.core.errors import MeshError
from localmesh_agent.core.tools import ToolRegistry
from localmesh_agent.observability.logging import get_logger

log = get_logger("agent-runtime")


@dataclass(frozen=True)
class ToolCall:
    """One tool call surfaced by the Backend (OpenAI semantics, defensive)."""

    call_id: str
    name: str
    arguments: str  # raw JSON string from the Backend


@dataclass
class AgentRunResult:
    """Final message + Metadata-only trace (no tool ARGUMENTS in the trace)."""

    text: str
    iterations: int
    tool_trace: list[dict[str, Any]] = field(default_factory=list)


def parse_tool_calls(raw: Any) -> tuple[ToolCall, ...]:
    """Defensive parse of OpenAI `tool_calls` (§10.3 rule 2: never raise)."""
    if not isinstance(raw, list):
        return ()
    calls: list[ToolCall] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        function = item.get("function")
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        if not isinstance(name, str) or not name:
            continue
        call_id = item.get("id")
        arguments = function.get("arguments")
        calls.append(
            ToolCall(
                call_id=call_id if isinstance(call_id, str) else f"call_{len(calls)}",
                name=name,
                arguments=arguments if isinstance(arguments, str) else "{}",
            )
        )
    return tuple(calls)


async def run_agent_loop(
    backend: Any,
    *,
    backend_model_id: str,
    mesh_model_id: str,
    messages: list[dict[str, Any]],
    tools: ToolRegistry,
    max_iterations: int,
    collect_fn: Any,  # injected: (ChatRequest) -> AssistantTurn
    tools_wire: tuple[dict[str, Any], ...] | None = None,
) -> AgentRunResult:
    """Execute the bounded loop. `collect_fn` performs ONE scheduled
    non-stream generation and returns {text, tool_calls} (injected by the
    API layer so the scheduler/cancel semantics live in one place)."""
    conversation: list[dict[str, Any]] = [dict(message) for message in messages]
    trace: list[dict[str, Any]] = []
    iterations = 0
    while iterations < max_iterations:
        iterations += 1
        turn = await collect_fn(
            backend,
            ChatRequest(
                model=mesh_model_id,
                backend_model_id=backend_model_id,
                messages=tuple(
                    ChatMessage(role=message["role"], content=message["content"])
                    for message in conversation
                ),
                stream=False,
                tools=tools_wire,
            ),
        )
        calls = turn.tool_calls
        if not calls:
            return AgentRunResult(text=turn.text, iterations=iterations, tool_trace=trace)
        # ADR-020: execute allow-listed tools only; deny others in-band.
        conversation.append(
            {
                "role": "assistant",
                "content": turn.text or "",
                "tool_calls": [
                    {
                        "id": call.call_id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": call.arguments},
                    }
                    for call in calls
                ],
            }
        )
        for call in calls:
            output = tools.execute(call.name, call.arguments)
            trace.append({"tool": call.name, "status": "executed"})
            log.info(
                "tool_executed",
                extra={"component": "tools", "status": "ok", "error_code": None},
            )
            conversation.append(
                {
                    "role": "tool",
                    "tool_call_id": call.call_id,
                    "content": output,
                }
            )
    # ADR-020: bounded — the loop MUST stop; surface a protocol error so the
    # App sees a terminal event instead of an unbounded generation.
    raise MeshError(
        "BACKEND_PROTOCOL",
        "Agent loop exceeded the iteration budget (ADR-020).",
        details={"max_iterations": max_iterations},
    )


def assistant_turn_from_chunk(
    text: str | None, finish_reason: str | None, tool_calls: tuple[ToolCall, ...]
) -> Any:
    """Bundle a non-stream generation into the turn shape the loop consumes."""
    return _Turn(
        text=text or "",
        finish_reason=finish_reason,
        tool_calls=tool_calls,
    )


class _Turn:
    def __init__(
        self,
        *,
        text: str,
        finish_reason: str | None,
        tool_calls: tuple[ToolCall, ...],
    ) -> None:
        self.text = text
        self.finish_reason = finish_reason
        self.tool_calls = tool_calls

    def to_json(self) -> str:
        return json.dumps({"text": self.text, "tool_calls": len(self.tool_calls)})
