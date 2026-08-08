#!/usr/bin/env python3
"""
Module: account_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel account (Chart of Accounts).
               Tabel ini adalah master data inti COA yang dipakai oleh hampir semua
               modul akuntansi (Journal/GL, AP, AR, Inventory, Fixed Asset, Payroll,
               Budget, Financial Report). Mendukung relasi parent-child (tree),
               kontrol posting, kategori pelaporan, dan flag operasional lain yang
               dipakai backend (service_coa.py) maupun frontend (coa_page.py).

CATATAN SINKRONISASI (PENTING):
    Kolom di model ini HARUS selalu sinkron dengan:
      1. Migration  : backend/migrations/versions/0047_coa_extended_fields.py
      2. Service     : backend/application/service_layer/service_coa.py
      3. Router      : backend/adapters/primary_api/v1/fastapi_coa_router.py
      4. Frontend    : frontend/ui/pages/coa_page.py (field CREATE_FIELDS/EDIT_FIELDS)
    Kalau menambah/mengubah kolom di sini, keempat lapisan itu WAJIB diikutkan.

Dependencies:
- sqlalchemy.orm (Mapped, mapped_column, relationship)
- sqlalchemy.dialects.postgresql (UUID, NUMERIC)
- infrastructure.persistence_orm.base_model (Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin)
Audit: Setiap perubahan pada akun dicatat di audit trail (lihat service_coa.py._record_audit).
       Akun yang sudah memiliki transaksi tidak dapat dihapus (hanya dinonaktifkan/soft-delete).
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
    from infrastructure.persistence_orm.journal_line_table import JournalLineTable
    from infrastructure.persistence_orm.ledger_entry_table import LedgerEntryTable
    from infrastructure.persistence_orm.legal_entity_table import LegalEntityTable


# Nilai yang diperbolehkan untuk beberapa kolom ENUM-like (dijaga juga di
# level Pydantic schema pada fastapi_coa_router.py supaya validasi terjadi
# di edge sebelum menyentuh database).
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
    """
    Model untuk tabel account (Chart of Accounts) — master data inti ERP.
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
    # HIERARCHY (parent_account_id sudah menggunakan schema public)
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

    # Tax & reporting
    tax_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    cashflow_type: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Lock (mis. dikunci setelah periode closing / audit) — independen dari
    # status "locked"/"suspended" supaya bisa dikombinasikan (mis. akun aktif
    # tapi dikunci sementara untuk investigasi).
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

    # ========================================================================
    # OVERRIDE legal_entity_id dari LegalEntityMixin agar menggunakan schema public
    # ========================================================================
    legal_entity_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("legal_entity.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================

    # Self-referential hierarchy
    parent: Mapped[AccountTable | None] = relationship(
        "AccountTable", remote_side="AccountTable.id", back_populates="children"
    )
    children: Mapped[list[AccountTable]] = relationship(
        "AccountTable", back_populates="parent", cascade="all, delete-orphan"
    )

    # Ledger entries
    ledger_entries: Mapped[list[LedgerEntryTable]] = relationship(
        "LedgerEntryTable", back_populates="account"
    )

    # Journal lines – menggunakan string reference dan foreign_keys eksplisit
    journal_lines: Mapped[list[JournalLineTable]] = relationship(
        "JournalLineTable",
        back_populates="account",
        primaryjoin="and_(AccountTable.account_code == JournalLineTable.account_code, "
                    "AccountTable.legal_entity_id == JournalLineTable.legal_entity_id)",
        foreign_keys="[JournalLineTable.account_code, JournalLineTable.legal_entity_id]",
        viewonly=True,
    )

    # ========================================================================
    # Relasi ke LegalEntityTable – karena LegalEntityMixin tidak memberikan relasi
    # setelah kita override legal_entity_id, kita tambahkan secara eksplisit.
    # ========================================================================
    legal_entity: Mapped[LegalEntityTable] = relationship(
        "LegalEntityTable",
        back_populates="accounts",
        foreign_keys=[legal_entity_id],
    )

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
        """Akun boleh dipakai sebagai baris jurnal jika tidak header, tidak
        dikunci, mengizinkan posting, dan berstatus aktif."""
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


__all__ = ["AccountTable", "ACCOUNT_TYPES", "NORMAL_BALANCES", "ACCOUNT_STATUSES", "CASHFLOW_TYPES"]
