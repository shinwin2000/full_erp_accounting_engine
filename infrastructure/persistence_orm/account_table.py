#!/usr/bin/env python3
"""
Module: account_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel account (Chart of Accounts).

FIX v3:
    Hapus DUA relationship yang pakai string reference ke class yang
    hanya di-import di TYPE_CHECKING:
      1. journal_lines -> "JournalLineTable"
      2. legal_entity  -> "LegalEntityTable"
    SQLAlchemy gagal resolve string reference saat configure_mappers()
    kalau class target tidak ada di registry, sehingga SEMUA query
    AccountTable (termasuk Laba Rugi) crash dan mengembalikan [].
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

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
    from infrastructure.persistence_orm.ledger_entry_table import LedgerEntryTable


# Nilai yang diperbolehkan untuk beberapa kolom ENUM-like
ACCOUNT_TYPES = (
    "Asset",
    "Liability",
    "Equity",
    "Revenue",
    "Expense",
    "ContraAsset",
    "ContraLiability",
    "ContraEquity",
)
NORMAL_BALANCES = ("debit", "credit")
ACCOUNT_STATUSES = ("active", "inactive", "suspended", "locked", "archived")
CASHFLOW_TYPES = ("operating", "investing", "financing")


class AccountTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    """Model untuk tabel account (Chart of Accounts) — master data inti ERP."""

    __tablename__ = "account"  # type: ignore[assignment]
    __table_args__ = (
        UniqueConstraint("account_code", "legal_entity_id", name="uq_account_code_legal_entity"),
        CheckConstraint("account_code IS NOT NULL AND account_code != ''", name="ck_account_code"),
        CheckConstraint("account_name IS NOT NULL AND account_name != ''", name="ck_account_name"),
        CheckConstraint(
            "account_type IN ('Asset', 'Liability', 'Equity', 'Revenue', 'Expense', 'ContraAsset', 'ContraLiability', 'ContraEquity')",
            name="ck_account_type",
        ),
        CheckConstraint("normal_balance IN ('debit', 'credit')", name="ck_normal_balance"),
        CheckConstraint("status IN ('active', 'inactive', 'suspended', 'locked', 'archived')", name="ck_account_status"),
        CheckConstraint("level BETWEEN 0 AND 10", name="ck_account_level"),
        CheckConstraint(
            "cashflow_type IS NULL OR cashflow_type IN ('operating', 'investing', 'financing')",
            name="ck_account_cashflow_type",
        ),
        Index("idx_account_account_code", "account_code"),
        Index("idx_account_type", "account_type"),
        Index("idx_account_parent", "parent_account_id"),
        Index("idx_account_legal_entity", "legal_entity_id"),
        Index("idx_account_status", "status"),
        Index("idx_account_group", "account_group"),
        Index("idx_account_sort_order", "sort_order"),
        {"extend_existing": True},
    )

    # ========================================================================
    # IDENTIFICATION
    # ========================================================================
    account_code: Mapped[str] = mapped_column(String(20), nullable=False)
    account_name: Mapped[str] = mapped_column(String(200), nullable=False)
    account_name_en: Mapped[str | None] = mapped_column(String(200), nullable=True)
    account_type: Mapped[str] = mapped_column(String(20), nullable=False)
    account_group: Mapped[str | None] = mapped_column(String(100), nullable=True)
    normal_balance: Mapped[str] = mapped_column(String(6), nullable=False)

    # ========================================================================
    # HIERARCHY
    # ========================================================================
    parent_account_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("account.id"), nullable=True
    )
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")

    # ========================================================================
    # POSTING / OPERATIONAL CONTROL
    # ========================================================================
    is_header: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allow_posting: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_bank_account: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_cash_account: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_intercompany: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    budget_control: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reconciliation_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    tax_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    cashflow_type: Mapped[str | None] = mapped_column(String(20), nullable=True)

    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    lock_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    opening_balance_debit: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=0
    )
    opening_balance_credit: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=0
    )

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    legal_entity_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("legal_entity.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================
    # Hanya self-referential & ledger_entries yang aman (targetnya class
    # yang bisa di-resolve tanpa circular import).

    parent: Mapped[AccountTable | None] = relationship(
        "AccountTable", remote_side="AccountTable.id", back_populates="children"
    )
    children: Mapped[list[AccountTable]] = relationship(
        "AccountTable", back_populates="parent", cascade="all, delete-orphan"
    )

    ledger_entries: Mapped[list[LedgerEntryTable]] = relationship(
        "LedgerEntryTable", back_populates="account"
    )

    # CATATAN FIX v3:
    #  - journal_lines  -> DIHAPUS (string ref ke JournalLineTable, tidak pernah dipakai)
    #  - legal_entity   -> DIHAPUS (string ref ke LegalEntityTable, tidak pernah dipakai)
    # Akses ke relasi itu harus lewat query eksplisit di repository.

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def opening_balance(self) -> Decimal:
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
        if self.parent and self.parent.account_code:
            return f"{self.parent.account_code}.{self.account_code}"
        return self.account_code

    @property
    def can_post(self) -> bool:
        return (
            self.allow_posting
            and not self.is_header
            and not self.is_locked
            and self.status == "active"
        )

    # ========================================================================
    # METHODS
    # ========================================================================

    def activate(self) -> None:
        self.is_active = True
        self.status = "active"
        self.increment_version()

    def deactivate(self) -> None:
        self.is_active = False
        self.status = "inactive"
        self.increment_version()

    def lock(self, reason: str | None = None) -> None:
        self.is_locked = True
        self.lock_reason = reason
        self.increment_version()

    def unlock(self) -> None:
        self.is_locked = False
        self.lock_reason = None
        self.increment_version()

    def can_delete(self) -> bool:
        return len(self.ledger_entries) == 0 and len(self.children) == 0

    def set_opening_balance(self, debit: Decimal, credit: Decimal) -> None:
        self.opening_balance_debit = debit
        self.opening_balance_credit = credit
        self.increment_version()


__all__ = ["ACCOUNT_STATUSES", "ACCOUNT_TYPES", "CASHFLOW_TYPES", "NORMAL_BALANCES", "AccountTable"]
