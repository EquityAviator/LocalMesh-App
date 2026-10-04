# Fixtures — recorded real Backend responses

Fixtures are **captured from real Backends only** (LM-ARCH-001 §21.5:
"Fixtures from real Backends outrank fakes"; §6.1: adapters MUST be written
against recorded real responses). Never fabricate a fixture from memory —
that is an anti-hallucination violation (§1.2).

## Layout

```
docs/fixtures/
  CAPTURE.md                        # how to capture; what to paste back (exists if fixtures are missing)
  lmstudio/<backend-version>/       # e.g. lmstudio/0.3.9/ — one dir per Backend version
    api-v1-models.json              # GET  /api/v1/models          (§6.1)
    v1-models.json                  # GET  /v1/models              (OpenAI-compatible, §6.1)
    chat-completions-stream.txt     # POST /v1/chat/completions    (stream=true, raw SSE bytes, §6.1)
    ...
  ollama/<backend-version>/         # e.g. ollama/0.x.y/
    api-tags.json                   # GET  /api/tags               (§6.2)
    api-ps.json                     # GET  /api/ps                 (§6.2)
    api-show.json                   # POST /api/show               (§6.2)
    chat-completions-stream.txt     # POST /v1/chat/completions    (stream=true, raw SSE bytes)
    ...
```

Every fixture directory MUST contain a `README.md` recording: Backend name and
exact version, host OS, capture date, and the exact commands used.

## Rules

1. Real responses only; redact nothing except local hostnames if desired (no
   Content in fixtures beyond a fixed canary prompt used for capture — fixures
   are test data, not logs).
2. Raw SSE is stored verbatim (including `[DONE]` and any keepalives).
3. Fixture-bearing responses drive the Backend adapter contract tests (WP-05)
   and outrank the fake backends (`tools/fake-backends/`) whenever both exist.
4. If a needed fixture is missing, `docs/fixtures/CAPTURE.md` lists it as a
   blocker for the adapter work (M1) — do not improvise shapes.
