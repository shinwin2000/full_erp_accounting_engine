#!/usr/bin/env python3
"""
Module: manufacturing_work_order_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel work order manufaktur.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import (
    Base,
    LegalEntityMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)


class ManufacturingWorkOrderTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    __tablename__ = "manufacturing_work_order"
    __table_args__ = (
        UniqueConstraint("wo_number", "legal_entity_id", name="uq_wo_number_legal_entity"),
        CheckConstraint("wo_number IS NOT NULL AND wo_number != ''", name="ck_wo_number"),
        CheckConstraint("product_id IS NOT NULL", name="ck_wo_product"),
        CheckConstraint(
            "status IN ('draft', 'planned', 'released', 'in_progress', 'completed', 'cancelled')",
            name="ck_wo_status",
        ),
        Index("idx_wo_number", "wo_number"),
        Index("idx_wo_product", "product_id"),
        Index("idx_wo_status", "status"),
        Index("idx_wo_legal_entity", "legal_entity_id"),
        Index("idx_wo_planned_start_date", "planned_start_date"),
        Index("idx_wo_actual_completion_date", "actual_completion_date")
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    wo_number: Mapped[str] = mapped_column(String(50), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    product_code: Mapped[str] = mapped_column(String(50), nullable=False)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    bill_of_materials_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False, default=1)
    completed_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False, default=0)
    rejected_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False, default=0)
    planned_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    planned_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    actual_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    actual_completion_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    priority: Mapped[str] = mapped_column(String(10), nullable=False, default="normal")
    total_material_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    total_labor_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    total_overhead_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def remaining_quantity(self) -> Decimal:
        return self.quantity - self.completed_quantity

    @property
    def completion_percentage(self) -> float:
        if self.quantity == 0:
            return 0.0
        return float((self.completed_quantity / self.quantity) * 100)

    @property
    def is_completed(self) -> bool:
        return self.status == "completed"

    @property
    def is_in_progress(self) -> bool:
        return self.status == "in_progress"

    def start_production(self, start_date: date) -> None:
        if self.status not in ("planned", "released"):
            raise ValueError(f"Cannot start work order with status {self.status}")
        self.status = "in_progress"
        self.actual_start_date = start_date
        self.increment_version()

    def complete_production(self, completion_date: date, completed_qty: Decimal) -> None:
        if self.status != "in_progress":
            raise ValueError(f"Cannot complete work order with status {self.status}")
        self.status = "completed"
        self.completed_quantity = completed_qty
        self.actual_completion_date = completion_date
        self.increment_version()

    def cancel(self) -> None:
        if self.status in ("completed", "cancelled"):
            raise ValueError(f"Cannot cancel work order with status {self.status}")
        self.status = "cancelled"
        self.increment_version()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "wo_number": self.wo_number,
            "product_id": str(self.product_id),
            "product_code": self.product_code,
            "product_name": self.product_name,
            "bill_of_materials_id": str(self.bill_of_materials_id) if self.bill_of_materials_id else None,
            "quantity": float(self.quantity),
            "completed_quantity": float(self.completed_quantity),
            "rejected_quantity": float(self.rejected_quantity),
            "remaining_quantity": float(self.remaining_quantity),
            "completion_percentage": self.completion_percentage,
            "planned_start_date": self.planned_start_date.isoformat() if self.planned_start_date else None,
            "planned_end_date": self.planned_end_date.isoformat() if self.planned_end_date else None,
            "actual_start_date": self.actual_start_date.isoformat() if self.actual_start_date else None,
            "actual_completion_date": self.actual_completion_date.isoformat() if self.actual_completion_date else None,
            "status": self.status,
            "priority": self.priority,
            "total_material_cost": float(self.total_material_cost),
            "total_labor_cost": float(self.total_labor_cost),
            "total_overhead_cost": float(self.total_overhead_cost),
            "total_cost": float(self.total_cost),
            "notes": self.notes,
            "legal_entity_id": str(self.legal_entity_id),
        }


__all__ = ["ManufacturingWorkOrderTable"]
