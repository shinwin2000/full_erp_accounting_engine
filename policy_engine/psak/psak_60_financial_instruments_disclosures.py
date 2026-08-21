#!/usr/bin/env python3
"""
Module: psak_60_financial_instruments_disclosures.py
Layer: 7 - Policy Engine & Standards / PSAK

Responsibility:
    PSAK 60: Instrumen Keuangan: Pengungkapan (setara dengan IFRS 7).
    Mengatur pengungkapan yang memungkinkan pengguna laporan keuangan
    mengevaluasi signifikansi instrumen keuangan terhadap posisi dan
    kinerja keuangan entitas, serta sifat dan tingkat risiko yang timbul
    dari instrumen keuangan (risiko kredit, likuiditas, pasar).
    Mencakup informasi tentang nilai wajar, manajemen risiko, dan analisis
    sensitivitas.

Dependencies:
    - datetime, decimal, enum, typing, dataclasses, uuid, hashlib, logging

Audit:
    Setiap pengungkapan instrumen keuangan dicatat untuk audit trail.
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
class PSAK60RiskType(Enum):
    CREDIT_RISK = "risiko_kredit"
    LIQUIDITY_RISK = "risiko_likuiditas"
    MARKET_RISK = "risiko_pasar"
    INTEREST_RATE_RISK = "risiko_suku_bunga"
    CURRENCY_RISK = "risiko_valuta_asing"
    PRICE_RISK = "risiko_harga"


class PSAK60FairValueHierarchyLevel(Enum):
    LEVEL_1 = "tingkat_1"  # Harga kuotasi di pasar aktif
    LEVEL_2 = "tingkat_2"  # Input selain harga kuotasi yang dapat diobservasi
    LEVEL_3 = "tingkat_3"  # Input tidak dapat diobservasi


class PSAK60CreditRiskStage(Enum):
    STAGE_1 = "tahap_1"  # 12-month expected credit losses
    STAGE_2 = "tahap_2"  # Lifetime ECL not credit-impaired
    STAGE_3 = "tahap_3"  # Lifetime ECL credit-impaired


class PSAK60CollateralType(Enum):
    CASH = "kas"
    SECURITIES = "efek"
    PROPERTY = "properti"
    GUARANTEE = "jaminan"
    OTHER = "lainnya"


class PSAK60ComplianceLevel(Enum):
    FULL = "penuh"
    SUBSTANTIAL = "substansial"
    PARTIAL = "sebagian"
    NON_COMPLIANT = "tidak_patuh"


# ============================================================================
# Data Classes
# ============================================================================
@dataclass
class PSAK60RiskExposure:
    """Eksposur risiko untuk kategori instrumen keuangan."""

    risk_type: PSAK60RiskType
    carrying_amount: Decimal
    maximum_exposure: Decimal
    collateral_held: Decimal = Decimal(0)
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "risk_type": self.risk_type.value,
            "carrying_amount": str(self.carrying_amount),
            "maximum_exposure": str(self.maximum_exposure),
            "collateral_held": str(self.collateral_held),
            "description": self.description,
        }


@dataclass
class PSAK60FairValueDisclosure:
    """Pengungkapan nilai wajar instrumen keuangan."""

    disclosure_id: UUID
    instrument_id: UUID
    instrument_name: str
    carrying_amount: Decimal
    fair_value: Decimal
    fair_value_hierarchy_level: PSAK60FairValueHierarchyLevel
    valuation_technique: str
    significant_unobservable_inputs: dict[str, Any] | None = None
    sensitivity_to_changes: str | None = None

    def difference(self) -> Decimal:
        return (self.fair_value - self.carrying_amount).quantize(
            Decimal("0"), rounding=ROUND_HALF_EVEN
        )

    def to_dict(self) -> dict:
        return {
            "instrument_id": str(self.instrument_id),
            "instrument_name": self.instrument_name,
            "carrying_amount": str(self.carrying_amount),
            "fair_value": str(self.fair_value),
            "difference": str(self.difference()),
            "hierarchy_level": self.fair_value_hierarchy_level.value,
            "valuation_technique": self.valuation_technique,
        }


@dataclass
class PSAK60CreditRiskDisclosure:
    """Pengungkapan risiko kredit."""

    disclosure_id: UUID
    portfolio_segment: str
    gross_carrying_amount: Decimal
    loss_allowance: Decimal
    stage: PSAK60CreditRiskStage
    past_due_days: int = 0
    individually_impaired: bool = False
    collateral_description: str = ""
    net_carrying_amount: Decimal = Decimal(0)  # FIX: diberi default, akan dihitung di __post_init__

    def __post_init__(self):
        self.net_carrying_amount = self.gross_carrying_amount - self.loss_allowance

    def to_dict(self) -> dict:
        return {
            "segment": self.portfolio_segment,
            "gross": str(self.gross_carrying_amount),
            "loss_allowance": str(self.loss_allowance),
            "net": str(self.net_carrying_amount),
            "stage": self.stage.value,
            "past_due_days": self.past_due_days,
            "individually_impaired": self.individually_impaired,
        }


@dataclass
class PSAK60LiquidityRiskDisclosure:
    """Pengungkapan risiko likuiditas (maturity analysis)."""

    disclosure_id: UUID
    liability_category: str
    total_contractual_undiscounted: Decimal
    on_demand: Decimal
    less_than_3_months: Decimal
    between_3_and_12_months: Decimal
    between_1_and_5_years: Decimal
    more_than_5_years: Decimal

    def to_dict(self) -> dict:
        return {
            "category": self.liability_category,
            "total": str(self.total_contractual_undiscounted),
            "on_demand": str(self.on_demand),
            "<3 months": str(self.less_than_3_months),
            "3-12 months": str(self.between_3_and_12_months),
            "1-5 years": str(self.between_1_and_5_years),
            ">5 years": str(self.more_than_5_years),
        }


@dataclass
class PSAK60MarketRiskSensitivity:
    """Analisis sensitivitas risiko pasar."""

    sensitivity_id: UUID
    risk_type: PSAK60RiskType
    change_in_risk_variable: str  # misal "kenaikan 100 bps"
    effect_on_profit_loss: Decimal
    effect_on_equity: Decimal
    assumptions: str = ""

    def to_dict(self) -> dict:
        return {
            "risk_type": self.risk_type.value,
            "change": self.change_in_risk_variable,
            "effect_pnl": str(self.effect_on_profit_loss),
            "effect_equity": str(self.effect_on_equity),
            "assumptions": self.assumptions,
        }


@dataclass
class PSAK60FinancialInstrumentsDisclosure:
    """Pengungkapan instrumen keuangan secara keseluruhan."""

    disclosure_id: UUID
    entity_id: UUID
    entity_name: str
    reporting_date: datetime
    risk_exposures: list[PSAK60RiskExposure] = field(default_factory=list)
    fair_value_disclosures: list[PSAK60FairValueDisclosure] = field(default_factory=list)
    credit_risk_disclosures: list[PSAK60CreditRiskDisclosure] = field(default_factory=list)
    liquidity_risk_disclosures: list[PSAK60LiquidityRiskDisclosure] = field(default_factory=list)
    market_risk_sensitivities: list[PSAK60MarketRiskSensitivity] = field(default_factory=list)
    collateral_policies: str = ""
    hedging_disclosures: str = ""
    default_breaches: list[str] = field(default_factory=list)

    def total_credit_exposure(self) -> Decimal:
        # FIX: tambahkan Decimal(0) sebagai nilai awal sum
        return sum((c.gross_carrying_amount for c in self.credit_risk_disclosures), Decimal(0))

    def total_loss_allowance(self) -> Decimal:
        return sum((c.loss_allowance for c in self.credit_risk_disclosures), Decimal(0))

    def to_dict(self) -> dict:
        return {
            "disclosure_id": str(self.disclosure_id),
            "entity_id": str(self.entity_id),
            "entity_name": self.entity_name,
            "reporting_date": self.reporting_date.isoformat(),
            "risk_exposures": [r.to_dict() for r in self.risk_exposures],
            "fair_value": [f.to_dict() for f in self.fair_value_disclosures],
            "credit_risk": [c.to_dict() for c in self.credit_risk_disclosures],
            "liquidity_risk": [liq.to_dict() for liq in self.liquidity_risk_disclosures],
            "market_risk": [m.to_dict() for m in self.market_risk_sensitivities],
            "total_credit_exposure": str(self.total_credit_exposure()),
            "total_loss_allowance": str(self.total_loss_allowance()),
            "collateral_policies": self.collateral_policies,
            "default_breaches": self.default_breaches,
        }


@dataclass
class PSAK60ValidationResult:
    is_compliant: bool
    compliance_level: PSAK60ComplianceLevel
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
        if self.compliance_level != PSAK60ComplianceLevel.NON_COMPLIANT:
            self.compliance_level = PSAK60ComplianceLevel.NON_COMPLIANT

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)
        if self.compliance_level == PSAK60ComplianceLevel.FULL:
            self.compliance_level = PSAK60ComplianceLevel.SUBSTANTIAL

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
class PSAK60DisclosureService:
    """Service untuk pengungkapan instrumen keuangan."""

    @staticmethod
    def calculate_credit_risk_stage(
        days_past_due: int, significant_increase_in_credit_risk: bool, credit_impaired: bool
    ) -> PSAK60CreditRiskStage:
        if credit_impaired:
            return PSAK60CreditRiskStage.STAGE_3
        if days_past_due > 30 or significant_increase_in_credit_risk:
            return PSAK60CreditRiskStage.STAGE_2
        return PSAK60CreditRiskStage.STAGE_1

    @staticmethod
    def calculate_market_risk_sensitivity(
        exposure: Decimal,
        risk_factor_change_percent: Decimal,
        correlation_adjustment: Decimal = Decimal(1),
    ) -> Decimal:
        """Menghitung dampak perubahan faktor risiko (dalam mata uang yang sama)."""
        return (exposure * (risk_factor_change_percent / 100) * correlation_adjustment).quantize(
            Decimal("0"), rounding=ROUND_HALF_EVEN
        )

    @staticmethod
    def determine_fair_value_hierarchy(
        quoted_price_available: bool, observable_inputs_available: bool
    ) -> PSAK60FairValueHierarchyLevel:
        if quoted_price_available:
            return PSAK60FairValueHierarchyLevel.LEVEL_1
        elif observable_inputs_available:
            return PSAK60FairValueHierarchyLevel.LEVEL_2
        else:
            return PSAK60FairValueHierarchyLevel.LEVEL_3


# ============================================================================
# Rules
# ============================================================================
class PSAK60Rules:
    """Aturan PSAK 60."""

    @staticmethod
    def validate_fair_value_disclosure(fv: PSAK60FairValueDisclosure) -> PSAK60ValidationResult:
        result = PSAK60ValidationResult(
            is_compliant=True, compliance_level=PSAK60ComplianceLevel.FULL
        )
        if (
            fv.fair_value_hierarchy_level == PSAK60FairValueHierarchyLevel.LEVEL_3
            and not fv.significant_unobservable_inputs
        ):
            result.add_warning(
                "Pengungkapan input tidak terobservasi untuk tingkat 3 tidak lengkap"
            )
        return result

    @staticmethod
    def validate_credit_risk_disclosure(cr: PSAK60CreditRiskDisclosure) -> PSAK60ValidationResult:
        result = PSAK60ValidationResult(
            is_compliant=True, compliance_level=PSAK60ComplianceLevel.FULL
        )
        if cr.stage == PSAK60CreditRiskStage.STAGE_3 and cr.collateral_description == "":
            result.add_warning("Informasi agunan untuk aset kredit tahap 3 tidak diungkapkan")
        return result

    @staticmethod
    def validate_liquidity_maturity_analysis(
        liq: PSAK60LiquidityRiskDisclosure,
    ) -> PSAK60ValidationResult:
        result = PSAK60ValidationResult(
            is_compliant=True, compliance_level=PSAK60ComplianceLevel.FULL
        )
        total = (
            liq.on_demand
            + liq.less_than_3_months
            + liq.between_3_and_12_months
            + liq.between_1_and_5_years
            + liq.more_than_5_years
        )
        if total != liq.total_contractual_undiscounted:
            result.add_error("Total analisis jatuh tempo tidak sesuai dengan total kontraktual")
        return result


# ============================================================================
# Validator
# ============================================================================
class PSAK60Validator:
    def __init__(self):
        self._rules = PSAK60Rules()
        self._service = PSAK60DisclosureService()

    def create_risk_exposure(
        self,
        risk_type: PSAK60RiskType,
        carrying_amount: Decimal,
        maximum_exposure: Decimal,
        collateral_held: Decimal = Decimal(0),
        description: str = "",
    ) -> PSAK60RiskExposure:
        return PSAK60RiskExposure(
            risk_type=risk_type,
            carrying_amount=carrying_amount,
            maximum_exposure=max(maximum_exposure, carrying_amount),
            collateral_held=collateral_held,
            description=description,
        )

    def create_fair_value_disclosure(
        self,
        instrument_id: UUID,
        instrument_name: str,
        carrying_amount: Decimal,
        fair_value: Decimal,
        valuation_technique: str,
        quoted_price_available: bool = False,
        observable_inputs_available: bool = False,
        significant_unobservable_inputs: dict | None = None,
    ) -> PSAK60FairValueDisclosure:
        level = self._service.determine_fair_value_hierarchy(
            quoted_price_available, observable_inputs_available
        )
        return PSAK60FairValueDisclosure(
            disclosure_id=uuid4(),
            instrument_id=instrument_id,
            instrument_name=instrument_name,
            carrying_amount=carrying_amount,
            fair_value=fair_value,
            fair_value_hierarchy_level=level,
            valuation_technique=valuation_technique,
            significant_unobservable_inputs=significant_unobservable_inputs,
        )

    def create_credit_risk_disclosure(
        self,
        portfolio_segment: str,
        gross_carrying_amount: Decimal,
        loss_allowance: Decimal,
        days_past_due: int = 0,
        significant_increase_in_credit_risk: bool = False,
        credit_impaired: bool = False,
        collateral_description: str = "",
    ) -> PSAK60CreditRiskDisclosure:
        stage = self._service.calculate_credit_risk_stage(
            days_past_due, significant_increase_in_credit_risk, credit_impaired
        )
        # FIX: net_carrying_amount akan dihitung otomatis di __post_init__
        return PSAK60CreditRiskDisclosure(
            disclosure_id=uuid4(),
            portfolio_segment=portfolio_segment,
            gross_carrying_amount=gross_carrying_amount,
            loss_allowance=loss_allowance,
            stage=stage,
            past_due_days=days_past_due,
            individually_impaired=credit_impaired,
            collateral_description=collateral_description,
        )

    def create_liquidity_risk_disclosure(
        self,
        liability_category: str,
        total_contractual_undiscounted: Decimal,
        on_demand: Decimal,
        less_than_3_months: Decimal,
        between_3_and_12_months: Decimal,
        between_1_and_5_years: Decimal,
        more_than_5_years: Decimal,
    ) -> PSAK60LiquidityRiskDisclosure:
        return PSAK60LiquidityRiskDisclosure(
            disclosure_id=uuid4(),
            liability_category=liability_category,
            total_contractual_undiscounted=total_contractual_undiscounted,
            on_demand=on_demand,
            less_than_3_months=less_than_3_months,
            between_3_and_12_months=between_3_and_12_months,
            between_1_and_5_years=between_1_and_5_years,
            more_than_5_years=more_than_5_years,
        )

    def create_market_risk_sensitivity(
        self,
        risk_type: PSAK60RiskType,
        change_in_risk_variable: str,
        effect_on_profit_loss: Decimal,
        effect_on_equity: Decimal,
        assumptions: str = "",
    ) -> PSAK60MarketRiskSensitivity:
        return PSAK60MarketRiskSensitivity(
            sensitivity_id=uuid4(),
            risk_type=risk_type,
            change_in_risk_variable=change_in_risk_variable,
            effect_on_profit_loss=effect_on_profit_loss,
            effect_on_equity=effect_on_equity,
            assumptions=assumptions,
        )

    def create_disclosure(
        self,
        entity_id: UUID,
        entity_name: str,
        reporting_date: datetime,
    ) -> PSAK60FinancialInstrumentsDisclosure:
        return PSAK60FinancialInstrumentsDisclosure(
            disclosure_id=uuid4(),
            entity_id=entity_id,
            entity_name=entity_name,
            reporting_date=reporting_date,
        )

    def add_risk_exposure(
        self, disclosure: PSAK60FinancialInstrumentsDisclosure, exposure: PSAK60RiskExposure
    ) -> PSAK60FinancialInstrumentsDisclosure:
        new_list = [*disclosure.risk_exposures, exposure]
        return PSAK60FinancialInstrumentsDisclosure(
            disclosure_id=disclosure.disclosure_id,
            entity_id=disclosure.entity_id,
            entity_name=disclosure.entity_name,
            reporting_date=disclosure.reporting_date,
            risk_exposures=new_list,
            fair_value_disclosures=disclosure.fair_value_disclosures,
            credit_risk_disclosures=disclosure.credit_risk_disclosures,
            liquidity_risk_disclosures=disclosure.liquidity_risk_disclosures,
            market_risk_sensitivities=disclosure.market_risk_sensitivities,
            collateral_policies=disclosure.collateral_policies,
            hedging_disclosures=disclosure.hedging_disclosures,
            default_breaches=disclosure.default_breaches,
        )

    def add_fair_value(
        self, disclosure: PSAK60FinancialInstrumentsDisclosure, fv: PSAK60FairValueDisclosure
    ) -> PSAK60FinancialInstrumentsDisclosure:
        new_list = [*disclosure.fair_value_disclosures, fv]
        return PSAK60FinancialInstrumentsDisclosure(
            disclosure_id=disclosure.disclosure_id,
            entity_id=disclosure.entity_id,
            entity_name=disclosure.entity_name,
            reporting_date=disclosure.reporting_date,
            risk_exposures=disclosure.risk_exposures,
            fair_value_disclosures=new_list,
            credit_risk_disclosures=disclosure.credit_risk_disclosures,
            liquidity_risk_disclosures=disclosure.liquidity_risk_disclosures,
            market_risk_sensitivities=disclosure.market_risk_sensitivities,
            collateral_policies=disclosure.collateral_policies,
            hedging_disclosures=disclosure.hedging_disclosures,
            default_breaches=disclosure.default_breaches,
        )

    def add_credit_risk(
        self, disclosure: PSAK60FinancialInstrumentsDisclosure, cr: PSAK60CreditRiskDisclosure
    ) -> PSAK60FinancialInstrumentsDisclosure:
        new_list = [*disclosure.credit_risk_disclosures, cr]
        return PSAK60FinancialInstrumentsDisclosure(
            disclosure_id=disclosure.disclosure_id,
            entity_id=disclosure.entity_id,
            entity_name=disclosure.entity_name,
            reporting_date=disclosure.reporting_date,
            risk_exposures=disclosure.risk_exposures,
            fair_value_disclosures=disclosure.fair_value_disclosures,
            credit_risk_disclosures=new_list,
            liquidity_risk_disclosures=disclosure.liquidity_risk_disclosures,
            market_risk_sensitivities=disclosure.market_risk_sensitivities,
            collateral_policies=disclosure.collateral_policies,
            hedging_disclosures=disclosure.hedging_disclosures,
            default_breaches=disclosure.default_breaches,
        )

    def add_liquidity_risk(
        self, disclosure: PSAK60FinancialInstrumentsDisclosure, liq: PSAK60LiquidityRiskDisclosure
    ) -> PSAK60FinancialInstrumentsDisclosure:
        new_list = [*disclosure.liquidity_risk_disclosures, liq]
        return PSAK60FinancialInstrumentsDisclosure(
            disclosure_id=disclosure.disclosure_id,
            entity_id=disclosure.entity_id,
            entity_name=disclosure.entity_name,
            reporting_date=disclosure.reporting_date,
            risk_exposures=disclosure.risk_exposures,
            fair_value_disclosures=disclosure.fair_value_disclosures,
            credit_risk_disclosures=disclosure.credit_risk_disclosures,
            liquidity_risk_disclosures=new_list,
            market_risk_sensitivities=disclosure.market_risk_sensitivities,
            collateral_policies=disclosure.collateral_policies,
            hedging_disclosures=disclosure.hedging_disclosures,
            default_breaches=disclosure.default_breaches,
        )

    def add_market_risk(
        self, disclosure: PSAK60FinancialInstrumentsDisclosure, sens: PSAK60MarketRiskSensitivity
    ) -> PSAK60FinancialInstrumentsDisclosure:
        new_list = [*disclosure.market_risk_sensitivities, sens]
        return PSAK60FinancialInstrumentsDisclosure(
            disclosure_id=disclosure.disclosure_id,
            entity_id=disclosure.entity_id,
            entity_name=disclosure.entity_name,
            reporting_date=disclosure.reporting_date,
            risk_exposures=disclosure.risk_exposures,
            fair_value_disclosures=disclosure.fair_value_disclosures,
            credit_risk_disclosures=disclosure.credit_risk_disclosures,
            liquidity_risk_disclosures=disclosure.liquidity_risk_disclosures,
            market_risk_sensitivities=new_list,
            collateral_policies=disclosure.collateral_policies,
            hedging_disclosures=disclosure.hedging_disclosures,
            default_breaches=disclosure.default_breaches,
        )

    def validate_disclosure(
        self, disclosure: PSAK60FinancialInstrumentsDisclosure
    ) -> PSAK60ValidationResult:
        result = PSAK60ValidationResult(
            is_compliant=True, compliance_level=PSAK60ComplianceLevel.FULL
        )
        for fv in disclosure.fair_value_disclosures:
            result = self._merge_results(result, self._rules.validate_fair_value_disclosure(fv))
        for cr in disclosure.credit_risk_disclosures:
            result = self._merge_results(result, self._rules.validate_credit_risk_disclosure(cr))
        for liq in disclosure.liquidity_risk_disclosures:
            result = self._merge_results(
                result, self._rules.validate_liquidity_maturity_analysis(liq)
            )
        return result

    def _merge_results(
        self, main: PSAK60ValidationResult, other: PSAK60ValidationResult
    ) -> PSAK60ValidationResult:
        main.errors.extend(other.errors)
        main.warnings.extend(other.warnings)
        main.is_compliant = main.is_compliant and other.is_compliant
        level_order = [
            PSAK60ComplianceLevel.FULL,
            PSAK60ComplianceLevel.SUBSTANTIAL,
            PSAK60ComplianceLevel.PARTIAL,
            PSAK60ComplianceLevel.NON_COMPLIANT,
        ]
        main_idx = level_order.index(main.compliance_level)
        other_idx = level_order.index(other.compliance_level)
        if other_idx > main_idx:
            main.compliance_level = level_order[other_idx]
        return main

    def get_requirements_summary(self) -> dict:
        return {
            "risk_disclosures": [
                "Risiko kredit: eksposur maksimum, kualitas kredit, agunan, analisis umur, konsentrasi risiko",
                "Risiko likuiditas: analisis jatuh tempo liabilitas keuangan (kontraktual undiscounted)",
                "Risiko pasar: analisis sensitivitas untuk risiko suku bunga, valuta asing, dan harga",
            ],
            "fair_value_disclosures": [
                "Nilai wajar setiap kelas instrumen keuangan",
                "Hierarki nilai wajar (Tingkat 1, 2, 3)",
                "Teknik penilaian dan input signifikan",
                "Rekonsiliasi untuk tingkat 3",
            ],
            "credit_risk_impairment": [
                "Informasi kualitas kredit",
                "Analisis umur piutang yang telah jatuh tempo tetapi tidak mengalami penurunan nilai",
                "Penjelasan penentuan peningkatan risiko kredit yang signifikan",
            ],
            "hedging": [
                "Jenis lindung nilai",
                "Instrumen lindung nilai dan item yang dilindungi",
                "Jumlah inefektivitas yang diakui",
            ],
            "collateral": "Kebijakan agunan dan informasi agunan yang dijaminkan",
            "breaches": "Default dan pelanggaran kontrak pinjaman",
        }


# ============================================================================
# Singleton Accessor
# ============================================================================
_psak60_validator_instance: PSAK60Validator | None = None


def get_psak60_validator() -> PSAK60Validator:
    global _psak60_validator_instance
    if _psak60_validator_instance is None:
        _psak60_validator_instance = PSAK60Validator()
    return _psak60_validator_instance


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    import json

    validator = get_psak60_validator()
    entity_id = uuid4()

    disclosure = validator.create_disclosure(
        entity_id=entity_id,
        entity_name="PT Instrumen Keuangan",
        reporting_date=datetime(2026, 12, 31, tzinfo=UTC),
    )

    # Risk exposures
    credit_risk = validator.create_risk_exposure(
        risk_type=PSAK60RiskType.CREDIT_RISK,
        carrying_amount=Decimal("5000000000"),
        maximum_exposure=Decimal("5200000000"),
        collateral_held=Decimal("1000000000"),
    )
    disclosure = validator.add_risk_exposure(disclosure, credit_risk)

    # Fair value disclosure
    fv = validator.create_fair_value_disclosure(
        instrument_id=uuid4(),
        instrument_name="Investasi Obligasi",
        carrying_amount=Decimal("1000000000"),
        fair_value=Decimal("1050000000"),
        valuation_technique="Discounted cash flow",
        quoted_price_available=False,
        observable_inputs_available=True,
    )
    disclosure = validator.add_fair_value(disclosure, fv)

    # Credit risk disclosure
    cr = validator.create_credit_risk_disclosure(
        portfolio_segment="Piutang Usaha",
        gross_carrying_amount=Decimal("2000000000"),
        loss_allowance=Decimal("10000000"),
        days_past_due=15,
        significant_increase_in_credit_risk=False,
    )
    disclosure = validator.add_credit_risk(disclosure, cr)

    # Liquidity risk
    liq = validator.create_liquidity_risk_disclosure(
        liability_category="Utang Bank",
        total_contractual_undiscounted=Decimal("3000000000"),
        on_demand=Decimal("0"),
        less_than_3_months=Decimal("500000000"),
        between_3_and_12_months=Decimal("1500000000"),
        between_1_and_5_years=Decimal("1000000000"),
        more_than_5_years=Decimal("0"),
    )
    disclosure = validator.add_liquidity_risk(disclosure, liq)

    # Market risk sensitivity
    sens = validator.create_market_risk_sensitivity(
        risk_type=PSAK60RiskType.INTEREST_RATE_RISK,
        change_in_risk_variable="Kenaikan 100 bps",
        effect_on_profit_loss=Decimal("-50000000"),
        effect_on_equity=Decimal("-50000000"),
        assumptions="Semua variabel lain konstan",
    )
    disclosure = validator.add_market_risk(disclosure, sens)

    # Collateral policy
    disclosure.collateral_policies = (
        "Entitas menerima agunan berupa kas, efek, dan properti untuk pinjaman yang diberikan"
    )

    # Validate
    result = validator.validate_disclosure(disclosure)
    print("Validation Result:")
    print(json.dumps(result.to_dict(), indent=2))
    print("\nDisclosure:")
    print(json.dumps(disclosure.to_dict(), indent=2, default=str))


# ============================================================================
# Compatibility aliases for Orchestration / Aggregator Core (PSAK 60)
# ============================================================================
RiskType = PSAK60RiskType
CreditRiskExposure = PSAK60RiskExposure
LiquidityRiskMaturity = PSAK60LiquidityRiskDisclosure
MarketRiskSensitivity = PSAK60MarketRiskSensitivity
