#!/usr/bin/env python3
"""
Module: sqlalchemy_event_status_adapter.py
Layer: Adapters (Secondary Implementation)
Responsibility: Real SQLAlchemy implementation of EventStatus port.
"""

from __future__ import annotations

import uuid
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime, String, Text, select, update, delete
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

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


class SQLAlchemyEventStatusAdapter:
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
        # Check if exists
        stmt = select(EventStatusTable).where(EventStatusTable.event_id == event_id)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if row:
            # Update
            row.status = status
            if message is not None:
                row.message = message
            row.updated_at = datetime.utcnow()
            await session.flush()
        else:
            # Create
            row = EventStatusTable(
                event_id=event_id,
                status=status,
                message=message,
            )
            session.add(row)
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
        stmt = delete(EventStatusTable).where(EventStatusTable.event_id == event_id)
        result = await session.execute(stmt)
        await session.flush()
        return result.rowcount > 0


__all__ = ["EventStatusTable", "SQLAlchemyEventStatusAdapter"]