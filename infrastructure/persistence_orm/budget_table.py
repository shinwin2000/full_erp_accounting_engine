#!/usr/bin/env python3
"""
Module: budget_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model untuk menyimpan anggaran (budget) dengan struktur header + lines.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ARRAY,
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

# ============================================================================
# BUDGET HEADER TABLE
# ============================================================================


class BudgetTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    """
    Model untuk tabel budget header.
    Satu budget = satu header + banyak lines.
    """

    __tablename__ = "budget"
    __table_args__ = (
        UniqueConstraint(
            "budget_code", "legal_entity_id", name="uq_budget_code_legal_entity"
        ),
        CheckConstraint(
            "budget_code IS NOT NULL AND budget_code != ''", name="ck_budget_code"
        ),
        CheckConstraint(
            "status IN ('draft', 'submitted', 'under_review', 'approved', 'rejected', "
            "'active', 'locked', 'archived', 'expired', 'cancelled', 'closed')",
            name="ck_budget_status",
        ),
        CheckConstraint(
            "budget_type IN ('operational', 'capital', 'cash', 'project', 'department', "
            "'fixed_asset', 'sales', 'production', 'labor')",
            name="ck_budget_type",
        ),
        CheckConstraint(
            "period IN ('monthly', 'quarterly', 'yearly')",
            name="ck_budget_period",
        ),
        Index("idx_budget_code", "budget_code"),
        Index("idx_budget_legal_entity", "legal_entity_id"),
        Index("idx_budget_fiscal_year", "fiscal_year"),
        Index("idx_budget_status", "status"),
        Index("idx_budget_effective_date", "effective_date"),
        Index("idx_budget_expiry_date", "expiry_date"),
    )

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Identifikasi
    budget_code: Mapped[str] = mapped_column(String(50), nullable=False)
    budget_name: Mapped[str] = mapped_column(String(200), nullable=False)
    budget_type: Mapped[str] = mapped_column(String(20), nullable=False, default="operational")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Period
    fiscal_year: Mapped[int] = mapped_column(nullable=False)
    period: Mapped[str] = mapped_column(String(20), nullable=False, default="monthly")
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0")

    # Tanggal
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Mata uang
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")

    # Metadata
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)

    # Audit
    created_by: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_by: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Approval
    submitted_by: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_by: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    lines: Mapped[list[BudgetLineTable]] = relationship(
        "BudgetLineTable",
        back_populates="budget",
        cascade="all, delete-orphan",
        order_by="BudgetLineTable.created_at",
    )

    # FIX: sisi balik dari BudgetActualTable.budget (back_populates="actuals")
    # di infrastructure/persistence_orm/budget_actual_table.py — tanpa ini,
    # SQLAlchemy gagal saat registry.configure() karena mencari property
    # 'actuals' di BudgetTable yang sebelumnya tidak pernah didefinisikan.
    actuals: Mapped[list[BudgetActualTable]] = relationship(
        "BudgetActualTable",
        back_populates="budget",
        cascade="all, delete-orphan",
    )

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def total_amount(self) -> Decimal:
        """Total amount dari semua lines."""
        if not self.lines:
            return Decimal(0)
        return sum(line.amount for line in self.lines)

    @property
    def is_active(self) -> bool:
        """Cek apakah budget aktif berdasarkan tanggal."""
        today = date.today()
        return (
            self.status == "active"
            and self.effective_date <= today
            and (self.expiry_date is None or self.expiry_date >= today)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "budget_code": self.budget_code,
            "budget_name": self.budget_name,
            "budget_type": self.budget_type,
            "fiscal_year": self.fiscal_year,
            "period": self.period,
            "version": self.version,
            "status": self.status,
            "effective_date": self.effective_date.isoformat(),
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "currency": self.currency,
            "total_amount": str(self.total_amount),
            "is_locked": self.is_locked,
            "notes": self.notes,
            "tags": self.tags,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "created_by": str(self.created_by) if self.created_by else None,
            "updated_by": str(self.updated_by) if self.updated_by else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "approved_by": str(self.approved_by) if self.approved_by else None,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "submitted_by": str(self.submitted_by) if self.submitted_by else None,
            "rejected_at": self.rejected_at.isoformat() if self.rejected_at else None,
            "rejected_by": str(self.rejected_by) if self.rejected_by else None,
            "rejection_reason": self.rejection_reason,
            "version": self.version,
            "lines": [line.to_dict() for line in self.lines] if self.lines else [],
        }


# ============================================================================
# BUDGET LINE TABLE
# ============================================================================


class BudgetLineTable(Base, TimestampMixin, VersionMixin):
    """
    Model untuk tabel budget line (detail per akun).
    """

    __tablename__ = "budget_line"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_budget_line_amount_nonneg"),
        CheckConstraint(
            "account_code IS NOT NULL AND account_code != ''", name="ck_budget_line_account_code"
        ),
        Index("idx_budget_line_budget", "budget_id"),
        Index("idx_budget_line_account", "account_id", "account_code"),
    )

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    budget_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("budget.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    account_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    account_code: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Audit
    created_by: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_by: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Relationship
    budget: Mapped[BudgetTable] = relationship("BudgetTable", back_populates="lines")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "budget_id": str(self.budget_id),
            "account_id": str(self.account_id),
            "account_code": self.account_code,
            "amount": str(self.amount),
            "note": self.note,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "created_by": str(self.created_by) if self.created_by else None,
            "updated_by": str(self.updated_by) if self.updated_by else None,
            "version": self.version,
        }


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["BudgetLineTable", "BudgetTable"]
