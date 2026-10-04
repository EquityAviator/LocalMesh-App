"""Supabase REST Control Plane client (M6, §12; FR-CP-01..03).

Concrete :class:`localmesh_agent.adapters.ports.ControlPlaneClient`. Talks to
a self-hosted/Supabase PostgREST surface. Everything here is **Metadata
only** (§12.1 "Does NOT carry prompts/outputs/files"; FR-CP-04) — the only
payloads are ids, names, public keys and timestamps.

Call shapes `[UNVERIFIED — verify at M6 deployment]` (§12.3, QUESTION-107):
the spec names the flows, not the REST calls. Chosen conventions:

- Row access via PostgREST table ``devices`` (§12.2 schema verbatim):
  ``GET/PATCH/POST {url}/rest/v1/devices``.
- Registration one-time-link code exchange via an Edge Function:
  ``POST {url}/functions/v1/register-agent`` (§12.3 "Register Agent" flow).
- Auth: ``apikey`` + ``Authorization: Bearer`` headers with the key read
  from the OS keyring at startup (§17.6 — never from config).
- ``bytea`` columns are exchanged as PostgREST hex strings (``\\x…``).

Every failure raises :class:`ControlPlaneError`; the core service degrades
(§12.3 failure mode) — nothing here is allowed to take the Agent down.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from localmesh_agent.observability.logging import get_logger

log = get_logger("controlplane")

_TIMEOUT_S = 5.0  # §10.5 bounded-wait spirit: CP is best effort, never blocking


class ControlPlaneError(RuntimeError):
    """Raised when a Control Plane call fails (status or transport)."""

    def __init__(self, operation: str, status: int | None, detail: str) -> None:
        # No URL / key / payload echoes in the message (§17.6, no secrets).
        super().__init__(f"control plane {operation} failed (status={status})")
        self.operation = operation
        self.status = status
        self.detail = detail


def _bytea(value: bytes) -> str:
    """Encode bytes as a PostgREST ``bytea`` hex literal (`\\x…`)."""
    return "\\x" + value.hex()


class SupabaseControlPlaneClient:
    """PostgREST/Edge-Function client for the §12.2 ``devices`` table."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout_s: float = _TIMEOUT_S,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # `transport` is injectable for tests (httpx.MockTransport).
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout_s = timeout_s
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        headers = {
            "apikey": self._api_key,
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=self._timeout_s,
            transport=self._transport,
        )

    async def register(
        self, code: str, agent_id: str, name: str, public_key_spki: bytes
    ) -> dict[str, Any]:
        """Exchange the one-time link code (§12.3 "Register Agent").

        The Edge Function validates the code against the signed-in Phone's
        account and returns the CP device row id `[UNVERIFIED]`.
        """
        body = {
            "code": code,
            "agent_id": agent_id,
            "name": name,
            "public_key": _bytea(public_key_spki),
        }
        async with self._client() as client:
            try:
                response = await client.post("/functions/v1/register-agent", json=body)
            except httpx.HTTPError as exc:
                raise ControlPlaneError("register", None, type(exc).__name__) from exc
        if response.status_code // 100 != 2:
            raise ControlPlaneError("register", response.status_code, "non-2xx")
        try:
            payload = json.loads(response.content.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ControlPlaneError("register", response.status_code, "bad json") from exc
        device_id = payload.get("device_id") if isinstance(payload, dict) else None
        if not isinstance(device_id, str) or not device_id:
            raise ControlPlaneError("register", response.status_code, "missing device_id")
        return payload

    async def heartbeat(self, cp_device_id: str, last_seen_epoch: int) -> None:
        """Upsert `last_seen` (§12.3 "Heartbeat", default 60 s cadence)."""
        body = {"last_seen": _iso8601(last_seen_epoch)}
        url = f"/rest/v1/devices?id=eq.{cp_device_id}"
        async with self._client() as client:
            try:
                response = await client.patch(url, json=body, headers={"Prefer": "return=minimal"})
            except httpx.HTTPError as exc:
                raise ControlPlaneError("heartbeat", None, type(exc).__name__) from exc
        if response.status_code // 100 != 2:
            raise ControlPlaneError("heartbeat", response.status_code, "non-2xx")

    async def mirror_revocation(self, public_key_spki: bytes, revoked_at_epoch: int) -> int:
        """Mirror a local revocation (FR-CP-03) by public key match.

        The CP row for the revoked phone is updated with ``revoked_at`` so the
        owner's other devices notice. The Agent keeps its own store as the
        authority (§12.1 "Does NOT replace local revocation").
        """
        body = {"revoked_at": _iso8601(revoked_at_epoch)}
        url = f"/rest/v1/devices?public_key=eq.{_bytea(public_key_spki)}"
        async with self._client() as client:
            try:
                response = await client.patch(
                    url, json=body, headers={"Prefer": "return=representation", "Count": "exact"}
                )
            except httpx.HTTPError as exc:
                raise ControlPlaneError("mirror_revocation", None, type(exc).__name__) from exc
        if response.status_code // 100 != 2:
            raise ControlPlaneError("mirror_revocation", response.status_code, "non-2xx")
        # PostgREST returns the affected row count in Content-Range
        # (`return=representation` + `Count=exact`); fall back to the body
        # length, then to 0 — the mirror is best effort by contract.
        content_range = response.headers.get("Content-Range", "")
        count = _parse_content_range_count(content_range)
        if count is None:
            try:
                rows = json.loads(response.content.decode("utf-8"))
                count = len(rows) if isinstance(rows, list) else 0
            except (ValueError, UnicodeDecodeError):
                count = 0
        return count


def _iso8601(epoch_s: int) -> str:
    """Epoch seconds → ISO-8601 UTC (Postgres ``timestamptz`` text input)."""
    import datetime as _dt

    return (
        _dt.datetime.fromtimestamp(epoch_s, tz=_dt.UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _parse_content_range_count(content_range: str) -> int | None:
    """Extract the total count from ``Content-Range: 0-1/2`` (or ``*/2``)."""
    if "/" not in content_range:
        return None
    total = content_range.rsplit("/", 1)[1]
    if total == "*":
        return None
    try:
        return int(total)
    except ValueError:
        return None
