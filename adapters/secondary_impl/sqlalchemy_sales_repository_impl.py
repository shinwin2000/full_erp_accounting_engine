#!/usr/bin/env python3
"""
Module: sqlalchemy_sales_repository_adapter_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi port SalesRepositoryPort dengan SQLAlchemy.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Column, DateTime, Numeric, String, Text, select, update, delete
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

from ports.primary.sales_repository_port import SalesRepositoryPort

logger = logging.getLogger(__name__)

Base = declarative_base()


class SalesOrderTable(Base):
    __tablename__ = "sales_orders"
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    legal_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    order_number = Column(String(50), nullable=False, unique=True)
    customer_id = Column(PGUUID(as_uuid=True), nullable=False)
    total_amount = Column(Numeric(20, 2), nullable=False, default=0)
    status = Column(String(50), nullable=False, default="draft")
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=datetime.utcnow)
    created_by = Column(PGUUID(as_uuid=True), nullable=True)


class SQLAlchemySalesRepositoryAdapter(SalesRepositoryPort):
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    async def get_sales_orders(self, legal_entity_id: uuid.UUID) -> list[dict[str, Any]]:
        session = await self._get_session()
        stmt = select(SalesOrderTable).where(
            SalesOrderTable.legal_entity_id == legal_entity_id
        ).order_by(SalesOrderTable.created_at.desc())
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [
            {
                "id": str(row.id),
                "order_number": row.order_number,
                "customer_id": str(row.customer_id),
                "total_amount": float(row.total_amount),
                "status": row.status,
                "description": row.description,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]

    async def get_sales_order_by_id(self, order_id: uuid.UUID) -> dict[str, Any] | None:
        session = await self._get_session()
        stmt = select(SalesOrderTable).where(SalesOrderTable.id == order_id)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None
        return {
            "id": str(row.id),
            "order_number": row.order_number,
            "customer_id": str(row.customer_id),
            "total_amount": float(row.total_amount),
            "status": row.status,
            "description": row.description,
            "created_at": row.created_at.isoformat(),
        }

    async def create_sales_order(self, data: dict[str, Any]) -> dict[str, Any]:
        session = await self._get_session()
        order = SalesOrderTable(
            id=uuid.uuid4(),
            legal_entity_id=data["legal_entity_id"],
            order_number=data["order_number"],
            customer_id=data["customer_id"],
            total_amount=data.get("total_amount", 0),
            status=data.get("status", "draft"),
            description=data.get("description"),
            created_by=data.get("created_by"),
        )
        session.add(order)
        await session.flush()
        return {
            "id": str(order.id),
            "order_number": order.order_number,
            "customer_id": str(order.customer_id),
            "total_amount": float(order.total_amount),
            "status": order.status,
            "created_at": order.created_at.isoformat(),
        }

    async def update_sales_order(self, order_id: uuid.UUID, data: dict[str, Any]) -> dict[str, Any]:
        session = await self._get_session()
        stmt = select(SalesOrderTable).where(SalesOrderTable.id == order_id)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            raise ValueError(f"Order {order_id} not found")
        for key, value in data.items():
            if hasattr(row, key) and key not in ("id", "order_number", "created_at", "legal_entity_id"):
                setattr(row, key, value)
        row.updated_at = datetime.utcnow()
        await session.flush()
        return {
            "id": str(row.id),
            "order_number": row.order_number,
            "customer_id": str(row.customer_id),
            "total_amount": float(row.total_amount),
            "status": row.status,
            "updated_at": row.updated_at.isoformat(),
        }

    async def delete_sales_order(self, order_id: uuid.UUID) -> bool:
        session = await self._get_session()
        stmt = delete(SalesOrderTable).where(SalesOrderTable.id == order_id)
        result = await session.execute(stmt)
        await session.flush()
        return result.rowcount > 0

    async def update_order_status(self, order_id: uuid.UUID, status: str) -> bool:
        session = await self._get_session()
        stmt = (
            update(SalesOrderTable)
            .where(SalesOrderTable.id == order_id)
            .values(status=status, updated_at=datetime.utcnow())
        )
        result = await session.execute(stmt)
        await session.flush()
        return result.rowcount > 0


__all__ = [
    "SalesOrderTable",
    "SQLAlchemySalesRepositoryAdapter",
]