#!/usr/bin/env python3
"""
Module: time_entry_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel time_entry.
               Tabel ini menyimpan entry waktu (timesheet) karyawan untuk
               proyek atau aktivitas tertentu. Digunakan untuk perhitungan
               biaya tenaga kerja proyek (project costing) dan payroll.
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
    from infrastructure.persistence_orm.employee_table import EmployeeTable
    from infrastructure.persistence_orm.project_table import ProjectTable


class TimeEntryTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    __tablename__ = "time_entry"
    __table_args__ = (
        CheckConstraint("hours > 0", name="ck_time_entry_hours_positive"),
        CheckConstraint("hourly_rate >= 0", name="ck_time_entry_rate_nonneg"),
        CheckConstraint("total_cost >= 0", name="ck_time_entry_total_nonneg"),
        CheckConstraint(
            "status IN ('draft', 'submitted', 'approved', 'rejected', 'billed')",
            name="ck_time_entry_status",
        ),
        Index("idx_time_entry_employee", "employee_id"),
        Index("idx_time_entry_project", "project_id"),
        Index("idx_time_entry_date", "entry_date"),
        Index("idx_time_entry_status", "status"),
        Index("idx_time_entry_legal_entity", "legal_entity_id"),
        Index("idx_time_entry_approved_by", "approved_by"),
        {"schema": "public", "extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Employee and project
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("public.employee.id", ondelete="RESTRICT"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("public.project.id", ondelete="SET NULL"),
        nullable=True,
    )
    work_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Time details
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    hours: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    hourly_rate: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")

    # Description
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    activity_code: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Status and approval
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Billing
    is_billable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    billing_rate: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    billed_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Overtime flag
    is_overtime: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    overtime_multiplier: Mapped[Decimal] = mapped_column(Numeric(3, 1), nullable=False, default=1.0)

    # Additional info
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Audit
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================

    employee: Mapped[EmployeeTable] = relationship(
        "EmployeeTable",
        foreign_keys=[employee_id],
        back_populates="time_entries",  # harus ditambahkan di EmployeeTable
    )
    project: Mapped[ProjectTable | None] = relationship(
        "ProjectTable",
        foreign_keys=[project_id],
        back_populates="time_entries",  # harus ditambahkan di ProjectTable
    )

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def is_approved(self) -> bool:
        return self.status == "approved"

    @property
    def is_submitted(self) -> bool:
        return self.status == "submitted"

    @property
    def is_draft(self) -> bool:
        return self.status == "draft"

    @property
    def effective_hourly_rate(self) -> Decimal:
        rate = self.hourly_rate
        if self.is_overtime:
            rate = rate * self.overtime_multiplier
        return rate

    @property
    def effective_total_cost(self) -> Decimal:
        return self.effective_hourly_rate * self.hours

    @property
    def billable_amount(self) -> Decimal:
        if not self.is_billable:
            return Decimal(0)
        billing_rate = self.billing_rate or self.effective_hourly_rate
        return billing_rate * self.hours

    @property
    def is_billed(self) -> bool:
        return self.status == "billed"

    @property
    def is_rejected(self) -> bool:
        return self.status == "rejected"

    # ========================================================================
    # METHODS
    # ========================================================================

    def submit(self) -> None:
        if self.status != "draft":
            raise ValueError(f"Cannot submit time entry with status {self.status}")
        self.status = "submitted"
        self.submitted_at = datetime.utcnow()
        self.increment_version()

    def approve(self, approved_by: uuid.UUID) -> None:
        if self.status != "submitted":
            raise ValueError(f"Cannot approve time entry with status {self.status}")
        self.status = "approved"
        self.approved_by = approved_by
        self.approved_at = datetime.utcnow()
        self.total_cost = self.effective_total_cost
        self.increment_version()

    def reject(self, reason: str) -> None:
        if self.status != "submitted":
            raise ValueError(f"Cannot reject time entry with status {self.status}")
        self.status = "rejected"
        self.rejection_reason = reason
        self.increment_version()

    def mark_billed(self, invoice_id: uuid.UUID, billed_amount: Decimal) -> None:
        if self.status != "approved":
            raise ValueError(f"Cannot bill time entry with status {self.status}")
        self.status = "billed"
        self.invoice_id = invoice_id
        self.billed_amount = billed_amount
        self.increment_version()

    def recalculate_cost(self) -> None:
        self.total_cost = self.effective_total_cost
        self.increment_version()

    def is_owner(self, employee_id: uuid.UUID) -> bool:
        return self.employee_id == employee_id


__all__ = ["TimeEntryTable"]
