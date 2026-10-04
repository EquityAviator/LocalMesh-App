#!/usr/bin/env python3
"""§19.1 benchmark skeleton — Agent latency harness (LM-ARCH-001 §19.1).

BUDGETS (§19.1, targets; "[DESIGN]" basis — verify with benchmarks at M5):
    Agent-added latency (request in → first upstream byte), p95, LAN  ≤ 25 ms
    Agent-added per-chunk latency, p95                                ≤ 10 ms

WHAT THIS HARNESS MEASURES TODAY (skeleton, [DESIGN] status):
    Client-observed TTFT (request start → first SSE data event) and
    client-observed per-chunk inter-arrival gaps, in-process over the ASGI
    transport (no TCP hop) against the WP-03 FAKE Ollama backend. These
    numbers therefore include the fake backend's own pacing — they are NOT
    the pure "Agent-added" deltas the budget table names. The in-process
    transport also coalesces stream chunks, so per-chunk gaps read ≈0; the
    per-chunk budget needs a TCP listener and real Backends. The harness is
    the deliverable; honest Agent-added numbers need REAL Backends on a LAN
    (docs/fixtures/CAPTURE.md owner action) plus timing instrumentation at
    the adapter boundary. Treat every printed number as sandbox-relative.

USAGE (from the repo root, with the agent venv):
    agent/.venv/bin/python scripts/bench_agent_latency.py [options]
Options:
    --iterations N   measured iterations after warmup (default 30)
    --warmup N       unmeasured warmup iterations (default 3; first demand-load
                     is the CI-21 cold path and is excluded like real benches)
    --json PATH      also write results as JSON to PATH
Exit code is always 0 unless the harness itself crashes — this is a
measurement tool, not a gate (the budgets are targets, not assertions).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import threading
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in ("tools/fake-backends", "agent/src"):
    _abs = REPO_ROOT / _p
    if _abs.is_dir() and str(_abs) not in sys.path:
        sys.path.insert(0, str(_abs))

import httpx  # noqa: E402
from fake_ollama import DEFAULT_MODEL, FakeOllama  # noqa: E402

from localmesh_agent.app import create_app  # noqa: E402
from localmesh_agent.config import Settings  # noqa: E402

MESH_MODEL_ID = f"ollama::{DEFAULT_MODEL}"

# §19.1 verbatim targets (the rows the harness will instrument for real).
TARGETS = {
    "ttft_p95_ms": {"budget": 25, "label": "Agent-added latency p95 (LAN)"},
    "chunk_gap_p95_ms": {"budget": 10, "label": "Agent-added per-chunk latency p95"},
}


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile on a non-empty sample."""
    ordered = sorted(values)
    rank = max(1, min(len(ordered), round(pct / 100 * len(ordered))))
    return ordered[rank - 1]


async def stream_once(client: httpx.AsyncClient) -> dict[str, Any]:
    """One streaming chat request; returns client-observed timing samples."""
    t_start = time.perf_counter()
    t_first_byte: float | None = None
    t_first_data: float | None = None
    data_marks: list[float] = []

    async with client.stream(
        "POST",
        "/mesh/v1/chat/completions",
        json={"model": MESH_MODEL_ID, "messages": [{"role": "user", "content": "Hi"}], "stream": True},
    ) as response:
        response.raise_for_status()
        async for chunk in response.aiter_text():
            now = time.perf_counter()
            if t_first_byte is None:
                t_first_byte = now
            for line in chunk.splitlines():
                if line.startswith("data:") and line[5:].strip() != "[DONE]":
                    if t_first_data is None:
                        t_first_data = now
                    data_marks.append(now)
    if t_first_byte is None or t_first_data is None or len(data_marks) < 2:
        raise RuntimeError("stream ended before enough SSE data events arrived")

    gaps = [
        (b - a) * 1000.0
        for a, b in zip(data_marks, data_marks[1:])
    ]
    return {
        "ttft_ms": (t_first_data - t_start) * 1000.0,
        "first_byte_ms": (t_first_byte - t_start) * 1000.0,
        "chunk_gaps_ms": gaps,
        "data_events": len(data_marks),
    }


async def run(iterations: int, warmup: int) -> dict[str, Any]:
    """Wire the REAL app to a fresh fake Ollama and measure N streams."""
    server = FakeOllama(("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        import tempfile

        with tempfile.TemporaryDirectory() as data_dir:
            settings = Settings(
                agent={"data_dir": data_dir},
                mdns={"enabled": False},
                backends=[{"id": "ollama", "kind": "ollama", "base_url": _fake_url(server)}],
            )
            app = create_app(settings, dev_insecure=True)  # QUESTION-105 dev token bypass
            async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://bench"
                ) as client:
                    for _ in range(warmup):
                        await stream_once(client)
                    samples = [await stream_once(client) for _ in range(iterations)]
    finally:
        server.shutdown()
        server.server_close()

    ttfts = [s["ttft_ms"] for s in samples]
    all_gaps = [g for s in samples for g in s["chunk_gaps_ms"]]
    return {
        "iterations": iterations,
        "warmup": warmup,
        "mesh_model_id": MESH_MODEL_ID,
        "transport": "in-process ASGI + fake Ollama (sandbox-relative, NOT LAN Agent-added)",
        "ttft_ms": {
            "p50": round(percentile(ttfts, 50), 2),
            "p95": round(percentile(ttfts, 95), 2),
            "max": round(max(ttfts), 2),
            "mean": round(statistics.fmean(ttfts), 2),
        },
        "chunk_gap_ms": {
            "p50": round(percentile(all_gaps, 50), 2),
            "p95": round(percentile(all_gaps, 95), 2),
            "max": round(max(all_gaps), 2),
            "mean": round(statistics.fmean(all_gaps), 2),
        },
        "data_events_total": sum(s["data_events"] for s in samples),
    }


def _fake_url(server: FakeOllama) -> str:
    return f"http://127.0.0.1:{server.server_address[1]}"


def render(results: dict[str, Any]) -> str:
    lines = [
        "LocalMesh Agent — §19.1 latency skeleton (sandbox-relative numbers)",
        f"iterations={results['iterations']} warmup={results['warmup']} "
        f"model={results['mesh_model_id']}",
        "",
        f"{'metric':<34}{'p50':>9}{'p95':>9}{'max':>9}{'mean':>9}",
        f"{'TTFT, first data event (ms)':<34}"
        f"{results['ttft_ms']['p50']:>9.2f}{results['ttft_ms']['p95']:>9.2f}"
        f"{results['ttft_ms']['max']:>9.2f}{results['ttft_ms']['mean']:>9.2f}",
        f"{'chunk inter-arrival (ms)':<34}"
        f"{results['chunk_gap_ms']['p50']:>9.2f}{results['chunk_gap_ms']['p95']:>9.2f}"
        f"{results['chunk_gap_ms']['max']:>9.2f}{results['chunk_gap_ms']['mean']:>9.2f}",
        "",
        f"§19.1 budgets (for reference — these samples are NOT Agent-added):",
        f"  {TARGETS['ttft_p95_ms']['label']:<50} ≤ {TARGETS['ttft_p95_ms']['budget']} ms",
        f"  {TARGETS['chunk_gap_p95_ms']['label']:<50} ≤ {TARGETS['chunk_gap_p95_ms']['budget']} ms",
        "",
        "note: the in-process ASGI transport coalesces stream chunks — per-chunk",
        "      gaps read ≈0 here; the per-chunk budget needs a TCP listener and",
        "      real Backends (docs/fixtures/CAPTURE.md owner action).",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--json", dest="json_path", default=None)
    args = parser.parse_args()

    results = asyncio.run(run(args.iterations, args.warmup))
    print(render(results))
    if args.json_path:
        Path(args.json_path).write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"\nJSON written to {args.json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
