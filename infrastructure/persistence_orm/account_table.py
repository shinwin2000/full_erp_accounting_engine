#!/usr/bin/env python3
"""
Module: account_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel account (Chart of Accounts).
               Tabel ini menyimpan data akun dalam COA, termasuk kode akun, nama,
               tipe akun, saldo normal, level hierarki, dan status. Mendukung
               relasi parent-child untuk hierarki akun dan hubungan dengan ledger entries.
Dependencies:
- sqlalchemy.orm (Mapped, mapped_column, relationship)
- sqlalchemy.dialects.postgresql (UUID, NUMERIC)
- infrastructure.persistence_orm.base_model (Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin)
Audit: Setiap perubahan pada akun dicatat di event store.
       Akun yang sudah memiliki transaksi tidak dapat dihapus (hanya dinonaktifkan).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
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

# ============================================================================
# MODEL
# ============================================================================


class AccountTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    """
    Model untuk tabel account (Chart of Accounts).
    """

    __tablename__ = "account"
    __table_args__ = (
        UniqueConstraint("account_code", "legal_entity_id", name="uq_account_code_legal_entity"),
        CheckConstraint("account_code IS NOT NULL AND account_code != ''", name="ck_account_code"),
        CheckConstraint("account_name IS NOT NULL AND account_name != ''", name="ck_account_name"),
        CheckConstraint(
            "account_type IN ('Asset', 'Liability', 'Equity', 'Revenue', 'Expense', 'ContraAsset', 'ContraLiability', 'ContraEquity')",
            name="ck_account_type",
        ),
        CheckConstraint("normal_balance IN ('debit', 'credit')", name="ck_normal_balance"),
        CheckConstraint("status IN ('active', 'inactive', 'suspended')", name="ck_account_status"),
        CheckConstraint("level BETWEEN 1 AND 10", name="ck_account_level"),
        Index("idx_account_account_code", "account_code"),
        Index("idx_account_type", "account_type"),
        Index("idx_account_parent", "parent_account_id"),
        Index("idx_account_legal_entity", "legal_entity_id"),
        Index("idx_account_status", "status")
    )

    # Account identification
    account_code: Mapped[str] = mapped_column(String(20), nullable=False)
    account_name: Mapped[str] = mapped_column(String(200), nullable=False)
    account_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # Asset, Liability, Equity, Revenue, Expense, ContraAsset, etc.
    normal_balance: Mapped[str] = mapped_column(String(6), nullable=False)  # debit or credit

    # Hierarchy
    parent_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account.id"), nullable=True
    )
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Description and details
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")

    # Flags
    is_bank_account: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_cash_account: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_intercompany: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_header: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )  # Header account (cannot post)

    # Opening balance (for new fiscal year)
    opening_balance_debit: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=0
    )
    opening_balance_credit: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=0
    )

    # Status
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Audit
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # ========================================================================
    # RELATIONSHIPS (semua menggunakan string referensi)
    # ========================================================================

    # Self-referential hierarchy
    legal_entity: Mapped[LegalEntityTable | None] = relationship(
        "LegalEntityTable", back_populates="accounts", foreign_keys="[AccountTable.legal_entity_id]"
    )
    parent: Mapped[AccountTable | None] = relationship(
        "AccountTable", remote_side=[id], back_populates="children"
    )
    children: Mapped[list[AccountTable]] = relationship(
        "AccountTable", back_populates="parent", cascade="all, delete-orphan"
    )

    # Ledger entries
    ledger_entries: Mapped[list[LedgerEntryTable]] = relationship(
        "LedgerEntryTable", back_populates="account"
    )

    # Journal lines
    journal_lines: Mapped[list[JournalLineTable]] = relationship(
        "JournalLineTable", back_populates="account"
    )

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def opening_balance(self) -> Decimal:
        """
        Get opening balance (debit minus credit) based on normal balance.
        For display, not for calculation.
        """
        if self.normal_balance == "debit":
            return self.opening_balance_debit - self.opening_balance_credit
        else:
            return self.opening_balance_credit - self.opening_balance_debit

    @property
    def is_asset(self) -> bool:
        return self.account_type in ("Asset", "ContraAsset")

    @property
    def is_liability(self) -> bool:
        return self.account_type in ("Liability", "ContraLiability")

    @property
    def is_equity(self) -> bool:
        return self.account_type in ("Equity", "ContraEquity")

    @property
    def is_revenue(self) -> bool:
        return self.account_type == "Revenue"

    @property
    def is_expense(self) -> bool:
        return self.account_type == "Expense"

    @property
    def full_account_code(self) -> str:
        """Return hierarchical account code if parent exists."""
        if self.parent and self.parent.account_code:
            return f"{self.parent.account_code}.{self.account_code}"
        return self.account_code

    # ========================================================================
    # METHODS
    # ========================================================================

    def activate(self) -> None:
        """Activate this account."""
        self.is_active = True
        self.status = "active"
        self.increment_version()

    def deactivate(self) -> None:
        """Deactivate this account (cannot be used in new transactions)."""
        self.is_active = False
        self.status = "inactive"
        self.increment_version()

    def can_delete(self) -> bool:
        """
        Check if account can be deleted (no ledger entries).
        """
        return len(self.ledger_entries) == 0

    def set_opening_balance(self, debit: Decimal, credit: Decimal) -> None:
        """
        Set opening balance for new fiscal year.
        """
        self.opening_balance_debit = debit
        self.opening_balance_credit = credit
        self.increment_version()


__all__ = ["AccountTable"]
