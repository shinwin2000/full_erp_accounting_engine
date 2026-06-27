#!/usr/bin/env python3
"""
Module: sqlalchemy_manufacturing_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi repository Manufacturing (BOM, Work Order, Cost Card, WIP)
               menggunakan SQLAlchemy ORM. Semua metode diimplementasikan secara nyata.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from domain.manufacturing.bill_of_materials_entity import BillOfMaterialsEntity, BOMStatus
from domain.manufacturing.cost_card_entity import CostCardEntity
from domain.manufacturing.standard_cost_entity import StandardCostEntity, StandardCostStatus
from domain.manufacturing.work_in_process_entity import WIPStatus, WorkInProcessEntity
from domain.manufacturing.work_order_entity import WorkOrderEntity, WorkOrderStatus
from infrastructure.persistence_orm.bill_of_materials_table import BillOfMaterialsTable
from infrastructure.persistence_orm.manufacturing_cost_card_table import ManufacturingCostCardTable
from infrastructure.persistence_orm.manufacturing_work_order_table import (
    ManufacturingWorkOrderTable,
)
from ports.primary.manufacturing_repository_port import ManufacturingRepositoryPort

logger = logging.getLogger(__name__)


class SQLAlchemyManufacturingRepository(ManufacturingRepositoryPort):
    def __init__(self, session: AsyncSession | None = None, legal_entity_id: UUID | None = None):
        self._session = session
        self._legal_entity_id = legal_entity_id

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    def _get_legal_entity_id(self) -> UUID:
        if self._legal_entity_id is None:
            raise ValueError("legal_entity_id not set in repository")
        return self._legal_entity_id

    # ========================================================================
    # MAPPING: ORM ↔ Domain
    # ========================================================================

    def _bom_to_domain(self, table: BillOfMaterialsTable) -> BillOfMaterialsEntity:
        return BillOfMaterialsEntity(
            id=table.id,
            product_id=table.product_id,
            product_code=table.product_code,
            product_name=table.product_name,
            version=table.version,
            status=BOMStatus(table.status) if table.status else BOMStatus.DRAFT,
            effective_date=table.effective_date,
            expiry_date=table.expiry_date,
            is_active=table.is_active,
            created_by=table.created_by,
            created_at=table.created_at,
            updated_at=table.updated_at,
        )

    def _bom_from_domain(self, bom: BillOfMaterialsEntity) -> BillOfMaterialsTable:
        status_str = bom.status.value if hasattr(bom.status, "value") else str(bom.status)
        return BillOfMaterialsTable(
            id=bom.id,
            product_id=bom.product_id,
            product_code=bom.product_code,
            product_name=bom.product_name,
            version=bom.version,
            status=status_str,
            effective_date=bom.effective_date,
            expiry_date=bom.expiry_date,
            is_active=bom.is_active,
            created_by=bom.created_by,
            created_at=bom.created_at,
            updated_at=bom.updated_at,
            legal_entity_id=self._get_legal_entity_id(),
        )

    def _wo_to_domain(self, table: ManufacturingWorkOrderTable) -> WorkOrderEntity:
        status_map = {
            "draft": WorkOrderStatus.DRAFT,
            "approved": WorkOrderStatus.APPROVED,
            "in_progress": WorkOrderStatus.IN_PROGRESS,
            "completed": WorkOrderStatus.COMPLETED,
            "cancelled": WorkOrderStatus.CANCELLED,
        }
        return WorkOrderEntity(
            id=table.id,
            work_order_number=table.work_order_number,
            product_id=table.product_id,
            product_code=table.product_code,
            product_name=table.product_name,
            planned_quantity=table.planned_quantity,
            completed_quantity=table.completed_quantity or Decimal(0),
            status=status_map.get(table.status, WorkOrderStatus.DRAFT),
            bom_id=table.bom_id,
            start_date=table.start_date,
            due_date=table.due_date,
            completed_at=table.completed_at,
            material_cost=table.material_cost or Decimal(0),
            labor_cost=table.labor_cost or Decimal(0),
            overhead_cost=table.overhead_cost or Decimal(0),
            created_by=table.created_by,
            created_at=table.created_at,
            updated_at=table.updated_at,
        )

    def _wo_from_domain(self, wo: WorkOrderEntity) -> ManufacturingWorkOrderTable:
        status_str = wo.status.value if hasattr(wo.status, "value") else str(wo.status)
        return ManufacturingWorkOrderTable(
            id=wo.id,
            work_order_number=wo.work_order_number,
            product_id=wo.product_id,
            product_code=wo.product_code,
            product_name=wo.product_name,
            planned_quantity=wo.planned_quantity,
            completed_quantity=wo.completed_quantity,
            status=status_str,
            bom_id=wo.bom_id,
            start_date=wo.start_date,
            due_date=wo.due_date,
            completed_at=wo.completed_at,
            material_cost=wo.material_cost,
            labor_cost=wo.labor_cost,
            overhead_cost=wo.overhead_cost,
            created_by=wo.created_by,
            created_at=wo.created_at,
            updated_at=wo.updated_at,
            legal_entity_id=self._get_legal_entity_id(),
        )

    def _cost_card_to_domain(self, table: ManufacturingCostCardTable) -> CostCardEntity:
        return CostCardEntity(
            id=table.id,
            product_id=table.product_id,
            product_code=table.product_code,
            product_name=table.product_name,
            period=table.period,
            material_cost=table.material_cost,
            labor_cost=table.labor_cost,
            overhead_cost=table.overhead_cost,
            total_cost=table.total_cost,
            is_active=table.is_active,
            created_by=table.created_by,
            created_at=table.created_at,
            updated_at=table.updated_at,
        )

    def _cost_card_from_domain(self, card: CostCardEntity) -> ManufacturingCostCardTable:
        return ManufacturingCostCardTable(
            id=card.id,
            product_id=card.product_id,
            product_code=card.product_code,
            product_name=card.product_name,
            period=card.period,
            material_cost=card.material_cost,
            labor_cost=card.labor_cost,
            overhead_cost=card.overhead_cost,
            total_cost=card.total_cost,
            is_active=card.is_active,
            created_by=card.created_by,
            created_at=card.created_at,
            updated_at=card.updated_at,
            legal_entity_id=self._get_legal_entity_id(),
        )

    def _wip_to_domain(self, table: ManufacturingWorkOrderTable) -> WorkInProcessEntity:
        wip_status = WIPStatus.OPEN if table.status in ("approved", "in_progress") else WIPStatus.CLOSED
        return WorkInProcessEntity(
            id=uuid4(),  # tidak ada tabel WIP terpisah, kita gunakan work order sebagai sumber WIP
            work_order_id=table.id,
            work_order_number=table.work_order_number,
            product_id=table.product_id,
            product_code=table.product_code,
            product_name=table.product_name,
            quantity_started=table.planned_quantity - table.completed_quantity,
            quantity_completed=table.completed_quantity,
            status=wip_status,
            created_at=table.created_at,
            updated_at=table.updated_at,
        )

    # ========================================================================
    # BILL OF MATERIALS
    # ========================================================================

    async def save_bom(self, bom: BillOfMaterialsEntity) -> None:
        session = await self._get_session()
        table = self._bom_from_domain(bom)
        existing = await session.get(BillOfMaterialsTable, bom.id)
        if existing:
            for key, value in table.__dict__.items():
                if not key.startswith("_") and key != "id":
                    setattr(existing, key, value)
            existing.updated_at = datetime.utcnow()
        else:
            session.add(table)
        await session.flush()

    async def get_bom_by_id(self, bom_id: UUID) -> BillOfMaterialsEntity | None:
        session = await self._get_session()
        table = await session.get(BillOfMaterialsTable, bom_id)
        if not table or table.deleted_at is not None:
            return None
        return self._bom_to_domain(table)

    async def get_active_bom(self, product_id: UUID, as_of_date: date) -> BillOfMaterialsEntity | None:
        legal_entity_id = self._get_legal_entity_id()
        session = await self._get_session()
        stmt = (
            select(BillOfMaterialsTable)
            .where(
                BillOfMaterialsTable.product_id == product_id,
                BillOfMaterialsTable.legal_entity_id == legal_entity_id,
                BillOfMaterialsTable.is_active == True,
                BillOfMaterialsTable.effective_date <= as_of_date,
                BillOfMaterialsTable.deleted_at.is_(None),
            )
            .order_by(BillOfMaterialsTable.effective_date.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        table = result.scalar_one_or_none()
        if not table:
            return None
        # Check expiry
        if table.expiry_date and table.expiry_date < as_of_date:
            return None
        return self._bom_to_domain(table)

    async def get_bom_by_product_and_version(self, product_id: UUID, version: int) -> BillOfMaterialsEntity | None:
        legal_entity_id = self._get_legal_entity_id()
        session = await self._get_session()
        stmt = (
            select(BillOfMaterialsTable)
            .where(
                BillOfMaterialsTable.product_id == product_id,
                BillOfMaterialsTable.version == version,
                BillOfMaterialsTable.legal_entity_id == legal_entity_id,
                BillOfMaterialsTable.deleted_at.is_(None),
            )
        )
        result = await session.execute(stmt)
        table = result.scalar_one_or_none()
        if not table:
            return None
        return self._bom_to_domain(table)

    async def list_boms_by_product(
        self, product_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[BillOfMaterialsEntity]:
        legal_entity_id = self._get_legal_entity_id()
        session = await self._get_session()
        stmt = (
            select(BillOfMaterialsTable)
            .where(
                BillOfMaterialsTable.product_id == product_id,
                BillOfMaterialsTable.legal_entity_id == legal_entity_id,
                BillOfMaterialsTable.deleted_at.is_(None),
            )
            .order_by(BillOfMaterialsTable.version.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        tables = result.scalars().all()
        return [self._bom_to_domain(t) for t in tables]

    # ========================================================================
    # WORK ORDER
    # ========================================================================

    async def save_work_order(self, work_order: WorkOrderEntity) -> None:
        session = await self._get_session()
        table = self._wo_from_domain(work_order)
        existing = await session.get(ManufacturingWorkOrderTable, work_order.id)
        if existing:
            for key, value in table.__dict__.items():
                if not key.startswith("_") and key != "id":
                    setattr(existing, key, value)
            existing.updated_at = datetime.utcnow()
        else:
            session.add(table)
        await session.flush()

    async def get_work_order(self, work_order_id: UUID) -> WorkOrderEntity | None:
        session = await self._get_session()
        table = await session.get(ManufacturingWorkOrderTable, work_order_id)
        if not table or table.deleted_at is not None:
            return None
        return self._wo_to_domain(table)

    async def get_work_order_by_number(self, work_order_number: str) -> WorkOrderEntity | None:
        legal_entity_id = self._get_legal_entity_id()
        session = await self._get_session()
        stmt = select(ManufacturingWorkOrderTable).where(
            ManufacturingWorkOrderTable.work_order_number == work_order_number,
            ManufacturingWorkOrderTable.legal_entity_id == legal_entity_id,
            ManufacturingWorkOrderTable.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        table = result.scalar_one_or_none()
        if not table:
            return None
        return self._wo_to_domain(table)

    async def list_work_orders_by_product(
        self,
        product_id: UUID,
        from_date: date | None = None,
        to_date: date | None = None,
        status: WorkOrderStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[WorkOrderEntity]:
        legal_entity_id = self._get_legal_entity_id()
        session = await self._get_session()
        conditions = [
            ManufacturingWorkOrderTable.product_id == product_id,
            ManufacturingWorkOrderTable.legal_entity_id == legal_entity_id,
            ManufacturingWorkOrderTable.deleted_at.is_(None),
        ]
        if from_date:
            conditions.append(ManufacturingWorkOrderTable.created_at >= from_date)
        if to_date:
            conditions.append(ManufacturingWorkOrderTable.created_at <= to_date)
        if status:
            status_str = status.value if hasattr(status, "value") else str(status)
            conditions.append(ManufacturingWorkOrderTable.status == status_str)
        stmt = (
            select(ManufacturingWorkOrderTable)
            .where(and_(*conditions))
            .order_by(ManufacturingWorkOrderTable.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        tables = result.scalars().all()
        return [self._wo_to_domain(t) for t in tables]

    async def list_completed_work_orders(
        self, legal_entity_id: UUID, from_date: date, to_date: date
    ) -> list[WorkOrderEntity]:
        session = await self._get_session()
        stmt = (
            select(ManufacturingWorkOrderTable)
            .where(
                ManufacturingWorkOrderTable.legal_entity_id == legal_entity_id,
                ManufacturingWorkOrderTable.status == "completed",
                ManufacturingWorkOrderTable.completed_at >= from_date,
                ManufacturingWorkOrderTable.completed_at <= to_date,
                ManufacturingWorkOrderTable.deleted_at.is_(None),
            )
            .order_by(ManufacturingWorkOrderTable.completed_at.desc())
        )
        result = await session.execute(stmt)
        tables = result.scalars().all()
        return [self._wo_to_domain(t) for t in tables]

    async def get_last_work_order_number(self) -> str | None:
        legal_entity_id = self._get_legal_entity_id()
        session = await self._get_session()
        stmt = (
            select(ManufacturingWorkOrderTable.work_order_number)
            .where(
                ManufacturingWorkOrderTable.legal_entity_id == legal_entity_id,
                ManufacturingWorkOrderTable.deleted_at.is_(None),
            )
            .order_by(ManufacturingWorkOrderTable.created_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def count_work_orders_by_status(
        self, status: WorkOrderStatus, legal_entity_id: UUID
    ) -> int:
        status_str = status.value if hasattr(status, "value") else str(status)
        session = await self._get_session()
        stmt = (
            select(func.count())
            .select_from(ManufacturingWorkOrderTable)
            .where(
                ManufacturingWorkOrderTable.legal_entity_id == legal_entity_id,
                ManufacturingWorkOrderTable.status == status_str,
                ManufacturingWorkOrderTable.deleted_at.is_(None),
            )
        )
        result = await session.execute(stmt)
        return result.scalar() or 0

    # ========================================================================
    # WIP
    # ========================================================================

    async def save_wip(self, wip: WorkInProcessEntity) -> None:
        # WIP disimpan sebagai bagian dari work order (update status dan quantity)
        session = await self._get_session()
        wo = await session.get(ManufacturingWorkOrderTable, wip.work_order_id)
        if not wo:
            raise ValueError(f"Work order {wip.work_order_id} not found")
        # Update work order dengan data WIP
        wo.completed_quantity = wip.quantity_completed
        wo.status = "in_progress" if wip.status == WIPStatus.OPEN else "completed"
        wo.updated_at = datetime.utcnow()
        await session.flush()

    async def get_wip_by_work_order(self, work_order_id: UUID) -> WorkInProcessEntity | None:
        session = await self._get_session()
        wo = await session.get(ManufacturingWorkOrderTable, work_order_id)
        if not wo or wo.deleted_at is not None:
            return None
        return self._wip_to_domain(wo)

    async def list_open_wip(self, legal_entity_id: UUID) -> list[WorkInProcessEntity]:
        session = await self._get_session()
        stmt = select(ManufacturingWorkOrderTable).where(
            ManufacturingWorkOrderTable.legal_entity_id == legal_entity_id,
            ManufacturingWorkOrderTable.status.in_(["approved", "in_progress"]),
            ManufacturingWorkOrderTable.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        tables = result.scalars().all()
        return [self._wip_to_domain(t) for t in tables]

    # ========================================================================
    # COST CARD
    # ========================================================================

    async def save_cost_card(self, cost_card: CostCardEntity) -> None:
        session = await self._get_session()
        table = self._cost_card_from_domain(cost_card)
        existing = await session.get(ManufacturingCostCardTable, cost_card.id)
        if existing:
            for key, value in table.__dict__.items():
                if not key.startswith("_") and key != "id":
                    setattr(existing, key, value)
            existing.updated_at = datetime.utcnow()
        else:
            session.add(table)
        await session.flush()

    async def get_cost_card(self, product_id: UUID, period: str) -> CostCardEntity | None:
        legal_entity_id = self._get_legal_entity_id()
        session = await self._get_session()
        stmt = select(ManufacturingCostCardTable).where(
            ManufacturingCostCardTable.product_id == product_id,
            ManufacturingCostCardTable.period == period,
            ManufacturingCostCardTable.legal_entity_id == legal_entity_id,
            ManufacturingCostCardTable.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        table = result.scalar_one_or_none()
        if not table:
            return None
        return self._cost_card_to_domain(table)

    async def get_cost_card_by_id(self, cost_card_id: UUID) -> CostCardEntity | None:
        session = await self._get_session()
        table = await session.get(ManufacturingCostCardTable, cost_card_id)
        if not table or table.deleted_at is not None:
            return None
        return self._cost_card_to_domain(table)

    async def list_cost_cards_by_product(
        self, product_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[CostCardEntity]:
        legal_entity_id = self._get_legal_entity_id()
        session = await self._get_session()
        stmt = (
            select(ManufacturingCostCardTable)
            .where(
                ManufacturingCostCardTable.product_id == product_id,
                ManufacturingCostCardTable.legal_entity_id == legal_entity_id,
                ManufacturingCostCardTable.deleted_at.is_(None),
            )
            .order_by(ManufacturingCostCardTable.period.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        tables = result.scalars().all()
        return [self._cost_card_to_domain(t) for t in tables]

    # ========================================================================
    # STANDARD COST
    # ========================================================================

    async def save_standard_cost(self, standard_cost: StandardCostEntity) -> None:
        # Simpan sebagai cost card dengan cost_type = 'standard'
        session = await self._get_session()
        # Cari existing standard cost card
        stmt = select(ManufacturingCostCardTable).where(
            ManufacturingCostCardTable.product_id == standard_cost.product_id,
            ManufacturingCostCardTable.cost_type == "standard",
            ManufacturingCostCardTable.legal_entity_id == self._get_legal_entity_id(),
            ManufacturingCostCardTable.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            existing.unit_cost = standard_cost.unit_cost
            existing.total_cost = standard_cost.total_cost
            existing.effective_date = standard_cost.effective_date
            existing.is_active = standard_cost.status == StandardCostStatus.ACTIVE
            existing.updated_at = datetime.utcnow()
        else:
            table = ManufacturingCostCardTable(
                id=standard_cost.id,
                product_id=standard_cost.product_id,
                product_code=standard_cost.product_code,
                product_name=standard_cost.product_name,
                period=standard_cost.period,
                cost_type="standard",
                unit_cost=standard_cost.unit_cost,
                total_cost=standard_cost.total_cost,
                effective_date=standard_cost.effective_date,
                is_active=standard_cost.status == StandardCostStatus.ACTIVE,
                created_by=standard_cost.created_by,
                created_at=datetime.utcnow(),
                legal_entity_id=self._get_legal_entity_id(),
            )
            session.add(table)
        await session.flush()

    async def get_standard_cost_by_product(
        self, product_id: UUID, as_of_date: datetime | None = None
    ) -> StandardCostEntity | None:
        legal_entity_id = self._get_legal_entity_id()
        session = await self._get_session()
        stmt = (
            select(ManufacturingCostCardTable)
            .where(
                ManufacturingCostCardTable.product_id == product_id,
                ManufacturingCostCardTable.cost_type == "standard",
                ManufacturingCostCardTable.is_active == True,
                ManufacturingCostCardTable.legal_entity_id == legal_entity_id,
                ManufacturingCostCardTable.deleted_at.is_(None),
            )
            .order_by(ManufacturingCostCardTable.effective_date.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        table = result.scalar_one_or_none()
        if not table:
            return None
        # Konversi ke StandardCostEntity
        return StandardCostEntity(
            id=table.id,
            product_id=table.product_id,
            product_code=table.product_code,
            product_name=table.product_name,
            unit_cost=table.unit_cost,
            total_cost=table.total_cost,
            effective_date=table.effective_date,
            period=table.period,
            status=StandardCostStatus.ACTIVE if table.is_active else StandardCostStatus.DRAFT,
            created_by=table.created_by,
            created_at=table.created_at,
            updated_at=table.updated_at,
        )

    async def get_standard_cost_by_id(self, standard_cost_id: UUID) -> StandardCostEntity | None:
        session = await self._get_session()
        table = await session.get(ManufacturingCostCardTable, standard_cost_id)
        if not table or table.cost_type != "standard" or table.deleted_at is not None:
            return None
        return StandardCostEntity(
            id=table.id,
            product_id=table.product_id,
            product_code=table.product_code,
            product_name=table.product_name,
            unit_cost=table.unit_cost,
            total_cost=table.total_cost,
            effective_date=table.effective_date,
            period=table.period,
            status=StandardCostStatus.ACTIVE if table.is_active else StandardCostStatus.DRAFT,
            created_by=table.created_by,
            created_at=table.created_at,
            updated_at=table.updated_at,
        )

    # ========================================================================
    # PERIOD OPERATIONS
    # ========================================================================

    async def close_period(self, legal_entity_id: UUID, period: str, user_id: UUID) -> None:
        session = await self._get_session()
        # Update work orders in period
        stmt = (
            update(ManufacturingWorkOrderTable)
            .where(
                ManufacturingWorkOrderTable.legal_entity_id == legal_entity_id,
                ManufacturingWorkOrderTable.fiscal_period == period,
                ManufacturingWorkOrderTable.status.in_(["approved", "in_progress"]),
            )
            .values(status="closed", updated_at=datetime.utcnow(), updated_by=user_id)
        )
        await session.execute(stmt)
        await session.flush()

    async def is_period_closed(self, legal_entity_id: UUID, period: str) -> bool:
        session = await self._get_session()
        stmt = (
            select(func.count())
            .select_from(ManufacturingWorkOrderTable)
            .where(
                ManufacturingWorkOrderTable.legal_entity_id == legal_entity_id,
                ManufacturingWorkOrderTable.fiscal_period == period,
                ManufacturingWorkOrderTable.status.in_(["approved", "in_progress"]),
                ManufacturingWorkOrderTable.deleted_at.is_(None),
            )
        )
        result = await session.execute(stmt)
        count = result.scalar() or 0
        return count == 0

    # ========================================================================
    # BATCH OPERATIONS
    # ========================================================================

    async def save_bom_batch(self, boms: list[BillOfMaterialsEntity]) -> None:
        session = await self._get_session()
        for bom in boms:
            table = self._bom_from_domain(bom)
            existing = await session.get(BillOfMaterialsTable, bom.id)
            if existing:
                for key, value in table.__dict__.items():
                    if not key.startswith("_") and key != "id":
                        setattr(existing, key, value)
                existing.updated_at = datetime.utcnow()
            else:
                session.add(table)
            # Save lines? Not implemented yet; assuming BOM entity doesn't have lines in this context.
        await session.flush()

    async def save_work_order_batch(self, work_orders: list[WorkOrderEntity]) -> None:
        session = await self._get_session()
        for wo in work_orders:
            table = self._wo_from_domain(wo)
            existing = await session.get(ManufacturingWorkOrderTable, wo.id)
            if existing:
                for key, value in table.__dict__.items():
                    if not key.startswith("_") and key != "id":
                        setattr(existing, key, value)
                existing.updated_at = datetime.utcnow()
            else:
                session.add(table)
        await session.flush()


# ============================================================================
# ALIAS UNTUK KOMPATIBILITAS DENGAN ADAPTER REGISTRY
# ============================================================================

SQLAlchemyManufacturingRepositoryImpl = SQLAlchemyManufacturingRepository

__all__ = [
    "SQLAlchemyManufacturingRepository",
    "SQLAlchemyManufacturingRepositoryImpl",
]
