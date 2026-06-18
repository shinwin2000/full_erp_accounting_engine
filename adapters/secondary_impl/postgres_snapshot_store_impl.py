#!/usr/bin/env python3
"""
Module: postgres_snapshot_store_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Menyimpan snapshot aggregate untuk event sourcing.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


class PostgresSnapshotStore:
    """
    Store untuk snapshot aggregate menggunakan PostgreSQL.
    Stub, tidak menyimpan nyata.
    """

    async def save_snapshot(self, aggregate_id: UUID, version: int, state: dict[str, Any]) -> None:
        logger.info(f"Saving snapshot for aggregate {aggregate_id} version {version}")

    async def get_latest_snapshot(self, aggregate_id: UUID) -> dict[str, Any] | None:
        logger.info(f"Getting latest snapshot for {aggregate_id}")
        return None
