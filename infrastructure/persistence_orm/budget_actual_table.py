#!/usr/bin/env python3
"""
Module: budget_actual_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model untuk mencatat realisasi (actual) dari transaksi
               yang terkait dengan budget. Digunakan untuk perbandingan
               budget vs actual dan variance analysis.
Dependencies:
- sqlalchemy, uuid, decimal, datetime
- base_model, LegalEntityMixin, TimestampMixin
Audit: Setiap actual dicatat dan tidak dapat diubah setelah diposting.

Perbaikan presisi:
    - Mengubah float() menjadi str() pada nilai moneter (amount) di to_dict()
      untuk menjaga presisi dan memenuhi aturan MNY-003.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import Base, LegalEntityMixin, TimestampMixin

if TYPE_CHECKING:
    from infrastructure.persistence_orm.budget_table import BudgetTable


class BudgetActualTable(Base, TimestampMixin, LegalEntityMixin):
    """
    Tabel realisasi budget (actual) dari transaksi aktual.
    """

    # ``Base`` mendeklarasikan ``__tablename__`` sebagai ``Callable[[Base], str]``
    # (kemungkinan karena metaclass/factory untuk auto-generate nama tabel).
    # Subclass menimpanya dengan string literal — assignment yang secara tipe
    # tidak kompatibel, tapi sah secara runtime untuk SQLAlchemy declarative.
    __tablename__ = "budget_actual"  # type: ignore[assignment]
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_budget_actual_nonneg"),
        CheckConstraint(
            "source_type IN ('journal', 'invoice', 'payment', 'purchase_order', 'sales_order', 'manual')",
            name="ck_budget_actual_source",
        ),
        Index("idx_budget_actual_budget", "budget_id"),
        Index("idx_budget_actual_date", "transaction_date"),
        Index("idx_budget_actual_source", "source_type", "source_id"),
        Index("idx_budget_actual_legal_entity", "legal_entity_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Referensi ke budget
    budget_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("budget.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Data transaksi
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")

    # Source transaksi
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    source_number: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Deskripsi
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Dimensi opsional
    cost_center: Mapped[str | None] = mapped_column(String(20), nullable=True)
    project_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    # Status (posted, reversed, etc.)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="posted")
    reversed_by_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Audit
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================
    budget: Mapped[BudgetTable] = relationship(
        "BudgetTable", back_populates="actuals"
    )

    # ========================================================================
    # PROPERTIES
    # ========================================================================
    @property
    def is_reversed(self) -> bool:
        return self.status == "reversed"

    @property
    def effective_amount(self) -> Decimal:
        """If reversed, return negative amount for variance calculation."""
        if self.is_reversed:
            return -self.amount
        return self.amount

    # ========================================================================
    # METHODS
    # ========================================================================
    def reverse(self, reversed_by: uuid.UUID, reason: str | None = None) -> None:
        """Reverse this actual entry."""
        if self.status == "reversed":
            raise ValueError("Actual already reversed")
        self.status = "reversed"
        self.reversed_by_id = reversed_by
        self.reversed_at = datetime.utcnow()
        if reason:
            self.description = f"{self.description or ''} [REVERSED: {reason}]"

    def to_dict(self) -> dict[str, Any]:  # type: ignore[override]
        return {
            "id": str(self.id),
            "budget_id": str(self.budget_id),
            "transaction_date": self.transaction_date.isoformat(),
            "amount": str(self.amount),  # ganti float -> str untuk presisi
            "currency": self.currency,
            "source_type": self.source_type,
            "source_id": str(self.source_id),
            "source_number": self.source_number,
            "description": self.description,
            "cost_center": self.cost_center,
            "project_id": str(self.project_id) if self.project_id else None,
            "status": self.status,
            "is_reversed": self.is_reversed,
            "legal_entity_id": str(self.legal_entity_id),
        }


__all__ = ["BudgetActualTable"]
