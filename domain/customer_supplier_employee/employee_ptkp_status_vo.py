#!/usr/bin/env python3
"""
Module: employee_ptkp_status_vo.py

Layer: Domain / Customer, Supplier, Employee

Responsibility:
    Value object for PTKP (Penghasilan Tidak Kena Pajak) status of an employee.
    Immutable. Used for calculating PPh 21 (income tax) for employees.

Business rules:
    - PTKP status is based on marital status and number of dependents (0-3).
    - Status codes: TK/0, TK/1, TK/2, TK/3, K/0, K/1, K/2, K/3, KB/0, KB/1, KB/2, KB/3.
    - TK = Tidak Kawin (Single), K = Kawin (Married), KB = Kawin dengan penghasilan digabung.
    - Dependents (tanggungan) max 3.
    - PTKP amount for tax year (updated annually).
    - Provides calculation for monthly and annual PTKP.
    - Supports validation and status transitions.

Dependencies:
    - Python standard library (dataclass, enum, decimal, datetime)

Audit:
    Pure value object; no I/O. Caller should log PTKP changes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class MaritalStatus(Enum):
    """Marital status for PTKP determination."""

    SINGLE = "TK"  # Tidak Kawin
    MARRIED = "K"  # Kawin
    MARRIED_COMBINED = "KB"  # Kawin, penghasilan digabung

    def display_name(self) -> str:
        names = {
            MaritalStatus.SINGLE: "Tidak Kawin",
            MaritalStatus.MARRIED: "Kawin",
            MaritalStatus.MARRIED_COMBINED: "Kawin (Penghasilan Digabung)",
        }
        return names.get(self, self.value)

    @classmethod
    def from_string(cls, value: str) -> MaritalStatus | None:
        value_lower = value.lower()
        if value_lower in ("tk", "single", "tidak kawin"):
            return MaritalStatus.SINGLE
        elif value_lower in ("k", "married", "kawin"):
            return MaritalStatus.MARRIED
        elif value_lower in ("kb", "combined", "digabung"):
            return MaritalStatus.MARRIED_COMBINED
        return None


class PTKPCategory(Enum):
    """PTKP category codes."""

    TK0 = "TK/0"
    TK1 = "TK/1"
    TK2 = "TK/2"
    TK3 = "TK/3"
    K0 = "K/0"
    K1 = "K/1"
    K2 = "K/2"
    K3 = "K/3"
    KB0 = "KB/0"
    KB1 = "KB/1"
    KB2 = "KB/2"
    KB3 = "KB/3"

    def get_marital_status(self) -> MaritalStatus:
        mapping = {
            PTKPCategory.TK0: MaritalStatus.SINGLE,
            PTKPCategory.TK1: MaritalStatus.SINGLE,
            PTKPCategory.TK2: MaritalStatus.SINGLE,
            PTKPCategory.TK3: MaritalStatus.SINGLE,
            PTKPCategory.K0: MaritalStatus.MARRIED,
            PTKPCategory.K1: MaritalStatus.MARRIED,
            PTKPCategory.K2: MaritalStatus.MARRIED,
            PTKPCategory.K3: MaritalStatus.MARRIED,
            PTKPCategory.KB0: MaritalStatus.MARRIED_COMBINED,
            PTKPCategory.KB1: MaritalStatus.MARRIED_COMBINED,
            PTKPCategory.KB2: MaritalStatus.MARRIED_COMBINED,
            PTKPCategory.KB3: MaritalStatus.MARRIED_COMBINED,
        }
        return mapping.get(self, MaritalStatus.SINGLE)

    def get_dependents(self) -> int:
        mapping = {
            PTKPCategory.TK0: 0,
            PTKPCategory.K0: 0,
            PTKPCategory.KB0: 0,
            PTKPCategory.TK1: 1,
            PTKPCategory.K1: 1,
            PTKPCategory.KB1: 1,
            PTKPCategory.TK2: 2,
            PTKPCategory.K2: 2,
            PTKPCategory.KB2: 2,
            PTKPCategory.TK3: 3,
            PTKPCategory.K3: 3,
            PTKPCategory.KB3: 3,
        }
        return mapping.get(self, 0)

    def display_name(self) -> str:
        names = {
            PTKPCategory.TK0: "TK/0 (Tidak Kawin, 0 tanggungan)",
            PTKPCategory.TK1: "TK/1 (Tidak Kawin, 1 tanggungan)",
            PTKPCategory.TK2: "TK/2 (Tidak Kawin, 2 tanggungan)",
            PTKPCategory.TK3: "TK/3 (Tidak Kawin, 3 tanggungan)",
            PTKPCategory.K0: "K/0 (Kawin, 0 tanggungan)",
            PTKPCategory.K1: "K/1 (Kawin, 1 tanggungan)",
            PTKPCategory.K2: "K/2 (Kawin, 2 tanggungan)",
            PTKPCategory.K3: "K/3 (Kawin, 3 tanggungan)",
            PTKPCategory.KB0: "KB/0 (Kawin digabung, 0 tanggungan)",
            PTKPCategory.KB1: "KB/1 (Kawin digabung, 1 tanggungan)",
            PTKPCategory.KB2: "KB/2 (Kawin digabung, 2 tanggungan)",
            PTKPCategory.KB3: "KB/3 (Kawin digabung, 3 tanggungan)",
        }
        return names.get(self, self.value)

    @classmethod
    def from_marital_and_dependents(cls, marital: MaritalStatus, dependents: int) -> PTKPCategory:
        if dependents < 0 or dependents > 3:
            raise ValueError(f"Dependents must be 0-3, got {dependents}")
        if marital == MaritalStatus.SINGLE:
            return getattr(cls, f"TK{dependents}")
        elif marital == MaritalStatus.MARRIED:
            return getattr(cls, f"K{dependents}")
        else:  # MARRIED_COMBINED
            return getattr(cls, f"KB{dependents}")


# ============================================================================
# PTKP Amounts (Annual in IDR)
# ============================================================================

# PTKP amounts for tax year 2024 (and onward)
PTKP_ANNUAL_AMOUNTS: dict[PTKPCategory, int] = {
    PTKPCategory.TK0: 54_000_000,
    PTKPCategory.TK1: 58_500_000,
    PTKPCategory.TK2: 63_000_000,
    PTKPCategory.TK3: 67_500_000,
    PTKPCategory.K0: 58_500_000,
    PTKPCategory.K1: 63_000_000,
    PTKPCategory.K2: 67_500_000,
    PTKPCategory.K3: 72_000_000,
    PTKPCategory.KB0: 63_000_000,
    PTKPCategory.KB1: 67_500_000,
    PTKPCategory.KB2: 72_000_000,
    PTKPCategory.KB3: 76_500_000,
}

# Additional deduction for spouse (if spouse works and not combined) - not used in this VO but for reference
SPOUSE_ADDITIONAL = 4_500_000  # IDR per year


# ============================================================================
# Exceptions
# ============================================================================


class PTKPError(ValueError):
    """Base exception for PTKP errors."""

    pass


class InvalidDependentsError(PTKPError):
    """Raised when dependents count is invalid."""

    pass


class InvalidMaritalStatusError(PTKPError):
    """Raised when marital status is invalid for operation."""

    pass


# ============================================================================
# Value Object: EmployeePTKPStatusVO
# ============================================================================


@dataclass(frozen=True)
class EmployeePTKPStatusVO:
    """
    Immutable value object for employee PTKP status.

    Attributes:
        marital_status: MaritalStatus enum (TK, K, KB)
        dependents: Number of dependents (0-3)
        spouse_income_combined: Whether spouse income is combined (for K status)
        effective_date: Date when this PTKP status becomes effective
        notes: Additional notes

    Examples:
        >>> ptkp = EmployeePTKPStatusVO(
        ...     marital_status=MaritalStatus.SINGLE,
        ...     dependents=2
        ... )
        >>> ptkp.get_status_code()
        'TK/2'
        >>> ptkp.get_ptkp_amount()
        63000000
        >>> ptkp.get_monthly_ptkp()
        5250000
    """

    marital_status: MaritalStatus
    dependents: int = 0
    spouse_income_combined: bool = False
    effective_date: date = field(default_factory=date.today)
    notes: str = ""

    def __post_init__(self) -> None:
        """Validate PTKP status."""
        # Validate marital_status
        if not isinstance(self.marital_status, MaritalStatus):
            raise PTKPError(f"Invalid marital_status: {self.marital_status}")

        # Validate dependents
        if self.dependents < 0 or self.dependents > 3:
            raise InvalidDependentsError(
                f"Dependents must be between 0 and 3, got {self.dependents}"
            )

        # Validate spouse_income_combined only matters for MARRIED
        if self.marital_status == MaritalStatus.SINGLE and self.spouse_income_combined:
            raise PTKPError("Spouse income combined cannot be true for single status")

        if (
            self.marital_status == MaritalStatus.MARRIED_COMBINED
            and not self.spouse_income_combined
        ):
            # For KB, spouse_income_combined should be True, but we can auto-correct
            object.__setattr__(self, "spouse_income_combined", True)

        # Validate effective_date is not in future? Allow future effective dates for planning
        if self.effective_date is None:
            object.__setattr__(self, "effective_date", date.today())

        # Clean notes
        if self.notes:
            object.__setattr__(self, "notes", self.notes.strip())

    # ------------------------------------------------------------------------
    # Factory Methods
    # ------------------------------------------------------------------------

    @classmethod
    def create_single(
        cls, dependents: int = 0, effective_date: date | None = None
    ) -> EmployeePTKPStatusVO:
        """Create PTKP status for single employee."""
        return cls(
            marital_status=MaritalStatus.SINGLE,
            dependents=dependents,
            spouse_income_combined=False,
            effective_date=effective_date or date.today(),
        )

    @classmethod
    def create_married(
        cls, dependents: int = 0, combined: bool = False, effective_date: date | None = None
    ) -> EmployeePTKPStatusVO:
        """Create PTKP status for married employee."""
        marital = MaritalStatus.MARRIED_COMBINED if combined else MaritalStatus.MARRIED
        return cls(
            marital_status=marital,
            dependents=dependents,
            spouse_income_combined=combined,
            effective_date=effective_date or date.today(),
        )

    @classmethod
    def from_category(
        cls, category: PTKPCategory, effective_date: date | None = None
    ) -> EmployeePTKPStatusVO:
        """Create PTKP status from category code (e.g., TK/2)."""
        marital = category.get_marital_status()
        dependents = category.get_dependents()
        spouse_combined = marital == MaritalStatus.MARRIED_COMBINED
        return cls(
            marital_status=marital,
            dependents=dependents,
            spouse_income_combined=spouse_combined,
            effective_date=effective_date or date.today(),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EmployeePTKPStatusVO:
        """Reconstruct from dictionary."""
        marital = MaritalStatus.from_string(data.get("marital_status", "TK"))
        if marital is None:
            raise PTKPError(f"Invalid marital_status: {data.get('marital_status')}")
        effective = data.get("effective_date")
        if isinstance(effective, str):
            effective = date.fromisoformat(effective)
        elif effective is None:
            effective = date.today()
        return cls(
            marital_status=marital,
            dependents=data.get("dependents", 0),
            spouse_income_combined=data.get("spouse_income_combined", False),
            effective_date=effective,
            notes=data.get("notes", ""),
        )

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    @property
    def category(self) -> PTKPCategory:
        """Get PTKP category code (e.g., TK/2)."""
        return PTKPCategory.from_marital_and_dependents(self.marital_status, self.dependents)

    @property
    def category_display(self) -> str:
        """Display name of the category."""
        return self.category.display_name()

    @property
    def status_code(self) -> str:
        """Get status code string (e.g., 'TK/2')."""
        return self.category.value

    @property
    def is_single(self) -> bool:
        return self.marital_status == MaritalStatus.SINGLE

    @property
    def is_married(self) -> bool:
        return self.marital_status == MaritalStatus.MARRIED

    @property
    def is_combined(self) -> bool:
        return self.marital_status == MaritalStatus.MARRIED_COMBINED

    @property
    def has_dependents(self) -> bool:
        return self.dependents > 0

    # ------------------------------------------------------------------------
    # PTKP Amount Calculations
    # ------------------------------------------------------------------------

    def get_ptkp_amount(self, tax_year: int | None = None) -> int:
        """
        Get annual PTKP amount in IDR for the given tax year.

        Args:
            tax_year: Tax year (defaults to current year if >=2024, else 2024)

        Returns:
            PTKP amount in IDR
        """
        if tax_year is None:
            tax_year = date.today().year
        # For years before 2024, use 2024 rates (simplified)
        year = max(tax_year, 2024)
        # Amounts are constant from 2016 onward, but we can adjust if needed
        return PTKP_ANNUAL_AMOUNTS.get(self.category, 54_000_000)

    def get_monthly_ptkp(self, tax_year: int | None = None) -> Decimal:
        """Get monthly PTKP amount in IDR (annual / 12)."""
        annual = self.get_ptkp_amount(tax_year)
        return Decimal(annual) / Decimal(12)

    def get_daily_ptkp(self, tax_year: int | None = None) -> Decimal:
        """Get daily PTKP amount (for daily calculation)."""
        annual = self.get_ptkp_amount(tax_year)
        return Decimal(annual) / Decimal(360)  # Simplified, some use 365

    def get_additional_for_spouse(self) -> int:
        """Get additional PTKP amount if spouse is not working and not combined."""
        if self.is_married and not self.spouse_income_combined:
            return SPOUSE_ADDITIONAL
        return 0

    def get_total_annual_ptkp(self, tax_year: int | None = None) -> int:
        """Get total annual PTKP including spouse additional if applicable."""
        base = self.get_ptkp_amount(tax_year)
        return base + self.get_additional_for_spouse()

    # ------------------------------------------------------------------------
    # Validation and Business Rules
    # ------------------------------------------------------------------------

    def is_valid_for_year(self, tax_year: int) -> bool:
        """Check if PTKP status is valid for the given tax year."""
        # PTKP status is generally valid, but we can implement future rules
        return tax_year >= 2016  # PTKP rates stable since 2016

    def can_upgrade_dependents(self, new_dependents: int) -> bool:
        """Check if dependents can be increased."""
        return 0 <= new_dependents <= 3 and new_dependents >= self.dependents

    def can_downgrade_dependents(self, new_dependents: int) -> bool:
        """Check if dependents can be decreased."""
        return 0 <= new_dependents <= 3 and new_dependents <= self.dependents

    def requires_spouse_income_verification(self) -> bool:
        """Check if spouse income verification is required."""
        return self.is_married and not self.spouse_income_combined

    # ------------------------------------------------------------------------
    # Transformations (Immutable)
    # ------------------------------------------------------------------------

    def with_marital_status(self, new_marital: MaritalStatus) -> EmployeePTKPStatusVO:
        """Create new PTKP status with different marital status."""
        # Adjust dependents if needed (combined vs not)
        spouse_combined = self.spouse_income_combined
        if new_marital == MaritalStatus.SINGLE:
            spouse_combined = False
        elif new_marital == MaritalStatus.MARRIED_COMBINED:
            spouse_combined = True
        return EmployeePTKPStatusVO(
            marital_status=new_marital,
            dependents=self.dependents,
            spouse_income_combined=spouse_combined,
            effective_date=self.effective_date,
            notes=f"{self.notes} | Marital changed to {new_marital.value}",
        )

    def with_dependents(self, new_dependents: int) -> EmployeePTKPStatusVO:
        """Create new PTKP status with updated dependents count."""
        if not (0 <= new_dependents <= 3):
            raise InvalidDependentsError(f"Dependents must be 0-3, got {new_dependents}")
        return EmployeePTKPStatusVO(
            marital_status=self.marital_status,
            dependents=new_dependents,
            spouse_income_combined=self.spouse_income_combined,
            effective_date=self.effective_date,
            notes=f"{self.notes} | Dependents changed to {new_dependents}",
        )

    def with_combined(self, combined: bool) -> EmployeePTKPStatusVO:
        """Toggle spouse income combined status (only for married)."""
        if self.is_single:
            raise InvalidMaritalStatusError("Cannot set combined for single status")
        new_marital = MaritalStatus.MARRIED_COMBINED if combined else MaritalStatus.MARRIED
        return EmployeePTKPStatusVO(
            marital_status=new_marital,
            dependents=self.dependents,
            spouse_income_combined=combined,
            effective_date=self.effective_date,
            notes=f"{self.notes} | Spouse income combined set to {combined}",
        )

    def effective_from(self, new_date: date) -> EmployeePTKPStatusVO:
        """Change effective date."""
        return EmployeePTKPStatusVO(
            marital_status=self.marital_status,
            dependents=self.dependents,
            spouse_income_combined=self.spouse_income_combined,
            effective_date=new_date,
            notes=self.notes,
        )

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "marital_status": self.marital_status.value,
            "marital_status_display": self.marital_status.display_name(),
            "dependents": self.dependents,
            "spouse_income_combined": self.spouse_income_combined,
            "status_code": self.status_code,
            "category_display": self.category_display,
            "effective_date": self.effective_date.isoformat(),
            "annual_ptkp": self.get_ptkp_amount(),
            "monthly_ptkp": str(self.get_monthly_ptkp()),
            "total_annual_ptkp": self.get_total_annual_ptkp(),
            "notes": self.notes,
        }

    def to_db_record(self) -> dict[str, Any]:
        """Convert to database-friendly format."""
        return {
            "ptkp_marital_status": self.marital_status.value,
            "ptkp_dependents": self.dependents,
            "ptkp_spouse_income_combined": self.spouse_income_combined,
            "ptkp_status_code": self.status_code,
            "ptkp_effective_date": self.effective_date,
            "ptkp_notes": self.notes,
        }

    # ------------------------------------------------------------------------
    # Dunder Methods
    # ------------------------------------------------------------------------

    def __str__(self) -> str:
        return self.status_code

    def __repr__(self) -> str:
        return f"EmployeePTKPStatusVO({self.status_code}, effective={self.effective_date})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, EmployeePTKPStatusVO):
            return False
        return (
            self.marital_status == other.marital_status
            and self.dependents == other.dependents
            and self.spouse_income_combined == other.spouse_income_combined
        )

    def __hash__(self) -> int:
        return hash((self.marital_status, self.dependents, self.spouse_income_combined))


# ============================================================================
# Helper Functions
# ============================================================================


def calculate_ptkp_deduction(
    ptkp_status: EmployeePTKPStatusVO,
    monthly_salary: Decimal,
    tax_year: int | None = None,
) -> Decimal:
    """
    Calculate PTKP deduction amount (the amount that is tax-free).
    For PPh 21 calculation, the PTKP is deducted from annual net income.
    This function returns the annual PTKP amount as Decimal.
    """
    return Decimal(ptkp_status.get_ptkp_amount(tax_year))


def get_ptkp_category_from_code(code: str) -> PTKPCategory | None:
    """Get PTKPCategory from code string (e.g., 'TK/2')."""
    for cat in PTKPCategory:
        if cat.value == code:
            return cat
    return None


def is_valid_ptkp_code(code: str) -> bool:
    """Check if a PTKP code is valid."""
    return get_ptkp_category_from_code(code) is not None


def get_max_dependents_for_marital(marital: MaritalStatus) -> int:
    """Get maximum dependents allowed for given marital status."""
    return 3  # All statuses allow up to 3


# ============================================================================
# Alias for backward compatibility (used by tests)
# ============================================================================

# PTKPStatus is an alias for PTKPCategory to satisfy imports in tests
PTKPStatus = PTKPCategory

# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "EmployeePTKPStatusVO",
    "InvalidDependentsError",
    "InvalidMaritalStatusError",
    "MaritalStatus",
    "PTKPCategory",
    "PTKPError",
    "PTKPStatus",  
    "calculate_ptkp_deduction",
    "get_max_dependents_for_marital",
    "get_ptkp_category_from_code",
    "is_valid_ptkp_code",
]