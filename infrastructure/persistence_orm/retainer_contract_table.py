#!/usr/bin/env python3
"""
Module: retainer_contract_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel retainer_contract.
               Tabel ini menyimpan data kontrak retainer (kontrak jangka panjang
               dengan pembayaran periodik) untuk proyek atau layanan berkelanjutan.
               Mencatat nilai retainer, periode billing, sisa dana, dan status.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
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

if TYPE_CHECKING:
    from infrastructure.persistence_orm.customer_table import CustomerTable
    from infrastructure.persistence_orm.project_table import ProjectTable


class RetainerContractTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    __tablename__ = "retainer_contract"
    __table_args__ = (
        UniqueConstraint(
            "contract_number", "legal_entity_id", name="uq_retainer_contract_number_legal_entity"
        ),
        CheckConstraint(
            "contract_number IS NOT NULL AND contract_number != ''",
            name="ck_retainer_contract_number",
        ),
        CheckConstraint("customer_id IS NOT NULL", name="ck_retainer_customer"),
        CheckConstraint("contract_value >= 0", name="ck_retainer_value_nonneg"),
        CheckConstraint("remaining_amount >= 0", name="ck_retainer_remaining_nonneg"),
        CheckConstraint("billed_amount >= 0", name="ck_retainer_billed_nonneg"),
        CheckConstraint("used_amount >= 0", name="ck_retainer_used_nonneg"),
        CheckConstraint(
            "billing_frequency IN ('monthly', 'quarterly', 'semi_annual', 'annual', 'one_time')",
            name="ck_retainer_frequency",
        ),
        CheckConstraint(
            "status IN ('draft', 'active', 'suspended', 'completed', 'cancelled', 'expired')",
            name="ck_retainer_status",
        ),
        Index("idx_retainer_contract_number", "contract_number"),
        Index("idx_retainer_customer", "customer_id"),
        Index("idx_retainer_status", "status"),
        Index("idx_retainer_start_date", "start_date"),
        Index("idx_retainer_end_date", "end_date"),
        Index("idx_retainer_next_billing_date", "next_billing_date"),
        Index("idx_retainer_project", "project_id"),
        Index("idx_retainer_legal_entity", "legal_entity_id")
    )

    # Contract identification
    contract_number: Mapped[str] = mapped_column(String(50), nullable=False)
    contract_name: Mapped[str] = mapped_column(String(200), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer.id"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id"), nullable=True
    )

    # Contract values
    contract_value: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    remaining_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    billed_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    used_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")

    # Dates
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_billing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_billing_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Billing
    billing_frequency: Mapped[str] = mapped_column(String(20), nullable=False, default="monthly")
    billing_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    auto_billing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Service description
    service_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    terms_and_conditions: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Limits
    max_hours_per_month: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    hourly_rate: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")

    # Approval
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Notes
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Audit
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================

    customer: Mapped[CustomerTable] = relationship("CustomerTable", foreign_keys=[customer_id])
    project: Mapped[ProjectTable | None] = relationship("ProjectTable", foreign_keys=[project_id])

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def available_amount(self) -> Decimal:
        """Amount still available for billing (remaining - used)."""
        return max(Decimal(0), self.remaining_amount - self.used_amount)

    @property
    def utilization_percentage(self) -> float:
        """Percentage of retainer used."""
        if self.contract_value == 0:
            return 0.0
        return float((self.used_amount / self.contract_value) * 100)

    @property
    def is_active_contract(self) -> bool:
        return self.status == "active"

    @property
    def is_expired(self) -> bool:
        if self.end_date:
            return date.today() > self.end_date
        return False

    @property
    def needs_billing(self) -> bool:
        """Check if billing is due."""
        if not self.is_active_contract:
            return False
        if self.available_amount <= 0:
            return False
        if self.next_billing_date and date.today() >= self.next_billing_date:
            return True
        return False

    # ========================================================================
    # METHODS
    # ========================================================================

    def activate(self) -> None:
        if self.status != "draft":
            raise ValueError(f"Cannot activate contract with status {self.status}")
        self.status = "active"
        self.next_billing_date = self.start_date
        self.increment_version()

    def suspend(self) -> None:
        if self.status != "active":
            raise ValueError(f"Cannot suspend contract with status {self.status}")
        self.status = "suspended"
        self.increment_version()

    def complete(self) -> None:
        if self.status not in ("active", "suspended"):
            raise ValueError(f"Cannot complete contract with status {self.status}")
        self.status = "completed"
        self.increment_version()

    def cancel(self) -> None:
        if self.status in ("completed", "cancelled", "expired"):
            raise ValueError(f"Cannot cancel contract with status {self.status}")
        self.status = "cancelled"
        self.increment_version()

    def record_billing(self, amount: Decimal, billing_date: date) -> None:
        """Record a billing transaction."""
        if amount <= 0:
            raise ValueError("Billing amount must be positive")
        if amount > self.available_amount:
            raise ValueError("Billing amount exceeds available retainer")

        self.billed_amount += amount
        self.remaining_amount -= amount
        self.last_billing_date = billing_date

        # Calculate next billing date based on frequency
        from datetime import timedelta

        if self.billing_frequency == "monthly":
            self.next_billing_date = billing_date + timedelta(days=30)
        elif self.billing_frequency == "quarterly":
            self.next_billing_date = billing_date + timedelta(days=90)
        elif self.billing_frequency == "semi_annual":
            self.next_billing_date = billing_date + timedelta(days=180)
        elif self.billing_frequency == "annual":
            self.next_billing_date = billing_date + timedelta(days=365)
        else:
            self.next_billing_date = None

        self.increment_version()

    def record_usage(self, amount: Decimal, description: str | None = None) -> None:
        """Record usage of retainer (service rendered)."""
        if amount <= 0:
            raise ValueError("Usage amount must be positive")
        if amount > self.remaining_amount:
            raise ValueError("Usage amount exceeds remaining retainer")

        self.used_amount += amount
        self.remaining_amount -= amount

        if self.remaining_amount <= 0:
            self.status = "completed"

        self.increment_version()

    def add_funds(self, amount: Decimal) -> None:
        """Add funds to retainer contract (top-up)."""
        if amount <= 0:
            raise ValueError("Amount must be positive")
        if self.status not in ("active", "suspended"):
            raise ValueError(f"Cannot add funds to contract with status {self.status}")

        self.contract_value += amount
        self.remaining_amount += amount
        self.increment_version()

    def extend_end_date(self, new_end_date: date) -> None:
        """Extend contract end date."""
        if self.status not in ("active", "suspended"):
            raise ValueError(f"Cannot extend contract with status {self.status}")
        self.end_date = new_end_date
        self.increment_version()


__all__ = ["RetainerContractTable"]
