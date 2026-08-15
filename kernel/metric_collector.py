#!/usr/bin/env python3
"""
Module: metric_collector.py
Layer: 4 - Kernel / Metric Collector
Responsibility: Mengumpulkan metrik kernel (jumlah command, latensi, error).
               Menyediakan antarmuka untuk mencatat metrik operasional kernel,
               seperti jumlah request, durasi eksekusi, error rate, dan status
               circuit breaker. Metrik dapat diekspor ke Prometheus.

               Semua nilai numerik di interface publik menggunakan Decimal
               untuk konsistensi dengan pola aplikasi, namun disimpan sebagai
               float untuk kompatibilitas dengan Prometheus.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import threading
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum, auto
from typing import Any

logger = logging.getLogger(__name__)


# === 1. CONSTANTS & ENUMS ===
class MetricType(Enum):
    COUNTER = auto()
    GAUGE = auto()
    HISTOGRAM = auto()
    SUMMARY = auto()


@dataclass
class Metric:
    """Definition of a metric."""

    name: str
    type: MetricType
    help_text: str
    labels: list[str] = field(default_factory=list)

    def validate(self) -> dict[str, Any]:
        errors = []
        if not self.name:
            errors.append("Metric name is required")
        if not isinstance(self.type, MetricType):
            errors.append("Invalid metric type")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type.name,
            "help_text": self.help_text,
            "labels": self.labels,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Metric:
        return cls(
            name=data["name"],
            type=MetricType[data["type"]],
            help_text=data.get("help_text", ""),
            labels=data.get("labels", []),
        )

    def clone(self) -> Metric:
        return Metric(
            name=self.name,
            type=self.type,
            help_text=self.help_text,
            labels=self.labels.copy(),
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type.name,
        }

    def version(self) -> int:
        return 1

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return [self.to_dict()]

    def touch(self, touched_by: str) -> Metric:
        return self.clone()


# === 2. FALLBACK METRIC COLLECTOR ===
class _FallbackMetricCollector:
    """Fallback metric collector when real collector is unavailable."""

    def increment_counter(
        self, name: str, tags: dict[str, str] | None = None, value: int = 1
    ) -> None:
        logger.debug(f"[METRIC] counter {name}: +{value}")

    def set_gauge(
        self, name: str, metric_value: Decimal, tags: dict[str, str] | None = None
    ) -> None:
        logger.debug(f"[METRIC] gauge {name}: {metric_value}")

    def record_histogram(
        self, name: str, metric_value: Decimal, tags: dict[str, str] | None = None
    ) -> None:
        logger.debug(f"[METRIC] histogram {name}: {metric_value}")


def _get_metric_collector():
    """
    Digunakan sebagai fallback di modul lain.
    Tidak melakukan import dari diri sendiri untuk menghindari circular import.
    """
    return _FallbackMetricCollector()


# ============================================================================
# BASE CLASS ABSTRAK (CONTRACT)
# ============================================================================
class BaseMetricCollector(ABC):
    """
    Base contract for Metric Collector.
    Semua method yang wajib diimplementasikan oleh subclass.
    """

    @abstractmethod
    def define_metric(
        self, name: str, metric_type: MetricType, help_text: str, labels: list[str] | None = None
    ) -> None:
        """Define a new metric."""
        pass

    @abstractmethod
    def increment_counter(
        self, name: str, labels: dict[str, str] | None = None, value: int = 1
    ) -> None:
        """Increment a counter metric."""
        pass

    @abstractmethod
    def set_gauge(
        self, name: str, metric_value: Decimal, labels: dict[str, str] | None = None
    ) -> None:
        """Set a gauge metric."""
        pass

    @abstractmethod
    def record_histogram(
        self, name: str, metric_value: Decimal, labels: dict[str, str] | None = None
    ) -> None:
        """Record a histogram metric."""
        pass

    @abstractmethod
    def reset_all(self) -> None:
        """Reset all metrics."""
        pass

    @abstractmethod
    def get_stats_summary(self) -> dict[str, Any]:
        """Get summary statistics of all metrics."""
        pass


# === 3. METRIC COLLECTOR ===
class MetricCollector(BaseMetricCollector):
    """
    Singleton collector for kernel metrics.
    Metrics are non-monetary: counts, durations, etc.
    """

    _instance: MetricCollector | None = None
    _lock = threading.Lock()
    _initialized: bool

    # Deklarasi tipe atribut untuk mypy (dengan __slots__)
    _audit_trail: list[dict[str, Any]]
    _counters: dict[str, int]
    _enabled: bool
    _gauges: dict[str, float]
    _histograms: dict[str, list[float]]
    _lock_internal: threading.RLock
    _max_histogram_samples: int
    _metric_definitions: dict[str, Metric]
    _snapshots: list[dict[str, Any]]
    _version: int

    __slots__ = (
        "_audit_trail",
        "_counters",
        "_enabled",
        "_gauges",
        "_histograms",
        "_initialized",
        "_lock_internal",
        "_max_histogram_samples",
        "_metric_definitions",
        "_snapshots",
        "_version",
    )

    def __new__(cls) -> MetricCollector:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._counters: dict[str, int] = defaultdict(int)
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, list[float]] = defaultdict(list)
        self._max_histogram_samples = 1000
        self._enabled = True
        self._metric_definitions: dict[str, Metric] = {}
        self._lock_internal = threading.RLock()
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._version = 1

    def define_metric(
        self, name: str, metric_type: MetricType, help_text: str, labels: list[str] | None = None
    ) -> None:
        with self._lock_internal:
            self._metric_definitions[name] = Metric(
                name=name,
                type=metric_type,
                help_text=help_text,
                labels=labels or [],
            )
            self._record_audit("DEFINE_METRIC", "system", {"name": name, "type": metric_type.name})

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self._record_audit("SET_ENABLED", "system", {"enabled": enabled})

    def increment_counter(
        self, name: str, labels: dict[str, str] | None = None, value: int = 1
    ) -> None:
        if not self._enabled:
            return
        key = self._build_key(name, labels)
        with self._lock_internal:
            self._counters[key] += value

    def decrement_counter(
        self, name: str, labels: dict[str, str] | None = None, value: int = 1
    ) -> None:
        if not self._enabled:
            return
        key = self._build_key(name, labels)
        with self._lock_internal:
            self._counters[key] = max(0, self._counters[key] - value)

    def set_gauge(
        self, name: str, metric_value: Decimal, labels: dict[str, str] | None = None
    ) -> None:
        if not self._enabled:
            return
        key = self._build_key(name, labels)
        with self._lock_internal:
            self._gauges[key] = float(metric_value)

    def increment_gauge(
        self, name: str, labels: dict[str, str] | None = None, delta: Decimal = Decimal("1.0")
    ) -> None:
        if not self._enabled:
            return
        key = self._build_key(name, labels)
        with self._lock_internal:
            self._gauges[key] = self._gauges.get(key, 0.0) + float(delta)

    def decrement_gauge(
        self, name: str, labels: dict[str, str] | None = None, delta: Decimal = Decimal("1.0")
    ) -> None:
        if not self._enabled:
            return
        key = self._build_key(name, labels)
        with self._lock_internal:
            self._gauges[key] = self._gauges.get(key, 0.0) - float(delta)

    def record_histogram(
        self, name: str, metric_value: Decimal, labels: dict[str, str] | None = None
    ) -> None:
        if not self._enabled:
            return
        key = self._build_key(name, labels)
        with self._lock_internal:
            hist = self._histograms[key]
            hist.append(float(metric_value))
            if len(hist) > self._max_histogram_samples:
                self._histograms[key] = hist[-self._max_histogram_samples :]

    def get_counter(self, name: str, labels: dict[str, str] | None = None) -> int:
        key = self._build_key(name, labels)
        with self._lock_internal:
            return self._counters.get(key, 0)

    def get_gauge(self, name: str, labels: dict[str, str] | None = None) -> float:
        key = self._build_key(name, labels)
        with self._lock_internal:
            return self._gauges.get(key, 0.0)

    def get_histogram_stats(
        self, name: str, labels: dict[str, str] | None = None
    ) -> dict[str, float]:
        key = self._build_key(name, labels)
        with self._lock_internal:
            values = self._histograms.get(key, [])
            if not values:
                return {
                    "count": 0,
                    "sum": 0,
                    "min": 0,
                    "max": 0,
                    "mean": 0,
                    "p50": 0,
                    "p90": 0,
                    "p95": 0,
                    "p99": 0,
                }
            sorted_vals = sorted(values)
            count = len(values)
            total = sum(values)
            mean = total / count
            p50 = sorted_vals[int(count * 0.5)] if count > 0 else 0
            p90 = sorted_vals[int(count * 0.9)] if count > 0 else 0
            p95 = sorted_vals[int(count * 0.95)] if count > 0 else 0
            p99 = sorted_vals[int(count * 0.99)] if count > 0 else 0
            return {
                "count": count,
                "sum": total,
                "min": min(values),
                "max": max(values),
                "mean": mean,
                "p50": p50,
                "p90": p90,
                "p95": p95,
                "p99": p99,
            }

    def reset_counter(self, name: str, labels: dict[str, str] | None = None) -> None:
        key = self._build_key(name, labels)
        with self._lock_internal:
            self._counters[key] = 0

    def reset_histogram(self, name: str, labels: dict[str, str] | None = None) -> None:
        key = self._build_key(name, labels)
        with self._lock_internal:
            self._histograms[key] = []

    def reset_all(self) -> None:
        with self._lock_internal:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()
            self._version += 1
            self._record_audit("RESET_ALL", "system", {})

    def _build_key(self, name: str, labels: dict[str, str] | None) -> str:
        if not labels:
            return name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}[{label_str}]"

    def _parse_key(self, key: str) -> tuple[str, dict[str, str] | None]:
        if "[" not in key:
            return key, None
        name, label_part = key.split("[", 1)
        label_part = label_part.rstrip("]")
        labels = {}
        for pair in label_part.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                labels[k] = v
        return name, labels if labels else None

    def get_all_metrics(self) -> dict[str, Any]:
        result: dict[str, Any] = {"counters": {}, "gauges": {}, "histograms": {}}
        with self._lock_internal:
            for key, counter_val in self._counters.items():
                name, labels = self._parse_key(key)
                result["counters"][key] = {"value": counter_val, "name": name, "labels": labels}
            for key, gauge_val in self._gauges.items():
                name, labels = self._parse_key(key)
                result["gauges"][key] = {"value": gauge_val, "name": name, "labels": labels}
            for key in self._histograms:
                name, labels = self._parse_key(key)
                stats = self.get_histogram_stats(name, labels)
                result["histograms"][key] = {"stats": stats, "name": name, "labels": labels}
        return result

    def export_to_prometheus(self) -> str:
        if not self._enabled:
            return "# Metrics collection disabled\n"
        lines = []
        lines.append("# HELP kernel_metrics Metrics from kernel layer")
        lines.append("# TYPE kernel_metrics summary")
        with self._lock_internal:
            for key, counter_value in self._counters.items():
                name, labels = self._parse_key(key)
                label_str = self._format_labels(labels) if labels else ""
                lines.append(f"{name}_total{label_str} {counter_value}")
            for key, gauge_value in self._gauges.items():
                name, labels = self._parse_key(key)
                label_str = self._format_labels(labels) if labels else ""
                lines.append(f"{name}{label_str} {gauge_value}")
            for key in self._histograms:
                name, labels = self._parse_key(key)
                label_str = self._format_labels(labels) if labels else ""
                stats = self.get_histogram_stats(name, labels)
                lines.append(f"{name}_count{label_str} {stats['count']}")
                lines.append(f"{name}_sum{label_str} {stats['sum']}")
                lines.append(f"{name}_min{label_str} {stats['min']}")
                lines.append(f"{name}_max{label_str} {stats['max']}")
                lines.append(f"{name}_mean{label_str} {stats['mean']:.6f}")
                lines.append(f"{name}_p50{label_str} {stats['p50']}")
                lines.append(f"{name}_p90{label_str} {stats['p90']}")
                lines.append(f"{name}_p95{label_str} {stats['p95']}")
                lines.append(f"{name}_p99{label_str} {stats['p99']}")
        return "\n".join(lines)

    def _format_labels(self, labels: dict[str, str]) -> str:
        parts = [f'{k}="{v}"' for k, v in labels.items()]
        return "{" + ",".join(parts) + "}"

    def get_stats_summary(self) -> dict[str, Any]:
        with self._lock_internal:
            return {
                "counters_count": len(self._counters),
                "gauges_count": len(self._gauges),
                "histograms_count": len(self._histograms),
                "total_samples": sum(len(v) for v in self._histograms.values()),
                "enabled": self._enabled,
                "version": self._version,
            }

    def get_counter_names(self) -> list[str]:
        with self._lock_internal:
            return list({self._parse_key(k)[0] for k in self._counters})

    def get_gauge_names(self) -> list[str]:
        with self._lock_internal:
            return list({self._parse_key(k)[0] for k in self._gauges})

    def clear(self) -> None:
        self.reset_all()

    # ==================== METODA ENTITY DASAR ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if self._max_histogram_samples <= 0:
            errors.append("max_histogram_samples must be positive")
        for name, metric in self._metric_definitions.items():
            res = metric.validate()
            if not res["is_valid"]:
                errors.extend([f"{name}: {e}" for e in res["errors"]])
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        with self._lock_internal:
            return {
                "enabled": self._enabled,
                "max_histogram_samples": self._max_histogram_samples,
                "counters_count": len(self._counters),
                "gauges_count": len(self._gauges),
                "histograms_count": len(self._histograms),
                "metric_definitions": {k: v.to_dict() for k, v in self._metric_definitions.items()},
                "version": self._version,
            }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MetricCollector:
        instance = cls()
        instance._enabled = data.get("enabled", True)
        instance._max_histogram_samples = data.get("max_histogram_samples", 1000)
        instance._version = data.get("version", 1)
        for name, metric_data in data.get("metric_definitions", {}).items():
            instance._metric_definitions[name] = Metric.from_dict(metric_data)
        return instance

    def clone(self) -> MetricCollector:
        new_instance = MetricCollector()
        new_instance._enabled = self._enabled
        new_instance._max_histogram_samples = self._max_histogram_samples
        new_instance._version = self._version + 1
        with self._lock_internal:
            new_instance._metric_definitions = {
                k: v.clone() for k, v in self._metric_definitions.items()
            }
        return new_instance

    def snapshot(self) -> dict[str, Any]:
        with self._lock_internal:
            return {
                "version": self._version,
                "enabled": self._enabled,
                "counters_count": len(self._counters),
                "gauges_count": len(self._gauges),
                "histograms_count": len(self._histograms),
                "total_samples": sum(len(v) for v in self._histograms.values()),
                "timestamp": datetime.now(UTC).isoformat(),
            }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> MetricCollector:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "details": details,
            }
        )

    def reset(self) -> None:
        self.reset_all()
        self._version = 1
        self._audit_trail = []
        self._snapshots = []


# === 4. SINGLETON ACCESSOR ===
_metric_collector_instance: MetricCollector | None = None


def get_metric_collector() -> MetricCollector:
    global _metric_collector_instance
    if _metric_collector_instance is None:
        _metric_collector_instance = MetricCollector()
    return _metric_collector_instance


# === 5. CONVENIENCE FUNCTIONS ===
def inc_counter(name: str, labels: dict[str, str] | None = None, value: int = 1) -> None:
    get_metric_collector().increment_counter(name, labels, value)


def set_gauge(
    name: str, metric_value: Decimal, labels: dict[str, str] | None = None
) -> None:
    get_metric_collector().set_gauge(name, metric_value, labels)


def record_histogram(
    name: str, metric_value: Decimal, labels: dict[str, str] | None = None
) -> None:
    get_metric_collector().record_histogram(name, metric_value, labels)


# === 6. TIMING CONTEXT MANAGER ===
@dataclass
class TimingContext:
    metric_name: str
    labels: dict[str, str] | None = None
    _start_time: float = 0.0
    _collector: MetricCollector | None = None

    def __enter__(self):
        self._collector = get_metric_collector()
        self._start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration_ms = (time.time() - self._start_time) * 1000
        # PERBAIKAN: Memastikan _collector tidak bernilai None sebelum memanggil method
        if self._collector is not None:
            self._collector.record_histogram(self.metric_name, Decimal(str(duration_ms)), self.labels)
            if exc_type is not None:
                self._collector.increment_counter(f"{self.metric_name}_errors", self.labels)
            else:
                self._collector.increment_counter(f"{self.metric_name}_success", self.labels)


def timing(metric_name: str, labels: dict[str, str] | None = None):
    def decorator(func):
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            collector = get_metric_collector()
            start = time.time()
            try:
                result = func(*args, **kwargs)
                duration_ms = (time.time() - start) * 1000
                collector.record_histogram(metric_name, Decimal(str(duration_ms)), labels)
                collector.increment_counter(f"{metric_name}_success", labels)
                return result
            except Exception:
                duration_ms = (time.time() - start) * 1000
                collector.record_histogram(metric_name, Decimal(str(duration_ms)), labels)
                collector.increment_counter(f"{metric_name}_errors", labels)
                raise

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            collector = get_metric_collector()
            start = time.time()
            try:
                result = await func(*args, **kwargs)
                duration_ms = (time.time() - start) * 1000
                collector.record_histogram(metric_name, Decimal(str(duration_ms)), labels)
                collector.increment_counter(f"{metric_name}_success", labels)
                return result
            except Exception:
                duration_ms = (time.time() - start) * 1000
                collector.record_histogram(metric_name, Decimal(str(duration_ms)), labels)
                collector.increment_counter(f"{metric_name}_errors", labels)
                raise

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


__all__ = [
    "Metric",
    "MetricCollector",
    "MetricType",
    "TimingContext",
    "get_metric_collector",
    "inc_counter",
    "record_histogram",
    "set_gauge",
    "timing",
]
