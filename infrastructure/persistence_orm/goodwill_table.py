#!/usr/bin/env python3
"""
Module: goodwill_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model untuk mencatat goodwill dari kombinasi bisnis (PSAK 22 / IFRS 3).
               Menyimpan nilai awal goodwill, carrying amount, dan informasi
               terkait akuisisi. Juga melacak impairment test dan amortisasi
               (jika ada, meskipun goodwill tidak diamortisasi, tetapi bisa saja
               untuk PSAK lama). Mendukung multiple mata uang, entitas hukum,
               dan integrasi dengan modul fixed asset / intangible asset.
Dependencies:
- sqlalchemy, uuid, decimal, datetime
- base_model, LegalEntityMixin, TimestampMixin, SoftDeleteMixin, VersionMixin
Audit: Setiap perubahan goodwill dicatat di event store.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Numeric,
    String,
    Text,
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


class GoodwillTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    """Model untuk tabel goodwill."""

    __tablename__ = "goodwill"
    __table_args__ = (
        UniqueConstraint("goodwill_code", "legal_entity_id", name="uq_goodwill_code_legal_entity"),
        CheckConstraint(
            "goodwill_code IS NOT NULL AND goodwill_code != ''", name="ck_goodwill_code"
        ),
        CheckConstraint("goodwill_initial >= 0", name="ck_goodwill_initial_nonneg"),
        CheckConstraint("carrying_amount >= 0", name="ck_goodwill_carrying_nonneg"),
        CheckConstraint(
            "status IN ('active', 'fully_impaired', 'partially_impaired', 'disposed')",
            name="ck_goodwill_status",
        ),
        Index("idx_goodwill_code", "goodwill_code"),
        Index("idx_goodwill_legal_entity", "legal_entity_id"),
        Index("idx_goodwill_acquisition_date", "acquisition_date"),
        Index("idx_goodwill_status", "status"),
        Index("idx_goodwill_cg_unit", "cash_generating_unit"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Identifikasi
    goodwill_code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Data akuisisi
    acquisition_date: Mapped[date] = mapped_column(Date, nullable=False)
    acquiree_name: Mapped[str] = mapped_column(String(200), nullable=False)
    acquiree_tax_id: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Nilai akuisisi
    purchase_price: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    fair_value_identifiable_net_assets: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=0
    )
    goodwill_initial: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    carrying_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)

    # Currency
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")
    exchange_rate_at_acquisition: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), nullable=False, default=1
    )

    # Cash generating unit
    cash_generating_unit: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Allocation
    allocated_to_segment: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Referensi
    acquisition_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    last_impairment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_impairment_loss: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=True)

    # Audit
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================
    impairments: Mapped[list[GoodwillImpairmentTable]] = relationship(
        "GoodwillImpairmentTable",
        back_populates="goodwill",
        cascade="all, delete-orphan",
        order_by="GoodwillImpairmentTable.test_date.desc()",
    )

    # ========================================================================
    # PROPERTIES
    # ========================================================================
    @property
    def impairment_accumulated(self) -> Decimal:
        """Total accumulated impairment loss."""
        if not self.impairments:
            return Decimal(0)
        return sum(imp.impairment_loss for imp in self.impairments)

    @property
    def net_carrying_amount(self) -> Decimal:
        """Carrying amount after accumulated impairment."""
        return self.carrying_amount - self.impairment_accumulated

    @property
    def impairment_percentage(self) -> Decimal:
        """Percentage of impairment relative to initial goodwill."""
        if self.goodwill_initial == 0:
            return Decimal(0)
        return (self.impairment_accumulated / self.goodwill_initial) * 100

    @property
    def is_fully_impaired(self) -> bool:
        return self.net_carrying_amount <= 0 or self.status == "fully_impaired"

    @property
    def is_partially_impaired(self) -> bool:
        return self.impairment_accumulated > 0 and not self.is_fully_impaired

    # ========================================================================
    # METHODS
    # ========================================================================
    def record_impairment(self, impairment_loss: Decimal, test_date: date, recoverable_amount: Decimal) -> None:
        """Record an impairment loss (will create an impairment record via repository)."""
        if impairment_loss < 0:
            raise ValueError("Impairment loss cannot be negative")
        if impairment_loss > self.carrying_amount:
            impairment_loss = self.carrying_amount
        self.last_impairment_date = test_date
        self.last_impairment_loss = impairment_loss
        self.carrying_amount -= impairment_loss
        if self.carrying_amount <= 0:
            self.status = "fully_impaired"
        else:
            self.status = "partially_impaired"
        self.increment_version()

    def recover_impairment(self, recovery_amount: Decimal, reversal_date: date) -> None:
        """
        Reversal of impairment loss (if allowed by accounting standard).
        Note: Under IFRS, reversal of goodwill impairment is prohibited.
        This method is for limited cases (e.g., PSAK lama atau jika ada ketentuan khusus).
        """
        if recovery_amount <= 0:
            raise ValueError("Recovery amount must be positive")
        if self.carrying_amount + recovery_amount > self.goodwill_initial:
            raise ValueError("Reversal cannot exceed original goodwill")
        self.carrying_amount += recovery_amount
        if self.carrying_amount > 0:
            self.status = "partially_impaired" if self.impairment_accumulated > 0 else "active"
        self.increment_version()

    def dispose(self, disposal_date: date) -> None:
        """Mark goodwill as disposed (e.g., sale of CGU)."""
        self.status = "disposed"
        self.is_active = False
        self.increment_version()

    def approve(self, approved_by: uuid.UUID) -> None:
        """Approve goodwill recognition."""
        self.approved_by = approved_by
        self.approved_at = datetime.utcnow()
        self.increment_version()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "goodwill_code": self.goodwill_code,
            "name": self.name,
            "description": self.description,
            "acquisition_date": self.acquisition_date.isoformat(),
            "purchase_price": float(self.purchase_price),
            "fair_value_identifiable_net_assets": float(self.fair_value_identifiable_net_assets),
            "goodwill_initial": float(self.goodwill_initial),
            "carrying_amount": float(self.carrying_amount),
            "currency": self.currency,
            "status": self.status,
            "impairment_accumulated": float(self.impairment_accumulated),
            "net_carrying_amount": float(self.net_carrying_amount),
            "cash_generating_unit": self.cash_generating_unit,
            "legal_entity_id": str(self.legal_entity_id),
            "version": self.version,
        }


__all__ = ["GoodwillTable"]
