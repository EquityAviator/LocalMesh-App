"""In-process rate limiter (§10.1 ratelimit.py).

Implements the WP-08 slice of the §13.8 limits table:

| Item                        | Default                          | On exceed |
|-----------------------------|----------------------------------|-----------|
| `GET /info`                 | 30/min per source IP             | 429       |
| `POST /auth/challenge`      | 10/min per source IP AND per
|                             | device_id                        | 429       |
| Failed `pair/*` proofs      | 5 per PairingSession             | handled by
|                             |                                  | SM-PAIR   |

Sliding-window counter, keyed by arbitrary strings, thread-safe, in-memory
only (no persistence — restart clears limits, which is acceptable for a
per-process abuse guard [DESIGN]; the limits are abuse mitigation, not a
security boundary).
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field


@dataclass
class SlidingWindowLimiter:
    """allow(key, limit, window_s) — sliding-window counting (§13.8)."""

    _events: dict[str, deque[float]] = field(default_factory=lambda: defaultdict(deque), repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def allow(self, key: str, limit: int, window_s: float = 60.0) -> bool:
        """Record one hit for `key`; True when under `limit` per window."""
        now = time.monotonic()
        with self._lock:
            bucket = self._events[key]
            cutoff = now - window_s
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            return True

    def reset(self) -> None:
        """Test hook: clear all counters."""
        with self._lock:
            self._events.clear()
