"""M6 Control Plane unit tests (§12, FR-CP-01..04, QUESTION-107).

Covers the port-level contract (`ControlPlaneClient`), the Supabase REST
adapter call shapes (via `httpx.MockTransport`), and the `ControlPlaneService`
state machine (§12.3 failure mode: degrade, never block).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from localmesh_agent.adapters.controlplane import (
    ControlPlaneError,
    SupabaseControlPlaneClient,
    _iso8601,
)
from localmesh_agent.config import Settings
from localmesh_agent.core.control_plane import (
    ControlPlaneRegistrationError,
    ControlPlaneService,
    ControlPlaneState,
    registration_codec,
)
from localmesh_agent.store.sqlite import Store

SPKI = b"\x30\x59\x30\x13\x06\x07" + b"A" * 16  # shape only — adapter is opaque


def make_client(
    handler: Any,
) -> SupabaseControlPlaneClient:
    return SupabaseControlPlaneClient(
        "https://cp.test", "cp-key-1", transport=httpx.MockTransport(handler)
    )


class TestSupabaseClient:
    @pytest.mark.asyncio
    async def test_register_posts_edge_function_shape(self) -> None:
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["body"] = json.loads(request.content.decode("utf-8"))
            seen["apikey"] = request.headers.get("apikey")
            seen["auth"] = request.headers.get("Authorization")
            return httpx.Response(200, json={"device_id": "cp-row-1"})

        payload = await make_client(handler).register("code-123", "ag_x", "PC", SPKI)
        assert payload == {"device_id": "cp-row-1"}
        assert seen["url"].endswith("/functions/v1/register-agent")
        assert seen["body"]["code"] == "code-123"
        assert seen["body"]["agent_id"] == "ag_x"
        assert seen["body"]["name"] == "PC"
        assert seen["body"]["public_key"] == "\\x" + SPKI.hex()  # PostgREST bytea
        assert seen["apikey"] == "cp-key-1"
        assert seen["auth"] == "Bearer cp-key-1"

    @pytest.mark.asyncio
    async def test_register_rejects_missing_device_id(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"unexpected": True})

        with pytest.raises(ControlPlaneError):
            await make_client(handler).register("c", "ag_x", "PC", SPKI)

    @pytest.mark.asyncio
    async def test_heartbeat_patches_last_seen(self) -> None:
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["method"] = request.method
            seen["url"] = str(request.url)
            seen["body"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(204)

        await make_client(handler).heartbeat("cp-row-1", 1_700_000_000)
        assert seen["method"] == "PATCH"
        assert "id=eq.cp-row-1" in seen["url"]
        assert seen["body"] == {"last_seen": _iso8601(1_700_000_000)}

    @pytest.mark.asyncio
    async def test_mirror_revocation_counts_content_range(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert "public_key=eq." in str(request.url)
            return httpx.Response(
                200,
                json=[{"id": "1"}, {"id": "2"}],
                headers={"Content-Range": "0-1/2"},
            )

        count = await make_client(handler).mirror_revocation(SPKI, 1_700_000_000)
        assert count == 2

    @pytest.mark.asyncio
    async def test_mirror_revocation_zero_rows_is_zero(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[], headers={"Content-Range": "*/0"})

        assert await make_client(handler).mirror_revocation(SPKI, 1) == 0

    @pytest.mark.asyncio
    async def test_transport_error_maps_to_control_plane_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        with pytest.raises(ControlPlaneError) as excinfo:
            await make_client(handler).heartbeat("x", 1)
        assert excinfo.value.status is None
        # §17.6: error strings carry no URL/key/payload echoes.
        assert "cp.test" not in str(excinfo.value)
        assert "cp-key-1" not in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_non_2xx_maps_to_control_plane_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"msg": "bad key"})

        with pytest.raises(ControlPlaneError) as excinfo:
            await make_client(handler).heartbeat("x", 1)
        assert excinfo.value.status == 401


class TestServiceStateMachine:
    def make_service(
        self,
        client: Any,
        store: Store,
        *,
        device_key: bytes | None = SPKI,
        interval_s: int = 3600,
    ) -> ControlPlaneService:
        load, save, clear = registration_codec(store)
        return ControlPlaneService(
            client,
            agent_id="ag_test",
            display_name="Test PC",
            public_key_spki=SPKI,
            clock=_FakeClock(),
            load_registration=load,
            save_registration=save,
            clear_registration=clear,
            device_public_key=lambda device_id: device_key,
            heartbeat_interval_s=interval_s,
        )

    async def test_unregistered_heartbeat_is_silent_skip(self, store: Store) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            return httpx.Response(204)

        service = self.make_service(make_client(handler), store)
        assert service.state() is ControlPlaneState.UNREGISTERED
        assert await service.heartbeat_once() is False
        assert calls == []  # no CP traffic before registration

    async def test_register_persists_and_flips_state(self, store: Store) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"device_id": "cp-row-9"})

        service = self.make_service(make_client(handler), store)
        registration = await service.register("link-code")
        assert registration["cp_device_id"] == "cp-row-9"
        assert service.state() is ControlPlaneState.OK
        assert service.registered() is True
        assert service.cp_device_id() == "cp-row-9"
        # persisted via the injected store codec
        raw = store.get_setting("cp_registration")
        assert raw is not None and "cp-row-9" in raw

    async def test_register_failure_keeps_previous_state_and_degrades(self, store: Store) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        service = self.make_service(make_client(handler), store)
        with pytest.raises(ControlPlaneRegistrationError):
            await service.register("link-code")
        assert service.state() is ControlPlaneState.OFFLINE
        assert service.registered() is False
        assert service.status()["last_error"] == "register_failed"

    async def test_heartbeat_failure_reports_offline(self, store: Store) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"device_id": "cp-row-1"})

        service = self.make_service(make_client(handler), store)
        await service.register("c")

        def broken(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        service._client = make_client(broken)  # simulate CP going down
        assert await service.heartbeat_once() is False
        assert service.state() is ControlPlaneState.OFFLINE
        assert service.status()["last_error"] == "heartbeat_failed"

    async def test_mirror_uses_device_public_key(self, store: Store) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(200, json=[], headers={"Content-Range": "*/1"})

        service = self.make_service(make_client(handler), store)
        count = await service.mirror_device_revocation("dv_1", 123)
        assert count == 1
        assert "public_key=eq." in seen[0]

    async def test_mirror_without_known_key_is_zero_traffic(self, store: Store) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            return httpx.Response(200)

        service = self.make_service(make_client(handler), store, device_key=None)
        assert await service.mirror_device_revocation("dv_unknown", 123) == 0
        assert calls == []

    async def test_heartbeat_loop_ticks_and_stops(self, store: Store) -> None:
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(204)

        service = self.make_service(
            make_client(handler),
            store,
            interval_s=0,  # 0 → immediate ticks
        )
        # Pre-register via the same codec so the loop has a device id.
        service._save_registration(
            {"cp_device_id": "cp-loop", "agent_id": "ag_test", "registered_at": 1}
        )
        service.start()
        for _ in range(200):
            if calls:
                break
            await asyncio.sleep(0.005)
        service._heartbeat_interval_s = 3600  # no further ticks
        await asyncio.sleep(0.02)
        ticks_after_stop_probe = len(calls)
        await service.stop()
        await asyncio.sleep(0.02)
        assert calls, "heartbeat loop never ticked"
        assert len(calls) <= ticks_after_stop_probe + 1  # bounded, no runaway

    def test_status_is_metadata_only(self, store: Store) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(204)

        service = self.make_service(make_client(handler), store)
        block = service.status()
        assert set(block) == {
            "enabled",
            "state",
            "registered",
            "registered_at",
            "heartbeat_interval_s",
            "last_error",
        }
        blob = json.dumps(block)
        assert "cp-key" not in blob and "https://cp.test" not in blob  # §17.6


class _FakeClock:
    def now_monotonic(self) -> float:
        return 0.0

    def now_wall(self) -> int:
        return 1_700_000_000


class TestRegistrationCodec:
    def test_roundtrip_over_concrete_store(self, store: Store) -> None:
        load, save, clear = registration_codec(store)
        assert load() is None
        save({"cp_device_id": "x", "agent_id": "ag", "registered_at": 5})
        assert load() == {"cp_device_id": "x", "agent_id": "ag", "registered_at": 5}
        clear()
        assert load() is None

    def test_corrupt_payload_reads_as_none(self, store: Store) -> None:
        load, _save, _clear = registration_codec(store)
        store.set_setting("cp_registration", "{not json")
        assert load() is None


class TestConfigGate:
    def test_disabled_by_default(self) -> None:
        settings = Settings(agent={"data_dir": "/tmp/x"})
        assert settings.control_plane.enabled is False

    def test_enabled_requires_url_and_auth_ref(self) -> None:
        with pytest.raises(ValidationError):
            Settings(
                agent={"data_dir": "/tmp/x"},
                control_plane={"enabled": True, "auth_ref": "k"},
            )
        with pytest.raises(ValidationError):
            Settings(
                agent={"data_dir": "/tmp/x"},
                control_plane={"enabled": True, "url": "http://insecure.test", "auth_ref": "k"},
            )
        with pytest.raises(ValidationError):
            Settings(
                agent={"data_dir": "/tmp/x"},
                control_plane={"enabled": True, "url": "https://cp.test"},
            )
        settings = Settings(
            agent={"data_dir": "/tmp/x"},
            control_plane={"enabled": True, "url": "https://cp.test", "auth_ref": "k"},
        )
        assert settings.control_plane.heartbeat_interval_s == 60  # §12.3 default
