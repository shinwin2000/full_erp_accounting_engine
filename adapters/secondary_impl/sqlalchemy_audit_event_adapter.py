#!/usr/bin/env python3
"""
Module: sqlalchemy_audit_event_adapter.py
Layer: Adapters (Secondary Implementation)
Responsibility: Real SQLAlchemy implementation of AuditEvent port.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, Column, DateTime, Integer, String, and_, asc, desc, func, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

logger = logging.getLogger(__name__)

Base = declarative_base()


class AuditEventTable(Base):
    __tablename__ = "audit_events"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    aggregate_id = Column(PGUUID(as_uuid=True), nullable=False, index=True)
    entity_id = Column(String(100), nullable=True)  # legacy/backward compatibility
    event_type = Column(String(50), nullable=False)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    user_id = Column(String(100), nullable=True)
    correlation_id = Column(String(100), nullable=True, index=True)
    sequence_number = Column(Integer, nullable=False, default=1)  # <-- Integer sekarang dikenali
    previous_hash = Column(String(128), nullable=True)
    hash_value = Column(String(128), nullable=True, index=True)
    event_version = Column(Integer, nullable=False, default=1)


class SQLAlchemyAuditEventAdapter:
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    # ========== Existing methods ==========

    async def log_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Legacy method – use append_event instead."""
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
        """Legacy method – use get_events_by_aggregate or other specific methods."""
        session = await self._get_session()
        stmt = select(AuditEventTable).where(AuditEventTable.entity_id == entity_id).order_by(desc(AuditEventTable.created_at)).limit(limit)
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

    # ========== New methods required by AuditRepositoryPort ==========

    async def append_event(
        self,
        aggregate_id: UUID,
        event_type: str,
        payload: dict[str, Any],
        correlation_id: str | None = None,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Append a new audit event to the hash chain for the aggregate.
        Computes the hash based on previous hash, payload, and sequence.
        """
        session = await self._get_session()

        # Determine next sequence number and previous hash
        stmt = (
            select(func.max(AuditEventTable.sequence_number))
            .where(AuditEventTable.aggregate_id == aggregate_id)
        )
        result = await session.execute(stmt)
        max_seq = result.scalar() or 0
        next_seq = max_seq + 1

        # Get previous hash (if any)
        if max_seq > 0:
            prev_stmt = (
                select(AuditEventTable.hash_value)
                .where(
                    AuditEventTable.aggregate_id == aggregate_id,
                    AuditEventTable.sequence_number == max_seq
                )
            )
            prev_result = await session.execute(prev_stmt)
            previous_hash = prev_result.scalar()
        else:
            previous_hash = None

        # Compute hash for this event
        # Include: aggregate_id, event_type, payload, sequence, previous_hash, timestamp
        hash_input = {
            "aggregate_id": str(aggregate_id),
            "event_type": event_type,
            "payload": payload,
            "sequence": next_seq,
            "previous_hash": previous_hash,
            "timestamp": datetime.utcnow().isoformat(),
        }
        hash_str = json.dumps(hash_input, sort_keys=True, separators=(",", ":"))
        hash_value = hashlib.sha256(hash_str.encode("utf-8")).hexdigest()

        # Create event record
        audit = AuditEventTable(
            aggregate_id=aggregate_id,
            entity_id=str(aggregate_id),  # for backward compatibility
            event_type=event_type,
            payload=payload,
            user_id=user_id,
            correlation_id=correlation_id,
            sequence_number=next_seq,
            previous_hash=previous_hash,
            hash_value=hash_value,
            event_version=metadata.get("event_version", 1) if metadata else 1,
        )
        session.add(audit)
        await session.flush()

        logger.info(f"Appended event {event_type} for aggregate {aggregate_id} at seq {next_seq}")

        return {
            "id": str(audit.id),
            "aggregate_id": str(audit.aggregate_id),
            "event_type": audit.event_type,
            "payload": audit.payload,
            "created_at": audit.created_at.isoformat(),
            "user_id": audit.user_id,
            "correlation_id": audit.correlation_id,
            "sequence_number": audit.sequence_number,
            "hash_value": audit.hash_value,
            "previous_hash": audit.previous_hash,
        }

    async def get_events_by_aggregate(
        self,
        aggregate_id: UUID,
        limit: int = 100,
        offset: int = 0,
        from_sequence: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Retrieve events for a specific aggregate, ordered by sequence ascending.
        """
        session = await self._get_session()
        conditions = [AuditEventTable.aggregate_id == aggregate_id]
        if from_sequence is not None:
            conditions.append(AuditEventTable.sequence_number >= from_sequence)

        stmt = (
            select(AuditEventTable)
            .where(and_(*conditions))
            .order_by(asc(AuditEventTable.sequence_number))
            .offset(offset)
            .limit(limit)
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [
            {
                "id": str(row.id),
                "aggregate_id": str(row.aggregate_id),
                "event_type": row.event_type,
                "payload": row.payload,
                "created_at": row.created_at.isoformat(),
                "user_id": row.user_id,
                "correlation_id": row.correlation_id,
                "sequence_number": row.sequence_number,
                "hash_value": row.hash_value,
                "previous_hash": row.previous_hash,
            }
            for row in rows
        ]

    async def get_events_by_correlation_id(
        self,
        correlation_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Retrieve events that share the same correlation ID.
        """
        session = await self._get_session()
        stmt = (
            select(AuditEventTable)
            .where(AuditEventTable.correlation_id == correlation_id)
            .order_by(asc(AuditEventTable.created_at))
            .offset(offset)
            .limit(limit)
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [
            {
                "id": str(row.id),
                "aggregate_id": str(row.aggregate_id),
                "event_type": row.event_type,
                "payload": row.payload,
                "created_at": row.created_at.isoformat(),
                "user_id": row.user_id,
                "correlation_id": row.correlation_id,
                "sequence_number": row.sequence_number,
                "hash_value": row.hash_value,
                "previous_hash": row.previous_hash,
            }
            for row in rows
        ]

    async def get_events_by_type(
        self,
        event_type: str,
        aggregate_id: UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Retrieve events by event type, optionally filtered by aggregate.
        """
        session = await self._get_session()
        conditions = [AuditEventTable.event_type == event_type]
        if aggregate_id is not None:
            conditions.append(AuditEventTable.aggregate_id == aggregate_id)

        stmt = (
            select(AuditEventTable)
            .where(and_(*conditions))
            .order_by(desc(AuditEventTable.created_at))
            .offset(offset)
            .limit(limit)
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [
            {
                "id": str(row.id),
                "aggregate_id": str(row.aggregate_id),
                "event_type": row.event_type,
                "payload": row.payload,
                "created_at": row.created_at.isoformat(),
                "user_id": row.user_id,
                "correlation_id": row.correlation_id,
                "sequence_number": row.sequence_number,
                "hash_value": row.hash_value,
                "previous_hash": row.previous_hash,
            }
            for row in rows
        ]

    async def get_hash_chain_root(self, aggregate_id: UUID) -> str | None:
        """
        Get the current root hash (hash of the last event) for the aggregate.
        """
        session = await self._get_session()
        stmt = (
            select(AuditEventTable.hash_value)
            .where(AuditEventTable.aggregate_id == aggregate_id)
            .order_by(desc(AuditEventTable.sequence_number))
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar()

    async def get_last_event(self, aggregate_id: UUID) -> dict[str, Any] | None:
        """
        Get the most recent event for the aggregate.
        """
        session = await self._get_session()
        stmt = (
            select(AuditEventTable)
            .where(AuditEventTable.aggregate_id == aggregate_id)
            .order_by(desc(AuditEventTable.sequence_number))
            .limit(1)
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None
        return {
            "id": str(row.id),
            "aggregate_id": str(row.aggregate_id),
            "event_type": row.event_type,
            "payload": row.payload,
            "created_at": row.created_at.isoformat(),
            "user_id": row.user_id,
            "correlation_id": row.correlation_id,
            "sequence_number": row.sequence_number,
            "hash_value": row.hash_value,
            "previous_hash": row.previous_hash,
        }

    async def replay_events(
        self,
        aggregate_id: UUID,
        from_sequence: int = 1,
        to_sequence: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Replay events in sequence order, optionally within a range.
        Useful for rebuilding state.
        """
        return await self.get_events_by_aggregate(
            aggregate_id=aggregate_id,
            from_sequence=from_sequence,
            limit=to_sequence - from_sequence + 1 if to_sequence else 1000,
        )

    async def verify_hash_chain(self, aggregate_id: UUID) -> dict[str, Any]:
        """
        Verify the integrity of the entire hash chain for the aggregate.
        Returns verification result with status and details.
        """
        events = await self.get_events_by_aggregate(aggregate_id, limit=10000)
        if not events:
            return {"status": "empty", "message": "No events found for aggregate"}

        valid = True
        errors = []
        previous_hash = None

        for i, event in enumerate(events):
            # Recompute hash from event data
            hash_input = {
                "aggregate_id": str(aggregate_id),
                "event_type": event["event_type"],
                "payload": event["payload"],
                "sequence": event["sequence_number"],
                "previous_hash": previous_hash,
                "timestamp": event["created_at"],
            }
            hash_str = json.dumps(hash_input, sort_keys=True, separators=(",", ":"))
            computed = hashlib.sha256(hash_str.encode("utf-8")).hexdigest()

            if computed != event["hash_value"]:
                valid = False
                errors.append({
                    "sequence": event["sequence_number"],
                    "expected": computed,
                    "actual": event["hash_value"],
                })

            # Check previous hash linkage
            if i > 0:
                if event["previous_hash"] != events[i-1]["hash_value"]:
                    valid = False
                    errors.append({
                        "sequence": event["sequence_number"],
                        "message": "Previous hash mismatch",
                        "expected_prev": events[i-1]["hash_value"],
                        "actual_prev": event["previous_hash"],
                    })

            previous_hash = event["hash_value"]

        return {
            "status": "valid" if valid else "corrupted",
            "aggregate_id": str(aggregate_id),
            "total_events": len(events),
            "errors": errors,
        }


__all__ = ["AuditEventTable", "SQLAlchemyAuditEventAdapter"]