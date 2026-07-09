#!/usr/bin/env python3
"""
Module: umkm_transaction_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model untuk transaksi UMKM (simplified accounting).

Perbaikan presisi:
    - Mengubah float() menjadi str() pada nilai moneter (amount) di to_dict()
      untuk menjaga presisi dan memenuhi aturan MNY-003.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, DateTime, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import Base


class UMKMTransactionTable(Base):
    __tablename__ = "umkm_transaction"
    __table_args__ = (
        CheckConstraint(
            "transaction_type IN ('revenue', 'expense', 'asset', 'liability')",
            name="ck_umkm_tx_type",
        ),
        CheckConstraint(
            "status IN ('draft', 'posted', 'cancelled')",
            name="ck_umkm_tx_status",
        ),
        Index("idx_umkm_tx_profile", "profile_id"),
        Index("idx_umkm_tx_date", "transaction_date"),
        Index("idx_umkm_tx_type", "transaction_type"),
        Index("idx_umkm_tx_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    profile_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    transaction_number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    reference_number: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # --- Kolom Tambahan (Ditambahkan agar tidak di-drop oleh Alembic) ---
    reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reference_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    umkm_profile_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    legal_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # -------------------------------------------------------------------

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, onupdate=datetime.utcnow)

    @property
    def is_revenue(self) -> bool:
        return self.transaction_type == "revenue"

    @property
    def is_expense(self) -> bool:
        return self.transaction_type == "expense"

    @property
    def is_posted(self) -> bool:
        return self.status == "posted"

    def post(self) -> None:
        if self.status != "draft":
            raise ValueError(f"Cannot post transaction with status {self.status}")
        self.status = "posted"

    def cancel(self) -> None:
        if self.status == "cancelled":
            raise ValueError("Transaction already cancelled")
        self.status = "cancelled"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "profile_id": str(self.profile_id),
            "transaction_number": self.transaction_number,
            "transaction_date": self.transaction_date.isoformat(),
            "transaction_type": self.transaction_type,
            "amount": str(self.amount),  # ganti float -> str untuk presisi
            "description": self.description,
            "category": self.category,
            "status": self.status,
            "reference_number": self.reference_number,
            "created_at": self.created_at.isoformat(),
            "created_by": str(self.created_by) if self.created_by else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


__all__ = ["UMKMTransactionTable"]