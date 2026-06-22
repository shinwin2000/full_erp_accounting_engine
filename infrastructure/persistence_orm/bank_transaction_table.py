#!/usr/bin/env python3
"""
Module: bank_transaction_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel bank_transaction.
               Tabel ini menyimpan data transaksi bank (setoran, penarikan, transfer,
               biaya bank, bunga). Setiap transaksi terhubung ke satu rekening bank.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
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


class BankTransactionTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    """
    Model untuk tabel bank_transaction.
    """

    __tablename__ = "bank_transaction"
    __table_args__ = (
        UniqueConstraint(
            "transaction_number", "legal_entity_id", name="uq_bank_transaction_number_legal_entity"
        ),
        CheckConstraint("transaction_number IS NOT NULL", name="ck_bank_tx_number"),
        CheckConstraint(
            "transaction_type IN ('deposit', 'withdrawal', 'transfer_in', 'transfer_out', 'bank_charge', 'interest')",
            name="ck_bank_tx_type",
        ),
        CheckConstraint("amount > 0", name="ck_bank_tx_amount_positive"),
        CheckConstraint(
            "status IN ('pending', 'posted', 'reconciled', 'cancelled')", name="ck_bank_tx_status"
        ),
        Index("idx_bank_tx_account", "bank_account_id"),
        Index("idx_bank_tx_date", "transaction_date"),
        Index("idx_bank_tx_type", "transaction_type"),
        Index("idx_bank_tx_status", "status"),
        Index("idx_bank_tx_reference", "reference_number"),
        Index("idx_bank_tx_reconciliation", "reconciliation_id"),
    )

    # Primary key
    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Transaction identification
    transaction_number: Mapped[str] = mapped_column(String(50), nullable=False)

    # Foreign key
    bank_account_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bank_account.id"), nullable=False
    )

    # Transaction details
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")

    # Description and reference
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    reference_number: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Counterparty information
    counterparty_account: Mapped[str | None] = mapped_column(String(50), nullable=True)
    counterparty_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Linking to journal
    journal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Status and reconciliation
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    is_reconciled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reconciliation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Audit
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # ========================================================================
    # RELATIONSHIPS (string referensi)
    # ========================================================================

    bank_account: Mapped[BankAccountTable] = relationship(
        "BankAccountTable", back_populates="transactions"
    )

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def is_deposit(self) -> bool:
        return self.transaction_type == "deposit"

    @property
    def is_withdrawal(self) -> bool:
        return self.transaction_type == "withdrawal"

    @property
    def is_transfer_in(self) -> bool:
        return self.transaction_type == "transfer_in"

    @property
    def is_transfer_out(self) -> bool:
        return self.transaction_type == "transfer_out"

    @property
    def is_bank_charge(self) -> bool:
        return self.transaction_type == "bank_charge"

    @property
    def is_interest(self) -> bool:
        return self.transaction_type == "interest"

    @property
    def is_pending(self) -> bool:
        return self.status == "pending"

    @property
    def is_posted(self) -> bool:
        return self.status == "posted"

    @property
    def is_reconciled(self) -> bool:
        return self.status == "reconciled"

    @property
    def is_cancelled(self) -> bool:
        return self.status == "cancelled"

    # ========================================================================
    # METHODS
    # ========================================================================

    def post(self, journal_id: uuid.UUID, posted_by: uuid.UUID) -> None:
        """Post transaction to general ledger."""
        if self.status != "pending":
            raise ValueError(f"Cannot post transaction with status {self.status}")
        self.status = "posted"
        self.journal_id = journal_id
        self.increment_version()

    def reconcile(self, reconciliation_id: uuid.UUID, reconciled_by: uuid.UUID) -> None:
        """Mark transaction as reconciled."""
        if self.status not in ("posted", "pending"):
            raise ValueError(f"Cannot reconcile transaction with status {self.status}")
        self.status = "reconciled"
        self.is_reconciled = True
        self.reconciliation_id = reconciliation_id
        self.increment_version()

    def cancel(self, cancelled_by: uuid.UUID) -> None:
        """Cancel transaction."""
        if self.status in ("reconciled", "cancelled"):
            raise ValueError(f"Cannot cancel transaction with status {self.status}")
        self.status = "cancelled"
        self.increment_version()


__all__ = ["BankTransactionTable"]
