#!/usr/bin/env python3
"""
Module: stock_opname_line_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model SQLAlchemy untuk line item stock opname.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import Base

if TYPE_CHECKING:
    from infrastructure.persistence_orm.stock_opname_table import StockOpnameTable


class StockOpnameLineTable(Base):
    __tablename__ = "stock_opname_line"
    __table_args__ = (
        CheckConstraint("system_quantity >= 0", name="ck_sol_system_qty_nonneg"),
        CheckConstraint("physical_quantity >= 0", name="ck_sol_physical_qty_nonneg"),
        CheckConstraint("difference_quantity IS NOT NULL", name="ck_sol_diff_not_null"),
        Index("idx_sol_opname", "stock_opname_id"),
        Index("idx_sol_product", "product_id")
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stock_opname_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stock_opname.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    product_code: Mapped[str] = mapped_column(String(50), nullable=False)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    system_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    physical_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    difference_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    difference_value: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    adjustment_journal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    stock_opname: Mapped[StockOpnameTable] = relationship("StockOpnameTable", back_populates="lines")

    @property
    def is_over(self) -> bool:
        return self.difference_quantity > 0

    @property
    def is_short(self) -> bool:
        return self.difference_quantity < 0

    @property
    def is_match(self) -> bool:
        return self.difference_quantity == 0

    @property
    def absolute_difference(self) -> Decimal:
        return abs(self.difference_quantity)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "stock_opname_id": str(self.stock_opname_id),
            "product_id": str(self.product_id),
            "product_code": self.product_code,
            "product_name": self.product_name,
            "warehouse_id": str(self.warehouse_id),
            "system_quantity": float(self.system_quantity),
            "physical_quantity": float(self.physical_quantity),
            "difference_quantity": float(self.difference_quantity),
            "unit_cost": float(self.unit_cost),
            "difference_value": float(self.difference_value),
            "adjustment_journal_id": str(self.adjustment_journal_id) if self.adjustment_journal_id else None,
            "notes": self.notes,
            "is_over": self.is_over,
            "is_short": self.is_short,
            "is_match": self.is_match,
            "absolute_difference": float(self.absolute_difference),
        }


__all__ = ["StockOpnameLineTable"]
