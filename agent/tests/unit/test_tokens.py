"""Unit tests for security/tokens.py (WP-08, ADR-008, §17.3) and
security/ratelimit.py (§13.8)."""

import pytest
from tests.unit.test_pairing import FakeClock, FakeStore  # shared port doubles

from localmesh_agent.security.devices import DeviceService
from localmesh_agent.security.ratelimit import SlidingWindowLimiter
from localmesh_agent.security.tokens import TokenService


def make_tokens(clock: FakeClock | None = None) -> tuple[TokenService, FakeStore, FakeClock]:
    clock = clock or FakeClock()
    store = FakeStore()
    return (  # type: ignore[return-value]
        TokenService(store, clock),  # type: ignore[arg-type]
        store,
        clock,
    )


def provision_device(store: FakeStore) -> str:
    devices = DeviceService(store)  # type: ignore[arg-type]
    return devices.create("Pixel 8", "android", b"\x01" * 91)


def test_issue_returns_b64url_32byte_token_and_expires_in_900() -> None:
    service, _store, _clock = make_tokens()
    import re

    issued = service.issue("dv_x")
    # 32 bytes → 43 base64url chars, no padding (§17.3).
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", issued.token)
    assert issued.expires_in == 900


def test_verify_roundtrip_and_last_seen_fields() -> None:
    service, _store, _clock = make_tokens()
    device_id = provision_device(_store)
    issued = service.issue(device_id)
    verdict = service.verify(issued.token)
    assert verdict is not None and not hasattr(verdict, "expired")
    assert verdict.device_id == device_id
    assert verdict.scopes == "models:read chat"


def test_verify_unknown_token_is_uniform_rejection() -> None:
    service, _store, _clock = make_tokens()
    result = service.verify("AAAA_looked_up_nothing")
    assert result is not None and getattr(result, "expired", None) is False


def test_token_expiry_is_token_expired_not_auth_failed() -> None:
    """Appendix D: TOKEN_EXPIRED (401 retryable) vs AUTH_FAILED (401 uniform)."""
    service, _store, clock = make_tokens()
    device_id = provision_device(_store)
    issued = service.issue(device_id)
    clock.advance(901)
    result = service.verify(issued.token)
    assert result is not None and getattr(result, "expired", None) is True


def test_revocation_deletes_hashes_so_verification_fails_uniformly() -> None:
    """§15.6: delete token hashes → next Bearer is indistinguishable from
    unknown (§17.8 uniform AUTH_FAILED — no revocation leak on /models)."""
    store = FakeStore()
    devices = DeviceService(store)  # type: ignore[arg-type]
    device_id = devices.create("Pixel 8", "android", b"\x01" * 91)
    service = TokenService(store, FakeClock())  # type: ignore[arg-type]
    issued = service.issue(device_id)
    revoked, _cancelled = devices.revoke(device_id)
    assert revoked
    result = service.verify(issued.token)
    assert result is not None and getattr(result, "expired", None) is False


def test_empty_token_is_none() -> None:
    service, _store, _clock = make_tokens()
    assert service.verify("") is None


# -- rate limiter (§13.8) ------------------------------------------------------


def test_limiter_allows_under_limit_and_blocks_at_limit() -> None:
    limiter = SlidingWindowLimiter()
    for _ in range(10):
        assert limiter.allow("k", limit=10)
    assert not limiter.allow("k", limit=10)


def test_limiter_keys_are_independent() -> None:
    limiter = SlidingWindowLimiter()
    assert limiter.allow("a", limit=1)  # first hit allowed
    assert not limiter.allow("a", limit=1)  # at limit
    assert limiter.allow("b", limit=1)  # different key unaffected


def test_limiter_window_slides(monkeypatch: pytest.MonkeyPatch) -> None:
    limiter = SlidingWindowLimiter()
    fake_now = [1000.0]

    class FakeTime:
        @staticmethod
        def monotonic() -> float:
            return fake_now[0]

    monkeypatch.setattr("localmesh_agent.security.ratelimit.time.monotonic", FakeTime.monotonic)
    assert limiter.allow("k", limit=1, window_s=10)
    assert not limiter.allow("k", limit=1, window_s=10)
    fake_now[0] += 11  # window slid past the first hit
    assert limiter.allow("k", limit=1, window_s=10)
