#!/usr/bin/env python3
"""
Adapter: Saga State Store
Layer: Adapters (Secondary Implementation)

Adapter untuk menyimpan state saga menggunakan SagaStateStore dari application layer.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from application.sagas.saga_state_store import SagaStateStore
from infrastructure.telemetry.structured_json_logging import get_logger
from ports.primary.saga_state_store_port import SagaStateStorePort

logger = get_logger(__name__)

class SagaStateStoreAdapter(SagaStateStorePort):
    """
    Adapter yang menggunakan SagaStateStore (implementasi in-memory/redis/db).
    """
    def __init__(self):
        self._store = SagaStateStore()

    async def save(self, saga_id: UUID, state: dict[str, Any]) -> None:
        # Asumsikan saga_type default atau ambil dari state
        saga_type = state.get("saga_type", "default")
        await self._store.save(saga_type, saga_id, state)

    async def get(self, saga_id: UUID) -> dict[str, Any] | None:
        # Kita butuh saga_type, kita simpan di state atau gunakan default
        # Kita bisa gunakan metode get dengan saga_type default
        return await self._store.get("default", saga_id)

    async def health_check(self) -> dict:
        return {"status": "healthy", "store_type": "saga_state_store"}

__all__ = ["SagaStateStoreAdapter"]