#!/usr/bin/env python3
"""
Module: work_order_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel work_order.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import (
    Base,
    LegalEntityMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)


class WorkOrderTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    __tablename__ = "work_order"
    __table_args__ = (
        UniqueConstraint("work_order_number", "legal_entity_id", name="uq_work_order_number_legal_entity"),
        CheckConstraint("work_order_number IS NOT NULL", name="ck_work_order_number"),
        CheckConstraint(
            "status IN ('planned', 'released', 'in_progress', 'completed', 'cancelled', 'closed')",
            name="ck_work_order_status",
        ),
        CheckConstraint("planned_quantity > 0", name="ck_work_order_planned_positive"),
        CheckConstraint("completed_quantity >= 0", name="ck_work_order_completed_nonneg"),
        CheckConstraint("rejected_quantity >= 0", name="ck_work_order_rejected_nonneg"),
        Index("idx_work_order_number", "work_order_number"),
        Index("idx_work_order_product", "product_id"),
        Index("idx_work_order_status", "status"),
        Index("idx_work_order_legal_entity", "legal_entity_id"),
        Index("idx_work_order_bom", "bom_id"),
        {"extend_existing": True},  # opsional, untuk keamanan
    )

    # id diwarisi dari Base (primary key UUID), tidak perlu didefinisikan ulang

    work_order_number: Mapped[str] = mapped_column(String(50), nullable=False)
    product_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    product_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    planned_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    completed_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    rejected_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    bom_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("bill_of_materials.id", ondelete="SET NULL"),
        nullable=True
    )
    routing_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True
    )
    planned_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    planned_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    actual_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    actual_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    standard_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    actual_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")
    cost_center: Mapped[str | None] = mapped_column(String(20), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    @property
    def remaining_quantity(self) -> Decimal:
        return self.planned_quantity - self.completed_quantity - self.rejected_quantity

    @property
    def completion_percentage(self) -> float:
        if self.planned_quantity == 0:
            return 0.0
        return float((self.completed_quantity / self.planned_quantity) * 100)

    @property
    def cost_variance(self) -> Decimal:
        return self.actual_cost - self.standard_cost

    @property
    def is_completed(self) -> bool:
        return self.status == "completed"

    @property
    def is_in_progress(self) -> bool:
        return self.status == "in_progress"

    @property
    def is_closed(self) -> bool:
        return self.status == "closed"

    def release(self) -> None:
        if self.status != "planned":
            raise ValueError(f"Cannot release work order with status {self.status}")
        self.status = "released"

    def start_production(self) -> None:
        if self.status != "released":
            raise ValueError(f"Cannot start work order with status {self.status}")
        self.status = "in_progress"
        self.actual_start_date = date.today()

    def complete(self) -> None:
        if self.status != "in_progress":
            raise ValueError(f"Cannot complete work order with status {self.status}")
        self.status = "completed"
        self.actual_end_date = date.today()

    def close(self) -> None:
        if self.status != "completed":
            raise ValueError(f"Cannot close work order with status {self.status}")
        self.status = "closed"

    def cancel(self) -> None:
        if self.status in ("completed", "closed", "cancelled"):
            raise ValueError(f"Cannot cancel work order with status {self.status}")
        self.status = "cancelled"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "work_order_number": self.work_order_number,
            "product_id": str(self.product_id),
            "product_name": self.product_name,
            "planned_quantity": float(self.planned_quantity),
            "completed_quantity": float(self.completed_quantity),
            "rejected_quantity": float(self.rejected_quantity),
            "remaining_quantity": float(self.remaining_quantity),
            "completion_percentage": self.completion_percentage,
            "bom_id": str(self.bom_id) if self.bom_id else None,
            "routing_id": str(self.routing_id) if self.routing_id else None,
            "planned_start_date": self.planned_start_date.isoformat(),
            "planned_end_date": self.planned_end_date.isoformat(),
            "actual_start_date": self.actual_start_date.isoformat() if self.actual_start_date else None,
            "actual_end_date": self.actual_end_date.isoformat() if self.actual_end_date else None,
            "standard_cost": float(self.standard_cost),
            "actual_cost": float(self.actual_cost),
            "cost_variance": float(self.cost_variance),
            "status": self.status,
            "cost_center": self.cost_center,
            "notes": self.notes,
            "legal_entity_id": str(self.legal_entity_id),
            "version": self.version,
        }


__all__ = ["WorkOrderTable"]