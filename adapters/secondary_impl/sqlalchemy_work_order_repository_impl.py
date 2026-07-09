#!/usr/bin/env python3
"""
Module: sqlalchemy_work_order_repository_impl.py
Layer: Adapters / Secondary / Implementation
Responsibility: SQLAlchemy implementation of WorkOrderRepositoryPort.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
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

from ports.primary.work_order_repository_port import WorkOrderEntity, WorkOrderRepositoryPort

logger = logging.getLogger(__name__)

Base = declarative_base()


class WorkOrderTable(Base):
    __tablename__ = "work_orders"
    __table_args__ = (
        Index("idx_wo_legal_entity", "legal_entity_id"),
        Index("idx_wo_number", "wo_number", unique=True),
        Index("idx_wo_product", "product_id"),
        Index("idx_wo_status", "status"),
        Index("idx_wo_dates", "planned_start_date", "planned_end_date"),
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    wo_number = Column(String(50), nullable=False, unique=True)
    legal_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    product_id = Column(PGUUID(as_uuid=True), nullable=False)
    product_code = Column(String(50), nullable=False)
    product_name = Column(String(200), nullable=False)
    planned_quantity = Column(Numeric(20, 2), nullable=False)
    completed_quantity = Column(Numeric(20, 2), nullable=False, default=0)
    status = Column(String(20), nullable=False, default="DRAFT")
    planned_start_date = Column(Date, nullable=False)
    planned_end_date = Column(Date, nullable=False)
    actual_start_date = Column(Date, nullable=True)
    actual_end_date = Column(Date, nullable=True)
    bom_id = Column(PGUUID(as_uuid=True), nullable=True)
    routing_id = Column(PGUUID(as_uuid=True), nullable=True)
    notes = Column(Text, nullable=True)
    created_by = Column(PGUUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=datetime.utcnow)


class SQLAlchemyWorkOrderRepository(WorkOrderRepositoryPort):
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    async def save(self, work_order: WorkOrderEntity) -> None:
        session = await self._get_session()
        async with session.begin():
            stmt = select(WorkOrderTable).where(WorkOrderTable.id == work_order.id)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing:
                existing.wo_number = work_order.wo_number
                existing.product_id = work_order.product_id
                existing.product_code = work_order.product_code
                existing.product_name = work_order.product_name
                existing.planned_quantity = work_order.planned_quantity
                existing.completed_quantity = work_order.completed_quantity
                existing.status = work_order.status
                existing.planned_start_date = work_order.planned_start_date
                existing.planned_end_date = work_order.planned_end_date
                existing.actual_start_date = work_order.actual_start_date
                existing.actual_end_date = work_order.actual_end_date
                existing.bom_id = work_order.bom_id
                existing.routing_id = work_order.routing_id
                existing.notes = work_order.notes
                existing.updated_at = datetime.utcnow()
            else:
                new = WorkOrderTable(
                    id=work_order.id,
                    wo_number=work_order.wo_number,
                    legal_entity_id=work_order.legal_entity_id,
                    product_id=work_order.product_id,
                    product_code=work_order.product_code,
                    product_name=work_order.product_name,
                    planned_quantity=work_order.planned_quantity,
                    completed_quantity=work_order.completed_quantity,
                    status=work_order.status,
                    planned_start_date=work_order.planned_start_date,
                    planned_end_date=work_order.planned_end_date,
                    actual_start_date=work_order.actual_start_date,
                    actual_end_date=work_order.actual_end_date,
                    bom_id=work_order.bom_id,
                    routing_id=work_order.routing_id,
                    notes=work_order.notes,
                    created_by=work_order.created_by,
                )
                session.add(new)

    async def update(self, work_order: WorkOrderEntity) -> None:
        await self.save(work_order)

    async def get_by_id(self, wo_id: UUID) -> WorkOrderEntity | None:
        session = await self._get_session()
        stmt = select(WorkOrderTable).where(WorkOrderTable.id == wo_id)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._to_entity(row) if row else None

    async def get_by_number(self, wo_number: str) -> WorkOrderEntity | None:
        session = await self._get_session()
        stmt = select(WorkOrderTable).where(WorkOrderTable.wo_number == wo_number)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._to_entity(row) if row else None

    async def list_by_legal_entity(
        self, legal_entity_id: UUID, status: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[WorkOrderEntity]:
        session = await self._get_session()
        stmt = select(WorkOrderTable).where(WorkOrderTable.legal_entity_id == legal_entity_id)
        if status:
            stmt = stmt.where(WorkOrderTable.status == status)
        stmt = stmt.offset(offset).limit(limit)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._to_entity(row) for row in rows]

    async def list_by_product(
        self, product_id: UUID, legal_entity_id: UUID, status: str | None = None
    ) -> list[WorkOrderEntity]:
        session = await self._get_session()
        stmt = select(WorkOrderTable).where(
            WorkOrderTable.product_id == product_id,
            WorkOrderTable.legal_entity_id == legal_entity_id,
        )
        if status:
            stmt = stmt.where(WorkOrderTable.status == status)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._to_entity(row) for row in rows]

    async def list_by_date_range(
        self, legal_entity_id: UUID, from_date: date, to_date: date
    ) -> list[WorkOrderEntity]:
        session = await self._get_session()
        stmt = select(WorkOrderTable).where(
            WorkOrderTable.legal_entity_id == legal_entity_id,
            WorkOrderTable.planned_start_date >= from_date,
            WorkOrderTable.planned_end_date <= to_date,
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._to_entity(row) for row in rows]

    async def get_last_wo_number(self, legal_entity_id: UUID) -> str | None:
        session = await self._get_session()
        stmt = (
            select(WorkOrderTable.wo_number)
            .where(WorkOrderTable.legal_entity_id == legal_entity_id)
            .order_by(WorkOrderTable.created_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_status(self, wo_id: UUID, new_status: str, updated_by: UUID) -> None:
        """
        Update work order status with pessimistic locking to prevent race conditions.
        LOCKING: SELECT FOR UPDATE ensures exclusive lock on the record.
        """
        session = await self._get_session()
        async with session.begin():
            # 1. Lock the row with SELECT FOR UPDATE
            stmt_lock = select(WorkOrderTable).where(WorkOrderTable.id == wo_id).with_for_update()
            result = await session.execute(stmt_lock)
            row = result.scalar_one_or_none()
            if not row:
                raise ValueError(f"Work order {wo_id} not found")

            # 2. Update the locked row
            row.status = new_status
            row.updated_at = datetime.utcnow()
            # Optionally store updated_by if needed (add column if required)
            # row.updated_by = updated_by
            await session.flush()

    async def delete(self, wo_id: UUID) -> None:
        """
        Delete work order with pessimistic locking to prevent race conditions.
        LOCKING: SELECT FOR UPDATE ensures exclusive lock on the record.
        """
        session = await self._get_session()
        async with session.begin():
            # 1. Lock the row with SELECT FOR UPDATE
            stmt_lock = select(WorkOrderTable).where(WorkOrderTable.id == wo_id).with_for_update()
            result = await session.execute(stmt_lock)
            row = result.scalar_one_or_none()
            if not row:
                raise ValueError(f"Work order {wo_id} not found")

            # 2. Delete the locked row
            await session.delete(row)
            await session.flush()

    def _to_entity(self, row):
        return WorkOrderEntity(
            id=row.id,
            wo_number=row.wo_number,
            legal_entity_id=row.legal_entity_id,
            product_id=row.product_id,
            product_code=row.product_code,
            product_name=row.product_name,
            planned_quantity=row.planned_quantity,
            completed_quantity=row.completed_quantity,
            status=row.status,
            planned_start_date=row.planned_start_date,
            planned_end_date=row.planned_end_date,
            actual_start_date=row.actual_start_date,
            actual_end_date=row.actual_end_date,
            bom_id=row.bom_id,
            routing_id=row.routing_id,
            created_by=row.created_by,
            created_at=row.created_at,
            notes=row.notes,
        )


__all__ = ["SQLAlchemyWorkOrderRepository", "WorkOrderTable"]