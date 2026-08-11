#!/usr/bin/env python3
"""
Module: manufacturing_cost_card_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Read model untuk kartu biaya produksi (cost card).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, Index, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import Base, TimestampMixin


class ManufacturingCostCardTable(Base, TimestampMixin):
    __tablename__ = "manufacturing_cost_card"
    __table_args__ = (
        Index("idx_mfg_cost_card_product", "product_id"),
        Index("idx_mfg_cost_card_period", "period"),
        CheckConstraint("total_cost >= 0", name="ck_mfg_cost_total_nonneg"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cost_card_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    product_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    product_code: Mapped[str] = mapped_column(String(50), nullable=False)
    period: Mapped[str] = mapped_column(String(20), nullable=False)
    material_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=0)
    labor_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=0)
    overhead_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=0)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=0)
    quantity_produced: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=0)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=0)

    @property
    def cost_per_unit(self) -> Decimal:
        if self.quantity_produced == 0:
            return Decimal(0)
        return self.total_cost / self.quantity_produced

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "cost_card_id": str(self.cost_card_id),
            "product_id": str(self.product_id),
            "product_code": self.product_code,
            "period": self.period,
            "material_cost": float(self.material_cost),
            "labor_cost": float(self.labor_cost),
            "overhead_cost": float(self.overhead_cost),
            "total_cost": float(self.total_cost),
            "quantity_produced": float(self.quantity_produced),
            "unit_cost": float(self.unit_cost),
            "cost_per_unit": float(self.cost_per_unit),
        }


CostCardTable = ManufacturingCostCardTable
CostCardReadModel = ManufacturingCostCardTable
ManufacturingCostCardReadModel = ManufacturingCostCardTable

__all__ = [
    "CostCardReadModel",
    "CostCardTable",
    "ManufacturingCostCardReadModel",
    "ManufacturingCostCardTable",
]