#!/usr/bin/env python3
"""
Module: sqlalchemy_customer_supplier_repository_port_impl.py
Adapter for CustomerCategory (from customer_supplier_repository_port)
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, String, Text, select, update
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

logger = logging.getLogger(__name__)

Base = declarative_base()


class CustomerCategoryTable(Base):
    __tablename__ = "customer_categories"
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    legal_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    code = Column(String(50), nullable=False, unique=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=datetime.utcnow)
    created_by = Column(PGUUID(as_uuid=True), nullable=True)


class SQLAlchemyCustomerCategoryAdapter:
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    async def get_categories(self, legal_entity_id: uuid.UUID) -> list[dict[str, Any]]:
        session = await self._get_session()
        stmt = select(CustomerCategoryTable).where(
            CustomerCategoryTable.legal_entity_id == legal_entity_id,
            CustomerCategoryTable.is_active == True,
        ).order_by(CustomerCategoryTable.code)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [
            {
                "id": str(row.id),
                "code": row.code,
                "name": row.name,
                "description": row.description,
                "is_active": row.is_active,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]

    async def get_category_by_code(self, code: str, legal_entity_id: uuid.UUID) -> dict[str, Any] | None:
        session = await self._get_session()
        stmt = select(CustomerCategoryTable).where(
            CustomerCategoryTable.code == code,
            CustomerCategoryTable.legal_entity_id == legal_entity_id,
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None
        return {
            "id": str(row.id),
            "code": row.code,
            "name": row.name,
            "description": row.description,
            "is_active": row.is_active,
            "created_at": row.created_at.isoformat(),
        }

    async def create_category(self, data: dict[str, Any]) -> dict[str, Any]:
        session = await self._get_session()
        category = CustomerCategoryTable(
            id=uuid.uuid4(),
            legal_entity_id=data["legal_entity_id"],
            code=data["code"],
            name=data["name"],
            description=data.get("description"),
            created_by=data.get("created_by"),
        )
        session.add(category)
        await session.flush()
        return {
            "id": str(category.id),
            "code": category.code,
            "name": category.name,
            "description": category.description,
            "is_active": category.is_active,
            "created_at": category.created_at.isoformat(),
        }

    async def update_category(self, category_id: uuid.UUID, data: dict[str, Any]) -> dict[str, Any]:
        """
        Update category with pessimistic locking to prevent race conditions.
        LOCKING: SELECT FOR UPDATE ensures exclusive lock on the record.
        """
        session = await self._get_session()
        async with session.begin():
            # 1. Lock the row with SELECT FOR UPDATE
            stmt_lock = select(CustomerCategoryTable).where(
                CustomerCategoryTable.id == category_id
            ).with_for_update()
            result = await session.execute(stmt_lock)
            row = result.scalar_one_or_none()
            if not row:
                raise ValueError(f"Category {category_id} not found")

            # 2. Update the locked row
            for key, value in data.items():
                if hasattr(row, key) and key not in ("id", "created_at", "legal_entity_id"):
                    setattr(row, key, value)
            row.updated_at = datetime.utcnow()
            await session.flush()

        return {
            "id": str(row.id),
            "code": row.code,
            "name": row.name,
            "description": row.description,
            "is_active": row.is_active,
            "updated_at": row.updated_at.isoformat(),
        }

    async def delete_category(self, category_id: uuid.UUID) -> bool:
        """
        Delete category with pessimistic locking to prevent race conditions.
        LOCKING: SELECT FOR UPDATE ensures exclusive lock on the record.
        """
        session = await self._get_session()
        async with session.begin():
            # 1. Lock the row with SELECT FOR UPDATE
            stmt_lock = select(CustomerCategoryTable).where(
                CustomerCategoryTable.id == category_id
            ).with_for_update()
            result = await session.execute(stmt_lock)
            row = result.scalar_one_or_none()
            if not row:
                return False

            # 2. Delete the locked row
            await session.delete(row)
            await session.flush()
            return True

    async def deactivate_category(self, category_id: uuid.UUID) -> bool:
        session = await self._get_session()
        stmt = (
            update(CustomerCategoryTable)
            .where(CustomerCategoryTable.id == category_id)
            .values(is_active=False, updated_at=datetime.utcnow())
        )
        result = await session.execute(stmt)
        await session.flush()
        return result.rowcount > 0


__all__ = ["CustomerCategoryTable", "SQLAlchemyCustomerCategoryAdapter"]
