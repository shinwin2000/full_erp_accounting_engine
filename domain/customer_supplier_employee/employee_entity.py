#!/usr/bin/env python3
"""
Module: employee_entity.py

Layer: Domain / Customer, Supplier, Employee

Responsibility:
    Employee entity representing a person employed by the company.
    Contains personal information, employment details, tax status (PTKP),
    BPJS enrollments, salary, and employment history.

Business rules:
    - Employee number must be unique across legal entity.
    - Email must be unique (if provided).
    - Tax ID (NPWP) must be unique (if provided).
    - Basic salary must be >= minimum wage.
    - Gender must be 'M' or 'F'.
    - Join date cannot be in the future.
    - Resign date must be after join date and cannot be before today if active.
    - PTKP status determines tax calculation.
    - BPJS enrollments have separate validity.
    - Version increments on every change (optimistic locking).

Dependencies:
    - Python standard library (uuid, datetime, decimal, logging, re)
    - domain.customer_supplier_employee.employee_ptkp_status_vo (EmployeePTKPStatusVO)
    - domain.customer_supplier_employee.employee_bpjs_enrollment_vo (EmployeeBPJSEnrollmentVO)

Audit:
    Every state change should be logged; domain events should be emitted separately.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from domain.customer_supplier_employee.employee_bpjs_enrollment_vo import (
    BPJSType,
    EmployeeBPJSEnrollmentVO,
)
from domain.customer_supplier_employee.employee_ptkp_status_vo import (
    EmployeePTKPStatusVO,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class EmployeeStatus(Enum):
    """Employment status."""

    ACTIVE = "active"  # Currently working
    INACTIVE = "inactive"  # Not working (e.g., unpaid leave)
    RESIGNED = "resigned"  # Voluntarily resigned
    TERMINATED = "terminated"  # Fired / laid off
    ON_LEAVE = "on_leave"  # On leave (e.g., maternity, sabbatical)
    SUSPENDED = "suspended"  # Suspended pending investigation
    DRAFT = "draft"  # Not yet activated

    def can_process_payroll(self) -> bool:
        """Can this employee be included in payroll processing?"""
        return self == EmployeeStatus.ACTIVE

    def can_be_edited(self) -> bool:
        """Can employee data be edited?"""
        return self not in (EmployeeStatus.RESIGNED, EmployeeStatus.TERMINATED)

    def display_name(self) -> str:
        names = {
            EmployeeStatus.ACTIVE: "Aktif",
            EmployeeStatus.INACTIVE: "Tidak Aktif",
            EmployeeStatus.RESIGNED: "Mengundurkan Diri",
            EmployeeStatus.TERMINATED: "Diberhentikan",
            EmployeeStatus.ON_LEAVE: "Cuti",
            EmployeeStatus.SUSPENDED: "Ditangguhkan",
            EmployeeStatus.DRAFT: "Draft",
        }
        return names.get(self, self.value)

    @classmethod
    def from_string(cls, value: str) -> EmployeeStatus | None:
        for status in cls:
            if status.value == value.lower():
                return status
        return None


class EmployeeType(Enum):
    """Type of employment."""

    PERMANENT = "permanent"  # Tetap
    CONTRACT = "contract"  # Kontrak
    INTERN = "intern"  # Magang
    FREELANCE = "freelance"  # Lepas
    DIRECTOR = "director"  # Direktur
    COMMISSIONER = "commissioner"  # Komisaris
    PROBATION = "probation"  # Masa percobaan

    def has_benefits(self) -> bool:
        """Does this employee type receive full benefits (BPJS, THR, etc.)?"""
        return self in (EmployeeStatus.ACTIVE, EmployeeStatus.ON_LEAVE) and self in (
            EmployeeType.PERMANENT,
            EmployeeType.DIRECTOR,
            EmployeeType.COMMISSIONER,
        )

    def display_name(self) -> str:
        names = {
            EmployeeType.PERMANENT: "Tetap",
            EmployeeType.CONTRACT: "Kontrak",
            EmployeeType.INTERN: "Magang",
            EmployeeType.FREELANCE: "Freelance",
            EmployeeType.DIRECTOR: "Direktur",
            EmployeeType.COMMISSIONER: "Komisaris",
            EmployeeType.PROBATION: "Masa Percobaan",
        }
        return names.get(self, self.value)

    @classmethod
    def from_string(cls, value: str) -> EmployeeType | None:
        for typ in cls:
            if typ.value == value.lower():
                return typ
        return None


class Gender(Enum):
    MALE = "M"
    FEMALE = "F"

    def display_name(self) -> str:
        return "Laki-laki" if self == Gender.MALE else "Perempuan"

    @classmethod
    def from_string(cls, value: str) -> Gender | None:
        val = value.upper()
        if val in ("M", "MALE", "L"):
            return Gender.MALE
        if val in ("F", "FEMALE", "P"):
            return Gender.FEMALE
        return None


# ============================================================================
# Helper Functions
# ============================================================================


def _validate_email(email: str | None) -> str | None:
    if email is None:
        return None
    email_clean = email.strip().lower()
    if not email_clean:
        return None
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    if not re.match(pattern, email_clean):
        raise ValueError(f"Invalid email format: {email}")
    return email_clean


def _validate_phone(phone: str | None) -> str | None:
    if phone is None:
        return None
    phone_clean = re.sub(r"[\s\-\(\)]", "", phone)
    if not phone_clean:
        return None
    if not phone_clean.isdigit():
        raise ValueError(f"Phone number must contain only digits, got {phone}")
    if len(phone_clean) < 8 or len(phone_clean) > 15:
        raise ValueError(f"Phone number must be 8-15 digits, got {len(phone_clean)}")
    return phone_clean


def _validate_npwp(npwp: str | None) -> str | None:
    if npwp is None:
        return None
    cleaned = re.sub(r"[^\d]", "", npwp)
    if len(cleaned) != 15:
        raise ValueError(f"NPWP must be 15 digits, got {len(cleaned)}")
    if not cleaned.isdigit():
        raise ValueError(f"NPWP must contain only digits, got {npwp}")
    return cleaned


def _calculate_age(birth_date: date, as_of: date | None = None) -> int:
    if birth_date is None:
        return 0
    as_of = as_of or date.today()
    years = as_of.year - birth_date.year
    if (as_of.month, as_of.day) < (birth_date.month, birth_date.day):
        years -= 1
    return max(0, years)


def _calculate_tenure(
    join_date: date, resign_date: date | None, as_of: date | None = None
) -> tuple[int, int]:
    """Return (years, days) of tenure."""
    as_of = as_of or date.today()
    end_date = resign_date if (resign_date and resign_date < as_of) else as_of
    if end_date < join_date:
        return 0, 0
    delta = end_date - join_date
    years = delta.days // 365
    days = delta.days % 365
    return years, days


# ============================================================================
# Employee Entity
# ============================================================================


@dataclass
class EmployeeEntity:
    """
    Employee entity representing a person employed by the company.

    Attributes:
        employee_id: Unique identifier
        legal_entity_id: Legal entity that employs this person
        employee_number: Unique employee code (e.g., 'EMP-001')
        full_name: Full legal name
        employee_type: Type of employment
        gender: Gender ('M' or 'F')
        ptkp_status: PTKP status for tax calculation
        bpjs_health: BPJS Kesehatan enrollment
        bpjs_employment: BPJS Ketenagakerjaan enrollment
        basic_salary: Monthly basic salary in currency
        join_date: Date employment started
        resign_date: Date employment ended (if resigned/terminated)
        nick_name: Optional nickname
        birth_place: Place of birth
        birth_date: Date of birth
        tax_id: NPWP (Tax ID)
        email: Work email (unique)
        phone: Work phone
        mobile: Personal mobile
        address: Street address
        city: City
        province: Province
        postal_code: Postal code
        department: Department name
        position: Job title
        cost_center: Cost center code
        bank_name: Bank name for salary
        bank_account_number: Bank account number
        bank_account_name: Account holder name
        currency: Salary currency (default IDR)
        status: Employment status
        created_at, updated_at, created_by, updated_by, version
    """

    # ========== Mandatory Fields ==========
    employee_id: UUID
    legal_entity_id: UUID
    employee_number: str
    full_name: str
    employee_type: EmployeeType
    gender: Gender
    ptkp_status: EmployeePTKPStatusVO
    bpjs_health: EmployeeBPJSEnrollmentVO
    bpjs_employment: EmployeeBPJSEnrollmentVO
    basic_salary: Decimal
    join_date: date

    # ========== Optional Fields ==========
    resign_date: date | None = None
    nick_name: str | None = None
    birth_place: str | None = None
    birth_date: date | None = None
    tax_id: str | None = None
    email: str | None = None
    phone: str | None = None
    mobile: str | None = None
    address: str | None = None
    city: str | None = None
    province: str | None = None
    postal_code: str | None = None
    department: str | None = None
    position: str | None = None
    cost_center: str | None = None
    bank_name: str | None = None
    bank_account_number: str | None = None
    bank_account_name: str | None = None
    currency: str = "IDR"
    status: EmployeeStatus = EmployeeStatus.ACTIVE
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    updated_by: str = "system"
    version: int = 1

    def __post_init__(self) -> None:
        """Validate employee data."""
        # Validate employee number
        if not self.employee_number or not isinstance(self.employee_number, str):
            raise ValueError("Employee number must be a non-empty string")
        emp_no_clean = self.employee_number.strip()
        if len(emp_no_clean) < 2:
            raise ValueError("Employee number must be at least 2 characters")
        if len(emp_no_clean) > 30:
            raise ValueError("Employee number must not exceed 30 characters")
        object.__setattr__(self, "employee_number", emp_no_clean)

        # Validate full name
        if not self.full_name or not isinstance(self.full_name, str):
            raise ValueError("Full name must be a non-empty string")
        name_clean = self.full_name.strip()
        if len(name_clean) < 2:
            raise ValueError("Full name must be at least 2 characters")
        if len(name_clean) > 200:
            raise ValueError("Full name must not exceed 200 characters")
        object.__setattr__(self, "full_name", name_clean)

        # Validate gender
        if not isinstance(self.gender, Gender):
            raise ValueError(f"Invalid gender: {self.gender}")

        # Validate basic salary
        if not isinstance(self.basic_salary, Decimal):
            object.__setattr__(self, "basic_salary", Decimal(str(self.basic_salary)))
        if self.basic_salary <= 0:
            raise ValueError(f"Basic salary must be positive: {self.basic_salary}")
        # Rough minimum wage check (can be overridden by service)
        min_wage = Decimal("4500000")  # 2024 Jakarta UMP approx
        if self.basic_salary < min_wage:
            logger.warning(
                f"Basic salary {self.basic_salary} below typical minimum wage {min_wage}"
            )

        # Validate join_date not future
        if self.join_date > date.today():
            raise ValueError(f"Join date cannot be in the future: {self.join_date}")

        # Validate resign_date
        if self.resign_date and self.resign_date <= self.join_date:
            raise ValueError(
                f"Resign date {self.resign_date} must be after join date {self.join_date}"
            )
        if self.resign_date and self.status not in (
            EmployeeStatus.RESIGNED,
            EmployeeStatus.TERMINATED,
        ):
            raise ValueError(f"Resign date set but status is {self.status.value}")

        # Validate status consistency
        if self.status == EmployeeStatus.RESIGNED and not self.resign_date:
            raise ValueError("Resigned employee must have resign_date")
        if self.status == EmployeeStatus.TERMINATED and not self.resign_date:
            raise ValueError("Terminated employee must have resign_date")

        # Validate birth_date
        if self.birth_date:
            if self.birth_date > date.today():
                raise ValueError(f"Birth date cannot be in the future: {self.birth_date}")
            age_at_join = _calculate_age(self.birth_date, self.join_date)
            if age_at_join < 18:
                raise ValueError(
                    f"Employee must be at least 18 years old at join date (age {age_at_join})"
                )

        # Validate email
        if self.email:
            object.__setattr__(self, "email", _validate_email(self.email))

        # Validate phone numbers
        if self.phone:
            object.__setattr__(self, "phone", _validate_phone(self.phone))
        if self.mobile:
            object.__setattr__(self, "mobile", _validate_phone(self.mobile))

        # Validate tax_id
        if self.tax_id:
            object.__setattr__(self, "tax_id", _validate_npwp(self.tax_id))

        # Validate currency
        if not self.currency or len(self.currency) != 3:
            raise ValueError(f"Invalid currency code: {self.currency}")

        # Validate dates UTC
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))
        if self.updated_at.tzinfo is None:
            object.__setattr__(self, "updated_at", self.updated_at.replace(tzinfo=UTC))

        # Validate version
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    # ------------------------------------------------------------------------
    # Factory Methods
    # ------------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        legal_entity_id: UUID,
        employee_number: str,
        full_name: str,
        employee_type: EmployeeType,
        gender: Gender,
        basic_salary: Decimal,
        join_date: date,
        ptkp_status: EmployeePTKPStatusVO | None = None,
        created_by: str = "system",
        employee_id: UUID | None = None,
        **kwargs,
    ) -> EmployeeEntity:
        """Create a new employee with defaults."""
        if ptkp_status is None:
            ptkp_status = EmployeePTKPStatusVO.create_single()
        now = datetime.now(UTC)
        return cls(
            employee_id=employee_id or uuid4(),
            legal_entity_id=legal_entity_id,
            employee_number=employee_number,
            full_name=full_name,
            employee_type=employee_type,
            gender=gender,
            ptkp_status=ptkp_status,
            bpjs_health=EmployeeBPJSEnrollmentVO(
                membership_number="", bpjs_type=BPJSType.HEALTH, is_active=False
            ),
            bpjs_employment=EmployeeBPJSEnrollmentVO(
                membership_number="", bpjs_type=BPJSType.EMPLOYMENT, is_active=False
            ),
            basic_salary=basic_salary,
            join_date=join_date,
            created_at=now,
            updated_at=now,
            created_by=created_by,
            updated_by=created_by,
            version=1,
            **kwargs,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EmployeeEntity:
        """Reconstruct employee from dictionary."""
        employee_type = EmployeeType.from_string(data["employee_type"])
        if employee_type is None:
            raise ValueError(f"Invalid employee_type: {data['employee_type']}")
        gender = Gender.from_string(data["gender"])
        if gender is None:
            raise ValueError(f"Invalid gender: {data['gender']}")
        status = EmployeeStatus.from_string(data.get("status", "active"))
        if status is None:
            status = EmployeeStatus.ACTIVE

        ptkp_status = data.get("ptkp_status")
        if isinstance(ptkp_status, dict):
            ptkp_status = EmployeePTKPStatusVO.from_dict(ptkp_status)
        elif ptkp_status is None:
            ptkp_status = EmployeePTKPStatusVO.create_single()

        bpjs_health = data.get("bpjs_health")
        if isinstance(bpjs_health, dict):
            bpjs_health = EmployeeBPJSEnrollmentVO.from_dict(bpjs_health)
        else:
            bpjs_health = EmployeeBPJSEnrollmentVO(
                membership_number="", bpjs_type=BPJSType.HEALTH, is_active=False
            )

        bpjs_employment = data.get("bpjs_employment")
        if isinstance(bpjs_employment, dict):
            bpjs_employment = EmployeeBPJSEnrollmentVO.from_dict(bpjs_employment)
        else:
            bpjs_employment = EmployeeBPJSEnrollmentVO(
                membership_number="", bpjs_type=BPJSType.EMPLOYMENT, is_active=False
            )

        join_date = data["join_date"]
        if isinstance(join_date, str):
            join_date = date.fromisoformat(join_date)
        resign_date = data.get("resign_date")
        if isinstance(resign_date, str):
            resign_date = date.fromisoformat(resign_date) if resign_date else None
        birth_date = data.get("birth_date")
        if isinstance(birth_date, str):
            birth_date = date.fromisoformat(birth_date) if birth_date else None

        return cls(
            employee_id=UUID(data["employee_id"])
            if isinstance(data["employee_id"], str)
            else data["employee_id"],
            legal_entity_id=UUID(data["legal_entity_id"])
            if isinstance(data["legal_entity_id"], str)
            else data["legal_entity_id"],
            employee_number=data["employee_number"],
            full_name=data["full_name"],
            employee_type=employee_type,
            gender=gender,
            ptkp_status=ptkp_status,
            bpjs_health=bpjs_health,
            bpjs_employment=bpjs_employment,
            basic_salary=Decimal(str(data["basic_salary"])),
            join_date=join_date,
            resign_date=resign_date,
            nick_name=data.get("nick_name"),
            birth_place=data.get("birth_place"),
            birth_date=birth_date,
            tax_id=data.get("tax_id"),
            email=data.get("email"),
            phone=data.get("phone"),
            mobile=data.get("mobile"),
            address=data.get("address"),
            city=data.get("city"),
            province=data.get("province"),
            postal_code=data.get("postal_code"),
            department=data.get("department"),
            position=data.get("position"),
            cost_center=data.get("cost_center"),
            bank_name=data.get("bank_name"),
            bank_account_number=data.get("bank_account_number"),
            bank_account_name=data.get("bank_account_name"),
            currency=data.get("currency", "IDR"),
            status=status,
            created_at=datetime.fromisoformat(data["created_at"])
            if data.get("created_at")
            else datetime.now(UTC),
            updated_at=datetime.fromisoformat(data["updated_at"])
            if data.get("updated_at")
            else datetime.now(UTC),
            created_by=data.get("created_by", "system"),
            updated_by=data.get("updated_by", "system"),
            version=data.get("version", 1),
        )

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    @property
    def age(self) -> int | None:
        if not self.birth_date:
            return None
        return _calculate_age(self.birth_date)

    @property
    def tenure_years(self) -> int:
        years, _ = _calculate_tenure(self.join_date, self.resign_date)
        return years

    @property
    def tenure_days(self) -> int:
        _, days = _calculate_tenure(self.join_date, self.resign_date)
        return days

    @property
    def is_active(self) -> bool:
        return self.status == EmployeeStatus.ACTIVE

    @property
    def full_address(self) -> str | None:
        parts = [
            self.address,
            self.city,
            self.province,
            self.postal_code,
        ]
        # Filter out None and empty strings, then join
        filtered = [p for p in parts if p]
        return ", ".join(filtered) if filtered else None

    # ------------------------------------------------------------------------
    # Core Business Logic
    # ------------------------------------------------------------------------

    def can_process_payroll(self) -> bool:
        """Can this employee be included in payroll processing?"""
        return self.status.can_process_payroll()

    def resign(self, resign_date: date, reason: str, updated_by: str) -> EmployeeEntity:
        """Mark employee as resigned."""
        if self.status == EmployeeStatus.RESIGNED:
            raise ValueError("Employee already resigned")
        if resign_date <= self.join_date:
            raise ValueError(f"Resign date {resign_date} must be after join date {self.join_date}")
        if resign_date > date.today():
            raise ValueError(f"Resign date cannot be in the future: {resign_date}")

        # Terminate BPJS enrollments if active
        new_bpjs_health = (
            self.bpjs_health.terminate(resign_date, reason)
            if self.bpjs_health.is_active
            else self.bpjs_health
        )
        new_bpjs_employment = (
            self.bpjs_employment.terminate(resign_date, reason)
            if self.bpjs_employment.is_active
            else self.bpjs_employment
        )

        return EmployeeEntity(
            employee_id=self.employee_id,
            legal_entity_id=self.legal_entity_id,
            employee_number=self.employee_number,
            full_name=self.full_name,
            employee_type=self.employee_type,
            gender=self.gender,
            ptkp_status=self.ptkp_status,
            bpjs_health=new_bpjs_health,
            bpjs_employment=new_bpjs_employment,
            basic_salary=self.basic_salary,
            join_date=self.join_date,
            resign_date=resign_date,
            nick_name=self.nick_name,
            birth_place=self.birth_place,
            birth_date=self.birth_date,
            tax_id=self.tax_id,
            email=self.email,
            phone=self.phone,
            mobile=self.mobile,
            address=self.address,
            city=self.city,
            province=self.province,
            postal_code=self.postal_code,
            department=self.department,
            position=self.position,
            cost_center=self.cost_center,
            bank_name=self.bank_name,
            bank_account_number=self.bank_account_number,
            bank_account_name=self.bank_account_name,
            currency=self.currency,
            status=EmployeeStatus.RESIGNED,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            updated_by=updated_by,
            version=self.version + 1,
        )

    def terminate(self, termination_date: date, reason: str, updated_by: str) -> EmployeeEntity:
        """Mark employee as terminated (fired)."""
        if self.status == EmployeeStatus.TERMINATED:
            raise ValueError("Employee already terminated")
        if termination_date <= self.join_date:
            raise ValueError(
                f"Termination date {termination_date} must be after join date {self.join_date}"
            )
        if termination_date > date.today():
            raise ValueError(f"Termination date cannot be in the future: {termination_date}")

        new_bpjs_health = (
            self.bpjs_health.terminate(termination_date, reason)
            if self.bpjs_health.is_active
            else self.bpjs_health
        )
        new_bpjs_employment = (
            self.bpjs_employment.terminate(termination_date, reason)
            if self.bpjs_employment.is_active
            else self.bpjs_employment
        )

        return EmployeeEntity(
            employee_id=self.employee_id,
            legal_entity_id=self.legal_entity_id,
            employee_number=self.employee_number,
            full_name=self.full_name,
            employee_type=self.employee_type,
            gender=self.gender,
            ptkp_status=self.ptkp_status,
            bpjs_health=new_bpjs_health,
            bpjs_employment=new_bpjs_employment,
            basic_salary=self.basic_salary,
            join_date=self.join_date,
            resign_date=termination_date,
            nick_name=self.nick_name,
            birth_place=self.birth_place,
            birth_date=self.birth_date,
            tax_id=self.tax_id,
            email=self.email,
            phone=self.phone,
            mobile=self.mobile,
            address=self.address,
            city=self.city,
            province=self.province,
            postal_code=self.postal_code,
            department=self.department,
            position=self.position,
            cost_center=self.cost_center,
            bank_name=self.bank_name,
            bank_account_number=self.bank_account_number,
            bank_account_name=self.bank_account_name,
            currency=self.currency,
            status=EmployeeStatus.TERMINATED,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            updated_by=updated_by,
            version=self.version + 1,
        )

    def reactivate(
        self, reactivation_date: date | None = None, updated_by: str = "system"
    ) -> EmployeeEntity:
        """Reactivate a resigned/terminated employee (e.g., rehire)."""
        if self.status not in (EmployeeStatus.RESIGNED, EmployeeStatus.TERMINATED):
            raise ValueError(f"Cannot reactivate employee with status {self.status.value}")
        if reactivation_date is None:
            reactivation_date = date.today()
        if self.resign_date is not None and reactivation_date <= self.resign_date:
            raise ValueError("Reactivation date must be after resignation/termination date")

        # Reactivate BPJS enrollments? Usually new enrollments needed
        # For simplicity, we set them as inactive and caller must re-enroll
        new_bpjs_health = EmployeeBPJSEnrollmentVO(
            membership_number="", bpjs_type=BPJSType.HEALTH, is_active=False
        )
        new_bpjs_employment = EmployeeBPJSEnrollmentVO(
            membership_number="", bpjs_type=BPJSType.EMPLOYMENT, is_active=False
        )

        return EmployeeEntity(
            employee_id=self.employee_id,
            legal_entity_id=self.legal_entity_id,
            employee_number=self.employee_number,
            full_name=self.full_name,
            employee_type=self.employee_type,
            gender=self.gender,
            ptkp_status=self.ptkp_status,
            bpjs_health=new_bpjs_health,
            bpjs_employment=new_bpjs_employment,
            basic_salary=self.basic_salary,
            join_date=reactivation_date,  # New join date for rehire
            resign_date=None,
            nick_name=self.nick_name,
            birth_place=self.birth_place,
            birth_date=self.birth_date,
            tax_id=self.tax_id,
            email=self.email,
            phone=self.phone,
            mobile=self.mobile,
            address=self.address,
            city=self.city,
            province=self.province,
            postal_code=self.postal_code,
            department=self.department,
            position=self.position,
            cost_center=self.cost_center,
            bank_name=self.bank_name,
            bank_account_number=self.bank_account_number,
            bank_account_name=self.bank_account_name,
            currency=self.currency,
            status=EmployeeStatus.ACTIVE,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            updated_by=updated_by,
            version=self.version + 1,
        )

    def update_ptkp_status(self, new_ptkp: EmployeePTKPStatusVO, updated_by: str) -> EmployeeEntity:
        """Update PTKP status."""
        return EmployeeEntity(
            employee_id=self.employee_id,
            legal_entity_id=self.legal_entity_id,
            employee_number=self.employee_number,
            full_name=self.full_name,
            employee_type=self.employee_type,
            gender=self.gender,
            ptkp_status=new_ptkp,
            bpjs_health=self.bpjs_health,
            bpjs_employment=self.bpjs_employment,
            basic_salary=self.basic_salary,
            join_date=self.join_date,
            resign_date=self.resign_date,
            nick_name=self.nick_name,
            birth_place=self.birth_place,
            birth_date=self.birth_date,
            tax_id=self.tax_id,
            email=self.email,
            phone=self.phone,
            mobile=self.mobile,
            address=self.address,
            city=self.city,
            province=self.province,
            postal_code=self.postal_code,
            department=self.department,
            position=self.position,
            cost_center=self.cost_center,
            bank_name=self.bank_name,
            bank_account_number=self.bank_account_number,
            bank_account_name=self.bank_account_name,
            currency=self.currency,
            status=self.status,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            updated_by=updated_by,
            version=self.version + 1,
        )

    def update_bpjs_health(
        self, bpjs_health: EmployeeBPJSEnrollmentVO, updated_by: str
    ) -> EmployeeEntity:
        """Update BPJS Kesehatan enrollment."""
        return EmployeeEntity(
            employee_id=self.employee_id,
            legal_entity_id=self.legal_entity_id,
            employee_number=self.employee_number,
            full_name=self.full_name,
            employee_type=self.employee_type,
            gender=self.gender,
            ptkp_status=self.ptkp_status,
            bpjs_health=bpjs_health,
            bpjs_employment=self.bpjs_employment,
            basic_salary=self.basic_salary,
            join_date=self.join_date,
            resign_date=self.resign_date,
            nick_name=self.nick_name,
            birth_place=self.birth_place,
            birth_date=self.birth_date,
            tax_id=self.tax_id,
            email=self.email,
            phone=self.phone,
            mobile=self.mobile,
            address=self.address,
            city=self.city,
            province=self.province,
            postal_code=self.postal_code,
            department=self.department,
            position=self.position,
            cost_center=self.cost_center,
            bank_name=self.bank_name,
            bank_account_number=self.bank_account_number,
            bank_account_name=self.bank_account_name,
            currency=self.currency,
            status=self.status,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            updated_by=updated_by,
            version=self.version + 1,
        )

    def update_bpjs_employment(
        self, bpjs_employment: EmployeeBPJSEnrollmentVO, updated_by: str
    ) -> EmployeeEntity:
        """Update BPJS Ketenagakerjaan enrollment."""
        return EmployeeEntity(
            employee_id=self.employee_id,
            legal_entity_id=self.legal_entity_id,
            employee_number=self.employee_number,
            full_name=self.full_name,
            employee_type=self.employee_type,
            gender=self.gender,
            ptkp_status=self.ptkp_status,
            bpjs_health=self.bpjs_health,
            bpjs_employment=bpjs_employment,
            basic_salary=self.basic_salary,
            join_date=self.join_date,
            resign_date=self.resign_date,
            nick_name=self.nick_name,
            birth_place=self.birth_place,
            birth_date=self.birth_date,
            tax_id=self.tax_id,
            email=self.email,
            phone=self.phone,
            mobile=self.mobile,
            address=self.address,
            city=self.city,
            province=self.province,
            postal_code=self.postal_code,
            department=self.department,
            position=self.position,
            cost_center=self.cost_center,
            bank_name=self.bank_name,
            bank_account_number=self.bank_account_number,
            bank_account_name=self.bank_account_name,
            currency=self.currency,
            status=self.status,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            updated_by=updated_by,
            version=self.version + 1,
        )

    def update_salary(
        self, new_salary: Decimal, updated_by: str, effective_date: date | None = None
    ) -> EmployeeEntity:
        """Update basic salary. Effective_date can be stored in notes."""
        if new_salary <= 0:
            raise ValueError(f"Salary must be positive: {new_salary}")
        return EmployeeEntity(
            employee_id=self.employee_id,
            legal_entity_id=self.legal_entity_id,
            employee_number=self.employee_number,
            full_name=self.full_name,
            employee_type=self.employee_type,
            gender=self.gender,
            ptkp_status=self.ptkp_status,
            bpjs_health=self.bpjs_health,
            bpjs_employment=self.bpjs_employment,
            basic_salary=new_salary,
            join_date=self.join_date,
            resign_date=self.resign_date,
            nick_name=self.nick_name,
            birth_place=self.birth_place,
            birth_date=self.birth_date,
            tax_id=self.tax_id,
            email=self.email,
            phone=self.phone,
            mobile=self.mobile,
            address=self.address,
            city=self.city,
            province=self.province,
            postal_code=self.postal_code,
            department=self.department,
            position=self.position,
            cost_center=self.cost_center,
            bank_name=self.bank_name,
            bank_account_number=self.bank_account_number,
            bank_account_name=self.bank_account_name,
            currency=self.currency,
            status=self.status,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            updated_by=updated_by,
            version=self.version + 1,
        )

    def update_department(self, new_department: str | None, updated_by: str) -> EmployeeEntity:
        """Change department."""
        return EmployeeEntity(
            employee_id=self.employee_id,
            legal_entity_id=self.legal_entity_id,
            employee_number=self.employee_number,
            full_name=self.full_name,
            employee_type=self.employee_type,
            gender=self.gender,
            ptkp_status=self.ptkp_status,
            bpjs_health=self.bpjs_health,
            bpjs_employment=self.bpjs_employment,
            basic_salary=self.basic_salary,
            join_date=self.join_date,
            resign_date=self.resign_date,
            nick_name=self.nick_name,
            birth_place=self.birth_place,
            birth_date=self.birth_date,
            tax_id=self.tax_id,
            email=self.email,
            phone=self.phone,
            mobile=self.mobile,
            address=self.address,
            city=self.city,
            province=self.province,
            postal_code=self.postal_code,
            department=new_department,
            position=self.position,
            cost_center=self.cost_center,
            bank_name=self.bank_name,
            bank_account_number=self.bank_account_number,
            bank_account_name=self.bank_account_name,
            currency=self.currency,
            status=self.status,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            updated_by=updated_by,
            version=self.version + 1,
        )

    def update_position(self, new_position: str | None, updated_by: str) -> EmployeeEntity:
        """Change position/job title."""
        return EmployeeEntity(
            employee_id=self.employee_id,
            legal_entity_id=self.legal_entity_id,
            employee_number=self.employee_number,
            full_name=self.full_name,
            employee_type=self.employee_type,
            gender=self.gender,
            ptkp_status=self.ptkp_status,
            bpjs_health=self.bpjs_health,
            bpjs_employment=self.bpjs_employment,
            basic_salary=self.basic_salary,
            join_date=self.join_date,
            resign_date=self.resign_date,
            nick_name=self.nick_name,
            birth_place=self.birth_place,
            birth_date=self.birth_date,
            tax_id=self.tax_id,
            email=self.email,
            phone=self.phone,
            mobile=self.mobile,
            address=self.address,
            city=self.city,
            province=self.province,
            postal_code=self.postal_code,
            department=self.department,
            position=new_position,
            cost_center=self.cost_center,
            bank_name=self.bank_name,
            bank_account_number=self.bank_account_number,
            bank_account_name=self.bank_account_name,
            currency=self.currency,
            status=self.status,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            updated_by=updated_by,
            version=self.version + 1,
        )

    # ------------------------------------------------------------------------
    # Validation Helpers
    # ------------------------------------------------------------------------

    def validate_can_modify(self, user_role: str = "user") -> tuple[bool, str]:
        """Check if employee can be modified."""
        if self.status in (EmployeeStatus.RESIGNED, EmployeeStatus.TERMINATED):
            return False, f"Cannot modify employee with status {self.status.display_name()}"
        return True, ""

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def to_dict(
        self, include_ptkp_details: bool = True, include_bpjs_details: bool = True
    ) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        result: dict[str, Any] = {
            "employee_id": str(self.employee_id),
            "legal_entity_id": str(self.legal_entity_id),
            "employee_number": self.employee_number,
            "full_name": self.full_name,
            "employee_type": self.employee_type.value,
            "employee_type_display": self.employee_type.display_name(),
            "gender": self.gender.value,
            "gender_display": self.gender.display_name(),
            "basic_salary": str(self.basic_salary),
            "currency": self.currency,
            "join_date": self.join_date.isoformat(),
            "resign_date": self.resign_date.isoformat() if self.resign_date else None,
            "status": self.status.value,
            "status_display": self.status.display_name(),
            "age": self.age,
            "tenure_years": self.tenure_years,
            "tenure_days": self.tenure_days,
            "is_active": self.is_active,
            "can_process_payroll": self.can_process_payroll(),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
        }
        if include_ptkp_details:
            result["ptkp_status"] = self.ptkp_status.to_dict()
        if include_bpjs_details:
            result["bpjs_health"] = self.bpjs_health.to_dict()
            result["bpjs_employment"] = self.bpjs_employment.to_dict()
        optional_fields = [
            "nick_name",
            "birth_place",
            "birth_date",
            "tax_id",
            "email",
            "phone",
            "mobile",
            "address",
            "city",
            "province",
            "postal_code",
            "department",
            "position",
            "cost_center",
            "bank_name",
            "bank_account_number",
            "bank_account_name",
            "created_by",
            "updated_by",
        ]
        for field_name in optional_fields:
            value = getattr(self, field_name)
            if value is not None:
                if isinstance(value, date):
                    result[field_name] = value.isoformat()
                else:
                    result[field_name] = value
        return result

    def to_db_record(self) -> dict[str, Any]:
        """Convert to database-friendly format."""
        return {
            "employee_id": self.employee_id,
            "legal_entity_id": self.legal_entity_id,
            "employee_number": self.employee_number,
            "full_name": self.full_name,
            "employee_type": self.employee_type.value,
            "gender": self.gender.value,
            "ptkp_marital_status": self.ptkp_status.marital_status.value,
            "ptkp_dependents": self.ptkp_status.dependents,
            "ptkp_spouse_combined": self.ptkp_status.spouse_income_combined,
            "bpjs_health_membership": self.bpjs_health.membership_number,
            "bpjs_health_active": self.bpjs_health.is_active,
            "bpjs_health_class": self.bpjs_health.health_class.value
            if self.bpjs_health.health_class
            else None,
            "bpjs_employment_membership": self.bpjs_employment.membership_number,
            "bpjs_employment_active": self.bpjs_employment.is_active,
            "bpjs_employment_programs": ",".join(
                [p.value for p in self.bpjs_employment.employment_programs]
            )
            if self.bpjs_employment.employment_programs
            else None,
            "basic_salary": self.basic_salary,
            "currency": self.currency,
            "join_date": self.join_date,
            "resign_date": self.resign_date,
            "nick_name": self.nick_name,
            "birth_place": self.birth_place,
            "birth_date": self.birth_date,
            "tax_id": self.tax_id,
            "email": self.email,
            "phone": self.phone,
            "mobile": self.mobile,
            "address": self.address,
            "city": self.city,
            "province": self.province,
            "postal_code": self.postal_code,
            "department": self.department,
            "position": self.position,
            "cost_center": self.cost_center,
            "bank_name": self.bank_name,
            "bank_account_number": self.bank_account_number,
            "bank_account_name": self.bank_account_name,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "version": self.version,
        }

    # ------------------------------------------------------------------------
    # Dunder Methods
    # ------------------------------------------------------------------------

    def __str__(self) -> str:
        return f"{self.employee_number} - {self.full_name}"

    def __repr__(self) -> str:
        return f"EmployeeEntity({self.employee_number}, status={self.status.value})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, EmployeeEntity):
            return False
        return self.employee_id == other.employee_id

    def __hash__(self) -> int:
        return hash(self.employee_id)


# ============================================================================
# Repository Protocol
# ============================================================================


class EmployeeEntityRepository:
    """Repository protocol for EmployeeEntity."""

    async def get_by_id(self, employee_id: UUID, legal_entity_id: UUID) -> EmployeeEntity | None:
        raise NotImplementedError

    async def get_by_number(
        self, employee_number: str, legal_entity_id: UUID
    ) -> EmployeeEntity | None:
        raise NotImplementedError

    async def get_by_email(self, email: str, legal_entity_id: UUID) -> EmployeeEntity | None:
        raise NotImplementedError

    async def get_by_tax_id(self, tax_id: str, legal_entity_id: UUID) -> EmployeeEntity | None:
        raise NotImplementedError

    async def list_by_department(
        self, department: str, legal_entity_id: UUID, limit: int = 100
    ) -> list[EmployeeEntity]:
        raise NotImplementedError

    async def list_by_status(
        self, status: EmployeeStatus, legal_entity_id: UUID, limit: int = 100
    ) -> list[EmployeeEntity]:
        raise NotImplementedError

    async def save(self, employee: EmployeeEntity, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, employee_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "EmployeeEntity",
    "EmployeeEntityRepository",
    "EmployeeStatus",
    "EmployeeType",
    "Gender",
]
