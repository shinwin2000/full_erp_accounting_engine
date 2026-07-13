#!/usr/bin/env python3
"""
Module: budget_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model untuk menyimpan anggaran (budget) per akun per periode.
               Mendukung multiple version, status (draft/approved/frozen),
               dan integrasi dengan COA, cost center, project, dan legal entity.
Dependencies:
- sqlalchemy, uuid, decimal, datetime
- base_model, LegalEntityMixin, TimestampMixin, SoftDeleteMixin, VersionMixin
Audit: Perubahan budget dicatat di event store.

Perbaikan presisi:
    - Mengubah float() menjadi str() pada nilai moneter (amount, total_actual, variance)
      di to_dict() untuk menjaga presisi dan memenuhi aturan MNY-003.
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


class BudgetTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    """
    Model untuk tabel budget (anggaran).
    """

    __tablename__ = "budget"
    __table_args__ = (
        UniqueConstraint(
            "budget_code", "legal_entity_id", name="uq_budget_code_legal_entity"
        ),
        CheckConstraint(
            "budget_code IS NOT NULL AND budget_code != ''", name="ck_budget_code"
        ),
        CheckConstraint("amount >= 0", name="ck_budget_amount_nonneg"),
        CheckConstraint(
            "status IN ('draft', 'submitted', 'approved', 'frozen', 'rejected', 'archived')",
            name="ck_budget_status",
        ),
        CheckConstraint(
            "budget_type IN ('annual', 'quarterly', 'monthly', 'project', 'ad_hoc')",
            name="ck_budget_type",
        ),
        Index("idx_budget_code", "budget_code"),
        Index("idx_budget_legal_entity", "legal_entity_id"),
        Index("idx_budget_fiscal_year", "fiscal_year"),
        Index("idx_budget_account_code", "account_code"),
        Index("idx_budget_cost_center", "cost_center"),
        Index("idx_budget_status", "status"),
        Index("idx_budget_period", "fiscal_year", "period"),
    )

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Identifikasi
    budget_code: Mapped[str] = mapped_column(String(50), nullable=False)
    budget_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    budget_type: Mapped[str] = mapped_column(String(20), nullable=False, default="annual")

    # Period
    fiscal_year: Mapped[int] = mapped_column(nullable=False)
    period: Mapped[int | None] = mapped_column(nullable=True)  # bulan (1-12) untuk monthly/quarterly
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Akun & dimensi
    account_code: Mapped[str] = mapped_column(String(20), nullable=False)
    account_name: Mapped[str] = mapped_column(String(200), nullable=False)
    cost_center: Mapped[str | None] = mapped_column(String(20), nullable=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    department: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Nilai budget
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")

    # Status
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Persetujuan
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Referensi
    original_budget_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )  # untuk revisi
    revision_number: Mapped[int] = mapped_column(nullable=False, default=0)

    # Audit
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================
    actuals: Mapped[list[BudgetActualTable]] = relationship(
        "BudgetActualTable",
        back_populates="budget",
        cascade="all, delete-orphan",
    )

    # ========================================================================
    # PROPERTIES
    # ========================================================================
    @property
    def total_actual(self) -> Decimal:
        """Total realisasi (actual) untuk budget ini."""
        if not self.actuals:
            return Decimal(0)
        return sum(a.amount for a in self.actuals)

    @property
    def variance(self) -> Decimal:
        """Variance = actual - budget."""
        return self.total_actual - self.amount

    @property
    def variance_percentage(self) -> float:
        """Variance as percentage of budget."""
        if self.amount == 0:
            return 0.0
        return float((self.variance / self.amount) * 100)

    @property
    def utilization_percentage(self) -> float:
        """Usage percentage = actual / budget."""
        if self.amount == 0:
            return 0.0
        return float((self.total_actual / self.amount) * 100)

    @property
    def is_over_budget(self) -> bool:
        """Check if actual exceeds budget."""
        return self.total_actual > self.amount

    @property
    def is_under_budget(self) -> bool:
        """Check if actual is below budget."""
        return self.total_actual < self.amount

    @property
    def is_approved(self) -> bool:
        return self.status == "approved"

    @property
    def is_draft(self) -> bool:
        return self.status == "draft"

    @property
    def is_frozen(self) -> bool:
        return self.status == "frozen"

    # ========================================================================
    # METHODS
    # ========================================================================
    def submit(self, submitted_by: uuid.UUID) -> None:
        """Submit budget for approval."""
        if self.status != "draft":
            raise ValueError(f"Cannot submit budget with status {self.status}")
        self.status = "submitted"
        self.submitted_by = submitted_by
        self.submitted_at = datetime.utcnow()
        self.increment_version()

    def approve(self, approved_by: uuid.UUID) -> None:
        """Approve budget."""
        if self.status != "submitted":
            raise ValueError(f"Cannot approve budget with status {self.status}")
        self.status = "approved"
        self.approved_by = approved_by
        self.approved_at = datetime.utcnow()
        self.increment_version()

    def reject(self, rejection_reason: str) -> None:
        """Reject budget."""
        if self.status != "submitted":
            raise ValueError(f"Cannot reject budget with status {self.status}")
        self.status = "rejected"
        self.rejection_reason = rejection_reason
        self.increment_version()

    def freeze(self) -> None:
        """Freeze approved budget (no more revisions allowed)."""
        if self.status != "approved":
            raise ValueError(f"Cannot freeze budget with status {self.status}")
        self.status = "frozen"
        self.increment_version()

    def archive(self) -> None:
        """Archive budget."""
        self.status = "archived"
        self.is_active = False
        self.increment_version()

    def revise(self, new_amount: Decimal, revision_reason: str) -> None:
        """Create a revision of budget (caller must create new record)."""
        # This method is for logic; actual new record creation is done by service.
        if self.status == "frozen":
            raise ValueError("Cannot revise frozen budget")
        # Mark current as superseded
        self.is_active = False
        self.increment_version()
        # New revision info
        self.revision_number += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "budget_code": self.budget_code,
            "budget_name": self.budget_name,
            "budget_type": self.budget_type,
            "fiscal_year": self.fiscal_year,
            "period": self.period,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "account_code": self.account_code,
            "account_name": self.account_name,
            "cost_center": self.cost_center,
            "project_id": str(self.project_id) if self.project_id else None,
            "department": self.department,
            "amount": str(self.amount),  # ganti float -> str untuk presisi
            "currency": self.currency,
            "status": self.status,
            "total_actual": str(self.total_actual),  # ganti float -> str
            "variance": str(self.variance),          # ganti float -> str
            "variance_percentage": self.variance_percentage,  # persentase, tetap float
            "utilization_percentage": self.utilization_percentage,  # persentase, tetap float
            "legal_entity_id": str(self.legal_entity_id),
            "version": self.version,
        }


__all__ = ["BudgetTable"]
