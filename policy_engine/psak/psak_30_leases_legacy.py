#!/usr/bin/env python3
"""
Module: psak_30_leases_legacy.py
Layer: 7 - Policy Engine & Standards / PSAK

Responsibility:
    PSAK 30: Sewa (Legacy - sebelum PSAK 73, setara dengan IAS 17).
    Mengatur akuntansi sewa untuk lessee dan lessor sebelum adopsi PSAK 73.
    Lessee mengklasifikasikan sewa sebagai sewa pembiayaan (finance lease)
    atau sewa operasi (operating lease). Sewa pembiayaan mengakui aset dan
    liabilitas sewa; sewa operasi mengakui beban sewa secara garis lurus.
    Lessor: sewa pembiayaan mengakui piutang sewa; sewa operasi tetap
    mengakui aset dan pendapatan sewa.

    Standar ini masih relevan untuk entitas yang belum mengadopsi PSAK 73,
    atau untuk perbandingan historis.

Dependencies:
    - datetime, decimal, enum, typing, dataclasses, uuid, hashlib, logging

Audit:
    Setiap kontrak sewa, klasifikasi, dan perhitungan amortisasi/liabilitas dicatat.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================
class PSAK30LeaseType(Enum):
    FINANCE = "pembiayaan"  # Finance lease (lessee recognizes asset and liability)
    OPERATING = "operasi"  # Operating lease (lessee recognizes expense)


class PSAK30AssetClass(Enum):
    PROPERTY = "properti"
    PLANT = "pabrik"
    EQUIPMENT = "peralatan"
    VEHICLE = "kendaraan"
    OTHER = "lainnya"


class PSAK30LeasePaymentTiming(Enum):
    IN_ADVANCE = "di_muka"  # Payment at beginning of period
    IN_ARREARS = "di_belakang"  # Payment at end of period


class PSAK30LessorType(Enum):
    FINANCE_LESSOR = "pembiayaan"
    OPERATING_LESSOR = "operasi"


class PSAK30ComplianceLevel(Enum):
    FULL = "penuh"
    SUBSTANTIAL = "substansial"
    PARTIAL = "sebagian"
    NON_COMPLIANT = "tidak_patuh"


# ============================================================================
# Exceptions
# ============================================================================
class PSAK30Error(Exception):
    pass


class LeaseClassificationError(PSAK30Error):
    pass


# ============================================================================
# Data Classes
# ============================================================================
@dataclass
class PSAK30LeaseContract:
    """Kontrak sewa (baik lessee atau lessor)."""

    contract_id: UUID
    contract_number: str
    lessor_name: str
    lessee_name: str
    asset_description: str
    asset_class: PSAK30AssetClass
    commencement_date: datetime
    lease_term_years: int
    annual_payment: Decimal
    interest_rate_implicit: Decimal  # Tingkat bunga implisit (dalam persen)
    fair_value_asset: Decimal  # Nilai wajar aset pada awal sewa
    guaranteed_residual_value: Decimal = Decimal(0)
    bargain_purchase_option: Decimal | None = None  # Harga opsi pembelian murah
    payment_timing: PSAK30LeasePaymentTiming = PSAK30LeasePaymentTiming.IN_ARREARS
    is_renewable: bool = False
    renewal_term_years: int = 0
    notes: str = ""

    @property
    def total_payments_undiscounted(self) -> Decimal:
        return self.annual_payment * Decimal(self.lease_term_years)

    def present_value_of_minimum_lease_payments(
        self, discount_rate: Decimal | None = None
    ) -> Decimal:
        """Menghitung nilai kini pembayaran sewa minimum."""
        rate = (discount_rate or self.interest_rate_implicit) / 100
        if rate == 0:
            return self.total_payments_undiscounted
        pv = Decimal(0)
        for t in range(1, self.lease_term_years + 1):
            if self.payment_timing == PSAK30LeasePaymentTiming.IN_ADVANCE:
                factor = (1 + rate) ** (t - 1)
            else:
                factor = (1 + rate) ** t
            pv += self.annual_payment / factor
        return pv.quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)

    def is_finance_lease_lessee(self) -> bool:
        """Kriteria klasifikasi sewa pembiayaan untuk lessee (PSAK 30)."""
        pv_payments = self.present_value_of_minimum_lease_payments()
        # Transfer of ownership, bargain purchase option, lease term covering major part of economic life,
        # PV of payments substantially all of fair value, asset is specialized.
        if self.bargain_purchase_option is not None:
            return True
        if self.lease_term_years >= 0.75 * 20:  # Example: economic life assumed 20 years
            return True
        if pv_payments >= 0.9 * self.fair_value_asset:
            return True
        return False

    def to_dict(self) -> dict:
        return {
            "contract_id": str(self.contract_id),
            "contract_number": self.contract_number,
            "lessor": self.lessor_name,
            "lessee": self.lessee_name,
            "asset": self.asset_description,
            "asset_class": self.asset_class.value,
            "commencement": self.commencement_date.isoformat(),
            "lease_term_years": self.lease_term_years,
            "annual_payment": str(self.annual_payment),
            "interest_rate": str(self.interest_rate_implicit),
            "fair_value": str(self.fair_value_asset),
            "payment_timing": self.payment_timing.value,
            "is_finance_lease": self.is_finance_lease_lessee(),
        }


@dataclass
class PSAK30FinanceLeaseLiability:
    """Liabilitas sewa pembiayaan untuk lessee."""

    liability_id: UUID
    contract_id: UUID
    initial_liability: Decimal  # Nilai kini pembayaran sewa pada awal
    outstanding_balance: Decimal
    interest_expense_ytd: Decimal = Decimal(0)
    principal_paid_ytd: Decimal = Decimal(0)
    last_payment_date: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "liability_id": str(self.liability_id),
            "contract_id": str(self.contract_id),
            "initial_liability": str(self.initial_liability),
            "outstanding_balance": str(self.outstanding_balance),
            "interest_expense_ytd": str(self.interest_expense_ytd),
            "principal_paid_ytd": str(self.principal_paid_ytd),
        }


@dataclass
class PSAK30FinanceLeaseAsset:
    """Aset hak-guna untuk lessee (sewa pembiayaan)."""

    asset_id: UUID
    contract_id: UUID
    asset_cost: Decimal  # Nilai awal aset (sama dengan liabilitas awal)
    accumulated_depreciation: Decimal = Decimal(0)
    depreciation_method: str = "straight_line"
    useful_life_years: int = 0

    def carrying_amount(self) -> Decimal:
        return self.asset_cost - self.accumulated_depreciation

    def annual_depreciation(self) -> Decimal:
        if self.useful_life_years == 0:
            return Decimal(0)
        return (self.asset_cost / Decimal(self.useful_life_years)).quantize(
            Decimal("0"), rounding=ROUND_HALF_EVEN
        )

    def to_dict(self) -> dict:
        return {
            "asset_id": str(self.asset_id),
            "contract_id": str(self.contract_id),
            "asset_cost": str(self.asset_cost),
            "accumulated_depreciation": str(self.accumulated_depreciation),
            "carrying_amount": str(self.carrying_amount()),
        }


@dataclass
class PSAK30OperatingLeaseExpense:
    """Beban sewa operasi untuk lessee."""

    expense_id: UUID
    contract_id: UUID
    period_start: datetime
    period_end: datetime
    lease_expense: Decimal  # Beban sewa garis lurus untuk periode
    actual_payment: Decimal
    prepaid_accrued: Decimal = Decimal(0)

    def to_dict(self) -> dict:
        return {
            "expense_id": str(self.expense_id),
            "contract_id": str(self.contract_id),
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "lease_expense": str(self.lease_expense),
            "actual_payment": str(self.actual_payment),
        }


@dataclass
class PSAK30LessorFinanceLeaseReceivable:
    """Piutang sewa pembiayaan untuk lessor."""

    receivable_id: UUID
    contract_id: UUID
    gross_investment: Decimal  # Total pembayaran sewa + nilai residu tidak dijamin
    unearned_finance_income: Decimal  # Pendapatan bunga yang belum diakui
    net_investment: Decimal
    finance_income_ytd: Decimal = Decimal(0)

    def to_dict(self) -> dict:
        return {
            "receivable_id": str(self.receivable_id),
            "contract_id": str(self.contract_id),
            "gross_investment": str(self.gross_investment),
            "unearned_income": str(self.unearned_finance_income),
            "net_investment": str(self.net_investment),
        }


@dataclass
class PSAK30ValidationResult:
    is_compliant: bool
    compliance_level: PSAK30ComplianceLevel
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
        if self.compliance_level != PSAK30ComplianceLevel.NON_COMPLIANT:
            self.compliance_level = PSAK30ComplianceLevel.NON_COMPLIANT

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)
        if self.compliance_level == PSAK30ComplianceLevel.FULL:
            self.compliance_level = PSAK30ComplianceLevel.SUBSTANTIAL

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
class PSAK30LeaseService:
    """Service untuk perhitungan sewa."""

    @staticmethod
    def allocate_lease_payment(
        outstanding: Decimal,
        annual_payment: Decimal,
        interest_rate: Decimal,
        is_advance: bool,
    ) -> tuple[Decimal, Decimal]:
        """Mengalokasikan pembayaran tahunan ke bunga dan pokok."""
        if is_advance:
            # Pembayaran di awal tahun: seluruhnya mengurangi pokok (bunga belum diakui)
            interest = Decimal(0)
            principal = annual_payment
        else:
            interest = (outstanding * (interest_rate / 100)).quantize(
                Decimal("0"), rounding=ROUND_HALF_EVEN
            )
            principal = min(annual_payment - interest, outstanding)
        return interest, principal

    @staticmethod
    def calculate_operating_lease_expense(annual_payment: Decimal, lease_term: int) -> Decimal:
        """Beban sewa garis lurus per tahun."""
        return annual_payment

    @staticmethod
    def calculate_lessor_finance_income(
        net_investment: Decimal,
        interest_rate: Decimal,
        days_in_year: int = 365,
    ) -> Decimal:
        return (net_investment * (interest_rate / 100)).quantize(
            Decimal("0"), rounding=ROUND_HALF_EVEN
        )


# ============================================================================
# Rules
# ============================================================================
class PSAK30Rules:
    """Aturan PSAK 30."""

    @staticmethod
    def validate_lease_classification(contract: PSAK30LeaseContract) -> PSAK30ValidationResult:
        result = PSAK30ValidationResult(
            is_compliant=True, compliance_level=PSAK30ComplianceLevel.FULL
        )
        if contract.annual_payment <= 0:
            result.add_error("Pembayaran sewa tahunan harus positif")
        if contract.interest_rate_implicit < 0:
            result.add_error("Tingkat bunga implisit tidak boleh negatif")
        if contract.fair_value_asset <= 0:
            result.add_warning(
                "Nilai wajar aset tidak diketahui, klasifikasi sewa mungkin tidak akurat"
            )
        return result

    @staticmethod
    def validate_disclosure(contracts: list[PSAK30LeaseContract]) -> PSAK30ValidationResult:
        result = PSAK30ValidationResult(
            is_compliant=True, compliance_level=PSAK30ComplianceLevel.FULL
        )
        finance_count = sum(1 for c in contracts if c.is_finance_lease_lessee())
        if finance_count > 0 and not any(c.is_finance_lease_lessee() for c in contracts):
            result.add_warning("Terdapat sewa pembiayaan tetapi tidak diungkapkan kebijakannya")
        return result


# ============================================================================
# Validator
# ============================================================================
class PSAK30Validator:
    def __init__(self):
        self._rules = PSAK30Rules()
        self._service = PSAK30LeaseService()

    def create_lease_contract(
        self,
        contract_number: str,
        lessor_name: str,
        lessee_name: str,
        asset_description: str,
        asset_class: PSAK30AssetClass,
        commencement_date: datetime,
        lease_term_years: int,
        annual_payment: Decimal,
        interest_rate_implicit: Decimal,
        fair_value_asset: Decimal,
        guaranteed_residual_value: Decimal = Decimal(0),
        bargain_purchase_option: Decimal | None = None,
        payment_timing: PSAK30LeasePaymentTiming = PSAK30LeasePaymentTiming.IN_ARREARS,
    ) -> PSAK30LeaseContract:
        return PSAK30LeaseContract(
            contract_id=uuid4(),
            contract_number=contract_number,
            lessor_name=lessor_name,
            lessee_name=lessee_name,
            asset_description=asset_description,
            asset_class=asset_class,
            commencement_date=commencement_date,
            lease_term_years=lease_term_years,
            annual_payment=annual_payment,
            interest_rate_implicit=interest_rate_implicit,
            fair_value_asset=fair_value_asset,
            guaranteed_residual_value=guaranteed_residual_value,
            bargain_purchase_option=bargain_purchase_option,
            payment_timing=payment_timing,
        )

    def compute_lessee_finance_lease_liability(
        self, contract: PSAK30LeaseContract
    ) -> PSAK30FinanceLeaseLiability:
        pv = contract.present_value_of_minimum_lease_payments()
        return PSAK30FinanceLeaseLiability(
            liability_id=uuid4(),
            contract_id=contract.contract_id,
            initial_liability=pv,
            outstanding_balance=pv,
        )

    def compute_lessee_finance_lease_asset(
        self, contract: PSAK30LeaseContract, useful_life_years: int
    ) -> PSAK30FinanceLeaseAsset:
        pv = contract.present_value_of_minimum_lease_payments()
        return PSAK30FinanceLeaseAsset(
            asset_id=uuid4(),
            contract_id=contract.contract_id,
            asset_cost=pv,
            useful_life_years=useful_life_years,
        )

    def record_annual_payment_lessee_finance(
        self,
        liability: PSAK30FinanceLeaseLiability,
        contract: PSAK30LeaseContract,
        payment_date: datetime,
    ) -> tuple[PSAK30FinanceLeaseLiability, Decimal, Decimal]:
        is_advance = contract.payment_timing == PSAK30LeasePaymentTiming.IN_ADVANCE
        interest, principal = self._service.allocate_lease_payment(
            liability.outstanding_balance,
            contract.annual_payment,
            contract.interest_rate_implicit,
            is_advance,
        )
        new_balance = liability.outstanding_balance - principal
        new_interest = liability.interest_expense_ytd + interest
        new_principal_paid = liability.principal_paid_ytd + principal
        new_liability = PSAK30FinanceLeaseLiability(
            liability_id=liability.liability_id,
            contract_id=liability.contract_id,
            initial_liability=liability.initial_liability,
            outstanding_balance=new_balance,
            interest_expense_ytd=new_interest,
            principal_paid_ytd=new_principal_paid,
            last_payment_date=payment_date,
        )
        return new_liability, interest, principal

    def record_depreciation_finance_asset(
        self,
        asset: PSAK30FinanceLeaseAsset,
        period_end: datetime,
    ) -> PSAK30FinanceLeaseAsset:
        annual_dep = asset.annual_depreciation()
        new_dep = asset.accumulated_depreciation + annual_dep
        return PSAK30FinanceLeaseAsset(
            asset_id=asset.asset_id,
            contract_id=asset.contract_id,
            asset_cost=asset.asset_cost,
            accumulated_depreciation=new_dep,
            depreciation_method=asset.depreciation_method,
            useful_life_years=asset.useful_life_years,
        )

    def validate_contract(self, contract: PSAK30LeaseContract) -> PSAK30ValidationResult:
        return self._rules.validate_lease_classification(contract)

    def get_requirements_summary(self) -> dict:
        return {
            "classification": "Lessee mengklasifikasikan sewa sebagai pembiayaan jika memenuhi kriteria (transfer kepemilikan, opsi beli murah, masa sewa substansial, nilai kini pembayaran â‰¥ 90% nilai wajar, aset khusus)",
            "finance_lease_lessee": "Mengakui aset dan liabilitas sebesar nilai kini pembayaran sewa minimum",
            "operating_lease_lessee": "Mengakui beban sewa secara garis lurus",
            "finance_lease_lessor": "Mengakui piutang sewa dan pendapatan bunga",
            "operating_lease_lessor": "Mengakui aset tetap dan pendapatan sewa",
            "disclosures": [
                "Klasifikasi sewa (pembiayaan/operasi)",
                "Rekonsiliasi pembayaran sewa minimum masa depan",
                "Beban sewa operasi",
                "Piutang sewa pembiayaan",
            ],
        }


# ============================================================================
# Singleton Accessor
# ============================================================================
_psak30_validator_instance: PSAK30Validator | None = None


def get_psak30_validator() -> PSAK30Validator:
    global _psak30_validator_instance
    if _psak30_validator_instance is None:
        _psak30_validator_instance = PSAK30Validator()
    return _psak30_validator_instance


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    validator = get_psak30_validator()

    # Contoh kontrak sewa pembiayaan
    finance_lease = validator.create_lease_contract(
        contract_number="L-001",
        lessor_name="PT Sewa Guna Usaha",
        lessee_name="PT Manufaktur",
        asset_description="Mesin Produksi X200",
        asset_class=PSAK30AssetClass.EQUIPMENT,
        commencement_date=datetime(2026, 1, 1, tzinfo=UTC),
        lease_term_years=5,
        annual_payment=Decimal("100000000"),
        interest_rate_implicit=Decimal("10"),
        fair_value_asset=Decimal("500000000"),
        bargain_purchase_option=Decimal("10000000"),
        payment_timing=PSAK30LeasePaymentTiming.IN_ARREARS,
    )

    # Klasifikasi
    print("Apakah finance lease?", finance_lease.is_finance_lease_lessee())

    # Hitung liabilitas awal
    liability = validator.compute_lessee_finance_lease_liability(finance_lease)
    print(f"Liabilitas awal: {liability.initial_liability}")

    # Rekam pembayaran tahun pertama
    new_liability, interest, principal = validator.record_annual_payment_lessee_finance(
        liability, finance_lease, datetime(2026, 12, 31, tzinfo=UTC)
    )
    print(
        f"Tahun 1 - Bunga: {interest}, Pokok: {principal}, Sisa: {new_liability.outstanding_balance}"
    )

    # Validasi
    result = validator.validate_contract(finance_lease)
    print("\nValidation Result:")
    print(json.dumps(result.to_dict(), indent=2))
# ============================================================================
# Compatibility alias for package-level aggregator
# ============================================================================
LeasePaymentTimingLegacy = PSAK30LeasePaymentTiming

# ============================================================================
# Compatibility alias for package-level aggregator
# ============================================================================
LegacyLeaseClassification = PSAK30LeaseType

# ============================================================================
# Compatibility alias for contract object mapping
# ============================================================================
LegacyLeaseContract = PSAK30LeaseContract
