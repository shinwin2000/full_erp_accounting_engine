#!/usr/bin/env python3
"""
Module: sqlalchemy_cache_adapter.py
Layer: Adapters (Secondary Implementation)
Responsibility: Real SQLAlchemy implementation of CachePort.
Note: This is a database-backed cache, not a distributed cache like Redis.
      For production, you may still want Redis; but this provides a real fallback.
"""

from __future__ import annotations

import uuid
import json
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Column, DateTime, String, Text, select, delete
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

logger = logging.getLogger(__name__)

Base = declarative_base()


class CacheTable(Base):
    __tablename__ = "cache_entries"
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key = Column(String(255), nullable=False, unique=True)
    value = Column(Text, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class SQLAlchemyCacheAdapter:
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    async def get(self, key: str) -> Any | None:
        session = await self._get_session()
        now = datetime.utcnow()
        stmt = select(CacheTable).where(
            CacheTable.key == key,
            (CacheTable.expires_at.is_(None)) | (CacheTable.expires_at > now)
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None
        try:
            return json.loads(row.value)
        except json.JSONDecodeError:
            return row.value

    async def set(self, key: str, value: Any, ttl: int = 60) -> None:
        session = await self._get_session()
        expires_at = datetime.utcnow() + timedelta(seconds=ttl) if ttl > 0 else None
        # Upsert
        stmt = select(CacheTable).where(CacheTable.key == key)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if row:
            row.value = json.dumps(value) if not isinstance(value, str) else value
            row.expires_at = expires_at
        else:
            row = CacheTable(
                key=key,
                value=json.dumps(value) if not isinstance(value, str) else value,
                expires_at=expires_at,
            )
            session.add(row)
        await session.flush()

    async def delete(self, key: str) -> None:
        session = await self._get_session()
        stmt = delete(CacheTable).where(CacheTable.key == key)
        await session.execute(stmt)
        await session.flush()

    async def clear_expired(self) -> int:
        session = await self._get_session()
        stmt = delete(CacheTable).where(CacheTable.expires_at < datetime.utcnow())
        result = await session.execute(stmt)
        await session.flush()
        return result.rowcount


__all__ = ["CacheTable", "SQLAlchemyCacheAdapter"]