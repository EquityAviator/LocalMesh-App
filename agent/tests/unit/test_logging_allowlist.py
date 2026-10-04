"""WP-04 unit tests — deny-by-default allow-list logging (§17.10, NFR-SEC-02).

The allow-list is binding: any key outside it is dropped by the formatter, and
a canary string passed in a disallowed position must never reach the output.
"""

import json
import logging

import pytest

from localmesh_agent.observability.logging import (
    ALLOWED_LOG_KEYS,
    AllowListJsonFormatter,
    configure_logging,
    get_logger,
)

CANARY = "CANARY-2f8a1c9b-prompt-secret"


def make_record(
    msg: str, extra: dict[str, object] | None = None, level: int = logging.INFO
) -> logging.LogRecord:
    record = logging.LogRecord(
        name="localmesh.test",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )
    if extra:
        # Mirror Logger.makeRecord: `extra` keys become record attributes.
        record.__dict__.update(extra)
    return record


def test_allow_list_matches_spec_verbatim() -> None:
    """The allow-list is §17.10 verbatim — no additions, no omissions."""
    assert ALLOWED_LOG_KEYS == frozenset(
        {
            "ts",
            "level",
            "event",
            "request_id",
            "device_id",
            "agent_id",
            "backend_id",
            "mesh_model_id",
            "status",
            "error_code",
            "duration_ms",
            "ttft_ms",
            "tokens_out",
            "queue_depth",
            "tier",
            "component",
        }
    )


def test_only_allow_listed_keys_emitted() -> None:
    record = make_record(
        "chat_started",
        extra={
            "request_id": "rq_1",
            "backend_id": "lmstudio",
            "mesh_model_id": "lmstudio::m",
            "duration_ms": 12,
            "disallowed_secret_field": CANARY,  # must be dropped (§17.10)
        },
    )
    entry = json.loads(AllowListJsonFormatter().format(record))
    assert entry["event"] == "chat_started"
    assert entry["request_id"] == "rq_1"
    assert entry["backend_id"] == "lmstudio"
    assert entry["duration_ms"] == 12
    assert "disallowed_secret_field" not in entry
    assert CANARY not in json.dumps(entry)
    assert set(entry) == {
        "ts",
        "level",
        "event",
        "request_id",
        "backend_id",
        "mesh_model_id",
        "duration_ms",
    }


def test_canary_in_disallowed_extra_dropped() -> None:
    """A canary passed under a non-allow-listed key never reaches output."""
    record = make_record("chat_started", extra={"prompt": CANARY, "messages": CANARY})
    line = AllowListJsonFormatter().format(record)
    assert CANARY not in line


def test_event_and_level_shape() -> None:
    line = json.loads(AllowListJsonFormatter().format(make_record("auth_ok", extra={})))
    assert line["level"] == "info"
    assert line["event"] == "auth_ok"
    assert line["ts"].endswith("Z")  # RFC3339 UTC


def test_component_injected_and_streamed(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("info")
    log = get_logger("api")
    log.info("chat_finished", extra={"tokens_out": 128})
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert '"component":"api"' in output
    assert '"event":"chat_finished"' in output
    assert '"tokens_out":128' in output


def test_configure_logging_respects_level() -> None:
    configure_logging("debug")
    assert logging.getLogger("localmesh").level == logging.DEBUG
    configure_logging("error")
    assert logging.getLogger("localmesh").level == logging.ERROR
    configure_logging("info")
