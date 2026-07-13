#!/usr/bin/env python3
"""
Module: sqlalchemy_bill_of_materials_repository_impl.py
Layer: Adapters / Secondary / Implementation
Responsibility: SQLAlchemy implementation of BillOfMaterialsRepositoryPort.

Uses async SQLAlchemy 2.0 with PostgreSQL.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    delete,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base, relationship, selectinload

from ports.primary.bill_of_materials_repository_port import (
    BillOfMaterialsEntity,
    BillOfMaterialsRepositoryPort,
    BOMItem,
)

logger = logging.getLogger(__name__)

# ============================================================================
# SQLAlchemy ORM Models
# ============================================================================

Base = declarative_base()


class BOMTable(Base):
    __tablename__ = "bill_of_materials"
    __table_args__ = (
        Index("idx_bom_product", "product_id"),
        Index("idx_bom_status", "status"),
        Index("idx_bom_effective_date", "effective_date"),
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    bom_code = Column(String(50), nullable=False, unique=True)
    product_id = Column(PGUUID(as_uuid=True), nullable=False)
    product_code = Column(String(50), nullable=False)
    product_name = Column(String(200), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    quantity_per_assembly = Column(Numeric(20, 6), nullable=False)
    unit_of_measure = Column(String(10), nullable=False)
    status = Column(String(20), nullable=False, default="DRAFT")
    effective_date = Column(Date, nullable=True)
    expiry_date = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)
    created_by = Column(PGUUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    version_counter = Column(Integer, nullable=False, default=1)

    # Relationship
    items = relationship("BOMItemTable", back_populates="bom", cascade="all, delete-orphan")


class BOMItemTable(Base):
    __tablename__ = "bom_items"
    __table_args__ = (
        Index("idx_bom_item_bom", "bom_id"),
        Index("idx_bom_item_component", "component_id"),
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    bom_id = Column(
        PGUUID(as_uuid=True), ForeignKey("bill_of_materials.id", ondelete="CASCADE"), nullable=False
    )
    component_id = Column(PGUUID(as_uuid=True), nullable=False)
    component_code = Column(String(50), nullable=False)
    component_name = Column(String(200), nullable=False)
    quantity = Column(Numeric(20, 6), nullable=False)
    unit_of_measure = Column(String(10), nullable=False)
    scrap_percentage = Column(Numeric(10, 6), nullable=False, default=Decimal("0"))
    sub_bom_id = Column(PGUUID(as_uuid=True), nullable=True)
    notes = Column(Text, nullable=True)

    # Relationship
    bom = relationship("BOMTable", back_populates="items")


# ============================================================================
# Repository Implementation
# ============================================================================


class SQLAlchemyBillOfMaterialsRepository(BillOfMaterialsRepositoryPort):
    """SQLAlchemy implementation of BillOfMaterialsRepositoryPort."""

    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    def _to_domain_entity(self, bom_row: BOMTable) -> BillOfMaterialsEntity:
        items = [
            BOMItem(
                component_id=item.component_id,
                component_code=item.component_code,
                component_name=item.component_name,
                quantity=item.quantity,
                unit_of_measure=item.unit_of_measure,
                scrap_percentage=item.scrap_percentage,
                sub_bom_id=item.sub_bom_id,
                notes=item.notes,
            )
            for item in bom_row.items
        ]
        return BillOfMaterialsEntity(
            id=bom_row.id,
            bom_code=bom_row.bom_code,
            product_id=bom_row.product_id,
            product_code=bom_row.product_code,
            product_name=bom_row.product_name,
            version=bom_row.version,
            quantity_per_assembly=bom_row.quantity_per_assembly,
            unit_of_measure=bom_row.unit_of_measure,
            items=items,
            status=bom_row.status,
            effective_date=bom_row.effective_date,
            expiry_date=bom_row.expiry_date,
            notes=bom_row.notes,
            created_by=bom_row.created_by,
            created_at=bom_row.created_at,
            version_counter=bom_row.version_counter,
        )

    async def save(self, bom: BillOfMaterialsEntity) -> None:
        session = await self._get_session()
        async with session.begin():
            # Check if exists
            stmt = select(BOMTable).where(BOMTable.id == bom.id)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                # Update existing
                existing.bom_code = bom.bom_code
                existing.product_id = bom.product_id
                existing.product_code = bom.product_code
                existing.product_name = bom.product_name
                existing.version = bom.version
                existing.quantity_per_assembly = bom.quantity_per_assembly
                existing.unit_of_measure = bom.unit_of_measure
                existing.status = bom.status
                existing.effective_date = bom.effective_date
                existing.expiry_date = bom.expiry_date
                existing.notes = bom.notes
                existing.version_counter = bom.version_counter
                # Delete old items
                await session.execute(delete(BOMItemTable).where(BOMItemTable.bom_id == bom.id))
                # Add new items
                for item in bom.items:
                    item_row = BOMItemTable(
                        bom_id=bom.id,
                        component_id=item.component_id,
                        component_code=item.component_code,
                        component_name=item.component_name,
                        quantity=item.quantity,
                        unit_of_measure=item.unit_of_measure,
                        scrap_percentage=item.scrap_percentage,
                        sub_bom_id=item.sub_bom_id,
                        notes=item.notes,
                    )
                    session.add(item_row)
            else:
                # Insert new
                bom_row = BOMTable(
                    id=bom.id,
                    bom_code=bom.bom_code,
                    product_id=bom.product_id,
                    product_code=bom.product_code,
                    product_name=bom.product_name,
                    version=bom.version,
                    quantity_per_assembly=bom.quantity_per_assembly,
                    unit_of_measure=bom.unit_of_measure,
                    status=bom.status,
                    effective_date=bom.effective_date,
                    expiry_date=bom.expiry_date,
                    notes=bom.notes,
                    created_by=bom.created_by,
                    created_at=bom.created_at or datetime.utcnow(),
                    version_counter=bom.version_counter,
                )
                session.add(bom_row)
                await session.flush()
                for item in bom.items:
                    item_row = BOMItemTable(
                        bom_id=bom.id,
                        component_id=item.component_id,
                        component_code=item.component_code,
                        component_name=item.component_name,
                        quantity=item.quantity,
                        unit_of_measure=item.unit_of_measure,
                        scrap_percentage=item.scrap_percentage,
                        sub_bom_id=item.sub_bom_id,
                        notes=item.notes,
                    )
                    session.add(item_row)

    async def get_by_id(self, bom_id: UUID) -> BillOfMaterialsEntity | None:
        session = await self._get_session()
        stmt = (
            select(BOMTable).options(selectinload(BOMTable.items)).where(BOMTable.id == bom_id)
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None
        return self._to_domain_entity(row)

    async def get_by_code(
        self, bom_code: str, legal_entity_id: UUID
    ) -> BillOfMaterialsEntity | None:
        # Note: legal_entity_id not directly in BOMTable; may need join to product.
        # For simplicity, we ignore legal_entity_id or assume product_id links to legal entity.
        session = await self._get_session()
        stmt = (
            select(BOMTable)
            .options(selectinload(BOMTable.items))
            .where(BOMTable.bom_code == bom_code)
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None
        return self._to_domain_entity(row)

    async def get_active_bom(
        self, product_id: UUID, as_of_date: date
    ) -> BillOfMaterialsEntity | None:
        session = await self._get_session()
        stmt = (
            select(BOMTable)
            .options(selectinload(BOMTable.items))
            .where(
                BOMTable.product_id == product_id,
                BOMTable.status == "ACTIVE",
                BOMTable.effective_date <= as_of_date,
                or_(BOMTable.expiry_date.is_(None), BOMTable.expiry_date >= as_of_date),
            )
            .order_by(BOMTable.version.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None
        return self._to_domain_entity(row)

    async def get_bom_by_product_and_version(
        self, product_id: UUID, version: int
    ) -> BillOfMaterialsEntity | None:
        session = await self._get_session()
        stmt = (
            select(BOMTable)
            .options(selectinload(BOMTable.items))
            .where(BOMTable.product_id == product_id, BOMTable.version == version)
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None
        return self._to_domain_entity(row)

    async def list_boms_by_product(
        self, product_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[BillOfMaterialsEntity]:
        session = await self._get_session()
        stmt = (
            select(BOMTable)
            .options(selectinload(BOMTable.items))
            .where(BOMTable.product_id == product_id)
            .order_by(BOMTable.version.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._to_domain_entity(row) for row in rows]

    async def get_last_bom_code(self, legal_entity_id: UUID) -> str | None:
        session = await self._get_session()
        # This assumes bom_code contains prefix. For simplicity, return the latest BOM code.
        stmt = select(BOMTable.bom_code).order_by(BOMTable.created_at.desc()).limit(1)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_status(self, bom_id: UUID, new_status: str, updated_by: UUID) -> None:
        """
        Update BOM status with pessimistic locking to prevent race conditions.
        LOCKING: SELECT FOR UPDATE ensures exclusive lock on the record.
        """
        session = await self._get_session()
        async with session.begin():
            # 1. Lock the row with SELECT FOR UPDATE
            stmt_lock = select(BOMTable).where(BOMTable.id == bom_id).with_for_update()
            result = await session.execute(stmt_lock)
            row = result.scalar_one_or_none()
            if not row:
                raise ValueError(f"Bill of Materials {bom_id} not found")

            # 2. Update the locked row
            row.status = new_status
            logger.info(f"BOM {bom_id} status updated to {new_status} by {updated_by}")

    async def delete(self, bom_id: UUID) -> None:
        """
        Delete BOM with pessimistic locking to prevent race conditions.
        LOCKING: SELECT FOR UPDATE ensures exclusive lock on the record.
        """
        session = await self._get_session()
        async with session.begin():
            # 1. Lock the row with SELECT FOR UPDATE
            stmt_lock = select(BOMTable).where(BOMTable.id == bom_id).with_for_update()
            result = await session.execute(stmt_lock)
            row = result.scalar_one_or_none()
            if not row:
                raise ValueError(f"Bill of Materials {bom_id} not found")

            # 2. Delete the locked row
            await session.delete(row)
            await session.flush()
            logger.info(f"BOM {bom_id} deleted")


__all__ = ["BOMItemTable", "BOMTable", "SQLAlchemyBillOfMaterialsRepository"]
