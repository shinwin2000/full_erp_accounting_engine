#!/usr/bin/env python3
"""
Module: inventory_price_history_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model SQLAlchemy untuk tabel inventory_price_history — mencatat
               setiap perubahan harga (cost/selling) pada inventory_item.
               Tabel ini bersifat append-only (audit trail harga).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import Base, LegalEntityMixin

if TYPE_CHECKING:
    from infrastructure.persistence_orm.inventory_item_table import InventoryItemTable


class InventoryPriceHistoryTable(Base, LegalEntityMixin):
    """Log riwayat perubahan harga. Immutable (append-only)."""

    __is_audit_log__ = True

    __tablename__ = "inventory_price_history"
    __table_args__ = (
        CheckConstraint(
            "price_type IN ('cost_price', 'standard_cost', 'average_cost', 'last_cost', "
            "'selling_price', 'minimum_selling_price', 'wholesale_price', 'retail_price')",
            name="ck_inventory_price_history_type",
        ),
        Index("idx_inventory_price_history_item", "item_id"),
        Index("idx_inventory_price_history_effective", "effective_date"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_item.id", ondelete="CASCADE"), nullable=False
    )
    price_type: Mapped[str] = mapped_column(String(30), nullable=False)
    old_price: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    new_price: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    effective_date: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    item: Mapped[InventoryItemTable] = relationship("InventoryItemTable", back_populates="price_history")

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "item_id": str(self.item_id),
            "price_type": self.price_type,
            "old_price": str(self.old_price),
            "new_price": str(self.new_price),
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "reason": self.reason,
            "changed_by": str(self.changed_by) if self.changed_by else None,
        }


__all__ = ["InventoryPriceHistoryTable"]
