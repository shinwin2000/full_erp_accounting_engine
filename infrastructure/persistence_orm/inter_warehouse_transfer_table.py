#!/usr/bin/env python3
"""
Module: inter_warehouse_transfer_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel transfer antar gudang
(header + lines). Tabel ini baru dibuat karena sebelumnya tidak ada persistensi
sama sekali untuk fitur inter-warehouse transfer.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import (
    Base,
    LegalEntityMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)

if TYPE_CHECKING:
    pass


class InterWarehouseTransferTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    __tablename__ = "inter_warehouse_transfer"
    __table_args__ = (
        UniqueConstraint(
            "transfer_number", "legal_entity_id", name="uq_inter_warehouse_transfer_number_legal_entity"
        ),
        Index("idx_inter_warehouse_transfer_status", "status", "legal_entity_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transfer_number: Mapped[str] = mapped_column(String(50), nullable=False)
    source_warehouse_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("warehouse.id", ondelete="SET NULL"), nullable=True
    )
    source_warehouse_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    destination_warehouse_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("warehouse.id", ondelete="SET NULL"), nullable=True
    )
    destination_warehouse_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    transfer_date: Mapped[date] = mapped_column(Date, nullable=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=0)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    total_value: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    requested_at: Mapped[datetime | None] = mapped_column(nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(nullable=True)
    shipped_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    shipped_at: Mapped[datetime | None] = mapped_column(nullable=True)
    received_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    lines: Mapped[list[InterWarehouseTransferLineTable]] = relationship(
        "InterWarehouseTransferLineTable",
        back_populates="transfer",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class InterWarehouseTransferLineTable(Base, TimestampMixin):
    __tablename__ = "inter_warehouse_transfer_line"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transfer_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("inter_warehouse_transfer.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    item_sku: Mapped[str] = mapped_column(String(64), nullable=False)
    item_name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    total_value: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    batch_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    transfer: Mapped[InterWarehouseTransferTable] = relationship(
        "InterWarehouseTransferTable", back_populates="lines"
    )
