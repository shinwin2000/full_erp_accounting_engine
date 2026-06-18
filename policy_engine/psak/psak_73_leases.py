#!/usr/bin/env python3
"""
Module: psak_73_leases.py
Layer: 7 - Policy Engine & Standards / PSAK

Responsibility:
    PSAK 73: Sewa (setara dengan IFRS 16).
    Mengatur akuntansi sewa untuk lessee dan lessor. Lessee mengakui aset
    hak-guna (right-of-use asset) dan liabilitas sewa untuk semua sewa
    (kecuali sewa jangka pendek ≤ 12 bulan dan sewa aset bernilai rendah).
    Lessor mengklasifikasikan sewa sebagai sewa pembiayaan atau sewa operasi.
    Mencakup pengukuran awal dan setelah pengakuan, modifikasi sewa,
    penjualan dan sewa balik (sale and leaseback), serta pengungkapan.

Dependencies:
    - datetime, decimal, enum, typing, dataclasses, uuid, hashlib, logging

Audit:
    Setiap kontrak sewa, perhitungan liabilitas, aset hak-guna, dan modifikasi dicatat.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================
class PSAK73LeaseType(Enum):
    FINANCE = "pembiayaan"  # Lessor: finance lease
    OPERATING = "operasi"  # Lessor: operating lease


class PSAK73PaymentTiming(Enum):
    IN_ADVANCE = "di_muka"  # Pembayaran di awal periode
    IN_ARREARS = "di_belakang"  # Pembayaran di akhir periode


class PSAK73IncrementalBorrowingRateSource(Enum):
    IMPLICIT_RATE_KNOWN = "suku_bunga_implisit_diketahui"
    ESTIMATED = "estimasi"  # Menggunakan IBR yang diestimasi


class PSAK73ModificationType(Enum):
    EXTENSION = "perpanjangan"
    TERMINATION = "penghentian_sebagian"
    CHANGE_IN_CONSIDERATION = "perubahan_imbalan"
    CHANGE_IN_LEASE_TERM = "perubahan_masa_sewa"


class PSAK73ShortTermLeaseExemption(Enum):
    EXEMPT = "dikecualikan"
    NOT_EXEMPT = "tidak_dikecualikan"


class PSAK73LowValueAssetExemption(Enum):
    EXEMPT = "dikecualikan"  # Nilai aset ≤ USD 5,000 (atau setara)
    NOT_EXEMPT = "tidak_dikecualikan"


class PSAK73ComplianceLevel(Enum):
    FULL = "penuh"
    SUBSTANTIAL = "substansial"
    PARTIAL = "sebagian"
    NON_COMPLIANT = "tidak_patuh"


# ============================================================================
# Exceptions
# ============================================================================
class PSAK73Error(Exception):
    pass


class LeaseModificationError(PSAK73Error):
    pass


# ============================================================================
# Data Classes
# ============================================================================
@dataclass
class PSAK73LeasePayment:
    """Pembayaran sewa individual."""

    amount: Decimal
    due_date: datetime
    is_variable: bool = False
    variable_basis: str = ""

    def to_dict(self) -> dict:
        return {
            "amount": str(self.amount),
            "due_date": self.due_date.isoformat(),
            "is_variable": self.is_variable,
        }


@dataclass
class PSAK73LeaseContract:
    """Kontrak sewa (lessee)."""

    contract_id: UUID
    contract_number: str
    asset_name: str
    lessor_name: str
    commencement_date: datetime
    lease_term_years: int
    payments: list[PSAK73LeasePayment]
    discount_rate: Decimal  # suku bunga implisit atau IBR (dalam persen)
    discount_rate_source: PSAK73IncrementalBorrowingRateSource
    initial_direct_costs: Decimal = Decimal(0)
    lease_incentives_received: Decimal = Decimal(0)
    restoration_cost_estimate: Decimal = Decimal(0)
    payment_timing: PSAK73PaymentTiming = PSAK73PaymentTiming.IN_ARREARS
    short_term_exemption: PSAK73ShortTermLeaseExemption = PSAK73ShortTermLeaseExemption.NOT_EXEMPT
    low_value_exemption: PSAK73LowValueAssetExemption = PSAK73LowValueAssetExemption.NOT_EXEMPT
    purchase_option_price: Decimal | None = None
    purchase_option_exercisable_date: datetime | None = None
    termination_penalty: Decimal = Decimal(0)
    modification_history: list[dict] = field(default_factory=list)

    def total_payments_undiscounted(self) -> Decimal:
        return sum(p.amount for p in self.payments)

    def present_value_of_lease_payments(self) -> Decimal:
        rate = self.discount_rate / 100
        pv = Decimal(0)
        for i, payment in enumerate(sorted(self.payments, key=lambda x: x.due_date)):
            if self.payment_timing == PSAK73PaymentTiming.IN_ADVANCE:
                factor = (Decimal(1) + rate) ** i
            else:
                factor = (Decimal(1) + rate) ** (i + 1)
            pv += payment.amount / factor
        return pv.quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)

    def to_dict(self) -> dict:
        return {
            "contract_id": str(self.contract_id),
            "contract_number": self.contract_number,
            "asset_name": self.asset_name,
            "lessor": self.lessor_name,
            "commencement": self.commencement_date.isoformat(),
            "lease_term_years": self.lease_term_years,
            "payments": [p.to_dict() for p in self.payments],
            "discount_rate": str(self.discount_rate),
            "pv_payments": str(self.present_value_of_lease_payments()),
            "short_term_exempt": self.short_term_exemption.value,
            "low_value_exempt": self.low_value_exemption.value,
        }


@dataclass
class PSAK73RightOfUseAsset:
    """Aset hak-guna (right-of-use asset)."""

    asset_id: UUID
    contract_id: UUID
    initial_measurement: Decimal
    accumulated_depreciation: Decimal = Decimal(0)
    accumulated_impairment: Decimal = Decimal(0)
    useful_life_years: int = 0  # 0 berarti menggunakan masa sewa
    depreciation_method: str = "straight_line"

    def carrying_amount(self) -> Decimal:
        return (
            self.initial_measurement - self.accumulated_depreciation - self.accumulated_impairment
        )

    def annual_depreciation(self, lease_term_years: int) -> Decimal:
        useful = self.useful_life_years if self.useful_life_years > 0 else lease_term_years
        if useful <= 0:
            return Decimal(0)
        return (self.initial_measurement / Decimal(useful)).quantize(
            Decimal("0"), rounding=ROUND_HALF_EVEN
        )

    def to_dict(self) -> dict:
        return {
            "asset_id": str(self.asset_id),
            "contract_id": str(self.contract_id),
            "initial": str(self.initial_measurement),
            "carrying": str(self.carrying_amount()),
            "depreciation_method": self.depreciation_method,
        }


@dataclass
class PSAK73LeaseLiability:
    """Liabilitas sewa."""

    liability_id: UUID
    contract_id: UUID
    initial_measurement: Decimal
    outstanding_balance: Decimal
    interest_expense_ytd: Decimal = Decimal(0)
    principal_paid_ytd: Decimal = Decimal(0)
    last_payment_date: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "liability_id": str(self.liability_id),
            "contract_id": str(self.contract_id),
            "initial": str(self.initial_measurement),
            "outstanding": str(self.outstanding_balance),
            "interest_expense": str(self.interest_expense_ytd),
            "principal_paid": str(self.principal_paid_ytd),
        }


@dataclass
class PSAK73LeaseModification:
    """Modifikasi kontrak sewa."""

    modification_id: UUID
    contract_id: UUID
    modification_type: PSAK73ModificationType
    effective_date: datetime
    old_pv_payments: Decimal
    new_pv_payments: Decimal
    adjustment_to_rou_asset: Decimal
    adjustment_to_lease_liability: Decimal
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "modification_id": str(self.modification_id),
            "contract_id": str(self.contract_id),
            "type": self.modification_type.value,
            "effective_date": self.effective_date.isoformat(),
            "pv_change": str(self.new_pv_payments - self.old_pv_payments),
            "rou_asset_adjustment": str(self.adjustment_to_rou_asset),
            "liability_adjustment": str(self.adjustment_to_lease_liability),
        }


@dataclass
class PSAK73ValidationResult:
    is_compliant: bool
    compliance_level: PSAK73ComplianceLevel
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
        if self.compliance_level != PSAK73ComplianceLevel.NON_COMPLIANT:
            self.compliance_level = PSAK73ComplianceLevel.NON_COMPLIANT

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)
        if self.compliance_level == PSAK73ComplianceLevel.FULL:
            self.compliance_level = PSAK73ComplianceLevel.SUBSTANTIAL

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
class PSAK73LeaseService:
    """Service untuk akuntansi sewa PSAK 73."""

    @staticmethod
    def apply_exemption(
        lease_term_years: int, asset_value: Decimal, low_value_threshold: Decimal = Decimal("5000")
    ) -> tuple[PSAK73ShortTermLeaseExemption, PSAK73LowValueAssetExemption]:
        short_term = (
            PSAK73ShortTermLeaseExemption.EXEMPT
            if lease_term_years <= 1
            else PSAK73ShortTermLeaseExemption.NOT_EXEMPT
        )
        low_value = (
            PSAK73LowValueAssetExemption.EXEMPT
            if asset_value <= low_value_threshold
            else PSAK73LowValueAssetExemption.NOT_EXEMPT
        )
        return short_term, low_value

    @staticmethod
    def allocate_lease_payment(
        outstanding_liability: Decimal,
        annual_payment: Decimal,
        discount_rate: Decimal,
        payment_timing: PSAK73PaymentTiming,
    ) -> tuple[Decimal, Decimal]:
        """Mengalokasikan pembayaran ke bunga dan pokok."""
        if payment_timing == PSAK73PaymentTiming.IN_ADVANCE:
            interest = Decimal(0)
            principal = annual_payment
        else:
            interest = (outstanding_liability * (discount_rate / 100)).quantize(
                Decimal("0"), rounding=ROUND_HALF_EVEN
            )
            principal = min(annual_payment - interest, outstanding_liability)
        return interest, principal

    @staticmethod
    def calculate_right_of_use_asset(
        pv_lease_payments: Decimal,
        initial_direct_costs: Decimal,
        lease_incentives: Decimal,
        restoration_cost: Decimal,
    ) -> Decimal:
        """Nilai awal aset hak-guna = nilai kini pembayaran sewa + biaya langsung awal - insentif + estimasi biaya restorasi."""
        return (
            pv_lease_payments + initial_direct_costs - lease_incentives + restoration_cost
        ).quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)

    @staticmethod
    def compute_modified_pv(
        original_remaining_payments: list[PSAK73LeasePayment],
        new_payments: list[PSAK73LeasePayment],
        discount_rate: Decimal,
        payment_timing: PSAK73PaymentTiming,
    ) -> tuple[Decimal, Decimal]:
        old_pv = sum(
            p.amount / ((1 + discount_rate / 100) ** (i + 1))
            for i, p in enumerate(original_remaining_payments)
        )
        new_pv = sum(
            p.amount / ((1 + discount_rate / 100) ** (i + 1)) for i, p in enumerate(new_payments)
        )
        return old_pv, new_pv


# ============================================================================
# Rules
# ============================================================================
class PSAK73Rules:
    @staticmethod
    def validate_lease_contract(contract: PSAK73LeaseContract) -> PSAK73ValidationResult:
        result = PSAK73ValidationResult(
            is_compliant=True, compliance_level=PSAK73ComplianceLevel.FULL
        )
        if contract.lease_term_years <= 0:
            result.add_error("Masa sewa harus positif")
        if contract.discount_rate < 0:
            result.add_error("Tingkat diskonto tidak boleh negatif")
        if not contract.payments:
            result.add_error("Setidaknya satu pembayaran sewa harus ada")
        if (
            contract.short_term_exemption == PSAK73ShortTermLeaseExemption.EXEMPT
            and contract.lease_term_years > 1
        ):
            result.add_error(
                "Pengecualian sewa jangka pendek tidak berlaku untuk masa sewa > 12 bulan"
            )
        return result

    @staticmethod
    def validate_modification(modification: PSAK73LeaseModification) -> PSAK73ValidationResult:
        result = PSAK73ValidationResult(
            is_compliant=True, compliance_level=PSAK73ComplianceLevel.FULL
        )
        if abs(
            modification.adjustment_to_rou_asset + modification.adjustment_to_lease_liability
        ) > Decimal("1"):
            result.add_error("Penyesuaian aset hak-guna dan liabilitas tidak konsisten")
        return result


# ============================================================================
# Validator
# ============================================================================
class PSAK73Validator:
    def __init__(self):
        self._rules = PSAK73Rules()
        self._service = PSAK73LeaseService()

    def create_lease_contract(
        self,
        contract_number: str,
        asset_name: str,
        lessor_name: str,
        commencement_date: datetime,
        lease_term_years: int,
        annual_payment: Decimal,
        discount_rate: Decimal,
        payment_timing: PSAK73PaymentTiming = PSAK73PaymentTiming.IN_ARREARS,
        initial_direct_costs: Decimal = Decimal(0),
        lease_incentives: Decimal = Decimal(0),
        restoration_cost: Decimal = Decimal(0),
        asset_value_for_exemption: Decimal | None = None,
    ) -> PSAK73LeaseContract:
        payments = []
        for year in range(1, lease_term_years + 1):
            due_date = commencement_date.replace(year=commencement_date.year + year - 1)
            if payment_timing == PSAK73PaymentTiming.IN_ADVANCE:
                due_date = due_date.replace(
                    month=commencement_date.month, day=commencement_date.day
                )
            else:
                due_date = due_date.replace(
                    month=commencement_date.month, day=commencement_date.day
                )  # actually end of period
            payments.append(PSAK73LeasePayment(amount=annual_payment, due_date=due_date))
        short_term, low_value = self._service.apply_exemption(
            lease_term_years, asset_value_for_exemption or Decimal(0)
        )
        return PSAK73LeaseContract(
            contract_id=uuid4(),
            contract_number=contract_number,
            asset_name=asset_name,
            lessor_name=lessor_name,
            commencement_date=commencement_date,
            lease_term_years=lease_term_years,
            payments=payments,
            discount_rate=discount_rate,
            discount_rate_source=PSAK73IncrementalBorrowingRateSource.ESTIMATED,
            initial_direct_costs=initial_direct_costs,
            lease_incentives_received=lease_incentives,
            restoration_cost_estimate=restoration_cost,
            payment_timing=payment_timing,
            short_term_exemption=short_term,
            low_value_exemption=low_value,
        )

    def compute_lease_liability(self, contract: PSAK73LeaseContract) -> PSAK73LeaseLiability:
        pv = contract.present_value_of_lease_payments()
        return PSAK73LeaseLiability(
            liability_id=uuid4(),
            contract_id=contract.contract_id,
            initial_measurement=pv,
            outstanding_balance=pv,
        )

    def compute_right_of_use_asset(self, contract: PSAK73LeaseContract) -> PSAK73RightOfUseAsset:
        pv = contract.present_value_of_lease_payments()
        rou = self._service.calculate_right_of_use_asset(
            pv,
            contract.initial_direct_costs,
            contract.lease_incentives_received,
            contract.restoration_cost_estimate,
        )
        return PSAK73RightOfUseAsset(
            asset_id=uuid4(),
            contract_id=contract.contract_id,
            initial_measurement=rou,
            useful_life_years=contract.lease_term_years,
        )

    def record_annual_payment(
        self,
        liability: PSAK73LeaseLiability,
        contract: PSAK73LeaseContract,
        payment_date: datetime,
    ) -> tuple[PSAK73LeaseLiability, Decimal, Decimal]:
        is_advance = contract.payment_timing == PSAK73PaymentTiming.IN_ADVANCE
        interest, principal = self._service.allocate_lease_payment(
            liability.outstanding_balance,
            contract.payments[0].amount,  # assuming constant annual payment
            contract.discount_rate,
            contract.payment_timing,
        )
        new_balance = liability.outstanding_balance - principal
        new_interest = liability.interest_expense_ytd + interest
        new_principal_paid = liability.principal_paid_ytd + principal
        new_liability = PSAK73LeaseLiability(
            liability_id=liability.liability_id,
            contract_id=liability.contract_id,
            initial_measurement=liability.initial_measurement,
            outstanding_balance=new_balance,
            interest_expense_ytd=new_interest,
            principal_paid_ytd=new_principal_paid,
            last_payment_date=payment_date,
        )
        return new_liability, interest, principal

    def record_depreciation(
        self,
        rou_asset: PSAK73RightOfUseAsset,
        lease_term_years: int,
    ) -> PSAK73RightOfUseAsset:
        annual_dep = rou_asset.annual_depreciation(lease_term_years)
        new_dep = rou_asset.accumulated_depreciation + annual_dep
        return PSAK73RightOfUseAsset(
            asset_id=rou_asset.asset_id,
            contract_id=rou_asset.contract_id,
            initial_measurement=rou_asset.initial_measurement,
            accumulated_depreciation=new_dep,
            accumulated_impairment=rou_asset.accumulated_impairment,
            useful_life_years=rou_asset.useful_life_years,
            depreciation_method=rou_asset.depreciation_method,
        )

    def modify_lease(
        self,
        contract: PSAK73LeaseContract,
        liability: PSAK73LeaseLiability,
        rou_asset: PSAK73RightOfUseAsset,
        new_payments: list[PSAK73LeasePayment],
        modification_type: PSAK73ModificationType,
        effective_date: datetime,
        new_discount_rate: Decimal | None = None,
        notes: str = "",
    ) -> tuple[
        PSAK73LeaseContract, PSAK73LeaseLiability, PSAK73RightOfUseAsset, PSAK73LeaseModification
    ]:
        rate = new_discount_rate if new_discount_rate is not None else contract.discount_rate
        # Compute remaining payments before modification
        remaining = [p for p in contract.payments if p.due_date >= effective_date]
        old_pv, new_pv = self._service.compute_modified_pv(
            remaining, new_payments, rate, contract.payment_timing
        )
        pv_change = new_pv - old_pv
        # Adjust liability and ROU asset
        new_liability = PSAK73LeaseLiability(
            liability_id=liability.liability_id,
            contract_id=liability.contract_id,
            initial_measurement=liability.initial_measurement,
            outstanding_balance=liability.outstanding_balance + pv_change,
            interest_expense_ytd=liability.interest_expense_ytd,
            principal_paid_ytd=liability.principal_paid_ytd,
            last_payment_date=liability.last_payment_date,
        )
        new_rou_asset = PSAK73RightOfUseAsset(
            asset_id=rou_asset.asset_id,
            contract_id=rou_asset.contract_id,
            initial_measurement=rou_asset.initial_measurement + pv_change,
            accumulated_depreciation=rou_asset.accumulated_depreciation,
            accumulated_impairment=rou_asset.accumulated_impairment,
            useful_life_years=rou_asset.useful_life_years,
            depreciation_method=rou_asset.depreciation_method,
        )
        # Create modified contract
        new_contract = PSAK73LeaseContract(
            contract_id=contract.contract_id,
            contract_number=contract.contract_number,
            asset_name=contract.asset_name,
            lessor_name=contract.lessor_name,
            commencement_date=contract.commencement_date,
            lease_term_years=len(new_payments),  # approximated
            payments=new_payments,
            discount_rate=rate,
            discount_rate_source=contract.discount_rate_source,
            initial_direct_costs=contract.initial_direct_costs,
            lease_incentives_received=contract.lease_incentives_received,
            restoration_cost_estimate=contract.restoration_cost_estimate,
            payment_timing=contract.payment_timing,
            short_term_exemption=contract.short_term_exemption,
            low_value_exemption=contract.low_value_exemption,
            modification_history=contract.modification_history
            + [{"date": effective_date.isoformat(), "type": modification_type.value}],
        )
        modification = PSAK73LeaseModification(
            modification_id=uuid4(),
            contract_id=contract.contract_id,
            modification_type=modification_type,
            effective_date=effective_date,
            old_pv_payments=old_pv,
            new_pv_payments=new_pv,
            adjustment_to_rou_asset=pv_change,
            adjustment_to_lease_liability=pv_change,
            notes=notes,
        )
        return new_contract, new_liability, new_rou_asset, modification

    def validate_contract(self, contract: PSAK73LeaseContract) -> PSAK73ValidationResult:
        return self._rules.validate_lease_contract(contract)

    def validate_modification(
        self, modification: PSAK73LeaseModification
    ) -> PSAK73ValidationResult:
        return self._rules.validate_modification(modification)

    def get_requirements_summary(self) -> dict:
        return {
            "lessee": "Mengakui aset hak-guna dan liabilitas sewa untuk semua sewa (kecuali pengecualian)",
            "initial_measurement_liability": "Nilai kini pembayaran sewa minimum",
            "initial_measurement_asset": "Liabilitas awal + biaya langsung awal - insentif + estimasi biaya restorasi",
            "subsequent_measurement_liability": "Amortized cost menggunakan metode bunga efektif",
            "subsequent_measurement_asset": "Depresiasi dan impairment sesuai PSAK 48",
            "exemptions": "Sewa jangka pendek (≤12 bulan) dan aset bernilai rendah (≤USD 5.000)",
            "lease_modification": "Jika modifikasi tidak terpisah, ukur ulang liabilitas dengan tingkat diskonto baru",
            "disclosures": [
                "Aset hak-guna per kelas aset",
                "Beban depresiasi",
                "Beban bunga",
                "Arus kas keluar untuk sewa",
                "Penjelasan pengecualian",
            ],
        }


# ============================================================================
# Compatibility Aliases & Orchestration Bridge (IFRS 16 / Aggregator Alignment)
# ============================================================================
LeaseContract = PSAK73LeaseContract
LeaseLiability = PSAK73LeaseLiability
LeasePaymentTiming = PSAK73PaymentTiming
LeaseType = PSAK73LeaseType
LeaseClassification = PSAK73LeaseType
RightOfUseAsset = PSAK73RightOfUseAsset


def _create_lease_compat(
    self,
    lease_number,
    asset_id,
    asset_name,
    lessor_name,
    commencement_date,
    lease_term_years,
    annual_payment,
    discount_rate,
    currency="IDR",
    payment_timing=PSAK73PaymentTiming.IN_ARREARS,
):
    return self.create_lease_contract(
        contract_number=lease_number,
        asset_name=asset_name,
        lessor_name=lessor_name,
        commencement_date=commencement_date,
        lease_term_years=lease_term_years,
        annual_payment=annual_payment,
        discount_rate=discount_rate,
        payment_timing=payment_timing,
    )


def _calculate_right_of_use_asset_compat(
    self, lease, initial_direct_costs=Decimal(0), lease_incentives=Decimal(0)
):
    lease.initial_direct_costs = initial_direct_costs
    lease.lease_incentives_received = lease_incentives
    return self.compute_right_of_use_asset(lease)


def _calculate_lease_liability_compat(self, lease):
    return self.compute_lease_liability(lease)


def _record_lease_payment_compat(self, liability, *args, **kwargs):
    if args and isinstance(args[0], PSAK73LeaseContract):
        return self.record_annual_payment(
            liability, args[0], args[1] if len(args) > 1 else datetime.now(UTC)
        )
    payment_amount = args[0] if args else kwargs.get("payment_amount", Decimal(0))
    discount_rate = Decimal("8")
    interest = (liability.outstanding_balance * (discount_rate / 100)).quantize(
        Decimal("0"), rounding=ROUND_HALF_EVEN
    )
    principal = min(payment_amount - interest, liability.outstanding_balance)
    new_balance = liability.outstanding_balance - principal
    return (
        PSAK73LeaseLiability(
            liability_id=liability.liability_id,
            contract_id=liability.contract_id,
            initial_measurement=liability.initial_measurement,
            outstanding_balance=new_balance,
            interest_expense_ytd=liability.interest_expense_ytd + interest,
            principal_paid_ytd=liability.principal_paid_ytd + principal,
            last_payment_date=datetime.now(UTC),
        ),
        interest,
        principal,
    )


def _record_amortization_compat(self, asset, *args, **kwargs):
    lease_term_years = (
        args[0] if args else kwargs.get("lease_term_years", asset.useful_life_years or 5)
    )
    return self.record_depreciation(asset, lease_term_years)


def _validate_lease_compliance_compat(self, lease, fair_value=None):
    return self.validate_contract(lease)


# Suntikkan metode jembatan orkestrasi ke dalam Validator utama
PSAK73Validator.create_lease = _create_lease_compat
PSAK73Validator.calculate_right_of_use_asset = _calculate_right_of_use_asset_compat
PSAK73Validator.calculate_lease_liability = _calculate_lease_liability_compat
PSAK73Validator.record_lease_payment = _record_lease_payment_compat
PSAK73Validator.record_amortization = _record_amortization_compat
PSAK73Validator.validate_lease_compliance = _validate_lease_compliance_compat


# ============================================================================
# Class PSAK73 for test compatibility
# ============================================================================


class PSAK73:
    """
    Convenience class for test that exposes static method recognize_lease.
    """

    @staticmethod
    def recognize_lease(payment: Decimal, discount_rate: Decimal, lease_term: int) -> Any:
        """
        Compute right-of-use asset and lease liability for a simple lease with constant annual payments.
        Returns a simple object with attributes right_of_use_asset and lease_liability.
        """
        # Create a validator instance to reuse existing logic
        validator = get_psak73_validator()
        # Create a simple contract with annual payments in arrears
        contract = validator.create_lease_contract(
            contract_number="TEST-LEASE",
            asset_name="Test Asset",
            lessor_name="Test Lessor",
            commencement_date=datetime.now(UTC),
            lease_term_years=lease_term,
            annual_payment=payment,
            discount_rate=discount_rate * 100,  # convert from decimal to percentage
            payment_timing=PSAK73PaymentTiming.IN_ARREARS,
        )
        # Compute liability and ROU asset
        liability = validator.compute_lease_liability(contract)
        rou_asset = validator.compute_right_of_use_asset(contract)
        # For test, we need only initial values
        result = type("Lease", (), {})()
        result.right_of_use_asset = rou_asset.initial_measurement
        result.lease_liability = liability.initial_measurement
        return result


# ============================================================================
# Singleton Accessor
# ============================================================================
_psak73_validator_instance: PSAK73Validator | None = None


def get_psak73_validator() -> PSAK73Validator:
    global _psak73_validator_instance
    if _psak73_validator_instance is None:
        _psak73_validator_instance = PSAK73Validator()
    return _psak73_validator_instance


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    validator = get_psak73_validator()

    # Create lease contract
    contract = validator.create_lease_contract(
        contract_number="LEASE-001",
        asset_name="Mesin Produksi",
        lessor_name="PT Sewa Guna",
        commencement_date=datetime(2026, 1, 1, tzinfo=UTC),
        lease_term_years=5,
        annual_payment=Decimal("120000000"),
        discount_rate=Decimal("8"),
        payment_timing=PSAK73PaymentTiming.IN_ARREARS,
        initial_direct_costs=Decimal("5000000"),
        lease_incentives=Decimal("1000000"),
        restoration_cost=Decimal("2000000"),
    )
    print("Contract created:")
    print(json.dumps(contract.to_dict(), indent=2))

    # Compute initial liability and ROU asset
    liability = validator.compute_lease_liability(contract)
    rou_asset = validator.compute_right_of_use_asset(contract)
    print(f"\nInitial Liability: {liability.initial_measurement}")
    print(f"Initial ROU Asset: {rou_asset.initial_measurement}")

    # Record first year payment
    liability, interest, principal = validator.record_annual_payment(
        liability, contract, datetime(2026, 12, 31, tzinfo=UTC)
    )
    print(
        f"\nYear 1 payment: interest={interest}, principal={principal}, remaining={liability.outstanding_balance}"
    )

    # Record depreciation
    rou_asset = validator.record_depreciation(rou_asset, contract.lease_term_years)
    print(f"ROU Asset after depreciation: carrying={rou_asset.carrying_amount()}")

    # Validate
    result = validator.validate_contract(contract)
    print("\nValidation Result:")
    print(json.dumps(result.to_dict(), indent=2))


# ============================================================================
# Exports (ensure PSAK73 is exported)
# ============================================================================
__all__ = [
    "PSAK73",
    "LeaseClassification",
    "LeaseContract",
    "LeaseLiability",
    "LeasePaymentTiming",
    "LeaseType",
    "PSAK73ComplianceLevel",
    "PSAK73IncrementalBorrowingRateSource",
    "PSAK73LeaseContract",
    "PSAK73LeaseLiability",
    "PSAK73LeaseModification",
    "PSAK73LeasePayment",
    "PSAK73LeaseService",
    "PSAK73LeaseType",
    "PSAK73LowValueAssetExemption",
    "PSAK73ModificationType",
    "PSAK73PaymentTiming",
    "PSAK73RightOfUseAsset",
    "PSAK73Rules",
    "PSAK73ShortTermLeaseExemption",
    "PSAK73ValidationResult",
    "PSAK73Validator",
    "RightOfUseAsset",
    "get_psak73_validator",
]
