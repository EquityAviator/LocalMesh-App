"""TC-SEC-05 — unauthenticated fuzz of every endpoint (§17.13 L5).

Spec: "TC-SEC-05 unauth fuzz of every endpoint". Repeatable and deterministic
(a fixed garbage battery per route — no random corpus). For EVERY public
`/mesh/v1/*` route and EVERY loopback admin route we assert:

1. never a 5xx — garbage input yields §13.4 error envelopes (401/403/404/405/
   410/413/422/429), never an unhandled exception;
2. every error body matches the §13.4 envelope shape
   ``{error: {code, message, retryable, request_id, details}}``;
3. no reflection: the fuzz marker (attacker-controlled input) never appears
   in a response body — error messages are human-readable, never echo input
   (§13.4 "never contains Content or backend raw bodies");
4. no stack traces in bodies;
5. ``X-Mesh-Request-Id`` present on every public response (§13.3);
6. the admin listener rejects a forged Host (ADR-014 / TC-SEC-06 companion)
   and every request lacking the correct ``X-Admin-Token`` header — handlers
   are therefore never reachable by the fuzz (asserted via fail-closed stubs).

Routes are enumerated from the REAL FastAPI apps, so a future endpoint cannot
dodge the fuzz by simply existing (pinned by the coverage test below).
"""

import json
import socket
import threading
from pathlib import Path
from typing import Any

import httpx

from localmesh_agent.admin_app import create_admin_app
from localmesh_agent.app import create_app
from localmesh_agent.config import Settings

MARKER = "FuzzMarker-7f3a9-ATTACKER_INPUT"
BIG_MARKER = "A" * 65536  # 64 KiB junk field (well under the 2 MiB body cap)
ENVELOPE_KEYS = {"code", "message", "retryable", "request_id", "details"}

# Template path params -> attacker-controlled junk values.
PATH_PARAM_JUNK: dict[str, str] = {
    "request_id": "rq_GARBAGE../../x",
    "pair_id": "pr_GARBAGE",
    "device_id": "dv_GARBAGE'--",
}


def _junk_path(path: str) -> str:
    for param, junk in PATH_PARAM_JUNK.items():
        path = path.replace("{" + param + "}", junk)
    return path


def _auth_variants() -> list[dict[str, str]]:
    return [
        {},  # no Authorization header at all
        {"Authorization": "Bearer !!!garbage"},
        {"Authorization": "Bearer AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"},
        {"Authorization": f"Bearer {MARKER}"},
    ]


def _fuzz_bodies(method: str) -> list[tuple[str, bytes | None]]:
    """(content-type, raw body) battery; single bodyless entry for GET/DELETE."""
    if method not in ("POST", "PUT", "PATCH"):
        return [("", None)]
    return [
        ("application/json", json.dumps({}).encode()),
        ("application/json", json.dumps({"__fuzz__": MARKER}).encode()),
        ("application/json", json.dumps({"model": 123, "messages": MARKER}).encode()),
        ("application/json", json.dumps({"nested": {"deep": {"x": BIG_MARKER}}}).encode()),
        ("application/json", b"not-json{{" + MARKER[:8].encode()),
        ("text/plain", MARKER.encode()),
        ("application/octet-stream", b"\x00\x01\x02" + MARKER[:8].encode()),
    ]


def _routes(app: Any, prefix: str) -> list[tuple[str, str]]:
    """Enumerate (path, METHOD) from the app's own OpenAPI schema — the
    authoritative served surface (works with FastAPI's lazy _IncludedRouter,
    which hides APIRoutes from app.routes)."""
    schema = app.openapi()
    return sorted(
        (path, method.upper())
        for path, operations in schema["paths"].items()
        if path.startswith(prefix)
        for method in operations
        if method.lower() in ("get", "post", "put", "patch", "delete")
    )


def _assert_public_response(method: str, response: httpx.Response) -> None:
    assert response.status_code < 500, (
        f"TC-SEC-05: {method} returned {response.status_code} for unauth fuzz "
        f"({response.text[:200]})"
    )
    assert "Traceback" not in response.text
    assert MARKER not in response.text, "responses must not reflect attacker input"
    assert response.headers.get("X-Mesh-Request-Id", "").startswith("rq_")
    body = response.json()
    if response.status_code < 400:
        # No-auth routes (§13.1: GET /info, auth bootstrap, pairing) may
        # succeed without a token — 2xx bodies are route-specific shapes.
        assert isinstance(body, dict)
        return
    assert set(body) == {"error"}, f"non-envelope body for {method}: {body}"
    err = body["error"]
    assert set(err) == ENVELOPE_KEYS
    assert isinstance(err["code"], str) and err["code"]
    assert isinstance(err["message"], str) and err["message"]
    assert isinstance(err["retryable"], bool)


class _DeadSink:
    """Socket sink: accepts and never answers (fail-closed fuzz target)."""

    def __init__(self) -> None:
        self._sock = socket.socket()
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self.port = int(self._sock.getsockname()[1])
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self._sock.accept()
                del conn  # never read/respond
            except OSError:  # shutdown race — fine
                return

    def close(self) -> None:
        self._sock.close()


def build_public_app(tmp_path: Path) -> Any:
    """Real public app, Device Token auth ENFORCED (dev_insecure=False)."""
    sink = _DeadSink()
    settings = Settings(
        agent={"data_dir": str(tmp_path)},
        backends=[
            {"id": "lmstudio", "kind": "lmstudio", "base_url": f"http://127.0.0.1:{sink.port}"}
        ],
    )
    app = create_app(settings, dev_insecure=False)
    return app, sink


class _NeverReachable:
    """Admin handler stubs — fail the test loudly if the guard is bypassed."""

    def _nope(self) -> None:
        raise AssertionError("admin fuzz must never reach handlers")

    open = _nope
    pending = _nope
    approve = _nope
    deny = _nope
    close = _nope


def build_admin_app() -> Any:
    return create_admin_app(
        pairing=_NeverReachable(),  # type: ignore[arg-type]
        devices=object(),  # type: ignore[arg-type]
        tls_rotate=lambda: "sha256-GARBAGE",
        admin_token="correct-admin-token",
        admin_port=8444,
    )


async def test_tc_sec_05_public_endpoints_fuzz(tmp_path: Path) -> None:
    """Every /mesh/v1 route × auth variants × body battery."""
    public, sink = build_public_app(tmp_path)
    routes = _routes(public, "/mesh/v1")
    assert len(routes) >= 12, f"route enumeration regressed: {routes}"
    try:
        async with public.router.lifespan_context(public):  # type: ignore[attr-defined]
            transport = httpx.ASGITransport(app=public)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                for path, method in routes:
                    target = _junk_path(path)
                    for auth in _auth_variants():
                        for content_type, body in _fuzz_bodies(method):
                            headers = dict(auth)
                            if body is not None:
                                headers["Content-Type"] = content_type
                            response = await client.request(
                                method,
                                target + f"?fuzz={MARKER[:16]}",
                                content=body,
                                headers=headers,
                            )
                            _assert_public_response(method, response)
    finally:
        sink.close()


async def test_tc_sec_05_no_route_escapes_enumeration(tmp_path: Path) -> None:
    """Pin the covered route set so new endpoints must join the fuzz."""
    public, sink = build_public_app(tmp_path)
    try:
        covered = {path for path, _ in _routes(public, "/mesh/v1")}
    finally:
        sink.close()
    assert {
        "/mesh/v1/info",
        "/mesh/v1/health",
        "/mesh/v1/models",
        "/mesh/v1/models/load",
        "/mesh/v1/models/unload",
        "/mesh/v1/chat/completions",
        "/mesh/v1/requests/{request_id}",
        "/mesh/v1/device",
        "/mesh/v1/auth/challenge",
        "/mesh/v1/auth/token",
    } <= covered


async def test_tc_sec_05_admin_listener_fuzz() -> None:
    """Admin surface: forged Host → 403; missing/wrong token → 401; envelope
    everywhere; handlers never reached."""
    admin = build_admin_app()
    routes = _routes(admin, "/admin")
    assert len(routes) >= 8, f"admin route enumeration regressed: {routes}"

    transport = httpx.ASGITransport(app=admin)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8444") as client:
        for path, method in routes:
            target = _junk_path(path)
            # 1. Forged Host (DNS-rebinding attempt, ADR-014 / TC-SEC-06).
            response = await client.request(
                method,
                target,
                headers={"Host": "evil.example", "X-Admin-Token": "correct-admin-token"},
            )
            assert response.status_code == 403, f"{method} {path}: {response.text[:200]}"
            err = response.json()["error"]
            assert set(err) == ENVELOPE_KEYS and err["code"] == "FORBIDDEN_SCOPE"
            # 2. Correct Host, NO token.
            response = await client.request(method, target, headers={"Host": "127.0.0.1:8444"})
            assert response.status_code == 401
            err = response.json()["error"]
            assert set(err) == ENVELOPE_KEYS and err["code"] == "AUTH_REQUIRED"
            # 3. Correct Host, WRONG token (must not reflect the token).
            response = await client.request(
                method,
                target,
                headers={"Host": "127.0.0.1:8444", "X-Admin-Token": MARKER},
            )
            assert response.status_code == 401
            assert MARKER not in response.text
