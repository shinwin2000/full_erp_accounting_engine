# infrastructure/event_store/event_store.py
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

# Re-export class AppendOnlyStore sebagai AppendOnlyEventStore
from infrastructure.event_store.append_only_store import (
    AppendOnlyStore,
    AppendOnlyStoreError,
    EventNotFoundError,
    IntegrityViolationError,
    get_event_store,
)

# Setup logger
logger = logging.getLogger(__name__)


class AppendOnlyEventStore(AppendOnlyStore):
    """
    Subclass dari AppendOnlyStore yang menambahkan metode kompatibilitas
    yang diharapkan oleh test integrasi:

    - append_stream(stream_name, events) -> alias untuk append_batch
    - load_stream(stream_name) -> alias untuk read_stream
    - update_event(...) -> metode simulasi (tidak didukung dalam append-only store,
      tetapi test membutuhkannya untuk demonstrasi tamper)
    - save_events(events) -> simpan multiple events (batch)
    """

    async def append_stream(self, stream_name: str, events: list[dict[str, Any]]) -> list[UUID]:
        """
        Menambahkan beberapa event ke stream.
        Test mengharapkan method ini.
        """
        # Konversi event list ke format yang diharapkan oleh append_batch
        batch = [(stream_name, ev, ev.get("type", "domain"), ev.get("metadata")) for ev in events]
        return await self.append_batch(batch)

    async def load_stream(self, stream_name: str) -> list[dict[str, Any]]:
        """
        Membaca semua event dari stream.
        """
        return await self.read_stream(stream_name, from_sequence=1, limit=1000000)

    async def update_event(self, stream: str, position: int, new_data: dict[str, Any]) -> None:
        """
        Simulasi update event (tidak mungkin di append‑only store asli).
        Digunakan hanya untuk test integrity (tamper detection).
        Dalam implementasi nyata, operasi ini tidak diizinkan.
        Untuk keperluan test, kita akan langsung memodifikasi data di penyimpanan
        (misalnya lewat SQL raw) atau hanya log peringatan.
        Karena kita menggunakan database in‑memory, kita bisa melakukan update
        langsung ke tabel event_store.
        """
        logger.warning(
            f"update_event called on append-only store! This should not happen in production. "
            f"stream={stream}, position={position}, new_data={new_data}"
        )
        try:
            from infrastructure.database.session_factory_sqlalchemy import get_session_factory

            session_factory = await get_session_factory()
            async with session_factory.get_session() as session, session.begin():
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
        except Exception as e:
            logger.error(f"Failed to update event in test: {e}")

    async def save_events(self, events: list[dict[str, Any]]) -> None:
        """
        Simpan multiple events (batch) ke stream yang sesuai.
        Test mengharapkan method ini.
        """
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
    "AppendOnlyStore",
    "AppendOnlyStoreError",
    "EventNotFoundError",
    "EventStore",
    "IntegrityViolationError",
    "get_event_store",
]
