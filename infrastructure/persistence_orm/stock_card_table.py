#!/usr/bin/env python3
"""
Module: stock_card_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel stock_card,
               yang mencatat mutasi stok per item per gudang (kartu stok).
               Tabel ini digunakan untuk read model dan analisis persediaan.
               Setiap entri mewakili satu baris dalam kartu stok yang dihasilkan
               dari event stock movement (inbound/outbound).
Dependencies:
- sqlalchemy.orm (Mapped, mapped_column, relationship)
- sqlalchemy.dialects.postgresql (UUID, NUMERIC)
- infrastructure.persistence_orm.base_model (Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin)
Audit: Data kartu stok bersifat immutable dan dihasilkan dari event store.
"""

from __future__ import annotations
from uuid import UUID

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import (
    Base,
    LegalEntityMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)


class StockCardTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    """
    Model untuk tabel stock_card.
    Menyimpan history mutasi stok per item per gudang.
    """

    __tablename__ = "stock_card"
    __table_args__ = (
        UniqueConstraint(
            "movement_id", name="uq_stock_card_movement_id"
        ),  # prevent duplicate entries
        CheckConstraint("in_quantity >= 0", name="ck_stock_card_in_nonneg"),
        CheckConstraint("out_quantity >= 0", name="ck_stock_card_out_nonneg"),
        CheckConstraint(
            "balance_quantity >= 0", name="ck_stock_card_balance_nonneg"
        ),
        CheckConstraint(
            "movement_type IN ('inbound', 'outbound')",
            name="ck_stock_card_movement_type",
        ),
        Index("idx_stock_card_legal_entity", "legal_entity_id"),
        Index("idx_stock_card_item", "item_id"),
        Index("idx_stock_card_warehouse", "warehouse_id"),
        Index("idx_stock_card_date", "movement_date"),
        Index("idx_stock_card_reference", "reference_document_type", "reference_document_number"),
        Index("idx_stock_card_movement_id", "movement_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Reference to the original movement (for audit)
    movement_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, unique=True)

    # Item identification
    item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, index=True
    )
    item_code: Mapped[str] = mapped_column(String(50), nullable=False)
    item_name: Mapped[str] = mapped_column(String(200), nullable=False)
    uom: Mapped[str] = mapped_column(String(10), nullable=False, default="PCS")

    # Warehouse
    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    warehouse_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    warehouse_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Movement details
    movement_date: Mapped[date] = mapped_column(Date, nullable=False)
    movement_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'inbound' or 'outbound'

    # Reference document
    reference_document_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reference_document_number: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Quantity and value
    in_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=Decimal(0))
    out_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=Decimal(0))
    balance_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)

    unit_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    in_value: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=Decimal(0))
    out_value: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=Decimal(0))
    balance_value: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)

    # Batch / serial number (optional)
    batch_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Description
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Audit (created_by is enough, but we also keep reference to user who created the movement)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    # Relationships (optional, for ORM convenience)
    # item: Mapped["InventoryItemTable"] = relationship("InventoryItemTable", foreign_keys=[item_id])
    # warehouse: Mapped["WarehouseTable"] = relationship("WarehouseTable", foreign_keys=[warehouse_id])

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def is_inbound(self) -> bool:
        return self.movement_type == "inbound"

    @property
    def is_outbound(self) -> bool:
        return self.movement_type == "outbound"

    @property
    def net_quantity_change(self) -> Decimal:
        return self.in_quantity - self.out_quantity

    @property
    def net_value_change(self) -> Decimal:
        return self.in_value - self.out_value

    # ========================================================================
    # METHODS
    # ========================================================================

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
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
            "warehouse_name": self.warehouse_name,
            "movement_date": self.movement_date.isoformat(),
            "movement_type": self.movement_type,
            "reference_document_type": self.reference_document_type,
            "reference_document_number": self.reference_document_number,
            "in_quantity": str(self.in_quantity),
            "out_quantity": str(self.out_quantity),
            "balance_quantity": str(self.balance_quantity),
            "unit_cost": str(self.unit_cost),
            "in_value": str(self.in_value),
            "out_value": str(self.out_value),
            "balance_value": str(self.balance_value),
            "batch_number": self.batch_number,
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "description": self.description,
            "created_by": str(self.created_by) if self.created_by else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "version": self.version,
        }

    @classmethod
    def from_movement(
        cls,
        movement_id: uuid.UUID,
        legal_entity_id: uuid.UUID,
        item_id: uuid.UUID,
        item_code: str,
        item_name: str,
        uom: str,
        movement_date: date,
        movement_type: str,
        quantity: Decimal,
        unit_cost: Decimal,
        total_value: Decimal,
        balance_quantity: Decimal,
        balance_value: Decimal,
        reference_document_type: str | None = None,
        reference_document_number: str | None = None,
        warehouse_id: uuid.UUID | None = None,
        warehouse_code: str | None = None,
        warehouse_name: str | None = None,
        batch_number: str | None = None,
        expiry_date: date | None = None,
        description: str | None = None,
        created_by: uuid.UUID | None = None,
    ) -> StockCardTable:
        """
        Factory method to create a stock card entry from a movement.
        Calculates in/out quantities based on movement type.
        """
        now = datetime.utcnow()
        if movement_type == "inbound":
            in_qty = quantity
            out_qty = Decimal(0)
            in_val = total_value
            out_val = Decimal(0)
        else:  # outbound
            in_qty = Decimal(0)
            out_qty = quantity
            in_val = Decimal(0)
            out_val = total_value

        return cls(
            id=uuid.uuid4(),
            legal_entity_id=legal_entity_id,
            movement_id=movement_id,
            item_id=item_id,
            item_code=item_code,
            item_name=item_name,
            uom=uom,
            warehouse_id=warehouse_id,
            warehouse_code=warehouse_code,
            warehouse_name=warehouse_name,
            movement_date=movement_date,
            movement_type=movement_type,
            reference_document_type=reference_document_type,
            reference_document_number=reference_document_number,
            in_quantity=in_qty,
            out_quantity=out_qty,
            balance_quantity=balance_quantity,
            unit_cost=unit_cost,
            in_value=in_val,
            out_value=out_val,
            balance_value=balance_value,
            batch_number=batch_number,
            expiry_date=expiry_date,
            description=description,
            created_by=created_by,
            created_at=now,
            updated_at=now,
            version=1,
            deleted_at=None,
        )


__all__ = ["StockCardTable"]