"""M8 unit tests — tool registry + agent loop (FR-AGENT-RT, ADR-020)."""

from __future__ import annotations

import json

import pytest

from localmesh_agent.core.agent_loop import parse_tool_calls, run_agent_loop
from localmesh_agent.core.errors import MeshError
from localmesh_agent.core.tools import ToolRegistry


def test_builtin_tools_are_metadata_only() -> None:
    registry = ToolRegistry()
    names = {spec["function"]["name"] for spec in registry.specs()}
    assert names == {"time_now", "uuid_v4"}  # no I/O tools by construction
    # list_models joins only after the app wires it against the Registry.
    registry.register_models_tool(lambda: ["a::m"])
    assert "list_models" in {spec["function"]["name"] for spec in registry.specs()}


def test_time_now_is_iso_and_uuid_is_valid() -> None:
    registry = ToolRegistry()
    now = registry.execute("time_now", {})
    assert now.endswith("Z") and "T" in now
    value = registry.execute("uuid_v4", "{}")
    assert len(value) == 36 and value.count("-") == 4


def test_unknown_tool_denied_fail_closed() -> None:
    registry = ToolRegistry()
    result = registry.execute("shell_exec", '{"command": "rm -rf /"}')
    assert "not allow-listed" in result  # never executed, in-band denial


def test_output_cap_enforced() -> None:
    registry = ToolRegistry()
    registry.register_models_tool(lambda: ["x" * 100000])
    result = registry.execute("list_models", {})
    assert "size cap" in result


def test_bad_arguments_json_is_in_band_error() -> None:
    registry = ToolRegistry()
    result = registry.execute("time_now", "{not json")
    assert "valid JSON" in result


def test_parse_tool_calls_defensive() -> None:
    assert parse_tool_calls(None) == ()
    assert parse_tool_calls("x") == ()
    assert parse_tool_calls([{"nope": 1}]) == ()
    calls = parse_tool_calls(
        [{"id": "c1", "type": "function", "function": {"name": "time_now", "arguments": "{}"}}]
    )
    assert len(calls) == 1 and calls[0].name == "time_now" and calls[0].call_id == "c1"


class Turn:
    def __init__(self, text: str, tool_calls: tuple = ()) -> None:
        self.text = text
        self.finish_reason = "tool_calls" if tool_calls else "stop"
        self.tool_calls = tool_calls


@pytest.mark.asyncio
async def test_loop_executes_then_finishes() -> None:
    registry = ToolRegistry()

    async def collect(_backend, _req) -> Turn:
        if len(collect.turns) == 0:
            collect.turns.append(1)
            return Turn(
                "",
                parse_tool_calls(
                    [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {"name": "time_now", "arguments": "{}"},
                        }
                    ]
                ),
            )
        return Turn("done text")

    collect.turns = []
    result = await run_agent_loop(
        None,
        backend_model_id="m",
        mesh_model_id="a::m",
        messages=[{"role": "user", "content": "hi"}],
        tools=registry,
        max_iterations=5,
        collect_fn=collect,
    )
    assert result.text == "done text"
    assert result.iterations == 2
    assert result.tool_trace == [{"tool": "time_now", "status": "executed"}]


@pytest.mark.asyncio
async def test_loop_iteration_budget_is_terminal() -> None:
    registry = ToolRegistry()

    async def always_tools(_backend, _req) -> Turn:
        return Turn(
            "",
            parse_tool_calls(
                [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "uuid_v4", "arguments": "{}"},
                    }
                ]
            ),
        )

    with pytest.raises(MeshError) as excinfo:
        await run_agent_loop(
            None,
            backend_model_id="m",
            mesh_model_id="a::m",
            messages=[{"role": "user", "content": "hi"}],
            tools=registry,
            max_iterations=3,
            collect_fn=always_tools,
        )
    assert excinfo.value.code == "BACKEND_PROTOCOL"
    assert excinfo.value.details == {"max_iterations": 3}


def test_trace_carries_no_arguments() -> None:
    """ADR-020 §6: arguments may carry Content — the trace never includes them."""
    registry = ToolRegistry()
    _ = json  # keep import honest for readers
    # The trace shape is built in agent_loop.run_agent_loop: {"tool", "status"}.
    # Pinned here via the executing path.
    import asyncio

    from localmesh_agent.core.tools import ToolSpec  # noqa: F401  (import sanity)

    async def main() -> None:
        async def collect(_b, _r) -> Turn:
            if not getattr(collect, "done", False):
                collect.done = True
                return Turn(
                    "",
                    parse_tool_calls(
                        [
                            {
                                "id": "c1",
                                "type": "function",
                                "function": {
                                    "name": "time_now",
                                    "arguments": json.dumps({"secret": "CANARY"}),
                                },
                            }
                        ]
                    ),
                )
            return Turn("ok")

        result = await run_agent_loop(
            None,
            backend_model_id="m",
            mesh_model_id="a::m",
            messages=[{"role": "user", "content": "hi"}],
            tools=registry,
            max_iterations=2,
            collect_fn=collect,
        )
        blob = json.dumps(result.tool_trace)
        assert "CANARY" not in blob

    asyncio.run(main())
