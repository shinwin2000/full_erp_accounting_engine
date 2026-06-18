#!/usr/bin/env python3
"""
Module: cost_card_per_work_order.py
Layer: Projections (Subledger)
Responsibility: Membangun read model cost card per work order untuk manufacturing.
               Menyimpan rincian biaya bahan baku, tenaga kerja, overhead, dan total
               biaya per work order. Mendukung query untuk perbandingan actual vs standard,
               analisis varian, dan perhitungan HPP produk.
Dependencies:
- asyncio, logging, datetime, decimal
- sqlalchemy.ext.asyncio
- infrastructure.database.session_factory_sqlalchemy
- infrastructure.persistence_orm.work_order_table
- infrastructure.persistence_orm.manufacturing_cost_table (asumsi)
- infrastructure.persistence_orm.bill_of_materials_table
Audit: Cost card per work order digunakan untuk costing dan variance analysis.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, insert, select, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession

# Internal dependencies
from infrastructure.database.session_factory_sqlalchemy import get_session_factory
from infrastructure.persistence_orm.work_order_table import WorkOrderTable
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

PROJECTION_NAME = "cost_card_per_work_order"

# Cost element types
COST_ELEMENT_MATERIAL = "material"
COST_ELEMENT_LABOR = "labor"
COST_ELEMENT_OVERHEAD = "overhead"
COST_ELEMENT_OTHER = "other"

# ============================================================================
# EXCEPTIONS
# ============================================================================


class CostCardError(Exception):
    """Base exception untuk cost card projection."""

    pass


# ============================================================================
# COST CARD PER WORK ORDER PROJECTION
# ============================================================================


class CostCardPerWorkOrder:
    """
    Read model cost card per work order.

    Fitur:
    - Agregasi biaya per work order dari berbagai sumber
    - Breakdown per cost element (material, labor, overhead)
    - Perbandingan actual vs standard cost
    - Query untuk completed work orders dalam periode
    - Mendukung analisis varian
    """

    def __init__(self):
        self._session_factory = None

    async def _get_session(self) -> AsyncSession:
        if self._session_factory is None:
            self._session_factory = await get_session_factory()
        return self._session_factory.get_session()

    async def compute_cost_card(self, work_order_id: UUID, legal_entity_id: UUID) -> dict[str, Any]:
        """
        Menghitung cost card untuk satu work order berdasarkan material issues,
        labor records, dan machine hours dari sistem MES.

        Returns:
            Dictionary dengan rincian biaya per element dan total.
        """
        async with await self._get_session() as session:
            # Get work order info
            wo_stmt = select(WorkOrderTable).where(
                WorkOrderTable.id == work_order_id,
                WorkOrderTable.legal_entity_id == legal_entity_id,
            )
            wo_result = await session.execute(wo_stmt)
            work_order = wo_result.scalar_one_or_none()
            if not work_order:
                raise CostCardError(f"Work order {work_order_id} not found")

            # In a real implementation, we would query material_issue, labor_record, machine_usage tables
            # For this projection, we'll assume tables exist and query them.
            # Since those tables are not yet defined, we'll use placeholders with comments.

            # 1. Material costs
            material_stmt = text("""
                SELECT COALESCE(SUM(quantity * unit_cost), 0) as total_material
                FROM material_issue
                WHERE work_order_id = :wo_id AND deleted_at IS NULL
            """)
            material_result = await session.execute(material_stmt, {"wo_id": work_order_id})
            total_material = Decimal(str(material_result.scalar() or 0))

            # 2. Labor costs
            labor_stmt = text("""
                SELECT COALESCE(SUM(hours * hourly_rate), 0) as total_labor
                FROM labor_record
                WHERE work_order_id = :wo_id AND deleted_at IS NULL
            """)
            labor_result = await session.execute(labor_stmt, {"wo_id": work_order_id})
            total_labor = Decimal(str(labor_result.scalar() or 0))

            # 3. Machine/overhead costs
            machine_stmt = text("""
                SELECT COALESCE(SUM(machine_hours * cost_per_hour), 0) as total_machine
                FROM machine_usage
                WHERE work_order_id = :wo_id AND deleted_at IS NULL
            """)
            machine_result = await session.execute(machine_stmt, {"wo_id": work_order_id})
            total_machine = Decimal(str(machine_result.scalar() or 0))

            # 4. Applied overhead (if using predetermined rate)
            overhead_stmt = text("""
                SELECT COALESCE(SUM(overhead_amount), 0) as total_overhead
                FROM overhead_allocation
                WHERE work_order_id = :wo_id AND deleted_at IS NULL
            """)
            overhead_result = await session.execute(overhead_stmt, {"wo_id": work_order_id})
            total_overhead = Decimal(str(overhead_result.scalar() or 0))

            total_cost = total_material + total_labor + total_machine + total_overhead

            # Get standard cost from BOM and routing (if available)
            standard_material = work_order.standard_material_cost or Decimal(0)
            standard_labor = work_order.standard_labor_cost or Decimal(0)
            standard_overhead = work_order.standard_overhead_cost or Decimal(0)
            standard_total = standard_material + standard_labor + standard_overhead

            # Calculate variances
            material_variance = total_material - standard_material
            labor_variance = total_labor - standard_labor
            overhead_variance = total_overhead - standard_overhead
            total_variance = total_cost - standard_total

            # Quantity completed
            completed_qty = work_order.completed_quantity or Decimal(0)
            unit_cost = total_cost / completed_qty if completed_qty > 0 else Decimal(0)
            standard_unit_cost = (
                standard_total / work_order.planned_quantity
                if work_order.planned_quantity > 0
                else Decimal(0)
            )

            return {
                "work_order_id": str(work_order_id),
                "work_order_number": work_order.work_order_number,
                "product_id": str(work_order.product_id),
                "product_name": work_order.product_name,
                "status": work_order.status,
                "planned_quantity": float(work_order.planned_quantity),
                "completed_quantity": float(completed_qty),
                "cost_breakdown": {
                    "material": {
                        "actual": float(total_material),
                        "standard": float(standard_material),
                        "variance": float(material_variance),
                        "variance_percent": float(material_variance / standard_material * 100)
                        if standard_material != 0
                        else 0,
                    },
                    "labor": {
                        "actual": float(total_labor),
                        "standard": float(standard_labor),
                        "variance": float(labor_variance),
                        "variance_percent": float(labor_variance / standard_labor * 100)
                        if standard_labor != 0
                        else 0,
                    },
                    "overhead": {
                        "actual": float(total_overhead),
                        "standard": float(standard_overhead),
                        "variance": float(overhead_variance),
                        "variance_percent": float(overhead_variance / standard_overhead * 100)
                        if standard_overhead != 0
                        else 0,
                    },
                },
                "total_actual_cost": float(total_cost),
                "total_standard_cost": float(standard_total),
                "total_variance": float(total_variance),
                "unit_actual_cost": float(unit_cost),
                "unit_standard_cost": float(standard_unit_cost),
                "unit_variance": float(unit_cost - standard_unit_cost),
                "last_updated": datetime.now(UTC).isoformat(),
            }

    async def save_cost_card(self, cost_card_data: dict[str, Any]) -> None:
        """
        Menyimpan cost card ke tabel materialized.
        """
        async with await self._get_session() as session, session.begin():
            # Delete existing
            await session.execute(
                delete(CostCardTable).where(
                    CostCardTable.work_order_id == UUID(cost_card_data["work_order_id"])
                )
            )

            stmt = insert(CostCardTable).values(
                id=uuid4(),
                work_order_id=UUID(cost_card_data["work_order_id"]),
                work_order_number=cost_card_data["work_order_number"],
                product_id=UUID(cost_card_data["product_id"]),
                product_name=cost_card_data["product_name"],
                status=cost_card_data["status"],
                planned_quantity=Decimal(str(cost_card_data["planned_quantity"])),
                completed_quantity=Decimal(str(cost_card_data["completed_quantity"])),
                material_actual=Decimal(
                    str(cost_card_data["cost_breakdown"]["material"]["actual"])
                ),
                material_standard=Decimal(
                    str(cost_card_data["cost_breakdown"]["material"]["standard"])
                ),
                material_variance=Decimal(
                    str(cost_card_data["cost_breakdown"]["material"]["variance"])
                ),
                labor_actual=Decimal(str(cost_card_data["cost_breakdown"]["labor"]["actual"])),
                labor_standard=Decimal(str(cost_card_data["cost_breakdown"]["labor"]["standard"])),
                labor_variance=Decimal(str(cost_card_data["cost_breakdown"]["labor"]["variance"])),
                overhead_actual=Decimal(
                    str(cost_card_data["cost_breakdown"]["overhead"]["actual"])
                ),
                overhead_standard=Decimal(
                    str(cost_card_data["cost_breakdown"]["overhead"]["standard"])
                ),
                overhead_variance=Decimal(
                    str(cost_card_data["cost_breakdown"]["overhead"]["variance"])
                ),
                total_actual=Decimal(str(cost_card_data["total_actual_cost"])),
                total_standard=Decimal(str(cost_card_data["total_standard_cost"])),
                total_variance=Decimal(str(cost_card_data["total_variance"])),
                unit_actual=Decimal(str(cost_card_data["unit_actual_cost"])),
                unit_standard=Decimal(str(cost_card_data["unit_standard_cost"])),
                unit_variance=Decimal(str(cost_card_data["unit_variance"])),
                last_updated=datetime.now(UTC),
            )
            await session.execute(stmt)
            await session.commit()

    async def get_cost_card(self, work_order_id: UUID) -> dict | None:
        """
        Mendapatkan cost card yang sudah tersimpan.
        """
        async with await self._get_session() as session:
            stmt = select(CostCardTable).where(CostCardTable.work_order_id == work_order_id)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                return None
            return {
                "work_order_id": str(row.work_order_id),
                "work_order_number": row.work_order_number,
                "product_id": str(row.product_id),
                "product_name": row.product_name,
                "status": row.status,
                "planned_quantity": float(row.planned_quantity),
                "completed_quantity": float(row.completed_quantity),
                "cost_breakdown": {
                    "material": {
                        "actual": float(row.material_actual),
                        "standard": float(row.material_standard),
                        "variance": float(row.material_variance),
                    },
                    "labor": {
                        "actual": float(row.labor_actual),
                        "standard": float(row.labor_standard),
                        "variance": float(row.labor_variance),
                    },
                    "overhead": {
                        "actual": float(row.overhead_actual),
                        "standard": float(row.overhead_standard),
                        "variance": float(row.overhead_variance),
                    },
                },
                "total_actual_cost": float(row.total_actual),
                "total_standard_cost": float(row.total_standard),
                "total_variance": float(row.total_variance),
                "unit_actual_cost": float(row.unit_actual),
                "unit_standard_cost": float(row.unit_standard),
                "unit_variance": float(row.unit_variance),
                "last_updated": row.last_updated.isoformat(),
            }

    async def get_cost_cards_by_period(
        self, legal_entity_id: UUID, start_date: date, end_date: date
    ) -> list[dict]:
        """
        Mendapatkan semua cost card untuk work order yang selesai dalam periode.
        """
        async with await self._get_session() as session:
            # First get work orders completed in period
            wo_stmt = select(WorkOrderTable.id).where(
                WorkOrderTable.legal_entity_id == legal_entity_id,
                WorkOrderTable.status == "completed",
                WorkOrderTable.actual_end_date >= start_date,
                WorkOrderTable.actual_end_date <= end_date,
            )
            wo_result = await session.execute(wo_stmt)
            wo_ids = wo_result.scalars().all()

            if not wo_ids:
                return []

            stmt = select(CostCardTable).where(CostCardTable.work_order_id.in_(wo_ids))
            result = await session.execute(stmt)
            rows = result.scalars().all()

            return [
                {
                    "work_order_id": str(r.work_order_id),
                    "work_order_number": r.work_order_number,
                    "product_name": r.product_name,
                    "total_actual_cost": float(r.total_actual),
                    "total_standard_cost": float(r.total_standard),
                    "total_variance": float(r.total_variance),
                }
                for r in rows
            ]

    async def get_variance_analysis(
        self, legal_entity_id: UUID, period_start: date, period_end: date
    ) -> dict:
        """
        Mendapatkan ringkasan analisis varian untuk periode.
        """
        cost_cards = await self.get_cost_cards_by_period(legal_entity_id, period_start, period_end)

        total_actual = sum(c["total_actual_cost"] for c in cost_cards)
        total_standard = sum(c["total_standard_cost"] for c in cost_cards)
        total_variance = total_actual - total_standard

        return {
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "total_work_orders": len(cost_cards),
            "total_actual_cost": total_actual,
            "total_standard_cost": total_standard,
            "total_variance": total_variance,
            "variance_percent": (total_variance / total_standard * 100)
            if total_standard != 0
            else 0,
            "favorable_unfavorable": "Unfavorable" if total_variance > 0 else "Favorable",
            "by_product": self._group_by_product(cost_cards),
        }

    def _group_by_product(self, cost_cards: list[dict]) -> list[dict]:
        """Group variance by product."""
        products = {}
        for card in cost_cards:
            prod_name = card["product_name"]
            if prod_name not in products:
                products[prod_name] = {"actual": 0, "standard": 0, "count": 0}
            products[prod_name]["actual"] += card["total_actual_cost"]
            products[prod_name]["standard"] += card["total_standard_cost"]
            products[prod_name]["count"] += 1

        return [
            {
                "product_name": name,
                "work_orders": data["count"],
                "actual_cost": data["actual"],
                "standard_cost": data["standard"],
                "variance": data["actual"] - data["standard"],
            }
            for name, data in products.items()
        ]

    async def rebuild_for_work_order(self, work_order_id: UUID, legal_entity_id: UUID) -> None:
        """
        Membangun ulang cost card untuk work order tertentu.
        """
        cost_card = await self.compute_cost_card(work_order_id, legal_entity_id)
        await self.save_cost_card(cost_card)
        logger.info(f"Cost card rebuilt for work order {work_order_id}")

    async def rebuild_all(self, legal_entity_id: UUID) -> dict:
        """
        Membangun ulang semua cost card untuk legal entity.
        """
        async with await self._get_session() as session:
            wo_stmt = select(WorkOrderTable.id).where(
                WorkOrderTable.legal_entity_id == legal_entity_id
            )
            wo_result = await session.execute(wo_stmt)
            wo_ids = wo_result.scalars().all()

        success = 0
        errors = 0
        for wo_id in wo_ids:
            try:
                await self.rebuild_for_work_order(wo_id, legal_entity_id)
                success += 1
            except Exception as e:
                logger.error(f"Failed to rebuild cost card for WO {wo_id}: {e}")
                errors += 1

        return {"success": success, "errors": errors}

    async def incremental_update(self, work_order_id: UUID, legal_entity_id: UUID) -> None:
        """
        Incremental update ketika ada perubahan biaya pada work order.
        """
        await self.rebuild_for_work_order(work_order_id, legal_entity_id)
        logger.info(f"Cost card incrementally updated for work order {work_order_id}")


# ============================================================================
# ORM MODEL (tambahan)
# ============================================================================

from sqlalchemy import Column, DateTime, Index, Numeric, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class CostCardTable(Base):
    __tablename__ = "cost_card"
    __table_args__ = (
        Index("idx_cost_card_work_order", "work_order_id"),
        Index("idx_cost_card_product", "product_id"),
        {"schema": "projections"},
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True)
    work_order_id = Column(PGUUID(as_uuid=True), nullable=False)
    work_order_number = Column(String(50), nullable=False)
    product_id = Column(PGUUID(as_uuid=True), nullable=False)
    product_name = Column(String(200), nullable=True)
    status = Column(String(20), nullable=False)
    planned_quantity = Column(Numeric(20, 2), nullable=False, default=0)
    completed_quantity = Column(Numeric(20, 2), nullable=False, default=0)
    material_actual = Column(Numeric(20, 2), nullable=False, default=0)
    material_standard = Column(Numeric(20, 2), nullable=False, default=0)
    material_variance = Column(Numeric(20, 2), nullable=False, default=0)
    labor_actual = Column(Numeric(20, 2), nullable=False, default=0)
    labor_standard = Column(Numeric(20, 2), nullable=False, default=0)
    labor_variance = Column(Numeric(20, 2), nullable=False, default=0)
    overhead_actual = Column(Numeric(20, 2), nullable=False, default=0)
    overhead_standard = Column(Numeric(20, 2), nullable=False, default=0)
    overhead_variance = Column(Numeric(20, 2), nullable=False, default=0)
    total_actual = Column(Numeric(20, 2), nullable=False, default=0)
    total_standard = Column(Numeric(20, 2), nullable=False, default=0)
    total_variance = Column(Numeric(20, 2), nullable=False, default=0)
    unit_actual = Column(Numeric(20, 2), nullable=False, default=0)
    unit_standard = Column(Numeric(20, 2), nullable=False, default=0)
    unit_variance = Column(Numeric(20, 2), nullable=False, default=0)
    last_updated = Column(DateTime(timezone=True), nullable=False)


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_cost_card_projection: CostCardPerWorkOrder | None = None


async def get_cost_card_projection() -> CostCardPerWorkOrder:
    """Get singleton instance of CostCardPerWorkOrder."""
    global _cost_card_projection
    if _cost_card_projection is None:
        _cost_card_projection = CostCardPerWorkOrder()
    return _cost_card_projection


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["CostCardError", "CostCardPerWorkOrder", "get_cost_card_projection"]
