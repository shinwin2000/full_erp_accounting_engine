# infrastructure/event_store/replay_engine.py
"""
Module: replay_engine.py
Layer: Infrastructure (Event Store)
Responsibility: Mesin replay untuk event sourcing. Memutar ulang event dari
               event store untuk membangun ulang state aggregate, mendukung
               versioning, filtering, dan parallel replay.
Dependencies:
- asyncio, logging, datetime
- infrastructure.event_store.append_only_store (AppendOnlyStore)
- infrastructure.event_store.snapshot_manager (SnapshotManager)
Audit: Setiap operasi replay dicatat.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from infrastructure.event_store.append_only_store import AppendOnlyStore, get_event_store
from infrastructure.event_store.snapshot_manager import SnapshotManager

logger = logging.getLogger(__name__)


class ReplayEngine:
    """
    Mesin replay untuk event sourcing.

    Fitur:
    - Replay event dari event store untuk aggregate tertentu
    - Mendukung snapshot untuk mempercepat replay
    - Filter event berdasarkan tipe atau rentang waktu
    - Parallel replay untuk multiple aggregates
    - Progress callback untuk monitoring
    """

    def __init__(
        self,
        event_store: AppendOnlyStore | None = None,
        snapshot_manager: SnapshotManager | None = None,
    ):
        self._event_store = event_store
        self._snapshot_manager = snapshot_manager

    async def _get_event_store(self) -> AppendOnlyStore:
        if self._event_store is None:
            self._event_store = await get_event_store()
        return self._event_store

    async def _get_snapshot_manager(self) -> SnapshotManager:
        if self._snapshot_manager is None:
            self._snapshot_manager = SnapshotManager(await self._get_event_store())
        return self._snapshot_manager

    async def replay_aggregate(
        self,
        aggregate_id: str,
        aggregate_type: str,
        target_version: int | None = None,
        use_snapshot: bool = True,
        event_filter: Callable[[dict], bool] | None = None,
    ) -> tuple[int, list[dict]]:
        """
        Memutar ulang event untuk aggregate dari version awal hingga target_version.

        Args:
            aggregate_id: ID aggregate
            aggregate_type: Tipe aggregate
            target_version: Version target (None untuk semua event)
            use_snapshot: Gunakan snapshot jika tersedia
            event_filter: Fungsi filter event (opsional)

        Returns:
            Tuple (last_version, list_of_events)
        """
        event_store = await self._get_event_store()
        stream_name = f"{aggregate_type}:{aggregate_id}"
        start_version = 1
        snapshot = None

        # Cari snapshot terbaru jika diizinkan
        if use_snapshot:
            snapshot_mgr = await self._get_snapshot_manager()
            snapshot = await snapshot_mgr.get_latest_snapshot(
                aggregate_id, aggregate_type, target_version
            )
            if snapshot:
                start_version = snapshot["version"] + 1
                logger.info(
                    f"Using snapshot for {aggregate_type}/{aggregate_id}: "
                    f"version {snapshot['version']}"
                )

        # Baca event dari event store
        events = await event_store.read_stream(stream_name, from_sequence=start_version)
        if target_version:
            events = [e for e in events if e.get("sequence_number", 0) <= target_version]

        # Filter event jika ada
        if event_filter:
            events = [e for e in events if event_filter(e)]

        # Hitung versi terakhir
        last_version = start_version - 1 + len(events)
        if snapshot:
            last_version = max(last_version, snapshot["version"])

        logger.info(
            f"Replayed {len(events)} events for {aggregate_type}/{aggregate_id} "
            f"(from v{start_version} to v{last_version})"
        )

        return last_version, events

    async def replay_with_state_builder(
        self,
        aggregate_id: str,
        aggregate_type: str,
        builder: Callable[[], Any],
        apply_event: Callable[[Any, dict], Any],
        target_version: int | None = None,
        use_snapshot: bool = True,
    ) -> tuple[Any, int]:
        """
        Replay event dan langsung membangun state aggregate.

        Args:
            aggregate_id: ID aggregate
            aggregate_type: Tipe aggregate
            builder: Fungsi yang mengembalikan instance aggregate kosong
            apply_event: Fungsi yang menerapkan event ke aggregate
            target_version: Target version (opsional)
            use_snapshot: Gunakan snapshot jika tersedia

        Returns:
            Tuple (aggregate_instance, last_version)
        """
        # Replay event
        last_version, events = await self.replay_aggregate(
            aggregate_id, aggregate_type, target_version, use_snapshot
        )

        # Inisialisasi aggregate dari snapshot jika ada
        snapshot_mgr = await self._get_snapshot_manager()
        snapshot = await snapshot_mgr.get_latest_snapshot(
            aggregate_id, aggregate_type, target_version
        )

        if snapshot and use_snapshot:
            # Deserialize state dari snapshot
            # Asumsikan builder dapat menerima state snapshot
            aggregate = builder()
            if hasattr(aggregate, "deserialize"):
                aggregate = aggregate.deserialize(snapshot["state"])
            else:
                # Fallback: apply event dari awal
                aggregate = builder()
                for ev in events:
                    aggregate = apply_event(aggregate, ev)
                return aggregate, last_version
        else:
            aggregate = builder()

        # Terapkan event setelah snapshot
        for ev in events:
            aggregate = apply_event(aggregate, ev)

        return aggregate, last_version

    async def replay_multiple(
        self,
        aggregates: list[tuple[str, str]],
        target_version: int | None = None,
        use_snapshot: bool = True,
        max_concurrent: int = 10,
    ) -> dict[str, tuple[int, list[dict]]]:
        """
        Replay multiple aggregates secara parallel.

        Args:
            aggregates: List of (aggregate_id, aggregate_type)
            target_version: Target version
            use_snapshot: Gunakan snapshot
            max_concurrent: Maksimum concurrent replay

        Returns:
            Dictionary mapping aggregate_id -> (last_version, events)
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def replay_one(agg_id: str, agg_type: str):
            async with semaphore:
                version, events = await self.replay_aggregate(
                    agg_id, agg_type, target_version, use_snapshot
                )
                return agg_id, (version, events)

        tasks = [replay_one(aid, atype) for aid, atype in aggregates]
        results = await asyncio.gather(*tasks)
        return dict(results)

    async def replay_by_time_range(
        self,
        aggregate_type: str,
        start_time: datetime,
        end_time: datetime,
        limit: int = 1000,
    ) -> list[dict]:
        """
        Memutar ulang event berdasarkan rentang waktu untuk semua aggregate dengan tipe tertentu.

        Args:
            aggregate_type: Tipe aggregate
            start_time: Waktu mulai
            end_time: Waktu akhir
            limit: Maksimum jumlah event

        Returns:
            List event dalam rentang waktu
        """
        event_store = await self._get_event_store()
        # Cari semua stream dengan prefix aggregate_type
        # Implementasi sederhana: scan semua event dengan filter waktu
        # Di production, gunakan indeks waktu

        all_events = await event_store.search_events(
            event_type=None,  # semua tipe
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )
        # Filter berdasarkan aggregate_type (dari stream_name)
        filtered = [
            e for e in all_events if e.get("stream_name", "").startswith(f"{aggregate_type}:")
        ]
        return filtered

    async def get_total_event_count(self, aggregate_type: str | None = None) -> int:
        """
        Mendapatkan total jumlah event untuk satu tipe aggregate atau semua.

        Args:
            aggregate_type: Tipe aggregate (opsional)

        Returns:
            Jumlah event
        """
        event_store = await self._get_event_store()
        # Implementasi sederhana: hitung dari database
        if aggregate_type:
            stream_prefix = f"{aggregate_type}:"
            # Di implementasi nyata, gunakan query COUNT dengan LIKE
            # Untuk fallback, kita baca semua event (tidak efisien untuk production)
            events = await event_store.read_all_events(limit=10_000_000)
            return len([e for e in events if e.get("stream_name", "").startswith(stream_prefix)])
        else:
            events = await event_store.read_all_events(limit=10_000_000)
            return len(events)


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_replay_engine: ReplayEngine | None = None


async def get_replay_engine() -> ReplayEngine:
    """Get singleton instance of ReplayEngine."""
    global _replay_engine
    if _replay_engine is None:
        _replay_engine = ReplayEngine()
    return _replay_engine


__all__ = ["ReplayEngine", "get_replay_engine"]
