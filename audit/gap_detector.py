#!/usr/bin/env python3
"""
Module: gap_detector.py
Layer: Audit
Responsibility: Mendeteksi gaps (kehilangan event) dalam event store sequence.
               Memeriksa apakah ada sequence number yang terlewat dalam suatu stream.
               Gaps dapat terjadi karena kegagalan sistem atau percobaan penghapusan.
               Juga mendeteksi gaps dalam waktu (timestamp anomali).
Dependencies:
- asyncio, logging, datetime
- infrastructure.event_store.append_only_store (AppendOnlyStore)
- infrastructure.telemetry.structured_json_logging
- infrastructure.telemetry.alert_manager_router
Audit: Setiap gap yang terdeteksi dicatat dan memicu alert.
"""

from __future__ import annotations

import asyncio
import importlib
from datetime import UTC, datetime
from typing import Any

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_CONFIG = {
    "enabled": True,
    "scan_interval_seconds": 3600,
    "max_allowed_gap": 100,  # Maximum gap size before alert
    "alert_on_gap": True,
    "streams_to_scan": [],  # Empty = all streams
}

_logger = None


def _get_logger():
    """Lazy logger initialization."""
    global _logger
    if _logger is None:
        mod = importlib.import_module("infrastructure.telemetry.structured_json_logging")
        get_logger_func = mod.get_logger
        _logger = get_logger_func(__name__)
    return _logger


# ============================================================================
# EXCEPTIONS
# ============================================================================


class GapDetectionError(Exception):
    """Base exception untuk gap detector."""

    pass


# ============================================================================
# GAP DETECTOR
# ============================================================================


class GapDetector:
    """
    Detektor untuk gaps dalam event store.

    Fitur:
    - Mendeteksi sequence number gaps per stream
    - Mendeteksi timestamp gaps (lompatan waktu yang tidak wajar)
    - Mendukung scanning periodik
    - Alert untuk gaps yang terdeteksi
    - Gap report generation
    """

    def __init__(self, config_path: str = "config_files/audit_config.yaml"):
        self.config = self._load_config(config_path)
        self._enabled = self.config.get("enabled", True)
        self._scan_interval = self.config.get("scan_interval_seconds", 3600)
        self._max_allowed_gap = self.config.get("max_allowed_gap", 100)
        self._alert_on_gap = self.config.get("alert_on_gap", True)
        self._streams_to_scan = self.config.get("streams_to_scan", [])

        self._event_store = None
        self._scan_task: asyncio.Task | None = None
        self._running = False
        self._last_scan: datetime | None = None
        self._detected_gaps: list[dict] = []

    def _load_config(self, config_path: str) -> dict[str, Any]:
        try:
            # Lazy import config loader
            mod = importlib.import_module("config.loader_yaml")
            load_yaml_config = mod.load_yaml_config
            config = load_yaml_config(config_path)
            gap_config = config.get("gap_detector", {})
            result = DEFAULT_CONFIG.copy()
            result.update(gap_config)
            return result
        except Exception:
            return DEFAULT_CONFIG.copy()

    async def _get_event_store(self):
        if self._event_store is None:
            mod = importlib.import_module("infrastructure.event_store.append_only_store")
            get_event_store = mod.get_event_store
            self._event_store = await get_event_store()
        return self._event_store

    async def detect_sequence_gaps(self, stream_name: str) -> list[dict[str, Any]]:
        """
        Detect sequence number gaps in a stream.

        Args:
            stream_name: Name of the stream to scan

        Returns:
            List of detected gaps (each with expected_sequence, actual_sequence, gap_size)
        """
        store = await self._get_event_store()
        events = await store.read_stream(stream_name, limit=1000000)

        gaps = []
        if not events:
            return gaps

        expected_seq = events[0].get("sequence_number", 1)

        for i, event in enumerate(events):
            actual_seq = event.get("sequence_number", i + 1)

            if actual_seq != expected_seq:
                gap_size = actual_seq - expected_seq
                gaps.append(
                    {
                        "stream_name": stream_name,
                        "position": i,
                        "expected_sequence": expected_seq,
                        "actual_sequence": actual_seq,
                        "gap_size": gap_size,
                        "detected_at": datetime.now(UTC).isoformat(),
                        "event_id": event.get("id"),
                    }
                )
                expected_seq = actual_seq + 1
            else:
                expected_seq += 1

        return gaps

    async def detect_timestamp_gaps(
        self, stream_name: str, max_gap_seconds: int = 3600
    ) -> list[dict[str, Any]]:
        """
        Detect timestamp gaps (unusual time jumps) in a stream.

        Args:
            stream_name: Name of the stream
            max_gap_seconds: Maximum allowed gap between consecutive events (seconds)

        Returns:
            List of detected timestamp gaps
        """
        store = await self._get_event_store()
        events = await store.read_stream(stream_name, limit=1000000)

        gaps = []
        last_timestamp = None

        for i, event in enumerate(events):
            timestamp_str = event.get("timestamp")
            if not timestamp_str:
                continue

            try:
                current_ts = datetime.fromisoformat(timestamp_str)
            except (ValueError, TypeError):
                continue

            if last_timestamp:
                gap_seconds = (current_ts - last_timestamp).total_seconds()
                if gap_seconds > max_gap_seconds:
                    gaps.append(
                        {
                            "stream_name": stream_name,
                            "position": i,
                            "previous_timestamp": last_timestamp.isoformat(),
                            "current_timestamp": current_ts.isoformat(),
                            "gap_seconds": gap_seconds,
                            "event_id": event.get("id"),
                        }
                    )

            last_timestamp = current_ts

        return gaps

    async def scan_all_streams(self) -> dict[str, Any]:
        """
        Scan all streams for gaps.

        Returns:
            Summary of scan results
        """
        store = await self._get_event_store()

        # Lazy import SQLAlchemy and ORM table
        sqlalchemy_mod = importlib.import_module("sqlalchemy")
        select = sqlalchemy_mod.select
        orm_mod = importlib.import_module("infrastructure.persistence_orm.event_store_table")
        EventStoreTable = orm_mod.EventStoreTable

        # Get all streams
        session_factory = store._session_factory
        async with session_factory() as session:
            if self._streams_to_scan:
                stream_names = self._streams_to_scan
            else:
                stmt = select(EventStoreTable.stream_name).distinct()
                result = await session.execute(stmt)
                stream_names = result.scalars().all()

        total_sequence_gaps = 0
        total_timestamp_gaps = 0
        all_sequence_gaps = []
        all_timestamp_gaps = []

        for stream_name in stream_names:
            # Sequence gaps
            seq_gaps = await self.detect_sequence_gaps(stream_name)
            if seq_gaps:
                total_sequence_gaps += len(seq_gaps)
                all_sequence_gaps.extend(seq_gaps)
                if self._alert_on_gap:
                    for gap in seq_gaps:
                        if gap["gap_size"] > self._max_allowed_gap:
                            await self._send_gap_alert(gap, "sequence")

            # Timestamp gaps
            ts_gaps = await self.detect_timestamp_gaps(stream_name)
            if ts_gaps:
                total_timestamp_gaps += len(ts_gaps)
                all_timestamp_gaps.extend(ts_gaps)
                if self._alert_on_gap:
                    for gap in ts_gaps:
                        await self._send_gap_alert(gap, "timestamp")

        # Store detected gaps
        self._detected_gaps = all_sequence_gaps + all_timestamp_gaps
        self._last_scan = datetime.now(UTC)

        result = {
            "scan_timestamp": self._last_scan.isoformat(),
            "streams_scanned": len(stream_names),
            "sequence_gaps_found": total_sequence_gaps,
            "timestamp_gaps_found": total_timestamp_gaps,
            "sequence_gaps": all_sequence_gaps[:100],  # Limit output
            "timestamp_gaps": all_timestamp_gaps[:100],
        }

        logger = _get_logger()
        logger.info(
            f"Gap detection scan completed: {total_sequence_gaps} sequence gaps, {total_timestamp_gaps} timestamp gaps"
        )

        # Trigger alert for large number of gaps
        if total_sequence_gaps > 100 or total_timestamp_gaps > 100:
            alert_mod = importlib.import_module("infrastructure.telemetry.alert_manager_router")
            trigger_alert = alert_mod.trigger_alert
            await trigger_alert(
                title="Large Number of Gaps Detected",
                message=f"Scan found {total_sequence_gaps} sequence gaps and {total_timestamp_gaps} timestamp gaps",
                severity="warning",
                source="GapDetector",
            )

        return result

    async def _send_gap_alert(self, gap: dict, gap_type: str) -> None:
        """
        Send alert for a detected gap.
        """
        alert_mod = importlib.import_module("infrastructure.telemetry.alert_manager_router")
        trigger_alert = alert_mod.trigger_alert

        if gap_type == "sequence":
            title = f"Sequence Gap Detected in {gap['stream_name']}"
            message = (
                f"Sequence gap: expected {gap['expected_sequence']}, "
                f"got {gap['actual_sequence']} (gap size: {gap['gap_size']})"
            )
        else:
            title = f"Timestamp Gap Detected in {gap['stream_name']}"
            message = (
                f"Timestamp gap of {gap['gap_seconds']:.0f} seconds "
                f"between {gap['previous_timestamp']} and {gap['current_timestamp']}"
            )

        await trigger_alert(
            title=title, message=message, severity="warning", source="GapDetector", metadata=gap
        )

    async def start_periodic_scan(self) -> None:
        """Start periodic gap detection scanning."""
        if not self._enabled:
            logger = _get_logger()
            logger.info("Gap detector is disabled")
            return

        if self._running:
            logger = _get_logger()
            logger.warning("Gap detector already running")
            return

        self._running = True

        async def _scan_loop():
            while self._running:
                try:
                    await self.scan_all_streams()
                    await asyncio.sleep(self._scan_interval)
                except asyncio.CancelledError:
                    logger = _get_logger()
                    logger.debug("Gap detector scan loop cancelled")
                    break
                except Exception as e:
                    logger = _get_logger()
                    logger.error(f"Gap detection error: {e}")
                    await asyncio.sleep(60)

        self._scan_task = asyncio.create_task(_scan_loop())
        logger = _get_logger()
        logger.info(f"Gap detector started (interval: {self._scan_interval}s)")

    async def stop_periodic_scan(self) -> None:
        """Stop periodic gap detection scanning."""
        self._running = False
        if self._scan_task:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                logger = _get_logger()
                logger.debug("Gap detector scan task cancelled during stop")
                # Expected cancellation; swallow after logging
            self._scan_task = None
        logger = _get_logger()
        logger.info("Gap detector stopped")

    async def get_gaps(self) -> list[dict]:
        """Get all detected gaps from last scan."""
        return self._detected_gaps

    async def get_status(self) -> dict[str, Any]:
        """Get status of gap detector."""
        return {
            "enabled": self._enabled,
            "running": self._running,
            "last_scan": self._last_scan.isoformat() if self._last_scan else None,
            "detected_gaps_count": len(self._detected_gaps),
            "max_allowed_gap": self._max_allowed_gap,
            "scan_interval_seconds": self._scan_interval,
        }


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_gap_detector: GapDetector | None = None


async def get_gap_detector() -> GapDetector:
    """Get singleton instance of GapDetector."""
    global _gap_detector
    if _gap_detector is None:
        _gap_detector = GapDetector()
    return _gap_detector


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["GapDetectionError", "GapDetector", "get_gap_detector"]
