#!/usr/bin/env python3
"""
Module: inventory_stock_card_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Read model untuk kartu stok inventory.
"""

from __future__ import annotations
from uuid import UUID

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, Date, Index, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import Base, LegalEntityMixin, TimestampMixin


class InventoryStockCardTable(Base, TimestampMixin, LegalEntityMixin):
    __tablename__ = "inventory_stock_card"
    __table_args__ = (
        Index("idx_isc_item", "item_id"),
        Index("idx_isc_warehouse", "warehouse_id"),
        Index("idx_isc_date", "movement_date"),
        Index("idx_isc_legal_entity", "legal_entity_id"),
        Index("idx_isc_movement", "movement_id"),
        CheckConstraint("in_quantity >= 0", name="ck_isc_in_nonneg"),
        CheckConstraint("out_quantity >= 0", name="ck_isc_out_nonneg"),
        CheckConstraint("balance_quantity >= 0", name="ck_isc_balance_nonneg"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    movement_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    item_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    item_code: Mapped[str] = mapped_column(String(50), nullable=False)
    item_name: Mapped[str] = mapped_column(String(200), nullable=False)
    uom: Mapped[str] = mapped_column(String(10), nullable=False, default="PCS")
    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    warehouse_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    movement_date: Mapped[date] = mapped_column(Date, nullable=False)
    movement_type: Mapped[str] = mapped_column(String(20), nullable=False)
    reference_document_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reference_document_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    in_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=Decimal(0))
    out_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=Decimal(0))
    balance_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    in_value: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=Decimal(0))
    out_value: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=Decimal(0))
    balance_value: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    batch_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    @property
    def is_inbound(self) -> bool:
        return self.movement_type in ("IN", "TRANSFER_IN", "ADJUSTMENT_IN")

    @property
    def is_outbound(self) -> bool:
        return self.movement_type in ("OUT", "TRANSFER_OUT", "ADJUSTMENT_OUT")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "legal_entity_id": str(self.legal_entity_id),
            "movement_id": str(self.movement_id),
            "item_id": str(self.item_id),
            "item_code": self.item_code,
            "item_name": self.item_name,
            "uom": self.uom,
            "warehouse_id": str(self.warehouse_id) if self.warehouse_id else None,
            "warehouse_code": self.warehouse_code,
            "movement_date": self.movement_date.isoformat(),
            "movement_type": self.movement_type,
            "reference_document_type": self.reference_document_type,
            "reference_document_number": self.reference_document_number,
            "in_quantity": float(self.in_quantity),
            "out_quantity": float(self.out_quantity),
            "balance_quantity": float(self.balance_quantity),
            "unit_cost": float(self.unit_cost),
            "in_value": float(self.in_value),
            "out_value": float(self.out_value),
            "balance_value": float(self.balance_value),
            "batch_number": self.batch_number,
            "notes": self.notes,
            "created_by": str(self.created_by) if self.created_by else None,
        }


StockCardTable = InventoryStockCardTable
StockCardReadModel = InventoryStockCardTable

__all__ = ["InventoryStockCardTable", "StockCardReadModel", "StockCardTable"]