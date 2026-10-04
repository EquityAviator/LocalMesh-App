# CAPTURE.md — how to record the real-Backend fixtures (owner action needed)

M0 requires fixtures **captured from real Backends** (LM-ARCH-001 §21.5:
"Fixtures from real Backends outrank fakes"; §6.1: adapters MUST be written
against recorded real responses). The WP-02 environment had **no LM Studio and
no Ollama** running, so nothing was fabricated. Instead: run the commands below
on the PC where the Backends run, and commit the outputs under
`docs/fixtures/<backend>/<backend-version>/` (layout rules:
`docs/fixtures/README.md`).

**Why this blocks M1:** WP-05 (Backend adapters) must write its contract tests
against these recorded responses. Until they exist, adapter work has no
authoritative shapes, and the fake backends mark non-contract fields
`UNVERIFIED_SHAPE`.

General rules while capturing:

- Start each capture with a fresh terminal; note OS, Backend version (LM Studio:
  app UI → about, or `GET /api/v1/models` response `product_version` field if
  present; Ollama: `ollama --version`), and date.
- Save response **headers and body separately** — field names AND status codes
  both matter. Use the `-D` flag of curl as shown.
- For streaming captures, redirect raw bytes — do not pipe through jq/pretty
  printers (we need exact SSE framing: `data:` lines, blank lines, `[DONE]`).
- If a Backend is configured with an API token (LM Studio can require one), also
  capture one unauthorized (no token) response for the 401 shape.
- Do NOT redact or "clean up" JSON — odd shapes are exactly what we need.

---

## 1. LM Studio (replace `LMVER` with your exact app version, e.g. `0.4.2`)

```bash
OUT=docs/fixtures/lmstudio/LMVER   # then rename LMVER below or use the real value
mkdir -p "$OUT"

# 1. Native model list (§6.1: GET /api/v1/models)
curl -sS -D "$OUT/api-v1-models.headers.txt" http://127.0.0.1:1234/api/v1/models \
     -o "$OUT/api-v1-models.json"

# 2. OpenAI-compatible model list (§6.1: GET /v1/models)
curl -sS -D "$OUT/v1-models.headers.txt" http://127.0.0.1:1234/v1/models \
     -o "$OUT/v1-models.json"

# 3. OpenAI-compatible streaming chat (§6.1: POST /v1/chat/completions, SSE)
#    Replace MODELID with a model id exactly as it appears in capture #2.
curl -sS -N -D "$OUT/chat-completions-stream.headers.txt" \
     http://127.0.0.1:1234/v1/chat/completions \
     -H 'Content-Type: application/json' \
     -d '{"model":"MODELID","stream":true,"messages":[{"role":"user","content":"Count from 1 to 5."}],"max_tokens":64}' \
     -o "$OUT/chat-completions-stream.txt"

# 4. (If your server has an API token enabled in LM Studio settings)
#    a) unauthorized shape:
curl -sS -D "$OUT/api-v1-models.unauthorized.headers.txt" http://127.0.0.1:1234/api/v1/models \
     -o "$OUT/api-v1-models.unauthorized.json"
#    b) authorized shape (TOKEN = the token):
curl -sS -D "$OUT/api-v1-models.authenticated.headers.txt" http://127.0.0.1:1234/api/v1/models \
     -H 'Authorization: Bearer TOKEN' \
     -o "$OUT/api-v1-models.authenticated.json"

# 5. Native chat (optional but useful — NOT used in v1 per ADR-009, recorded for completeness)
curl -sS -N -D "$OUT/api-v1-chat-stream.headers.txt" \
     http://127.0.0.1:1234/api/v1/chat \
     -H 'Content-Type: application/json' \
     -d '{"model":"MODELID","messages":[{"role":"user","content":"Count from 1 to 5."}],"stream":true}' \
     -o "$OUT/api-v1-chat-stream.txt"
```

Then write `docs/fixtures/lmstudio/LMVER/README.md` with: LM Studio exact
version, host OS, capture date, and the exact commands used.

---

## 2. Ollama (replace `OLVER` with `ollama --version` output, e.g. `0.13.1`)

```bash
ollama --version > docs/fixtures/ollama-version.txt   # paste into README too
OUT=docs/fixtures/ollama/OLVER
mkdir -p "$OUT"

# 1. Models on disk (§6.2: GET /api/tags)
curl -sS -D "$OUT/api-tags.headers.txt" http://127.0.0.1:11434/api/tags \
     -o "$OUT/api-tags.json"

# 2. Models in memory incl. VRAM footprint (§6.2: GET /api/ps)
#    Tip: `ollama run MODELID` first so at least one model is loaded.
curl -sS -D "$OUT/api-ps.headers.txt" http://127.0.0.1:11434/api/ps \
     -o "$OUT/api-ps.json"

# 3. Model details incl. context length / quantization (§6.2: POST /api/show)
#    Replace MODELID with an id from capture #1.
curl -sS -D "$OUT/api-show.headers.txt" http://127.0.0.1:11434/api/show \
     -H 'Content-Type: application/json' \
     -d '{"model":"MODELID"}' \
     -o "$OUT/api-show.json"

# 4. OpenAI-compatible streaming chat (§6.2: POST /v1/chat/completions, SSE)
curl -sS -N -D "$OUT/chat-completions-stream.headers.txt" \
     http://127.0.0.1:11434/v1/chat/completions \
     -H 'Content-Type: application/json' \
     -d '{"model":"MODELID","stream":true,"messages":[{"role":"user","content":"Count from 1 to 5."}],"max_tokens":64}' \
     -o "$OUT/chat-completions-stream.txt"

# 5. OpenAI-compatible non-streaming chat (used by fake-backend non-stream mode)
curl -sS -D "$OUT/chat-completions-nonstream.headers.txt" \
     http://127.0.0.1:11434/v1/chat/completions \
     -H 'Content-Type: application/json' \
     -d '{"model":"MODELID","stream":false,"messages":[{"role":"user","content":"Say OK."}],"max_tokens":8}' \
     -o "$OUT/chat-completions-nonstream.json"

# 6. keep_alive probe — answers §6.2 [UNVERIFIED]: is keep_alive honored on /v1?
curl -sS -D "$OUT/chat-completions-keepalive.headers.txt" \
     http://127.0.0.1:11434/v1/chat/completions \
     -H 'Content-Type: application/json' \
     -d '{"model":"MODELID","stream":false,"keep_alive":"5m","messages":[{"role":"user","content":"Say OK."}],"max_tokens":8}' \
     -o "$OUT/chat-completions-keepalive.json"
#    Then: immediately after this call, check `curl -s http://127.0.0.1:11434/api/ps`
#    and save whether the model expiry reflects 5m: save as $OUT/api-ps-after-keepalive.json
curl -sS http://127.0.0.1:11434/api/ps -o "$OUT/api-ps-after-keepalive.json"
```

Then write `docs/fixtures/ollama/OLVER/README.md` with: Ollama exact version,
host OS, capture date, exact commands.

---

## 3. Checklist to paste back (tick when committed)

- [ ] `docs/fixtures/lmstudio/<version>/api-v1-models.json` (+ headers)
- [ ] `docs/fixtures/lmstudio/<version>/v1-models.json` (+ headers)
- [ ] `docs/fixtures/lmstudio/<version>/chat-completions-stream.txt` (raw SSE)
- [ ] `docs/fixtures/lmstudio/<version>/README.md` (version/OS/date/commands)
- [ ] `docs/fixtures/ollama/<version>/api-tags.json` (+ headers)
- [ ] `docs/fixtures/ollama/<version>/api-ps.json` (+ headers)
- [ ] `docs/fixtures/ollama/<version>/api-show.json` (+ headers)
- [ ] `docs/fixtures/ollama/<version>/chat-completions-stream.txt` (raw SSE)
- [ ] `docs/fixtures/ollama/<version>/README.md` (version/OS/date/commands)
- [ ] keep-alive probe result (answers §6.2 [UNVERIFIED])

Once committed: delete this file's blocker note in WP-05, run the capture
commands' outputs through the adapter contract tests, and the fake backends
switch from `UNVERIFIED_SHAPE` marking to fixture-loaded shapes.
