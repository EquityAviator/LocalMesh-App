# tools/fake-backends

Fake LM Studio + fake Ollama HTTP servers used by Agent integration tests
(LM-ARCH-001 §10.1, §21.5). **Test assets only** — not part of the Agent, never
on any content path, loopback-bound.

## Implemented (§21.5 required behaviours)

| Behaviour | Fake LM Studio | Fake Ollama |
|---|---|---|
| Streaming SSE with `[DONE]` | `POST /v1/chat/completions` (`stream:true`) | same |
| Mid-stream disconnect | `X-Fake-Backend-Scenario: mid-stream-disconnect` | same |
| Slow first token (cold load) | `X-Fake-Backend-Scenario: slow-first-token` + `X-Fake-Backend-Delay-Ms`, plus demand-load simulation (`--cold-load-ms`) | same (header-driven) |
| HTTP 500s | `X-Fake-Backend-Scenario: http-500` | same |
| Model-list shape variants | `X-Fake-Backend-Scenario: shape-variant-a|b|c` on `/api/v1/models` and `/v1/models` | same on `/api/tags` |
| no-auth / token-auth modes | `--auth none` (default, §6.1) / `--auth token --token X` | no-auth only, by construction (Ollama has no auth, §6.2) |

## Endpoints

Fake LM Studio (§6.1 only): `GET /api/v1/models`, `POST /api/v1/models/load`,
`POST /api/v1/models/unload`, `GET /v1/models`, `POST /v1/chat/completions`.
Deliberately absent (Appendix C traps; tests assert 404): `/v1/list_models`,
`/v1/load_model`, `/api/v0/*`, and `/api/v1/chat` (native chat is not used in
v1, ADR-009).

Fake Ollama (§6.2): `GET /api/tags`, `GET /api/ps`, `POST /api/show`,
`POST /v1/chat/completions`, `POST /api/chat` (NDJSON, for keep-warm tests).
`/api/generate` intentionally absent. `keep_alive` on the `/v1` path is
`[UNVERIFIED]` (§6.2) and is ignored by the fake.

## UNVERIFIED_SHAPE rule

No real-Backend fixtures existed at capture time, so **every synthetic response
is explicitly marked**: header `X-Fake-Backend-Shape: UNVERIFIED_SHAPE`, a
top-level `_localmesh_fake` marker object on JSON bodies, and an SSE comment on
streams. Model-list variants are tolerance-training shapes for the adapter
parsers — they are NOT claims about real Backend shapes.

**Fixtures from real Backends outrank fakes** (§21.5). Run the capture in
`docs/fixtures/CAPTURE.md`, commit files under `docs/fixtures/<backend>/<version>/`,
then start the fakes with `--fixtures-dir` to serve recorded bodies verbatim
(marked `RECORDED_FIXTURE`). Contract tests (WP-05) then run against fixtures,
not fakes.

## Run

```bash
python tools/fake-backends/fake_lmstudio.py --port 1234 [--auth token --token SECRET]
python tools/fake-backends/fake_ollama.py --port 11434
```

Self-tests: `pytest tools/fake-backends/tests` (run by the §21.4 CI pipeline,
"integration tests" layer). Zero runtime dependencies beyond stdlib for the
servers; the tests use `httpx`/`pytest` from the agent toolchain.

**Note:** the fake CLIs are test-tool surface — not Mesh API (§13) or Agent CLI
(§10.1) contract, and carry no compatibility promise.
