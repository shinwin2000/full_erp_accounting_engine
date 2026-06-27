#!/usr/bin/env python3
# Code quality fix: removed any placeholder 'XXX' markers.
"""
Module: customer_tax_status_vo.py

Layer: Domain / Customer, Supplier, Employee

Responsibility:
    Value object for customer tax status. Immutable.
    Represents the tax status of a customer, including PKP (VAT-registered)
    status, NPWP (tax identification number), tax office, registration dates,
    and tax-related validations for VAT and withholding tax calculations.

Business rules:
    - PKP (Pengusaha Kena Pajak) status determines VAT handling.
    - NPWP must be 15 digits (with optional formatting).
    - Tax office is optional but recommended for PKP customers.
    - Registration date must be valid and not in future.
    - Provides methods to format NPWP, validate NPWP checksum, and determine
      applicable tax rates for withholding (PPh 23).
    - Immutable: all operations return new instances.

Dependencies:
    - Python standard library (datetime, dataclass, re, logging, decimal)
    - domain.shared_value_objects.npwp_vo (optional, for advanced NPWP handling)

Audit:
    Pure value object; no I/O. Caller should log tax status changes.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================================
# Custom Exceptions
# ============================================================================


class TaxStatusError(ValueError):
    """Base exception for tax status errors."""

    pass


class InvalidNPWPError(TaxStatusError):
    """Raised when NPWP format is invalid."""

    pass


class InvalidPKPStatusError(TaxStatusError):
    """Raised when PKP status is invalid."""

    pass


class TaxOfficeNotFoundError(TaxStatusError):
    """Raised when tax office code is not recognized."""

    pass


# ============================================================================
# Constants & Helper Functions
# ============================================================================

# NPWP validation constants
NPWP_LENGTH = 15
NPWP_PATTERN = r"^[0-9]{15}$"
NPWP_FORMATTED_PATTERN = r"^[0-9]{2}\.[0-9]{3}\.[0-9]{3}\.[0-9]{1}-[0-9]{3}\.[0-9]{3}$"
NPWP_WEIGHTS = [2, 3, 4, 5, 6, 7, 8, 9, 10, 2, 3, 4, 5, 6]  # for first 14 digits

# Tax office registry (simplified - in production would be from config)
TAX_OFFICE_REGISTRY = {
    "01": {"name": "Jakarta KPP Madya", "city": "Jakarta", "region": "DKI Jakarta"},
    "02": {"name": "Jakarta KPP Kebayoran Baru", "city": "Jakarta", "region": "DKI Jakarta"},
    "03": {"name": "Jakarta KPP Gambir", "city": "Jakarta", "region": "DKI Jakarta"},
    "04": {"name": "Jakarta KPP Cengkareng", "city": "Jakarta", "region": "DKI Jakarta"},
    "05": {"name": "Jakarta KPP Pasar Rebo", "city": "Jakarta", "region": "DKI Jakarta"},
    "07": {"name": "Bandung KPP", "city": "Bandung", "region": "Jawa Barat"},
    "09": {"name": "Surabaya KPP", "city": "Surabaya", "region": "Jawa Timur"},
    "10": {"name": "Medan KPP", "city": "Medan", "region": "Sumatera Utara"},
    "11": {"name": "Semarang KPP", "city": "Semarang", "region": "Jawa Tengah"},
    "12": {"name": "Makassar KPP", "city": "Makassar", "region": "Sulawesi Selatan"},
    "13": {"name": "Denpasar KPP", "city": "Denpasar", "region": "Bali"},
    "14": {"name": "Palembang KPP", "city": "Palembang", "region": "Sumatera Selatan"},
    "15": {"name": "Balikpapan KPP", "city": "Balikpapan", "region": "Kalimantan Timur"},
    "16": {"name": "Manado KPP", "city": "Manado", "region": "Sulawesi Utara"},
    "17": {"name": "Pontianak KPP", "city": "Pontianak", "region": "Kalimantan Barat"},
    "18": {"name": "Banjarmasin KPP", "city": "Banjarmasin", "region": "Kalimantan Selatan"},
    "19": {"name": "Jayapura KPP", "city": "Jayapura", "region": "Papua"},
    "20": {"name": "Mataram KPP", "city": "Mataram", "region": "Nusa Tenggara Barat"},
    "21": {"name": "Kupang KPP", "city": "Kupang", "region": "Nusa Tenggara Timur"},
}

# VAT rates based on PKP status and transaction type
VAT_RATES = {
    "pkp_standard": Decimal("11"),  # 11% standard VAT
    "pkp_reduced": Decimal("0"),    # For certain goods/services (0%)
    "non_pkp": Decimal("0"),        # No VAT
}

# Withholding tax (PPh 23) rates based on tax status
WITHHOLDING_RATES = {
    "with_npwp": Decimal("2"),      # 2% with NPWP
    "without_npwp": Decimal("3"),   # 3% without NPWP
    "final": Decimal("1"),          # 1% for certain services
}


# ============================================================================
# Enums
# ============================================================================


class PKPStatus(Enum):
    """PKP (Pengusaha Kena Pajak) status."""

    PKP = "pkp"          # Registered for VAT
    NON_PKP = "non_pkp"  # Not registered for VAT
    EXEMPT = "exempt"    # Exempt by law (e.g., small businesses)
    PENDING = "pending"  # Application in progress

    def is_registered(self) -> bool:
        """Check if customer is VAT-registered."""
        return self == PKPStatus.PKP

    def can_issue_tax_invoice(self) -> bool:
        """Check if can issue tax invoice (faktur pajak)."""
        return self == PKPStatus.PKP

    def display_name(self) -> str:
        """Indonesian display name."""
        names = {
            PKPStatus.PKP: "PKP",
            PKPStatus.NON_PKP: "Non-PKP",
            PKPStatus.EXEMPT: "Dikecualikan",
            PKPStatus.PENDING: "Proses",
        }
        return names.get(self, self.value)


class TaxRegistrationStatus(Enum):
    """Overall tax registration status."""

    REGISTERED = "registered"
    NOT_REGISTERED = "not_registered"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"
    PENDING = "pending"


class WithholdingTaxType(Enum):
    """Types of withholding tax applicable to customer."""

    PPH_23 = "pph_23"    # Services, royalties, interest
    PPH_22 = "pph_22"    # Imports, purchases
    PPH_4_2 = "pph_4_2"  # Final tax
    NONE = "none"

    def rate(self, has_npwp: bool = True) -> Decimal:
        """Get withholding tax rate percentage."""
        rates = {
            WithholdingTaxType.PPH_23: Decimal("2") if has_npwp else Decimal("3"),
            WithholdingTaxType.PPH_22: Decimal("1.5"),
            WithholdingTaxType.PPH_4_2: Decimal("1"),
            WithholdingTaxType.NONE: Decimal("0"),
        }
        return rates.get(self, Decimal("0"))


# ============================================================================
# Value Object: CustomerTaxStatusVO
# ============================================================================


@dataclass(frozen=True)
class CustomerTaxStatusVO:
    """
    Immutable value object for customer tax status.

    Attributes:
        is_pkp: Whether customer is PKP (VAT-registered)
        npwp: Tax identification number (NPWP) - raw string
        npwp_validated: Whether NPWP has been validated with DJP
        tax_office_code: Two-digit tax office code (KPP)
        tax_office_name: Name of tax office (derived from code)
        registration_date: Date when tax registration was completed
        deregistration_date: Date when tax registration was cancelled (if any)
        registration_status: Current tax registration status
        withholding_type: Type of withholding tax applicable
        vat_rate_override: Override VAT rate (if different from standard)
        notes: Additional notes about tax status
        last_validation_date: Last date NPWP was validated with DJP
        validation_attempts: Number of validation attempts
        source: Source of this tax status ('manual', 'coretax_api', 'djp_online')

    Examples:
        >>> tax_status = CustomerTaxStatusVO.pkp_registered(npwp="123456789012345")
        >>> tax_status.is_pkp
        True
        >>> tax_status.get_formatted_npwp()
        '12.345.678.9-012.345'
        >>> tax_status.get_vat_rate()
        Decimal('11')
        >>> tax_status.to_dict()
        {...}
    """

    is_pkp: bool = False
    npwp: str | None = None
    npwp_validated: bool = False
    tax_office_code: str | None = None
    tax_office_name: str | None = None
    registration_date: date | None = None
    deregistration_date: date | None = None
    registration_status: TaxRegistrationStatus = TaxRegistrationStatus.NOT_REGISTERED
    withholding_type: WithholdingTaxType = WithholdingTaxType.NONE
    vat_rate_override: Decimal | None = None
    notes: str = ""
    last_validation_date: datetime | None = None
    validation_attempts: int = 0
    source: str = "manual"

    def __post_init__(self) -> None:
        """Validate tax status data."""
        # Validate and clean NPWP
        if self.npwp is not None:
            clean_npwp = self._clean_npwp(self.npwp)
            if not self._validate_npwp_format(clean_npwp):
                raise InvalidNPWPError(f"Invalid NPWP format: {self.npwp}")
            object.__setattr__(self, "npwp", clean_npwp)

        # Validate tax office code
        if self.tax_office_code is not None:
            clean_code = self.tax_office_code.strip().upper()
            if clean_code in TAX_OFFICE_REGISTRY:
                object.__setattr__(self, "tax_office_code", clean_code)
                if self.tax_office_name is None:
                    object.__setattr__(
                        self, "tax_office_name", TAX_OFFICE_REGISTRY[clean_code]["name"]
                    )
            else:
                # Allow unknown codes but log warning
                logger.warning(f"Unknown tax office code: {clean_code}")

        # Validate registration and deregistration dates
        if self.registration_date and self.deregistration_date:
            if self.deregistration_date <= self.registration_date:
                raise TaxStatusError("Deregistration date must be after registration date")

        # Validate registration status consistency
        if self.is_pkp and self.registration_status == TaxRegistrationStatus.NOT_REGISTERED:
            object.__setattr__(self, "registration_status", TaxRegistrationStatus.REGISTERED)
        elif not self.is_pkp and self.registration_status == TaxRegistrationStatus.REGISTERED:
            object.__setattr__(self, "registration_status", TaxRegistrationStatus.NOT_REGISTERED)

        # Validate NPWP validated status
        if self.npwp_validated and not self.npwp:
            raise TaxStatusError("Cannot have npwp_validated=True without NPWP")

        # Validate last_validation_date
        if self.last_validation_date and self.last_validation_date.tzinfo is None:
            object.__setattr__(
                self, "last_validation_date", self.last_validation_date.replace(tzinfo=UTC)
            )

        # Validate validation_attempts
        if self.validation_attempts < 0:
            object.__setattr__(self, "validation_attempts", 0)

        # Validate vat_rate_override
        if self.vat_rate_override is not None:
            if self.vat_rate_override < 0 or self.vat_rate_override > 100:
                raise TaxStatusError(f"Invalid VAT rate override: {self.vat_rate_override}")

    # ------------------------------------------------------------------------
    # NPWP Helpers
    # ------------------------------------------------------------------------

    @staticmethod
    def _clean_npwp(npwp: str) -> str:
        """Remove formatting from NPWP string."""
        if not npwp:
            return ""
        return re.sub(r"[^\d]", "", npwp)

    @staticmethod
    def _validate_npwp_format(npwp: str) -> bool:
        """Validate NPWP format (15 digits)."""
        if not npwp:
            return True  # Empty NPWP is allowed
        return bool(re.match(NPWP_PATTERN, npwp))

    @classmethod
    def _validate_npwp_checksum(cls, npwp: str) -> bool:
        """
        Validate NPWP check digit (modulo 11 algorithm).

        NPWP is 15 digits. The last digit (15th) is the check digit.
        Algorithm: multiply first 14 digits by weights [2,3,4,5,6,7,8,9,10,2,3,4,5,6],
        sum them, then check digit = (11 - (sum % 11)) % 10.
        """
        if not npwp or len(npwp) != NPWP_LENGTH:
            return False
        total = 0
        for i in range(14):
            digit = int(npwp[i])
            weight = NPWP_WEIGHTS[i]
            total += digit * weight
        remainder = total % 11
        expected_check = (11 - remainder) % 10
        actual_check = int(npwp[14])
        return expected_check == actual_check

    def is_npwp_valid(self, check_checksum: bool = True) -> bool:
        """
        Check if NPWP exists and is valid.

        Args:
            check_checksum: Whether to validate the check digit.
        """
        if not self.npwp:
            return False
        if not self._validate_npwp_format(self.npwp):
            return False
        if check_checksum:
            return self._validate_npwp_checksum(self.npwp)
        return True

    def get_formatted_npwp(self) -> str | None:
        """
        Return NPWP in standard Indonesian format: 00.000.000.0-000.000
        Example: 12.345.678.9-012.345
        """
        if not self.npwp or len(self.npwp) != 15:
            return self.npwp
        return f"{self.npwp[:2]}.{self.npwp[2:5]}.{self.npwp[5:8]}.{self.npwp[8:9]}-{self.npwp[9:12]}.{self.npwp[12:15]}"

    def get_tax_office_info(self) -> dict[str, str] | None:
        """Get tax office information from code."""
        if not self.tax_office_code:
            return None
        return TAX_OFFICE_REGISTRY.get(
            self.tax_office_code,
            {"name": self.tax_office_name or "Unknown", "city": "Unknown", "region": "Unknown"},
        )

    # ------------------------------------------------------------------------
    # VAT Methods
    # ------------------------------------------------------------------------

    def get_vat_rate(self, transaction_type: str = "standard") -> Decimal:
        """
        Get applicable VAT rate for this customer.

        Args:
            transaction_type: 'standard', 'reduced', or 'export'

        Returns:
            VAT rate as percentage (Decimal)
        """
        if not self.is_pkp:
            return Decimal("0")
        if self.vat_rate_override is not None:
            return self.vat_rate_override
        if transaction_type == "reduced":
            return VAT_RATES["pkp_reduced"]
        if transaction_type == "export":
            return Decimal("0")
        return VAT_RATES["pkp_standard"]

    def calculate_vat(self, amount: Decimal, transaction_type: str = "standard") -> Decimal:
        """
        Calculate VAT amount for a given base amount.

        Args:
            amount: Base amount (exclude VAT)
            transaction_type: 'standard', 'reduced', or 'export'

        Returns:
            VAT amount
        """
        rate = self.get_vat_rate(transaction_type)
        vat_amount = amount * (rate / Decimal("100"))
        return vat_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    def calculate_inclusive_vat(
        self, total_amount: Decimal, transaction_type: str = "standard"
    ) -> tuple[Decimal, Decimal]:
        """
        Calculate base amount and VAT from a total inclusive amount.

        Args:
            total_amount: Amount including VAT
            transaction_type: 'standard', 'reduced', or 'export'

        Returns:
            (base_amount, vat_amount) tuple
        """
        rate = self.get_vat_rate(transaction_type)
        if rate == 0:
            return total_amount, Decimal("0")
        factor = Decimal("100") / (Decimal("100") + rate)
        base_amount = (total_amount * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        vat_amount = total_amount - base_amount
        return base_amount, vat_amount

    # ------------------------------------------------------------------------
    # Withholding Tax Methods
    # ------------------------------------------------------------------------

    def get_withholding_rate(self, with_npwp: bool = True) -> Decimal:
        """
        Get withholding tax rate for PPh 23.

        Args:
            with_npwp: Whether customer has NPWP for this transaction

        Returns:
            Rate as percentage (Decimal)
        """
        if self.withholding_type == WithholdingTaxType.NONE:
            return Decimal("0")
        if self.withholding_type == WithholdingTaxType.PPH_23:
            return (
                WITHHOLDING_RATES["with_npwp"] if with_npwp else WITHHOLDING_RATES["without_npwp"]
            )
        elif self.withholding_type == WithholdingTaxType.PPH_22:
            return WITHHOLDING_RATES["with_npwp"]  # 1.5%
        elif self.withholding_type == WithholdingTaxType.PPH_4_2:
            return WITHHOLDING_RATES["final"]
        return Decimal("0")

    def calculate_withholding(self, amount: Decimal, with_npwp: bool = True) -> Decimal:
        """
        Calculate withholding tax amount (PPh 23/22/4(2)).

        Args:
            amount: Transaction amount
            with_npwp: Whether customer provides NPWP for this transaction

        Returns:
            Withholding tax amount
        """
        rate = self.get_withholding_rate(with_npwp)
        withholding = amount * (rate / Decimal("100"))
        return withholding.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    # ------------------------------------------------------------------------
    # Business Logic Methods
    # ------------------------------------------------------------------------

    def is_registered(self) -> bool:
        """Check if customer is fully tax-registered."""
        return self.registration_status == TaxRegistrationStatus.REGISTERED

    def is_active(self, as_of: date | None = None) -> bool:
        """Check if tax registration is active on given date."""
        if self.registration_status != TaxRegistrationStatus.REGISTERED:
            return False
        check_date = as_of or date.today()
        if self.registration_date and check_date < self.registration_date:
            return False
        if self.deregistration_date and check_date >= self.deregistration_date:
            return False
        return True

    def can_issue_invoice_with_tax(self) -> bool:
        """Check if customer can receive tax invoice (faktur pajak)."""
        return self.is_pkp and self.is_active()

    def needs_withholding(self) -> bool:
        """Check if customer is subject to withholding tax."""
        return self.withholding_type != WithholdingTaxType.NONE

    def deregister(self, effective_date: date, reason: str) -> CustomerTaxStatusVO:
        """
        Create a new tax status with deregistration.

        Args:
            effective_date: Date when deregistration takes effect
            reason: Reason for deregistration
        """
        if self.deregistration_date is not None:
            raise TaxStatusError("Already deregistered")
        return CustomerTaxStatusVO(
            is_pkp=self.is_pkp,
            npwp=self.npwp,
            npwp_validated=self.npwp_validated,
            tax_office_code=self.tax_office_code,
            tax_office_name=self.tax_office_name,
            registration_date=self.registration_date,
            deregistration_date=effective_date,
            registration_status=TaxRegistrationStatus.CANCELLED,
            withholding_type=self.withholding_type,
            vat_rate_override=self.vat_rate_override,
            notes=f"{self.notes}\nDeregistered: {reason}",
            last_validation_date=self.last_validation_date,
            validation_attempts=self.validation_attempts,
            source=self.source,
        )

    def validate_npwp_with_djp(self, is_valid: bool, validator: str) -> CustomerTaxStatusVO:
        """
        Record NPWP validation result from DJP (Coretax).

        Args:
            is_valid: Whether validation succeeded
            validator: User/system that performed validation
        """
        return CustomerTaxStatusVO(
            is_pkp=self.is_pkp,
            npwp=self.npwp,
            npwp_validated=is_valid,
            tax_office_code=self.tax_office_code,
            tax_office_name=self.tax_office_name,
            registration_date=self.registration_date,
            deregistration_date=self.deregistration_date,
            registration_status=self.registration_status,
            withholding_type=self.withholding_type,
            vat_rate_override=self.vat_rate_override,
            notes=f"{self.notes}\nValidated by {validator} on {datetime.now(UTC).date()}: {is_valid}",
            last_validation_date=datetime.now(UTC),
            validation_attempts=self.validation_attempts + 1,
            source=self.source,
        )

    def upgrade_to_pkp(
        self, npwp: str, tax_office_code: str, registration_date: date
    ) -> CustomerTaxStatusVO:
        """Upgrade customer to PKP status."""
        clean_npwp = self._clean_npwp(npwp)
        if not self._validate_npwp_format(clean_npwp):
            raise InvalidNPWPError(f"Invalid NPWP: {npwp}")
        return CustomerTaxStatusVO(
            is_pkp=True,
            npwp=clean_npwp,
            npwp_validated=False,
            tax_office_code=tax_office_code,
            tax_office_name=TAX_OFFICE_REGISTRY.get(tax_office_code, {}).get("name"),
            registration_date=registration_date,
            deregistration_date=None,
            registration_status=TaxRegistrationStatus.REGISTERED,
            withholding_type=self.withholding_type,
            vat_rate_override=self.vat_rate_override,
            notes=f"{self.notes}\nUpgraded to PKP on {registration_date}",
            last_validation_date=None,
            validation_attempts=0,
            source=self.source,
        )

    def set_withholding_type(
        self, new_type: WithholdingTaxType, changed_by: str
    ) -> CustomerTaxStatusVO:
        """Change withholding tax type."""
        return CustomerTaxStatusVO(
            is_pkp=self.is_pkp,
            npwp=self.npwp,
            npwp_validated=self.npwp_validated,
            tax_office_code=self.tax_office_code,
            tax_office_name=self.tax_office_name,
            registration_date=self.registration_date,
            deregistration_date=self.deregistration_date,
            registration_status=self.registration_status,
            withholding_type=new_type,
            vat_rate_override=self.vat_rate_override,
            notes=f"{self.notes}\nWithholding type changed to {new_type.value} by {changed_by}",
            last_validation_date=self.last_validation_date,
            validation_attempts=self.validation_attempts,
            source=self.source,
        )

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "is_pkp": self.is_pkp,
            "npwp": self.npwp,
            "npwp_formatted": self.get_formatted_npwp(),
            "npwp_validated": self.npwp_validated,
            "tax_office_code": self.tax_office_code,
            "tax_office_name": self.tax_office_name,
            "tax_office_info": self.get_tax_office_info(),
            "registration_date": self.registration_date.isoformat()
            if self.registration_date
            else None,
            "deregistration_date": self.deregistration_date.isoformat()
            if self.deregistration_date
            else None,
            "registration_status": self.registration_status.value,
            "withholding_type": self.withholding_type.value,
            "vat_rate_override": str(self.vat_rate_override) if self.vat_rate_override else None,
            "default_vat_rate": str(self.get_vat_rate()),
            "notes": self.notes,
            "last_validation_date": self.last_validation_date.isoformat()
            if self.last_validation_date
            else None,
            "validation_attempts": self.validation_attempts,
            "source": self.source,
            "is_registered": self.is_registered(),
            "is_active": self.is_active(),
            "can_issue_tax_invoice": self.can_issue_invoice_with_tax(),
        }

    def to_db_record(self) -> dict[str, Any]:
        """Convert to database-friendly format."""
        return {
            "customer_is_pkp": self.is_pkp,
            "customer_npwp": self.npwp,
            "customer_npwp_validated": self.npwp_validated,
            "customer_tax_office_code": self.tax_office_code,
            "customer_tax_registration_date": self.registration_date,
            "customer_tax_deregistration_date": self.deregistration_date,
            "customer_tax_registration_status": self.registration_status.value,
            "customer_withholding_type": self.withholding_type.value,
            "customer_vat_rate_override": self.vat_rate_override,
            "customer_tax_notes": self.notes,
            "customer_tax_last_validation": self.last_validation_date,
            "customer_tax_validation_attempts": self.validation_attempts,
            "customer_tax_source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CustomerTaxStatusVO:
        """Reconstruct from dictionary."""
        reg_date = None
        if data.get("registration_date"):
            reg_date = date.fromisoformat(data["registration_date"])
        dereg_date = None
        if data.get("deregistration_date"):
            dereg_date = date.fromisoformat(data["deregistration_date"])
        last_val = None
        if data.get("last_validation_date"):
            last_val = datetime.fromisoformat(data["last_validation_date"])
        reg_status = TaxRegistrationStatus(data.get("registration_status", "not_registered"))
        withholding = WithholdingTaxType(data.get("withholding_type", "none"))
        vat_override = None
        if data.get("vat_rate_override"):
            vat_override = Decimal(str(data["vat_rate_override"]))
        return cls(
            is_pkp=data.get("is_pkp", False),
            npwp=data.get("npwp"),
            npwp_validated=data.get("npwp_validated", False),
            tax_office_code=data.get("tax_office_code"),
            tax_office_name=data.get("tax_office_name"),
            registration_date=reg_date,
            deregistration_date=dereg_date,
            registration_status=reg_status,
            withholding_type=withholding,
            vat_rate_override=vat_override,
            notes=data.get("notes", ""),
            last_validation_date=last_val,
            validation_attempts=data.get("validation_attempts", 0),
            source=data.get("source", "manual"),
        )

    # ------------------------------------------------------------------------
    # Factory Methods
    # ------------------------------------------------------------------------

    @classmethod
    def non_pkp(cls) -> CustomerTaxStatusVO:
        """Create default non-PKP customer tax status."""
        return cls(
            is_pkp=False,
            registration_status=TaxRegistrationStatus.NOT_REGISTERED,
        )

    @classmethod
    def pkp_registered(
        cls,
        npwp: str,
        tax_office_code: str | None = None,
        registration_date: date | None = None,
        withholding_type: WithholdingTaxType = WithholdingTaxType.PPH_23,
    ) -> CustomerTaxStatusVO:
        """Create PKP-registered customer tax status."""
        if registration_date is None:
            registration_date = date.today()
        return cls(
            is_pkp=True,
            npwp=npwp,
            npwp_validated=False,
            tax_office_code=tax_office_code,
            registration_date=registration_date,
            registration_status=TaxRegistrationStatus.REGISTERED,
            withholding_type=withholding_type,
        )

    @classmethod
    def from_npwp(cls, npwp: str) -> CustomerTaxStatusVO:
        """Create tax status from NPWP only (assuming PKP)."""
        return cls.pkp_registered(npwp=npwp)

    # ------------------------------------------------------------------------
    # Dunder Methods
    # ------------------------------------------------------------------------

    def __str__(self) -> str:
        if self.is_pkp:
            return f"PKP ({self.get_formatted_npwp() or 'No NPWP'})"
        return "Non-PKP"

    def __repr__(self) -> str:
        return f"CustomerTaxStatusVO(is_pkp={self.is_pkp}, npwp={self.npwp}, status={self.registration_status.value})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CustomerTaxStatusVO):
            return False
        return (
            self.is_pkp == other.is_pkp
            and self.npwp == other.npwp
            and self.registration_date == other.registration_date
        )

    def __hash__(self) -> int:
        return hash((self.is_pkp, self.npwp, self.registration_date))


# ============================================================================
# Helper Functions
# ============================================================================


def format_npwp(npwp: str) -> str:
    """Format NPWP string to standard Indonesian format."""
    clean = re.sub(r"[^\d]", "", npwp)
    if len(clean) != 15:
        return npwp
    return f"{clean[:2]}.{clean[2:5]}.{clean[5:8]}.{clean[8:9]}-{clean[9:12]}.{clean[12:15]}"


def validate_npwp(npwp: str, check_checksum: bool = True) -> bool:
    """Quick NPWP validation without creating object."""
    if not npwp:
        return False
    clean = re.sub(r"[^\d]", "", npwp)
    if len(clean) != 15:
        return False
    if not check_checksum:
        return True
    return CustomerTaxStatusVO._validate_npwp_checksum(clean)


def get_tax_office_by_code(code: str) -> dict[str, str] | None:
    """Get tax office information by two-digit code."""
    return TAX_OFFICE_REGISTRY.get(code)


def get_pkp_status_display(is_pkp: bool) -> str:
    """Get Indonesian display string for PKP status."""
    return "PKP" if is_pkp else "Non-PKP"


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "CustomerTaxStatusVO",
    "InvalidNPWPError",
    "InvalidPKPStatusError",
    "PKPStatus",
    "TaxOfficeNotFoundError",
    "TaxRegistrationStatus",
    "TaxStatusError",
    "WithholdingTaxType",
    "format_npwp",
    "get_pkp_status_display",
    "get_tax_office_by_code",
    "validate_npwp",
]
