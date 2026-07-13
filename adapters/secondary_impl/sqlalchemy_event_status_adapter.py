#!/usr/bin/env python3
"""
Module: sqlalchemy_event_status_adapter.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi EventStatusPort dengan SQLAlchemy.
Perbaikan:
  - Menggunakan pessimistic locking (SELECT FOR UPDATE) untuk mencegah race condition.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime, String, Text, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

from ports.primary.event_status_port import EventStatusPort

logger = logging.getLogger(__name__)

Base = declarative_base()


class EventStatusTable(Base):
    __tablename__ = "event_status"
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(String(100), nullable=False, unique=True)
    status = Column(String(50), nullable=False)
    message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=datetime.utcnow)


class SQLAlchemyEventStatusAdapter(EventStatusPort):
    """
    Implementasi EventStatusPort dengan SQLAlchemy.
    """

    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    async def get_status(self, event_id: str) -> dict[str, Any] | None:
        session = await self._get_session()
        stmt = select(EventStatusTable).where(EventStatusTable.event_id == event_id)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None
        return {
            "event_id": row.event_id,
            "status": row.status,
            "message": row.message,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    async def set_status(self, event_id: str, status: str, message: str | None = None) -> dict[str, Any]:
        session = await self._get_session()
        # Lock the row if it exists to prevent race conditions
        stmt = select(EventStatusTable).where(EventStatusTable.event_id == event_id).with_for_update()
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()

        if row:
            row.status = status
            if message is not None:
                row.message = message
            row.updated_at = datetime.utcnow()
            await session.flush()
        else:
            # Insert new row, handle concurrent insert
            try:
                row = EventStatusTable(
                    event_id=event_id,
                    status=status,
                    message=message,
                )
                session.add(row)
                await session.flush()
            except IntegrityError:
                await session.rollback()
                # Retry with lock
                stmt_retry = select(EventStatusTable).where(
                    EventStatusTable.event_id == event_id
                ).with_for_update()
                result_retry = await session.execute(stmt_retry)
                row = result_retry.scalar_one()
                row.status = status
                if message is not None:
                    row.message = message
                row.updated_at = datetime.utcnow()
                await session.flush()

        return {
            "event_id": row.event_id,
            "status": row.status,
            "message": row.message,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    async def delete_status(self, event_id: str) -> bool:
        session = await self._get_session()
        stmt = select(EventStatusTable).where(EventStatusTable.event_id == event_id).with_for_update()
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return False
        await session.delete(row)
        await session.flush()
        return True


__all__ = ["EventStatusTable", "SQLAlchemyEventStatusAdapter"]
