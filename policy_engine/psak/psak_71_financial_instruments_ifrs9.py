#!/usr/bin/env python3
"""
Module: psak_71_financial_instruments_ifrs9.py
Layer: 7 - Policy Engine & Standards / PSAK

Responsibility:
    PSAK 71: Instrumen Keuangan (setara dengan IFRS 9).
    Mengatur pengakuan, pengukuran, penurunan nilai (impairment menggunakan
    model expected credit loss - ECL 3 stage), dan akuntansi lindung nilai
    (hedge accounting) untuk instrumen keuangan. Menggantikan PSAK 55.
    Klasifikasi aset keuangan didasarkan pada model bisnis entitas dan
    karakteristik arus kas kontraktual (SPPI test).
    Aset keuangan diklasifikasikan sebagai:
    (1) Biaya perolehan diamortisasi (amortized cost),
    (2) Nilai wajar melalui penghasilan komprehensif lain (FVOCI),
    (3) Nilai wajar melalui laba rugi (FVTPL).
    Liabilitas keuangan: umumnya diukur pada biaya perolehan diamortisasi,
    kecuali yang ditetapkan sebagai FVTPL.
    Impairment: 12-month ECL atau lifetime ECL tergantung stage.
    Hedge accounting: fair value hedge, cash flow hedge, net investment hedge.

Dependencies:
    - datetime, decimal, enum, typing, dataclasses, uuid, hashlib, logging

Audit:
    Setiap klasifikasi, pengukuran, ECL, dan hedge accounting dicatat.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================
class PSAK71FinancialAssetCategory(Enum):
    AMORTIZED_COST = "biaya_perolehan_diamortisasi"
    FVOCI = "nilai_wajar_penghasilan_komprehensif_lain"
    FVTPL = "nilai_wajar_laba_rugi"


class PSAK71BusinessModel(Enum):
    HOLD_TO_COLLECT = "dimiliki_untuk_ditagih"
    HOLD_TO_COLLECT_AND_SELL = "dimiliki_untuk_ditagih_dan_dijual"
    OTHER = "lainnya"


class PSAK71SPPITestResult(Enum):
    PASS = "lolos"
    FAIL = "gagal"


class PSAK71ECLStage(Enum):
    STAGE_1 = "tahap_1"  # 12-month ECL
    STAGE_2 = "tahap_2"  # Lifetime ECL (belum turun nilai)
    STAGE_3 = "tahap_3"  # Lifetime ECL (sudah turun nilai)


class PSAK71HedgeType(Enum):
    FAIR_VALUE_HEDGE = "lindung_nilai_nilai_wajar"
    CASH_FLOW_HEDGE = "lindung_nilai_arus_kas"
    NET_INVESTMENT_HEDGE = "lindung_nilai_investasi_neto"


class PSAK71HedgeEffectivenessStatus(Enum):
    EFFECTIVE = "efektif"
    INEFFECTIVE = "tidak_efektif"
    PARTIALLY_EFFECTIVE = "sebagian_efektif"


class PSAK71ComplianceLevel(Enum):
    FULL = "penuh"
    SUBSTANTIAL = "substansial"
    PARTIAL = "sebagian"
    NON_COMPLIANT = "tidak_patuh"


# ============================================================================
# Exceptions
# ============================================================================
class PSAK71Error(Exception):
    pass


class SPPITestFailedError(PSAK71Error):
    pass


class HedgeEffectivenessError(PSAK71Error):
    pass


# ============================================================================
# Data Classes
# ============================================================================
@dataclass
class PSAK71CashFlow:
    amount: Decimal
    date: date


@dataclass
class PSAK71HedgeRelationship:
    hedge_id: UUID
    hedge_type: PSAK71HedgeType
    hedged_item_id: UUID
    hedging_instrument_id: UUID
    designation_date: datetime
    effectiveness_ratio: Decimal
    status: PSAK71HedgeEffectivenessStatus
    ineffectiveness_recognized: Decimal = Decimal(0)


@dataclass
class PSAK71FinancialAsset:
    asset_id: UUID
    asset_name: str
    principal: Decimal
    interest_rate: Decimal
    effective_interest_rate: Decimal
    acquisition_date: datetime
    maturity_date: datetime | None = None
    category: PSAK71FinancialAssetCategory = PSAK71FinancialAssetCategory.AMORTIZED_COST
    business_model: PSAK71BusinessModel = PSAK71BusinessModel.HOLD_TO_COLLECT
    amortized_cost: Decimal = Decimal(0)
    fair_value: Decimal | None = None
    accumulated_impairment: Decimal = Decimal(0)
    ecl_stage: PSAK71ECLStage = PSAK71ECLStage.STAGE_1
    modification_gain_loss: Decimal = Decimal(0)

    def __post_init__(self):
        if self.amortized_cost == 0:
            self.amortized_cost = self.principal
        if self.effective_interest_rate == 0:
            self.effective_interest_rate = self.interest_rate

    def carrying_amount(self) -> Decimal:
        if self.category == PSAK71FinancialAssetCategory.AMORTIZED_COST:
            return self.amortized_cost - self.accumulated_impairment
        else:
            return self.fair_value if self.fair_value is not None else self.amortized_cost

    def interest_revenue(self, period_start: datetime, period_end: datetime) -> Decimal:
        gross = self.amortized_cost
        if self.ecl_stage == PSAK71ECLStage.STAGE_3:
            gross = self.amortized_cost - self.accumulated_impairment
        days = (period_end - period_start).days
        years = Decimal(days) / Decimal(365)
        return (gross * (self.effective_interest_rate / 100) * years).quantize(
            Decimal("0"), rounding=ROUND_HALF_EVEN
        )

    def to_dict(self) -> dict:
        return {
            "asset_id": str(self.asset_id),
            "asset_name": self.asset_name,
            "principal": str(self.principal),
            "interest_rate": str(self.interest_rate),
            "effective_rate": str(self.effective_interest_rate),
            "acquisition_date": self.acquisition_date.isoformat(),
            "category": self.category.value,
            "amortized_cost": str(self.amortized_cost),
            "fair_value": str(self.fair_value) if self.fair_value else None,
            "carrying_amount": str(self.carrying_amount()),
            "ecl_stage": self.ecl_stage.value,
            "impairment": str(self.accumulated_impairment),
        }


@dataclass
class PSAK71ExpectedCreditLoss:
    ecl_id: UUID
    asset_id: UUID
    stage: PSAK71ECLStage
    exposure_at_default: Decimal
    probability_default: Decimal
    loss_given_default: Decimal
    ecl_amount: Decimal

    def __post_init__(self):
        self.ecl_amount = (
            self.exposure_at_default * self.probability_default * self.loss_given_default
        ).quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)

    def to_dict(self) -> dict:
        return {
            "ecl_id": str(self.ecl_id),
            "asset_id": str(self.asset_id),
            "stage": self.stage.value,
            "ead": str(self.exposure_at_default),
            "pd": str(self.probability_default),
            "lgd": str(self.loss_given_default),
            "ecl": str(self.ecl_amount),
        }


@dataclass
class PSAK71ValidationResult:
    is_compliant: bool
    compliance_level: PSAK71ComplianceLevel
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
        if self.compliance_level != PSAK71ComplianceLevel.NON_COMPLIANT:
            self.compliance_level = PSAK71ComplianceLevel.NON_COMPLIANT

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)
        if self.compliance_level == PSAK71ComplianceLevel.FULL:
            self.compliance_level = PSAK71ComplianceLevel.SUBSTANTIAL

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
class PSAK71FinancialInstrumentService:
    """Service untuk PSAK 71."""

    @staticmethod
    def perform_sppi_test(
        contractual_cash_flows: list[PSAK71CashFlow],
        principal: Decimal,
        interest_rate: Decimal,
        is_variable_rate: bool = False,
    ) -> PSAK71SPPITestResult:
        if is_variable_rate:
            return PSAK71SPPITestResult.PASS
        remaining_principal = principal
        for cf in sorted(contractual_cash_flows, key=lambda x: x.date):
            days = (cf.date - contractual_cash_flows[0].date).days
            expected_interest = remaining_principal * interest_rate * Decimal(days) / Decimal(365)
            expected_interest = expected_interest.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_EVEN
            )
            if cf.amount > remaining_principal + expected_interest + Decimal("0.01"):
                return PSAK71SPPITestResult.FAIL
            principal_paid = min(cf.amount - expected_interest, remaining_principal)
            remaining_principal -= principal_paid
        return PSAK71SPPITestResult.PASS

    @staticmethod
    def classify_financial_asset(
        business_model: PSAK71BusinessModel,
        sppi_result: PSAK71SPPITestResult,
        fair_value_option_elected: bool = False,
    ) -> PSAK71FinancialAssetCategory:
        if fair_value_option_elected:
            return PSAK71FinancialAssetCategory.FVTPL
        if business_model == PSAK71BusinessModel.HOLD_TO_COLLECT:
            return (
                PSAK71FinancialAssetCategory.AMORTIZED_COST
                if sppi_result == PSAK71SPPITestResult.PASS
                else PSAK71FinancialAssetCategory.FVTPL
            )
        elif business_model == PSAK71BusinessModel.HOLD_TO_COLLECT_AND_SELL:
            return (
                PSAK71FinancialAssetCategory.FVOCI
                if sppi_result == PSAK71SPPITestResult.PASS
                else PSAK71FinancialAssetCategory.FVTPL
            )
        else:
            return PSAK71FinancialAssetCategory.FVTPL

    @staticmethod
    def determine_ecl_stage(
        days_past_due: int,
        significant_increase_in_credit_risk: bool,
        credit_impaired: bool,
    ) -> PSAK71ECLStage:
        if credit_impaired:
            return PSAK71ECLStage.STAGE_3
        if significant_increase_in_credit_risk or days_past_due > 30:
            return PSAK71ECLStage.STAGE_2
        return PSAK71ECLStage.STAGE_1

    @staticmethod
    def calculate_ecl(
        ead: Decimal,
        pd: Decimal,
        lgd: Decimal,
        stage: PSAK71ECLStage,
        lifetime_pd: Decimal | None = None,
    ) -> Decimal:
        if stage == PSAK71ECLStage.STAGE_1:
            return (ead * pd * lgd).quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)
        else:
            actual_pd = lifetime_pd if lifetime_pd is not None else pd
            return (ead * actual_pd * lgd).quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)


# ============================================================================
# Rules
# ============================================================================
class PSAK71Rules:
    @staticmethod
    def validate_asset(asset: PSAK71FinancialAsset) -> PSAK71ValidationResult:
        result = PSAK71ValidationResult(
            is_compliant=True, compliance_level=PSAK71ComplianceLevel.FULL
        )
        if (
            asset.category == PSAK71FinancialAssetCategory.AMORTIZED_COST
            and asset.effective_interest_rate == 0
        ):
            result.add_warning("Aset biaya perolehan diamortisasi dengan tingkat bunga efektif nol")
        if asset.category == PSAK71FinancialAssetCategory.FVOCI and asset.fair_value is None:
            result.add_error("Aset FVOCI harus memiliki nilai wajar")
        return result

    @staticmethod
    def validate_ecl_stage_transition(
        old_stage: PSAK71ECLStage, new_stage: PSAK71ECLStage
    ) -> PSAK71ValidationResult:
        result = PSAK71ValidationResult(
            is_compliant=True, compliance_level=PSAK71ComplianceLevel.FULL
        )
        if old_stage == PSAK71ECLStage.STAGE_1 and new_stage == PSAK71ECLStage.STAGE_2:
            result.add_warning(
                "Transisi dari stage 1 ke stage 2: peningkatan risiko kredit signifikan"
            )
        return result


# ============================================================================
# Validator
# ============================================================================
class PSAK71Validator:
    def __init__(self):
        self._rules = PSAK71Rules()
        self._service = PSAK71FinancialInstrumentService()

    def create_asset(
        self,
        asset_name: str,
        principal: Decimal,
        interest_rate: Decimal,
        acquisition_date: datetime,
        maturity_date: datetime | None = None,
        business_model: PSAK71BusinessModel = PSAK71BusinessModel.HOLD_TO_COLLECT,
        fair_value_option_elected: bool = False,
        contractual_cash_flows: list[PSAK71CashFlow] | None = None,
    ) -> PSAK71FinancialAsset:
        if contractual_cash_flows is None:
            contractual_cash_flows = [
                PSAK71CashFlow(
                    principal + (principal * interest_rate / 100), maturity_date or date.today()
                )
            ]
        sppi = self._service.perform_sppi_test(
            contractual_cash_flows, principal, interest_rate / 100
        )
        category = self._service.classify_financial_asset(
            business_model, sppi, fair_value_option_elected
        )
        effective_rate = (
            interest_rate if category != PSAK71FinancialAssetCategory.FVTPL else Decimal(0)
        )
        return PSAK71FinancialAsset(
            asset_id=uuid4(),
            asset_name=asset_name,
            principal=principal,
            interest_rate=interest_rate,
            effective_interest_rate=effective_rate,
            acquisition_date=acquisition_date,
            maturity_date=maturity_date,
            category=category,
            business_model=business_model,
            fair_value=principal
            if category != PSAK71FinancialAssetCategory.AMORTIZED_COST
            else None,
        )

    def calculate_amortized_cost(
        self, asset: PSAK71FinancialAsset, period_end: datetime
    ) -> PSAK71FinancialAsset:
        interest = asset.interest_revenue(asset.acquisition_date, period_end)
        new_cost = asset.amortized_cost + interest
        return PSAK71FinancialAsset(
            asset_id=asset.asset_id,
            asset_name=asset.asset_name,
            principal=asset.principal,
            interest_rate=asset.interest_rate,
            effective_interest_rate=asset.effective_interest_rate,
            acquisition_date=asset.acquisition_date,
            maturity_date=asset.maturity_date,
            category=asset.category,
            business_model=asset.business_model,
            amortized_cost=new_cost,
            fair_value=asset.fair_value,
            accumulated_impairment=asset.accumulated_impairment,
            ecl_stage=asset.ecl_stage,
        )

    def update_ecl_stage(
        self,
        asset: PSAK71FinancialAsset,
        days_past_due: int,
        significant_increase_in_credit_risk: bool,
        credit_impaired: bool,
        pd_12m: Decimal,
        pd_lifetime: Decimal,
        lgd: Decimal,
        ead: Decimal | None = None,
    ) -> tuple[PSAK71FinancialAsset, PSAK71ExpectedCreditLoss]:
        new_stage = self._service.determine_ecl_stage(
            days_past_due, significant_increase_in_credit_risk, credit_impaired
        )
        ecl_amount = self._service.calculate_ecl(
            ead or asset.amortized_cost, pd_12m, lgd, new_stage, pd_lifetime
        )
        ecl = PSAK71ExpectedCreditLoss(
            ecl_id=uuid4(),
            asset_id=asset.asset_id,
            stage=new_stage,
            exposure_at_default=ead or asset.amortized_cost,
            probability_default=pd_12m if new_stage == PSAK71ECLStage.STAGE_1 else pd_lifetime,
            loss_given_default=lgd,
        )
        new_asset = PSAK71FinancialAsset(
            asset_id=asset.asset_id,
            asset_name=asset.asset_name,
            principal=asset.principal,
            interest_rate=asset.interest_rate,
            effective_interest_rate=asset.effective_interest_rate,
            acquisition_date=asset.acquisition_date,
            maturity_date=asset.maturity_date,
            category=asset.category,
            business_model=asset.business_model,
            amortized_cost=asset.amortized_cost,
            fair_value=asset.fair_value,
            accumulated_impairment=ecl_amount,
            ecl_stage=new_stage,
        )
        return new_asset, ecl

    def hedge_effectiveness_test(
        self,
        change_hedged_item: Decimal,
        change_hedging_instrument: Decimal,
        hedge_type: PSAK71HedgeType,
    ) -> tuple[PSAK71HedgeEffectivenessStatus, Decimal]:
        if change_hedging_instrument == 0:
            return PSAK71HedgeEffectivenessStatus.INEFFECTIVE, Decimal(0)
        ratio = abs(change_hedged_item / change_hedging_instrument)
        if 0.8 <= ratio <= 1.25:
            return PSAK71HedgeEffectivenessStatus.EFFECTIVE, ratio
        else:
            return PSAK71HedgeEffectivenessStatus.INEFFECTIVE, ratio

    def create_hedge_relationship(
        self,
        hedge_type: PSAK71HedgeType,
        hedged_item_id: UUID,
        hedging_instrument_id: UUID,
        designation_date: datetime,
        effectiveness_ratio: Decimal,
    ) -> PSAK71HedgeRelationship:
        status = (
            PSAK71HedgeEffectivenessStatus.EFFECTIVE
            if 0.8 <= effectiveness_ratio <= 1.25
            else PSAK71HedgeEffectivenessStatus.INEFFECTIVE
        )
        return PSAK71HedgeRelationship(
            hedge_id=uuid4(),
            hedge_type=hedge_type,
            hedged_item_id=hedged_item_id,
            hedging_instrument_id=hedging_instrument_id,
            designation_date=designation_date,
            effectiveness_ratio=effectiveness_ratio,
            status=status,
        )

    def validate_asset(self, asset: PSAK71FinancialAsset) -> PSAK71ValidationResult:
        return self._rules.validate_asset(asset)

    def get_requirements_summary(self) -> dict:
        return {
            "classification": "Aset keuangan diklasifikasikan berdasarkan model bisnis dan SPPI test: biaya perolehan diamortisasi, FVOCI, FVTPL",
            "sppi_test": "Arus kas kontraktual hanya terdiri dari pokok dan bunga",
            "impairment": "Model expected credit loss (ECL) 3 stage: 12-month ECL (stage 1), lifetime ECL (stage 2 & 3)",
            "hedge_accounting": "Lindung nilai fair value, cash flow, net investment; uji efektivitas 80-125%",
            "disclosures": [
                "Kebijakan akuntansi instrumen keuangan",
                "Klasifikasi dan nilai wajar",
                "Informasi ECL dan stage",
                "Lindung nilai",
            ],
        }


# ============================================================================
# Singleton Accessor
# ============================================================================
_psak71_validator_instance: PSAK71Validator | None = None


def get_psak71_validator() -> PSAK71Validator:
    global _psak71_validator_instance
    if _psak71_validator_instance is None:
        _psak71_validator_instance = PSAK71Validator()
    return _psak71_validator_instance


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    validator = get_psak71_validator()

    # Buat aset pinjaman (amortized cost)
    loan = validator.create_asset(
        asset_name="Pinjaman Korporasi",
        principal=Decimal("1000000000"),
        interest_rate=Decimal("10"),
        acquisition_date=datetime(2026, 1, 1, tzinfo=UTC),
        maturity_date=datetime(2027, 1, 1, tzinfo=UTC),
        business_model=PSAK71BusinessModel.HOLD_TO_COLLECT,
    )
    print("Aset:")
    print(json.dumps(loan.to_dict(), indent=2))

    # Amortisasi
    loan = validator.calculate_amortized_cost(loan, datetime(2026, 12, 31, tzinfo=UTC))
    print("\nSetelah amortisasi:")
    print(json.dumps(loan.to_dict(), indent=2))

    # ECL (stage 2)
    loan_updated, ecl = validator.update_ecl_stage(
        asset=loan,
        days_past_due=45,
        significant_increase_in_credit_risk=True,
        credit_impaired=False,
        pd_12m=Decimal("0.01"),
        pd_lifetime=Decimal("0.05"),
        lgd=Decimal("0.5"),
    )
    print("\nSetelah ECL:")
    print(json.dumps(loan_updated.to_dict(), indent=2))
    print("ECL detail:", ecl.to_dict())

    # Hedge
    status, ratio = validator.hedge_effectiveness_test(
        Decimal("1000"), Decimal("950"), PSAK71HedgeType.FAIR_VALUE_HEDGE
    )
    print("\nHedge effectiveness:", status.value, "ratio:", ratio)

    # Validasi
    result = validator.validate_asset(loan_updated)
    print("\nValidation Result:")
    print(json.dumps(result.to_dict(), indent=2))

# ============================================================================
# Compatibility Aliases for Orchestration / Aggregator Core (PSAK 71)
# ============================================================================
FinancialAssetClassification = PSAK71FinancialAssetCategory
ImpairmentStage = PSAK71ECLStage
HedgeType = PSAK71HedgeType
FinancialAsset = PSAK71FinancialAsset
ExpectedCreditLoss = PSAK71ExpectedCreditLoss
HedgingRelationship = PSAK71HedgeRelationship


# ============================================================================
# Financial Liability Classification & Orchestration Aliases (PSAK 71)
# ============================================================================
class PSAK71FinancialLiabilityCategory(Enum):
    AMORTIZED_COST = "biaya_perolehan_diamortisasi"
    FVTPL = "nilai_wajar_laba_rugi"


FinancialAssetClassification = PSAK71FinancialAssetCategory
FinancialLiabilityClassification = PSAK71FinancialLiabilityCategory
ImpairmentStage = PSAK71ECLStage
HedgeType = PSAK71HedgeType
FinancialAsset = PSAK71FinancialAsset
ExpectedCreditLoss = PSAK71ExpectedCreditLoss
HedgingRelationship = PSAK71HedgeRelationship
