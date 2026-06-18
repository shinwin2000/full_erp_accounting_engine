#!/usr/bin/env python3
"""
Module: tax_transaction_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel tax_transaction.
               Tabel ini menyimpan data transaksi pajak, termasuk perhitungan
               PPN, PPh 21, PPh 23, PPh 25, PPh 26, PPh 4(2), PPh Badan,
               serta faktur pajak keluaran/masukan, bukti potong, dan NTPN.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import (
    Base,
    LegalEntityMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)


class TaxTransactionTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    __tablename__ = "tax_transaction"
    __table_args__ = (
        UniqueConstraint(
            "transaction_number", "legal_entity_id", name="uq_tax_transaction_number_legal_entity"
        ),
        CheckConstraint("transaction_number IS NOT NULL", name="ck_tax_tx_number"),
        CheckConstraint(
            "tax_type IN ('ppn', 'pph21', 'pph22', 'pph23', 'pph25', 'pph26', 'pph4_2', 'pph_badan', 'other')",
            name="ck_tax_tx_type",
        ),
        CheckConstraint(
            "tax_period_type IN ('monthly', 'quarterly', 'annual')", name="ck_tax_tx_period_type"
        ),
        CheckConstraint("tax_period_month BETWEEN 1 AND 13", name="ck_tax_tx_period_month"),
        CheckConstraint("tax_period_year >= 2000", name="ck_tax_tx_period_year"),
        CheckConstraint("taxable_amount >= 0", name="ck_tax_tx_taxable_nonneg"),
        CheckConstraint("tax_amount >= 0", name="ck_tax_tx_amount_nonneg"),
        CheckConstraint(
            "status IN ('calculated', 'reported', 'paid', 'adjusted', 'cancelled')",
            name="ck_tax_tx_status",
        ),
        Index("idx_tax_transaction_number", "transaction_number"),
        Index("idx_tax_tx_type_period", "tax_type", "tax_period_year", "tax_period_month"),
        Index("idx_tax_tx_status", "status"),
        Index("idx_tax_tx_reference", "reference_id", "reference_type"),
        Index("idx_tax_tx_legal_entity", "legal_entity_id")
    )

    # Transaction identification
    transaction_number: Mapped[str] = mapped_column(String(50), nullable=False)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Tax type and period
    tax_type: Mapped[str] = mapped_column(String(20), nullable=False)
    tax_period_type: Mapped[str] = mapped_column(String(10), nullable=False, default="monthly")
    tax_period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    tax_period_month: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # 1-12, 13 for adjustment

    # Base amounts
    taxable_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    tax_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=0
    )  # in percent
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")

    # Withholding/crediting
    is_withholding: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    counterparty_tax_id: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # NPWP lawan transaksi
    counterparty_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # NTPN (payment reference)
    ntpn: Mapped[str | None] = mapped_column(String(16), nullable=True)
    payment_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Reference to source document
    reference_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # invoice, journal, payroll, etc.
    reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Filing information (SPT)
    spt_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    filing_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="calculated")

    # Additional data (e.g., breakdown per invoice)
    extra_metadata: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True
    )  # renamed from metadata

    # Audit
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def is_reported(self) -> bool:
        return self.status in ("reported", "paid", "adjusted")

    @property
    def is_paid(self) -> bool:
        return self.status == "paid" and self.ntpn is not None

    @property
    def effective_tax_rate(self) -> Decimal:
        if self.taxable_amount == 0:
            return Decimal(0)
        return (self.tax_amount / self.taxable_amount) * Decimal(100)

    @property
    def period_display(self) -> str:
        if self.tax_period_type == "monthly":
            return f"{self.tax_period_year}-{self.tax_period_month:02d}"
        elif self.tax_period_type == "quarterly":
            quarter = (self.tax_period_month - 1) // 3 + 1
            return f"Q{quarter} {self.tax_period_year}"
        else:
            return str(self.tax_period_year)

    # ========================================================================
    # METHODS
    # ========================================================================

    def calculate_tax(self) -> None:
        """Calculate tax amount based on taxable_amount and tax_rate."""
        self.tax_amount = self.taxable_amount * (self.tax_rate / Decimal(100))
        self.increment_version()

    def mark_reported(self, spt_number: str, filing_date: date) -> None:
        if self.status not in ("calculated", "adjusted"):
            raise ValueError(f"Cannot mark as reported with status {self.status}")
        self.status = "reported"
        self.spt_number = spt_number
        self.filing_date = filing_date
        self.increment_version()

    def mark_paid(self, ntpn: str, payment_date: date) -> None:
        if self.status not in ("reported", "adjusted"):
            raise ValueError(f"Cannot mark as paid with status {self.status}")
        self.status = "paid"
        self.ntpn = ntpn
        self.payment_date = payment_date
        self.increment_version()

    def adjust(self, adjustment_amount: Decimal, reason: str) -> None:
        if self.status == "paid":
            raise ValueError("Cannot adjust tax transaction that is already paid")
        self.tax_amount = adjustment_amount
        self.status = "adjusted"
        if self.extra_metadata is None:
            self.extra_metadata = {}
        self.extra_metadata["adjustment_reason"] = reason
        self.extra_metadata["adjusted_at"] = datetime.now(UTC).isoformat()
        self.increment_version()

    def cancel(self) -> None:
        if self.status == "paid":
            raise ValueError("Cannot cancel tax transaction that is already paid")
        self.status = "cancelled"
        self.increment_version()

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "transaction_number": self.transaction_number,
            "transaction_date": self.transaction_date.isoformat(),
            "tax_type": self.tax_type,
            "tax_period_type": self.tax_period_type,
            "tax_period_year": self.tax_period_year,
            "tax_period_month": self.tax_period_month,
            "taxable_amount": float(self.taxable_amount),
            "tax_rate": float(self.tax_rate),
            "tax_amount": float(self.tax_amount),
            "currency": self.currency,
            "is_withholding": self.is_withholding,
            "counterparty_tax_id": self.counterparty_tax_id,
            "counterparty_name": self.counterparty_name,
            "ntpn": self.ntpn,
            "payment_date": self.payment_date.isoformat() if self.payment_date else None,
            "reference_type": self.reference_type,
            "reference_id": str(self.reference_id) if self.reference_id else None,
            "spt_number": self.spt_number,
            "filing_date": self.filing_date.isoformat() if self.filing_date else None,
            "status": self.status,
            "extra_metadata": self.extra_metadata,
            "legal_entity_id": str(self.legal_entity_id),
            "created_by": str(self.created_by) if self.created_by else None,
            "version": self.version,
        }


__all__ = ["TaxTransactionTable"]
