"""Unit tests — observability.metrics (§20.1 registry semantics + render)."""

from __future__ import annotations

import pytest

from localmesh_agent.observability.metrics import (
    CANCEL_BUCKETS_MS,
    TTFT_BUCKETS_MS,
    MetricsRegistry,
)


class TestCounterSemantics:
    def test_inc_accumulates_per_label_set(self) -> None:
        registry = MetricsRegistry()
        registry.inc("auth_failures_total")
        registry.inc("auth_failures_total")
        registry.inc("requests_total", labels={"status": "ok", "backend": "lmstudio"})
        registry.inc("requests_total", labels={"status": "ok", "backend": "lmstudio"}, value=3)
        snapshot = registry.snapshot()
        assert snapshot["counters"]["auth_failures_total"][""] == 2.0
        assert snapshot["counters"]["requests_total"]['{backend="lmstudio",status="ok"}'] == 4.0

    def test_inc_fractional_values_allowed(self) -> None:
        registry = MetricsRegistry()
        registry.inc("tokens_out_total", labels={"backend": "ollama"}, value=0.5)
        assert registry.snapshot()["counters"]["tokens_out_total"]['{backend="ollama"}'] == 0.5

    def test_inc_unknown_name_raises(self) -> None:
        registry = MetricsRegistry()
        with pytest.raises(ValueError, match="not a counter"):
            registry.inc("not_a_metric")

    def test_inc_on_gauge_raises(self) -> None:
        registry = MetricsRegistry()
        with pytest.raises(ValueError, match="not a counter"):
            registry.inc("queue_depth")


class TestGaugeSemantics:
    def test_set_gauge_overwrites(self) -> None:
        registry = MetricsRegistry()
        registry.set_gauge("tokens_per_sec", 12.5)
        registry.set_gauge("tokens_per_sec", 9.75)
        assert registry.snapshot()["gauges"]["tokens_per_sec"][""] == 9.75

    def test_backend_up_per_label(self) -> None:
        registry = MetricsRegistry()
        registry.set_gauge("backend_up", 1.0, labels={"backend": "lmstudio"})
        registry.set_gauge("backend_up", 0.0, labels={"backend": "ollama"})
        gauges = registry.snapshot()["gauges"]["backend_up"]
        assert gauges['{backend="lmstudio"}'] == 1.0
        assert gauges['{backend="ollama"}'] == 0.0


class TestHistogramSemantics:
    def test_observe_lands_in_buckets_and_inf(self) -> None:
        registry = MetricsRegistry()
        registry.observe("ttft_ms", 40)  # crosses every bound ≥ 50
        registry.observe("ttft_ms", 2500)  # crosses every bound ≥ 5000
        rendered = registry.render_prometheus()
        assert "# TYPE ttft_ms histogram" in rendered
        assert 'ttft_ms_bucket{le="50"} 1' in rendered
        assert 'ttft_ms_bucket{le="5000"} 2' in rendered
        assert 'ttft_ms_bucket{le="+Inf"} 2' in rendered
        assert "ttft_ms_count 2" in rendered

    def test_observe_sum_accumulates(self) -> None:
        registry = MetricsRegistry()
        registry.observe("cancel_latency_ms", 10)
        registry.observe("cancel_latency_ms", 20)
        assert "cancel_latency_ms_sum 30" in registry.render_prometheus()

    def test_bucket_constants_cover_19_1_and_13_7_bands(self) -> None:
        # §19.1 warm TTFT budget 200ms and §13.7 abort ≤ 1 s must be resolvable.
        assert 200.0 in TTFT_BUCKETS_MS
        assert 1000.0 in CANCEL_BUCKETS_MS

    def test_observe_unknown_name_raises(self) -> None:
        registry = MetricsRegistry()
        with pytest.raises(ValueError, match="not a histogram"):
            registry.observe("tokens_out_total", 5)


class TestRender:
    def test_label_escaping(self) -> None:
        registry = MetricsRegistry()
        registry.set_gauge("backend_up", 1.0, labels={"backend": 'weird"\\name'})
        rendered = registry.render_prometheus()
        assert 'backend="weird\\"\\\\name"' in rendered

    def test_labelless_empty_families_render_zero_series(self) -> None:
        registry = MetricsRegistry()
        rendered = registry.render_prometheus()
        for family in (
            "tokens_per_sec",
            "queue_depth",
            "active_generations",
            "auth_failures_total",
            "pairing_attempts_total",
        ):
            assert f"\n{family} 0" in rendered

    def test_labeled_family_absent_until_observed(self) -> None:
        registry = MetricsRegistry()
        assert "requests_total" not in registry.render_prometheus().replace(
            "# HELP requests_total", ""
        ).replace("# TYPE requests_total counter", "")
        # HELP/TYPE headers appear; no zero data series for labeled families.
        assert not any(
            line.startswith("requests_total{") or line.startswith("requests_total ")
            for line in registry.render_prometheus().splitlines()
        )

    def test_all_ten_20_1_families_declared(self) -> None:
        rendered = MetricsRegistry().render_prometheus()
        for family in (
            "requests_total",
            "ttft_ms",
            "tokens_out_total",
            "tokens_per_sec",
            "queue_depth",
            "active_generations",
            "backend_up",
            "auth_failures_total",
            "pairing_attempts_total",
            "cancel_latency_ms",
        ):
            assert f"# HELP {family} " in rendered


class TestPullGauges:
    def test_refresh_pull_gauges_reads_scheduler_and_registry(self) -> None:
        class FakeScheduler:
            def queue_stats(self) -> dict[str, int]:
                return {"active": 2, "queued": 5, "max_queued": 8}

        class FakeRegistry:
            def snapshot(self) -> dict[str, object]:
                return {
                    "backends": [
                        {"id": "lmstudio", "status": "up"},
                        {"id": "ollama", "status": "down"},
                    ]
                }

        registry = MetricsRegistry()
        registry.refresh_pull_gauges(scheduler=FakeScheduler(), registry=FakeRegistry())
        gauges = registry.snapshot()["gauges"]
        assert gauges["queue_depth"][""] == 5.0
        assert gauges["active_generations"][""] == 2.0
        assert gauges["backend_up"]['{backend="lmstudio"}'] == 1.0
        assert gauges["backend_up"]['{backend="ollama"}'] == 0.0

    def test_refresh_degrades_to_stale_on_probe_crash(self) -> None:
        class ExplodingScheduler:
            def queue_stats(self) -> dict[str, int]:
                raise RuntimeError("boom")

        registry = MetricsRegistry()
        registry.set_gauge("queue_depth", 3.0)
        registry.refresh_pull_gauges(scheduler=ExplodingScheduler())  # must not raise
        assert registry.snapshot()["gauges"]["queue_depth"][""] == 3.0
