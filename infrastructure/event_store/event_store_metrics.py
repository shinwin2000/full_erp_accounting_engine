#!/usr/bin/env python3
"""
Module: event_store_metrics.py
Layer: Infrastructure (Event Store)
Responsibility: Mengumpulkan dan mengekspos metrik tentang event store.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, text

from infrastructure.telemetry.prometheus_registry import (
    get_counter,
    get_gauge,
    get_histogram,
)

try:
    import prometheus_client
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    class Gauge:
        def set(self, *args, **kwargs): pass
        def inc(self, *args, **kwargs): pass
        def dec(self, *args, **kwargs): pass
    class Counter:
        def inc(self, *args, **kwargs): pass
    class Histogram:
        def observe(self, *args, **kwargs): pass

logger = logging.getLogger(__name__)

METRIC_PREFIX = "event_store"
DEFAULT_COLLECTION_INTERVAL_SECONDS = 60

events_appended_total = get_counter(
    f"{METRIC_PREFIX}_events_appended_total",
    "Total number of events appended",
    ["stream_name", "event_type"],
)
events_appended_bytes = get_counter(
    f"{METRIC_PREFIX}_events_appended_bytes_total",
    "Total bytes of events appended",
    ["stream_name"],
)
errors_total = get_counter(
    f"{METRIC_PREFIX}_errors_total", "Total number of errors", ["error_type"]
)
append_latency = get_histogram(
    f"{METRIC_PREFIX}_append_latency_seconds",
    "Latency of append operations",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10],
)
read_latency = get_histogram(
    f"{METRIC_PREFIX}_read_latency_seconds",
    "Latency of read operations",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10],
)
snapshot_save_latency = get_histogram(
    f"{METRIC_PREFIX}_snapshot_save_latency_seconds", "Latency of snapshot save operations"
)
snapshot_load_latency = get_histogram(
    f"{METRIC_PREFIX}_snapshot_load_latency_seconds", "Latency of snapshot load operations"
)
total_events_gauge = get_gauge(f"{METRIC_PREFIX}_total_events", "Total number of events")
total_streams_gauge = get_gauge(f"{METRIC_PREFIX}_total_streams", "Total number of streams")
events_per_stream = get_gauge(
    f"{METRIC_PREFIX}_events_per_stream", "Events per stream", ["stream_name"]
)
snapshot_count_gauge = get_gauge(f"{METRIC_PREFIX}_snapshots_total", "Total snapshots")
hash_chain_valid = get_gauge(
    f"{METRIC_PREFIX}_hash_chain_valid",
    "Is hash chain valid (1=valid, 0=invalid)",
    ["stream_name"],
)
event_store_size_bytes = get_gauge(f"{METRIC_PREFIX}_size_bytes", "Total size in bytes")
last_append_timestamp = get_gauge(
    f"{METRIC_PREFIX}_last_append_timestamp_seconds", "Timestamp of last append"
)
events_per_second_gauge = get_gauge(
    f"{METRIC_PREFIX}_events_per_second", "Events per second throughput"
)


class EventStoreMetricsCollector:
    def __init__(
        self,
        event_store=None,
        snapshot_store=None,  # type akan diresolve dengan annotations
    ):
        self._event_store = event_store
        self._snapshot_store = snapshot_store
        self._collection_task: asyncio.Task | None = None
        self._running = False
        self._last_event_count = 0
        self._last_collection_time: datetime | None = None
        self._throughput_cache: dict[str, float] = {}
        self._metrics_enabled = PROMETHEUS_AVAILABLE

    async def _get_event_store(self):
        if self._event_store is None:
            from infrastructure.event_store.append_only_store import get_event_store
            self._event_store = await get_event_store()
        return self._event_store

    async def _get_snapshot_store(self):
        if self._snapshot_store is None:
            from infrastructure.event_store.snapshot_store_aggregate import get_snapshot_store
            self._snapshot_store = await get_snapshot_store()
        return self._snapshot_store

    async def collect_metrics(self) -> dict[str, Any]:
        metrics = {}
        start_time = time.time()
        try:
            store = await self._get_event_store()
            if not hasattr(store, "_session_factory") or store._session_factory is None:
                from infrastructure.database.session_factory_sqlalchemy import get_session_factory
                store._session_factory = await get_session_factory()

            total_events = 0
            total_streams = 0
            stream_stats = {}

            async with store._session_factory() as session:
                from infrastructure.persistence_orm.event_store_table import EventStoreTable

                count_stmt = select(func.count()).select_from(EventStoreTable)
                count_result = await session.execute(count_stmt)
                total_events = count_result.scalar() or 0

                stream_stmt = select(EventStoreTable.stream_name).distinct()
                stream_result = await session.execute(stream_stmt)
                stream_names = stream_result.scalars().all()
                total_streams = len(stream_names)

                for stream_name in stream_names[:100]:
                    stream_count_stmt = (
                        select(func.count())
                        .select_from(EventStoreTable)
                        .where(EventStoreTable.stream_name == stream_name)
                    )
                    stream_count_result = await session.execute(stream_count_stmt)
                    events_in_stream = stream_count_result.scalar() or 0
                    stream_stats[stream_name] = events_in_stream

            size_stmt = "SELECT pg_total_relation_size('event_store')"
            async with store._session_factory() as session:
                size_result = await session.execute(text(size_stmt))
                size_bytes = size_result.scalar() or 0

            snapshot_store = await self._get_snapshot_store()
            snapshot_stats = await snapshot_store.get_stats()

            now = datetime.now(UTC)
            if self._last_collection_time:
                time_diff = (now - self._last_collection_time).total_seconds()
                if time_diff > 0:
                    events_diff = total_events - self._last_event_count
                    throughput = events_diff / time_diff
                    self._throughput_cache["events_per_second"] = throughput

            self._last_event_count = total_events
            self._last_collection_time = now

            metrics = {
                "total_events": total_events,
                "total_streams": total_streams,
                "storage_size_bytes": size_bytes,
                "events_per_second": self._throughput_cache.get("events_per_second", 0),
                "stream_stats": stream_stats,
                "snapshot_stats": snapshot_stats,
                "collection_duration_seconds": time.time() - start_time,
            }

            if self._metrics_enabled:
                total_events_gauge.set(total_events)
                total_streams_gauge.set(total_streams)
                event_store_size_bytes.set(size_bytes)
                if self._throughput_cache.get("events_per_second"):
                    events_per_second_gauge.set(self._throughput_cache["events_per_second"])
                for stream_name, count in stream_stats.items():
                    events_per_stream.labels(stream_name=stream_name).set(count)
                if snapshot_stats:
                    snapshot_count_gauge.set(snapshot_stats.get("total_snapshots", 0))

            logger.debug(f"Metrics collected: {total_events} events, {total_streams} streams")
            return metrics
        except Exception as e:
            errors_total.labels(error_type="metrics_collection").inc()
            logger.error(f"Failed to collect metrics: {e}")
            return {"error": str(e)}

    async def check_hash_chain_integrity(self) -> dict[str, Any]:
        try:
            store = await self._get_event_store()
            from infrastructure.event_store.hash_chain_builder import get_hash_chain_builder
            hash_builder = get_hash_chain_builder()

            async with store._session_factory() as session:
                from infrastructure.persistence_orm.event_store_table import EventStoreTable
                stream_stmt = select(EventStoreTable.stream_name).distinct()
                stream_result = await session.execute(stream_stmt)
                stream_names = stream_result.scalars().all()

                results = {}
                for stream_name in stream_names:
                    events = await store.read_stream(stream_name, limit=1000000)
                    is_valid, broken_at, _ = await hash_builder.verify_chain(events)
                    results[stream_name] = {"is_valid": is_valid, "broken_at_sequence": broken_at}
                    if self._metrics_enabled:
                        hash_chain_valid.labels(stream_name=stream_name).set(1 if is_valid else 0)
                    if not is_valid:
                        logger.warning(f"Hash chain invalid for stream {stream_name} at {broken_at}")
                return results
        except Exception as e:
            logger.error(f"Failed to check hash chain integrity: {e}")
            return {"error": str(e)}

    async def start_periodic_collection(self, interval_seconds: int = DEFAULT_COLLECTION_INTERVAL_SECONDS) -> None:
        if self._running:
            return
        self._running = True
        self._collection_task = asyncio.create_task(self._periodic_collection_loop(interval_seconds))
        logger.info(f"Started periodic metrics collection every {interval_seconds} seconds")

    async def _periodic_collection_loop(self, interval_seconds: int) -> None:
        while self._running:
            try:
                await self.collect_metrics()
                await self.check_hash_chain_integrity()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic metrics collection: {e}")
            await asyncio.sleep(interval_seconds)

    async def stop_periodic_collection(self) -> None:
        self._running = False
        if self._collection_task:
            self._collection_task.cancel()
            try:
                await self._collection_task
            except asyncio.CancelledError:
                pass
            self._collection_task = None
        logger.info("Stopped periodic metrics collection")

    async def record_append(self, stream_name: str, event_type: str, size_bytes: int, duration_seconds: float) -> None:
        if self._metrics_enabled:
            events_appended_total.labels(stream_name=stream_name, event_type=event_type).inc()
            events_appended_bytes.labels(stream_name=stream_name).inc(size_bytes)
            append_latency.observe(duration_seconds)
            last_append_timestamp.set(time.time())

    async def record_read(self, stream_name: str, duration_seconds: float) -> None:
        if self._metrics_enabled:
            read_latency.observe(duration_seconds)

    async def record_snapshot_save(self, duration_seconds: float) -> None:
        if self._metrics_enabled:
            snapshot_save_latency.observe(duration_seconds)

    async def record_snapshot_load(self, duration_seconds: float) -> None:
        if self._metrics_enabled:
            snapshot_load_latency.observe(duration_seconds)

    async def record_error(self, error_type: str) -> None:
        if self._metrics_enabled:
            errors_total.labels(error_type=error_type).inc()

    async def get_metrics_report(self) -> dict[str, Any]:
        metrics = await self.collect_metrics()
        integrity = await self.check_hash_chain_integrity()
        total_streams = len(integrity)
        valid_streams = sum(1 for v in integrity.values() if v.get("is_valid", False))
        report = {
            "timestamp": datetime.now(UTC).isoformat(),
            "event_store": {
                "total_events": metrics.get("total_events", 0),
                "total_streams": metrics.get("total_streams", 0),
                "storage_size_mb": metrics.get("storage_size_bytes", 0) / (1024 * 1024),
                "events_per_second": metrics.get("events_per_second", 0),
                "collection_duration_seconds": metrics.get("collection_duration_seconds", 0),
            },
            "integrity": {
                "total_streams_checked": total_streams,
                "valid_streams": valid_streams,
                "invalid_streams": total_streams - valid_streams,
            },
            "snapshots": metrics.get("snapshot_stats", {}),
        }
        invalid_streams = [
            {"stream_name": name, "broken_at": v.get("broken_at_sequence")}
            for name, v in integrity.items()
            if not v.get("is_valid", False)
        ]
        if invalid_streams:
            report["integrity"]["invalid_streams_detail"] = invalid_streams[:20]
        return report


_metrics_collector: EventStoreMetricsCollector | None = None

async def get_metrics_collector() -> EventStoreMetricsCollector:
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = EventStoreMetricsCollector()
    return _metrics_collector

async def get_metrics_collector_dep():
    return await get_metrics_collector()

__all__ = ["EventStoreMetricsCollector", "get_metrics_collector", "get_metrics_collector_dep"]