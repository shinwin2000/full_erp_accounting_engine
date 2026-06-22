#!/usr/bin/env python3
"""
Module: bill_of_materials_line_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel bill_of_materials_line.
               Tabel ini menyimpan komponen-komponen dari Bill of Materials (BOM),
               termasuk produk komponen, kuantitas, unit of measure, dan biaya per unit.
Dependencies:
- sqlalchemy.orm (Mapped, mapped_column, relationship)
- infrastructure.persistence_orm.base_model
Audit: Setiap perubahan BOM line dicatat bersama dengan BOM.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import (
    Base,
    LegalEntityMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)

if TYPE_CHECKING:
    from infrastructure.persistence_orm.bill_of_materials_table import BillOfMaterialsTable


class BillOfMaterialsLineTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    """
    Model untuk tabel bill_of_materials_line.
    Menyimpan komponen BOM.
    """

    __tablename__ = "bill_of_materials_line"
    __table_args__ = (
        UniqueConstraint("bom_id", "line_number", name="uq_bom_line_number"),
        CheckConstraint("line_number > 0", name="ck_bom_line_number_positive"),
        CheckConstraint("quantity > 0", name="ck_bom_line_quantity_positive"),
        CheckConstraint("unit_cost >= 0", name="ck_bom_line_unit_cost_nonneg"),
        CheckConstraint("total_cost >= 0", name="ck_bom_line_total_cost_nonneg"),
        Index("idx_bom_line_bom", "bom_id"),
        Index("idx_bom_line_component", "component_product_id"),
        {"schema": "public", "extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bom_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("public.bill_of_materials.id", ondelete="CASCADE"),  # schema explicitly added
        nullable=False,
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    component_product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    component_product_code: Mapped[str] = mapped_column(String(50), nullable=False)
    component_product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    unit_of_measure: Mapped[str] = mapped_column(String(10), nullable=False, default="pcs")
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False, default=0)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    scrap_percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # =========================================================================
    # RELATIONSHIP back to header (many-to-one)
    # Menggunakan back_populates yang sama dengan di BillOfMaterialsTable.lines
    # =========================================================================
    bom: Mapped[BillOfMaterialsTable] = relationship(
        "BillOfMaterialsTable",
        back_populates="lines",
        foreign_keys=[bom_id],
    )

    def calculate_total_cost(self) -> None:
        """Hitung total cost berdasarkan quantity dan unit cost, ditambah scrap."""
        base_cost = self.quantity * self.unit_cost
        scrap_adjustment = base_cost * (self.scrap_percentage / 100)
        self.total_cost = (base_cost + scrap_adjustment).quantize(Decimal("0.01"))
        self.increment_version()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "bom_id": str(self.bom_id),
            "line_number": self.line_number,
            "component_product_id": str(self.component_product_id),
            "component_product_code": self.component_product_code,
            "component_product_name": self.component_product_name,
            "quantity": float(self.quantity),
            "unit_of_measure": self.unit_of_measure,
            "unit_cost": float(self.unit_cost),
            "total_cost": float(self.total_cost),
            "scrap_percentage": float(self.scrap_percentage),
            "notes": self.notes,
            "legal_entity_id": str(self.legal_entity_id),
        }


__all__ = ["BillOfMaterialsLineTable"]
