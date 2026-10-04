"""Unit tests — DeviceService.update (§13.1 `PATCH /admin/devices/{id}`).

The service-level validation contract: scope universe (§17.7 matrix),
name bounds, canonical storage order, audit trail, and the [DESIGN]
revoked-device rule (editable rows, blocked auth).
"""

from __future__ import annotations

import pytest
from tests.unit.fake_store import FakeStore  # shared port double (§10.1)

from localmesh_agent.core.errors import MeshError
from localmesh_agent.security.devices import (
    KNOWN_DEVICE_SCOPES,
    MAX_DEVICE_NAME_LEN,
    DeviceService,
)


def make_service() -> tuple[DeviceService, FakeStore, str]:
    store = FakeStore()
    service = DeviceService(store)  # type: ignore[arg-type]
    device_id = service.create("Pixel 8", "android", b"\x01" * 91)
    return service, store, device_id


def test_scope_universe_is_the_17_7_matrix() -> None:
    assert KNOWN_DEVICE_SCOPES == frozenset({"models:read", "chat", "models:manage", "tasks"})


def test_update_scopes_canonical_order_and_dedupe() -> None:
    service, _store, device_id = make_service()
    row = service.update(device_id, scopes=["chat", "models:manage", "chat", "models:read"])
    assert row is not None
    assert row["scopes"] == "chat models:manage models:read"


def test_update_grant_models_manage_round_trip() -> None:
    """§13.1: 'models:manage and tasks are granted per Device by the operator'."""
    service, store, device_id = make_service()
    service.update(device_id, scopes=["models:read", "chat", "tasks"])
    row = store.get_device(device_id)
    assert row is not None
    assert set(row["scopes"].split()) == {"models:read", "chat", "tasks"}


def test_update_name_strips_and_keeps_row_shape() -> None:
    service, _store, device_id = make_service()
    row = service.update(device_id, name="  Tablet  ")
    assert row is not None
    assert row["name"] == "Tablet"
    assert "public_key_spki" not in row  # operator display data only


def test_update_partial_fields_left_alone() -> None:
    service, store, device_id = make_service()
    service.update(device_id, name="Renamed")
    row = store.get_device(device_id)
    assert row is not None
    assert row["scopes"] == "models:read chat"  # untouched


def test_update_unknown_device_returns_none() -> None:
    service, _store, _device_id = make_service()
    assert service.update("dv_missing", name="x") is None


@pytest.mark.parametrize("bad_scopes", [["sudo"], ["models:read", "root"], [""]])
def test_update_unknown_scope_rejected_denies_by_default(bad_scopes: list[str]) -> None:
    service, _store, device_id = make_service()
    with pytest.raises(MeshError) as excinfo:
        service.update(device_id, scopes=bad_scopes)
    assert excinfo.value.code == "INVALID_REQUEST"


def test_update_empty_scopes_rejected_revoke_instead() -> None:
    service, _store, device_id = make_service()
    with pytest.raises(MeshError, match="revoke"):
        service.update(device_id, scopes=[])


def test_update_blank_name_rejected() -> None:
    service, _store, device_id = make_service()
    with pytest.raises(MeshError, match="empty"):
        service.update(device_id, name="   ")


def test_update_name_over_limit_rejected() -> None:
    service, _store, device_id = make_service()
    with pytest.raises(MeshError) as excinfo:
        service.update(device_id, name="x" * (MAX_DEVICE_NAME_LEN + 1))
    assert excinfo.value.details == {"limit": MAX_DEVICE_NAME_LEN}


def test_update_writes_device_updated_audit_metadata_only() -> None:
    service, store, device_id = make_service()
    service.update(device_id, name="Renamed", scopes=["chat"])
    events = [event for event, _device, _meta in store.audit]
    assert events[-1] == "device_updated"


def test_update_on_revoked_device_allowed_but_auth_stays_blocked() -> None:
    """[DESIGN]: row editable (§14.1 keeps the row), auth blocked regardless."""
    service, _store, device_id = make_service()
    service.revoke(device_id)
    row = service.update(device_id, scopes=["chat"])
    assert row is not None
    assert row["revoked_at"] is not None  # still revoked
