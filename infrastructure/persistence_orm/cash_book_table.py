#!/usr/bin/env python3
"""
Module: cash_book_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel cash_book.
               Tabel ini menyimpan buku kas (cash book) per legal entity dan mata uang,
               termasuk saldo awal, saldo saat ini, dan referensi ke akun GL.
Dependencies:
- sqlalchemy.orm (Mapped, mapped_column)
- infrastructure.persistence_orm.base_model
Audit: Setiap transaksi kas dicatat di event store.

Perbaikan presisi:
    - Mengubah float() menjadi str() pada nilai moneter (current_balance, opening_balance)
      untuk menghindari kehilangan presisi dan memenuhi aturan MNY-003.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, DateTime, Index, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import (
    Base,
    LegalEntityMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)


class CashBookTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    __tablename__ = "cash_book"
    __table_args__ = (
        UniqueConstraint("legal_entity_id", "currency_code", name="uq_cash_book_legal_entity_currency"),
        CheckConstraint("currency_code IS NOT NULL", name="ck_cash_book_currency"),
        CheckConstraint("current_balance >= 0", name="ck_cash_book_balance_nonneg"),
        CheckConstraint("opening_balance >= 0", name="ck_cash_book_opening_nonneg"),
        Index("idx_cash_book_legal_entity", "legal_entity_id"),
        Index("idx_cash_book_currency", "currency_code"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    legal_entity_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")
    current_balance: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    opening_balance_date: Mapped[date] = mapped_column(Date, nullable=False)
    gl_cash_account_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    gl_bank_account_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    def update_balance(self, new_balance: Decimal) -> None:
        self.current_balance = new_balance
        self.last_updated = datetime.utcnow()
        self.increment_version()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "legal_entity_id": str(self.legal_entity_id),
            "currency_code": self.currency_code,
            "current_balance": str(self.current_balance),   # ganti float -> str
            "opening_balance": str(self.opening_balance),   # ganti float -> str
            "opening_balance_date": self.opening_balance_date.isoformat(),
            "gl_cash_account_id": str(self.gl_cash_account_id) if self.gl_cash_account_id else None,
            "gl_bank_account_id": str(self.gl_bank_account_id) if self.gl_bank_account_id else None,
            "last_updated": self.last_updated.isoformat(),
            "created_by": str(self.created_by) if self.created_by else None,
        }


__all__ = ["CashBookTable"]