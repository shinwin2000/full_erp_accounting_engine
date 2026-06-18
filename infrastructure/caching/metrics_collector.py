#!/usr/bin/env python3
"""
Module: metrics_collector.py
Layer: Infrastructure (Caching)
Responsibility: Mengumpulkan dan mengekspor metrik tentang cache (Redis) untuk
               monitoring dan observability. Metrik mencakup hit rate,
               miss rate, cache size, eviction count, memory usage, latency,
               dan error rates. Metrik diekspos untuk Prometheus scraping.
Dependencies:
- asyncio, logging, time
- infrastructure.caching.redis_manager (RedisManager)
- infrastructure.telemetry.prometheus_registry
- infrastructure.telemetry.alert_manager_router
Audit: Metrik cache digunakan untuk monitoring performance dan capacity planning.
       Cache hit rate rendah memicu alert untuk review.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

# Internal dependencies
from infrastructure.caching.redis_manager import RedisManager, get_redis_manager
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.prometheus_registry import (
    get_counter,
    get_gauge,
    get_histogram,
)

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

METRIC_PREFIX = "cache"
COLLECTION_INTERVAL_SECONDS = 60  # Collect metrics every minute

# Alert thresholds
CACHE_HIT_RATE_WARNING = 0.5  # 50% hit rate warning
CACHE_HIT_RATE_CRITICAL = 0.2  # 20% hit rate critical
MEMORY_USAGE_WARNING = 0.8  # 80% memory usage warning
MEMORY_USAGE_CRITICAL = 0.95  # 95% memory usage critical

# ============================================================================
# PROMETHEUS METRICS
# ============================================================================

# Counter metrics
cache_hits_total = get_counter(f"{METRIC_PREFIX}_hits_total", "Total number of cache hits")

cache_misses_total = get_counter(f"{METRIC_PREFIX}_misses_total", "Total number of cache misses")

cache_errors_total = get_counter(
    f"{METRIC_PREFIX}_errors_total", "Total number of cache errors", ["error_type"]
)

cache_evictions_total = get_counter(
    f"{METRIC_PREFIX}_evictions_total", "Total number of cache evictions"
)

# Gauge metrics
cache_hit_rate = get_gauge(f"{METRIC_PREFIX}_hit_rate", "Cache hit rate (0-1)")

cache_size_bytes = get_gauge(f"{METRIC_PREFIX}_size_bytes", "Total cache size in bytes")

cache_keys_count = get_gauge(f"{METRIC_PREFIX}_keys_count", "Number of keys in cache")

cache_memory_usage_percent = get_gauge(
    f"{METRIC_PREFIX}_memory_usage_percent", "Redis memory usage percentage"
)

cache_connected_clients = get_gauge(
    f"{METRIC_PREFIX}_connected_clients", "Number of connected Redis clients"
)

cache_uptime_seconds = get_gauge(f"{METRIC_PREFIX}_uptime_seconds", "Redis uptime in seconds")

# Histogram metrics
cache_operation_latency = get_histogram(
    f"{METRIC_PREFIX}_operation_latency_seconds",
    "Cache operation latency",
    ["operation"],
    buckets=[0.0001, 0.0005, 0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1],
)


# ============================================================================
# METRICS COLLECTOR
# ============================================================================


class CacheMetricsCollector:
    """
    Collector untuk metrik cache.

    Fitur:
    - Periodic collection
    - Hit rate calculation
    - Memory usage monitoring
    - Operation latency tracking
    - Prometheus integration
    """

    def __init__(self, redis_manager: RedisManager | None = None):
        self._redis_manager = redis_manager
        self._collection_task: asyncio.Task | None = None
        self._running = False
        self._hits = 0
        self._misses = 0
        self._operation_stats: dict[str, list[float]] = {}

    async def _get_redis(self) -> RedisManager:
        if self._redis_manager is None:
            self._redis_manager = await get_redis_manager()
        return self._redis_manager

    async def collect_metrics(self) -> dict[str, Any]:
        """
        Collect all cache metrics.
        """
        metrics = {}
        start_time = time.time()

        try:
            redis = await self._get_redis()
            client = await redis.get_client()

            # Get Redis INFO
            info = await client.info()

            # Basic stats
            metrics["uptime_seconds"] = info.get("uptime_in_seconds", 0)
            metrics["connected_clients"] = info.get("connected_clients", 0)
            metrics["used_memory_bytes"] = info.get("used_memory", 0)
            metrics["used_memory_peak_bytes"] = info.get("used_memory_peak", 0)
            metrics["total_connections_received"] = info.get("total_connections_received", 0)
            metrics["total_commands_processed"] = info.get("total_commands_processed", 0)
            metrics["keyspace_hits"] = info.get("keyspace_hits", 0)
            metrics["keyspace_misses"] = info.get("keyspace_misses", 0)
            metrics["evicted_keys"] = info.get("evicted_keys", 0)
            metrics["expired_keys"] = info.get("expired_keys", 0)

            # Memory usage percentage
            maxmemory = info.get("maxmemory", 0)
            if maxmemory and maxmemory > 0:
                metrics["memory_usage_percent"] = (metrics["used_memory_bytes"] / maxmemory) * 100
            else:
                metrics["memory_usage_percent"] = 0

            # Calculate hit rate
            total_ops = metrics["keyspace_hits"] + metrics["keyspace_misses"]
            if total_ops > 0:
                metrics["hit_rate"] = metrics["keyspace_hits"] / total_ops
            else:
                metrics["hit_rate"] = 0

            # Get keyspace info
            keyspace = info.get("keyspace", {})
            metrics["keys_count"] = sum(db.get("keys", 0) for db in keyspace.values())

            # Track differences from previous collection
            if hasattr(self, "_last_hits"):
                metrics["hits_since_last"] = metrics["keyspace_hits"] - self._last_hits
                metrics["misses_since_last"] = metrics["keyspace_misses"] - self._last_misses
            else:
                metrics["hits_since_last"] = 0
                metrics["misses_since_last"] = 0

            self._last_hits = metrics["keyspace_hits"]
            self._last_misses = metrics["keyspace_misses"]

            # Update Prometheus gauges
            cache_hit_rate.set(metrics["hit_rate"])
            cache_size_bytes.set(metrics["used_memory_bytes"])
            cache_keys_count.set(metrics["keys_count"])
            cache_memory_usage_percent.set(metrics["memory_usage_percent"])
            cache_connected_clients.set(metrics["connected_clients"])
            cache_uptime_seconds.set(metrics["uptime_seconds"])

            # Update counters for cumulative stats
            cache_evictions_total.inc(metrics["evicted_keys"] - getattr(self, "_last_evictions", 0))
            self._last_evictions = metrics["evicted_keys"]

            # Log warning if hit rate is low
            hit_rate = metrics["hit_rate"]
            if hit_rate < CACHE_HIT_RATE_CRITICAL:
                await trigger_alert(
                    title="Cache Hit Rate Critical",
                    message=f"Cache hit rate is {hit_rate:.2%} (below {CACHE_HIT_RATE_CRITICAL:.0%})",
                    severity="critical",
                    source="CacheMetricsCollector",
                )
            elif hit_rate < CACHE_HIT_RATE_WARNING:
                await trigger_alert(
                    title="Cache Hit Rate Low",
                    message=f"Cache hit rate is {hit_rate:.2%} (below {CACHE_HIT_RATE_WARNING:.0%})",
                    severity="warning",
                    source="CacheMetricsCollector",
                )

            # Log warning if memory usage is high
            mem_usage = metrics["memory_usage_percent"]
            if mem_usage > MEMORY_USAGE_CRITICAL * 100:
                await trigger_alert(
                    title="Cache Memory Usage Critical",
                    message=f"Cache memory usage is {mem_usage:.1f}% (above {MEMORY_USAGE_CRITICAL:.0%})",
                    severity="critical",
                    source="CacheMetricsCollector",
                )
            elif mem_usage > MEMORY_USAGE_WARNING * 100:
                await trigger_alert(
                    title="Cache Memory Usage High",
                    message=f"Cache memory usage is {mem_usage:.1f}% (above {MEMORY_USAGE_WARNING:.0%})",
                    severity="warning",
                    source="CacheMetricsCollector",
                )

            metrics["collection_duration_seconds"] = time.time() - start_time
            logger.debug(
                f"Cache metrics collected: hit_rate={hit_rate:.2%}, keys={metrics['keys_count']}"
            )

            return metrics

        except Exception as e:
            cache_errors_total.labels(error_type="metrics_collection").inc()
            logger.error(f"Failed to collect cache metrics: {e}")
            return {"error": str(e)}

    async def record_operation(
        self, operation: str, duration_seconds: float, success: bool
    ) -> None:
        """
        Record a cache operation for metrics.
        """
        cache_operation_latency.labels(operation=operation).observe(duration_seconds)

        if operation not in self._operation_stats:
            self._operation_stats[operation] = []
        self._operation_stats[operation].append(duration_seconds)

        # Keep only last 1000 samples
        if len(self._operation_stats[operation]) > 1000:
            self._operation_stats[operation] = self._operation_stats[operation][-1000:]

    async def record_hit(self) -> None:
        """Record a cache hit."""
        self._hits += 1
        cache_hits_total.inc()

    async def record_miss(self) -> None:
        """Record a cache miss."""
        self._misses += 1
        cache_misses_total.inc()

    async def record_error(self, error_type: str) -> None:
        """Record a cache error."""
        cache_errors_total.labels(error_type=error_type).inc()

    async def start_periodic_collection(
        self, interval_seconds: int = COLLECTION_INTERVAL_SECONDS
    ) -> None:
        """
        Start periodic collection of metrics.
        """
        if self._running:
            logger.warning("Periodic collection already running")
            return

        self._running = True
        self._collection_task = asyncio.create_task(
            self._periodic_collection_loop(interval_seconds)
        )
        logger.info(f"Started periodic cache metrics collection every {interval_seconds} seconds")

    async def _periodic_collection_loop(self, interval_seconds: int) -> None:
        """
        Background loop for periodic metrics collection.
        """
        while self._running:
            try:
                await self.collect_metrics()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic metrics collection: {e}")

            await asyncio.sleep(interval_seconds)

    async def stop_periodic_collection(self) -> None:
        """
        Stop periodic collection.
        """
        self._running = False
        if self._collection_task:
            self._collection_task.cancel()
            try:
                await self._collection_task
            except asyncio.CancelledError:
                pass
            self._collection_task = None
        logger.info("Stopped periodic cache metrics collection")

    async def get_operation_stats(self) -> dict[str, Any]:
        """
        Get operation statistics.
        """
        stats = {}
        for op, durations in self._operation_stats.items():
            if durations:
                stats[op] = {
                    "count": len(durations),
                    "avg_latency_ms": (sum(durations) / len(durations)) * 1000,
                    "min_latency_ms": min(durations) * 1000,
                    "max_latency_ms": max(durations) * 1000,
                    "p95_latency_ms": sorted(durations)[int(len(durations) * 0.95)] * 1000
                    if durations
                    else 0,
                }
        return stats

    async def get_hit_rate(self) -> float:
        """
        Get current cache hit rate.
        """
        total = self._hits + self._misses
        if total == 0:
            return 0.0
        return self._hits / total

    async def reset_stats(self) -> None:
        """
        Reset statistics (for testing).
        """
        self._hits = 0
        self._misses = 0
        self._operation_stats.clear()
        logger.info("Cache metrics stats reset")


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_metrics_collector: CacheMetricsCollector | None = None


async def get_cache_metrics_collector() -> CacheMetricsCollector:
    """Get singleton instance of CacheMetricsCollector."""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = CacheMetricsCollector()
    return _metrics_collector


async def start_cache_metrics_collection() -> None:
    """Start cache metrics collection."""
    collector = await get_cache_metrics_collector()
    await collector.start_periodic_collection()


async def stop_cache_metrics_collection() -> None:
    """Stop cache metrics collection."""
    global _metrics_collector
    if _metrics_collector:
        await _metrics_collector.stop_periodic_collection()
        _metrics_collector = None


# ============================================================================
# DECORATOR FOR CACHE OPERATION METRICS
# ============================================================================


def with_cache_metrics(operation: str):
    """
    Decorator untuk mencatat metrik operasi cache.
    """

    def decorator(func):
        async def wrapper(*args, **kwargs):
            collector = await get_cache_metrics_collector()
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                duration = time.time() - start_time
                await collector.record_operation(operation, duration, success=True)

                # Record hit/miss based on result
                if result is not None:
                    await collector.record_hit()
                else:
                    await collector.record_miss()

                return result
            except Exception:
                duration = time.time() - start_time
                await collector.record_operation(operation, duration, success=False)
                await collector.record_error(operation)
                raise

        return wrapper

    return decorator


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "CacheMetricsCollector",
    "get_cache_metrics_collector",
    "start_cache_metrics_collection",
    "stop_cache_metrics_collection",
    "with_cache_metrics",
]
