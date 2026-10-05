# ADR-020 — Agent runtime tool calling: default-deny, allow-listed, no-I/O

Status: Accepted (M8 delivery; the security ADR the spec requires for FR-AGENT-RT)

Context: FR-AGENT-RT ("Agent runtime / tool calling on the PC", P2, M8) is
explicitly gated on a dedicated security ADR (T-14/SEC-11; §4.4 forbids "agent
tool execution on the PC (browser automation, file ops, shell) before M8 and
before a dedicated security ADR"). §13.6 defers the `tools` parameter to M8.

Decision:

1. **Default-deny.** `[agent_runtime] enabled = false` by default; a chat
   request carrying `tools` gets 422 `INVALID_REQUEST`
   (`details.tools_disabled`) until the operator enables it.
2. **Allow-listed built-ins only.** The executable set is fixed in
   `core/tools.py`: `time_now`, `uuid_v4`, `list_models` (Capability Registry
   ids). All are deterministic, no-I/O, Metadata-only. Client-declared tools
   are NEVER executed — unknown names are denied in-band.
3. **Forbidden categories (v1):** shell/exec, filesystem, network, browser
   automation, and any tool reading or writing Content. Enabling them
   requires a future ADR with a sandboxing design.
4. **Bounded loop.** ≤ `max_iterations` (default 5, config ≤ 10) model turns;
   per-call output cap (4096 B); exceeding the budget is a terminal
   `BACKEND_PROTOCOL` error, never an unbounded generation.
5. **Non-stream only (v1).** `tools` + `stream: true` → 422: the loop's tool
   turns must not leak into a phone-side SSE buffer (T-14 prompt-injection
   surface); the final message plus a Metadata-only trace is the v1 surface.
6. **Audit without arguments.** Tool executions log Metadata only
   (component/status); arguments may carry Content and are never logged
   (§17.10).

Consequences: FR-AGENT-RT is delivered with the minimum blast radius; the App
can render `x_mesh.agent_trace` (tool names + status, no arguments). Real
tool ecosystems (file/shell/browser) remain explicitly out of scope until a
sandboxing ADR supersedes this one.

Alternatives rejected: executing client-declared function schemas directly
(prompt-injection and exfiltration surface, T-14); streaming tool deltas to
the App mid-loop (rendering ambiguity, injection risk); implementing the loop
without scheduler admission (bypasses §16 concurrency).

Requirements affected: FR-AGENT-RT, FR-CHAT-04 (stateless rule unchanged —
loop state is memory-only)   Contracts affected: §13.6 (`tools` arrival),
§16.6, T-14/SEC-11, §22.1 M8
