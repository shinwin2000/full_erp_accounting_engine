#!/usr/bin/env python3
"""
Module: audit_chain_length_metrics.py
Layer: Infrastructure (Telemetry)
Responsibility: Mengumpulkan dan mengekspor metrik tentang panjang hash chain
               audit trail.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from infrastructure.event_store.hash_chain_builder import HashChainBuilder, get_hash_chain_builder
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.prometheus_registry import get_gauge
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

METRIC_PREFIX = "audit_chain"
NAMESPACE = "erp"
COLLECTION_INTERVAL_SECONDS = 3600
CHAIN_BROKEN_ALERT = "chain_broken"
STREAM_SIZE_WARNING = 100000
STREAM_SIZE_CRITICAL = 500000
TOTAL_EVENTS_WARNING = 10000000

# ============================================================================
# METRICS
# ============================================================================

chain_length = get_gauge(
    f"{METRIC_PREFIX}_length", "Number of events in hash chain", ["stream_name"]
)
total_events = get_gauge(f"{METRIC_PREFIX}_total_events", "Total number of events in event store")
total_streams = get_gauge(f"{METRIC_PREFIX}_total_streams", "Total number of streams")
chain_integrity = get_gauge(
    f"{METRIC_PREFIX}_integrity",
    "Hash chain integrity status (1=valid, 0=invalid)",
    ["stream_name"],
)
last_event_timestamp = get_gauge(
    f"{METRIC_PREFIX}_last_event_timestamp_seconds",
    "Timestamp of last event in stream (Unix timestamp)",
    ["stream_name"],
)
chain_growth_rate = get_gauge(
    f"{METRIC_PREFIX}_growth_rate_per_hour", "Chain growth rate (events per hour)", ["stream_name"]
)
oldest_event_age_days = get_gauge(
    f"{METRIC_PREFIX}_oldest_event_age_days", "Age of oldest event in days", ["stream_name"]
)


# ============================================================================
# METRICS COLLECTOR
# ============================================================================


class AuditChainLengthMetrics:
    def __init__(self):
        self._event_store = None
        self._hash_builder: HashChainBuilder | None = None
        self._previous_lengths: dict[str, int] = {}
        self._previous_collection_time: datetime | None = None
        self._collection_task: asyncio.Task | None = None
        self._running = False

    async def _get_event_store(self):
        if self._event_store is None:
            from infrastructure.event_store.append_only_store import get_event_store
            self._event_store = await get_event_store()
        return self._event_store

    async def _get_hash_builder(self) -> HashChainBuilder:
        if self._hash_builder is None:
            self._hash_builder = get_hash_chain_builder()
        return self._hash_builder

    async def collect_stream_metrics(self, stream_name: str) -> dict[str, Any]:
        store = await self._get_event_store()
        hash_builder = await self._get_hash_builder()
        try:
            events = await store.read_stream(stream_name, limit=1000000)
            event_count = len(events)
            is_valid, broken_at, error = await hash_builder.verify_chain(events)

            last_event_ts = None
            if events:
                last_event = events[-1]
                timestamp_str = last_event.get("timestamp")
                if timestamp_str:
                    try:
                        if isinstance(timestamp_str, str):
                            last_event_ts = datetime.fromisoformat(timestamp_str).timestamp()
                        else:
                            last_event_ts = timestamp_str.timestamp()
                    except (ValueError, AttributeError):
                        pass

            oldest_age_days = None
            if events:
                first_event = events[0]
                timestamp_str = first_event.get("timestamp")
                if timestamp_str:
                    try:
                        if isinstance(timestamp_str, str):
                            first_ts = datetime.fromisoformat(timestamp_str)
                        else:
                            first_ts = timestamp_str
                        oldest_age_days = (datetime.now(UTC) - first_ts).days
                    except (ValueError, AttributeError):
                        pass

            chain_length.labels(stream_name=stream_name).set(event_count)
            chain_integrity.labels(stream_name=stream_name).set(1 if is_valid else 0)
            if last_event_ts:
                last_event_timestamp.labels(stream_name=stream_name).set(last_event_ts)
            if oldest_age_days is not None:
                oldest_event_age_days.labels(stream_name=stream_name).set(oldest_age_days)

            growth_rate = await self._calculate_growth_rate(stream_name, event_count)
            if growth_rate is not None:
                chain_growth_rate.labels(stream_name=stream_name).set(growth_rate)

            if not is_valid:
                await trigger_alert(
                    title="Audit Chain Integrity Violation",
                    message=f"Stream {stream_name} has broken hash chain at sequence {broken_at}",
                    severity="critical",
                    source="AuditChainLengthMetrics",
                )
            if event_count > STREAM_SIZE_CRITICAL:
                await trigger_alert(
                    title="Audit Chain Size Critical",
                    message=f"Stream {stream_name} has {event_count:,} events (critical threshold: {STREAM_SIZE_CRITICAL:,})",
                    severity="critical",
                    source="AuditChainLengthMetrics",
                )
            elif event_count > STREAM_SIZE_WARNING:
                await trigger_alert(
                    title="Audit Chain Size Warning",
                    message=f"Stream {stream_name} has {event_count:,} events (warning threshold: {STREAM_SIZE_WARNING:,})",
                    severity="warning",
                    source="AuditChainLengthMetrics",
                )

            return {
                "stream_name": stream_name,
                "event_count": event_count,
                "is_valid": is_valid,
                "broken_at_sequence": broken_at if not is_valid else None,
                "last_event_timestamp": last_event_ts,
                "oldest_event_age_days": oldest_age_days,
                "growth_rate": growth_rate,
            }
        except Exception as e:
            logger.error(f"Failed to collect metrics for stream {stream_name}: {e}")
            return {"stream_name": stream_name, "error": str(e)}

    async def _calculate_growth_rate(self, stream_name: str, current_length: int) -> float | None:
        if stream_name in self._previous_lengths and self._previous_collection_time:
            prev_length = self._previous_lengths[stream_name]
            delta_events = current_length - prev_length
            delta_time_hours = (
                datetime.now(UTC) - self._previous_collection_time
            ).total_seconds() / 3600
            if delta_time_hours > 0:
                return delta_events / delta_time_hours
        return None

    async def collect_all_streams(self) -> dict[str, Any]:
        store = await self._get_event_store()
        try:
            async with store._session_factory() as session:
                from infrastructure.persistence_orm.event_store_table import EventStoreTable
                stmt = select(EventStoreTable.stream_name).distinct()
                result = await session.execute(stmt)
                stream_names = result.scalars().all()

            total_events = 0
            results = []
            for stream_name in stream_names:
                metrics = await self.collect_stream_metrics(stream_name)
                results.append(metrics)
                if "event_count" in metrics:
                    total_events += metrics["event_count"]

            total_events_gauge.set(total_events)
            total_streams_gauge.set(len(stream_names))

            self._previous_lengths = {
                r["stream_name"]: r.get("event_count", 0) for r in results if "stream_name" in r
            }
            self._previous_collection_time = datetime.now(UTC)

            if total_events > TOTAL_EVENTS_WARNING:
                await trigger_alert(
                    title="Event Store Size Warning",
                    message=f"Total events in event store: {total_events:,} (warning threshold: {TOTAL_EVENTS_WARNING:,})",
                    severity="warning",
                    source="AuditChainLengthMetrics",
                )

            return {
                "total_events": total_events,
                "total_streams": len(stream_names),
                "streams": results,
            }
        except Exception as e:
            logger.error(f"Failed to collect metrics for all streams: {e}")
            return {"error": str(e)}

    async def start_periodic_collection(
        self, interval_seconds: int = COLLECTION_INTERVAL_SECONDS
    ) -> None:
        if self._running:
            return
        self._running = True
        self._collection_task = asyncio.create_task(
            self._periodic_collection_loop(interval_seconds)
        )
        logger.info(f"Started periodic audit chain metrics collection every {interval_seconds} seconds")

    async def _periodic_collection_loop(self, interval_seconds: int) -> None:
        while self._running:
            try:
                await self.collect_all_streams()
            except asyncio.CancelledError:
                logger.debug("Periodic audit chain collection loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in periodic audit chain collection: {e}")
            await asyncio.sleep(interval_seconds)

    async def stop_periodic_collection(self) -> None:
        self._running = False
        if self._collection_task:
            self._collection_task.cancel()
            try:
                await self._collection_task
            except asyncio.CancelledError:
                logger.debug("Audit chain collection task cancelled during stop")
            self._collection_task = None
        logger.info("Stopped periodic audit chain metrics collection")

    async def get_status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "previous_collection_time": self._previous_collection_time.isoformat()
            if self._previous_collection_time
            else None,
            "collection_interval_seconds": COLLECTION_INTERVAL_SECONDS,
            "stream_size_warning": STREAM_SIZE_WARNING,
            "stream_size_critical": STREAM_SIZE_CRITICAL,
            "total_events_warning": TOTAL_EVENTS_WARNING,
        }

    async def force_collection(self) -> dict[str, Any]:
        return await self.collect_all_streams()


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_audit_chain_metrics: AuditChainLengthMetrics | None = None

async def get_audit_chain_metrics() -> AuditChainLengthMetrics:
    global _audit_chain_metrics
    if _audit_chain_metrics is None:
        _audit_chain_metrics = AuditChainLengthMetrics()
    return _audit_chain_metrics

async def start_audit_chain_collection() -> None:
    collector = await get_audit_chain_metrics()
    await collector.start_periodic_collection()

async def stop_audit_chain_collection() -> None:
    global _audit_chain_metrics
    if _audit_chain_metrics:
        await _audit_chain_metrics.stop_periodic_collection()
        _audit_chain_metrics = None

__all__ = [
    "AuditChainLengthMetrics",
    "get_audit_chain_metrics",
    "start_audit_chain_collection",
    "stop_audit_chain_collection",
]