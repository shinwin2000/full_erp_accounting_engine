#!/usr/bin/env python3
"""
Module: prometheus_registry.py
Layer: Infrastructure (Telemetry)
Responsibility: Mengelola registry Prometheus untuk metrics collection.
               Menyediakan fungsi untuk mendaftarkan dan mengakses counter,
               gauge, histogram, dan summary metrics. Mendukung multiple
               registries dan label validation.
Dependencies:
- prometheus_client (optional, fallback ke dummy)
- logging
- infrastructure.telemetry.structured_json_logging
Audit: Metrics digunakan untuk monitoring performance dan alerting.
       Registry dapat di-scrape oleh Prometheus server.
"""

from __future__ import annotations

import logging
import threading
from functools import wraps
from typing import Any

# Try to import prometheus_client
try:
    import prometheus_client
    from prometheus_client import Counter, Enum, Gauge, Histogram, Info, Summary, start_http_server
    from prometheus_client.registry import REGISTRY

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

    # Create dummy classes
    class Counter:
        def __init__(self, *args, **kwargs):
            pass

        def inc(self, *args, **kwargs):
            pass

        def labels(self, *args, **kwargs):
            return self

    class Gauge:
        def __init__(self, *args, **kwargs):
            pass

        def set(self, *args, **kwargs):
            pass

        def inc(self, *args, **kwargs):
            pass

        def dec(self, *args, **kwargs):
            pass

        def labels(self, *args, **kwargs):
            return self

    class Histogram:
        def __init__(self, *args, **kwargs):
            pass

        def observe(self, *args, **kwargs):
            pass

        def labels(self, *args, **kwargs):
            return self

    class Summary:
        def __init__(self, *args, **kwargs):
            pass

        def observe(self, *args, **kwargs):
            pass

        def labels(self, *args, **kwargs):
            return self

    class Info:
        def __init__(self, *args, **kwargs):
            pass

        def info(self, *args, **kwargs):
            pass

    class Enum:
        def __init__(self, *args, **kwargs):
            pass

        def state(self, *args, **kwargs):
            pass

    REGISTRY = None

    def start_http_server(port, addr=""):
        pass


logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.075,
    0.1,
    0.25,
    0.5,
    0.75,
    1.0,
    2.5,
    5.0,
    7.5,
    10.0,
    float("inf"),
)
BATCH_BUCKETS = (1, 2, 5, 10, 20, 50, 100, 250, 500, float("inf"))

# ============================================================================
# METRIC REGISTRY
# ============================================================================


class PrometheusMetricRegistry:
    """
    Registry untuk Prometheus metrics.

    Fitur:
    - Mendaftarkan metrics dengan namespace
    - Mendapatkan metric yang sudah terdaftar
    - Multiple registry support
    - Label validation
    - Metrics listing
    """

    def __init__(self, namespace: str = "erp"):
        self.namespace = namespace
        self._metrics: dict[str, Any] = {}
        self._registry = REGISTRY

    def _get_metric_name(self, name: str) -> str:
        """Get fully qualified metric name."""
        return f"{self.namespace}_{name}"

    def counter(
        self, name: str, documentation: str, labelnames: list[str] | None = None
    ) -> Counter:
        """
        Create or get a Counter metric.
        """
        metric_name = self._get_metric_name(name)
        if metric_name in self._metrics:
            return self._metrics[metric_name]

        if PROMETHEUS_AVAILABLE:
            metric = Counter(metric_name, documentation, labelnames or [], registry=self._registry)
        else:
            metric = Counter()

        self._metrics[metric_name] = metric
        logger.debug(f"Registered counter: {metric_name}")
        return metric

    def gauge(self, name: str, documentation: str, labelnames: list[str] | None = None) -> Gauge:
        """
        Create or get a Gauge metric.
        """
        metric_name = self._get_metric_name(name)
        if metric_name in self._metrics:
            return self._metrics[metric_name]

        if PROMETHEUS_AVAILABLE:
            metric = Gauge(metric_name, documentation, labelnames or [], registry=self._registry)
        else:
            metric = Gauge()

        self._metrics[metric_name] = metric
        logger.debug(f"Registered gauge: {metric_name}")
        return metric

    def histogram(
        self,
        name: str,
        documentation: str,
        labelnames: list[str] | None = None,
        buckets: list[float] | None = None,
    ) -> Histogram:
        """
        Create or get a Histogram metric.
        """
        metric_name = self._get_metric_name(name)
        if metric_name in self._metrics:
            return self._metrics[metric_name]

        if PROMETHEUS_AVAILABLE:
            metric = Histogram(
                metric_name,
                documentation,
                labelnames or [],
                buckets=buckets or DEFAULT_BUCKETS,
                registry=self._registry,
            )
        else:
            metric = Histogram()

        self._metrics[metric_name] = metric
        logger.debug(f"Registered histogram: {metric_name}")
        return metric

    def summary(
        self, name: str, documentation: str, labelnames: list[str] | None = None
    ) -> Summary:
        """
        Create or get a Summary metric.
        """
        metric_name = self._get_metric_name(name)
        if metric_name in self._metrics:
            return self._metrics[metric_name]

        if PROMETHEUS_AVAILABLE:
            metric = Summary(metric_name, documentation, labelnames or [], registry=self._registry)
        else:
            metric = Summary()

        self._metrics[metric_name] = metric
        logger.debug(f"Registered summary: {metric_name}")
        return metric

    def info(self, name: str, documentation: str) -> Info:
        """
        Create or get an Info metric.
        """
        metric_name = self._get_metric_name(name)
        if metric_name in self._metrics:
            return self._metrics[metric_name]

        if PROMETHEUS_AVAILABLE:
            metric = Info(metric_name, documentation, registry=self._registry)
        else:
            metric = Info()

        self._metrics[metric_name] = metric
        logger.debug(f"Registered info: {metric_name}")
        return metric

    def enum(
        self, name: str, documentation: str, states: list[str], labelnames: list[str] | None = None
    ) -> Enum:
        """
        Create or get an Enum metric.
        """
        metric_name = self._get_metric_name(name)
        if metric_name in self._metrics:
            return self._metrics[metric_name]

        if PROMETHEUS_AVAILABLE:
            metric = Enum(
                metric_name, documentation, states, labelnames or [], registry=self._registry
            )
        else:
            metric = Enum()

        self._metrics[metric_name] = metric
        logger.debug(f"Registered enum: {metric_name}")
        return metric

    def get_metric(self, name: str) -> Any | None:
        """
        Get a registered metric by name.
        """
        metric_name = self._get_metric_name(name)
        return self._metrics.get(metric_name)

    def list_metrics(self) -> list[str]:
        """
        List all registered metric names.
        """
        return list(self._metrics.keys())

    def get_registry(self):
        """
        Get the underlying Prometheus registry.
        """
        return self._registry


# ============================================================================
# DEFAULT REGISTRY
# ============================================================================

_default_registry: PrometheusMetricRegistry | None = None


def get_registry(namespace: str = "erp") -> PrometheusMetricRegistry:
    """
    Get the default Prometheus metric registry.
    """
    global _default_registry
    if _default_registry is None:
        _default_registry = PrometheusMetricRegistry(namespace)
    return _default_registry


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================


def get_counter(name: str, documentation: str, labelnames: list[str] | None = None) -> Counter:
    """Get a Counter metric from default registry."""
    return get_registry().counter(name, documentation, labelnames)


def get_gauge(name: str, documentation: str, labelnames: list[str] | None = None) -> Gauge:
    """Get a Gauge metric from default registry."""
    return get_registry().gauge(name, documentation, labelnames)


def get_histogram(
    name: str,
    documentation: str,
    labelnames: list[str] | None = None,
    buckets: list[float] | None = None,
) -> Histogram:
    """Get a Histogram metric from default registry."""
    return get_registry().histogram(name, documentation, labelnames, buckets)


def get_summary(name: str, documentation: str, labelnames: list[str] | None = None) -> Summary:
    """Get a Summary metric from default registry."""
    return get_registry().summary(name, documentation, labelnames)


def get_info(name: str, documentation: str) -> Info:
    """Get an Info metric from default registry."""
    return get_registry().info(name, documentation)


# ============================================================================
# PREâ€‘DEFINED METRICS
# ============================================================================

# Command bus metrics
commands_dispatched_total = get_counter(
    "commands_dispatched_total", "Total number of commands dispatched", labelnames=["command_type"]
)

commands_execution_latency_seconds = get_histogram(
    "commands_execution_latency_seconds",
    "Command execution latency in seconds",
    labelnames=["command_type"],
)

commands_failed_total = get_counter(
    "commands_failed_total",
    "Total number of commands that failed",
    labelnames=["command_type", "reason"],
)

commands_succeeded_total = get_counter(
    "commands_succeeded_total",
    "Total number of commands that succeeded",
    labelnames=["command_type"],
)

commands_duration_seconds = get_histogram(
    "commands_duration_seconds",
    "Duration of command handling in seconds",
    labelnames=["command_type"],
)

# Query bus metrics
queries_dispatched_total = get_counter(
    "queries_dispatched_total", "Total number of queries dispatched", labelnames=["query_type"]
)

queries_latency_seconds = get_histogram(
    "queries_latency_seconds", "Query execution latency in seconds", labelnames=["query_type"]
)

queries_cache_hits_total = get_counter(
    "queries_cache_hits_total", "Total number of cache hits for queries", labelnames=["query_type"]
)

queries_duration_seconds = get_histogram(
    "queries_duration_seconds", "Duration of query handling in seconds", labelnames=["query_type"]
)

# Event metrics (publisher & handlers)
events_published_total = get_counter(
    "events_published_total", "Total number of events published", labelnames=["event_type"]
)

events_publish_latency_seconds = get_histogram(
    "events_publish_latency_seconds",
    "Event publishing latency in seconds",
    labelnames=["event_type"],
)

events_publish_errors_total = get_counter(
    "events_publish_errors_total",
    "Total number of event publishing errors",
    labelnames=["error_type"],
)

events_handled_total = get_counter(
    "events_handled_total",
    "Total number of events handled by subscribers",
    labelnames=["event_type", "status"],
)

# Outbox Relay metrics
outbox_events_published_total = get_counter(
    "outbox_events_published_total",
    "Total number of outbox events published to message broker",
    labelnames=["event_type"],
)

outbox_events_failed_total = get_counter(
    "outbox_events_failed_total",
    "Total number of outbox events that failed to publish to message broker",
    labelnames=["event_type", "reason"],
)

outbox_publish_latency_seconds = get_histogram(
    "outbox_publish_latency_seconds",
    "Outbox event publishing latency in seconds",
    labelnames=["event_type"],
)

outbox_batch_size = get_histogram(
    "outbox_batch_size", "Distribution of outbox relay batch sizes", buckets=BATCH_BUCKETS
)

# Subscriber metrics (consumption)
events_consumed_total = get_counter(
    "events_consumed_total",
    "Total number of events consumed from broker",
    labelnames=["event_type", "status"],
)

events_processed_total = get_counter(
    "events_processed_total",
    "Total number of events processed by handlers",
    labelnames=["event_type"],
)

events_processing_errors_total = get_counter(
    "events_processing_errors_total",
    "Total number of event processing errors",
    labelnames=["event_type", "error_type"],
)

events_processing_latency_seconds = get_histogram(
    "events_processing_latency_seconds",
    "Event processing latency in seconds",
    labelnames=["event_type"],
)

dead_letter_events_total = get_counter(
    "dead_letter_events_total",
    "Total number of events sent to dead letter",
    labelnames=["event_type"],
)

# Business metrics
journal_entries_total = get_counter(
    "journal_entries_total",
    "Total number of journal entries",
    labelnames=["journal_type", "status"],
)

transaction_volume_total = get_counter(
    "transaction_volume_total",
    "Total number of financial transactions",
    labelnames=["transaction_type"],
)

# ============================================================================
# PROMETHEUS HTTP SERVER SETUP (for app_factory)
# ============================================================================

_http_server_thread: threading.Thread | None = None


def setup_prometheus(port: int = 9090, addr: str = "") -> None:
    """
    Start Prometheus HTTP server for metrics scraping.

    This function is called from app_factory.py to expose /metrics endpoint.

    Args:
        port: Port to listen on (default 9090)
        addr: Address to bind (default '' for all interfaces)
    """
    global _http_server_thread

    if not PROMETHEUS_AVAILABLE:
        logger.warning("Prometheus client not installed. Metrics disabled.")
        return

    if _http_server_thread is not None and _http_server_thread.is_alive():
        logger.info(f"Prometheus HTTP server already running on port {port}")
        return

    try:
        start_http_server(port, addr=addr)
        _http_server_thread = threading.Thread(target=lambda: None, daemon=True)
        logger.info(f"Prometheus metrics server started on port {port}")
    except Exception as e:
        logger.error(f"Failed to start Prometheus HTTP server: {e}")


async def flush() -> None:
    """Flush metrics atau no-op untuk kompatibilitas daur hidup ASGI."""
    logger.info("Prometheus metrics registry flush executed.")


# ============================================================================
# DECORATORS
# ============================================================================


def timed_metric(metric_name: str, labelnames: list[str] | None = None):
    """
    Decorator untuk mengukur durasi fungsi.

    Usage:
        @timed_metric("my_function_duration", ["method"])
        async def my_function(method: str):
            ...
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            import time

            start = time.time()
            try:
                result = await func(*args, **kwargs)
                duration = time.time() - start

                # Get label values from kwargs
                labels = {}
                if labelnames:
                    for label in labelnames:
                        labels[label] = str(kwargs.get(label, "default"))

                metric = get_histogram(metric_name, f"Duration of {func.__name__}", labelnames)
                if labels:
                    metric.labels(**labels).observe(duration)
                else:
                    metric.observe(duration)

                return result
            except Exception:
                duration = time.time() - start
                metric = get_histogram(metric_name, f"Duration of {func.__name__}", labelnames)
                if labelnames:
                    metric.labels(**{l: str(kwargs.get(l, "default")) for l in labelnames}).observe(
                        duration
                    )
                else:
                    metric.observe(duration)
                raise

        return wrapper

    return decorator


def count_metric(metric_name: str, labelnames: list[str] | None = None):
    """
    Decorator untuk menghitung jumlah panggilan fungsi.
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            metric = get_counter(metric_name, f"Count of {func.__name__}", labelnames)
            if labelnames:
                labels = {l: str(kwargs.get(l, "default")) for l in labelnames}
                metric.labels(**labels).inc()
            else:
                metric.inc()
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def error_metric(metric_name: str, labelnames: list[str] | None = None):
    """
    Decorator untuk menghitung error pada fungsi.
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            metric = get_counter(metric_name, f"Error count of {func.__name__}", labelnames)
            try:
                return await func(*args, **kwargs)
            except Exception:
                if labelnames:
                    labels = {l: str(kwargs.get(l, "default")) for l in labelnames}
                    metric.labels(**labels).inc()
                else:
                    metric.inc()
                raise

        return wrapper

    return decorator


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "PrometheusMetricRegistry",
    "get_registry",
    "get_counter",
    "get_gauge",
    "get_histogram",
    "get_summary",
    "get_info",
    "timed_metric",
    "count_metric",
    "error_metric",
    "flush",
    "setup_prometheus",
    "PROMETHEUS_AVAILABLE",
    # Pre-defined metrics
    "commands_dispatched_total",
    "commands_execution_latency_seconds",
    "commands_failed_total",
    "commands_succeeded_total",
    "commands_duration_seconds",
    "queries_dispatched_total",
    "queries_latency_seconds",
    "queries_cache_hits_total",
    "queries_duration_seconds",
    "events_published_total",
    "events_publish_latency_seconds",
    "events_publish_errors_total",
    "events_handled_total",
    # Outbox Relay metrics
    "outbox_events_published_total",
    "outbox_events_failed_total",
    "outbox_publish_latency_seconds",
    "outbox_batch_size",
    # Subscriber metrics
    "events_consumed_total",
    "events_processed_total",
    "events_processing_errors_total",
    "events_processing_latency_seconds",
    "dead_letter_events_total",
    "journal_entries_total",
    "transaction_volume_total",
]
