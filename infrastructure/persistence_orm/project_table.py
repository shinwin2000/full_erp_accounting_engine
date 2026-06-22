#!/usr/bin/env python3
"""
Module: project_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel project.
               Tabel ini menyimpan data proyek (project-based accounting),
               termasuk kode proyek, nama, status, budget, progress, dan
               periode pelaksanaan. Digunakan untuk project costing, billing,
               dan revenue recognition.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
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
    from infrastructure.persistence_orm.retainer_contract_table import RetainerContractTable
    from infrastructure.persistence_orm.time_entry_table import TimeEntryTable


class ProjectTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    __tablename__ = "project"
    __table_args__ = (
        UniqueConstraint("project_code", "legal_entity_id", name="uq_project_code_legal_entity"),
        CheckConstraint("project_code IS NOT NULL AND project_code != ''", name="ck_project_code"),
        CheckConstraint("project_name IS NOT NULL AND project_name != ''", name="ck_project_name"),
        CheckConstraint(
            "status IN ('planning', 'active', 'on_hold', 'completed', 'cancelled', 'archived')",
            name="ck_project_status",
        ),
        CheckConstraint("budget >= 0", name="ck_project_budget_nonneg"),
        CheckConstraint("actual_cost >= 0", name="ck_project_actual_cost_nonneg"),
        CheckConstraint("billed_amount >= 0", name="ck_project_billed_nonneg"),
        CheckConstraint("paid_amount >= 0", name="ck_project_paid_nonneg"),
        Index("idx_project_code", "project_code"),
        Index("idx_project_customer", "customer_id"),
        Index("idx_project_status", "status"),
        Index("idx_project_legal_entity", "legal_entity_id"),
        Index("idx_project_start_date", "start_date"),
        Index("idx_project_end_date", "end_date"),
        Index("idx_project_manager", "project_manager_id"),
        {"schema": "public", "extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Basic identification
    project_code: Mapped[str] = mapped_column(String(50), nullable=False)
    project_name: Mapped[str] = mapped_column(String(200), nullable=False)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("public.customer.id", ondelete="SET NULL"),
        nullable=True,
    )
    customer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Dates
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    actual_completion_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Financial
    budget: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    actual_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    billed_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")

    # Progress
    progress_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planning")

    # Management
    project_manager_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    project_manager_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cost_center: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Billing
    billing_type: Mapped[str] = mapped_column(String(20), nullable=False, default="time_material")
    contract_value: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    retainer_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)

    # Description
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Project type and classification
    project_type: Mapped[str] = mapped_column(String(50), nullable=False, default="internal")
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")

    # Template / parent project
    parent_project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Audit
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================

    # Retainer Contracts (connected via retainer_contract_table)
    retainer_contracts: Mapped[list[RetainerContractTable]] = relationship(
        "RetainerContractTable",
        back_populates="project",
        cascade="all, delete-orphan",
    )

    # Time entries (connected via time_entry_table)
    time_entries: Mapped[list[TimeEntryTable]] = relationship(
        "TimeEntryTable",
        back_populates="project",
        foreign_keys="[TimeEntryTable.project_id]",
        cascade="all, delete-orphan",
    )

    # REMOVED: cost_trackers (ProjectCostTrackerTable not defined)
    # REMOVED: billing_schedules (ProjectBillingScheduleTable not defined)

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def remaining_budget(self) -> Decimal:
        return max(Decimal(0), self.budget - self.actual_cost)

    @property
    def outstanding_billed(self) -> Decimal:
        return max(Decimal(0), self.billed_amount - self.paid_amount)

    @property
    def cost_overrun(self) -> Decimal:
        return max(Decimal(0), self.actual_cost - self.budget)

    @property
    def is_over_budget(self) -> bool:
        return self.actual_cost > self.budget

    @property
    def is_completed(self) -> bool:
        return self.status == "completed"

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    @property
    def progress_status(self) -> str:
        if self.progress_percent >= 100:
            return "completed"
        elif self.progress_percent >= 75:
            return "near_completion"
        elif self.progress_percent >= 50:
            return "halfway"
        elif self.progress_percent >= 25:
            return "started"
        elif self.progress_percent > 0:
            return "just_started"
        return "not_started"

    @property
    def profitability(self) -> Decimal:
        """Profit/Loss (billed - actual_cost)."""
        return self.billed_amount - self.actual_cost

    # ========================================================================
    # METHODS
    # ========================================================================

    def activate(self) -> None:
        if self.status not in ("planning", "on_hold"):
            raise ValueError(f"Cannot activate project with status {self.status}")
        self.status = "active"
        if self.start_date is None:
            self.start_date = date.today()
        self.increment_version()

    def put_on_hold(self) -> None:
        if self.status != "active":
            raise ValueError(f"Cannot put project on hold with status {self.status}")
        self.status = "on_hold"
        self.increment_version()

    def complete(self, completion_date: date | None = None) -> None:
        if self.status not in ("active", "on_hold"):
            raise ValueError(f"Cannot complete project with status {self.status}")
        self.status = "completed"
        self.actual_completion_date = completion_date or date.today()
        self.progress_percent = Decimal(100)
        self.increment_version()

    def cancel(self) -> None:
        if self.status in ("completed", "cancelled", "archived"):
            raise ValueError(f"Cannot cancel project with status {self.status}")
        self.status = "cancelled"
        self.increment_version()

    def archive(self) -> None:
        if self.status != "completed":
            raise ValueError("Only completed projects can be archived")
        self.status = "archived"
        self.increment_version()

    def add_actual_cost(self, amount: Decimal) -> None:
        if amount <= 0:
            raise ValueError("Amount must be positive")
        self.actual_cost += amount
        if self.budget > 0:
            self.progress_percent = min(
                Decimal(100), (self.actual_cost / self.budget) * Decimal(100)
            )
        self.increment_version()

    def record_billing(self, amount: Decimal) -> None:
        if amount <= 0:
            raise ValueError("Billing amount must be positive")
        self.billed_amount += amount
        self.increment_version()

    def record_payment(self, amount: Decimal) -> None:
        if amount <= 0:
            raise ValueError("Payment amount must be positive")
        self.paid_amount += amount
        self.increment_version()

    def update_progress(self, progress_percent: Decimal) -> None:
        if progress_percent < 0 or progress_percent > 100:
            raise ValueError("Progress must be between 0 and 100")
        self.progress_percent = progress_percent
        self.increment_version()


__all__ = ["ProjectTable"]
