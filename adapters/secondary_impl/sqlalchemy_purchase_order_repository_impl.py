#!/usr/bin/env python3
"""
Module: sqlalchemy_purchase_order_repository_impl.py
Layer: Adapters / Secondary / Implementation
Responsibility: SQLAlchemy implementation of PurchaseOrderRepositoryPort.
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

from ports.primary.purchase_order_repository_port import (
    PurchaseOrderEntity,
    PurchaseOrderRepositoryPort,
)

logger = logging.getLogger(__name__)

Base = declarative_base()


class PurchaseOrderTable(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        Index("idx_po_legal_entity", "legal_entity_id"),
        Index("idx_po_number", "po_number", unique=True),
        Index("idx_po_supplier", "supplier_id"),
        Index("idx_po_status", "status"),
        Index("idx_po_order_date", "order_date"),
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    po_number = Column(String(50), nullable=False, unique=True)
    legal_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    supplier_id = Column(PGUUID(as_uuid=True), nullable=False)
    supplier_name = Column(String(200), nullable=False)
    order_date = Column(Date, nullable=False)
    expected_delivery_date = Column(Date, nullable=True)
    currency = Column(String(3), nullable=False, default="IDR")
    total_amount = Column(Numeric(20, 2), nullable=False, default=0)
    status = Column(String(20), nullable=False, default="DRAFT")
    items = Column(JSON, nullable=True)  # Store items as JSON for simplicity
    approval_date = Column(DateTime(timezone=True), nullable=True)
    approved_by = Column(PGUUID(as_uuid=True), nullable=True)
    notes = Column(Text, nullable=True)
    created_by = Column(PGUUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class SQLAlchemyPurchaseOrderRepository(PurchaseOrderRepositoryPort):
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    async def save(self, po: PurchaseOrderEntity) -> None:
        session = await self._get_session()
        async with session.begin():
            stmt = select(PurchaseOrderTable).where(PurchaseOrderTable.id == po.id)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing:
                existing.po_number = po.po_number
                existing.supplier_name = po.supplier_name
                existing.order_date = po.order_date
                existing.expected_delivery_date = po.expected_delivery_date
                existing.currency = po.currency
                existing.total_amount = po.total_amount
                existing.status = po.status
                existing.items = (
                    [item.__dict__ if hasattr(item, "__dict__") else item for item in po.items]
                    if po.items
                    else None
                )
                existing.approval_date = po.approval_date
                existing.approved_by = po.approved_by
                existing.notes = po.notes
            else:
                new = PurchaseOrderTable(
                    id=po.id,
                    po_number=po.po_number,
                    legal_entity_id=po.legal_entity_id,
                    supplier_id=po.supplier_id,
                    supplier_name=po.supplier_name,
                    order_date=po.order_date,
                    expected_delivery_date=po.expected_delivery_date,
                    currency=po.currency,
                    total_amount=po.total_amount,
                    status=po.status,
                    items=[
                        item.__dict__ if hasattr(item, "__dict__") else item for item in po.items
                    ]
                    if po.items
                    else None,
                    approval_date=po.approval_date,
                    approved_by=po.approved_by,
                    notes=po.notes,
                    created_by=po.created_by,
                )
                session.add(new)

    async def get_by_id(self, po_id: UUID) -> PurchaseOrderEntity | None:
        session = await self._get_session()
        stmt = select(PurchaseOrderTable).where(PurchaseOrderTable.id == po_id)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None
        return self._to_entity(row)

    async def get_by_number(self, po_number: str) -> PurchaseOrderEntity | None:
        session = await self._get_session()
        stmt = select(PurchaseOrderTable).where(PurchaseOrderTable.po_number == po_number)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._to_entity(row) if row else None

    async def list_by_supplier(
        self, supplier_id: UUID, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[PurchaseOrderEntity]:
        session = await self._get_session()
        stmt = (
            select(PurchaseOrderTable)
            .where(
                PurchaseOrderTable.supplier_id == supplier_id,
                PurchaseOrderTable.legal_entity_id == legal_entity_id,
            )
            .offset(offset)
            .limit(limit)
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._to_entity(row) for row in rows]

    async def list_by_status(
        self, legal_entity_id: UUID, status: str, limit: int = 100, offset: int = 0
    ) -> list[PurchaseOrderEntity]:
        session = await self._get_session()
        stmt = (
            select(PurchaseOrderTable)
            .where(
                PurchaseOrderTable.legal_entity_id == legal_entity_id,
                PurchaseOrderTable.status == status,
            )
            .offset(offset)
            .limit(limit)
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._to_entity(row) for row in rows]

    async def list_by_date_range(
        self, legal_entity_id: UUID, from_date: date, to_date: date, limit: int = 100
    ) -> list[PurchaseOrderEntity]:
        session = await self._get_session()
        stmt = (
            select(PurchaseOrderTable)
            .where(
                PurchaseOrderTable.legal_entity_id == legal_entity_id,
                PurchaseOrderTable.order_date.between(from_date, to_date),
            )
            .limit(limit)
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._to_entity(row) for row in rows]

    async def get_last_po_number(self, legal_entity_id: UUID) -> str | None:
        session = await self._get_session()
        stmt = (
            select(PurchaseOrderTable.po_number)
            .where(PurchaseOrderTable.legal_entity_id == legal_entity_id)
            .order_by(PurchaseOrderTable.created_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_status(self, po_id: UUID, new_status: str, updated_by: UUID) -> None:
        session = await self._get_session()
        async with session.begin():
            stmt = (
                update(PurchaseOrderTable)
                .where(PurchaseOrderTable.id == po_id)
                .values(status=new_status)
            )
            await session.execute(stmt)

    async def delete(self, po_id: UUID) -> None:
        session = await self._get_session()
        async with session.begin():
            await session.execute(delete(PurchaseOrderTable).where(PurchaseOrderTable.id == po_id))

    def _to_entity(self, row):
        from ports.primary.purchase_order_repository_port import PurchaseOrderEntity

        items = row.items if isinstance(row.items, list) else []
        return PurchaseOrderEntity(
            id=row.id,
            po_number=row.po_number,
            legal_entity_id=row.legal_entity_id,
            supplier_id=row.supplier_id,
            supplier_name=row.supplier_name,
            order_date=row.order_date,
            expected_delivery_date=row.expected_delivery_date,
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


__all__ = ["PurchaseOrderTable", "SQLAlchemyPurchaseOrderRepository"]
