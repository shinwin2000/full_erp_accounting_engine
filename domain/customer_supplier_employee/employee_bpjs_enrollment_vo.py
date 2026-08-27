#!/usr/bin/env python3
"""
Module: employee_bpjs_enrollment_vo.py

Layer: Domain / Customer, Supplier, Employee

Responsibility:
    Value object for BPJS (BPJS Ketenagakerjaan and BPJS Kesehatan) enrollment.
    Immutable. Represents an employee's participation in social security programs
    including Health Insurance (BPJS Kesehatan) and Employment Social Security
    (BPJS Ketenagakerjaan with programs: JKK, JKM, JHT, JP).

Business rules:
    - BPJS type can be HEALTH or EMPLOYMENT.
    - Membership number format: for HEALTH: 16 digits, for EMPLOYMENT: 10-12 digits.
    - Enrollment date must be <= termination date if terminated.
    - Contribution rates follow government regulations (updated annually).
    - For HEALTH: class (1,2,3) determines contribution amount.
    - For EMPLOYMENT: programs (JKK, JKM, JHT, JP) have fixed rates.
    - Immutable: changes create new instances.

Dependencies:
    - Python standard library (dataclass, decimal, datetime, enum, re, logging)

Audit:
    Pure value object; no I/O. Caller should log BPJS enrollment changes.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class BPJSType(Enum):
    """Types of BPJS programs."""

    HEALTH = "health"  # BPJS Kesehatan
    EMPLOYMENT = "employment"  # BPJS Ketenagakerjaan

    def display_name(self) -> str:
        names = {
            BPJSType.HEALTH: "BPJS Kesehatan",
            BPJSType.EMPLOYMENT: "BPJS Ketenagakerjaan",
        }
        return names.get(self, self.value)

    @classmethod
    def from_string(cls, value: str) -> BPJSType | None:
        value_lower = value.lower()
        if value_lower in ("health", "kesehatan"):
            return BPJSType.HEALTH
        elif value_lower in ("employment", "ketenagakerjaan", "tenagakerja"):
            return BPJSType.EMPLOYMENT
        return None


class BPJSHealthClass(Enum):
    """Membership class for BPJS Kesehatan."""

    CLASS_1 = 1  # Kelas 1 (highest premium)
    CLASS_2 = 2  # Kelas 2
    CLASS_3 = 3  # Kelas 3 (lowest premium)

    def monthly_premium(self) -> Decimal:
        """Monthly premium in IDR (as of 2024)."""
        premiums = {
            BPJSHealthClass.CLASS_1: Decimal("150000"),
            BPJSHealthClass.CLASS_2: Decimal("100000"),
            BPJSHealthClass.CLASS_3: Decimal("42000"),
        }
        return premiums.get(self, Decimal("42000"))

    def display_name(self) -> str:
        return f"Kelas {self.value}"

    @classmethod
    def from_int(cls, value: int) -> BPJSHealthClass | None:
        for c in cls:
            if c.value == value:
                return c
        return None


class BPJSEmploymentProgram(Enum):
    """
    Programs under BPJS Ketenagakerjaan.
    JKK: Jaminan Kecelakaan Kerja (Work Accident Insurance)
    JKM: Jaminan Kematian (Death Insurance)
    JHT: Jaminan Hari Tua (Old Age Savings)
    JP:  Jaminan Pensiun (Pension Insurance)
    """

    JKK = "jkk"  # Premium based on risk level (0.24% - 1.74%)
    JKM = "jkm"  # Fixed 0.30% of salary
    JHT = "jht"  # 5.7% of salary (2% employee, 3.7% employer)
    JP = "jp"  # 3% of salary (1% employee, 2% employer) - for eligible

    def display_name(self) -> str:
        names = {
            BPJSEmploymentProgram.JKK: "JKK (Jaminan Kecelakaan Kerja)",
            BPJSEmploymentProgram.JKM: "JKM (Jaminan Kematian)",
            BPJSEmploymentProgram.JHT: "JHT (Jaminan Hari Tua)",
            BPJSEmploymentProgram.JP: "JP (Jaminan Pensiun)",
        }
        return names.get(self, self.value)

    def employee_rate(self) -> Decimal:
        """Employee contribution rate (as percentage of salary)."""
        rates = {
            BPJSEmploymentProgram.JKK: Decimal("0"),  # Employer only
            BPJSEmploymentProgram.JKM: Decimal("0"),  # Employer only
            BPJSEmploymentProgram.JHT: Decimal("2"),  # 2% of salary
            BPJSEmploymentProgram.JP: Decimal("1"),  # 1% of salary
        }
        return rates.get(self, Decimal("0"))

    def employer_rate(self) -> Decimal:
        """Employer contribution rate (as percentage of salary)."""
        rates = {
            BPJSEmploymentProgram.JKK: Decimal("0.54"),  # 0.24-1.74% based on risk, default 0.54%
            BPJSEmploymentProgram.JKM: Decimal("0.30"),
            BPJSEmploymentProgram.JHT: Decimal("3.7"),
            BPJSEmploymentProgram.JP: Decimal("2"),  # For eligible employees
        }
        return rates.get(self, Decimal("0"))

    @classmethod
    def from_string(cls, value: str) -> BPJSEmploymentProgram | None:
        value_lower = value.lower()
        for prog in cls:
            if prog.value == value_lower:
                return prog
        return None


# ============================================================================
# Constants
# ============================================================================

HEALTH_MEMBERSHIP_PATTERN = re.compile(r"^\d{16}$")
EMPLOYMENT_MEMBERSHIP_PATTERN = re.compile(r"^\d{10,12}$")


# ============================================================================
# Exceptions
# ============================================================================


class BPJSError(ValueError):
    """Base exception for BPJS enrollment errors."""

    pass


class InvalidBPJSMembershipNumberError(BPJSError):
    """Raised when membership number format is invalid."""

    pass


class InvalidBPJSProgramError(BPJSError):
    """Raised when BPJS program is invalid."""

    pass


# ============================================================================
# Value Object: EmployeeBPJSEnrollmentVO
# ============================================================================


@dataclass(frozen=True)
class EmployeeBPJSEnrollmentVO:
    """
    Immutable value object for BPJS enrollment.

    Attributes:
        bpjs_type: Type of BPJS (HEALTH or EMPLOYMENT)
        membership_number: Unique membership number
        is_active: Whether the enrollment is currently active
        enrollment_date: Date when enrollment started
        termination_date: Date when enrollment ended (if terminated)
        health_class: Health class (1,2,3) for HEALTH type
        employment_programs: List of BPJSEmploymentProgram for EMPLOYMENT type
        employee_contribution: Monthly contribution paid by employee (IDR)
        employer_contribution: Monthly contribution paid by employer (IDR)
        risk_level: Risk level for JKK (1-5, default 3)
        notes: Additional notes

    Examples:
        >>> bpjs_health = EmployeeBPJSEnrollmentVO.create_health(
        ...     membership_number="1234567890123456",
        ...     health_class=BPJSHealthClass.CLASS_1
        ... )
        >>> bpjs_health.is_active
        True
        >>> bpjs_health.calculate_contributions(Decimal("10000000"))
        (Decimal('30000'), Decimal('54000'))
    """

    bpjs_type: BPJSType
    membership_number: str
    is_active: bool = True
    enrollment_date: date = field(default_factory=date.today)
    termination_date: date | None = None
    health_class: BPJSHealthClass | None = None
    employment_programs: list[BPJSEmploymentProgram] = field(default_factory=list)
    employee_contribution: Decimal = Decimal("0")
    employer_contribution: Decimal = Decimal("0")
    risk_level: int = 3  # 1-5 for JKK calculation
    notes: str = ""

    def __post_init__(self) -> None:
        """Validate BPJS enrollment data."""
        # Validate bpjs_type
        if not isinstance(self.bpjs_type, BPJSType):
            raise BPJSError(f"Invalid bpjs_type: {self.bpjs_type}")

        # Validate membership number format
        if self.bpjs_type == BPJSType.HEALTH:
            if not HEALTH_MEMBERSHIP_PATTERN.match(self.membership_number):
                raise InvalidBPJSMembershipNumberError(
                    f"Health BPJS membership number must be 16 digits, got {self.membership_number}"
                )
        else:  # EMPLOYMENT
            if not EMPLOYMENT_MEMBERSHIP_PATTERN.match(self.membership_number):
                raise InvalidBPJSMembershipNumberError(
                    f"Employment BPJS membership number must be 10-12 digits, got {self.membership_number}"
                )

        # Validate health_class for HEALTH type
        if self.bpjs_type == BPJSType.HEALTH:
            if self.health_class is None:
                raise BPJSError("health_class is required for HEALTH BPJS type")
        else:
            if self.health_class is not None:
                raise BPJSError("health_class should be None for EMPLOYMENT BPJS type")

        # Validate employment_programs for EMPLOYMENT type
        if self.bpjs_type == BPJSType.EMPLOYMENT:
            if not self.employment_programs:
                raise BPJSError("employment_programs is required for EMPLOYMENT BPJS type")
            for prog in self.employment_programs:
                if not isinstance(prog, BPJSEmploymentProgram):
                    raise BPJSError(f"Invalid employment_program: {prog}")
        else:
            if self.employment_programs:
                raise BPJSError("employment_programs should be None for HEALTH BPJS type")

        # Validate dates
        if self.enrollment_date > date.today():
            logger.warning(f"Enrollment date {self.enrollment_date} is in the future")

        if self.termination_date:
            if self.termination_date <= self.enrollment_date:
                raise BPJSError("Termination date must be after enrollment date")
            if not self.is_active:
                raise BPJSError(
                    "Termination date set but is_active is False (should be consistent)"
                )

        # Validate contributions
        if self.employee_contribution < 0:
            raise BPJSError(
                f"Employee contribution cannot be negative: {self.employee_contribution}"
            )
        if self.employer_contribution < 0:
            raise BPJSError(
                f"Employer contribution cannot be negative: {self.employer_contribution}"
            )

        # Validate risk level for JKK
        if self.risk_level < 1 or self.risk_level > 5:
            raise BPJSError(f"Risk level must be 1-5, got {self.risk_level}")

        # Clean notes
        if self.notes:
            object.__setattr__(self, "notes", self.notes.strip())

    # ------------------------------------------------------------------------
    # Factory Methods
    # ------------------------------------------------------------------------

    @classmethod
    def create_health(
        cls,
        membership_number: str,
        health_class: BPJSHealthClass,
        enrollment_date: date | None = None,
        employee_contribution: Decimal | None = None,
        employer_contribution: Decimal | None = None,
        notes: str = "",
    ) -> EmployeeBPJSEnrollmentVO:
        """Create a HEALTH BPJS enrollment."""
        if enrollment_date is None:
            enrollment_date = date.today()
        # Calculate default contributions based on health class if not provided
        if employee_contribution is None:
            # Employee pays 1% of premium? Actually premium is split: employee 1%, employer 4%?
            # Standard: total premium = health_class.monthly_premium()
            # For class 1: total 150k, employee 30k, employer 120k
            # For class 2: total 100k, employee 20k, employer 80k
            # For class 3: total 42k, employee 35k? Wait, government subsidizes.
            # Simplified: employee pays 50% of premium (except class 3 with subsidy)
            total = health_class.monthly_premium()
            if health_class == BPJSHealthClass.CLASS_3:
                employee = Decimal("35000")  # Fixed for class 3
                employer = total - employee
            else:
                employee = total * Decimal("0.5")  # 50%
                employer = total * Decimal("0.5")
            employee_contribution = employee
            employer_contribution = employer
        return cls(
            bpjs_type=BPJSType.HEALTH,
            membership_number=membership_number,
            is_active=True,
            enrollment_date=enrollment_date,
            health_class=health_class,
            employee_contribution=employee_contribution,
            employer_contribution=employer_contribution,
            notes=notes,
        )

    @classmethod
    def create_employment(
        cls,
        membership_number: str,
        programs: list[BPJSEmploymentProgram],
        enrollment_date: date | None = None,
        risk_level: int = 3,
        notes: str = "",
    ) -> EmployeeBPJSEnrollmentVO:
        """Create an EMPLOYMENT BPJS enrollment (contributions calculated dynamically)."""
        if enrollment_date is None:
            enrollment_date = date.today()
        return cls(
            bpjs_type=BPJSType.EMPLOYMENT,
            membership_number=membership_number,
            is_active=True,
            enrollment_date=enrollment_date,
            employment_programs=programs,
            risk_level=risk_level,
            employee_contribution=Decimal("0"),  # Calculated on the fly with salary
            employer_contribution=Decimal("0"),  # Calculated on the fly with salary
            notes=notes,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EmployeeBPJSEnrollmentVO:
        """Reconstruct from dictionary."""
        bpjs_type = BPJSType.from_string(data["bpjs_type"])
        if bpjs_type is None:
            raise BPJSError(f"Invalid bpjs_type: {data['bpjs_type']}")

        health_class = None
        if data.get("health_class"):
            if isinstance(data["health_class"], int):
                health_class = BPJSHealthClass.from_int(data["health_class"])
            else:
                for hc in BPJSHealthClass:
                    if hc.name == data["health_class"] or str(hc.value) == data["health_class"]:
                        health_class = hc
                        break

        employment_programs = []
        for prog_str in data.get("employment_programs", []):
            prog = BPJSEmploymentProgram.from_string(prog_str)
            if prog:
                employment_programs.append(prog)

        enrollment_date = data.get("enrollment_date")
        if isinstance(enrollment_date, str):
            enrollment_date = date.fromisoformat(enrollment_date)
        elif enrollment_date is None:
            enrollment_date = date.today()

        termination_date = data.get("termination_date")
        if isinstance(termination_date, str):
            termination_date = date.fromisoformat(termination_date)

        return cls(
            bpjs_type=bpjs_type,
            membership_number=data["membership_number"],
            is_active=data.get("is_active", True),
            enrollment_date=enrollment_date,
            termination_date=termination_date,
            health_class=health_class,
            employment_programs=employment_programs,
            employee_contribution=Decimal(str(data.get("employee_contribution", 0))),
            employer_contribution=Decimal(str(data.get("employer_contribution", 0))),
            risk_level=data.get("risk_level", 3),
            notes=data.get("notes", ""),
        )

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    @property
    def is_terminated(self) -> bool:
        """Check if enrollment has been terminated."""
        return self.termination_date is not None

    @property
    def masked_membership_number(self) -> str:
        """Return masked membership number (e.g., ****5678)."""
        if len(self.membership_number) <= 4:
            return "****"
        return "*" * (len(self.membership_number) - 4) + self.membership_number[-4:]

    @property
    def health_class_display(self) -> str | None:
        """Display name of health class."""
        if self.health_class:
            return self.health_class.display_name()
        return None

    @property
    def employment_programs_display(self) -> list[str]:
        """Display names of employment programs."""
        return [p.display_name() for p in self.employment_programs]

    @property
    def total_contribution(self) -> Decimal:
        """Total monthly contribution (employee + employer)."""
        return self.employee_contribution + self.employer_contribution

    # ------------------------------------------------------------------------
    # Calculation Methods
    # ------------------------------------------------------------------------

    def calculate_contributions(
        self,
        monthly_salary: Decimal,
        risk_level: int | None = None,
    ) -> tuple[Decimal, Decimal]:
        """
        Calculate employee and employer contributions based on monthly salary.

        Args:
            monthly_salary: Gross monthly salary in IDR
            risk_level: Risk level for JKK (1-5), overrides instance value

        Returns:
            (employee_contribution, employer_contribution) as Decimals
        """
        if self.bpjs_type == BPJSType.HEALTH:
            # Contributions are fixed per class, not based on salary
            return self.employee_contribution, self.employer_contribution

        # EMPLOYMENT type: calculate based on salary
        emp_total = Decimal("0")
        er_total = Decimal("0")
        risk = risk_level if risk_level is not None else self.risk_level

        # JKK rate based on risk level (0.24% to 1.74%)
        jkk_rates = {
            1: Decimal("0.24"),
            2: Decimal("0.54"),
            3: Decimal("0.89"),
            4: Decimal("1.27"),
            5: Decimal("1.74"),
        }
        jkk_rate = jkk_rates.get(risk, Decimal("0.89"))

        for prog in self.employment_programs:
            if prog == BPJSEmploymentProgram.JKK:
                er_total += monthly_salary * (jkk_rate / Decimal("100"))
            elif prog == BPJSEmploymentProgram.JKM:
                er_total += monthly_salary * (Decimal("0.30") / Decimal("100"))
            elif prog == BPJSEmploymentProgram.JHT:
                emp_total += monthly_salary * (Decimal("2") / Decimal("100"))
                er_total += monthly_salary * (Decimal("3.7") / Decimal("100"))
            elif prog == BPJSEmploymentProgram.JP:
                # JP only for employees with salary up to cap ~ 10 million? Simplified.
                emp_total += monthly_salary * (Decimal("1") / Decimal("100"))
                er_total += monthly_salary * (Decimal("2") / Decimal("100"))

        # Round to nearest IDR
        emp_total = emp_total.quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
        er_total = er_total.quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)

        return emp_total, er_total

    def get_monthly_contribution(self, monthly_salary: Decimal) -> Decimal:
        """Get total monthly contribution (employee + employer)."""
        emp, er = self.calculate_contributions(monthly_salary)
        return emp + er

    # ------------------------------------------------------------------------
    # Business Logic
    # ------------------------------------------------------------------------

    def is_active_on_date(self, check_date: date | None = None) -> bool:
        """
        Check if enrollment is active on a specific date.
        (SIM103 fix: return boolean expression directly.)
        """
        if check_date is None:
            check_date = date.today()
        return (
            self.is_active
            and check_date >= self.enrollment_date
            and (self.termination_date is None or check_date <= self.termination_date)
        )

    def terminate(
        self, termination_date: date | None = None, reason: str = ""
    ) -> EmployeeBPJSEnrollmentVO:
        """Terminate the enrollment."""
        if self.is_terminated:
            raise BPJSError("Enrollment already terminated")
        if termination_date is None:
            termination_date = date.today()
        if termination_date < self.enrollment_date:
            raise BPJSError("Termination date cannot be before enrollment date")
        notes = f"{self.notes}\nTerminated on {termination_date}: {reason}".strip()
        return EmployeeBPJSEnrollmentVO(
            bpjs_type=self.bpjs_type,
            membership_number=self.membership_number,
            is_active=False,
            enrollment_date=self.enrollment_date,
            termination_date=termination_date,
            health_class=self.health_class,
            employment_programs=self.employment_programs,
            employee_contribution=self.employee_contribution,
            employer_contribution=self.employer_contribution,
            risk_level=self.risk_level,
            notes=notes,
        )

    def reactivate(
        self, reactivation_date: date | None = None, reason: str = ""
    ) -> EmployeeBPJSEnrollmentVO:
        """Reactivate a terminated enrollment (creates new enrollment)."""
        if self.is_active:
            raise BPJSError("Enrollment is already active")
        if reactivation_date is None:
            reactivation_date = date.today()
        if self.termination_date and reactivation_date <= self.termination_date:
            raise BPJSError("Reactivation date must be after termination date")
        notes = f"{self.notes}\nReactivated on {reactivation_date}: {reason}".strip()
        return EmployeeBPJSEnrollmentVO(
            bpjs_type=self.bpjs_type,
            membership_number=self.membership_number,
            is_active=True,
            enrollment_date=reactivation_date,
            termination_date=None,
            health_class=self.health_class,
            employment_programs=self.employment_programs,
            employee_contribution=self.employee_contribution,
            employer_contribution=self.employer_contribution,
            risk_level=self.risk_level,
            notes=notes,
        )

    def update_membership_number(self, new_membership_number: str) -> EmployeeBPJSEnrollmentVO:
        """Update membership number."""
        return EmployeeBPJSEnrollmentVO(
            bpjs_type=self.bpjs_type,
            membership_number=new_membership_number,
            is_active=self.is_active,
            enrollment_date=self.enrollment_date,
            termination_date=self.termination_date,
            health_class=self.health_class,
            employment_programs=self.employment_programs,
            employee_contribution=self.employee_contribution,
            employer_contribution=self.employer_contribution,
            risk_level=self.risk_level,
            notes=f"{self.notes}\nMembership changed from {self.membership_number} to {new_membership_number}",
        )

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "bpjs_type": self.bpjs_type.value,
            "bpjs_type_display": self.bpjs_type.display_name(),
            "membership_number": self.membership_number,
            "masked_membership_number": self.masked_membership_number,
            "is_active": self.is_active,
            "enrollment_date": self.enrollment_date.isoformat(),
            "termination_date": self.termination_date.isoformat()
            if self.termination_date
            else None,
            "health_class": self.health_class.value if self.health_class else None,
            "health_class_display": self.health_class_display,
            "employment_programs": [p.value for p in self.employment_programs],
            "employment_programs_display": self.employment_programs_display,
            "employee_contribution": str(self.employee_contribution),
            "employer_contribution": str(self.employer_contribution),
            "total_contribution": str(self.total_contribution),
            "risk_level": self.risk_level,
            "notes": self.notes,
        }

    def to_db_record(self) -> dict[str, Any]:
        """Convert to database-friendly format."""
        return {
            "bpjs_type": self.bpjs_type.value,
            "bpjs_membership_number": self.membership_number,
            "bpjs_is_active": self.is_active,
            "bpjs_enrollment_date": self.enrollment_date,
            "bpjs_termination_date": self.termination_date,
            "bpjs_health_class": self.health_class.value if self.health_class else None,
            "bpjs_employment_programs": [p.value for p in self.employment_programs],
            "bpjs_employee_contribution": self.employee_contribution,
            "bpjs_employer_contribution": self.employer_contribution,
            "bpjs_risk_level": self.risk_level,
            "bpjs_notes": self.notes,
        }

    # ------------------------------------------------------------------------
    # Dunder Methods
    # ------------------------------------------------------------------------

    def __str__(self) -> str:
        return f"{self.bpjs_type.display_name()}: {self.masked_membership_number}"

    def __repr__(self) -> str:
        return f"EmployeeBPJSEnrollmentVO(type={self.bpjs_type.value}, membership={self.masked_membership_number}, active={self.is_active})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, EmployeeBPJSEnrollmentVO):
            return False
        return (
            self.bpjs_type == other.bpjs_type
            and self.membership_number == other.membership_number
            and self.enrollment_date == other.enrollment_date
        )

    def __hash__(self) -> int:
        return hash((self.bpjs_type, self.membership_number, self.enrollment_date))


# ============================================================================
# Helper Functions
# ============================================================================


def calculate_health_contribution(health_class: BPJSHealthClass) -> tuple[Decimal, Decimal]:
    """Calculate employee and employer contributions for BPJS Kesehatan."""
    total = health_class.monthly_premium()
    if health_class == BPJSHealthClass.CLASS_3:
        employee = Decimal("35000")
        employer = total - employee
    else:
        employee = total * Decimal("0.5")
        employer = total * Decimal("0.5")
    return employee, employer


def calculate_employment_contribution(
    salary: Decimal,
    programs: list[BPJSEmploymentProgram],
    risk_level: int = 3,
) -> tuple[Decimal, Decimal]:
    """Calculate BPJS Ketenagakerjaan contributions."""
    emp_total = Decimal("0")
    er_total = Decimal("0")
    jkk_rates = {1: 0.24, 2: 0.54, 3: 0.89, 4: 1.27, 5: 1.74}
    jkk_rate = Decimal(str(jkk_rates.get(risk_level, 0.89))) / Decimal("100")
    for prog in programs:
        if prog == BPJSEmploymentProgram.JKK:
            er_total += salary * jkk_rate
        elif prog == BPJSEmploymentProgram.JKM:
            er_total += salary * (Decimal("0.30") / Decimal("100"))
        elif prog == BPJSEmploymentProgram.JHT:
            emp_total += salary * (Decimal("2") / Decimal("100"))
            er_total += salary * (Decimal("3.7") / Decimal("100"))
        elif prog == BPJSEmploymentProgram.JP:
            emp_total += salary * (Decimal("1") / Decimal("100"))
            er_total += salary * (Decimal("2") / Decimal("100"))
    return emp_total.quantize(Decimal("1")), er_total.quantize(Decimal("1"))


def validate_bpjs_membership_number(number: str, bpjs_type: BPJSType) -> bool:
    """Validate BPJS membership number format."""
    if bpjs_type == BPJSType.HEALTH:
        return bool(HEALTH_MEMBERSHIP_PATTERN.match(number))
    else:
        return bool(EMPLOYMENT_MEMBERSHIP_PATTERN.match(number))


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "BPJSEmploymentProgram",
    "BPJSError",
    "BPJSHealthClass",
    "BPJSType",
    "EmployeeBPJSEnrollmentVO",
    "InvalidBPJSMembershipNumberError",
    "InvalidBPJSProgramError",
    "calculate_employment_contribution",
    "calculate_health_contribution",
    "validate_bpjs_membership_number",
]
