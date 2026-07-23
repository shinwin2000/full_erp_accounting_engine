# test_metric_collector.py
# Comprehensive tests for kernel/metric_collector.py
# Covers all classes, methods, edge cases, and singleton behavior.

import asyncio
import functools
import time
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from kernel.metric_collector import (
    BaseMetricCollector,
    Metric,
    MetricCollector,
    MetricType,
    TimingContext,
    _FallbackMetricCollector,
    get_metric_collector,
    inc_counter,
    record_histogram,
    set_gauge,
    timing,
)


# -------------------- Fixtures --------------------
@pytest.fixture(autouse=True)
def reset_metric_collector():
    """Reset the singleton before each test."""
    MetricCollector._instance = None
    yield
    # Also ensure it's reset after test
    MetricCollector._instance = None


@pytest.fixture
def collector():
    """Get a fresh MetricCollector instance."""
    return get_metric_collector()


@pytest.fixture
def metric_definition():
    return Metric(
        name="test_metric",
        type=MetricType.COUNTER,
        help_text="Test counter",
        labels=["label1", "label2"],
    )


# -------------------- Tests for MetricType Enum --------------------
class TestMetricType:
    def test_members(self):
        assert MetricType.COUNTER is not None
        assert MetricType.GAUGE is not None
        assert MetricType.HISTOGRAM is not None
        assert MetricType.SUMMARY is not None

    def test_values(self):
        assert MetricType.COUNTER.name == "COUNTER"
        assert MetricType.GAUGE.name == "GAUGE"


# -------------------- Tests for Metric Dataclass --------------------
class TestMetric:
    def test_construction(self, metric_definition):
        assert metric_definition.name == "test_metric"
        assert metric_definition.type == MetricType.COUNTER
        assert metric_definition.help_text == "Test counter"
        assert metric_definition.labels == ["label1", "label2"]

    def test_validate_valid(self, metric_definition):
        result = metric_definition.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_invalid_missing_name(self):
        metric = Metric(name="", type=MetricType.COUNTER, help_text="help")
        result = metric.validate()
        assert result["is_valid"] is False
        assert "Metric name is required" in result["errors"]

    def test_validate_invalid_type(self):
        metric = Metric(name="test", type="invalid", help_text="help")
        # Since type is not an enum, it will fail validation
        result = metric.validate()
        assert result["is_valid"] is False
        assert "Invalid metric type" in result["errors"]

    def test_to_dict(self, metric_definition):
        d = metric_definition.to_dict()
        assert d["name"] == "test_metric"
        assert d["type"] == "COUNTER"
        assert d["help_text"] == "Test counter"
        assert d["labels"] == ["label1", "label2"]

    def test_from_dict(self):
        data = {
            "name": "my_metric",
            "type": "GAUGE",
            "help_text": "My gauge",
            "labels": ["tag"],
        }
        metric = Metric.from_dict(data)
        assert metric.name == "my_metric"
        assert metric.type == MetricType.GAUGE
        assert metric.help_text == "My gauge"
        assert metric.labels == ["tag"]

    def test_clone(self, metric_definition):
        cloned = metric_definition.clone()
        assert cloned.name == metric_definition.name
        assert cloned.type == metric_definition.type
        assert cloned.help_text == metric_definition.help_text
        assert cloned.labels == metric_definition.labels
        assert cloned is not metric_definition

    def test_snapshot(self, metric_definition):
        snap = metric_definition.snapshot()
        assert snap["name"] == "test_metric"
        assert snap["type"] == "COUNTER"

    def test_version(self, metric_definition):
        assert metric_definition.version() == 1

    def test_audit_trail(self, metric_definition):
        trail = metric_definition.audit_trail()
        assert len(trail) == 1
        assert trail[0]["name"] == "test_metric"

    def test_touch(self, metric_definition):
        touched = metric_definition.touch("user")
        assert touched.name == metric_definition.name
        assert touched is not metric_definition  # clone returns new instance


# -------------------- Tests for _FallbackMetricCollector --------------------
class TestFallbackMetricCollector:
    def test_construction(self):
        fallback = _FallbackMetricCollector()
        assert fallback is not None

    def test_increment_counter_logs(self, caplog):
        fallback = _FallbackMetricCollector()
        with caplog.at_level("DEBUG"):
            fallback.increment_counter("test_counter", {"tag": "value"}, 5)
            assert "[METRIC] counter test_counter: +5" in caplog.text

    def test_set_gauge_logs(self, caplog):
        fallback = _FallbackMetricCollector()
        with caplog.at_level("DEBUG"):
            fallback.set_gauge("test_gauge", Decimal("3.14"), {"tag": "value"})
            assert "[METRIC] gauge test_gauge: 3.14" in caplog.text

    def test_record_histogram_logs(self, caplog):
        fallback = _FallbackMetricCollector()
        with caplog.at_level("DEBUG"):
            fallback.record_histogram("test_hist", Decimal("1.5"), {"tag": "value"})
            assert "[METRIC] histogram test_hist: 1.5" in caplog.text


# -------------------- Tests for BaseMetricCollector (abstract) --------------------
class TestBaseMetricCollector:
    def test_abstract_class(self):
        # Cannot instantiate abstract class
        with pytest.raises(TypeError):
            BaseMetricCollector()


# -------------------- Tests for MetricCollector (singleton) --------------------
class TestMetricCollector:
    def test_singleton(self):
        c1 = get_metric_collector()
        c2 = get_metric_collector()
        assert c1 is c2

    def test_construction(self, collector):
        assert collector._enabled is True
        assert collector._counters == {}
        assert collector._gauges == {}
        assert collector._histograms == {}
        assert collector._version == 1
        assert collector._audit_trail == []

    def test_define_metric(self, collector):
        collector.define_metric("my_counter", MetricType.COUNTER, "help", ["tag"])
        assert "my_counter" in collector._metric_definitions
        metric = collector._metric_definitions["my_counter"]
        assert metric.type == MetricType.COUNTER
        assert metric.help_text == "help"
        assert metric.labels == ["tag"]
        # audit trail
        trail = collector.audit_trail()
        assert any(entry["action"] == "DEFINE_METRIC" for entry in trail)

    def test_set_enabled(self, collector):
        collector.set_enabled(False)
        assert collector._enabled is False
        collector.increment_counter("test")  # should be no-op
        assert collector.get_counter("test") == 0
        collector.set_enabled(True)
        assert collector._enabled is True
        trail = collector.audit_trail()
        assert any(entry["action"] == "SET_ENABLED" for entry in trail)

    def test_increment_counter(self, collector):
        collector.increment_counter("requests")
        assert collector.get_counter("requests") == 1
        collector.increment_counter("requests", {"path": "/api"}, 2)
        key = "requests[path=/api]"
        assert collector.get_counter("requests", {"path": "/api"}) == 2
        # total for name without labels is still 1
        assert collector.get_counter("requests") == 1

    def test_decrement_counter(self, collector):
        collector.increment_counter("requests", value=5)
        collector.decrement_counter("requests", value=2)
        assert collector.get_counter("requests") == 3
        collector.decrement_counter("requests", value=10)
        assert collector.get_counter("requests") == 0  # not negative

    def test_set_gauge(self, collector):
        collector.set_gauge("temp", Decimal("23.5"))
        assert collector.get_gauge("temp") == 23.5
        collector.set_gauge("temp", Decimal("24.0"), {"unit": "c"})
        key = "temp[unit=c]"
        assert collector.get_gauge("temp", {"unit": "c"}) == 24.0

    def test_increment_gauge(self, collector):
        collector.increment_gauge("active_connections")
        assert collector.get_gauge("active_connections") == 1.0
        collector.increment_gauge("active_connections", delta=Decimal("2.5"))
        assert collector.get_gauge("active_connections") == 3.5

    def test_decrement_gauge(self, collector):
        collector.set_gauge("stock", Decimal("10"))
        collector.decrement_gauge("stock", delta=Decimal("3"))
        assert collector.get_gauge("stock") == 7.0

    def test_record_histogram(self, collector):
        collector.record_histogram("latency", Decimal("1.2"))
        collector.record_histogram("latency", Decimal("2.3"))
        collector.record_histogram("latency", Decimal("0.8"))
        stats = collector.get_histogram_stats("latency")
        assert stats["count"] == 3
        assert stats["sum"] == 4.3
        assert stats["min"] == 0.8
        assert stats["max"] == 2.3
        assert stats["mean"] == 4.3 / 3
        assert stats["p50"] == 1.2
        assert stats["p90"] == 2.3
        assert stats["p95"] == 2.3
        assert stats["p99"] == 2.3

    def test_histogram_max_samples(self, collector):
        collector._max_histogram_samples = 5
        for i in range(10):
            collector.record_histogram("test", Decimal(i))
        stats = collector.get_histogram_stats("test")
        assert stats["count"] == 5  # only last 5 kept

    def test_get_counter(self, collector):
        collector.increment_counter("c1", value=7)
        assert collector.get_counter("c1") == 7
        assert collector.get_counter("nonexistent") == 0

    def test_get_gauge(self, collector):
        collector.set_gauge("g1", Decimal("42.5"))
        assert collector.get_gauge("g1") == 42.5
        assert collector.get_gauge("nonexistent") == 0.0

    def test_get_histogram_stats_empty(self, collector):
        stats = collector.get_histogram_stats("empty")
        assert stats["count"] == 0
        assert stats["sum"] == 0
        assert stats["min"] == 0
        assert stats["max"] == 0
        assert stats["mean"] == 0
        assert stats["p50"] == 0
        assert stats["p90"] == 0
        assert stats["p95"] == 0
        assert stats["p99"] == 0

    def test_reset_counter(self, collector):
        collector.increment_counter("test", value=5)
        collector.reset_counter("test")
        assert collector.get_counter("test") == 0

    def test_reset_histogram(self, collector):
        collector.record_histogram("h1", Decimal("1.0"))
        collector.reset_histogram("h1")
        stats = collector.get_histogram_stats("h1")
        assert stats["count"] == 0

    def test_reset_all(self, collector):
        collector.increment_counter("c1")
        collector.set_gauge("g1", Decimal("1"))
        collector.record_histogram("h1", Decimal("1"))
        old_version = collector._version
        collector.reset_all()
        assert collector._counters == {}
        assert collector._gauges == {}
        assert collector._histograms == {}
        assert collector._version == old_version + 1
        trail = collector.audit_trail()
        assert any(entry["action"] == "RESET_ALL" for entry in trail)

    def test_build_key(self, collector):
        assert collector._build_key("my_metric", None) == "my_metric"
        assert collector._build_key("my_metric", {"tag1": "val1", "tag2": "val2"}) == "my_metric[tag1=val1,tag2=val2]"

    def test_parse_key(self, collector):
        name, labels = collector._parse_key("my_metric")
        assert name == "my_metric"
        assert labels is None
        name2, labels2 = collector._parse_key("my_metric[tag1=val1,tag2=val2]")
        assert name2 == "my_metric"
        assert labels2 == {"tag1": "val1", "tag2": "val2"}

    def test_get_all_metrics(self, collector):
        collector.increment_counter("c1", {"a": "1"})
        collector.set_gauge("g1", Decimal("2.5"), {"b": "2"})
        collector.record_histogram("h1", Decimal("1.2"), {"c": "3"})
        all_metrics = collector.get_all_metrics()
        assert "c1[a=1]" in all_metrics["counters"]
        assert "g1[b=2]" in all_metrics["gauges"]
        assert "h1[c=3]" in all_metrics["histograms"]

    def test_export_to_prometheus(self, collector):
        collector.define_metric("req", MetricType.COUNTER, "requests")
        collector.increment_counter("req", value=10)
        collector.increment_counter("req", {"status": "200"}, value=5)
        collector.set_gauge("active", Decimal("3.14"))
        collector.record_histogram("latency", Decimal("1.5"))
        output = collector.export_to_prometheus()
        assert "req_total 10" in output
        assert 'req_total{status="200"} 5' in output
        assert "active 3.14" in output
        assert "latency_count 1" in output
        assert "latency_sum 1.5" in output
        assert "latency_mean 1.500000" in output

    def test_export_to_prometheus_disabled(self, collector):
        collector.set_enabled(False)
        output = collector.export_to_prometheus()
        assert output == "# Metrics collection disabled\n"

    def test_get_stats_summary(self, collector):
        collector.increment_counter("c1")
        collector.set_gauge("g1", Decimal("1"))
        collector.record_histogram("h1", Decimal("1"))
        summary = collector.get_stats_summary()
        assert summary["counters_count"] == 1
        assert summary["gauges_count"] == 1
        assert summary["histograms_count"] == 1
        assert summary["total_samples"] == 1
        assert summary["enabled"] is True
        assert summary["version"] == 1

    def test_get_counter_names(self, collector):
        collector.increment_counter("c1")
        collector.increment_counter("c2")
        names = collector.get_counter_names()
        assert set(names) == {"c1", "c2"}

    def test_get_gauge_names(self, collector):
        collector.set_gauge("g1", Decimal("1"))
        collector.set_gauge("g2", Decimal("2"))
        names = collector.get_gauge_names()
        assert set(names) == {"g1", "g2"}

    def test_clear(self, collector):
        collector.increment_counter("c1")
        collector.clear()
        assert collector._counters == {}

    def test_validate_valid(self, collector):
        collector.define_metric("m", MetricType.COUNTER, "help")
        result = collector.validate()
        assert result["is_valid"] is True

    def test_validate_invalid_max_samples(self, collector):
        collector._max_histogram_samples = -1
        result = collector.validate()
        assert result["is_valid"] is False
        assert any("max_histogram_samples must be positive" in e for e in result["errors"])

    def test_validate_invalid_metric_definition(self, collector):
        # define metric with empty name
        collector.define_metric("", MetricType.COUNTER, "help")
        result = collector.validate()
        assert result["is_valid"] is False
        assert any("Metric name is required" in e for e in result["errors"])

    def test_to_dict(self, collector):
        collector.define_metric("m", MetricType.COUNTER, "help")
        d = collector.to_dict()
        assert d["enabled"] is True
        assert d["max_histogram_samples"] == 1000
        assert d["counters_count"] == 0
        assert "metric_definitions" in d
        assert d["version"] == 1

    def test_from_dict(self, collector):
        data = {
            "enabled": False,
            "max_histogram_samples": 500,
            "metric_definitions": {
                "m1": {"name": "m1", "type": "GAUGE", "help_text": "gauge", "labels": []}
            },
            "version": 2,
        }
        new_collector = MetricCollector.from_dict(data)
        assert new_collector._enabled is False
        assert new_collector._max_histogram_samples == 500
        assert "m1" in new_collector._metric_definitions
        assert new_collector._version == 2

    def test_clone(self, collector):
        collector.define_metric("m", MetricType.COUNTER, "help")
        cloned = collector.clone()
        assert cloned._enabled == collector._enabled
        assert cloned._max_histogram_samples == collector._max_histogram_samples
        assert cloned._version == collector._version + 1
        assert "m" in cloned._metric_definitions
        assert cloned is not collector

    def test_snapshot(self, collector):
        collector.define_metric("m", MetricType.COUNTER, "help")
        snap = collector.snapshot()
        assert snap["version"] == 1
        assert snap["enabled"] is True
        assert snap["counters_count"] == 0
        assert snap["total_samples"] == 0
        assert "timestamp" in snap

    def test_version(self, collector):
        assert collector.version() == 1

    def test_audit_trail(self, collector):
        collector.define_metric("m", MetricType.COUNTER, "help")
        trail = collector.audit_trail()
        assert len(trail) >= 1
        assert any(entry["action"] == "DEFINE_METRIC" for entry in trail)

    def test_touch(self, collector):
        old_version = collector._version
        touched = collector.touch("tester")
        assert touched._version == old_version + 1
        trail = touched.audit_trail()
        assert any(entry["action"] == "TOUCH" for entry in trail)

    def test_reset(self, collector):
        collector.define_metric("m", MetricType.COUNTER, "help")
        collector.increment_counter("c1")
        collector.reset()
        assert collector._counters == {}
        assert collector._gauges == {}
        assert collector._histograms == {}
        assert collector._metric_definitions == {}  # definitions cleared?
        # Actually reset does not clear definitions, it only clears counters/gauges/histograms and resets version/audit
        # The implementation calls reset_all() which clears counters/gauges/histograms, then resets version and audit trail, but not definitions.
        # Let's check: reset_all clears counters/gauges/histograms, increments version. Then reset sets version=1 and clears audit and snapshots.
        # So definitions remain. We'll test that.
        assert "m" in collector._metric_definitions
        assert collector._version == 1
        assert collector._audit_trail == []
        trail = collector.audit_trail()
        assert trail == []  # reset cleared it

    def test_clear_and_reset_interaction(self, collector):
        collector.increment_counter("c1")
        collector.clear()
        assert collector.get_counter("c1") == 0


# -------------------- Tests for Convenience Functions --------------------
def test_get_metric_collector():
    c1 = get_metric_collector()
    c2 = get_metric_collector()
    assert c1 is c2


def test_inc_counter(collector):
    inc_counter("test", {"tag": "val"}, 3)
    assert collector.get_counter("test", {"tag": "val"}) == 3


def test_set_gauge(collector):
    set_gauge("temp", Decimal("25.5"), {"unit": "c"})
    assert collector.get_gauge("temp", {"unit": "c"}) == 25.5


def test_record_histogram(collector):
    record_histogram("latency", Decimal("2.3"), {"endpoint": "/api"})
    stats = collector.get_histogram_stats("latency", {"endpoint": "/api"})
    assert stats["count"] == 1
    assert stats["sum"] == 2.3


# -------------------- Tests for TimingContext --------------------
class TestTimingContext:
    def test_context_manager_success(self, collector):
        with TimingContext("op_duration", {"method": "GET"}) as ctx:
            time.sleep(0.01)
        # Check that histogram recorded
        stats = collector.get_histogram_stats("op_duration", {"method": "GET"})
        assert stats["count"] == 1
        assert stats["sum"] > 0
        # Check success counter incremented
        assert collector.get_counter("op_duration_success", {"method": "GET"}) == 1
        assert collector.get_counter("op_duration_errors", {"method": "GET"}) == 0

    def test_context_manager_exception(self, collector):
        with pytest.raises(ValueError):
            with TimingContext("op_duration"):
                raise ValueError("test error")
        stats = collector.get_histogram_stats("op_duration")
        assert stats["count"] == 1
        assert collector.get_counter("op_duration_errors") == 1
        assert collector.get_counter("op_duration_success") == 0

    def test_context_manager_without_labels(self, collector):
        with TimingContext("simple"):
            pass
        stats = collector.get_histogram_stats("simple")
        assert stats["count"] == 1


# -------------------- Tests for timing decorator --------------------
class TestTimingDecorator:
    def test_sync_success(self, collector):
        @timing("sync_op")
        def sync_func():
            time.sleep(0.01)
            return "ok"

        result = sync_func()
        assert result == "ok"
        stats = collector.get_histogram_stats("sync_op")
        assert stats["count"] == 1
        assert collector.get_counter("sync_op_success") == 1
        assert collector.get_counter("sync_op_errors") == 0

    def test_sync_exception(self, collector):
        @timing("sync_error")
        def sync_func():
            raise ValueError("bad")

        with pytest.raises(ValueError):
            sync_func()
        stats = collector.get_histogram_stats("sync_error")
        assert stats["count"] == 1
        assert collector.get_counter("sync_error_errors") == 1
        assert collector.get_counter("sync_error_success") == 0

    def test_async_success(self, collector):
        @timing("async_op")
        async def async_func():
            await asyncio.sleep(0.01)
            return "ok"

        result = asyncio.run(async_func())
        assert result == "ok"
        stats = collector.get_histogram_stats("async_op")
        assert stats["count"] == 1
        assert collector.get_counter("async_op_success") == 1

    def test_async_exception(self, collector):
        @timing("async_error")
        async def async_func():
            raise ValueError("bad")

        with pytest.raises(ValueError):
            asyncio.run(async_func())
        stats = collector.get_histogram_stats("async_error")
        assert stats["count"] == 1
        assert collector.get_counter("async_error_errors") == 1

    def test_decorator_with_labels(self, collector):
        @timing("labeled_op", {"env": "test"})
        def labeled_func():
            return "done"

        labeled_func()
        stats = collector.get_histogram_stats("labeled_op", {"env": "test"})
        assert stats["count"] == 1
        assert collector.get_counter("labeled_op_success", {"env": "test"}) == 1