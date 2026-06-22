#!/usr/bin/env python3
"""
Module: cost_card_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel cost_card.
               Tabel ini menyimpan cost card (kartu biaya) untuk produk manufaktur,
               berisi rincian biaya bahan baku, tenaga kerja, dan overhead per unit.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    Index,
    Integer,
    Numeric,
    String,
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


class CostCardTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    __tablename__ = "cost_card"
    __table_args__ = (
        UniqueConstraint(
            "cost_card_code", "legal_entity_id", name="uq_cost_card_code_legal_entity"
        ),
        CheckConstraint("cost_card_code IS NOT NULL", name="ck_cost_card_code"),
        CheckConstraint("product_id IS NOT NULL", name="ck_cost_card_product"),
        CheckConstraint(
            "status IN ('draft', 'active', 'inactive', 'obsolete')", name="ck_cost_card_status"
        ),
        CheckConstraint("total_cost >= 0", name="ck_cost_card_total_nonneg"),
        CheckConstraint("material_cost >= 0", name="ck_cost_card_material_nonneg"),
        CheckConstraint("labor_cost >= 0", name="ck_cost_card_labor_nonneg"),
        CheckConstraint("overhead_cost >= 0", name="ck_cost_card_overhead_nonneg"),
        Index("idx_cost_card_code", "cost_card_code"),
        Index("idx_cost_card_product", "product_id"),
        Index("idx_cost_card_status", "status"),
        Index("idx_cost_card_effective_date", "effective_date"),
        Index("idx_cost_card_legal_entity", "legal_entity_id"),
    )

    cost_card_code: Mapped[str] = mapped_column(String(50), nullable=False)
    product_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    product_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Cost components
    material_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    labor_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    overhead_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    other_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")

    # Quantity base (cost per unit)
    quantity_base: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=1
    )  # biasanya 1 unit
    unit_of_measure: Mapped[str] = mapped_column(String(10), nullable=False, default="pcs")

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Detailed breakdown as JSON
    breakdown: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    @property
    def cost_per_unit(self) -> Decimal:
        if self.quantity_base == 0:
            return Decimal(0)
        return self.total_cost / self.quantity_base

    @property
    def is_active_card(self) -> bool:
        return self.status == "active" and self.is_active

    def activate(self) -> None:
        if self.status != "draft":
            raise ValueError(f"Cannot activate cost card with status {self.status}")
        self.status = "active"
        self.is_active = True
        self.increment_version()

    def deactivate(self) -> None:
        self.status = "inactive"
        self.is_active = False
        self.increment_version()

    def calculate_total(self) -> None:
        self.total_cost = (
            self.material_cost + self.labor_cost + self.overhead_cost + self.other_cost
        )
        self.increment_version()


__all__ = ["CostCardTable"]
