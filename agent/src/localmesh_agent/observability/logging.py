"""Deny-by-default structured logging (§17.10; NFR-SEC-02).

Allow-list (verbatim from §17.10): `ts, level, event, request_id, device_id,
agent_id, backend_id, mesh_model_id, status, error_code, duration_ms, ttft_ms,
tokens_out, queue_depth, tier, component`. Any other key is dropped by the
formatter.

Rules implemented here:
- Only allow-listed keys are emitted; any other key is dropped.
- The log message is used ONLY as the `event` value and MUST be a short event
  code — never message text, prompts or completions (SEC-N3; §17.10 "Never
  log" list). Compliance is verified by the canary test (TC-SEC-01).
- JSON lines on stdout; an optional file sink (§17.10 canary test greps the
  data/log directory and all stdout).
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# §17.10 allow-list — the ONLY keys the formatter may emit.
ALLOWED_LOG_KEYS: frozenset[str] = frozenset(
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

_LOGGER_ROOT = "localmesh"

_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}


class AllowListJsonFormatter(logging.Formatter):
    """JSON formatter that emits allow-listed keys only (§17.10)."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "event": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in ALLOWED_LOG_KEYS and key not in entry:
                entry[key] = value
        return json.dumps(entry, separators=(",", ":"), ensure_ascii=False, default=str)


def configure_logging(level: str = "info", log_file: Path | None = None) -> None:
    """(Re)configure the `localmesh` logger tree: JSON allow-list lines only."""
    logger = logging.getLogger(_LOGGER_ROOT)
    logger.setLevel(_LEVELS.get(level.lower(), logging.INFO))
    logger.propagate = False
    for existing in list(logger.handlers):
        logger.removeHandler(existing)
        existing.close()
    formatter = AllowListJsonFormatter()
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    logger.addHandler(stdout_handler)
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)


class ComponentLogger(logging.LoggerAdapter):
    """Adapter that MERGES call-site `extra` with the adapter's `component`.

    The stdlib `LoggerAdapter.process` on Python 3.12 *replaces* the call-site
    `extra` with the adapter's own (`kwargs["extra"] = self.extra`), silently
    dropping call-site keys. We merge instead: adapter keys first, call-site
    keys win on conflicts.
    """

    def process(self, msg: str, kwargs: Any) -> tuple[str, Any]:
        merged: dict[str, Any] = dict(self.extra or {})
        merged.update(kwargs.get("extra") or {})
        kwargs["extra"] = merged
        return msg, kwargs


def get_logger(component: str) -> ComponentLogger:
    """Component logger that injects the allow-listed `component` key."""
    return ComponentLogger(
        logging.getLogger(f"{_LOGGER_ROOT}.{component}"), {"component": component}
    )
