#!/usr/bin/env python3
"""
Module: journal_line_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel journal_line.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import (
    Base,
    LegalEntityMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)

if TYPE_CHECKING:
    from infrastructure.persistence_orm.account_table import AccountTable
    from infrastructure.persistence_orm.journal_header_table import JournalHeaderTable


class JournalLineTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    __tablename__ = "journal_line"
    __table_args__ = (
        CheckConstraint("debit_amount >= 0", name="ck_journal_line_debit_nonneg"),
        CheckConstraint("credit_amount >= 0", name="ck_journal_line_credit_nonneg"),
        CheckConstraint("debit_amount > 0 OR credit_amount > 0", name="ck_journal_line_nonzero"),
        CheckConstraint("line_number >= 1", name="ck_journal_line_number"),
        Index("idx_journal_line_journal", "journal_id"),
        Index("idx_journal_line_account", "account_code"),
        Index("idx_journal_line_legal_entity", "legal_entity_id"),
        Index("idx_journal_line_cost_center", "cost_center")
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    journal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("journal_header.id"), nullable=False)
    account_code: Mapped[str] = mapped_column(String(20), nullable=False)
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    debit_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    credit_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")
    cost_center: Mapped[str | None] = mapped_column(String(20), nullable=True)
    department: Mapped[str | None] = mapped_column(String(20), nullable=True)
    account_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    audit_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    journal: Mapped[JournalHeaderTable] = relationship("JournalHeaderTable", back_populates="lines")
    account: Mapped[AccountTable | None] = relationship(
        "AccountTable",
        foreign_keys=[account_code],
        primaryjoin="JournalLineTable.account_code == AccountTable.account_code",
        viewonly=True,
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

    def validate(self) -> bool:
        return (self.debit_amount > 0) != (self.credit_amount > 0)

    def get_absolute_amount(self) -> Decimal:
        return self.amount

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "journal_id": str(self.journal_id),
            "account_code": self.account_code,
            "line_number": self.line_number,
            "description": self.description,
            "debit_amount": float(self.debit_amount),
            "credit_amount": float(self.credit_amount),
            "currency": self.currency,
            "cost_center": self.cost_center,
            "department": self.department,
            "account_name": self.account_name,
            "audit_metadata": self.audit_metadata,
            "legal_entity_id": str(self.legal_entity_id),
        }


__all__ = ["JournalLineTable"]
