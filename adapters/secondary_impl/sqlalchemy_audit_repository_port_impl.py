#!/usr/bin/env python3
"""
Module: sqlalchemy_audit_repository_port_impl.py
Adapter for AuditEvent (from audit_repository_port)
"""

from __future__ import annotations

import uuid
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime, String, Text, JSON, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

logger = logging.getLogger(__name__)

Base = declarative_base()


class AuditEventTable(Base):
    __tablename__ = "audit_events"
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id = Column(String(100), nullable=False)
    event_type = Column(String(50), nullable=False)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    user_id = Column(String(100), nullable=True)


class SQLAlchemyAuditEventAdapter:
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    async def log_event(self, event: dict[str, Any]) -> dict[str, Any]:
        session = await self._get_session()
        audit = AuditEventTable(
            entity_id=event.get("entity_id", "unknown"),
            event_type=event.get("type", "unknown"),
            payload=event.get("payload"),
            user_id=event.get("user_id"),
        )
        session.add(audit)
        await session.flush()
        return {
            "id": str(audit.id),
            "entity_id": audit.entity_id,
            "event_type": audit.event_type,
            "payload": audit.payload,
            "created_at": audit.created_at.isoformat(),
            "user_id": audit.user_id,
        }

    async def get_events(self, entity_id: str, limit: int = 100) -> list[dict[str, Any]]:
        session = await self._get_session()
        stmt = select(AuditEventTable).where(AuditEventTable.entity_id == entity_id).order_by(AuditEventTable.created_at.desc()).limit(limit)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [
            {
                "id": str(row.id),
                "entity_id": row.entity_id,
                "event_type": row.event_type,
                "payload": row.payload,
                "created_at": row.created_at.isoformat(),
                "user_id": row.user_id,
            }
            for row in rows
        ]


__all__ = ["AuditEventTable", "SQLAlchemyAuditEventAdapter"]