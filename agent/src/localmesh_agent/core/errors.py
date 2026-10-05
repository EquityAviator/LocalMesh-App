"""MeshError codes (Appendix D) (§10.1).

One error type carries the Appendix D code; the HTTP mapping and retryable
flag come from the normative Appendix D table. `message` MUST be human-readable
and MUST NOT contain Content or raw backend bodies (§13.4).
"""

from __future__ import annotations

from typing import Any

# Appendix D — Code -> (HTTP status, retryable). Normative mapping.
MESH_ERROR_CODES: dict[str, tuple[int, bool]] = {
    "AUTH_REQUIRED": (401, False),
    "AUTH_FAILED": (401, False),
    "TOKEN_EXPIRED": (401, True),
    "DEVICE_REVOKED": (403, False),
    "FORBIDDEN_SCOPE": (403, False),
    "PAIRING_CLOSED": (409, False),
    "PAIRING_INVALID": (403, False),
    "PAIRING_EXPIRED": (410, False),
    "PAIRING_LOCKED": (429, False),
    "INVALID_REQUEST": (422, False),
    "PAYLOAD_TOO_LARGE": (413, False),
    "MODEL_NOT_FOUND": (404, False),
    "MODEL_NOT_LOADED": (409, True),
    "UNSUPPORTED_CAPABILITY": (501, False),
    "QUEUE_FULL": (429, True),
    "RATE_LIMITED": (429, True),
    "BACKEND_UNAVAILABLE": (503, True),
    "BACKEND_TIMEOUT": (504, True),
    # Appendix D marks BACKEND_PROTOCOL and INTERNAL retryable="maybe"; the
    # envelope needs a boolean, so the conservative value (False) is used —
    # the App may still offer a manual retry.
    "BACKEND_PROTOCOL": (502, False),
    "DEADLINE_EXCEEDED": (504, False),
    "CANCELLED": (0, False),  # SSE-only code; never an HTTP response
    "INTERNAL": (500, False),
}


class MeshError(Exception):
    """Agent error carrying an Appendix D code (§13.4 envelope on the wire).

    `status_override` exists for the one case where §13.2 fixes an HTTP
    status that the Appendix D table has no code for: API-REQ-01's 404 for
    unknown/finished requests (the envelope still carries an Appendix D
    code). Any new use must be documented as a [DESIGN] gap resolution.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        status_override: int | None = None,
    ) -> None:
        if code not in MESH_ERROR_CODES:
            raise ValueError(f"unknown MeshError code: {code!r} (Appendix D)")
        super().__init__(message)
        self.code = code
        self.message = message  # never Content, never raw backend bodies (§13.4)
        self.details = details
        self._status_override = status_override

    @property
    def http_status(self) -> int:
        if self._status_override is not None:
            return self._status_override
        return MESH_ERROR_CODES[self.code][0]

    @property
    def retryable(self) -> bool:
        return MESH_ERROR_CODES[self.code][1]

    def is_retryable_sse(self) -> bool:
        """SSE mesh.error payload uses the same retryable flag (§13.4)."""
        return self.retryable
