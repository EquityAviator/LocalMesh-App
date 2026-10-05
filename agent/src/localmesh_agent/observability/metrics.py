"""Agent metrics (§20.1) — in-process, Metadata only.

Implements the ten §20.1 metric families:

    requests_total{status,backend} · ttft_ms histogram · tokens_out_total ·
    tokens_per_sec gauge (rolling) · queue_depth · active_generations ·
    backend_up{backend} · auth_failures_total · pairing_attempts_total ·
    cancel_latency_ms.

Exposure (§20.1): the optional Prometheus text endpoint lives on the
**loopback admin listener only** — served as `GET /admin/metrics` behind the
ADR-014 guard (admin token + Host check). The route path is [DESIGN]: §20.1
names the endpoint type, not a path. Metric names are §20.1-verbatim (no
vendor prefix) so spec traceability stays literal [DESIGN].

Push vs pull (single source of truth per family):
- **push at the event**: `requests_total`, `tokens_out_total`, `ttft_ms`,
  `tokens_per_sec` (last finished stream), `auth_failures_total`,
  `pairing_attempts_total`, `cancel_latency_ms` (scheduler).
- **pull at scrape**: `queue_depth` / `active_generations`
  (scheduler.queue_stats()) and `backend_up{backend}` (registry.snapshot()) —
  the scrape closure refreshes these gauges so the exposition always reflects
  live state instead of a stale push.

Thread-safety: instrumentation runs on the event loop and in worker threads
(scheduler releases, revoke fan-out); every mutating method takes a lock.
No Content ever reaches a metric: values are counts/durations/booleans, and
label values are agent-side identifiers (backend ids, status words) only
(§17.6 secret matrix, SEC-N3).
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from typing import Any

# §20.1 histograms [DESIGN] buckets (ms): TTFT spans sub-ms cache hits to
# multi-second cold loads (§19.1 warm budget 200 ms, stream start ≤ 500 ms —
# cold loads beyond the last bucket still land in +Inf so counts stay honest).
TTFT_BUCKETS_MS: tuple[float, ...] = (5, 10, 25, 50, 100, 200, 500, 1000, 2000, 5000, 10000)
# §13.7 abort ≤ 1 s: buckets resolve the compliance band.
CANCEL_BUCKETS_MS: tuple[float, ...] = (1, 5, 10, 25, 50, 100, 250, 500, 1000, 5000)

_HISTOGRAM_BUCKETS: dict[str, tuple[float, ...]] = {
    "ttft_ms": TTFT_BUCKETS_MS,
    "cancel_latency_ms": CANCEL_BUCKETS_MS,
}

# label sets per §20.1 (verbatim families; labels [DESIGN] where §20.1 lists
# them — requests_total{status,backend}, backend_up{backend} — and empty for
# the scalar families).
_SPEC: dict[str, dict[str, Any]] = {
    "requests_total": {
        "type": "counter",
        "labels": ("status", "backend"),
        "help": "Chat generations by terminal status (ok|error|cancelled) and backend.",
    },
    "ttft_ms": {"type": "histogram", "labels": (), "help": "Time to first token (ms)."},
    "tokens_out_total": {
        "type": "counter",
        "labels": ("backend",),
        "help": "Output tokens counted across finished generations.",
    },
    "tokens_per_sec": {
        "type": "gauge",
        "labels": (),
        "help": "Output tokens per second of the most recently finished stream.",
    },
    "queue_depth": {
        "type": "gauge",
        "labels": (),
        "help": "Generations waiting for a backend slot.",
    },
    "active_generations": {
        "type": "gauge",
        "labels": (),
        "help": "Generations currently running.",
    },
    "backend_up": {
        "type": "gauge",
        "labels": ("backend",),
        "help": "1 when the backend answered its last probe, else 0.",
    },
    "auth_failures_total": {
        "type": "counter",
        "labels": (),
        "help": "Rejected Device Token authentications (401 class).",
    },
    "pairing_attempts_total": {
        "type": "counter",
        "labels": (),
        "help": "Pairing claim attempts (API-PAIR-01), any outcome.",
    },
    "cancel_latency_ms": {
        "type": "histogram",
        "labels": (),
        "help": "Cancel request to job-finished latency (ms; §13.7 abort ≤ 1 s).",
    },
}

LabelKey = tuple[tuple[str, str], ...]


def _label_key(labels: Mapping[str, str] | None) -> LabelKey:
    return tuple(sorted((labels or {}).items()))


def _label_str(key: LabelKey) -> str:
    if not key:
        return ""
    inner = ",".join(
        '{}="{}"'.format(
            name,
            value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n"),
        )
        for name, value in key
    )
    return "{" + inner + "}"


class MetricsRegistry:
    """Thread-safe in-process §20.1 registry (push families)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, dict[LabelKey, float]] = {
            name: {} for name in _SPEC if _SPEC[name]["type"] == "counter"
        }
        self._gauges: dict[str, dict[LabelKey, float]] = {
            name: {} for name in _SPEC if _SPEC[name]["type"] == "gauge"
        }
        self._histograms: dict[str, dict[LabelKey, dict[str, Any]]] = {
            name: {} for name in _HISTOGRAM_BUCKETS
        }

    # -- push API (instrumentation) -------------------------------------------

    def inc(
        self, name: str, *, labels: Mapping[str, str] | None = None, value: float = 1.0
    ) -> None:
        """Increment a counter (unknown names are a programming error)."""
        if _SPEC.get(name, {}).get("type") != "counter":  # pragma: no cover - guarded by tests
            raise ValueError(f"not a counter: {name}")
        key = _label_key(labels)
        with self._lock:
            series = self._counters[name]
            series[key] = series.get(key, 0.0) + value

    def set_gauge(
        self, name: str, value: float, *, labels: Mapping[str, str] | None = None
    ) -> None:
        """Set a gauge to an absolute value."""
        if _SPEC.get(name, {}).get("type") != "gauge":  # pragma: no cover - guarded by tests
            raise ValueError(f"not a gauge: {name}")
        key = _label_key(labels)
        with self._lock:
            self._gauges[name][key] = value

    def observe(
        self, name: str, value_ms: float, *, labels: Mapping[str, str] | None = None
    ) -> None:
        """Record one histogram observation (ms)."""
        if name not in _HISTOGRAM_BUCKETS:  # pragma: no cover - guarded by tests
            raise ValueError(f"not a histogram: {name}")
        key = _label_key(labels)
        with self._lock:
            series = self._histograms[name]
            state = series.get(key)
            if state is None:
                state = {
                    "buckets": [0] * len(_HISTOGRAM_BUCKETS[name]),
                    "sum": 0.0,
                    "count": 0,
                }
                series[key] = state
            for index, bound in enumerate(_HISTOGRAM_BUCKETS[name]):
                if value_ms <= bound:
                    state["buckets"][index] += 1
            state["sum"] += value_ms
            state["count"] += 1

    # -- pull API (scrape-time gauges, §20.1 pull families) --------------------

    def refresh_pull_gauges(self, *, scheduler: Any = None, registry: Any = None) -> None:
        """Refresh queue_depth / active_generations / backend_up from live state.

        Called by the scrape closure immediately before rendering; failures
        degrade to stale values and never fail the scrape (a metrics glitch
        must not take the admin listener down).
        """
        if scheduler is not None:
            try:
                stats = scheduler.queue_stats()
                self.set_gauge("queue_depth", float(stats.get("queued", 0)))
                self.set_gauge("active_generations", float(stats.get("active", 0)))
            except Exception:  # noqa: BLE001, S110 - scrape must not fail (§20.1 optional)
                pass
        if registry is not None:
            try:
                backends = registry.snapshot().get("backends", [])
                if isinstance(backends, list):
                    for backend in backends:
                        if isinstance(backend, dict):
                            self.set_gauge(
                                "backend_up",
                                1.0 if backend.get("status") == "up" else 0.0,
                                labels={"backend": str(backend.get("id", "unknown"))},
                            )
            except Exception:  # noqa: BLE001, S110 - scrape must not fail
                pass

    # -- render ------------------------------------------------------------------

    def render_prometheus(self) -> str:
        """Prometheus text exposition (media type `text/plain; version=0.0.4`)."""
        lines: list[str] = []
        with self._lock:
            for name, spec in _SPEC.items():
                labels = spec["labels"]
                lines.append(f"# HELP {name} {spec['help']}")
                lines.append(f"# TYPE {name} {spec['type']}")
                if spec["type"] == "counter":
                    for key, value in sorted(self._counters[name].items()):
                        lines.append(f"{name}{_label_str(key)} {_format_value(value)}")
                elif spec["type"] == "gauge":
                    for key, value in sorted(self._gauges[name].items()):
                        lines.append(f"{name}{_label_str(key)} {_format_value(value)}")
                else:  # histogram
                    buckets = _HISTOGRAM_BUCKETS[name]
                    for key, state in sorted(self._histograms[name].items()):
                        for bound, count in zip(buckets, state["buckets"], strict=True):
                            le = _format_value(bound)
                            suffix = _label_str(key + (("le", le),)) if key else f'{{le="{le}"}}'
                            lines.append(f"{name}_bucket{suffix} {count}")
                        inf_suffix = _label_str(key + (("le", "+Inf"),)) if key else '{le="+Inf"}'
                        lines.append(f"{name}_bucket{inf_suffix} {state['count']}")
                        sum_labels = "" if not key else _label_str(key)
                        lines.append(f"{name}_sum{sum_labels} {_format_value(state['sum'])}")
                        lines.append(f"{name}_count{sum_labels} {state['count']}")
                # §20.1 families should always be present at scrape time: a
                # label-less counter/gauge with no observations renders one
                # zero series (histograms appear after their first observe).
                if not labels:
                    series = (
                        self._counters[name]
                        if spec["type"] == "counter"
                        else self._gauges[name]
                        if spec["type"] == "gauge"
                        else None
                    )
                    if series is not None and not series:
                        lines.append(f"{name} 0")
        return "\n".join(lines) + "\n"

    def snapshot(self) -> dict[str, Any]:
        """Structured view (tests, /admin/status summary, tooling)."""
        with self._lock:
            counters = {
                name: {_label_str(key): value for key, value in series.items()}
                for name, series in self._counters.items()
            }
            gauges = {
                name: {_label_str(key): value for key, value in series.items()}
                for name, series in self._gauges.items()
            }
            histograms = {
                name: {
                    _label_str(key): {
                        "count": state["count"],
                        "sum": round(state["sum"], 3),
                    }
                    for key, state in series.items()
                }
                for name, series in self._histograms.items()
            }
        return {"counters": counters, "gauges": gauges, "histograms": histograms}


def _format_value(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return repr(round(value, 6))
