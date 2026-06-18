#!/usr/bin/env python3
"""
Module: psak_46_income_taxes.py
Layer: 7 - Policy Engine & Standards / PSAK

Responsibility:
    PSAK 46: Pajak Penghasilan (setara dengan IAS 12).
    Mengatur perlakuan akuntansi untuk pajak penghasilan, termasuk
    pajak kini dan pajak tangguhan. Aset dan liabilitas pajak tangguhan
    diakui untuk perbedaan temporer antara nilai buku dan dasar pajak,
    serta untuk akumulasi rugi fiskal dan kredit pajak yang belum dimanfaatkan.
    Mengakui pajak tangguhan untuk seluruh perbedaan temporer kena pajak,
    dan untuk perbedaan temporer yang dapat dikurangkan sepanjang kemungkinan
    besar laba kena pajak akan tersedia.

Dependencies:
    - datetime, decimal, enum, typing, dataclasses, uuid, hashlib, logging

Audit:
    Setiap perhitungan pajak kini, pajak tangguhan, dan rekonsiliasi dicatat.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================
class PSAK46TemporaryDifferenceType(Enum):
    TAXABLE = "kena_pajak"  # Akan menambah laba kena pajak di masa depan
    DEDUCTIBLE = "dapat_dikurangkan"  # Akan mengurangi laba kena pajak di masa depan


class PSAK46DeferredTaxAssetRecognition(Enum):
    PROBABLE = "probable"  # Diakui jika kemungkinan besar laba akan tersedia
    FULL = "penuh"  # Diakui penuh (misal untuk deductible temporary differences)
    VALUATION_ALLOWANCE = "cadangan"  # Cadangan penurunan nilai aset pajak tangguhan


class PSAK46TaxRateChangeTreatment(Enum):
    PROSPECTIVE = "prospektif"  # Diterapkan untuk perbedaan temporer masa depan
    RETROSPECTIVE = "retrospektif"  # Disesuaikan untuk semua perbedaan temporer yang ada


class PSAK46ComplianceLevel(Enum):
    FULL = "penuh"
    SUBSTANTIAL = "substansial"
    PARTIAL = "sebagian"
    NON_COMPLIANT = "tidak_patuh"


# ============================================================================
# Exceptions
# ============================================================================
class PSAK46Error(Exception):
    pass


class TaxRateNotEnactedError(PSAK46Error):
    pass


# ============================================================================
# Data Classes
# ============================================================================
@dataclass
class PSAK46TemporaryDifference:
    """Perbedaan temporer antara nilai buku dan dasar pajak."""

    difference_id: UUID
    asset_liability_id: UUID
    description: str
    carrying_amount: Decimal
    tax_base: Decimal
    difference_type: PSAK46TemporaryDifferenceType
    temporary_difference: Decimal
    tax_rate: Decimal
    deferred_tax_amount: Decimal

    def __post_init__(self):
        self.temporary_difference = self.carrying_amount - self.tax_base
        self.deferred_tax_amount = (
            abs(self.temporary_difference) * (self.tax_rate / 100)
        ).quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)

    def to_dict(self) -> dict:
        return {
            "difference_id": str(self.difference_id),
            "asset_liability_id": str(self.asset_liability_id),
            "description": self.description,
            "carrying_amount": str(self.carrying_amount),
            "tax_base": str(self.tax_base),
            "difference_type": self.difference_type.value,
            "temporary_difference": str(self.temporary_difference),
            "deferred_tax": str(self.deferred_tax_amount),
        }


@dataclass
class PSAK46CurrentTax:
    """Pajak kini untuk periode."""

    current_tax_id: UUID
    entity_id: UUID
    entity_name: str
    taxable_profit: Decimal
    applicable_tax_rate: Decimal
    current_tax_expense: Decimal
    over_under_provision_previous: Decimal = Decimal(0)
    tax_paid_ytd: Decimal = Decimal(0)
    tax_payable: Decimal = Decimal(0)

    def __post_init__(self):
        self.current_tax_expense = (
            self.taxable_profit * (self.applicable_tax_rate / 100)
        ).quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)
        self.tax_payable = (
            self.current_tax_expense + self.over_under_provision_previous - self.tax_paid_ytd
        )

    def to_dict(self) -> dict:
        return {
            "current_tax_id": str(self.current_tax_id),
            "entity_id": str(self.entity_id),
            "taxable_profit": str(self.taxable_profit),
            "tax_rate": str(self.applicable_tax_rate),
            "tax_expense": str(self.current_tax_expense),
            "over_under_provision": str(self.over_under_provision_previous),
            "tax_paid": str(self.tax_paid_ytd),
            "tax_payable": str(self.tax_payable),
        }


@dataclass
class PSAK46DeferredTax:
    """Pajak tangguhan."""

    deferred_tax_id: UUID
    entity_id: UUID
    entity_name: str
    taxable_temporary_differences: list[PSAK46TemporaryDifference] = field(default_factory=list)
    deductible_temporary_differences: list[PSAK46TemporaryDifference] = field(default_factory=list)
    tax_loss_carryforwards: Decimal = Decimal(0)
    tax_credit_carryforwards: Decimal = Decimal(0)
    valuation_allowance: Decimal = Decimal(0)  # Cadangan penurunan nilai aset pajak tangguhan
    applicable_tax_rate: Decimal = Decimal(22)

    @property
    def deferred_tax_liability(self) -> Decimal:
        total = sum(d.deferred_tax_amount for d in self.taxable_temporary_differences)
        return total.quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)

    @property
    def deferred_tax_asset_before_allowance(self) -> Decimal:
        total = sum(d.deferred_tax_amount for d in self.deductible_temporary_differences)
        total += (self.tax_loss_carryforwards * (self.applicable_tax_rate / 100)).quantize(
            Decimal("0"), rounding=ROUND_HALF_EVEN
        )
        total += self.tax_credit_carryforwards
        return total

    @property
    def deferred_tax_asset(self) -> Decimal:
        return max(Decimal(0), self.deferred_tax_asset_before_allowance - self.valuation_allowance)

    @property
    def net_deferred_tax(self) -> Decimal:
        return self.deferred_tax_asset - self.deferred_tax_liability

    def to_dict(self) -> dict:
        return {
            "deferred_tax_id": str(self.deferred_tax_id),
            "entity_id": str(self.entity_id),
            "taxable_temporary": [d.to_dict() for d in self.taxable_temporary_differences],
            "deductible_temporary": [d.to_dict() for d in self.deductible_temporary_differences],
            "tax_loss_carryforwards": str(self.tax_loss_carryforwards),
            "tax_credit_carryforwards": str(self.tax_credit_carryforwards),
            "valuation_allowance": str(self.valuation_allowance),
            "deferred_tax_liability": str(self.deferred_tax_liability),
            "deferred_tax_asset": str(self.deferred_tax_asset),
            "net_deferred_tax": str(self.net_deferred_tax),
        }


@dataclass
class PSAK46TaxReconciliation:
    """Rekonsiliasi antara beban pajak dengan laba akuntansi dikali tarif."""

    reconciliation_id: UUID
    entity_id: UUID
    entity_name: str
    accounting_profit_before_tax: Decimal
    applicable_tax_rate: Decimal
    expected_tax_expense: Decimal
    actual_tax_expense: Decimal
    differences: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.expected_tax_expense = (
            self.accounting_profit_before_tax * (self.applicable_tax_rate / 100)
        ).quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)

    def variance(self) -> Decimal:
        return self.actual_tax_expense - self.expected_tax_expense

    def to_dict(self) -> dict:
        return {
            "reconciliation_id": str(self.reconciliation_id),
            "entity_id": str(self.entity_id),
            "accounting_profit": str(self.accounting_profit_before_tax),
            "expected_tax": str(self.expected_tax_expense),
            "actual_tax": str(self.actual_tax_expense),
            "variance": str(self.variance()),
            "differences": self.differences,
        }


@dataclass
class PSAK46ValidationResult:
    is_compliant: bool
    compliance_level: PSAK46ComplianceLevel
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    hash_sha256: str = ""

    def __post_init__(self):
        self.hash_sha256 = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "is_compliant": self.is_compliant,
            "level": self.compliance_level.value,
            "errors": self.errors,
            "warnings": self.warnings,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def add_error(self, error: str) -> None:
        self.errors.append(error)
        self.is_compliant = False
        if self.compliance_level != PSAK46ComplianceLevel.NON_COMPLIANT:
            self.compliance_level = PSAK46ComplianceLevel.NON_COMPLIANT

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)
        if self.compliance_level == PSAK46ComplianceLevel.FULL:
            self.compliance_level = PSAK46ComplianceLevel.SUBSTANTIAL

    def to_dict(self) -> dict:
        return {
            "is_compliant": self.is_compliant,
            "compliance_level": self.compliance_level.value,
            "errors": self.errors,
            "warnings": self.warnings,
            "hash": self.hash_sha256,
        }


# ============================================================================
# Domain Services
# ============================================================================
class PSAK46TaxService:
    """Service untuk perhitungan pajak."""

    @staticmethod
    def compute_tax_base_asset(cost: Decimal, accumulated_tax_depreciation: Decimal) -> Decimal:
        """Dasar pajak aset = biaya perolehan - akumulasi penyusutan fiskal."""
        return cost - accumulated_tax_depreciation

    @staticmethod
    def compute_tax_base_liability(carrying_amount: Decimal, future_deductible: Decimal) -> Decimal:
        """Dasar pajak liabilitas = nilai tercatat - jumlah yang dapat dikurangkan di masa depan."""
        return carrying_amount - future_deductible

    @staticmethod
    def determine_valuation_allowance(
        deferred_tax_asset: Decimal, probable_future_taxable_profit: Decimal
    ) -> Decimal:
        """Menentukan cadangan penurunan nilai aset pajak tangguhan."""
        if deferred_tax_asset <= probable_future_taxable_profit:
            return Decimal(0)
        return deferred_tax_asset - probable_future_taxable_profit

    @staticmethod
    def compute_tax_loss_recognition(tax_loss: Decimal, probable_future_profit: Decimal) -> Decimal:
        """Jumlah rugi fiskal yang dapat dikompensasikan ke masa depan (diakui sebagai aset pajak tangguhan)."""
        return min(tax_loss, probable_future_profit)


# ============================================================================
# Rules
# ============================================================================
class PSAK46Rules:
    """Aturan PSAK 46."""

    @staticmethod
    def validate_deferred_tax_asset_recognition(
        deferred_tax_asset: Decimal,
        probable_future_taxable_profit: Decimal,
    ) -> PSAK46ValidationResult:
        result = PSAK46ValidationResult(
            is_compliant=True, compliance_level=PSAK46ComplianceLevel.FULL
        )
        if deferred_tax_asset > 0 and deferred_tax_asset > probable_future_taxable_profit:
            result.add_warning(
                "Aset pajak tangguhan melebihi estimasi laba kena pajak masa depan; pertimbangkan valuation allowance"
            )
        return result

    @staticmethod
    def validate_tax_rate_change(
        old_rate: Decimal,
        new_rate: Decimal,
        effective_date: datetime,
        current_date: datetime,
    ) -> PSAK46ValidationResult:
        result = PSAK46ValidationResult(
            is_compliant=True, compliance_level=PSAK46ComplianceLevel.FULL
        )
        if new_rate != old_rate and effective_date <= current_date:
            result.add_warning("Perubahan tarif pajak efektif; deferred tax harus diukur ulang")
        return result


# ============================================================================
# Validator
# ============================================================================
class PSAK46Validator:
    def __init__(self):
        self._rules = PSAK46Rules()
        self._service = PSAK46TaxService()

    def create_current_tax(
        self,
        entity_id: UUID,
        entity_name: str,
        taxable_profit: Decimal,
        applicable_tax_rate: Decimal,
        over_under_provision: Decimal = Decimal(0),
        tax_paid: Decimal = Decimal(0),
    ) -> PSAK46CurrentTax:
        return PSAK46CurrentTax(
            current_tax_id=uuid4(),
            entity_id=entity_id,
            entity_name=entity_name,
            taxable_profit=taxable_profit,
            applicable_tax_rate=applicable_tax_rate,
            over_under_provision_previous=over_under_provision,
            tax_paid_ytd=tax_paid,
        )

    def create_temporary_difference(
        self,
        asset_liability_id: UUID,
        description: str,
        carrying_amount: Decimal,
        tax_base: Decimal,
        difference_type: PSAK46TemporaryDifferenceType,
        tax_rate: Decimal,
    ) -> PSAK46TemporaryDifference:
        return PSAK46TemporaryDifference(
            difference_id=uuid4(),
            asset_liability_id=asset_liability_id,
            description=description,
            carrying_amount=carrying_amount,
            tax_base=tax_base,
            difference_type=difference_type,
            tax_rate=tax_rate,
            temporary_difference=Decimal(0),
            deferred_tax_amount=Decimal(0),
        )

    def create_deferred_tax(
        self,
        entity_id: UUID,
        entity_name: str,
        applicable_tax_rate: Decimal = Decimal(22),
        taxable_differences: list[PSAK46TemporaryDifference] | None = None,
        deductible_differences: list[PSAK46TemporaryDifference] | None = None,
        tax_loss_carryforwards: Decimal = Decimal(0),
        tax_credit_carryforwards: Decimal = Decimal(0),
        valuation_allowance: Decimal = Decimal(0),
    ) -> PSAK46DeferredTax:
        return PSAK46DeferredTax(
            deferred_tax_id=uuid4(),
            entity_id=entity_id,
            entity_name=entity_name,
            taxable_temporary_differences=taxable_differences or [],
            deductible_temporary_differences=deductible_differences or [],
            tax_loss_carryforwards=tax_loss_carryforwards,
            tax_credit_carryforwards=tax_credit_carryforwards,
            valuation_allowance=valuation_allowance,
            applicable_tax_rate=applicable_tax_rate,
        )

    def create_reconciliation(
        self,
        entity_id: UUID,
        entity_name: str,
        accounting_profit_before_tax: Decimal,
        actual_tax_expense: Decimal,
        applicable_tax_rate: Decimal,
        differences: list[str] | None = None,
    ) -> PSAK46TaxReconciliation:
        return PSAK46TaxReconciliation(
            reconciliation_id=uuid4(),
            entity_id=entity_id,
            entity_name=entity_name,
            accounting_profit_before_tax=accounting_profit_before_tax,
            applicable_tax_rate=applicable_tax_rate,
            actual_tax_expense=actual_tax_expense,
            differences=differences or [],
        )

    def validate_deferred_tax(
        self, deferred_tax: PSAK46DeferredTax, probable_future_profit: Decimal
    ) -> PSAK46ValidationResult:
        result = self._rules.validate_deferred_tax_asset_recognition(
            deferred_tax.deferred_tax_asset_before_allowance,
            probable_future_profit,
        )
        return result

    def get_requirements_summary(self) -> dict:
        return {
            "current_tax": "Pajak kini diakui sebagai liabilitas sebesar estimasi pajak terutang",
            "deferred_tax_liability": "Diakui untuk semua perbedaan temporer kena pajak",
            "deferred_tax_asset": "Diakui untuk perbedaan temporer yang dapat dikurangkan, rugi fiskal, dan kredit pajak, sepanjang kemungkinan besar laba kena pajak akan tersedia",
            "measurement": "Menggunakan tarif pajak yang telah berlaku atau secara substantif berlaku pada akhir periode",
            "reconciliation": "Rekonsiliasi antara beban pajak efektif dengan tarif pajak yang berlaku harus diungkapkan",
            "disclosures": [
                "Komponen beban pajak (kini dan tangguhan)",
                "Rekonsiliasi tarif pajak",
                "Jumlah perbedaan temporer",
                "Rugi fiskal dan kredit pajak yang belum diakui",
            ],
        }


# ============================================================================
# Singleton Accessor
# ============================================================================
_psak46_validator_instance: PSAK46Validator | None = None


def get_psak46_validator() -> PSAK46Validator:
    global _psak46_validator_instance
    if _psak46_validator_instance is None:
        _psak46_validator_instance = PSAK46Validator()
    return _psak46_validator_instance


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    validator = get_psak46_validator()
    entity_id = uuid4()

    # Current tax
    current_tax = validator.create_current_tax(
        entity_id=entity_id,
        entity_name="PT Maju Jaya",
        taxable_profit=Decimal("1000000000"),
        applicable_tax_rate=Decimal("22"),
    )
    print("Current Tax:")
    print(json.dumps(current_tax.to_dict(), indent=2))

    # Temporary differences
    taxable_diff = validator.create_temporary_difference(
        asset_liability_id=uuid4(),
        description="Aset tetap (depresiasi lebih cepat secara fiskal)",
        carrying_amount=Decimal("500000000"),
        tax_base=Decimal("300000000"),
        difference_type=PSAK46TemporaryDifferenceType.TAXABLE,
        tax_rate=Decimal("22"),
    )
    deductible_diff = validator.create_temporary_difference(
        asset_liability_id=uuid4(),
        description="Provisi garansi",
        carrying_amount=Decimal("100000000"),
        tax_base=Decimal("0"),
        difference_type=PSAK46TemporaryDifferenceType.DEDUCTIBLE,
        tax_rate=Decimal("22"),
    )

    # Deferred tax
    deferred_tax = validator.create_deferred_tax(
        entity_id=entity_id,
        entity_name="PT Maju Jaya",
        applicable_tax_rate=Decimal("22"),
        taxable_differences=[taxable_diff],
        deductible_differences=[deductible_diff],
        tax_loss_carryforwards=Decimal("50000000"),
    )
    print("\nDeferred Tax:")
    print(json.dumps(deferred_tax.to_dict(), indent=2))

    # Reconciliation
    reconciliation = validator.create_reconciliation(
        entity_id=entity_id,
        entity_name="PT Maju Jaya",
        accounting_profit_before_tax=Decimal("1200000000"),
        actual_tax_expense=current_tax.current_tax_expense + deferred_tax.net_deferred_tax,
        applicable_tax_rate=Decimal("22"),
        differences=["Perbedaan permanen: biaya entertainment tidak dapat dikurangkan (10jt)"],
    )
    print("\nTax Reconciliation:")
    print(json.dumps(reconciliation.to_dict(), indent=2))

    # Validate deferred tax
    result = validator.validate_deferred_tax(
        deferred_tax, probable_future_profit=Decimal("200000000")
    )
    print("\nValidation Result:")
    print(json.dumps(result.to_dict(), indent=2))
# ============================================================================
# Compatibility aliases for package-level aggregator (__init__.py)
# ============================================================================
CurrentTax = PSAK46CurrentTax
DeferredTax = PSAK46DeferredTax
TaxReconciliation = PSAK46TaxReconciliation
TemporaryDifference = PSAK46TemporaryDifference

# ============================================================================
# Compatibility aliases for temporary difference variants
# ============================================================================
DeductibleTemporaryDifference = PSAK46TemporaryDifference
TaxableTemporaryDifference = PSAK46TemporaryDifference


# ============================================================================
# Compatibility class for TaxLossCarryforward representation
# ============================================================================
@dataclass
class TaxLossCarryforward:
    """Placeholder representation for tax loss carryforwards tracking."""

    amount: Decimal = Decimal(0)
    expiry_year: int | None = None
    description: str = "Akumulasi Rugi Fiskal"
