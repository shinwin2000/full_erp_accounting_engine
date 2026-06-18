#!/usr/bin/env python3
"""
Module: tamper_detection_scanner.py
Layer: Infrastructure (Event Store)
Responsibility: Memindai event store untuk mendeteksi tampering.
               Tidak mengimpor append_only_store. Menerima instance event store
               dari luar (dependency injection).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from infrastructure.event_store.hash_chain_builder import get_hash_chain_builder
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

DEFAULT_MAX_GAP_SIZE = 5

SCAN_TYPE_FULL = "full"
SCAN_TYPE_INCREMENTAL = "incremental"
SCAN_TYPE_STREAM = "stream"

ALERT_SEVERITY_CRITICAL = "critical"
ALERT_SEVERITY_WARNING = "warning"


class TamperDetectionError(Exception):
    pass


class ScanInterruptedError(TamperDetectionError):
    pass


class TamperDetectionResult:
    __slots__ = (
        "anomalies",
        "anomalies_found",
        "end_time",
        "events_scanned",
        "is_clean",
        "scan_id",
        "scan_type",
        "start_time",
        "streams_scanned",
    )

    def __init__(self, scan_id: UUID, scan_type: str):
        self.scan_id = scan_id
        self.scan_type = scan_type
        self.start_time = datetime.now(UTC)
        self.end_time: datetime | None = None
        self.streams_scanned: int = 0
        self.events_scanned: int = 0
        self.anomalies_found: int = 0
        self.anomalies: list[dict[str, Any]] = []
        self.is_clean: bool = True

    def add_anomaly(
        self,
        anomaly_type: str,
        stream_name: str,
        sequence: int | None,
        details: dict[str, Any],
        severity: str = ALERT_SEVERITY_WARNING,
    ) -> None:
        self.anomalies.append(
            {
                "anomaly_type": anomaly_type,
                "stream_name": stream_name,
                "sequence": sequence,
                "details": details,
                "severity": severity,
                "detected_at": datetime.now(UTC).isoformat(),
            }
        )
        self.anomalies_found += 1
        self.is_clean = False

    def finish(self) -> None:
        self.end_time = datetime.now(UTC)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scan_id": str(self.scan_id),
            "scan_type": self.scan_type,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": (self.end_time - self.start_time).total_seconds()
            if self.end_time
            else None,
            "streams_scanned": self.streams_scanned,
            "events_scanned": self.events_scanned,
            "anomalies_found": self.anomalies_found,
            "anomalies": self.anomalies,
            "is_clean": self.is_clean,
        }


class TamperDetectionScanner:
    def __init__(self, event_store):
        """
        Args:
            event_store: Instance dari AppendOnlyStore (diberikan dari luar).
        """
        self._event_store = event_store
        self._hash_builder = get_hash_chain_builder()
        self._last_scan_results: dict[str, Any] = {}
        self._scan_history: list[TamperDetectionResult] = []

    async def scan_full(self) -> TamperDetectionResult:
        scan_id = uuid4()
        result = TamperDetectionResult(scan_id, SCAN_TYPE_FULL)
        logger.info(f"Starting full tamper detection scan: {scan_id}")
        try:
            # Get all stream names
            async with self._event_store._session_factory() as session:
                from sqlalchemy import select

                from infrastructure.persistence_orm.event_store_table import EventStoreTable

                stmt = select(EventStoreTable.stream_name).distinct()
                db_result = await session.execute(stmt)
                stream_names = db_result.scalars().all()

            result.streams_scanned = len(stream_names)

            for stream_name in stream_names:
                events = await self._event_store.read_stream(stream_name, limit=1000000)
                result.events_scanned += len(events)

                gap_anomalies = await self._detect_gaps(events, stream_name)
                for anomaly in gap_anomalies:
                    result.add_anomaly(
                        anomaly_type="sequence_gap",
                        stream_name=stream_name,
                        sequence=anomaly.get("missing_sequence"),
                        details=anomaly,
                        severity=ALERT_SEVERITY_WARNING,
                    )

                is_valid, broken_at, error = await self._hash_builder.verify_chain(events)
                if not is_valid:
                    result.add_anomaly(
                        anomaly_type="hash_chain_broken",
                        stream_name=stream_name,
                        sequence=broken_at,
                        details={"error": error, "broken_at_sequence": broken_at},
                        severity=ALERT_SEVERITY_CRITICAL,
                    )

                ts_anomalies = await self._detect_timestamp_anomalies(events, stream_name)
                for anomaly in ts_anomalies:
                    result.add_anomaly(
                        anomaly_type="timestamp_anomaly",
                        stream_name=stream_name,
                        sequence=anomaly.get("sequence"),
                        details=anomaly,
                        severity=ALERT_SEVERITY_WARNING,
                    )

            result.finish()
            self._last_scan_results["full"] = result.to_dict()
            self._scan_history.append(result)

            if result.anomalies_found > 0:
                await trigger_alert(
                    title="Tamper Detection Scan Completed with Anomalies",
                    message=f"Full scan {scan_id} found {result.anomalies_found} anomalies in {result.streams_scanned} streams",
                    severity=ALERT_SEVERITY_CRITICAL
                    if result.anomalies_found > 5
                    else ALERT_SEVERITY_WARNING,
                    source="TamperDetectionScanner",
                )
            else:
                logger.info(
                    f"Full scan {scan_id} completed: {result.events_scanned} events, no anomalies"
                )
            return result
        except Exception as e:
            logger.exception(f"Full scan failed: {e}")
            raise TamperDetectionError(f"Full scan failed: {e}") from e

    async def scan_incremental(self, since: datetime | None = None) -> TamperDetectionResult:
        if since is None:
            last_scan = self._last_scan_results.get("full", {}).get("end_time")
            if last_scan:
                since = datetime.fromisoformat(last_scan)
            else:
                since = datetime.now(UTC) - timedelta(days=1)
        scan_id = uuid4()
        result = TamperDetectionResult(scan_id, SCAN_TYPE_INCREMENTAL)
        logger.info(f"Starting incremental tamper detection scan since {since.isoformat()}")

        try:
            events = await self._event_store.search_events(start_time=since, limit=1000000)
            result.events_scanned = len(events)

            events_by_stream: dict[str, list] = {}
            for event in events:
                stream = event.get("stream_name", "unknown")
                if stream not in events_by_stream:
                    events_by_stream[stream] = []
                events_by_stream[stream].append(event)

            result.streams_scanned = len(events_by_stream)

            for stream_name, stream_events in events_by_stream.items():
                last_event_before = await self._event_store.get_last_event(stream_name)
                if last_event_before:
                    full_events = [last_event_before] + stream_events
                    is_valid, broken_at, error = await self._hash_builder.verify_chain(full_events)
                    if not is_valid:
                        result.add_anomaly(
                            anomaly_type="hash_chain_broken",
                            stream_name=stream_name,
                            sequence=broken_at,
                            details={"error": error},
                            severity=ALERT_SEVERITY_CRITICAL,
                        )

            result.finish()
            self._last_scan_results["incremental"] = result.to_dict()
            self._scan_history.append(result)
            logger.info(f"Incremental scan {scan_id} completed: {result.events_scanned} events")
            return result
        except Exception as e:
            logger.exception(f"Incremental scan failed: {e}")
            raise TamperDetectionError(f"Incremental scan failed: {e}") from e

    async def scan_stream(self, stream_name: str) -> TamperDetectionResult:
        scan_id = uuid4()
        result = TamperDetectionResult(scan_id, SCAN_TYPE_STREAM)
        logger.info(f"Starting stream scan for {stream_name}: {scan_id}")

        try:
            events = await self._event_store.read_stream(stream_name, limit=1000000)
            result.streams_scanned = 1
            result.events_scanned = len(events)

            gap_anomalies = await self._detect_gaps(events, stream_name)
            for anomaly in gap_anomalies:
                result.add_anomaly(
                    anomaly_type="sequence_gap",
                    stream_name=stream_name,
                    sequence=anomaly.get("missing_sequence"),
                    details=anomaly,
                    severity=ALERT_SEVERITY_WARNING,
                )

            is_valid, broken_at, error = await self._hash_builder.verify_chain(events)
            if not is_valid:
                result.add_anomaly(
                    anomaly_type="hash_chain_broken",
                    stream_name=stream_name,
                    sequence=broken_at,
                    details={"error": error},
                    severity=ALERT_SEVERITY_CRITICAL,
                )

            ts_anomalies = await self._detect_timestamp_anomalies(events, stream_name)
            for anomaly in ts_anomalies:
                result.add_anomaly(
                    anomaly_type="timestamp_anomaly",
                    stream_name=stream_name,
                    sequence=anomaly.get("sequence"),
                    details=anomaly,
                    severity=ALERT_SEVERITY_WARNING,
                )

            result.finish()
            self._scan_history.append(result)
            logger.info(f"Stream scan for {stream_name} completed: {result.events_scanned} events")
            return result
        except Exception as e:
            logger.exception(f"Stream scan failed for {stream_name}: {e}")
            raise TamperDetectionError(f"Stream scan failed: {e}") from e

    async def _detect_gaps(self, events: list[dict], stream_name: str) -> list[dict[str, Any]]:
        anomalies = []
        if not events:
            return anomalies
        expected_seq = events[0].get("sequence_number", 1)
        for i, event in enumerate(events):
            actual_seq = event.get("sequence_number", i + 1)
            if actual_seq != expected_seq:
                gap_size = actual_seq - expected_seq
                if gap_size > DEFAULT_MAX_GAP_SIZE:
                    anomalies.append(
                        {
                            "type": "large_gap",
                            "expected_sequence": expected_seq,
                            "actual_sequence": actual_seq,
                            "gap_size": gap_size,
                            "position": i,
                        }
                    )
                else:
                    anomalies.append(
                        {
                            "type": "small_gap",
                            "expected_sequence": expected_seq,
                            "actual_sequence": actual_seq,
                            "gap_size": gap_size,
                            "position": i,
                        }
                    )
            expected_seq = actual_seq + 1
        return anomalies

    async def _detect_timestamp_anomalies(
        self, events: list[dict], stream_name: str
    ) -> list[dict[str, Any]]:
        anomalies = []
        if len(events) < 2:
            return anomalies
        last_timestamp = None
        now = datetime.now(UTC)
        ten_years_ago = now - timedelta(days=3650)
        for i, event in enumerate(events):
            timestamp_str = event.get("timestamp")
            if not timestamp_str:
                continue
            try:
                if isinstance(timestamp_str, str):
                    timestamp = datetime.fromisoformat(timestamp_str)
                else:
                    timestamp = timestamp_str
            except (ValueError, TypeError):
                anomalies.append(
                    {
                        "type": "invalid_timestamp",
                        "sequence": event.get("sequence_number", i + 1),
                        "timestamp": str(timestamp_str),
                        "position": i,
                    }
                )
                continue
            if last_timestamp and timestamp < last_timestamp:
                time_diff = (last_timestamp - timestamp).total_seconds()
                anomalies.append(
                    {
                        "type": "decreasing_timestamp",
                        "sequence": event.get("sequence_number", i + 1),
                        "previous_timestamp": last_timestamp.isoformat(),
                        "current_timestamp": timestamp.isoformat(),
                        "difference_seconds": time_diff,
                        "position": i,
                    }
                )
            if timestamp > now + timedelta(days=1):
                anomalies.append(
                    {
                        "type": "future_timestamp",
                        "sequence": event.get("sequence_number", i + 1),
                        "timestamp": timestamp.isoformat(),
                        "current_time": now.isoformat(),
                        "days_ahead": (timestamp - now).days,
                        "position": i,
                    }
                )
            if timestamp < ten_years_ago:
                anomalies.append(
                    {
                        "type": "very_old_timestamp",
                        "sequence": event.get("sequence_number", i + 1),
                        "timestamp": timestamp.isoformat(),
                        "age_years": (now - timestamp).days / 365,
                        "position": i,
                    }
                )
            last_timestamp = timestamp
        return anomalies

    async def get_last_scan_result(self, scan_type: str | None = None) -> dict[str, Any] | None:
        if scan_type:
            return self._last_scan_results.get(scan_type)
        if self._scan_history:
            return self._scan_history[-1].to_dict()
        return None

    async def get_scan_history(self, limit: int = 10) -> list[dict[str, Any]]:
        return [result.to_dict() for result in self._scan_history[-limit:]]

    async def clear_history(self) -> None:
        self._scan_history.clear()
        self._last_scan_results.clear()
        logger.info("Tamper detection scan history cleared")

    async def get_health_status(self) -> dict[str, Any]:
        if not self._scan_history:
            return {"status": "unknown", "message": "No scans performed yet", "last_scan": None}
        last_scan = self._scan_history[-1]
        if last_scan.anomalies_found > 0:
            return {
                "status": "compromised",
                "message": f"Found {last_scan.anomalies_found} anomalies in last scan",
                "last_scan": last_scan.to_dict(),
            }
        return {
            "status": "healthy",
            "message": "No anomalies detected",
            "last_scan": last_scan.to_dict(),
        }


def get_tamper_scanner(event_store) -> TamperDetectionScanner:
    """Factory untuk mendapatkan scanner dengan event store yang diberikan."""
    return TamperDetectionScanner(event_store)


__all__ = [
    "ScanInterruptedError",
    "TamperDetectionError",
    "TamperDetectionResult",
    "TamperDetectionScanner",
    "get_tamper_scanner",
]
