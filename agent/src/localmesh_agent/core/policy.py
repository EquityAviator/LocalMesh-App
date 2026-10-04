"""Param allow-list and limits (§10.4).

Implements §13.6 (chat parameter allow-list v1) and the request-shape limits
of §13.8. "Reject, don't truncate silently" (§10.4 Policy rule): anything
outside the allow-list is a 422 `INVALID_REQUEST` with
`details.unknown_fields` (§13.6), size limits map per §13.8.
"""

from __future__ import annotations

from typing import Any, Literal

from localmesh_agent.core.errors import MeshError

# §13.6 — the ONLY chat parameters accepted. M7 (§13.6: "Image/audio parts …
# arrive with their milestones (M7/M8)"): message content MAY be a list of
# OpenAI-style parts. `tools`/`response_format` stay outside until M8.
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
        "tools",  # M8 (FR-AGENT-RT): arrives with its milestone (§13.6)
    }
)

# M7 content part types (§13.6, FR-MM-01/02). Shape [DESIGN] follows the
# OpenAI conventions the Backends already speak (ADR-009).
ALLOWED_PART_TYPES: frozenset[str] = frozenset({"text", "image_url", "input_audio"})

# §13.9 — Task contract (shape fixed at the M0 stub).
ALLOWED_TASK_TOP_LEVEL: frozenset[str] = frozenset({"type", "input", "options"})
TASK_INPUT_FIELDS: dict[str, frozenset[str]] = {
    "chat": frozenset({"model", "messages", "temperature", "max_tokens"}),
    "vision": frozenset({"model", "messages", "temperature", "max_tokens"}),
    "transcribe": frozenset({"audio", "model", "language"}),
    "doc_qa": frozenset({"question", "model", "max_tokens"}),
}

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
        unknown_message_keys = sorted(set(message) - {"role", "content"})
        if unknown_message_keys:
            raise MeshError(
                "INVALID_REQUEST",
                "Message contains fields outside the v1 allow-list (§13.6).",
                details={"unknown_fields": unknown_message_keys},
            )
        content = message.get("content")
        # §13.6 (M7): string content OR an OpenAI-style part list. Parts carry
        # binary references by value; the 2 MiB body limit (§13.8) bounds them.
        if isinstance(content, str):
            continue
        if isinstance(content, list) and content:
            _validate_content_parts(content)
            continue
        raise MeshError(
            "INVALID_REQUEST",
            "message content must be a string or a non-empty list of content parts (§13.6).",
        )

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

    tools = payload.get("tools")
    if tools is not None:
        validate_tools_payload(tools)

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


MAX_TOOLS = 16  # [DESIGN] sanity bound (ADR-020)


def validate_tools_payload(tools: Any) -> list[dict[str, Any]]:
    """M8 (§13.6 "tools … arrive with M8"): OpenAI function-calling shape.

    `[{type: "function", function: {name, description?, parameters?}}]`.
    The allow-listed EXECUTABLE set is decided by ADR-020 (core.tools);
    this only validates the wire shape so Backends never see garbage.
    """
    if not isinstance(tools, list) or not tools:
        raise MeshError("INVALID_REQUEST", "'tools' must be a non-empty list.")
    if len(tools) > MAX_TOOLS:
        raise MeshError("INVALID_REQUEST", f"'tools' limited to {MAX_TOOLS} entries.")
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            raise MeshError(
                "INVALID_REQUEST",
                "Each tool must be {type: 'function', function: {...}} (§13.6).",
            )
        unknown_tool_keys = sorted(set(tool) - {"type", "function"})
        if unknown_tool_keys:
            raise MeshError(
                "INVALID_REQUEST",
                "Tool contains unknown fields.",
                details={"unknown_fields": unknown_tool_keys},
            )
        function = tool.get("function")
        if (
            not isinstance(function, dict)
            or not isinstance(function.get("name"), str)
            or not function["name"]
        ):
            raise MeshError("INVALID_REQUEST", "tool.function.name is required.")
        unknown_fn_keys = sorted(set(function) - {"name", "description", "parameters"})
        if unknown_fn_keys:
            raise MeshError(
                "INVALID_REQUEST",
                "tool.function contains unknown fields.",
                details={"unknown_fields": unknown_fn_keys},
            )
    return tools


def _validate_content_parts(parts: list[Any]) -> None:
    """Shape-check M7 content parts (§13.6; FR-MM-01/02).

    Capability gating happens AFTER model resolution in the API layer
    (UNSUPPORTED_CAPABILITY, 501); here we only enforce shape so the
    Backend never receives garbage.
    """
    for part in parts:
        if not isinstance(part, dict):
            raise MeshError("INVALID_REQUEST", "Content parts must be objects.")
        part_type = part.get("type")
        if part_type not in ALLOWED_PART_TYPES:
            raise MeshError(
                "INVALID_REQUEST",
                "Content part type outside the M7 allow-list (§13.6).",
                details={"allowed_types": sorted(ALLOWED_PART_TYPES)},
            )
        unknown_part_keys = sorted(set(part) - {"type", "text", "image_url", "input_audio"})
        if unknown_part_keys:
            raise MeshError(
                "INVALID_REQUEST",
                "Content part contains fields outside the M7 allow-list (§13.6).",
                details={"unknown_fields": unknown_part_keys},
            )
        if part_type == "text":
            if not isinstance(part.get("text"), str):
                raise MeshError("INVALID_REQUEST", "text part requires a string 'text'.")
        elif part_type == "image_url":
            image_url = part.get("image_url")
            url = image_url.get("url") if isinstance(image_url, dict) else None
            if not isinstance(url, str) or not url:
                raise MeshError(
                    "INVALID_REQUEST", "image_url part requires image_url.url (data: or https:)."
                )
            if not (url.startswith("data:image/") or url.startswith("https://")):
                raise MeshError(
                    "INVALID_REQUEST",
                    "image_url.url must be a data:image/* or https: URL (§17.9: no cleartext).",
                )
        else:  # input_audio
            audio = part.get("input_audio")
            if not isinstance(audio, dict):
                raise MeshError("INVALID_REQUEST", "input_audio part requires an object.")
            data = audio.get("data")
            audio_format = audio.get("format")
            if not isinstance(data, str) or not data:
                raise MeshError("INVALID_REQUEST", "input_audio requires base64 'data'.")
            if audio_format not in ("wav", "mp3"):
                raise MeshError("INVALID_REQUEST", "input_audio.format must be 'wav' or 'mp3'.")


def validate_task_payload(payload: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Validate `POST /tasks` (§13.9): `{type, input, options}`.

    Returns (type, input, options); raises `MeshError("INVALID_REQUEST")`
    with §13.4 `details.unknown_fields` semantics. `options` is a free-form
    object but unknown top-level keys are rejected; per-type input fields
    are allow-listed.
    """
    from localmesh_agent.config import TASK_TYPES

    if not isinstance(payload, dict):
        raise MeshError("INVALID_REQUEST", "Request body must be a JSON object.")
    unknown = sorted(set(payload) - ALLOWED_TASK_TOP_LEVEL)
    if unknown:
        raise MeshError(
            "INVALID_REQUEST",
            "Request contains parameters outside the §13.9 allow-list.",
            details={"unknown_fields": unknown},
        )
    task_type = payload.get("type")
    if task_type not in TASK_TYPES:
        raise MeshError(
            "INVALID_REQUEST",
            f"'type' must be one of {TASK_TYPES} (§13.9).",
        )
    task_input = payload.get("input")
    if not isinstance(task_input, dict):
        raise MeshError("INVALID_REQUEST", "'input' must be an object.")
    allowed_fields = TASK_INPUT_FIELDS[str(task_type)]
    unknown_input = sorted(set(task_input) - allowed_fields)
    if unknown_input:
        raise MeshError(
            "INVALID_REQUEST",
            "Task input contains fields outside the §13.9 allow-list.",
            details={"unknown_fields": unknown_input},
        )
    if task_type in ("chat", "vision"):
        inner = {
            "model": task_input.get("model"),
            "messages": task_input.get("messages"),
            "stream": False,
        }
        inner_payload = validate_chat_payload(inner)
        # chat/vision tasks run server-side, non-streamed by construction.
        if task_type == "vision":
            _require_vision_parts(task_input["messages"])
        task_input = {
            "model": inner_payload["model"],
            "messages": inner_payload["messages"],
            "temperature": inner_payload.get("temperature"),
            "max_tokens": inner_payload.get("max_tokens"),
        }
    elif task_type == "transcribe":
        audio = task_input.get("audio")
        if not isinstance(audio, str) or not audio:
            raise MeshError("INVALID_REQUEST", "'input.audio' must name an uploaded attachment.")
        model = task_input.get("model")
        if model is not None and (not isinstance(model, str) or not model):
            raise MeshError("INVALID_REQUEST", "'input.model' must be a string when present.")
        language = task_input.get("language")
        if language is not None and not isinstance(language, str):
            raise MeshError("INVALID_REQUEST", "'input.language' must be a string when present.")
    else:  # doc_qa
        question = task_input.get("question")
        if not isinstance(question, str) or not question.strip():
            raise MeshError("INVALID_REQUEST", "'input.question' is required for doc_qa.")
        model = task_input.get("model")
        if not isinstance(model, str) or not model:
            raise MeshError("INVALID_REQUEST", "'input.model' is required for doc_qa.")
    options = payload.get("options") or {}
    if not isinstance(options, dict):
        raise MeshError("INVALID_REQUEST", "'options' must be an object.")
    source_ids = options.get("source_ids")
    if source_ids is not None:
        if not isinstance(source_ids, list) or not all(isinstance(s, str) for s in source_ids):
            raise MeshError("INVALID_REQUEST", "options.source_ids must be a list of strings.")
    return str(task_type), task_input, options


def _require_vision_parts(messages: list[Any]) -> None:
    """A vision task must actually carry an image part (fail fast, §10.4)."""
    for message in messages:
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, list):
                if any(
                    isinstance(part, dict) and part.get("type") == "image_url" for part in content
                ):
                    return
    raise MeshError(
        "INVALID_REQUEST",
        "A vision task requires at least one image_url content part (FR-MM-01).",
    )


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
