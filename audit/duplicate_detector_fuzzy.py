#!/usr/bin/env python3
"""
Module: duplicate_detector_fuzzy.py
Layer: Audit
Responsibility: Mendeteksi kemungkinan duplikasi event atau transaksi dalam event store
               menggunakan fuzzy matching. Membandingkan event berdasarkan kesamaan
               konten, timestamp, dan metadata untuk mengidentifikasi event yang
               mungkin duplikat (misal karena retry atau kesalahan sistem).
Dependencies:
- asyncio, logging, hashlib, difflib
- infrastructure.event_store.append_only_store (AppendOnlyStore)
- infrastructure.telemetry.structured_json_logging
- infrastructure.telemetry.alert_manager_router
Audit: Duplikasi yang terdeteksi dicatat untuk investigasi.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from typing import Any

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_CONFIG = {
    "enabled": True,
    "similarity_threshold": 0.85,  # 85% similarity to consider duplicate
    "time_window_seconds": 300,  # Only compare events within 5 minutes
    "scan_interval_seconds": 7200,  # Scan every 2 hours
    "max_events_per_scan": 10000,
    "alert_on_duplicate": True,
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


class DuplicateDetectionError(Exception):
    """Base exception untuk duplicate detector."""

    pass


# ============================================================================
# DUPLICATE DETECTOR
# ============================================================================


class DuplicateDetectorFuzzy:
    """
    Detektor duplikasi event secara fuzzy.

    Fitur:
    - Membandingkan event berdasarkan similarity konten
    - Deteksi duplikat berdasarkan ID yang sama dalam window waktu
    - Fuzzy matching untuk event yang mirip tapi tidak persis sama
    - Periodic scanning
    - Alert untuk duplikasi yang terdeteksi
    """

    def __init__(self, config_path: str = "config_files/audit_config.yaml"):
        self.config = self._load_config(config_path)
        self._enabled = self.config.get("enabled", True)
        self._similarity_threshold = self.config.get("similarity_threshold", 0.85)
        self._time_window = self.config.get("time_window_seconds", 300)
        self._scan_interval = self.config.get("scan_interval_seconds", 7200)
        self._max_events = self.config.get("max_events_per_scan", 10000)
        self._alert_on_duplicate = self.config.get("alert_on_duplicate", True)

        self._event_store = None
        self._scan_task: asyncio.Task | None = None
        self._running = False
        self._detected_duplicates: list[dict] = []

    def _load_config(self, config_path: str) -> dict[str, Any]:
        try:
            # Lazy import config loader
            mod = importlib.import_module("config.loader_yaml")
            load_yaml_config = mod.load_yaml_config
            config = load_yaml_config(config_path)
            dup_config = config.get("duplicate_detector", {})
            result = DEFAULT_CONFIG.copy()
            result.update(dup_config)
            return result
        except Exception:
            return DEFAULT_CONFIG.copy()

    async def _get_event_store(self):
        if self._event_store is None:
            mod = importlib.import_module("infrastructure.event_store.append_only_store")
            get_event_store = mod.get_event_store
            self._event_store = await get_event_store()
        return self._event_store

    def _compute_content_hash(self, event: dict[str, Any]) -> str:
        """
        Compute hash of event content (excluding timestamp and id for fuzzy matching).
        """
        # Create a copy without id and timestamp for comparison
        content = {
            "event_type": event.get("event_type"),
            "data": event.get("data", {}),
            "metadata": {
                k: v
                for k, v in event.get("metadata", {}).items()
                if k not in ["timestamp", "correlation_id"]
            },
        }
        json_str = json.dumps(content, sort_keys=True, default=str)
        return hashlib.sha256(json_str.encode("utf-8")).hexdigest()

    def _calculate_similarity(self, event1: dict, event2: dict) -> float:
        """
        Calculate similarity between two events using multiple factors.
        """
        # Factor 1: Content hash similarity (0-0.5)
        hash1 = self._compute_content_hash(event1)
        hash2 = self._compute_content_hash(event2)
        content_similarity = 1.0 if hash1 == hash2 else 0.0

        # Factor 2: Event type match (0-0.2)
        type_match = 0.2 if event1.get("event_type") == event2.get("event_type") else 0.0

        # Factor 3: JSON structure similarity (0-0.3)
        try:
            data1 = json.dumps(event1.get("data", {}), sort_keys=True)
            data2 = json.dumps(event2.get("data", {}), sort_keys=True)
            structural_similarity = SequenceMatcher(None, data1, data2).ratio()
        except Exception:
            structural_similarity = 0.0

        total = content_similarity + type_match + (structural_similarity * 0.3)
        return min(total, 1.0)

    async def detect_duplicates_in_stream(self, stream_name: str) -> list[dict[str, Any]]:
        """
        Detect duplicate events within a stream.

        Args:
            stream_name: Name of the stream to scan

        Returns:
            List of detected duplicate groups
        """
        store = await self._get_event_store()
        events = await store.read_stream(stream_name, limit=self._max_events)

        if len(events) < 2:
            return []

        duplicates = []
        # Group events by content hash for quick initial grouping
        hash_groups: dict[str, list[dict]] = defaultdict(list)
        for event in events:
            content_hash = self._compute_content_hash(event)
            hash_groups[content_hash].append(event)

        # For each group, check if events are within time window and similar enough
        for content_hash, group_events in hash_groups.items():
            if len(group_events) < 2:
                continue

            # Sort by timestamp
            sorted_events = sorted(group_events, key=lambda e: e.get("timestamp", ""))
            window_start = datetime.now(UTC) - timedelta(seconds=self._time_window)

            # Check for duplicates within time window
            duplicate_group = []
            for i, event in enumerate(sorted_events):
                try:
                    ts = datetime.fromisoformat(event.get("timestamp"))
                    if ts > window_start:
                        duplicate_group.append(event)
                except (ValueError, TypeError):
                    continue

            if len(duplicate_group) >= 2:
                # Also check similarity score between first and others
                for dup in duplicate_group[1:]:
                    similarity = self._calculate_similarity(duplicate_group[0], dup)
                    if similarity >= self._similarity_threshold:
                        duplicates.append(
                            {
                                "stream_name": stream_name,
                                "duplicate_group": duplicate_group,
                                "detected_at": datetime.now(UTC).isoformat(),
                                "similarity_score": similarity,
                                "event_ids": [e.get("id") for e in duplicate_group],
                            }
                        )
                        break

        return duplicates

    async def scan_all_streams(self) -> dict[str, Any]:
        """
        Scan all streams for duplicate events.

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
            stmt = select(EventStoreTable.stream_name).distinct()
            result = await session.execute(stmt)
            stream_names = result.scalars().all()

        total_duplicates = 0
        all_duplicates = []

        for stream_name in stream_names:
            duplicates = await self.detect_duplicates_in_stream(stream_name)
            if duplicates:
                total_duplicates += len(duplicates)
                all_duplicates.extend(duplicates)

                if self._alert_on_duplicate:
                    for dup in duplicates:
                        await self._send_duplicate_alert(dup)

        self._detected_duplicates = all_duplicates

        result = {
            "scan_timestamp": datetime.now(UTC).isoformat(),
            "streams_scanned": len(stream_names),
            "duplicate_groups_found": total_duplicates,
            "duplicates": all_duplicates[:50],  # Limit output
        }

        logger = _get_logger()
        logger.info(
            f"Duplicate detection scan completed: {total_duplicates} duplicate groups found"
        )

        if total_duplicates > 10:
            # Lazy import alert manager
            alert_mod = importlib.import_module("infrastructure.telemetry.alert_manager_router")
            trigger_alert = alert_mod.trigger_alert
            await trigger_alert(
                title="High Number of Potential Duplicates Detected",
                message=f"Found {total_duplicates} potential duplicate event groups",
                severity="warning",
                source="DuplicateDetectorFuzzy",
            )

        return result

    async def _send_duplicate_alert(self, duplicate: dict) -> None:
        """Send alert for detected duplicate."""
        alert_mod = importlib.import_module("infrastructure.telemetry.alert_manager_router")
        trigger_alert = alert_mod.trigger_alert
        title = f"Potential Duplicate Events in {duplicate['stream_name']}"
        message = (
            f"Found {len(duplicate['duplicate_group'])} similar events with "
            f"similarity score {duplicate['similarity_score']:.2f}"
        )
        await trigger_alert(
            title=title,
            message=message,
            severity="warning",
            source="DuplicateDetectorFuzzy",
            metadata=duplicate,
        )

    async def start_periodic_scan(self) -> None:
        """Start periodic duplicate detection scanning."""
        if not self._enabled:
            logger = _get_logger()
            logger.info("Duplicate detector is disabled")
            return

        if self._running:
            logger = _get_logger()
            logger.warning("Duplicate detector already running")
            return

        self._running = True

        async def _scan_loop():
            while self._running:
                try:
                    await self.scan_all_streams()
                    await asyncio.sleep(self._scan_interval)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger = _get_logger()
                    logger.error(f"Duplicate detection error: {e}")
                    await asyncio.sleep(60)

        self._scan_task = asyncio.create_task(_scan_loop())
        logger = _get_logger()
        logger.info(f"Duplicate detector started (interval: {self._scan_interval}s)")

    async def stop_periodic_scan(self) -> None:
        """Stop periodic duplicate detection scanning."""
        self._running = False
        if self._scan_task:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass
            self._scan_task = None
        logger = _get_logger()
        logger.info("Duplicate detector stopped")

    async def get_duplicates(self) -> list[dict]:
        """Get all detected duplicates from last scan."""
        return self._detected_duplicates

    async def get_status(self) -> dict[str, Any]:
        """Get status of duplicate detector."""
        return {
            "enabled": self._enabled,
            "running": self._running,
            "detected_duplicates_count": len(self._detected_duplicates),
            "similarity_threshold": self._similarity_threshold,
            "time_window_seconds": self._time_window,
            "scan_interval_seconds": self._scan_interval,
        }


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_duplicate_detector: DuplicateDetectorFuzzy | None = None


async def get_duplicate_detector() -> DuplicateDetectorFuzzy:
    """Get singleton instance of DuplicateDetectorFuzzy."""
    global _duplicate_detector
    if _duplicate_detector is None:
        _duplicate_detector = DuplicateDetectorFuzzy()
    return _duplicate_detector


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["DuplicateDetectionError", "DuplicateDetectorFuzzy", "get_duplicate_detector"]
