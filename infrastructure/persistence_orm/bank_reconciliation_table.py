#!/usr/bin/env python3
"""
Module: bank_reconciliation_table.py
Layer: Infrastructure / Persistence ORM
Responsibility: SQLAlchemy ORM model for bank reconciliation records.

Perbaikan presisi:
    - Mengubah float() menjadi str() pada nilai moneter (statement_ending_balance,
      system_ending_balance, difference, amount) di to_dict() untuk menjaga
      presisi dan memenuhi aturan MNY-003.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import Base, LegalEntityMixin, TimestampMixin

if TYPE_CHECKING:
    # Mencegah circular import / NameError saat runtime
    from infrastructure.persistence_orm.bank_account_table import BankAccountTable


class BankReconciliationTable(Base, TimestampMixin, LegalEntityMixin):
    __tablename__ = "bank_reconciliations"
    __table_args__ = (
        CheckConstraint("statement_ending_balance >= 0", name="ck_bank_recon_statement_balance"),
        CheckConstraint("system_ending_balance >= 0", name="ck_bank_recon_system_balance"),
        CheckConstraint(
            "status IN ('pending', 'in_progress', 'reconciled', 'closed')", name="ck_bank_recon_status"
        ),
        Index("idx_bank_recon_legal_entity", "legal_entity_id"),
        Index("idx_bank_recon_bank_account", "bank_account_id"),
        Index("idx_bank_recon_statement_date", "statement_date"),
        Index("idx_bank_recon_status", "status"),
        Index("idx_bank_recon_period", "period_start", "period_end"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    legal_entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)

    # [FIX]: Penambahan ForeignKey eksplisit ke tabel bank_account
    bank_account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("bank_account.id"),
        nullable=False
    )

    statement_date: Mapped[date] = mapped_column(Date, nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    statement_ending_balance: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    system_ending_balance: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    difference: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    reconciled_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    # [FIX]: Relationships menggunakan String Literal dan Fully Qualified Path
    items: Mapped[list[BankReconciliationItemTable]] = relationship(
        "BankReconciliationItemTable",
        back_populates="reconciliation",
        cascade="all, delete-orphan"
    )
    bank_account: Mapped[BankAccountTable] = relationship(
        "infrastructure.persistence_orm.bank_account_table.BankAccountTable",
        back_populates="reconciliations"
    )

    @property
    def is_reconciled(self) -> bool:
        return self.status == "reconciled"

    @property
    def is_in_progress(self) -> bool:
        return self.status == "in_progress"

    @property
    def is_closed(self) -> bool:
        return self.status == "closed"

    def start_reconciliation(self) -> None:
        if self.status != "pending":
            raise ValueError(f"Cannot start reconciliation with status {self.status}")
        self.status = "in_progress"

    def complete(self, reconciled_by: uuid.UUID) -> None:
        if self.status != "in_progress":
            raise ValueError(f"Cannot complete reconciliation with status {self.status}")
        self.status = "reconciled"
        self.reconciled_by = reconciled_by
        self.reconciled_at = datetime.utcnow()

    def close(self) -> None:
        if self.status != "reconciled":
            raise ValueError(f"Cannot close reconciliation with status {self.status}")
        self.status = "closed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "legal_entity_id": str(self.legal_entity_id),
            "bank_account_id": str(self.bank_account_id),
            "statement_date": self.statement_date.isoformat(),
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "statement_ending_balance": str(self.statement_ending_balance),  # ganti float -> str
            "system_ending_balance": str(self.system_ending_balance),        # ganti float -> str
            "difference": str(self.difference),                              # ganti float -> str
            "status": self.status,
            "reconciled_by": str(self.reconciled_by) if self.reconciled_by else None,
            "reconciled_at": self.reconciled_at.isoformat() if self.reconciled_at else None,
            "notes": self.notes,
            "created_by": str(self.created_by) if self.created_by else None,
        }


class BankReconciliationItemTable(Base):
    __tablename__ = "bank_reconciliation_items"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_bank_recon_item_amount"),
        CheckConstraint("item_type IN ('bank_statement', 'system_transaction', 'adjustment')", name="ck_bank_recon_item_type"),
        CheckConstraint("is_matched IN (0, 1)", name="ck_bank_recon_item_matched"),
        Index("idx_bank_recon_item_reconciliation", "reconciliation_id"),
        Index("idx_bank_recon_item_transaction", "transaction_id"),
        Index("idx_bank_recon_item_type", "item_type"),
        Index("idx_bank_recon_item_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reconciliation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("bank_reconciliations.id", ondelete="CASCADE"), nullable=False
    )
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str | None] = mapped_column(String(200), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    is_matched: Mapped[int] = mapped_column(nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="unmatched")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # [FIX]: Relationships menggunakan String Literal
    reconciliation: Mapped[BankReconciliationTable] = relationship(
        "BankReconciliationTable",
        back_populates="items"
    )

    def match(self) -> None:
        self.is_matched = 1
        self.status = "matched"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "reconciliation_id": str(self.reconciliation_id),
            "transaction_id": str(self.transaction_id) if self.transaction_id else None,
            "transaction_date": self.transaction_date.isoformat(),
            "description": self.description,
            "amount": str(self.amount),          # ganti float -> str untuk presisi
            "item_type": self.item_type,
            "source": self.source,
            "is_matched": self.is_matched,
            "status": self.status,
            "notes": self.notes,
        }


BankReconciliationReadModel = BankReconciliationTable

__all__ = [
    "BankReconciliationItemTable",
    "BankReconciliationReadModel",
    "BankReconciliationTable",
]