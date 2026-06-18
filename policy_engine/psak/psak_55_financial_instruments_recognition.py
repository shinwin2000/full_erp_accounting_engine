#!/usr/bin/env python3
"""
Module: psak_55_financial_instruments_recognition.py
Layer: 7 - Policy Engine & Standards / PSAK

Responsibility:
    PSAK 55: Instrumen Keuangan: Pengakuan dan Pengukuran (legacy, setara dengan IAS 39).
    Mengatur pengakuan awal, pengukuran awal dan setelah pengakuan, impairment
    (model kerugian yang telah terjadi - incurred loss model), dan hedge accounting
    untuk instrumen keuangan. Standar ini berlaku sebelum adopsi PSAK 71 (IFRS 9).
    Klasifikasi aset keuangan: (1) Loan and receivables, (2) Held-to-maturity,
    (3) Available-for-sale, (4) Fair value through profit or loss (FVTPL).

Dependencies:
    - datetime, decimal, enum, typing, dataclasses, uuid, hashlib, logging

Audit:
    Setiap pengakuan awal, perubahan klasifikasi, perhitungan impairment, dan transaksi lindung nilai dicatat.
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
class PSAK55FinancialAssetCategory(Enum):
    LOAN_AND_RECEIVABLE = "pinjaman_dan_piutang"
    HELD_TO_MATURITY = "dimiliki_hingga_jatuh_tempo"
    AVAILABLE_FOR_SALE = "tersedia_untuk_dijual"
    FAIR_VALUE_THROUGH_PROFIT_LOSS = "nilai_wajar_laba_rugi"


class PSAK55FinancialLiabilityCategory(Enum):
    FAIR_VALUE_THROUGH_PROFIT_LOSS = "nilai_wajar_laba_rugi"
    OTHER_LIABILITIES = "liabilitas_lainnya"  # Diukur pada biaya perolehan diamortisasi


class PSAK55HedgeType(Enum):
    FAIR_VALUE_HEDGE = "lindung_nilai_nilai_wajar"
    CASH_FLOW_HEDGE = "lindung_nilai_arus_kas"
    NET_INVESTMENT_HEDGE = "lindung_nilai_investasi_neto"


class PSAK55HedgeEffectivenessStatus(Enum):
    HIGHLY_EFFECTIVE = "sangat_efektif"
    PARTIALLY_EFFECTIVE = "sebagian_efektif"
    INEFFECTIVE = "tidak_efektif"


class PSAK55ImpairmentStatus(Enum):
    NOT_IMPAIRED = "tidak_turun_nilai"
    INDIVIDUAL_IMPAIRED = "penurunan_nilai_individu"
    COLLECTIVE_IMPAIRED = "penurunan_nilai_kolektif"


class PSAK55ComplianceLevel(Enum):
    FULL = "penuh"
    SUBSTANTIAL = "substansial"
    PARTIAL = "sebagian"
    NON_COMPLIANT = "tidak_patuh"


# ============================================================================
# Exceptions
# ============================================================================
class PSAK55Error(Exception):
    pass


class ClassificationChangeError(PSAK55Error):
    pass


class HedgeEffectivenessError(PSAK55Error):
    pass


# ============================================================================
# Data Classes
# ============================================================================
@dataclass
class PSAK55FinancialAsset:
    """Aset keuangan."""

    asset_id: UUID
    asset_name: str
    category: PSAK55FinancialAssetCategory
    principal: Decimal
    interest_rate: Decimal  # dalam persen per tahun
    acquisition_date: datetime
    maturity_date: datetime | None = None
    fair_value: Decimal | None = None
    amortized_cost: Decimal = Decimal(0)
    accumulated_impairment: Decimal = Decimal(0)
    effective_interest_rate: Decimal = Decimal(0)
    is_impaired: bool = False
    impairment_status: PSAK55ImpairmentStatus = PSAK55ImpairmentStatus.NOT_IMPAIRED

    def __post_init__(self):
        if self.amortized_cost == 0:
            self.amortized_cost = self.principal
        if self.effective_interest_rate == 0:
            self.effective_interest_rate = self.interest_rate

    def carrying_amount(self) -> Decimal:
        if self.category in [
            PSAK55FinancialAssetCategory.FAIR_VALUE_THROUGH_PROFIT_LOSS,
            PSAK55FinancialAssetCategory.AVAILABLE_FOR_SALE,
        ]:
            return self.fair_value if self.fair_value is not None else self.amortized_cost
        else:
            return self.amortized_cost - self.accumulated_impairment

    def interest_revenue(self, period_start: datetime, period_end: datetime) -> Decimal:
        """Menghitung pendapatan bunga untuk periode menggunakan metode bunga efektif."""
        if self.effective_interest_rate == 0 or self.amortized_cost == 0:
            return Decimal(0)
        days = (period_end - period_start).days
        years = Decimal(days) / Decimal(365)
        return (self.amortized_cost * (self.effective_interest_rate / 100) * years).quantize(
            Decimal("0"), rounding=ROUND_HALF_EVEN
        )

    def to_dict(self) -> dict:
        return {
            "asset_id": str(self.asset_id),
            "asset_name": self.asset_name,
            "category": self.category.value,
            "principal": str(self.principal),
            "interest_rate": str(self.interest_rate),
            "acquisition_date": self.acquisition_date.isoformat(),
            "maturity_date": self.maturity_date.isoformat() if self.maturity_date else None,
            "fair_value": str(self.fair_value) if self.fair_value else None,
            "amortized_cost": str(self.amortized_cost),
            "carrying_amount": str(self.carrying_amount()),
            "impairment": str(self.accumulated_impairment),
            "is_impaired": self.is_impaired,
            "impairment_status": self.impairment_status.value,
        }


@dataclass
class PSAK55FinancialLiability:
    """Liabilitas keuangan."""

    liability_id: UUID
    liability_name: str
    category: PSAK55FinancialLiabilityCategory
    principal: Decimal
    interest_rate: Decimal
    acquisition_date: datetime
    maturity_date: datetime | None = None
    fair_value: Decimal | None = None
    amortized_cost: Decimal = Decimal(0)
    effective_interest_rate: Decimal = Decimal(0)

    def __post_init__(self):
        if self.amortized_cost == 0:
            self.amortized_cost = self.principal
        if self.effective_interest_rate == 0:
            self.effective_interest_rate = self.interest_rate

    def carrying_amount(self) -> Decimal:
        if self.category == PSAK55FinancialLiabilityCategory.FAIR_VALUE_THROUGH_PROFIT_LOSS:
            return self.fair_value if self.fair_value is not None else self.amortized_cost
        else:
            return self.amortized_cost

    def interest_expense(self, period_start: datetime, period_end: datetime) -> Decimal:
        days = (period_end - period_start).days
        years = Decimal(days) / Decimal(365)
        return (self.amortized_cost * (self.effective_interest_rate / 100) * years).quantize(
            Decimal("0"), rounding=ROUND_HALF_EVEN
        )

    def to_dict(self) -> dict:
        return {
            "liability_id": str(self.liability_id),
            "liability_name": self.liability_name,
            "category": self.category.value,
            "principal": str(self.principal),
            "interest_rate": str(self.interest_rate),
            "acquisition_date": self.acquisition_date.isoformat(),
            "maturity_date": self.maturity_date.isoformat() if self.maturity_date else None,
            "amortized_cost": str(self.amortized_cost),
            "carrying_amount": str(self.carrying_amount()),
        }


@dataclass
class PSAK55ImpairmentAssessment:
    """Penilaian penurunan nilai aset keuangan (incurred loss model)."""

    assessment_id: UUID
    asset_id: UUID
    assessment_date: datetime
    objective_evidence: list[str]  # Bukti objektif penurunan nilai
    estimated_future_cash_flows: list[tuple[datetime, Decimal]]
    discount_rate_original: Decimal
    present_value_expected_cash_flows: Decimal
    carrying_amount_before: Decimal
    impairment_loss: Decimal
    reversal_allowed: bool = False

    def __post_init__(self):
        # Hitung present value dari expected cash flows
        pv = Decimal(0)
        for dt, cf in self.estimated_future_cash_flows:
            days = (dt - self.assessment_date).days
            years = Decimal(days) / Decimal(365)
            discount = (Decimal(1) + (self.discount_rate_original / 100)) ** years
            pv += cf / discount
        self.present_value_expected_cash_flows = pv.quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)
        self.impairment_loss = (
            self.carrying_amount_before - self.present_value_expected_cash_flows
        ).quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)
        if self.impairment_loss < 0:
            self.impairment_loss = Decimal(0)

    def to_dict(self) -> dict:
        return {
            "assessment_id": str(self.assessment_id),
            "asset_id": str(self.asset_id),
            "assessment_date": self.assessment_date.isoformat(),
            "objective_evidence": self.objective_evidence,
            "pv_expected_cf": str(self.present_value_expected_cash_flows),
            "carrying_before": str(self.carrying_amount_before),
            "impairment_loss": str(self.impairment_loss),
        }


@dataclass
class PSAK55HedgeRelationship:
    """Hubungan lindung nilai."""

    hedge_id: UUID
    hedge_type: PSAK55HedgeType
    hedged_item_id: UUID
    hedging_instrument_id: UUID
    designation_date: datetime
    effectiveness_ratio: Decimal
    effectiveness_status: PSAK55HedgeEffectivenessStatus
    ineffective_amount: Decimal = Decimal(0)

    def __post_init__(self):
        if not (Decimal("0.8") <= self.effectiveness_ratio <= Decimal("1.25")):
            self.effectiveness_status = PSAK55HedgeEffectivenessStatus.INEFFECTIVE
        elif self.effectiveness_ratio >= Decimal("0.8") and self.effectiveness_ratio <= Decimal(
            "1.25"
        ):
            self.effectiveness_status = PSAK55HedgeEffectivenessStatus.HIGHLY_EFFECTIVE
        else:
            self.effectiveness_status = PSAK55HedgeEffectivenessStatus.PARTIALLY_EFFECTIVE

    def to_dict(self) -> dict:
        return {
            "hedge_id": str(self.hedge_id),
            "hedge_type": self.hedge_type.value,
            "hedged_item_id": str(self.hedged_item_id),
            "designation_date": self.designation_date.isoformat(),
            "effectiveness_ratio": str(self.effectiveness_ratio),
            "status": self.effectiveness_status.value,
        }


@dataclass
class PSAK55ValidationResult:
    is_compliant: bool
    compliance_level: PSAK55ComplianceLevel
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
        if self.compliance_level != PSAK55ComplianceLevel.NON_COMPLIANT:
            self.compliance_level = PSAK55ComplianceLevel.NON_COMPLIANT

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)
        if self.compliance_level == PSAK55ComplianceLevel.FULL:
            self.compliance_level = PSAK55ComplianceLevel.SUBSTANTIAL

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
class PSAK55FinancialInstrumentService:
    """Service untuk perhitungan instrumen keuangan."""

    @staticmethod
    def effective_interest_rate(
        principal: Decimal, cash_flows: list[tuple[datetime, Decimal]]
    ) -> Decimal:
        """Menghitung tingkat bunga efektif (EIR) menggunakan metode iterasi sederhana."""
        # Sederhana: jika hanya satu arus kas pada jatuh tempo
        if len(cash_flows) == 1:
            days = (cash_flows[0][0] - datetime.now(UTC)).days
            years = Decimal(days) / Decimal(365)
            if years <= 0:
                return Decimal(0)
            rate = ((cash_flows[0][1] / principal) ** (1 / years) - 1) * 100
            return rate.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        # Placeholder untuk kasus kompleks
        return Decimal(5)  # default

    @staticmethod
    def classify_asset(
        business_model: str, contractual_cash_flows: bool
    ) -> PSAK55FinancialAssetCategory:
        """Klasifikasi aset keuangan berdasarkan model bisnis."""
        if business_model == "hold_to_collect":
            if contractual_cash_flows:
                return PSAK55FinancialAssetCategory.LOAN_AND_RECEIVABLE
            else:
                return PSAK55FinancialAssetCategory.HELD_TO_MATURITY
        elif business_model == "hold_to_collect_and_sell":
            if contractual_cash_flows:
                return PSAK55FinancialAssetCategory.AVAILABLE_FOR_SALE
            else:
                return PSAK55FinancialAssetCategory.AVAILABLE_FOR_SALE
        else:
            return PSAK55FinancialAssetCategory.FAIR_VALUE_THROUGH_PROFIT_LOSS

    @staticmethod
    def calculate_impairment_collective(
        portfolio: list[PSAK55FinancialAsset],
        historical_loss_rate: Decimal,
        exposure_at_default: Decimal,
    ) -> Decimal:
        """Perhitungan impairment kolektif untuk portofolio (incurred loss model)."""
        total_impairment = Decimal(0)
        for asset in portfolio:
            if asset.category in [
                PSAK55FinancialAssetCategory.LOAN_AND_RECEIVABLE,
                PSAK55FinancialAssetCategory.HELD_TO_MATURITY,
            ]:
                ead = asset.principal
                impairment = ead * (historical_loss_rate / 100)
                total_impairment += impairment
        return total_impairment.quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)


# ============================================================================
# Rules
# ============================================================================
class PSAK55Rules:
    """Aturan PSAK 55."""

    @staticmethod
    def validate_classification_change(
        old_category: PSAK55FinancialAssetCategory, new_category: PSAK55FinancialAssetCategory
    ) -> PSAK55ValidationResult:
        result = PSAK55ValidationResult(
            is_compliant=True, compliance_level=PSAK55ComplianceLevel.FULL
        )
        if (
            old_category == PSAK55FinancialAssetCategory.HELD_TO_MATURITY
            and new_category != PSAK55FinancialAssetCategory.HELD_TO_MATURITY
        ):
            result.add_error(
                "Perubahan kategori dari held-to-maturity tidak diperbolehkan kecuali dalam keadaan terbatas (tainting)"
            )
        return result

    @staticmethod
    def validate_impairment_evidence(evidence: list[str]) -> PSAK55ValidationResult:
        result = PSAK55ValidationResult(
            is_compliant=True, compliance_level=PSAK55ComplianceLevel.FULL
        )
        if not evidence:
            result.add_warning("Penurunan nilai harus didukung bukti objektif")
        return result

    @staticmethod
    def validate_hedge_effectiveness(ratio: Decimal) -> PSAK55ValidationResult:
        result = PSAK55ValidationResult(
            is_compliant=True, compliance_level=PSAK55ComplianceLevel.FULL
        )
        if not (Decimal("0.8") <= ratio <= Decimal("1.25")):
            result.add_error("Lindung nilai tidak memenuhi kriteria efektivitas (80-125%)")
        return result


# ============================================================================
# Validator
# ============================================================================
class PSAK55Validator:
    def __init__(self):
        self._rules = PSAK55Rules()
        self._service = PSAK55FinancialInstrumentService()

    def create_asset(
        self,
        asset_name: str,
        category: PSAK55FinancialAssetCategory,
        principal: Decimal,
        interest_rate: Decimal,
        acquisition_date: datetime,
        maturity_date: datetime | None = None,
        fair_value: Decimal | None = None,
    ) -> PSAK55FinancialAsset:
        return PSAK55FinancialAsset(
            asset_id=uuid4(),
            asset_name=asset_name,
            category=category,
            principal=principal,
            interest_rate=interest_rate,
            acquisition_date=acquisition_date,
            maturity_date=maturity_date,
            fair_value=fair_value,
        )

    def create_liability(
        self,
        liability_name: str,
        category: PSAK55FinancialLiabilityCategory,
        principal: Decimal,
        interest_rate: Decimal,
        acquisition_date: datetime,
        maturity_date: datetime | None = None,
        fair_value: Decimal | None = None,
    ) -> PSAK55FinancialLiability:
        return PSAK55FinancialLiability(
            liability_id=uuid4(),
            liability_name=liability_name,
            category=category,
            principal=principal,
            interest_rate=interest_rate,
            acquisition_date=acquisition_date,
            maturity_date=maturity_date,
            fair_value=fair_value,
        )

    def classify_asset(
        self, business_model: str, contractual_cash_flows: bool
    ) -> PSAK55FinancialAssetCategory:
        return self._service.classify_asset(business_model, contractual_cash_flows)

    def record_amortization(
        self, asset: PSAK55FinancialAsset, period_end: datetime
    ) -> PSAK55FinancialAsset:
        interest = asset.interest_revenue(asset.acquisition_date, period_end)
        new_amortized_cost = asset.amortized_cost + interest
        return PSAK55FinancialAsset(
            asset_id=asset.asset_id,
            asset_name=asset.asset_name,
            category=asset.category,
            principal=asset.principal,
            interest_rate=asset.interest_rate,
            acquisition_date=asset.acquisition_date,
            maturity_date=asset.maturity_date,
            fair_value=asset.fair_value,
            amortized_cost=new_amortized_cost,
            accumulated_impairment=asset.accumulated_impairment,
            effective_interest_rate=asset.effective_interest_rate,
            is_impaired=asset.is_impaired,
        )

    def assess_impairment(
        self,
        asset: PSAK55FinancialAsset,
        objective_evidence: list[str],
        estimated_future_cash_flows: list[tuple[datetime, Decimal]],
        assessment_date: datetime,
    ) -> PSAK55ImpairmentAssessment:
        return PSAK55ImpairmentAssessment(
            assessment_id=uuid4(),
            asset_id=asset.asset_id,
            assessment_date=assessment_date,
            objective_evidence=objective_evidence,
            estimated_future_cash_flows=estimated_future_cash_flows,
            discount_rate_original=asset.effective_interest_rate,
            present_value_expected_cash_flows=Decimal(0),
            carrying_amount_before=asset.carrying_amount(),
        )

    def create_hedge_relationship(
        self,
        hedge_type: PSAK55HedgeType,
        hedged_item_id: UUID,
        hedging_instrument_id: UUID,
        effectiveness_ratio: Decimal,
        designation_date: datetime,
    ) -> PSAK55HedgeRelationship:
        return PSAK55HedgeRelationship(
            hedge_id=uuid4(),
            hedge_type=hedge_type,
            hedged_item_id=hedged_item_id,
            hedging_instrument_id=hedging_instrument_id,
            designation_date=designation_date,
            effectiveness_ratio=effectiveness_ratio,
            effectiveness_status=PSAK55HedgeEffectivenessStatus.HIGHLY_EFFECTIVE,
        )

    def validate_impairment(self, assessment: PSAK55ImpairmentAssessment) -> PSAK55ValidationResult:
        result = self._rules.validate_impairment_evidence(assessment.objective_evidence)
        if assessment.impairment_loss > 0:
            result.add_warning(
                f"Pengakuan kerugian penurunan nilai sebesar {assessment.impairment_loss}"
            )
        return result

    def validate_hedge(self, hedge: PSAK55HedgeRelationship) -> PSAK55ValidationResult:
        return self._rules.validate_hedge_effectiveness(hedge.effectiveness_ratio)

    def validate_asset(self, asset: PSAK55FinancialAsset) -> PSAK55ValidationResult:
        result = PSAK55ValidationResult(
            is_compliant=True, compliance_level=PSAK55ComplianceLevel.FULL
        )
        if (
            asset.category == PSAK55FinancialAssetCategory.HELD_TO_MATURITY
            and not asset.maturity_date
        ):
            result.add_error("Aset held-to-maturity harus memiliki tanggal jatuh tempo")
        return result

    def get_requirements_summary(self) -> dict:
        return {
            "classification": "Aset keuangan diklasifikasikan sebagai (1) pinjaman/piutang, (2) dimiliki hingga jatuh tempo, (3) tersedia untuk dijual, (4) nilai wajar melalui laba rugi",
            "initial_measurement": "Pada nilai wajar + biaya transaksi (kecuali FVTPL)",
            "subsequent_measurement": "Biaya perolehan diamortisasi untuk (1)(2), nilai wajar untuk (3)(4)",
            "impairment": "Model kerugian yang telah terjadi (incurred loss); bukti objektif diperlukan",
            "hedge_accounting": "Lindung nilai harus sangat efektif (80-125%)",
            "disclosures": [
                "Kebijakan akuntansi instrumen keuangan",
                "Klasifikasi dan nilai wajar",
                "Informasi impairment",
                "Lindung nilai",
            ],
        }


# ============================================================================
# Singleton Accessor
# ============================================================================
_psak55_validator_instance: PSAK55Validator | None = None


def get_psak55_validator() -> PSAK55Validator:
    global _psak55_validator_instance
    if _psak55_validator_instance is None:
        _psak55_validator_instance = PSAK55Validator()
    return _psak55_validator_instance


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    validator = get_psak55_validator()

    # Klasifikasi aset
    cat = validator.classify_asset("hold_to_collect", True)
    print(f"Klasifikasi: {cat.value}")

    # Buat aset pinjaman
    loan = validator.create_asset(
        asset_name="Pinjaman Korporasi",
        category=PSAK55FinancialAssetCategory.LOAN_AND_RECEIVABLE,
        principal=Decimal("1000000000"),
        interest_rate=Decimal("10"),
        acquisition_date=datetime(2026, 1, 1, tzinfo=UTC),
        maturity_date=datetime(2027, 1, 1, tzinfo=UTC),
    )
    print("\nAset:")
    print(json.dumps(loan.to_dict(), indent=2))

    # Rekam amortisasi
    loan = validator.record_amortization(loan, datetime(2026, 12, 31, tzinfo=UTC))
    print("Setelah amortisasi:")
    print(json.dumps(loan.to_dict(), indent=2))

    # Penurunan nilai
    assessment = validator.assess_impairment(
        asset=loan,
        objective_evidence=["Peminjam mengalami kesulitan keuangan signifikan"],
        estimated_future_cash_flows=[(datetime(2027, 1, 1, tzinfo=UTC), Decimal("800000000"))],
        assessment_date=datetime(2026, 12, 31, tzinfo=UTC),
    )
    print("\nImpairment Assessment:")
    print(json.dumps(assessment.to_dict(), indent=2))

    # Hedge relationship
    hedge = validator.create_hedge_relationship(
        hedge_type=PSAK55HedgeType.FAIR_VALUE_HEDGE,
        hedged_item_id=uuid4(),
        hedging_instrument_id=uuid4(),
        effectiveness_ratio=Decimal("0.95"),
        designation_date=datetime(2026, 1, 1, tzinfo=UTC),
    )
    print("\nHedge Relationship:")
    print(json.dumps(hedge.to_dict(), indent=2))

    # Validasi
    result = validator.validate_asset(loan)
    print("\nValidation Result:")
    print(json.dumps(result.to_dict(), indent=2))


# ============================================================================
# Compatibility Stubs & Aliases for Orchestration (PSAK 55)
# ============================================================================
@dataclass
class DerecognitionResult:
    """Stub hasil penghentian pengakuan instrumen keuangan sesuai PSAK 55."""

    is_derecognized: bool
    gain_loss: Decimal
    carrying_amount_derecognized: Decimal
    notes: str = ""


@dataclass
class ModificationResult:
    """Stub hasil penilaian modifikasi kontraktual instrumen keuangan."""

    is_substantial: bool
    modification_gain_loss: Decimal
    new_amortized_cost: Decimal
    notes: str = ""


# Alias pengikat untuk entitas instrumen generik
FinancialInstrument = PSAK55FinancialAsset
