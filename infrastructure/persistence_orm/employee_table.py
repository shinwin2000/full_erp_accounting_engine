#!/usr/bin/env python3
"""
Module: employee_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel employee.
               Tabel ini menyimpan data master karyawan, termasuk informasi
               pribadi, kontak, data payroll (gaji, PTKP, BPJS), dan status
               kepegawaian. Digunakan oleh modul Payroll, HR, dan IAM.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import (
    Base,
    LegalEntityMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)

if TYPE_CHECKING:
    from infrastructure.persistence_orm.payslip_table import PayslipTable
    from infrastructure.persistence_orm.salary_component_table import SalaryComponentTable
    from infrastructure.persistence_orm.time_entry_table import TimeEntryTable


class EmployeeTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    """
    Model untuk tabel employee.
    """

    __tablename__ = "employee"
    __table_args__ = (
        UniqueConstraint("employee_code", "legal_entity_id", name="uq_employee_code_legal_entity"),
        UniqueConstraint("nik", name="uq_employee_nik"),
        UniqueConstraint("email", name="uq_employee_email"),
        UniqueConstraint("tax_id", name="uq_employee_tax_id"),
        CheckConstraint(
            "employee_code IS NOT NULL AND employee_code != ''", name="ck_employee_code"
        ),
        CheckConstraint("full_name IS NOT NULL AND full_name != ''", name="ck_employee_full_name"),
        CheckConstraint(
            "employment_status IN ('active', 'inactive', 'resigned', 'terminated', 'on_leave')",
            name="ck_employee_status",
        ),
        CheckConstraint("gender IN ('M', 'F', 'O')", name="ck_employee_gender"),
        CheckConstraint(
            "marital_status IN ('single', 'married', 'divorced', 'widowed')",
            name="ck_employee_marital_status",
        ),
        CheckConstraint(
            "ptkp_status IN ('TK/0', 'TK/1', 'TK/2', 'TK/3', 'K/0', 'K/1', 'K/2', 'K/3')",
            name="ck_employee_ptkp",
        ),
        Index("idx_employee_employee_code", "employee_code"),
        Index("idx_employee_nik", "nik"),
        Index("idx_employee_email", "email"),
        Index("idx_employee_tax_id", "tax_id"),
        Index("idx_employee_status", "employment_status"),
        Index("idx_employee_legal_entity", "legal_entity_id"),
        Index("idx_employee_department", "department"),
        Index("idx_employee_position", "position"),
        Index("idx_employee_ptkp_status", "ptkp_status"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Basic identification
    employee_code: Mapped[str] = mapped_column(String(30), nullable=False)
    nik: Mapped[str | None] = mapped_column(String(30), nullable=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    preferred_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    gender: Mapped[str | None] = mapped_column(String(1), nullable=True)

    # Personal information
    birth_place: Mapped[str | None] = mapped_column(String(100), nullable=True)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    marital_status: Mapped[str] = mapped_column(String(20), nullable=False, default="single")
    religion: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Contact
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    mobile: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    email_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Tax (PPh 21)
    tax_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tax_id_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    ptkp_status: Mapped[str] = mapped_column(String(10), nullable=False, default="TK/0")

    # Employment information
    join_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    resignation_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    employment_status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")

    # Position and organization
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    division: Mapped[str | None] = mapped_column(String(100), nullable=True)
    position: Mapped[str | None] = mapped_column(String(100), nullable=True)
    job_level: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cost_center: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Manager hierarchy
    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employee.id"), nullable=True
    )

    # Payroll data
    basic_salary: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    allowances: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    overtime_rate_multiplier: Mapped[Decimal] = mapped_column(
        Numeric(3, 1), nullable=False, default=1.5
    )

    # BPJS
    bpjs_ketenagakerjaan_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    bpjs_kesehatan_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    bpjs_jht_rate_employee: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=2.0
    )
    bpjs_jht_rate_employer: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=3.7
    )
    bpjs_jkk_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0.24)
    bpjs_jkm_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0.30)
    bpjs_kesehatan_rate_employee: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=1.0
    )
    bpjs_kesehatan_rate_employer: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=4.0
    )

    # Banking
    bank_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bank_account_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    bank_account_number_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    bank_account_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Leave balances
    annual_leave_balance: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=12
    )
    sick_leave_balance: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=14)
    special_leave_balance: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0
    )

    # Additional
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Audit
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================

    # Manager hierarchy (self-referential)
    manager: Mapped[EmployeeTable | None] = relationship(
        "EmployeeTable", remote_side="EmployeeTable.id", back_populates="subordinates"
    )
    subordinates: Mapped[list[EmployeeTable]] = relationship(
        "EmployeeTable", back_populates="manager"
    )

    # Salary components
    salary_components: Mapped[list[SalaryComponentTable]] = relationship(
        "SalaryComponentTable",
        back_populates="employee",
        foreign_keys="[SalaryComponentTable.employee_id]",
        cascade="all, delete-orphan",
    )

    # Time entries
    time_entries: Mapped[list[TimeEntryTable]] = relationship(
        "TimeEntryTable",
        back_populates="employee",
        foreign_keys="[TimeEntryTable.employee_id]",
        cascade="all, delete-orphan",
    )

    # Payslips (added for back_populates in PayslipTable)
    payslips: Mapped[list[PayslipTable]] = relationship(
        "PayslipTable",
        back_populates="employee",
        foreign_keys="[PayslipTable.employee_id]",
        cascade="all, delete-orphan",
    )

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def age(self) -> int | None:
        if self.birth_date:
            today = date.today()
            return (
                today.year
                - self.birth_date.year
                - ((today.month, today.day) < (self.birth_date.month, self.birth_date.day))
            )
        return None

    @property
    def is_active_employee(self) -> bool:
        return self.employment_status == "active" and self.is_active

    @property
    def is_resigned(self) -> bool:
        return self.employment_status == "resigned"

    @property
    def total_annual_salary(self) -> Decimal:
        monthly = self.basic_salary + self.allowances
        return monthly * 12

    @property
    def monthly_taxable_income(self) -> Decimal:
        bpjs_deduction = self.basic_salary * (
            self.bpjs_jht_rate_employee / 100
        ) + self.basic_salary * (self.bpjs_kesehatan_rate_employee / 100)
        return self.basic_salary + self.allowances - bpjs_deduction

    @property
    def bpjs_employee_total_rate(self) -> Decimal:
        return self.bpjs_jht_rate_employee + self.bpjs_kesehatan_rate_employee

    @property
    def bpjs_employer_total_rate(self) -> Decimal:
        return (
            self.bpjs_jht_rate_employer
            + self.bpjs_jkk_rate
            + self.bpjs_jkm_rate
            + self.bpjs_kesehatan_rate_employer
        )

    # ========================================================================
    # METHODS
    # ========================================================================

    def activate(self) -> None:
        self.employment_status = "active"
        self.is_active = True
        self.increment_version()

    def deactivate(self) -> None:
        self.employment_status = "inactive"
        self.is_active = False
        self.increment_version()

    def resign(self, resignation_date: date) -> None:
        self.employment_status = "resigned"
        self.resignation_date = resignation_date
        self.is_active = False
        self.increment_version()

    def terminate(self, termination_date: date, reason: str | None = None) -> None:
        self.employment_status = "terminated"
        self.resignation_date = termination_date
        self.is_active = False
        if reason:
            if self.extra_metadata is None:
                self.extra_metadata = {}
            self.extra_metadata["termination_reason"] = reason
        self.increment_version()

    def update_salary(self, new_basic_salary: Decimal, effective_date: date) -> None:
        old = self.basic_salary
        self.basic_salary = new_basic_salary
        if self.extra_metadata is None:
            self.extra_metadata = {}
        if "salary_history" not in self.extra_metadata:
            self.extra_metadata["salary_history"] = []
        self.extra_metadata["salary_history"].append(
            {
                "date": effective_date.isoformat(),
                "old_salary": float(old),
                "new_salary": float(new_basic_salary),
            }
        )
        self.increment_version()

    def has_available_leave(self, leave_type: str, days: Decimal) -> bool:
        if leave_type == "annual":
            return self.annual_leave_balance >= days
        elif leave_type == "sick":
            return self.sick_leave_balance >= days
        elif leave_type == "special":
            return self.special_leave_balance >= days
        return False

    def deduct_leave(self, leave_type: str, days: Decimal) -> None:
        if leave_type == "annual":
            self.annual_leave_balance -= days
        elif leave_type == "sick":
            self.sick_leave_balance -= days
        elif leave_type == "special":
            self.special_leave_balance -= days
        self.increment_version()

    def reset_leave_balance(self, annual_days: Decimal = 12, sick_days: Decimal = 14) -> None:
        self.annual_leave_balance = annual_days
        self.sick_leave_balance = sick_days
        self.special_leave_balance = 0
        self.increment_version()

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "employee_code": self.employee_code,
            "nik": self.nik,
            "full_name": self.full_name,
            "preferred_name": self.preferred_name,
            "gender": self.gender,
            "birth_place": self.birth_place,
            "birth_date": self.birth_date.isoformat() if self.birth_date else None,
            "age": self.age,
            "marital_status": self.marital_status,
            "religion": self.religion,
            "address": self.address,
            "city": self.city,
            "postal_code": self.postal_code,
            "phone": self.phone,
            "mobile": self.mobile,
            "email": self.email,
            "tax_id": self.tax_id,
            "ptkp_status": self.ptkp_status,
            "join_date": self.join_date.isoformat() if self.join_date else None,
            "resignation_date": self.resignation_date.isoformat()
            if self.resignation_date
            else None,
            "employment_status": self.employment_status,
            "department": self.department,
            "division": self.division,
            "position": self.position,
            "job_level": self.job_level,
            "cost_center": self.cost_center,
            "manager_id": str(self.manager_id) if self.manager_id else None,
            "basic_salary": float(self.basic_salary),
            "allowances": float(self.allowances),
            "overtime_rate_multiplier": float(self.overtime_rate_multiplier),
            "total_annual_salary": float(self.total_annual_salary),
            "monthly_taxable_income": float(self.monthly_taxable_income),
            "bpjs_ketenagakerjaan_number": self.bpjs_ketenagakerjaan_number,
            "bpjs_kesehatan_number": self.bpjs_kesehatan_number,
            "bpjs_jht_rate_employee": float(self.bpjs_jht_rate_employee),
            "bpjs_jht_rate_employer": float(self.bpjs_jht_rate_employer),
            "bpjs_jkk_rate": float(self.bpjs_jkk_rate),
            "bpjs_jkm_rate": float(self.bpjs_jkm_rate),
            "bpjs_kesehatan_rate_employee": float(self.bpjs_kesehatan_rate_employee),
            "bpjs_kesehatan_rate_employer": float(self.bpjs_kesehatan_rate_employer),
            "bank_name": self.bank_name,
            "bank_account_number": self.bank_account_number,
            "bank_account_name": self.bank_account_name,
            "annual_leave_balance": float(self.annual_leave_balance),
            "sick_leave_balance": float(self.sick_leave_balance),
            "special_leave_balance": float(self.special_leave_balance),
            "is_active": self.is_active,
            "notes": self.notes,
            "extra_metadata": self.extra_metadata,
            "legal_entity_id": str(self.legal_entity_id),
            "created_by": str(self.created_by) if self.created_by else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "version": self.version,
        }


__all__ = ["EmployeeTable"]
