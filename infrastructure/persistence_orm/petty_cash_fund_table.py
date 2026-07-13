#!/usr/bin/env python3
"""
Module: petty_cash_fund_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel petty_cash_fund.

Perbaikan presisi:
    - Mengubah float() menjadi str() pada nilai moneter (current_balance, initial_amount,
      reimbursement_threshold) di to_dict() untuk menjaga presisi dan memenuhi aturan MNY-003.
    - Persentase (used_percentage) tetap menggunakan float karena bukan nilai moneter.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, Index, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import (
    Base,
    LegalEntityMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)


class PettyCashFundTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    __tablename__ = "petty_cash_fund"
    __table_args__ = (
        UniqueConstraint("fund_name", "legal_entity_id", name="uq_petty_cash_name_legal_entity"),
        CheckConstraint("fund_name IS NOT NULL", name="ck_petty_cash_name"),
        CheckConstraint("currency_code IS NOT NULL", name="ck_petty_cash_currency"),
        CheckConstraint("initial_amount >= 0", name="ck_petty_cash_initial_nonneg"),
        CheckConstraint("current_balance >= 0", name="ck_petty_cash_balance_nonneg"),
        CheckConstraint("status IN ('active', 'closed')", name="ck_petty_cash_status"),
        Index("idx_petty_cash_legal_entity", "legal_entity_id"),
        Index("idx_petty_cash_custodian", "custodian_id"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fund_name: Mapped[str] = mapped_column(String(100), nullable=False)
    legal_entity_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")
    current_balance: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    initial_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    custodian_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gl_account_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reimbursement_threshold: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=1000000)
    fund_location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    @property
    def is_active_fund(self) -> bool:
        return self.status == "active"

    @property
    def remaining_balance(self) -> Decimal:
        return self.current_balance

    @property
    def used_percentage(self) -> float:
        """Persentase dana yang telah digunakan (non-moneter)."""
        if self.initial_amount == 0:
            return 0.0
        used = self.initial_amount - self.current_balance
        return float((used / self.initial_amount) * 100)

    def update_balance(self, amount: Decimal) -> None:
        self.current_balance += amount
        if self.current_balance < 0:
            self.current_balance = 0
        self.increment_version()

    def close_fund(self) -> None:
        self.status = "closed"
        self.increment_version()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "fund_name": self.fund_name,
            "legal_entity_id": str(self.legal_entity_id),
            "currency_code": self.currency_code,
            "current_balance": str(self.current_balance),           # ganti float -> str
            "initial_amount": str(self.initial_amount),             # ganti float -> str
            "custodian_id": str(self.custodian_id),
            "gl_account_id": str(self.gl_account_id),
            "reimbursement_threshold": str(self.reimbursement_threshold),  # ganti float -> str
            "fund_location": self.fund_location,
            "status": self.status,
            "remaining_balance": str(self.remaining_balance),      # ganti float -> str
            "used_percentage": self.used_percentage,                # persentase, tetap float
        }


__all__ = ["PettyCashFundTable"]
