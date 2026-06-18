#!/usr/bin/env python3
"""
Module: stock_opname_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel stock_opname,
               yang mencatat hasil stock opname (physical count) dari item inventaris.
               Model ini mendukung pencatatan perbedaan stok, approval,
               dan adjustment journal.
Dependencies:
- sqlalchemy.orm (Mapped, mapped_column, relationship)
- sqlalchemy.dialects.postgresql (UUID, JSONB)
- infrastructure.persistence_orm.base_model (Base, TimestampMixin, SoftDeleteMixin, VersionMixin)
Audit: Setiap stock opname dan adjustment dicatat di event store.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)

# ============================================================================
# STOCK OPNAME HEADER MODEL
# ============================================================================


class StockOpnameTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin):
    """
    Model untuk tabel stock_opname (header).
    Menyimpan data stock opname per periode/lokasi.
    """

    __tablename__ = "stock_opname"
    __table_args__ = (
        UniqueConstraint("opname_number", "legal_entity_id", name="uq_stock_opname_number_entity"),
        CheckConstraint(
            "opname_number IS NOT NULL AND opname_number != ''", name="ck_stock_opname_number"
        ),
        CheckConstraint(
            "status IN ('draft', 'in_progress', 'completed', 'adjusted', 'cancelled')",
            name="ck_stock_opname_status",
        ),
        Index("idx_stock_opname_number", "opname_number"),
        Index("idx_stock_opname_legal_entity", "legal_entity_id"),
        Index("idx_stock_opname_date", "opname_date"),
        Index("idx_stock_opname_status", "status"),
        Index("idx_stock_opname_location", "location_code"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    legal_entity_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, index=True
    )
    opname_number: Mapped[str] = mapped_column(String(50), nullable=False)
    opname_date: Mapped[date] = mapped_column(Date, nullable=False)
    location_code: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    total_expected_value: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    total_counted_value: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    total_variance_value: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    adjustment_journal_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    completed_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    extra_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Relationships
    lines: Mapped[list[StockOpnameLineTable]] = relationship(
        "StockOpnameLineTable",
        back_populates="header",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # Properties
    @property
    def is_draft(self) -> bool:
        return self.status == "draft"

    @property
    def is_in_progress(self) -> bool:
        return self.status == "in_progress"

    @property
    def is_completed(self) -> bool:
        return self.status == "completed"

    @property
    def is_adjusted(self) -> bool:
        return self.status == "adjusted"

    @property
    def is_cancelled(self) -> bool:
        return self.status == "cancelled"

    # Methods
    def mark_in_progress(self, user_id: uuid.UUID) -> None:
        if self.status != "draft":
            raise ValueError(f"Cannot start opname in status {self.status}")
        self.status = "in_progress"
        self.increment_version()

    def complete(self, user_id: uuid.UUID) -> None:
        if self.status != "in_progress":
            raise ValueError(f"Cannot complete opname in status {self.status}")
        self.status = "completed"
        self.completed_by = user_id
        self.completed_at = datetime.utcnow()
        self.increment_version()

    def approve(self, user_id: uuid.UUID) -> None:
        if self.status != "completed":
            raise ValueError(f"Cannot approve opname in status {self.status}")
        self.status = "adjusted"  # after approval, ready for adjustment
        self.approved_by = user_id
        self.approved_at = datetime.utcnow()
        self.increment_version()

    def cancel(self, user_id: uuid.UUID, reason: str) -> None:
        if self.status in ("adjusted", "cancelled"):
            raise ValueError(f"Cannot cancel opname in status {self.status}")
        self.status = "cancelled"
        if self.extra_metadata:
            self.extra_metadata["cancellation_reason"] = reason
        self.increment_version()

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "legal_entity_id": str(self.legal_entity_id),
            "opname_number": self.opname_number,
            "opname_date": self.opname_date.isoformat(),
            "location_code": self.location_code,
            "warehouse_id": str(self.warehouse_id) if self.warehouse_id else None,
            "description": self.description,
            "status": self.status,
            "total_expected_value": str(self.total_expected_value),
            "total_counted_value": str(self.total_counted_value),
            "total_variance_value": str(self.total_variance_value),
            "adjustment_journal_id": str(self.adjustment_journal_id)
            if self.adjustment_journal_id
            else None,
            "completed_by": str(self.completed_by) if self.completed_by else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "approved_by": str(self.approved_by) if self.approved_by else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "created_by": str(self.created_by) if self.created_by else None,
            "extra_metadata": self.extra_metadata,
            "version": self.version,
        }


# ============================================================================
# STOCK OPNAME LINE MODEL
# ============================================================================


class StockOpnameLineTable(Base, TimestampMixin):
    """
    Model untuk tabel stock_opname_lines (detail per item).
    """

    __tablename__ = "stock_opname_lines"
    __table_args__ = (
        UniqueConstraint("stock_opname_id", "item_id", name="uq_stock_opname_line_item"),
        Index("idx_stock_opname_line_header", "stock_opname_id"),
        Index("idx_stock_opname_line_item", "item_id"),
        Index("idx_stock_opname_line_variance", "variance_quantity"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    stock_opname_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("stock_opname.id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    item_code: Mapped[str] = mapped_column(String(50), nullable=False)
    item_name: Mapped[str] = mapped_column(String(200), nullable=False)
    uom: Mapped[str] = mapped_column(String(10), nullable=False, default="PCS")
    expected_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=0)
    counted_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=0)
    variance_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=0)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    variance_value: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    counted_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    counted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    header: Mapped[StockOpnameTable] = relationship("StockOpnameTable", back_populates="lines")

    # Methods
    def set_count(self, quantity: Decimal, user_id: uuid.UUID) -> None:
        if quantity < 0:
            raise ValueError("Counted quantity cannot be negative")
        self.counted_quantity = quantity
        self.variance_quantity = self.counted_quantity - self.expected_quantity
        self.variance_value = self.variance_quantity * self.unit_cost
        self.counted_by = user_id
        self.counted_at = datetime.utcnow()
        self.increment_version()

    def verify(self, user_id: uuid.UUID) -> None:
        self.verified_by = user_id
        self.verified_at = datetime.utcnow()
        self.increment_version()

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "stock_opname_id": str(self.stock_opname_id),
            "item_id": str(self.item_id),
            "item_code": self.item_code,
            "item_name": self.item_name,
            "uom": self.uom,
            "expected_quantity": str(self.expected_quantity),
            "counted_quantity": str(self.counted_quantity),
            "variance_quantity": str(self.variance_quantity),
            "unit_cost": str(self.unit_cost),
            "variance_value": str(self.variance_value),
            "notes": self.notes,
            "counted_by": str(self.counted_by) if self.counted_by else None,
            "counted_at": self.counted_at.isoformat() if self.counted_at else None,
            "verified_by": str(self.verified_by) if self.verified_by else None,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
        }


__all__ = ["Base", "StockOpnameLineTable", "StockOpnameTable"]
