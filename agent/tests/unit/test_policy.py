"""WP-06 unit tests — policy allow-list (§13.6, §13.8; FR-CHAT-05)."""

import pytest

from localmesh_agent.core.errors import MeshError
from localmesh_agent.core.policy import validate_chat_payload


def test_valid_payload_passes() -> None:
    payload = {
        "model": "lmstudio::m",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
        "temperature": 0.7,
        "max_tokens": 1024,
        "x_mesh": {"client_request_id": "0d184df2-0000-4000-8000-000000000000"},
    }
    assert validate_chat_payload(payload) == payload


def test_unknown_param_rejected_422() -> None:
    """FR-CHAT-05 AC: unknown params rejected 422 with details.unknown_fields."""
    with pytest.raises(MeshError) as excinfo:
        validate_chat_payload(
            {
                "model": "m",
                "messages": [{"role": "user", "content": "hi"}],
                "logprobs": True,
                "tools": [],
            }
        )
    error = excinfo.value
    assert error.code == "INVALID_REQUEST"
    assert error.http_status == 422
    assert error.details is not None
    assert sorted(error.details["unknown_fields"]) == ["logprobs", "tools"]


def test_unknown_role_rejected() -> None:
    with pytest.raises(MeshError):
        validate_chat_payload({"model": "m", "messages": [{"role": "tool", "content": "x"}]})


def test_non_string_content_rejected_v1() -> None:
    """§13.6: string content in v1 — image/audio parts arrive at M7."""
    with pytest.raises(MeshError):
        validate_chat_payload(
            {
                "model": "m",
                "messages": [{"role": "user", "content": [{"type": "text", "text": "x"}]}],
            }
        )


def test_message_count_limit_200() -> None:
    messages = [{"role": "user", "content": "x"}] * 201
    with pytest.raises(MeshError) as excinfo:
        validate_chat_payload({"model": "m", "messages": messages})
    assert excinfo.value.details == {"limit": 200}


def test_numeric_ranges() -> None:
    with pytest.raises(MeshError):
        validate_chat_payload(
            {"model": "m", "messages": [{"role": "user", "content": "x"}], "temperature": 5.0}
        )
    with pytest.raises(MeshError):
        validate_chat_payload(
            {"model": "m", "messages": [{"role": "user", "content": "x"}], "max_tokens": 0}
        )


def test_x_mesh_unknown_field_rejected() -> None:
    with pytest.raises(MeshError) as excinfo:
        validate_chat_payload(
            {
                "model": "m",
                "messages": [{"role": "user", "content": "x"}],
                "x_mesh": {"client_request_id": "x", "history": []},
            }
        )
    assert excinfo.value.details is not None
    assert excinfo.value.details["unknown_fields"] == ["history"]


def test_missing_model_rejected() -> None:
    with pytest.raises(MeshError):
        validate_chat_payload({"messages": [{"role": "user", "content": "x"}]})
