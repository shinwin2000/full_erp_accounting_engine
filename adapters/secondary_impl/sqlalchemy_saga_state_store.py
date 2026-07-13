#!/usr/bin/env python3
"""
SQLAlchemy implementation of SagaStateStorePort.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, String, Text, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

from ports.primary.saga_state_store_port import SagaStateStorePort

logger = logging.getLogger(__name__)

Base = declarative_base()


class SagaStateTable(Base):
    __tablename__ = "saga_state_store"
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    saga_type = Column(String(100), nullable=False)
    saga_id = Column(PGUUID(as_uuid=True), nullable=False)
    state_json = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=datetime.utcnow)


class SQLAlchemySagaStateStoreRepository(SagaStateStorePort):
    """Implementasi SagaStateStorePort dengan SQLAlchemy."""

    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    async def save(self, saga_type: str, saga_id: UUID, state: dict[str, Any]) -> None:
        session = await self._get_session()
        stmt = select(SagaStateTable).where(
            SagaStateTable.saga_type == saga_type,
            SagaStateTable.saga_id == saga_id,
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()
        state_json = json.dumps(state, default=str)
        if existing:
            existing.state_json = state_json
            existing.updated_at = datetime.utcnow()
        else:
            new = SagaStateTable(
                saga_type=saga_type,
                saga_id=saga_id,
                state_json=state_json,
            )
            session.add(new)
        await session.flush()

    async def get(self, saga_type: str, saga_id: UUID) -> dict[str, Any] | None:
        session = await self._get_session()
        stmt = select(SagaStateTable).where(
            SagaStateTable.saga_type == saga_type,
            SagaStateTable.saga_id == saga_id,
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None
        return json.loads(row.state_json)


# ============================================================================
# ALIAS UNTUK BACKWARD COMPATIBILITY (diperlukan oleh __init__.py)
# ============================================================================
SagaStateStore = SQLAlchemySagaStateStoreRepository
SQLAlchemySagaStateStore = SQLAlchemySagaStateStoreRepository


# ============================================================================
# EXPORTS
# ============================================================================
__all__ = [
    "SQLAlchemySagaStateStore",
    "SQLAlchemySagaStateStoreRepository",
    "SagaStateStore",
    "SagaStateTable",
]
