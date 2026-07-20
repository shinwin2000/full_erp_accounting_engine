# ============================================================================
# infrastructure/event_store/event_store.py
# ============================================================================
"""
Module: event_store.py
Layer: Infrastructure (Event Store)
Responsibility: Wrapper / alias untuk AppendOnlyStore dengan metode tambahan yang
               digunakan dalam pengujian integrasi (append_stream, load_stream,
               update_event, save_events, etc.).
               File ini memastikan kompatibilitas dengan kode lama yang mengimpor
               AppendOnlyEventStore.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any
from uuid import UUID

# Tidak ada impor langsung dari append_only_store di sini.
# Semua impor dilakukan di dalam fungsi/metode.

logger = logging.getLogger(__name__)


class AppendOnlyEventStore:
    """
    Wrapper untuk AppendOnlyStore yang menambahkan metode kompatibilitas
    yang diharapkan oleh test integrasi. Semua operasi didelegasikan ke
    AppendOnlyStore yang diambil secara lazy.
    """

    def __init__(self):
        self._store = None

    async def _get_store(self):
        if self._store is None:
            # Impor lokal di dalam fungsi untuk menghindari circular import
            # Gunakan singleton atau buat instance baru
            # Karena kita hanya membutuhkan instance, kita ambil yang sudah ada
            store = await self._get_event_store()
            self._store = store
        return self._store

    async def _get_event_store(self):
        # Impor lokal
        from infrastructure.event_store.append_only_store import get_event_store
        return await get_event_store()

    async def append_stream(self, stream_name: str, events: list[dict[str, Any]]) -> list[UUID]:
        """Menambahkan beberapa event ke stream."""
        store = await self._get_event_store()
        # Konversi event list ke format yang diharapkan oleh append_batch
        batch = [(stream_name, ev, ev.get("type", "domain"), ev.get("metadata")) for ev in events]
        return await store.append_batch(batch)

    async def load_stream(self, stream_name: str) -> list[dict[str, Any]]:
        """Membaca semua event dari stream."""
        store = await self._get_event_store()
        return await store.read_stream(stream_name, from_sequence=1, limit=1000000)

    async def update_event(self, stream: str, position: int, new_data: dict[str, Any]) -> None:
        """
        Simulasi update event (tidak mungkin di append‑only store asli).
        Digunakan hanya untuk test integrity (tamper detection).
        """
        logger.warning(
            f"update_event called on append-only store! This should not happen in production. "
            f"stream={stream}, position={position}, new_data={new_data}"
        )
        try:
            from infrastructure.database.session_factory_sqlalchemy import get_session_factory

            session_factory = await get_session_factory()
            async with session_factory.get_session() as session, session.begin():
                # 1. Lock the row with SELECT FOR UPDATE
                lock_query = """
                    SELECT id FROM event_store
                    WHERE stream_name = $1 AND sequence_number = $2
                    FOR UPDATE
                """
                locked_row = await session.fetchrow(lock_query, stream, position)
                if not locked_row:
                    logger.warning(f"Event not found for update: stream={stream}, position={position}")
                    return

                # 2. Update the locked row
                query = """
                    UPDATE event_store
                    SET data = $1, metadata = $2, hash = $3
                    WHERE stream_name = $4 AND sequence_number = $5
                """
                await session.execute(
                    query,
                    json.dumps(new_data, default=str),
                    json.dumps({"tampered": True}),
                    "tampered_hash",
                    stream,
                    position,
                )
                await session.commit()
                logger.info(f"Event updated in test: stream={stream}, position={position}")
        except Exception as e:
            logger.error(f"Failed to update event in test: {e}")

    async def save_events(self, events: list[dict[str, Any]]) -> None:
        """Simpan multiple events (batch) ke stream yang sesuai."""
        streams = defaultdict(list)
        for ev in events:
            stream = ev.get("stream", f"default-{ev.get('type', 'unknown')}")
            streams[stream].append(ev)

        for stream_name, ev_list in streams.items():
            await self.append_stream(stream_name, ev_list)


# ============================================================================
# ALIAS FOR TEST COMPATIBILITY
# ============================================================================

EventStore = AppendOnlyEventStore


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "AppendOnlyEventStore",
    "EventStore",
]
