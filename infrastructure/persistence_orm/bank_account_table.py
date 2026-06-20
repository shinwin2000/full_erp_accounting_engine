#!/usr/bin/env python3
"""
Module: bank_account_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model SQLAlchemy untuk tabel bank_account.
"""

from __future__ import annotations
from uuid import UUID

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
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


class BankAccountTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    __tablename__ = "bank_account"
    __table_args__ = (
        UniqueConstraint(
            "account_number", "legal_entity_id", name="uq_bank_account_number_legal_entity"
        ),
        CheckConstraint("account_number IS NOT NULL", name="ck_bank_account_number"),
        CheckConstraint("bank_name IS NOT NULL", name="ck_bank_account_bank_name"),
        CheckConstraint("account_type IN ('checking', 'savings', 'deposit')", name="ck_bank_account_type"),
        CheckConstraint("status IN ('active', 'inactive', 'closed')", name="ck_bank_account_status"),
        CheckConstraint("current_balance >= 0", name="ck_bank_account_balance_nonneg"),
        Index("idx_bank_account_number", "account_number"),
        Index("idx_bank_account_legal_entity", "legal_entity_id"),
        Index("idx_bank_account_status", "status"),
        Index("idx_bank_account_gl_account", "gl_account_id"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_number: Mapped[str] = mapped_column(String(50), nullable=False)
    bank_name: Mapped[str] = mapped_column(String(100), nullable=False)
    bank_code: Mapped[str] = mapped_column(String(10), nullable=False)
    account_name: Mapped[str] = mapped_column(String(200), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")
    account_type: Mapped[str] = mapped_column(String(20), nullable=False, default="checking")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    current_balance: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    available_balance: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    opening_balance_date: Mapped[date] = mapped_column(Date, nullable=False)
    gl_account_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    last_reconciliation_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    transactions: Mapped[list[BankTransactionTable]] = relationship(
        "BankTransactionTable", back_populates="bank_account", cascade="all, delete-orphan"
    )
    reconciliations: Mapped[list[BankReconciliationTable]] = relationship(
        "BankReconciliationTable", back_populates="bank_account"
    )

    @property
    def is_checking(self) -> bool:
        return self.account_type == "checking"

    @property
    def is_savings(self) -> bool:
        return self.account_type == "savings"

    @property
    def is_closed(self) -> bool:
        return self.status == "closed"

    @property
    def is_active_account(self) -> bool:
        return self.status == "active" and self.is_active

    def activate(self) -> None:
        self.is_active = True
        self.status = "active"
        self.increment_version()

    def deactivate(self) -> None:
        self.is_active = False
        self.status = "inactive"
        self.increment_version()

    def close(self, closed_by: uuid.UUID) -> None:
        self.status = "closed"
        self.is_active = False
        self.increment_version()

    def update_balance(self, new_balance: Decimal, new_available_balance: Decimal | None = None) -> None:
        self.current_balance = new_balance
        self.available_balance = new_available_balance if new_available_balance is not None else new_balance
        self.increment_version()

    def can_delete(self) -> bool:
        return len(self.transactions) == 0

    def record_reconciliation(self, reconciliation_date: date) -> None:
        self.last_reconciliation_date = reconciliation_date
        self.increment_version()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "account_number": self.account_number,
            "bank_name": self.bank_name,
            "bank_code": self.bank_code,
            "account_name": self.account_name,
            "currency_code": self.currency_code,
            "account_type": self.account_type,
            "status": self.status,
            "is_active": self.is_active,
            "is_default": self.is_default,
            "current_balance": float(self.current_balance),
            "available_balance": float(self.available_balance),
            "opening_balance": float(self.opening_balance),
            "opening_balance_date": self.opening_balance_date.isoformat(),
            "gl_account_id": str(self.gl_account_id) if self.gl_account_id else None,
            "last_reconciliation_date": self.last_reconciliation_date.isoformat() if self.last_reconciliation_date else None,
            "legal_entity_id": str(self.legal_entity_id),
            "version": self.version,
        }


__all__ = ["BankAccountTable"]