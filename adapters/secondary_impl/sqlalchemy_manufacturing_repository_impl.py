#!/usr/bin/env python3
"""
Module: sqlalchemy_manufacturing_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi repository Manufacturing (BOM, Work Order, Cost Card,
                WIP, Standard Cost) menggunakan SQLAlchemy ORM.

Design notes:
  - Entity domain (dataclass frozen) adalah aggregate kaya; tabel ORM flat.
    Mapping 2 arah di layer ini menutup gap tersebut.
  - BOM: entity punya `items: list[BOMItem]` di-embed -> ORM punya relasi
    `lines` ke `bill_of_materials_line`. Kita load `lines` saat to_domain,
    dan sinkronkan `lines` saat from_domain (delete + insert ulang).
  - WorkOrderStatus mapping 2 arah (domain enum <-> ORM string) menggunakan
    tabel konstanta karena ORM punya 'planned'/'released' yang tidak ada di
    domain, dan domain punya 'approved'/'partial' yang tidak ada di ORM.
  - Cost Card: entity ORM `ManufacturingCostCardTable` lebih miskin dari
    `CostCardEntity`. Field yang hilang di ORM disimpan sebagai metadata di
    `product_code` bila memungkinkan, atau default konservatif.
  - WIP: dihitung on-the-fly dari WorkOrder. `WorkInProcessTable` tidak
    dipakai (lihat analysis: 0 referensi dari adapter manapun).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from domain.manufacturing.bill_of_materials_entity import (
    BillOfMaterialsEntity,
    BOMItem,
    BOMStatus,
)
from domain.manufacturing.cost_card_entity import CostCardEntity, CostCardStatus, CostEntry
from domain.manufacturing.cost_element_enum import CostElement
from domain.manufacturing.standard_cost_entity import (
    StandardCostComponent,
    StandardCostEntity,
    StandardCostStatus,
)
from domain.manufacturing.work_in_process_entity import (
    WIPStatus,
    WorkInProcessEntity,
)
from domain.manufacturing.work_order_entity import (
    WorkOrderEntity,
    WorkOrderPriority,
    WorkOrderStatus,
    WorkOrderType,
)
from infrastructure.persistence_orm.bill_of_materials_line_table import (
    BillOfMaterialsLineTable,
)
from infrastructure.persistence_orm.bill_of_materials_table import BillOfMaterialsTable
from infrastructure.persistence_orm.manufacturing_cost_card_table import (
    ManufacturingCostCardTable,
)
from infrastructure.persistence_orm.manufacturing_work_order_table import (
    ManufacturingWorkOrderTable,
)
from ports.primary.manufacturing_repository_port import (
    ManufacturingRepositoryPort,
    WorkOrderCosts,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Status mapping (domain enum <-> ORM string)
# ============================================================================

_DOMAIN_TO_ORM_STATUS: dict[WorkOrderStatus, str] = {
    WorkOrderStatus.DRAFT: "draft",
    WorkOrderStatus.APPROVED: "released",
    WorkOrderStatus.IN_PROGRESS: "in_progress",
    WorkOrderStatus.COMPLETED: "completed",
    WorkOrderStatus.PARTIALLY_COMPLETED: "in_progress",
    WorkOrderStatus.CANCELLED: "cancelled",
}

_ORM_TO_DOMAIN_STATUS: dict[str, WorkOrderStatus] = {
    "draft": WorkOrderStatus.DRAFT,
    "planned": WorkOrderStatus.APPROVED,     # planned = approved, not yet started
    "released": WorkOrderStatus.APPROVED,
    "in_progress": WorkOrderStatus.IN_PROGRESS,
    "completed": WorkOrderStatus.COMPLETED,
    "cancelled": WorkOrderStatus.CANCELLED,
    # Status turunan (dipakai internal WorkOrderEntity.cancel, dll)
    "partial": WorkOrderStatus.PARTIALLY_COMPLETED,
    "partially_completed": WorkOrderStatus.PARTIALLY_COMPLETED,
}

_DOMAIN_TO_ORM_PRIORITY: dict[WorkOrderPriority, str] = {
    WorkOrderPriority.LOW: "low",
    WorkOrderPriority.NORMAL: "normal",
    WorkOrderPriority.HIGH: "high",
    WorkOrderPriority.URGENT: "urgent",
}

_ORM_TO_DOMAIN_PRIORITY: dict[str, WorkOrderPriority] = {
    "low": WorkOrderPriority.LOW,
    "normal": WorkOrderPriority.NORMAL,
    "high": WorkOrderPriority.HIGH,
    "urgent": WorkOrderPriority.URGENT,
}

_BOM_STATUS_FROM_STR: dict[str, BOMStatus] = {
    "draft": BOMStatus.DRAFT,
    "active": BOMStatus.ACTIVE,
    "obsolete": BOMStatus.OBSOLETE,
    "inactive": BOMStatus.OBSOLETE,  # ORM punya 'inactive', petakan ke OBSOLETE
}

_STD_COST_STATUS_FROM_STR: dict[str, StandardCostStatus] = {
    "draft": StandardCostStatus.DRAFT,
    "active": StandardCostStatus.ACTIVE,
    "obsolete": StandardCostStatus.OBSOLETE,
}

# Period sentinel untuk baris "standard cost" yang disimpan di tabel cost card.
_STD_PERIOD = "standard"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SQLAlchemyManufacturingRepository(ManufacturingRepositoryPort):
    """
    Implementasi ManufacturingRepositoryPort menggunakan SQLAlchemy ORM.

    Konvensi:
      - `legal_entity_id` di-set saat construction, atau di-inject via method
        `set_legal_entity_id()` sebelum operasi tulis.
      - Session lazy: kalau belum di-set, ambil dari session factory global.
    """

    def __init__(
        self,
        session: AsyncSession | None = None,
        legal_entity_id: UUID | None = None,
    ):
        self._session = session
        self._legal_entity_id = legal_entity_id

    # ------------------------------------------------------------------------
    # Session / context helpers
    # ------------------------------------------------------------------------

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            # PENTING: gunakan get_async_session_direct(), BUKAN get_async_session().
            # get_async_session() adalah FastAPI dependency generator (yield session)
            # — memanggilnya langsung akan mengembalikan async_generator object,
            # bukan AsyncSession. Setiap .execute()/.get()/.refresh() gagal
            # AttributeError -> 500 di semua endpoint GET/POST.
            from infrastructure.database.session_factory_sqlalchemy import (
                get_async_session_direct,
            )
            self._session = await get_async_session_direct()
        return self._session

    def _get_legal_entity_id(self) -> UUID:
        if self._legal_entity_id is None:
            raise ValueError(
                "legal_entity_id not set in manufacturing repository; "
                "pass it in constructor or set_legal_entity_id()"
            )
        return self._legal_entity_id

    def set_legal_entity_id(self, legal_entity_id: UUID) -> None:
        self._legal_entity_id = legal_entity_id

    # ========================================================================
    # BILL OF MATERIALS (BOM)
    # ========================================================================

    def _bom_line_to_item(self, line: BillOfMaterialsLineTable) -> BOMItem:
        return BOMItem(
            item_id=line.id,
            item_code=line.component_product_code,
            item_name=line.component_product_name,
            quantity=Decimal(str(line.quantity)),
            unit_of_measure=line.unit_of_measure or "pcs",
            unit_cost=Decimal(str(line.unit_cost)),
            scrap_percentage=Decimal(str(line.scrap_percentage)),
            cost_element=CostElement.MATERIAL,  # ORM tidak simpan cost_element
            sub_bom_id=None,
            notes=line.notes or "",
        )

    def _bom_to_domain(self, table: BillOfMaterialsTable) -> BillOfMaterialsEntity:
        status_str = (table.status or "draft").lower()
        status = _BOM_STATUS_FROM_STR.get(status_str, BOMStatus.DRAFT)

        # Baca relasi lines jika tersedia (pakai eager loading di caller)
        lines = getattr(table, "lines", []) or []
        items = [self._bom_line_to_item(line) for line in lines]

        # product_code tidak ada di tabel header -> fallback ke bom_code
        product_code = table.bom_code or ""

        return BillOfMaterialsEntity(
            bom_id=table.id,
            bom_code=table.bom_code or "",
            product_id=table.product_id,
            product_code=product_code,
            product_name=table.product_name or "",
            version=table.version or 1,
            quantity_per_assembly=Decimal("1"),
            unit_of_measure="pcs",
            items=items,
            status=status,
            routing_id=None,
            effective_date=(
                datetime.combine(table.effective_date, datetime.min.time(), tzinfo=timezone.utc)
                if table.effective_date else None
            ),
            expiry_date=(
                datetime.combine(table.expiry_date, datetime.min.time(), tzinfo=timezone.utc)
                if table.expiry_date else None
            ),
            notes=table.notes or "",
            created_at=table.created_at or _utc_now(),
            updated_at=table.updated_at or _utc_now(),
            created_by=str(table.created_by) if table.created_by else "system",
            version_counter=table.version or 1,
        )

    def _apply_bom_header(
        self, table: BillOfMaterialsTable, bom: BillOfMaterialsEntity
    ) -> None:
        table.legal_entity_id = self._get_legal_entity_id()
        table.bom_code = bom.bom_code or f"BOM-{bom.product_code}-V{bom.version}"
        table.bom_name = bom.product_name or f"BOM {bom.bom_code}"
        table.product_id = bom.product_id
        table.product_name = bom.product_name or None
        table.version = bom.version or 1
        if bom.effective_date:
            table.effective_date = bom.effective_date.date()
        else:
            table.effective_date = date.today()
        table.expiry_date = bom.expiry_date.date() if bom.expiry_date else None
        table.status = (
            bom.status.value if isinstance(bom.status, BOMStatus) else str(bom.status)
        )
        table.notes = bom.notes or None
        # created_by
        try:
            table.created_by = UUID(bom.created_by) if bom.created_by else None
        except (ValueError, TypeError):
            table.created_by = None
        # FIX: TimestampMixin.created_at/updated_at pakai server_default=now()
        # yang baru terisi SETELAH commit. Karena kita pakai session.flush()
        # tanpa commit, Pydantic serializer di router melihat None -> validation
        # error di GET /bom. Set eksplisit di aplikasi.
        if table.created_at is None:
            table.created_at = _utc_now()
        table.updated_at = _utc_now()

    def _make_bom_line(
        self, bom_id: UUID, item: BOMItem, line_number: int
    ) -> BillOfMaterialsLineTable:
        return BillOfMaterialsLineTable(
            id=item.item_id if item.item_id else uuid4(),
            bom_id=bom_id,
            line_number=line_number,
            component_product_id=item.item_id,  # domain tidak simpan product_id komponen terpisah
            component_product_code=item.item_code,
            component_product_name=item.item_name,
            quantity=item.quantity,
            unit_of_measure=item.unit_of_measure or "pcs",
            unit_cost=item.unit_cost,
            total_cost=item.total_cost,
            scrap_percentage=item.scrap_percentage,
            notes=item.notes or None,
            legal_entity_id=self._get_legal_entity_id(),
        )

    async def save_bom(self, bom: BillOfMaterialsEntity) -> None:
        session = await self._get_session()
        existing = await session.get(BillOfMaterialsTable, bom.bom_id)

        if existing is None:
            table = BillOfMaterialsTable(id=bom.bom_id)
            self._apply_bom_header(table, bom)
            session.add(table)
        else:
            table = existing
            self._apply_bom_header(table, bom)
            # Hapus lines lama, insert ulang (entity immutable)
            old_lines = (
                await session.execute(
                    select(BillOfMaterialsLineTable).where(
                        BillOfMaterialsLineTable.bom_id == bom.bom_id
                    )
                )
            ).scalars().all()
            for line in old_lines:
                await session.delete(line)

        # Insert lines baru
        for idx, item in enumerate(bom.items, start=1):
            line = self._make_bom_line(bom.bom_id, item, idx)
            session.add(line)

        await session.flush()
        try:
            await session.commit()
        except Exception as e:
            logger.warning(f"commit failed: {e}")
            await session.rollback()
            raise

    async def get_bom_by_id(self, bom_id: UUID) -> BillOfMaterialsEntity | None:
        session = await self._get_session()
        table = await session.get(BillOfMaterialsTable, bom_id)
        if table is None:
            return None
        # Pastikan `lines` di-load
        await session.refresh(table, attribute_names=["lines"])
        return self._bom_to_domain(table)

    async def get_active_bom(
        self, product_id: UUID, as_of_date: date
    ) -> BillOfMaterialsEntity | None:
        legal_entity_id = self._get_legal_entity_id()
        session = await self._get_session()
        stmt = (
            select(BillOfMaterialsTable)
            .where(
                BillOfMaterialsTable.product_id == product_id,
                BillOfMaterialsTable.legal_entity_id == legal_entity_id,
                BillOfMaterialsTable.status == "active",
                BillOfMaterialsTable.effective_date <= as_of_date,
            )
            .order_by(BillOfMaterialsTable.effective_date.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        table = result.scalar_one_or_none()
        if table is None:
            return None
        if table.expiry_date and table.expiry_date < as_of_date:
            return None
        await session.refresh(table, attribute_names=["lines"])
        return self._bom_to_domain(table)

    async def get_bom_by_product_and_version(
        self, product_id: UUID, version: int
    ) -> BillOfMaterialsEntity | None:
        legal_entity_id = self._get_legal_entity_id()
        session = await self._get_session()
        stmt = select(BillOfMaterialsTable).where(
            BillOfMaterialsTable.product_id == product_id,
            BillOfMaterialsTable.version == version,
            BillOfMaterialsTable.legal_entity_id == legal_entity_id,
        )
        result = await session.execute(stmt)
        table = result.scalar_one_or_none()
        if table is None:
            return None
        await session.refresh(table, attribute_names=["lines"])
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
            )
            .order_by(BillOfMaterialsTable.version.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        tables = result.scalars().all()
        out: list[BillOfMaterialsEntity] = []
        for t in tables:
            await session.refresh(t, attribute_names=["lines"])
            out.append(self._bom_to_domain(t))
        return out

    async def list_all_boms(
        self,
        legal_entity_id: UUID,
        product_id: UUID | None = None,
        status: str | None = None,
        is_default: bool | None = None,
        effective_as_of: date | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[BillOfMaterialsEntity]:
        session = await self._get_session()
        conditions = [BillOfMaterialsTable.legal_entity_id == legal_entity_id]
        if product_id is not None:
            conditions.append(BillOfMaterialsTable.product_id == product_id)
        if status is not None:
            conditions.append(BillOfMaterialsTable.status == status)
        if is_default is not None:
            conditions.append(BillOfMaterialsTable.is_default == is_default)
        if effective_as_of is not None:
            conditions.append(BillOfMaterialsTable.effective_date <= effective_as_of)
        stmt = (
            select(BillOfMaterialsTable)
            .where(and_(*conditions))
            .order_by(BillOfMaterialsTable.effective_date.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        tables = result.scalars().all()
        out: list[BillOfMaterialsEntity] = []
        for t in tables:
            await session.refresh(t, attribute_names=["lines"])
            out.append(self._bom_to_domain(t))
        return out

    # ========================================================================
    # WORK ORDER
    # ========================================================================

    def _wo_to_domain(self, table: ManufacturingWorkOrderTable) -> WorkOrderEntity:
        status_str = (table.status or "draft").lower()
        status = _ORM_TO_DOMAIN_STATUS.get(status_str, WorkOrderStatus.DRAFT)

        priority_str = (getattr(table, "priority", "normal") or "normal").lower()
        priority = _ORM_TO_DOMAIN_PRIORITY.get(priority_str, WorkOrderPriority.NORMAL)

        planned_start = self._combine_dt(table.planned_start_date)
        planned_end = self._combine_dt(table.planned_end_date) or planned_start
        if planned_end <= planned_start:
            # Entity invariant: end > start
            from datetime import timedelta
            planned_end = planned_start + timedelta(days=1)

        return WorkOrderEntity(
            work_order_id=table.id,
            work_order_number=table.wo_number,
            product_id=table.product_id,
            product_code=table.product_code,
            product_name=table.product_name,
            bom_id=table.bill_of_materials_id or uuid4(),
            bom_version=1,
            planned_quantity=Decimal(str(table.quantity)),
            completed_quantity=Decimal(str(table.completed_quantity or 0)),
            status=status,
            priority=priority,
            planned_start_date=planned_start,
            planned_end_date=planned_end,
            actual_start_date=self._combine_dt(table.actual_start_date),
            actual_end_date=self._combine_dt(table.actual_completion_date),
            routing_id=None,
            cost_center=None,
            notes=table.notes or "",
            work_order_type=WorkOrderType.PRODUCTION,
            created_at=table.created_at or _utc_now(),
            updated_at=table.updated_at or _utc_now(),
            created_by=str(table.created_by) if table.created_by else "system",
            version=table.version or 1,
            material_actual_cost=Decimal(str(table.total_material_cost or 0)),
            labor_actual_cost=Decimal(str(table.total_labor_cost or 0)),
            overhead_actual_cost=Decimal(str(table.total_overhead_cost or 0)),
        )

    def _apply_wo_from_domain(
        self, table: ManufacturingWorkOrderTable, wo: WorkOrderEntity
    ) -> None:
        table.legal_entity_id = self._get_legal_entity_id()
        table.wo_number = wo.work_order_number
        table.product_id = wo.product_id
        table.product_code = wo.product_code
        table.product_name = wo.product_name
        table.bill_of_materials_id = wo.bom_id
        table.quantity = wo.planned_quantity
        table.completed_quantity = wo.completed_quantity
        table.rejected_quantity = Decimal("0")
        table.planned_start_date = wo.planned_start_date.date() if wo.planned_start_date else None
        table.planned_end_date = wo.planned_end_date.date() if wo.planned_end_date else None
        table.actual_start_date = wo.actual_start_date.date() if wo.actual_start_date else None
        table.actual_completion_date = wo.actual_end_date.date() if wo.actual_end_date else None
        table.status = _DOMAIN_TO_ORM_STATUS.get(wo.status, "draft")
        table.priority = _DOMAIN_TO_ORM_PRIORITY.get(wo.priority, "normal")
        table.total_material_cost = wo.material_actual_cost
        table.total_labor_cost = wo.labor_actual_cost
        table.total_overhead_cost = wo.overhead_actual_cost
        table.total_cost = (
            wo.material_actual_cost + wo.labor_actual_cost + wo.overhead_actual_cost
        )
        table.notes = wo.notes or None
        try:
            table.created_by = UUID(wo.created_by) if wo.created_by else None
        except (ValueError, TypeError):
            table.created_by = None

        # FIX: set timestamp eksplisit (alasan sama seperti _apply_bom_header)
        if table.created_at is None:
            table.created_at = _utc_now()
        table.updated_at = _utc_now()

    @staticmethod
    def _combine_dt(d) -> datetime | None:
        """Terima date atau datetime, kembalikan datetime UTC-aware."""
        if d is None:
            return None
        if isinstance(d, datetime):
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        return datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc)

    async def save_work_order(self, work_order: WorkOrderEntity) -> None:
        session = await self._get_session()
        existing = await session.get(ManufacturingWorkOrderTable, work_order.work_order_id)
        if existing is None:
            table = ManufacturingWorkOrderTable(id=work_order.work_order_id)
            self._apply_wo_from_domain(table, work_order)
            session.add(table)
        else:
            self._apply_wo_from_domain(existing, work_order)
        await session.flush()
        try:
            await session.commit()
        except Exception as e:
            logger.warning(f"commit failed: {e}")
            await session.rollback()
            raise

    async def get_work_order(self, work_order_id: UUID) -> WorkOrderEntity | None:
        session = await self._get_session()
        table = await session.get(ManufacturingWorkOrderTable, work_order_id)
        if table is None:
            return None
        return self._wo_to_domain(table)

    async def get_work_order_by_number(
        self, work_order_number: str
    ) -> WorkOrderEntity | None:
        legal_entity_id = self._get_legal_entity_id()
        session = await self._get_session()
        stmt = select(ManufacturingWorkOrderTable).where(
            ManufacturingWorkOrderTable.wo_number == work_order_number,
            ManufacturingWorkOrderTable.legal_entity_id == legal_entity_id,
        )
        result = await session.execute(stmt)
        table = result.scalar_one_or_none()
        if table is None:
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
        ]
        if from_date:
            conditions.append(ManufacturingWorkOrderTable.planned_start_date >= from_date)
        if to_date:
            conditions.append(ManufacturingWorkOrderTable.planned_end_date <= to_date)
        if status:
            conditions.append(
                ManufacturingWorkOrderTable.status == _DOMAIN_TO_ORM_STATUS.get(status, "draft")
            )
        stmt = (
            select(ManufacturingWorkOrderTable)
            .where(and_(*conditions))
            .order_by(ManufacturingWorkOrderTable.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        return [self._wo_to_domain(t) for t in result.scalars().all()]

    async def list_work_orders(
        self,
        legal_entity_id: UUID,
        product_id: UUID | None = None,
        status: WorkOrderStatus | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[WorkOrderEntity]:
        session = await self._get_session()
        conditions = [ManufacturingWorkOrderTable.legal_entity_id == legal_entity_id]
        if product_id is not None:
            conditions.append(ManufacturingWorkOrderTable.product_id == product_id)
        if status is not None:
            conditions.append(
                ManufacturingWorkOrderTable.status == _DOMAIN_TO_ORM_STATUS.get(status, "draft")
            )
        if start_date:
            conditions.append(ManufacturingWorkOrderTable.planned_start_date >= start_date)
        if end_date:
            conditions.append(ManufacturingWorkOrderTable.planned_end_date <= end_date)
        stmt = (
            select(ManufacturingWorkOrderTable)
            .where(and_(*conditions))
            .order_by(ManufacturingWorkOrderTable.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        return [self._wo_to_domain(t) for t in result.scalars().all()]

    async def list_completed_work_orders(
        self, legal_entity_id: UUID, from_date: date, to_date: date
    ) -> list[WorkOrderEntity]:
        session = await self._get_session()
        stmt = (
            select(ManufacturingWorkOrderTable)
            .where(
                ManufacturingWorkOrderTable.legal_entity_id == legal_entity_id,
                ManufacturingWorkOrderTable.status == "completed",
                ManufacturingWorkOrderTable.actual_completion_date >= from_date,
                ManufacturingWorkOrderTable.actual_completion_date <= to_date,
            )
            .order_by(ManufacturingWorkOrderTable.actual_completion_date.desc())
        )
        result = await session.execute(stmt)
        return [self._wo_to_domain(t) for t in result.scalars().all()]

    async def get_last_work_order_number(self) -> str | None:
        legal_entity_id = self._get_legal_entity_id()
        session = await self._get_session()
        stmt = (
            select(ManufacturingWorkOrderTable.wo_number)
            .where(ManufacturingWorkOrderTable.legal_entity_id == legal_entity_id)
            .order_by(ManufacturingWorkOrderTable.created_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def count_work_orders_by_status(
        self, status: WorkOrderStatus, legal_entity_id: UUID
    ) -> int:
        status_str = _DOMAIN_TO_ORM_STATUS.get(status, "draft")
        session = await self._get_session()
        stmt = (
            select(func.count())
            .select_from(ManufacturingWorkOrderTable)
            .where(
                ManufacturingWorkOrderTable.legal_entity_id == legal_entity_id,
                ManufacturingWorkOrderTable.status == status_str,
            )
        )
        result = await session.execute(stmt)
        return result.scalar() or 0

    # ========================================================================
    # WIP (dihitung on-the-fly dari Work Order)
    # ========================================================================

    def _wo_to_wip(self, table: ManufacturingWorkOrderTable) -> WorkInProcessEntity:
        """Bangun WIP entity dari data Work Order (tanpa tabel WIP terpisah)."""
        planned = Decimal(str(table.quantity or 0))
        completed = Decimal(str(table.completed_quantity or 0))
        remaining = planned - completed
        if remaining < 0:
            remaining = Decimal("0")
        started = planned

        status_str = (table.status or "").lower()
        if status_str in ("planned", "released", "in_progress", "draft"):
            wip_status = WIPStatus.OPEN
        elif status_str == "completed":
            wip_status = WIPStatus.CLOSED
        else:
            wip_status = WIPStatus.ADJUSTED

        material = Decimal(str(table.total_material_cost or 0))
        labor = Decimal(str(table.total_labor_cost or 0))
        overhead = Decimal(str(table.total_overhead_cost or 0))
        total = material + labor + overhead

        return WorkInProcessEntity(
            wip_id=table.id,  # gunakan WO id sebagai WIP id (1:1)
            work_order_id=table.id,
            work_order_number=table.wo_number,
            product_id=table.product_id,
            product_code=table.product_code,
            product_name=table.product_name,
            quantity_started=started,
            quantity_remaining=remaining,
            quantity_completed=completed,
            material_cost=material,
            labor_cost=labor,
            overhead_cost=overhead,
            total_cost=total,
            status=wip_status,
            last_update_date=table.updated_at or _utc_now(),
            cost_components=[],
            created_at=table.created_at or _utc_now(),
            updated_at=table.updated_at or _utc_now(),
            created_by=str(table.created_by) if table.created_by else "system",
            version=table.version or 1,
        )

    async def save_wip(self, wip: WorkInProcessEntity) -> None:
        """Update Work Order yang bersangkutan dengan quantity completed + cost aktual."""
        session = await self._get_session()
        table = await session.get(ManufacturingWorkOrderTable, wip.work_order_id)
        if table is None:
            raise ValueError(f"Work order {wip.work_order_id} not found for WIP save")
        table.completed_quantity = wip.quantity_completed
        table.total_material_cost = wip.material_cost
        table.total_labor_cost = wip.labor_cost
        table.total_overhead_cost = wip.overhead_cost
        table.total_cost = wip.material_cost + wip.labor_cost + wip.overhead_cost
        if wip.status == WIPStatus.CLOSED:
            table.status = "completed"
        table.updated_at = _utc_now()
        await session.flush()
        try:
            await session.commit()
        except Exception as e:
            logger.warning(f"commit failed: {e}")
            await session.rollback()
            raise

    async def get_wip_by_work_order(
        self, work_order_id: UUID
    ) -> WorkInProcessEntity | None:
        session = await self._get_session()
        table = await session.get(ManufacturingWorkOrderTable, work_order_id)
        if table is None:
            return None
        return self._wo_to_wip(table)

    async def list_open_wip(self, legal_entity_id: UUID) -> list[WorkInProcessEntity]:
        return await self.list_wip(legal_entity_id=legal_entity_id)

    async def list_wip(
        self,
        legal_entity_id: UUID,
        work_order_id: UUID | None = None,
        product_id: UUID | None = None,
    ) -> list[WorkInProcessEntity]:
        session = await self._get_session()
        conditions = [
            ManufacturingWorkOrderTable.legal_entity_id == legal_entity_id,
            ManufacturingWorkOrderTable.status.in_(
                ("planned", "released", "in_progress")
            ),
        ]
        if work_order_id is not None:
            conditions.append(ManufacturingWorkOrderTable.id == work_order_id)
        if product_id is not None:
            conditions.append(ManufacturingWorkOrderTable.product_id == product_id)
        stmt = select(ManufacturingWorkOrderTable).where(and_(*conditions))
        result = await session.execute(stmt)
        return [self._wo_to_wip(t) for t in result.scalars().all()]

    # ========================================================================
    # COST CARD
    # ========================================================================

    def _cost_card_to_domain(self, table: ManufacturingCostCardTable) -> CostCardEntity:
        """
        Rekonstruksi CostCardEntity dari ORM.
        FIX v6.4: baca `quantity_base`, `other_cost`, `unit_of_measure`;
        hitung ulang `unit_cost` dari `total_cost / quantity_base`.
        """
        total = Decimal(str(table.total_cost or 0))
        material = Decimal(str(table.material_cost or 0))
        labor = Decimal(str(table.labor_cost or 0))
        overhead = Decimal(str(table.overhead_cost or 0))
        other = Decimal(str(getattr(table, "other_cost", 0) or 0))

        qb = Decimal(str(getattr(table, "quantity_base", 0) or 0))
        if qb <= 0:
            qp = Decimal(str(table.quantity_produced or 0))
            qb = qp if qp > 0 else Decimal("1")

        uom = getattr(table, "unit_of_measure", None) or "pcs"
        unit = (total / qb).quantize(Decimal("0.01")) if qb > 0 else Decimal("0")

        completed = Decimal(str(table.quantity_produced or 0))
        planned = qb
        status = CostCardStatus.from_string(
            (getattr(table, "status", None) or "open").lower()
        )

        return CostCardEntity(
            cost_card_id=table.id,
            work_order_id=table.cost_card_id,
            work_order_number=table.product_code or "",
            product_id=table.product_id,
            product_code=table.product_code or "",
            product_name=table.product_code or "",
            planned_quantity=planned,
            completed_quantity=completed,
            material_cost=material,
            labor_cost=labor,
            overhead_cost=overhead,
            other_cost=other,
            total_cost=total,
            unit_cost=unit,
            status=status,
            quantity_base=qb,
            unit_of_measure=uom,
            entries=[],
            created_at=table.created_at or _utc_now(),
            updated_at=table.updated_at or _utc_now(),
            created_by="system",
            version=1,
        )

    def _apply_cost_card(
        self, table: ManufacturingCostCardTable, card: CostCardEntity
    ) -> None:
        """Mapping domain -> ORM. FIX v6.4: simpan semua kolom baru + LE."""
        table.legal_entity_id = self._get_legal_entity_id()
        table.cost_card_id = card.cost_card_id
        table.product_id = card.product_id
        table.product_code = card.product_code or None
        table.period = f"{card.created_at.year}-{card.created_at.month:02d}"

        table.material_cost = card.material_cost
        table.labor_cost = card.labor_cost
        table.overhead_cost = card.overhead_cost
        table.other_cost = card.other_cost
        table.total_cost = card.total_cost
        table.quantity_base = card.quantity_base
        table.unit_of_measure = card.unit_of_measure
        table.quantity_produced = card.completed_quantity
        table.unit_cost = (
            (card.total_cost / card.quantity_base).quantize(Decimal("0.01"))
            if card.quantity_base > 0
            else Decimal("0")
        )
        table.status = card.status.value
        table.notes = None

        if table.created_at is None:
            table.created_at = _utc_now()
        table.updated_at = _utc_now()

    async def save_cost_card(self, cost_card: CostCardEntity) -> None:
        session = await self._get_session()
        existing = await session.get(ManufacturingCostCardTable, cost_card.cost_card_id)
        if existing is None:
            table = ManufacturingCostCardTable(id=cost_card.cost_card_id)
            self._apply_cost_card(table, cost_card)
            session.add(table)
        else:
            self._apply_cost_card(existing, cost_card)
        await session.flush()
        try:
            await session.commit()
        except Exception as e:
            logger.warning(f"commit failed: {e}")
            await session.rollback()
            raise

    async def list_cost_cards(
        self,
        legal_entity_id: UUID,
        product_id: UUID | None = None,
        effective_as_of: date | None = None,
        is_active: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CostCardEntity]:
        session = await self._get_session()
        conditions = [
            # Exclude row "standard" dari listing biasa.
            ManufacturingCostCardTable.period != _STD_PERIOD,
        ]
        if product_id is not None:
            conditions.append(ManufacturingCostCardTable.product_id == product_id)
        if legal_entity_id is not None:
            conditions.append(
                ManufacturingCostCardTable.legal_entity_id == legal_entity_id
            )
        if effective_as_of is not None:
            conditions.append(
                ManufacturingCostCardTable.created_at <= datetime.combine(
                    effective_as_of, datetime.max.time(), tzinfo=timezone.utc
                )
            )
        stmt = (
            select(ManufacturingCostCardTable)
            .where(and_(*conditions))
            .order_by(ManufacturingCostCardTable.period.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        return [self._cost_card_to_domain(t) for t in result.scalars().all()]

    # ------------------------------------------------------------------------
    # FIX: 3 method abstract yang sebelumnya hilang (penyebab TypeError).
    # ------------------------------------------------------------------------

    async def get_cost_card(
        self, product_id: UUID, period: str
    ) -> CostCardEntity | None:
        """
        Retrieve cost card untuk (product_id, period=YYYY-MM).
        Exclude baris standard (period='standard').
        """
        if period == _STD_PERIOD:
            # Jangan pernah kembalikan standard cost dari sini
            return None
        session = await self._get_session()
        conditions = [
            ManufacturingCostCardTable.product_id == product_id,
            ManufacturingCostCardTable.period == period,
        ]
        legal_entity_id = self._legal_entity_id
        if legal_entity_id is not None:
            conditions.append(
                ManufacturingCostCardTable.legal_entity_id == legal_entity_id
            )
        stmt = (
            select(ManufacturingCostCardTable)
            .where(and_(*conditions))
            .order_by(ManufacturingCostCardTable.created_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        table = result.scalar_one_or_none()
        if table is None:
            return None
        return self._cost_card_to_domain(table)

    async def get_cost_card_by_id(
        self, cost_card_id: UUID
    ) -> CostCardEntity | None:
        """
        Retrieve cost card by primary key.
        Tolak kalau row-nya sebenarnya standard cost (period='standard').
        """
        session = await self._get_session()
        table = await session.get(ManufacturingCostCardTable, cost_card_id)
        if table is None:
            return None
        if (table.period or "").lower() == _STD_PERIOD:
            return None
        return self._cost_card_to_domain(table)

    async def list_cost_cards_by_product(
        self, product_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[CostCardEntity]:
        """
        List cost card (non-standard) untuk satu produk, terbaru dulu.
        """
        session = await self._get_session()
        conditions = [
            ManufacturingCostCardTable.product_id == product_id,
            ManufacturingCostCardTable.period != _STD_PERIOD,
        ]
        legal_entity_id = self._legal_entity_id
        if legal_entity_id is not None:
            conditions.append(
                ManufacturingCostCardTable.legal_entity_id == legal_entity_id
            )
        stmt = (
            select(ManufacturingCostCardTable)
            .where(and_(*conditions))
            .order_by(ManufacturingCostCardTable.period.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        return [self._cost_card_to_domain(t) for t in result.scalars().all()]

    # ========================================================================
    # STANDARD COST (disimpan di ManufacturingCostCardTable dengan period="standard")
    # ========================================================================

    def _std_to_domain(
        self, table: ManufacturingCostCardTable
    ) -> StandardCostEntity:
        total = Decimal(str(table.total_cost or 0))
        # Distribusi kasar: 50/30/20 (tidak ada kolom terpisah di ORM)
        material = (total * Decimal("0.5")).quantize(Decimal("0.01"))
        labor = (total * Decimal("0.3")).quantize(Decimal("0.01"))
        overhead = total - material - labor
        components = [
            StandardCostComponent(cost_element=CostElement.MATERIAL, amount=material),
            StandardCostComponent(cost_element=CostElement.LABOR, amount=labor),
            StandardCostComponent(cost_element=CostElement.OVERHEAD, amount=overhead),
        ]
        return StandardCostEntity(
            standard_cost_id=table.id,
            product_id=table.product_id,
            product_code=table.product_code,
            product_name=table.product_code,
            version=1,
            effective_date=table.created_at or _utc_now(),
            material_cost=material,
            labor_cost=labor,
            overhead_cost=overhead,
            total_cost=total,
            components=components,
            status=StandardCostStatus.ACTIVE,
            expiry_date=None,
            created_at=table.created_at or _utc_now(),
            updated_at=table.updated_at or _utc_now(),
            created_by="system",
            version_counter=1,
        )

    async def save_standard_cost(
        self, standard_cost: StandardCostEntity
    ) -> None:
        session = await self._get_session()
        stmt = (
            select(ManufacturingCostCardTable)
            .where(
                ManufacturingCostCardTable.product_id == standard_cost.product_id,
                ManufacturingCostCardTable.period == _STD_PERIOD,
            )
            .limit(1)
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing is None:
            table = ManufacturingCostCardTable(
                id=standard_cost.standard_cost_id,
                cost_card_id=standard_cost.standard_cost_id,
                product_id=standard_cost.product_id,
                product_code=standard_cost.product_code,
                period=_STD_PERIOD,
                material_cost=standard_cost.material_cost,
                labor_cost=standard_cost.labor_cost,
                overhead_cost=standard_cost.overhead_cost,
                total_cost=standard_cost.total_cost,
                quantity_produced=Decimal("0"),
                unit_cost=standard_cost.total_cost,
            )
            # Set kolom baru kalau ada
            if hasattr(table, "other_cost"):
                table.other_cost = Decimal("0")
            if hasattr(table, "quantity_base"):
                table.quantity_base = Decimal("1")
            if hasattr(table, "unit_of_measure"):
                table.unit_of_measure = "pcs"
            session.add(table)
        else:
            existing.material_cost = standard_cost.material_cost
            existing.labor_cost = standard_cost.labor_cost
            existing.overhead_cost = standard_cost.overhead_cost
            existing.total_cost = standard_cost.total_cost
            existing.unit_cost = standard_cost.total_cost
            existing.updated_at = _utc_now()
        await session.flush()
        try:
            await session.commit()
        except Exception as e:
            logger.warning(f"commit failed: {e}")
            await session.rollback()
            raise

    async def get_standard_cost_by_product(
        self, product_id: UUID, as_of_date: datetime | None = None
    ) -> StandardCostEntity | None:
        session = await self._get_session()
        stmt = (
            select(ManufacturingCostCardTable)
            .where(
                ManufacturingCostCardTable.product_id == product_id,
                ManufacturingCostCardTable.period == _STD_PERIOD,
            )
            .order_by(ManufacturingCostCardTable.created_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        table = result.scalar_one_or_none()
        if table is None:
            return None
        return self._std_to_domain(table)

    async def get_standard_cost_by_id(
        self, standard_cost_id: UUID
    ) -> StandardCostEntity | None:
        session = await self._get_session()
        table = await session.get(ManufacturingCostCardTable, standard_cost_id)
        if table is None or table.period != _STD_PERIOD:
            return None
        return self._std_to_domain(table)

    # ========================================================================
    # COST AGGREGATION (dipakai workflow cost flow / COGS / HPP close)
    # ========================================================================

    async def get_total_labor_for_work_order(self, work_order_id: UUID) -> Decimal:
        session = await self._get_session()
        stmt = select(ManufacturingWorkOrderTable.total_labor_cost).where(
            ManufacturingWorkOrderTable.id == work_order_id
        )
        result = await session.execute(stmt)
        value = result.scalar_one_or_none()
        return Decimal(str(value or 0))

    async def get_total_overhead_for_work_order(self, work_order_id: UUID) -> Decimal:
        session = await self._get_session()
        stmt = select(ManufacturingWorkOrderTable.total_overhead_cost).where(
            ManufacturingWorkOrderTable.id == work_order_id
        )
        result = await session.execute(stmt)
        value = result.scalar_one_or_none()
        return Decimal(str(value or 0))

    async def get_work_order_costs(self, work_order_id: UUID) -> WorkOrderCosts:
        session = await self._get_session()
        table = await session.get(ManufacturingWorkOrderTable, work_order_id)
        if table is None:
            return WorkOrderCosts(
                work_order_id=work_order_id,
                material_cost=Decimal("0"),
                labor_cost=Decimal("0"),
                overhead_cost=Decimal("0"),
            )
        return WorkOrderCosts(
            work_order_id=work_order_id,
            material_cost=Decimal(str(table.total_material_cost or 0)),
            labor_cost=Decimal(str(table.total_labor_cost or 0)),
            overhead_cost=Decimal(str(table.total_overhead_cost or 0)),
        )

    async def get_wip_value(self, legal_entity_id: UUID, as_of_date: date) -> Decimal:
        """Total WIP value = sum total_cost untuk WO open per as_of_date."""
        session = await self._get_session()
        as_of_dt = datetime.combine(as_of_date, datetime.max.time(), tzinfo=timezone.utc)
        stmt = select(
            func.coalesce(func.sum(ManufacturingWorkOrderTable.total_cost), 0)
        ).where(
            ManufacturingWorkOrderTable.legal_entity_id == legal_entity_id,
            ManufacturingWorkOrderTable.status.in_(("planned", "released", "in_progress")),
            ManufacturingWorkOrderTable.created_at <= as_of_dt,
        )
        result = await session.execute(stmt)
        return Decimal(str(result.scalar() or 0))

    async def get_manufacturing_costs(
        self, legal_entity_id: UUID, from_date: date, to_date: date
    ) -> Decimal:
        """Total manufacturing cost = sum total_cost untuk WO yang completed dalam range."""
        session = await self._get_session()
        stmt = select(
            func.coalesce(func.sum(ManufacturingWorkOrderTable.total_cost), 0)
        ).where(
            ManufacturingWorkOrderTable.legal_entity_id == legal_entity_id,
            ManufacturingWorkOrderTable.status == "completed",
            ManufacturingWorkOrderTable.actual_completion_date >= from_date,
            ManufacturingWorkOrderTable.actual_completion_date <= to_date,
        )
        result = await session.execute(stmt)
        return Decimal(str(result.scalar() or 0))

    # ========================================================================
    # PERIOD OPERATIONS
    # ========================================================================

    async def close_period(
        self, legal_entity_id: UUID, period: str, user_id: UUID
    ) -> None:
        """Tandai semua WO open sebagai 'closed' untuk periode tsb.

        Format period: "YYYY-MM". Filter berdasarkan planned_start_date dalam bulan itu.
        """
        session = await self._get_session()
        try:
            year_str, month_str = period.split("-")
            year, month = int(year_str), int(month_str)
        except (ValueError, AttributeError):
            raise ValueError(f"Invalid period format '{period}', expected YYYY-MM")

        import calendar
        last_day = calendar.monthrange(year, month)[1]
        period_start = date(year, month, 1)
        period_end = date(year, month, last_day)

        stmt = (
            select(ManufacturingWorkOrderTable)
            .where(
                ManufacturingWorkOrderTable.legal_entity_id == legal_entity_id,
                ManufacturingWorkOrderTable.status.in_(
                    ("planned", "released", "in_progress")
                ),
                ManufacturingWorkOrderTable.planned_start_date >= period_start,
                ManufacturingWorkOrderTable.planned_start_date <= period_end,
            )
        )
        result = await session.execute(stmt)
        for table in result.scalars().all():
            table.status = "closed"
            table.updated_at = _utc_now()
        await session.flush()
        try:
            await session.commit()
        except Exception as e:
            logger.warning(f"commit failed: {e}")
            await session.rollback()
            raise

    async def is_period_closed(self, legal_entity_id: UUID, period: str) -> bool:
        """True kalau tidak ada WO open pada periode tsb."""
        session = await self._get_session()
        try:
            year_str, month_str = period.split("-")
            year, month = int(year_str), int(month_str)
        except (ValueError, AttributeError):
            raise ValueError(f"Invalid period format '{period}', expected YYYY-MM")

        import calendar
        last_day = calendar.monthrange(year, month)[1]
        period_start = date(year, month, 1)
        period_end = date(year, month, last_day)

        stmt = (
            select(func.count())
            .select_from(ManufacturingWorkOrderTable)
            .where(
                ManufacturingWorkOrderTable.legal_entity_id == legal_entity_id,
                ManufacturingWorkOrderTable.status.in_(
                    ("planned", "released", "in_progress")
                ),
                ManufacturingWorkOrderTable.planned_start_date >= period_start,
                ManufacturingWorkOrderTable.planned_start_date <= period_end,
            )
        )
        result = await session.execute(stmt)
        return (result.scalar() or 0) == 0

    # ========================================================================
    # BATCH OPERATIONS
    # ========================================================================

    async def save_bom_batch(self, boms: list[BillOfMaterialsEntity]) -> None:
        for bom in boms:
            await self.save_bom(bom)

    async def save_work_order_batch(
        self, work_orders: list[WorkOrderEntity]
    ) -> None:
        for wo in work_orders:
            await self.save_work_order(wo)


# ============================================================================
# Alias untuk kompatibilitas dengan adapter registry
# ============================================================================

SQLAlchemyManufacturingRepositoryImpl = SQLAlchemyManufacturingRepository

__all__ = [
    "SQLAlchemyManufacturingRepository",
    "SQLAlchemyManufacturingRepositoryImpl",
]
