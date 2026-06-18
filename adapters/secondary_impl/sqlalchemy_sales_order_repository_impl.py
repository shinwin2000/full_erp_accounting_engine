#!/usr/bin/env python3
"""
Module: sqlalchemy_sales_order_repository_impl.py
Layer: Adapters / Secondary / Implementation
Responsibility: SQLAlchemy implementation of SalesOrderRepositoryPort.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
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
    delete,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

from ports.primary.sales_order_repository_port import SalesOrderEntity, SalesOrderRepositoryPort

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


class SQLAlchemySalesOrderRepository(SalesOrderRepositoryPort):
    def __init__(self, session_factory):
        self._session_factory = session_factory

    async def _get_session(self) -> AsyncSession:
        return self._session_factory()

    async def save(self, so: SalesOrderEntity) -> None:
        async with await self._get_session() as session, session.begin():
            stmt = select(SalesOrderTable).where(SalesOrderTable.id == so.id)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing:
                existing.so_number = so.so_number
                existing.customer_name = so.customer_name
                existing.order_date = so.order_date
                existing.requested_delivery_date = so.requested_delivery_date
                existing.currency = so.currency
                existing.total_amount = so.total_amount
                existing.status = so.status
                existing.items = (
                    [item.__dict__ if hasattr(item, "__dict__") else item for item in so.items]
                    if so.items
                    else None
                )
                existing.approval_date = so.approval_date
                existing.approved_by = so.approved_by
                existing.notes = so.notes
            else:
                new = SalesOrderTable(
                    id=so.id,
                    so_number=so.so_number,
                    legal_entity_id=so.legal_entity_id,
                    customer_id=so.customer_id,
                    customer_name=so.customer_name,
                    order_date=so.order_date,
                    requested_delivery_date=so.requested_delivery_date,
                    currency=so.currency,
                    total_amount=so.total_amount,
                    status=so.status,
                    items=[
                        item.__dict__ if hasattr(item, "__dict__") else item for item in so.items
                    ]
                    if so.items
                    else None,
                    approval_date=so.approval_date,
                    approved_by=so.approved_by,
                    notes=so.notes,
                    created_by=so.created_by,
                )
                session.add(new)

    async def get_by_id(self, so_id: UUID) -> SalesOrderEntity | None:
        async with await self._get_session() as session:
            stmt = select(SalesOrderTable).where(SalesOrderTable.id == so_id)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            return self._to_entity(row) if row else None

    async def get_by_number(self, so_number: str) -> SalesOrderEntity | None:
        async with await self._get_session() as session:
            stmt = select(SalesOrderTable).where(SalesOrderTable.so_number == so_number)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            return self._to_entity(row) if row else None

    async def list_by_customer(
        self, customer_id: UUID, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[SalesOrderEntity]:
        async with await self._get_session() as session:
            stmt = (
                select(SalesOrderTable)
                .where(
                    SalesOrderTable.customer_id == customer_id,
                    SalesOrderTable.legal_entity_id == legal_entity_id,
                )
                .offset(offset)
                .limit(limit)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [self._to_entity(row) for row in rows]

    async def list_by_status(
        self, legal_entity_id: UUID, status: str, limit: int = 100, offset: int = 0
    ) -> list[SalesOrderEntity]:
        async with await self._get_session() as session:
            stmt = (
                select(SalesOrderTable)
                .where(
                    SalesOrderTable.legal_entity_id == legal_entity_id,
                    SalesOrderTable.status == status,
                )
                .offset(offset)
                .limit(limit)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [self._to_entity(row) for row in rows]

    async def list_by_date_range(
        self, legal_entity_id: UUID, from_date: date, to_date: date, limit: int = 100
    ) -> list[SalesOrderEntity]:
        async with await self._get_session() as session:
            stmt = (
                select(SalesOrderTable)
                .where(
                    SalesOrderTable.legal_entity_id == legal_entity_id,
                    SalesOrderTable.order_date.between(from_date, to_date),
                )
                .limit(limit)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [self._to_entity(row) for row in rows]

    async def get_last_so_number(self, legal_entity_id: UUID) -> str | None:
        async with await self._get_session() as session:
            stmt = (
                select(SalesOrderTable.so_number)
                .where(SalesOrderTable.legal_entity_id == legal_entity_id)
                .order_by(SalesOrderTable.created_at.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def update_status(self, so_id: UUID, new_status: str, updated_by: UUID) -> None:
        async with await self._get_session() as session, session.begin():
            stmt = (
                update(SalesOrderTable).where(SalesOrderTable.id == so_id).values(status=new_status)
            )
            await session.execute(stmt)

    async def delete(self, so_id: UUID) -> None:
        async with await self._get_session() as session, session.begin():
            await session.execute(delete(SalesOrderTable).where(SalesOrderTable.id == so_id))

    def _to_entity(self, row):
        items = row.items if isinstance(row.items, list) else []
        return SalesOrderEntity(
            id=row.id,
            so_number=row.so_number,
            legal_entity_id=row.legal_entity_id,
            customer_id=row.customer_id,
            customer_name=row.customer_name,
            order_date=row.order_date,
            requested_delivery_date=row.requested_delivery_date,
            currency=row.currency,
            total_amount=row.total_amount,
            status=row.status,
            created_by=row.created_by,
            created_at=row.created_at,
            items=items,
            approval_date=row.approval_date,
            approved_by=row.approved_by,
            notes=row.notes,
        )


__all__ = ["SQLAlchemySalesOrderRepository", "SalesOrderTable"]
