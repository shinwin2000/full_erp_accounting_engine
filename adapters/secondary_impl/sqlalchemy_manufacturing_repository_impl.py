#!/usr/bin/env python3
"""
Module: sqlalchemy_manufacturing_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi repository Manufacturing (BOM, Work Order, Routing) menggunakan SQLAlchemy.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence_orm.bill_of_materials_table import (
    BillOfMaterialsLineTable,
    BillOfMaterialsTable,
)
from infrastructure.persistence_orm.manufacturing_cost_card_table import ManufacturingCostCardTable
from infrastructure.persistence_orm.manufacturing_work_order_table import (
    ManufacturingWorkOrderTable,
)
from ports.primary.manufacturing_repository_port import ManufacturingRepositoryPort


class SQLAlchemyManufacturingRepository(ManufacturingRepositoryPort):
    def __init__(self, session: AsyncSession):
        self._session = session

    # ========== Bill of Materials ==========
    async def save_bom(self, bom: BillOfMaterialsTable) -> BillOfMaterialsTable:
        self._session.add(bom)
        await self._session.flush()
        return bom

    async def get_bom_by_id(self, bom_id: uuid.UUID) -> BillOfMaterialsTable | None:
        stmt = select(BillOfMaterialsTable).where(BillOfMaterialsTable.id == bom_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_bom_by_product(
        self, product_id: uuid.UUID, legal_entity_id: uuid.UUID
    ) -> list[BillOfMaterialsTable]:
        stmt = (
            select(BillOfMaterialsTable)
            .where(
                BillOfMaterialsTable.product_id == product_id,
                BillOfMaterialsTable.legal_entity_id == legal_entity_id,
            )
            .order_by(BillOfMaterialsTable.version.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def save_bom_line(self, line: BillOfMaterialsLineTable) -> BillOfMaterialsLineTable:
        self._session.add(line)
        await self._session.flush()
        return line

    async def get_bom_lines(self, bom_id: uuid.UUID) -> list[BillOfMaterialsLineTable]:
        stmt = (
            select(BillOfMaterialsLineTable)
            .where(BillOfMaterialsLineTable.bom_id == bom_id)
            .order_by(BillOfMaterialsLineTable.line_number)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # ========== Work Order ==========
    async def save_work_order(self, wo: ManufacturingWorkOrderTable) -> ManufacturingWorkOrderTable:
        self._session.add(wo)
        await self._session.flush()
        return wo

    async def get_work_order_by_id(self, wo_id: uuid.UUID) -> ManufacturingWorkOrderTable | None:
        stmt = select(ManufacturingWorkOrderTable).where(ManufacturingWorkOrderTable.id == wo_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_work_orders_by_status(
        self, status: str, legal_entity_id: uuid.UUID
    ) -> list[ManufacturingWorkOrderTable]:
        stmt = select(ManufacturingWorkOrderTable).where(
            ManufacturingWorkOrderTable.status == status,
            ManufacturingWorkOrderTable.legal_entity_id == legal_entity_id,
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def update_work_order_status(self, wo_id: uuid.UUID, status: str) -> None:
        stmt = (
            update(ManufacturingWorkOrderTable)
            .where(ManufacturingWorkOrderTable.id == wo_id)
            .values(status=status)
        )
        await self._session.execute(stmt)

    # ========== Cost Card ==========
    async def save_cost_card(
        self, cost_card: ManufacturingCostCardTable
    ) -> ManufacturingCostCardTable:
        self._session.add(cost_card)
        await self._session.flush()
        return cost_card

    async def get_cost_card_by_product(
        self, product_id: uuid.UUID, legal_entity_id: uuid.UUID
    ) -> ManufacturingCostCardTable | None:
        stmt = select(ManufacturingCostCardTable).where(
            ManufacturingCostCardTable.product_id == product_id,
            ManufacturingCostCardTable.legal_entity_id == legal_entity_id,
            ManufacturingCostCardTable.is_active == True,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()


__all__ = ["SQLAlchemyManufacturingRepository"]
