#!/usr/bin/env python3
"""
Adapter: Saga State Store
Layer: Adapters (Secondary Implementation)

Adapter untuk menyimpan state saga menggunakan in-memory store.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional, Dict
from uuid import UUID

from infrastructure.telemetry.structured_json_logging import get_logger
from ports.primary.saga_state_store_port import SagaStateStorePort

logger = get_logger(__name__)


class SagaStateStoreAdapter(SagaStateStorePort):
    """
    Adapter in-memory untuk menyimpan state saga.
    """

    def __init__(self):
        self._store: Dict[str, Dict[UUID, Dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    async def save(self, saga_id: UUID, state: dict[str, Any]) -> None:
        saga_type = state.get("saga_type", "default")
        async with self._lock:
            if saga_type not in self._store:
                self._store[saga_type] = {}
            self._store[saga_type][saga_id] = state
        logger.debug(f"Saga state saved: {saga_id}")

    async def get(self, saga_id: UUID) -> Optional[dict[str, Any]]:
        # Cari di semua tipe
        async with self._lock:
            for saga_type, entries in self._store.items():
                if saga_id in entries:
                    return entries[saga_id]
            return None

    async def update(self, saga_id: UUID, state: dict[str, Any]) -> None:
        await self.save(saga_id, state)

    async def delete(self, saga_id: UUID) -> None:
        async with self._lock:
            for saga_type in list(self._store.keys()):
                if saga_id in self._store[saga_type]:
                    del self._store[saga_type][saga_id]
                    break
        logger.debug(f"Saga state deleted: {saga_id}")

    async def health_check(self) -> dict:
        async with self._lock:
            total = sum(len(entries) for entries in self._store.values())
        return {"status": "healthy", "store_type": "in_memory", "total_sagas": total}


__all__ = ["SagaStateStoreAdapter"]