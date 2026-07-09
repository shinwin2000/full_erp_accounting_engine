#!/usr/bin/env python3
"""
Module: general_ledger_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: ORM model untuk tabel general ledger (read model).

Perbaikan presisi:
    - Mengubah float() menjadi str() pada nilai moneter (debit, credit)
      untuk menghindari kehilangan presisi dan memenuhi aturan MNY-003.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)


class GeneralLedgerEntry(Base, TimestampMixin, SoftDeleteMixin, VersionMixin):
    __tablename__ = "general_ledger"
    __table_args__ = (
        {"extend_existing": True},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    journal_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    journal_number: Mapped[str] = mapped_column(String, nullable=False)
    account_code: Mapped[str] = mapped_column(String, nullable=False)
    debit: Mapped[Decimal] = mapped_column(Numeric, default=Decimal(0))
    credit: Mapped[Decimal] = mapped_column(Numeric, default=Decimal(0))
    posting_date: Mapped[datetime] = mapped_column(nullable=False)
    fiscal_period: Mapped[str] = mapped_column(String, nullable=False)
    legal_entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    is_reversal: Mapped[bool] = mapped_column(Boolean, default=False)
    original_entry_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    @property
    def amount(self) -> Decimal:
        return self.debit if self.debit > 0 else self.credit

    @property
    def is_debit_entry(self) -> bool:
        return self.debit > 0

    @property
    def is_credit_entry(self) -> bool:
        return self.credit > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "journal_id": str(self.journal_id),
            "journal_number": self.journal_number,
            "account_code": self.account_code,
            "debit": str(self.debit),   # ganti float -> str untuk presisi
            "credit": str(self.credit), # ganti float -> str untuk presisi
            "posting_date": self.posting_date.isoformat(),
            "fiscal_period": self.fiscal_period,
            "legal_entity_id": str(self.legal_entity_id),
            "is_reversal": self.is_reversal,
            "original_entry_id": str(self.original_entry_id) if self.original_entry_id else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


__all__ = ["GeneralLedgerEntry"]