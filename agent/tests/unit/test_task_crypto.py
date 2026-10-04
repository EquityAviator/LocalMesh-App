"""M7 unit tests — task crypto (§13.9 encrypted at rest, ADR-011)."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from localmesh_agent.security import task_crypto


def test_roundtrip(tmp_path: Path) -> None:
    key = task_crypto.load_or_create_key(tmp_path)
    nonce, ciphertext = task_crypto.encrypt(key, b"hello task result")
    assert nonce != ciphertext and len(nonce) == task_crypto.NONCE_BYTES
    assert task_crypto.decrypt(key, nonce, ciphertext) == b"hello task result"


def test_fresh_nonce_per_call(tmp_path: Path) -> None:
    key = task_crypto.load_or_create_key(tmp_path)
    nonce_a, ciphertext_a = task_crypto.encrypt(key, b"same")
    nonce_b, ciphertext_b = task_crypto.encrypt(key, b"same")
    assert nonce_a != nonce_b
    assert ciphertext_a != ciphertext_b  # GCM nonce misuse would make these equal


def test_tamper_is_invalid_tag(tmp_path: Path) -> None:
    key = task_crypto.load_or_create_key(tmp_path)
    nonce, ciphertext = task_crypto.encrypt(key, b"canary-never-in-plaintext")
    tampered = bytearray(ciphertext)
    tampered[0] ^= 0xFF
    with pytest.raises(InvalidTag):
        task_crypto.decrypt(key, nonce, bytes(tampered))


def test_aad_binds_task_id(tmp_path: Path) -> None:
    key = task_crypto.load_or_create_key(tmp_path)
    nonce, ciphertext = task_crypto.encrypt(key, b"x", aad=b"tk_1")
    with pytest.raises(InvalidTag):
        task_crypto.decrypt(key, nonce, ciphertext, aad=b"tk_2")


def test_key_file_is_owner_only_and_stable(tmp_path: Path) -> None:
    import stat
    import sys

    key_a = task_crypto.load_or_create_key(tmp_path)
    key_b = task_crypto.load_or_create_key(tmp_path)  # second read, no regen
    assert key_a == key_b and len(key_a) == task_crypto.KEY_BYTES
    if sys.platform != "win32":
        mode = stat.S_IMODE((tmp_path / "task_results.key").stat().st_mode)
        assert mode == 0o600  # §17.6 owner-only secret material


def test_wrong_length_key_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "task_results.key").write_bytes(b"short")
    with pytest.raises(task_crypto.TaskCryptoError):
        task_crypto.load_or_create_key(tmp_path)
