#!/usr/bin/env python3
"""
Module: ledger_entry_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel ledger_entry.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from infrastructure.persistence_orm.account_table import AccountTable
    from infrastructure.persistence_orm.journal_header_table import JournalHeaderTable
    from infrastructure.persistence_orm.journal_line_table import JournalLineTable


class LedgerEntryTable(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "ledger_entry"
    __table_args__ = (
        UniqueConstraint(
            "journal_id", "account_code", "line_number",
            name="uq_ledger_entry_journal_account_line"
        ),
        CheckConstraint("debit_amount >= 0", name="ck_ledger_entry_debit_nonneg"),
        CheckConstraint("credit_amount >= 0", name="ck_ledger_entry_credit_nonneg"),
        CheckConstraint("debit_amount > 0 OR credit_amount > 0", name="ck_ledger_entry_nonzero"),
        Index("idx_ledger_entry_account", "account_id"),
        Index("idx_ledger_entry_account_code", "account_code"),
        Index("idx_ledger_entry_journal", "journal_id"),
        Index("idx_ledger_entry_date", "posting_date"),
        Index("idx_ledger_entry_legal_entity", "legal_entity_id"),
        Index("idx_ledger_entry_cost_center", "cost_center"),
        Index("idx_ledger_entry_period", "fiscal_year", "period_month"),
        {"extend_existing": True},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    journal_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("journal_header.id"), nullable=False
    )
    account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("account.id"), nullable=False
    )
    account_code: Mapped[str] = mapped_column(String(20), nullable=False)
    line_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    debit_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    credit_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")
    posting_date: Mapped[date] = mapped_column(Date, nullable=False)
    cost_center: Mapped[str | None] = mapped_column(String(20), nullable=True)
    department: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reference_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)
    legal_entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    audit_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Relationships
    journal: Mapped[JournalHeaderTable] = relationship(
        "JournalHeaderTable", back_populates="ledger_entries"
    )
    account: Mapped[AccountTable] = relationship(
        "AccountTable", back_populates="ledger_entries"
    )

    @property
    def amount(self) -> Decimal:
        return self.debit_amount if self.debit_amount > 0 else self.credit_amount

    @property
    def is_debit(self) -> bool:
        return self.debit_amount > 0

    @property
    def is_credit(self) -> bool:
        return self.credit_amount > 0

    @property
    def posting_month(self) -> int:
        return self.period_month

    @property
    def posting_year(self) -> int:
        return self.fiscal_year

    @property
    def period_display(self) -> str:
        return f"{self.fiscal_year}-{self.period_month:02d}"

    @classmethod
    def from_journal_line(
        cls,
        journal_line: JournalLineTable,
        journal: JournalHeaderTable,
        account_id: uuid.UUID,
        legal_entity_id: uuid.UUID,
    ) -> LedgerEntryTable:
        return cls(
            id=uuid.uuid4(),
            journal_id=journal.id,
            account_id=account_id,
            account_code=journal_line.account_code,
            line_number=journal_line.line_number,
            debit_amount=journal_line.debit_amount,
            credit_amount=journal_line.credit_amount,
            currency=journal_line.currency,
            posting_date=journal.journal_date,
            cost_center=journal_line.cost_center,
            department=journal_line.department,
            reference_number=journal.reference_number,
            description=journal_line.description or journal.description,
            fiscal_year=journal.journal_date.year,
            period_month=journal.journal_date.month,
            legal_entity_id=legal_entity_id,
            created_by=journal.posted_by,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "journal_id": str(self.journal_id),
            "account_id": str(self.account_id),
            "account_code": self.account_code,
            "line_number": self.line_number,
            "debit_amount": float(self.debit_amount),
            "credit_amount": float(self.credit_amount),
            "currency": self.currency,
            "posting_date": self.posting_date.isoformat(),
            "cost_center": self.cost_center,
            "department": self.department,
            "reference_number": self.reference_number,
            "description": self.description,
            "fiscal_year": self.fiscal_year,
            "period_month": self.period_month,
            "legal_entity_id": str(self.legal_entity_id),
            "created_by": str(self.created_by) if self.created_by else None,
            "audit_metadata": self.audit_metadata,
        }


__all__ = ["LedgerEntryTable"]
