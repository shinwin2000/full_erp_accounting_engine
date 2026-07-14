# ============================================================================
# infrastructure/event_store/replay_engine.py
# ============================================================================
"""
Module: replay_engine.py
Layer: Infrastructure (Event Store)
Responsibility: Mesin replay untuk event sourcing.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from infrastructure.event_store.snapshot_manager import SnapshotManager

logger = logging.getLogger(__name__)


class ReplayEngine:
    def __init__(self, event_store=None, snapshot_manager: SnapshotManager | None = None):
        self._event_store = event_store
        self._snapshot_manager = snapshot_manager

    async def _get_event_store(self):
        if self._event_store is None:
            # Impor lokal di dalam fungsi
            from infrastructure.event_store.append_only_store import get_event_store
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
        event_store = await self._get_event_store()
        stream_name = f"{aggregate_type}:{aggregate_id}"
        start_version = 1
        snapshot = None
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
        events = await event_store.read_stream(stream_name, from_sequence=start_version)
        if target_version:
            events = [e for e in events if e.get("sequence_number", 0) <= target_version]
        if event_filter:
            events = [e for e in events if event_filter(e)]
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
        last_version, events = await self.replay_aggregate(
            aggregate_id, aggregate_type, target_version, use_snapshot
        )
        snapshot_mgr = await self._get_snapshot_manager()
        snapshot = await snapshot_mgr.get_latest_snapshot(
            aggregate_id, aggregate_type, target_version
        )
        if snapshot and use_snapshot:
            aggregate = builder()
            if hasattr(aggregate, "deserialize"):
                aggregate = aggregate.deserialize(snapshot["state"])
            else:
                aggregate = builder()
                for ev in events:
                    aggregate = apply_event(aggregate, ev)
                return aggregate, last_version
        else:
            aggregate = builder()
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
        event_store = await self._get_event_store()
        all_events = await event_store.search_events(
            event_type=None,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )
        filtered = [
            e for e in all_events if e.get("stream_name", "").startswith(f"{aggregate_type}:")
        ]
        return filtered

    async def get_total_event_count(self, aggregate_type: str | None = None) -> int:
        event_store = await self._get_event_store()
        if aggregate_type:
            stream_prefix = f"{aggregate_type}:"
            events = await event_store.read_all_events(limit=10_000_000)
            return len([e for e in events if e.get("stream_name", "").startswith(stream_prefix)])
        else:
            events = await event_store.read_all_events(limit=10_000_000)
            return len(events)


_replay_engine: ReplayEngine | None = None

async def get_replay_engine() -> ReplayEngine:
    global _replay_engine
    if _replay_engine is None:
        _replay_engine = ReplayEngine()
    return _replay_engine

__all__ = ["ReplayEngine", "get_replay_engine"]