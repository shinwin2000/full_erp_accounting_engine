#!/usr/bin/env python3
"""
Module: sqlalchemy_audit_repository.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi AuditRepositoryPort dengan SQLAlchemy.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime
from uuid import UUID

from sqlalchemy import Column, DateTime, Index, Integer, String, Text, desc, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

from ports.primary.audit_repository_port import AuditEvent, AuditRepositoryPort

logger = logging.getLogger(__name__)

Base = declarative_base()


class AuditEventTable(Base):
    """SQLAlchemy ORM model for audit events with hash chaining."""

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("idx_audit_aggregate", "aggregate_id", "version"),
        Index("idx_audit_type", "event_type"),
        Index("idx_audit_correlation", "correlation_id"),
        Index("idx_audit_timestamp", "event_time"),
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    aggregate_id = Column(PGUUID(as_uuid=True), nullable=False)
    aggregate_type = Column(String(100), nullable=False)
    version = Column(Integer, nullable=False)
    event_type = Column(String(100), nullable=False)
    event_data = Column(Text, nullable=False)  # JSON
    correlation_id = Column(String(100), nullable=True)
    previous_hash = Column(String(64), nullable=True)
    hash = Column(String(64), nullable=False)
    event_time = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class SQLAlchemyAuditRepository(AuditRepositoryPort):
    """
    SQLAlchemy implementation of AuditRepositoryPort.
    """

    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    def _compute_hash(self, event: AuditEvent) -> str:
        data = {
            "aggregate_id": str(event.aggregate_id),
            "version": event.version,
            "event_type": event.event_type,
            "event_data": event.payload,  # payload is dict
            "previous_hash": event.previous_hash,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()

    # ========================================================================
    # PORT METHODS (9 methods)
    # ========================================================================

    async def append_event(self, event: AuditEvent) -> None:
        """Append an immutable audit event."""
        session = await self._get_session()
        # Get previous hash if any
        prev = await self.get_last_event(event.aggregate_id)
        event.previous_hash = prev.hash if prev else None
        event.hash = self._compute_hash(event)

        record = AuditEventTable(
            aggregate_id=event.aggregate_id,
            aggregate_type=event.event_type,
            version=event.version,
            event_type=event.event_type,
            event_data=json.dumps(event.payload, default=str),
            correlation_id=event.correlation_id,
            previous_hash=event.previous_hash,
            hash=event.hash,
            event_time=event.occurred_at or datetime.utcnow(),
        )
        session.add(record)
        await session.commit()

    async def get_events_by_aggregate(
        self, aggregate_id: UUID, from_version: int | None = None, limit: int = 1000
    ) -> list[AuditEvent]:
        session = await self._get_session()
        stmt = select(AuditEventTable).where(AuditEventTable.aggregate_id == aggregate_id)
        if from_version is not None:
            stmt = stmt.where(AuditEventTable.version >= from_version)
        stmt = stmt.order_by(AuditEventTable.version).limit(limit)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._to_domain(row) for row in rows]

    async def get_events_by_type(
        self,
        event_type: str,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        limit: int = 1000,
    ) -> list[AuditEvent]:
        session = await self._get_session()
        stmt = select(AuditEventTable).where(AuditEventTable.event_type == event_type)
        if from_date:
            stmt = stmt.where(AuditEventTable.event_time >= from_date)
        if to_date:
            stmt = stmt.where(AuditEventTable.event_time <= to_date)
        stmt = stmt.order_by(desc(AuditEventTable.event_time)).limit(limit)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._to_domain(row) for row in rows]

    async def get_events_by_correlation_id(self, correlation_id: str) -> list[AuditEvent]:
        session = await self._get_session()
        stmt = select(AuditEventTable).where(
            AuditEventTable.correlation_id == correlation_id
        ).order_by(AuditEventTable.version)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._to_domain(row) for row in rows]

    async def get_last_event(self, aggregate_id: UUID) -> AuditEvent | None:
        session = await self._get_session()
        stmt = select(AuditEventTable).where(
            AuditEventTable.aggregate_id == aggregate_id
        ).order_by(desc(AuditEventTable.version)).limit(1)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def verify_hash_chain(self, aggregate_id: UUID) -> bool:
        """Verify the integrity of the hash chain."""
        events = await self.get_events_by_aggregate(aggregate_id, limit=999999)
        if not events:
            return True
        for i, evt in enumerate(events):
            if i == 0:
                if evt.previous_hash is not None:
                    return False
            else:
                if evt.previous_hash != events[i-1].hash:
                    return False
            if evt.hash != self._compute_hash(evt):
                return False
        return True

    async def get_hash_chain_root(self, aggregate_id: UUID) -> str | None:
        last = await self.get_last_event(aggregate_id)
        return last.hash if last else None

    async def replay_events(
        self,
        aggregate_id: UUID,
        from_version: int | None = None,
        to_version: int | None = None,
    ) -> list[AuditEvent]:
        events = await self.get_events_by_aggregate(aggregate_id, from_version, limit=10000)
        if to_version is not None:
            events = [e for e in events if e.version <= to_version]
        return events

    # ========================================================================
    # Helper
    # ========================================================================

    def _to_domain(self, row: AuditEventTable) -> AuditEvent:
        """Convert ORM row to AuditEvent."""
        return AuditEvent(
            event_id=row.id,
            aggregate_id=row.aggregate_id,
            event_type=row.event_type,
            payload=json.loads(row.event_data),
            occurred_at=row.event_time,
            user_id=None,  # not stored
            correlation_id=row.correlation_id,
            causation_id=None,
            version=row.version,
            hash_chain_previous=row.previous_hash,
            hash_chain_current=row.hash,
        )


# Alias for protocol compatibility
SQLAlchemyAuditRepositoryProtocol = SQLAlchemyAuditRepository

__all__ = ["AuditEventTable", "SQLAlchemyAuditRepository", "SQLAlchemyAuditRepositoryProtocol"]
