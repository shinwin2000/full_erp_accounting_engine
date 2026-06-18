#!/usr/bin/env python3
"""
Module: sqlalchemy_dead_letter_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository untuk Dead Letter Queue menggunakan SQLAlchemy core.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    insert,
    select,
    update,
)
from sqlalchemy.ext.asyncio import async_sessionmaker

from infrastructure.database.session_factory_sqlalchemy import get_async_session_factory

logger = logging.getLogger(__name__)

# Define table metadata (table will be created if not exists, but usually via migration)
metadata = MetaData()
dead_letter_table = Table(
    "dead_letter_queue",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("event_id", String, nullable=False, index=True),
    Column("event_type", String, nullable=False),
    Column("aggregate_id", String, nullable=True),
    Column("aggregate_type", String, nullable=True),
    Column("payload", JSON, nullable=False),
    Column("metadata", JSON, nullable=True),
    Column("error_message", Text, nullable=False),
    Column("retry_count", Integer, default=0),
    Column("topic", String, nullable=False),
    Column("partition", Integer, nullable=False),
    Column("offset", Integer, nullable=False),
    Column("created_at", DateTime, default=datetime.utcnow),
    Column("status", String, default="pending"),
)


class SQLAlchemyDeadLetterRepository:
    """Repository untuk menyimpan dead letter events menggunakan SQLAlchemy core."""

    def __init__(self, session_factory: async_sessionmaker | None = None):
        self._session_factory = session_factory or get_async_session_factory()

    async def store(
        self,
        envelope: Any,
        error: str,
        retry_count: int,
        topic: str,
        partition: int,
        offset: int,
    ) -> None:
        """
        Store a failed event in the dead letter table.
        """
        async with self._session_factory() as session:
            stmt = insert(dead_letter_table).values(
                event_id=str(envelope.event_id),
                event_type=envelope.event_type,
                aggregate_id=str(envelope.aggregate_id)
                if hasattr(envelope, "aggregate_id")
                else None,
                aggregate_type=getattr(envelope, "aggregate_type", None),
                payload=envelope.to_json()
                if hasattr(envelope, "to_json")
                else json.dumps(envelope.payload, default=str),
                metadata=envelope.metadata if hasattr(envelope, "metadata") else {},
                error_message=error,
                retry_count=retry_count,
                topic=topic,
                partition=partition,
                offset=offset,
                created_at=datetime.now(UTC),
                status="pending",
            )
            await session.execute(stmt)
            await session.commit()
            logger.info(f"Dead letter stored for event {envelope.event_id}")

    async def get_failed_count(self, event_id: UUID) -> int:
        """Get number of failures for an event."""
        async with self._session_factory() as session:
            stmt = select(dead_letter_table.c.id).where(
                dead_letter_table.c.event_id == str(event_id)
            )
            result = await session.execute(stmt)
            return len(result.fetchall())

    async def mark_resolved(self, event_id: UUID) -> None:
        """Mark dead letter entry as resolved."""
        async with self._session_factory() as session:
            stmt = (
                update(dead_letter_table)
                .where(dead_letter_table.c.event_id == str(event_id))
                .values(status="resolved")
            )
            await session.execute(stmt)
            await session.commit()

    async def list_pending(self, limit: int = 100) -> list[dict]:
        """List pending dead letter entries."""
        async with self._session_factory() as session:
            stmt = (
                select(dead_letter_table)
                .where(dead_letter_table.c.status == "pending")
                .limit(limit)
            )
            result = await session.execute(stmt)
            rows = result.fetchall()
            return [dict(row._mapping) for row in rows]


__all__ = ["SQLAlchemyDeadLetterRepository"]
