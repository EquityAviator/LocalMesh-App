"""Task result encryption at rest (M7, §13.9 + ADR-011).

§13.9: task "Results retained ≤ 1 h, encrypted at rest, deleted on fetch-ack
or expiry (ADR-011)." ADR-011/FR-CHAT-04 keep the Agent stateless for chat;
durable Tasks are the sanctioned exception ONLY because the result bytes are
ciphertext at rest and carry a hard expiry (TC-SEC-01 canary greps stay clean).

Scheme [DESIGN within §13.9's mandate]: AES-256-GCM (cryptography lib,
§21.2 approved stack) with a fresh 12-byte nonce per encrypt; the key is a
per-install 32-byte value generated once and persisted **owner-only**
(0600, same rule as the admin token / TLS keys, §17.6) in the data dir.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_BYTES = 32  # AES-256
NONCE_BYTES = 12  # GCM standard nonce size

_KEY_FILENAME = "task_results.key"


class TaskCryptoError(RuntimeError):
    """Raised when the at-rest key material is unusable (fail closed)."""


def load_or_create_key(data_dir: Path) -> bytes:
    """Per-install 32-byte key, created once, file 0600 (§17.6)."""
    path = data_dir / _KEY_FILENAME
    if path.exists():
        key = path.read_bytes()
        if len(key) != KEY_BYTES:
            raise TaskCryptoError("task results key has wrong length; refusing to decrypt")
        return key
    key = os.urandom(KEY_BYTES)
    path.write_bytes(key)
    if sys.platform != "win32":
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
    return key


def encrypt(key: bytes, plaintext: bytes, *, aad: bytes = b"") -> tuple[bytes, bytes]:
    """Encrypt → (nonce, ciphertext). Nonce is fresh CSPRNG per call."""
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, aad or None)
    return nonce, ciphertext


def decrypt(key: bytes, nonce: bytes, ciphertext: bytes, *, aad: bytes = b"") -> bytes:
    """Decrypt; raises `cryptography.exceptions.InvalidTag` on tamper —
    callers map that to a task failure, never to raw error propagation."""
    return AESGCM(key).decrypt(nonce, ciphertext, aad or None)
