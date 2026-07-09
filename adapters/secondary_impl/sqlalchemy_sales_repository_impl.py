#!/usr/bin/env python3
"""
Module: sqlalchemy_sales_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi SQLAlchemy untuk SalesRepositoryPort.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Column,
    Date,
    DateTime,
    Index,
    Numeric,
    String,
    Text,
    func,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

from ports.primary.sales_repository_port import SalesRepositoryPort

logger = logging.getLogger(__name__)

Base = declarative_base()


class SalesOrderTable(Base):
    __tablename__ = "sales_orders"
    __table_args__ = (
        Index("idx_so_legal_entity", "legal_entity_id"),
        Index("idx_so_number", "so_number", unique=True),
        Index("idx_so_customer", "customer_id"),
        Index("idx_so_status", "status"),
        Index("idx_so_order_date", "order_date"),
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    so_number = Column(String(50), nullable=False, unique=True)
    legal_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    customer_id = Column(PGUUID(as_uuid=True), nullable=False)
    customer_name = Column(String(200), nullable=False)
    order_date = Column(Date, nullable=False)
    requested_delivery_date = Column(Date, nullable=True)
    currency = Column(String(3), nullable=False, default="IDR")
    total_amount = Column(Numeric(20, 2), nullable=False, default=0)
    status = Column(String(20), nullable=False, default="DRAFT")
    items = Column(JSON, nullable=True)
    approval_date = Column(DateTime(timezone=True), nullable=True)
    approved_by = Column(PGUUID(as_uuid=True), nullable=True)
    notes = Column(Text, nullable=True)
    created_by = Column(PGUUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class SQLAlchemySalesRepository(SalesRepositoryPort):
    """
    Implementasi SQLAlchemy untuk SalesRepositoryPort.
    Semua return type mengikuti kontrak port: dict[str, Any] | None, list[dict[str, Any]], dll.
    """

    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    def _row_to_dict(self, row: SalesOrderTable) -> dict[str, Any]:
        """Convert ORM row to plain dict."""
        items = row.items if isinstance(row.items, list) else []
        return {
            "id": row.id,
            "so_number": row.so_number,
            "legal_entity_id": row.legal_entity_id,
            "customer_id": row.customer_id,
            "customer_name": row.customer_name,
            "order_date": row.order_date,
            "requested_delivery_date": row.requested_delivery_date,
            "currency": row.currency,
            "total_amount": row.total_amount,
            "status": row.status,
            "created_by": row.created_by,
            "created_at": row.created_at,
            "items": items,
            "approval_date": row.approval_date,
            "approved_by": row.approved_by,
            "notes": row.notes,
        }

    # ---------- Port methods with explicit return types ----------

    async def save_transaction(self, transaction: Any) -> None:
        session = await self._get_session()
        async with session.begin():
            stmt = select(SalesOrderTable).where(SalesOrderTable.id == transaction["id"])
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing:
                existing.so_number = transaction["so_number"]
                existing.customer_name = transaction["customer_name"]
                existing.order_date = transaction["order_date"]
                existing.requested_delivery_date = transaction.get("requested_delivery_date")
                existing.currency = transaction["currency"]
                existing.total_amount = transaction["total_amount"]
                existing.status = transaction["status"]
                existing.items = transaction.get("items")
                existing.approval_date = transaction.get("approval_date")
                existing.approved_by = transaction.get("approved_by")
                existing.notes = transaction.get("notes")
            else:
                new = SalesOrderTable(
                    id=transaction["id"],
                    so_number=transaction["so_number"],
                    legal_entity_id=transaction["legal_entity_id"],
                    customer_id=transaction["customer_id"],
                    customer_name=transaction["customer_name"],
                    order_date=transaction["order_date"],
                    requested_delivery_date=transaction.get("requested_delivery_date"),
                    currency=transaction["currency"],
                    total_amount=transaction["total_amount"],
                    status=transaction["status"],
                    items=transaction.get("items"),
                    approval_date=transaction.get("approval_date"),
                    approved_by=transaction.get("approved_by"),
                    notes=transaction.get("notes"),
                    created_by=transaction.get("created_by"),
                )
                session.add(new)

    async def get_by_id(self, transaction_id: UUID) -> dict[str, Any] | None:
        session = await self._get_session()
        stmt = select(SalesOrderTable).where(SalesOrderTable.id == transaction_id)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return self._row_to_dict(row)

    async def get_by_number(self, so_number: str, legal_entity_id: UUID) -> dict[str, Any] | None:
        session = await self._get_session()
        stmt = select(SalesOrderTable).where(
            SalesOrderTable.so_number == so_number,
            SalesOrderTable.legal_entity_id == legal_entity_id,
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return self._row_to_dict(row)

    async def list_by_period(
        self,
        legal_entity_id: UUID,
        from_date: date,
        to_date: date,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        session = await self._get_session()
        stmt = select(SalesOrderTable).where(
            SalesOrderTable.legal_entity_id == legal_entity_id,
            SalesOrderTable.order_date.between(from_date, to_date),
        )
        if status:
            stmt = stmt.where(SalesOrderTable.status == status)
        stmt = stmt.order_by(SalesOrderTable.order_date.desc())
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._row_to_dict(row) for row in rows]

    async def list_by_customer(
        self,
        customer_id: UUID,
        legal_entity_id: UUID,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        session = await self._get_session()
        stmt = select(SalesOrderTable).where(
            SalesOrderTable.customer_id == customer_id,
            SalesOrderTable.legal_entity_id == legal_entity_id,
        )
        if status:
            stmt = stmt.where(SalesOrderTable.status == status)
        stmt = stmt.offset(offset).limit(limit).order_by(SalesOrderTable.order_date.desc())
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._row_to_dict(row) for row in rows]

    async def delete_transaction(self, transaction_id: UUID) -> bool:
        """
        Soft delete sales order with pessimistic locking to prevent race conditions.
        LOCKING: SELECT FOR UPDATE ensures exclusive lock on the record.
        """
        session = await self._get_session()
        async with session.begin():
            # 1. Lock the row with SELECT FOR UPDATE
            stmt_lock = select(SalesOrderTable).where(
                SalesOrderTable.id == transaction_id
            ).with_for_update()
            result = await session.execute(stmt_lock)
            row = result.scalar_one_or_none()
            if not row:
                return False

            # 2. Update the locked row
            row.status = "DELETED"
            await session.flush()
            return True

    async def exists(self, transaction_id: UUID) -> bool:
        session = await self._get_session()
        stmt = select(func.count()).select_from(SalesOrderTable).where(SalesOrderTable.id == transaction_id)
        result = await session.execute(stmt)
        return result.scalar() > 0

    async def count_by_period(
        self,
        legal_entity_id: UUID,
        from_date: date,
        to_date: date,
        status: str | None = None,
    ) -> int:
        session = await self._get_session()
        stmt = select(func.count()).select_from(SalesOrderTable).where(
            SalesOrderTable.legal_entity_id == legal_entity_id,
            SalesOrderTable.order_date.between(from_date, to_date),
        )
        if status:
            stmt = stmt.where(SalesOrderTable.status == status)
        result = await session.execute(stmt)
        return result.scalar() or 0

    async def get_last_transaction_number(self, legal_entity_id: UUID) -> str | None:
        session = await self._get_session()
        stmt = (
            select(SalesOrderTable.so_number)
            .where(SalesOrderTable.legal_entity_id == legal_entity_id)
            .order_by(SalesOrderTable.created_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def search(
        self,
        legal_entity_id: UUID,
        query: str,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        session = await self._get_session()
        search_pattern = f"%{query}%"
        stmt = select(SalesOrderTable).where(
            SalesOrderTable.legal_entity_id == legal_entity_id,
            or_(
                SalesOrderTable.so_number.ilike(search_pattern),
                SalesOrderTable.customer_name.ilike(search_pattern),
            ),
        )
        if status:
            stmt = stmt.where(SalesOrderTable.status == status)
        stmt = stmt.offset(offset).limit(limit).order_by(SalesOrderTable.created_at.desc())
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._row_to_dict(row) for row in rows]

    async def get_total_by_period(
        self,
        legal_entity_id: UUID,
        from_date: date,
        to_date: date,
        status: str | None = None,
    ) -> dict[str, Any]:
        session = await self._get_session()
        stmt_amount = select(func.sum(SalesOrderTable.total_amount)).where(
            SalesOrderTable.legal_entity_id == legal_entity_id,
            SalesOrderTable.order_date.between(from_date, to_date),
        )
        if status:
            stmt_amount = stmt_amount.where(SalesOrderTable.status == status)
        total_amount_result = await session.execute(stmt_amount)
        total_amount = total_amount_result.scalar() or Decimal(0)

        stmt_count = select(func.count()).select_from(SalesOrderTable).where(
            SalesOrderTable.legal_entity_id == legal_entity_id,
            SalesOrderTable.order_date.between(from_date, to_date),
        )
        if status:
            stmt_count = stmt_count.where(SalesOrderTable.status == status)
        count_result = await session.execute(stmt_count)
        count = count_result.scalar() or 0

        return {
            "total_amount": float(total_amount),
            "count": count,
        }


# ============================================================================
# ALIAS UNTUK KOMPATIBILITAS
# ============================================================================

SQLAlchemySalesRepositoryImpl = SQLAlchemySalesRepository

__all__ = [
    "SQLAlchemySalesRepository",
    "SQLAlchemySalesRepositoryImpl",
    "SalesOrderTable",
]