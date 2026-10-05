"""M7 unit tests — §13.6 content parts + §13.9 task payload validation."""

from __future__ import annotations

import pytest

from localmesh_agent.core.errors import MeshError
from localmesh_agent.core.policy import (
    validate_chat_payload,
    validate_task_payload,
)

IMG = "data:image/png;base64,iVBORw0KGgo="


def test_string_content_still_valid() -> None:
    payload = {"model": "a::b", "messages": [{"role": "user", "content": "Hi"}]}
    assert validate_chat_payload(payload) == payload


def test_image_part_accepted() -> None:
    payload = {
        "model": "a::b",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is this?"},
                    {"type": "image_url", "image_url": {"url": IMG}},
                ],
            }
        ],
    }
    assert validate_chat_payload(payload) == payload


def test_https_image_url_accepted_cleartext_rejected() -> None:
    ok = {
        "model": "a::b",
        "messages": [
            {
                "role": "user",
                "content": [{"type": "image_url", "image_url": {"url": "https://x/y.png"}}],
            }
        ],
    }
    validate_chat_payload(ok)
    bad = {
        "model": "a::b",
        "messages": [
            {
                "role": "user",
                "content": [{"type": "image_url", "image_url": {"url": "http://x/y.png"}}],
            }
        ],
    }
    with pytest.raises(MeshError):  # §17.9: no cleartext, even in part URLs
        validate_chat_payload(bad)


def test_unknown_part_type_rejected() -> None:
    payload = {
        "model": "a::b",
        "messages": [{"role": "user", "content": [{"type": "video_url"}]}],
    }
    with pytest.raises(MeshError) as excinfo:
        validate_chat_payload(payload)
    assert "allowed_types" in excinfo.value.details


def test_malformed_audio_part_rejected() -> None:
    payload = {
        "model": "a::b",
        "messages": [
            {"role": "user", "content": [{"type": "input_audio", "input_audio": {"data": ""}}]}
        ],
    }
    with pytest.raises(MeshError):
        validate_chat_payload(payload)
    ok = {
        "model": "a::b",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "input_audio", "input_audio": {"data": "AAAA", "format": "wav"}}
                ],
            }
        ],
    }
    validate_chat_payload(ok)  # shape accepted; routing is gated later (501)


def test_unknown_message_field_rejected() -> None:
    payload = {"model": "a::b", "messages": [{"role": "user", "content": "Hi", "name": "x"}]}
    with pytest.raises(MeshError) as excinfo:
        validate_chat_payload(payload)
    assert excinfo.value.details["unknown_fields"] == ["name"]


# -- §13.9 task payloads -------------------------------------------------------


def base_chat_task() -> dict:
    return {
        "type": "chat",
        "input": {"model": "a::b", "messages": [{"role": "user", "content": "Hi"}]},
    }


def test_task_chat_valid() -> None:
    task_type, task_input, options = validate_task_payload(base_chat_task())
    assert task_type == "chat"
    assert task_input["model"] == "a::b"
    assert options == {}


def test_task_unknown_top_level_rejected() -> None:
    payload = {**base_chat_task(), "priority": 3}
    with pytest.raises(MeshError) as excinfo:
        validate_task_payload(payload)
    assert excinfo.value.details["unknown_fields"] == ["priority"]


def test_task_unknown_type_rejected() -> None:
    with pytest.raises(MeshError):
        validate_task_payload({"type": "video", "input": {}})


def test_task_input_allow_list_per_type() -> None:
    payload = {"type": "transcribe", "input": {"audio": "note.wav", "wrong": 1}}
    with pytest.raises(MeshError) as excinfo:
        validate_task_payload(payload)
    assert excinfo.value.details["unknown_fields"] == ["wrong"]
    ok_type, ok_input, _ = validate_task_payload(
        {"type": "transcribe", "input": {"audio": "note.wav", "language": "en"}}
    )
    assert ok_type == "transcribe" and ok_input["audio"] == "note.wav"


def test_vision_task_requires_image_part() -> None:
    payload = {
        "type": "vision",
        "input": {
            "model": "a::b",
            "messages": [{"role": "user", "content": "no image here"}],
        },
    }
    with pytest.raises(MeshError):
        validate_task_payload(payload)
    payload["input"]["messages"][0]["content"] = [{"type": "image_url", "image_url": {"url": IMG}}]
    task_type, _task_input, _options = validate_task_payload(payload)
    assert task_type == "vision"


def test_transcribe_requires_audio_attachment() -> None:
    with pytest.raises(MeshError):
        validate_task_payload({"type": "transcribe", "input": {}})


def test_doc_qa_requires_question_and_model() -> None:
    with pytest.raises(MeshError):
        validate_task_payload({"type": "doc_qa", "input": {"question": "q"}})
    task_type, task_input, options = validate_task_payload(
        {
            "type": "doc_qa",
            "input": {"question": "What is it?", "model": "a::b"},
            "options": {"source_ids": ["doc_1"]},
        }
    )
    assert task_type == "doc_qa"
    assert options["source_ids"] == ["doc_1"]


def test_stream_param_in_chat_task_is_rejected_as_unknown() -> None:
    payload = {
        "type": "chat",
        "input": {"model": "a::b", "messages": [{"role": "user", "content": "Hi"}], "stream": True},
    }
    with pytest.raises(MeshError):
        validate_task_payload(payload)  # tasks are server-side, non-streamed
