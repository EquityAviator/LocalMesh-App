"""Param allow-list and limits (§10.4).

Implements §13.6 (chat parameter allow-list v1) and the request-shape limits
of §13.8. "Reject, don't truncate silently" (§10.4 Policy rule): anything
outside the allow-list is a 422 `INVALID_REQUEST` with
`details.unknown_fields` (§13.6), size limits map per §13.8.
"""

from __future__ import annotations

from typing import Any, Literal

from localmesh_agent.core.errors import MeshError

# §13.6 — the ONLY chat parameters accepted in v1. Anything else -> 422 with
# details.unknown_fields. Image/audio parts, tools, response_format arrive
# with their milestones (M7/M8).
ALLOWED_CHAT_PARAMS: frozenset[str] = frozenset(
    {
        "model",
        "messages",
        "stream",
        "temperature",
        "top_p",
        "max_tokens",
        "stop",
        "presence_penalty",
        "frequency_penalty",
        "seed",
        "x_mesh",
    }
)

_ALLOWED_ROLES = ("system", "user", "assistant")  # §13.6
_MAX_MESSAGES = 200  # §13.8

# §13.8 limits enforced here (defaults from Appendix E; the body-size limit
# itself is enforced by the app middleware before parsing).
MAX_STREAM_SECONDS = 900


def validate_chat_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a raw chat JSON body against §13.6/§13.8.

    Returns the validated fields; raises `MeshError("INVALID_REQUEST", ...)`
    on any violation. Content is never included in error messages.
    """
    if not isinstance(payload, dict):
        raise MeshError("INVALID_REQUEST", "Request body must be a JSON object.")

    unknown = sorted(set(payload) - ALLOWED_CHAT_PARAMS)
    if unknown:
        raise MeshError(
            "INVALID_REQUEST",
            "Request contains parameters outside the v1 allow-list (§13.6).",
            details={"unknown_fields": unknown},
        )

    model = payload.get("model")
    if not isinstance(model, str) or not model:
        raise MeshError("INVALID_REQUEST", "'model' is required.")

    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise MeshError("INVALID_REQUEST", "'messages' must be a non-empty list.")
    if len(messages) > _MAX_MESSAGES:
        raise MeshError("INVALID_REQUEST", "Too many messages.", details={"limit": _MAX_MESSAGES})
    for message in messages:
        if not isinstance(message, dict):
            raise MeshError("INVALID_REQUEST", "Each message must be an object.")
        role = message.get("role")
        if role not in _ALLOWED_ROLES:
            raise MeshError("INVALID_REQUEST", f"message role must be one of {_ALLOWED_ROLES}.")
        content = message.get("content")
        # §13.6: string content in v1 (no image/audio parts before M7).
        if not isinstance(content, str):
            raise MeshError("INVALID_REQUEST", "message content must be a string in v1 (§13.6).")

    stream = payload.get("stream", True)
    if not isinstance(stream, bool):
        raise MeshError("INVALID_REQUEST", "'stream' must be a boolean.")

    _validate_number(payload, "temperature", 0.0, 2.0)
    _validate_number(payload, "top_p", 0.0, 1.0)
    _validate_number(payload, "presence_penalty", -2.0, 2.0)
    _validate_number(payload, "frequency_penalty", -2.0, 2.0)

    max_tokens = payload.get("max_tokens")
    if max_tokens is not None and (not isinstance(max_tokens, int) or max_tokens <= 0):
        raise MeshError("INVALID_REQUEST", "'max_tokens' must be a positive integer.")

    seed = payload.get("seed")
    if seed is not None and not isinstance(seed, int):
        raise MeshError("INVALID_REQUEST", "'seed' must be an integer.")

    stop = payload.get("stop")
    if stop is not None:
        if isinstance(stop, str):
            stop_ok = len(stop) > 0
        elif isinstance(stop, list) and stop:
            stop_ok = all(isinstance(item, str) and item for item in stop)
        else:
            stop_ok = False
        if not stop_ok:
            raise MeshError("INVALID_REQUEST", "'stop' must be a non-empty string or string list.")

    x_mesh = payload.get("x_mesh")
    if x_mesh is not None:
        if not isinstance(x_mesh, dict):
            raise MeshError("INVALID_REQUEST", "'x_mesh' must be an object.")
        unknown_x = sorted(set(x_mesh) - {"client_request_id"})
        if unknown_x:
            raise MeshError(
                "INVALID_REQUEST",
                "x_mesh contains unknown fields.",
                details={"unknown_fields": unknown_x},
            )
        client_request_id = x_mesh.get("client_request_id")
        if not isinstance(client_request_id, str) or not client_request_id:
            raise MeshError("INVALID_REQUEST", "x_mesh.client_request_id must be a string.")

    return payload


def validate_model_ref_payload(payload: dict[str, Any]) -> str:
    """Validate an API-MODEL-02/03 `POST /models/load|unload` body (§13.2).

    The contract body is exactly `{ "mesh_model_id": "lmstudio::…" }`; any
    other field is outside the v1 allow-list. Returns the mesh_model_id;
    raises `MeshError("INVALID_REQUEST", ...)` on violation (§13.4 envelope).
    """
    if not isinstance(payload, dict):
        raise MeshError("INVALID_REQUEST", "Request body must be a JSON object.")
    unknown = sorted(set(payload) - {"mesh_model_id"})
    if unknown:
        raise MeshError(
            "INVALID_REQUEST",
            "Request contains parameters outside the v1 allow-list (§13.2).",
            details={"unknown_fields": unknown},
        )
    mesh_model_id = payload.get("mesh_model_id")
    if not isinstance(mesh_model_id, str) or not mesh_model_id:
        raise MeshError("INVALID_REQUEST", "'mesh_model_id' is required.")
    return mesh_model_id


def _validate_number(payload: dict[str, Any], key: str, low: float, high: float) -> None:
    value = payload.get(key)
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MeshError("INVALID_REQUEST", f"'{key}' must be a number.")
    if not low <= float(value) <= high:
        raise MeshError("INVALID_REQUEST", f"'{key}' out of range [{low}, {high}].")


def status_of(payload: dict[str, Any]) -> Literal["ok"] | None:  # pragma: no cover
    """Reserved (unused); keeps the module importable without side effects."""
    return None
