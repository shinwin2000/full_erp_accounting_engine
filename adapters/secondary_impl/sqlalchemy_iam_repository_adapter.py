#!/usr/bin/env python3
"""
Module: sqlalchemy_iam_repository_adapter.py
Layer: Adapters (Secondary Implementation)
Responsibility: Real SQLAlchemy implementation of IAMRepositoryPort.
"""

from __future__ import annotations

import uuid
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, String, select, delete
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

logger = logging.getLogger(__name__)

Base = declarative_base()


class IAMUserTable(Base):
    __tablename__ = "iam_users"
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    legal_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    username = Column(String(100), nullable=False, unique=True)
    email = Column(String(200), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class SQLAlchemyIAMRepositoryAdapter:
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    async def get_users(self, legal_entity_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
        session = await self._get_session()
        stmt = select(IAMUserTable)
        if legal_entity_id is not None:
            stmt = stmt.where(IAMUserTable.legal_entity_id == legal_entity_id)
        stmt = stmt.order_by(IAMUserTable.username)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [
            {
                "id": str(row.id),
                "username": row.username,
                "email": row.email,
                "is_active": row.is_active,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]

    async def create_user(self, data: dict[str, Any]) -> dict[str, Any]:
        session = await self._get_session()
        user = IAMUserTable(
            id=uuid.uuid4(),
            legal_entity_id=data["legal_entity_id"],
            username=data["username"],
            email=data.get("email"),
            is_active=data.get("is_active", True),
        )
        session.add(user)
        await session.flush()
        return {
            "id": str(user.id),
            "username": user.username,
            "email": user.email,
            "is_active": user.is_active,
            "created_at": user.created_at.isoformat(),
        }

    async def delete_user(self, user_id: uuid.UUID) -> bool:
        session = await self._get_session()
        stmt = delete(IAMUserTable).where(IAMUserTable.id == user_id)
        result = await session.execute(stmt)
        await session.flush()
        return result.rowcount > 0

    async def get_user_by_id(self, user_id: uuid.UUID) -> dict[str, Any] | None:
        session = await self._get_session()
        stmt = select(IAMUserTable).where(IAMUserTable.id == user_id)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None
        return {
            "id": str(row.id),
            "username": row.username,
            "email": row.email,
            "is_active": row.is_active,
            "created_at": row.created_at.isoformat(),
        }


__all__ = ["IAMUserTable", "SQLAlchemyIAMRepositoryAdapter"]