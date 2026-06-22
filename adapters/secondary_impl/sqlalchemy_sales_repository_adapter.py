#!/usr/bin/env python3
"""
Module: sqlalchemy_sales_repository_adapter.py
Layer: Adapters (Secondary Implementation)
Responsibility: Real SQLAlchemy implementation of SalesRepositoryPort.
"""

from __future__ import annotations

import uuid
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime, String, Numeric, JSON, select, delete
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

logger = logging.getLogger(__name__)

Base = declarative_base()


class SalesOrderTable(Base):
    __tablename__ = "sales_orders"
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    legal_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    order_number = Column(String(50), nullable=False, unique=True)
    customer_id = Column(PGUUID(as_uuid=True), nullable=False)
    order_date = Column(DateTime(timezone=True), nullable=False)
    total_amount = Column(Numeric(18, 2), nullable=False)
    currency = Column(String(3), nullable=False, default="IDR")
    status = Column(String(50), nullable=False, default="draft")
    extra_data = Column(JSON, nullable=True)  # renamed from 'metadata'
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=datetime.utcnow)


class SQLAlchemySalesRepositoryAdapter:
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    async def get_sales_orders(self, legal_entity_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
        session = await self._get_session()
        stmt = select(SalesOrderTable)
        if legal_entity_id is not None:
            stmt = stmt.where(SalesOrderTable.legal_entity_id == legal_entity_id)
        stmt = stmt.order_by(SalesOrderTable.order_date.desc())
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [
            {
                "id": str(row.id),
                "order_number": row.order_number,
                "customer_id": str(row.customer_id),
                "order_date": row.order_date.isoformat(),
                "total_amount": float(row.total_amount),
                "currency": row.currency,
                "status": row.status,
                "extra_data": row.extra_data,
                "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
            for row in rows
        ]

    async def create_sales_order(self, data: dict[str, Any]) -> dict[str, Any]:
        session = await self._get_session()
        order = SalesOrderTable(
            id=uuid.uuid4(),
            legal_entity_id=data["legal_entity_id"],
            order_number=data["order_number"],
            customer_id=data["customer_id"],
            order_date=data.get("order_date", datetime.utcnow()),
            total_amount=data["total_amount"],
            currency=data.get("currency", "IDR"),
            status=data.get("status", "draft"),
            extra_data=data.get("extra_data"),
        )
        session.add(order)
        await session.flush()
        return {
            "id": str(order.id),
            "order_number": order.order_number,
            "customer_id": str(order.customer_id),
            "order_date": order.order_date.isoformat(),
            "total_amount": float(order.total_amount),
            "currency": order.currency,
            "status": order.status,
            "extra_data": order.extra_data,
            "created_at": order.created_at.isoformat(),
            "updated_at": order.updated_at.isoformat() if order.updated_at else None,
        }

    async def get_order_by_number(self, order_number: str) -> dict[str, Any] | None:
        session = await self._get_session()
        stmt = select(SalesOrderTable).where(SalesOrderTable.order_number == order_number)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None
        return {
            "id": str(row.id),
            "order_number": row.order_number,
            "customer_id": str(row.customer_id),
            "order_date": row.order_date.isoformat(),
            "total_amount": float(row.total_amount),
            "currency": row.currency,
            "status": row.status,
            "extra_data": row.extra_data,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    async def delete_order(self, order_id: uuid.UUID) -> bool:
        session = await self._get_session()
        stmt = delete(SalesOrderTable).where(SalesOrderTable.id == order_id)
        result = await session.execute(stmt)
        await session.flush()
        return result.rowcount > 0


__all__ = ["SalesOrderTable", "SQLAlchemySalesRepositoryAdapter"]