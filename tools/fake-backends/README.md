# tools/fake-backends

Fake LM Studio + fake Ollama HTTP servers used by Agent integration tests (§10.1, §21.5).

Must reproduce (§21.5): streaming SSE with `[DONE]`, mid-stream disconnect, slow first token (cold load), HTTP 500s, model-list shape variants, no-auth and token-auth modes.

Response shapes MUST come from recorded real-Backend fixtures (`docs/fixtures/`); where no fixture exists responses are explicitly marked `UNVERIFIED_SHAPE`. Fixtures from real Backends outrank fakes.

**Status M0:** implemented in WP-03.
