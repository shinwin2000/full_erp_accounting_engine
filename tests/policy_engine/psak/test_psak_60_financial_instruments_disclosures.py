# tests/policy_engine/psak/test_psak_60_financial_instruments_disclosures.py
"""
Comprehensive tests for policy_engine/psak/psak_60_financial_instruments_disclosures.py
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from policy_engine.psak.psak_60_financial_instruments_disclosures import (
    CreditRiskExposure,
    LiquidityRiskMaturity,
    MarketRiskSensitivity,
    PSAK60CollateralType,
    PSAK60ComplianceLevel,
    PSAK60CreditRiskDisclosure,
    PSAK60CreditRiskStage,
    PSAK60DisclosureService,
    PSAK60FairValueDisclosure,
    PSAK60FairValueHierarchyLevel,
    PSAK60FinancialInstrumentsDisclosure,
    PSAK60LiquidityRiskDisclosure,
    PSAK60MarketRiskSensitivity,
    PSAK60RiskExposure,
    PSAK60RiskType,
    PSAK60Rules,
    PSAK60ValidationResult,
    PSAK60Validator,
    RiskType,
    get_psak60_validator,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def entity_id():
    return uuid4()


@pytest.fixture
def instrument_id():
    return uuid4()


@pytest.fixture
def disclosure(entity_id):
    return PSAK60FinancialInstrumentsDisclosure(
        disclosure_id=uuid4(),
        entity_id=entity_id,
        entity_name="Test Entity",
        reporting_date=datetime(2026, 12, 31, tzinfo=UTC),
    )


@pytest.fixture
def risk_exposure():
    return PSAK60RiskExposure(
        risk_type=PSAK60RiskType.CREDIT_RISK,
        carrying_amount=Decimal("1000000000"),
        maximum_exposure=Decimal("1200000000"),
        collateral_held=Decimal("500000000"),
        description="Credit risk exposure",
    )


@pytest.fixture
def fair_value_disclosure():
    return PSAK60FairValueDisclosure(
        disclosure_id=uuid4(),
        instrument_id=uuid4(),
        instrument_name="Bond Investment",
        carrying_amount=Decimal("1000000000"),
        fair_value=Decimal("1100000000"),
        fair_value_hierarchy_level=PSAK60FairValueHierarchyLevel.LEVEL_2,
        valuation_technique="Discounted Cash Flow",
        significant_unobservable_inputs={"discount_rate": "8%"},
        sensitivity_to_changes="+5%",
    )


@pytest.fixture
def credit_risk_disclosure():
    return PSAK60CreditRiskDisclosure(
        disclosure_id=uuid4(),
        portfolio_segment="Trade Receivables",
        gross_carrying_amount=Decimal("500000000"),
        loss_allowance=Decimal("25000000"),
        stage=PSAK60CreditRiskStage.STAGE_1,
        past_due_days=0,
        individually_impaired=False,
        collateral_description="No collateral",
    )


@pytest.fixture
def liquidity_risk_disclosure():
    return PSAK60LiquidityRiskDisclosure(
        disclosure_id=uuid4(),
        liability_category="Bank Loans",
        total_contractual_undiscounted=Decimal("3000000000"),
        on_demand=Decimal("0"),
        less_than_3_months=Decimal("500000000"),
        between_3_and_12_months=Decimal("1500000000"),
        between_1_and_5_years=Decimal("1000000000"),
        more_than_5_years=Decimal("0"),
    )


@pytest.fixture
def market_risk_sensitivity():
    return PSAK60MarketRiskSensitivity(
        sensitivity_id=uuid4(),
        risk_type=PSAK60RiskType.INTEREST_RATE_RISK,
        change_in_risk_variable="Increase 100 bps",
        effect_on_profit_loss=Decimal("-50000000"),
        effect_on_equity=Decimal("-50000000"),
        assumptions="All other variables constant",
    )


# ============================================================================
# Tests for Enums
# ============================================================================

class TestEnums:
    def test_risk_type(self):
        assert PSAK60RiskType.CREDIT_RISK.value == "risiko_kredit"
        assert PSAK60RiskType.LIQUIDITY_RISK.value == "risiko_likuiditas"
        assert PSAK60RiskType.MARKET_RISK.value == "risiko_pasar"

    def test_fair_value_hierarchy(self):
        assert PSAK60FairValueHierarchyLevel.LEVEL_1.value == "tingkat_1"
        assert PSAK60FairValueHierarchyLevel.LEVEL_2.value == "tingkat_2"
        assert PSAK60FairValueHierarchyLevel.LEVEL_3.value == "tingkat_3"

    def test_credit_risk_stage(self):
        assert PSAK60CreditRiskStage.STAGE_1.value == "tahap_1"
        assert PSAK60CreditRiskStage.STAGE_2.value == "tahap_2"
        assert PSAK60CreditRiskStage.STAGE_3.value == "tahap_3"

    def test_collateral_type(self):
        assert PSAK60CollateralType.CASH.value == "kas"
        assert PSAK60CollateralType.GUARANTEE.value == "jaminan"


# ============================================================================
# Tests for Data Classes
# ============================================================================

class TestPSAK60RiskExposure:
    def test_construction(self):
        exposure = PSAK60RiskExposure(
            risk_type=PSAK60RiskType.CREDIT_RISK,
            carrying_amount=Decimal("1000000000"),
            maximum_exposure=Decimal("1500000000"),
            collateral_held=Decimal("200000000"),
            description="Test",
        )
        assert exposure.risk_type == PSAK60RiskType.CREDIT_RISK
        assert exposure.carrying_amount == Decimal("1000000000")
        assert exposure.maximum_exposure == Decimal("1500000000")

    def test_maximum_exposure_cannot_be_less_than_carrying(self):
        exposure = PSAK60RiskExposure(
            risk_type=PSAK60RiskType.CREDIT_RISK,
            carrying_amount=Decimal("1000000000"),
            maximum_exposure=Decimal("800000000"),  # less than carrying
            collateral_held=Decimal("0"),
        )
        # maximum_exposure should be max(maximum_exposure, carrying_amount) = 1,000,000,000
        assert exposure.maximum_exposure == Decimal("1000000000")

    def test_to_dict(self):
        exposure = PSAK60RiskExposure(
            risk_type=PSAK60RiskType.CREDIT_RISK,
            carrying_amount=Decimal("1000000000"),
            maximum_exposure=Decimal("1200000000"),
            collateral_held=Decimal("300000000"),
            description="Test exposure",
        )
        d = exposure.to_dict()
        assert d["risk_type"] == "risiko_kredit"
        assert d["carrying_amount"] == "1000000000"
        assert d["maximum_exposure"] == "1200000000"
        assert d["collateral_held"] == "300000000"
        assert d["description"] == "Test exposure"


class TestPSAK60FairValueDisclosure:
    def test_construction(self):
        fv = PSAK60FairValueDisclosure(
            disclosure_id=uuid4(),
            instrument_id=uuid4(),
            instrument_name="Bond",
            carrying_amount=Decimal("1000000000"),
            fair_value=Decimal("1100000000"),
            fair_value_hierarchy_level=PSAK60FairValueHierarchyLevel.LEVEL_1,
            valuation_technique="Market price",
        )
        assert fv.instrument_name == "Bond"
        assert fv.fair_value == Decimal("1100000000")

    def test_difference(self):
        fv = PSAK60FairValueDisclosure(
            disclosure_id=uuid4(),
            instrument_id=uuid4(),
            instrument_name="Bond",
            carrying_amount=Decimal("1000000000"),
            fair_value=Decimal("1100000000"),
            fair_value_hierarchy_level=PSAK60FairValueHierarchyLevel.LEVEL_1,
            valuation_technique="Market price",
        )
        assert fv.difference() == Decimal("100000000")

    def test_difference_negative(self):
        fv = PSAK60FairValueDisclosure(
            disclosure_id=uuid4(),
            instrument_id=uuid4(),
            instrument_name="Bond",
            carrying_amount=Decimal("1000000000"),
            fair_value=Decimal("900000000"),
            fair_value_hierarchy_level=PSAK60FairValueHierarchyLevel.LEVEL_1,
            valuation_technique="Market price",
        )
        assert fv.difference() == Decimal("-100000000")

    def test_to_dict(self):
        fv = PSAK60FairValueDisclosure(
            disclosure_id=uuid4(),
            instrument_id=uuid4(),
            instrument_name="Bond",
            carrying_amount=Decimal("1000000000"),
            fair_value=Decimal("1100000000"),
            fair_value_hierarchy_level=PSAK60FairValueHierarchyLevel.LEVEL_2,
            valuation_technique="DCF",
            significant_unobservable_inputs={"rate": "8%"},
            sensitivity_to_changes="+5%",
        )
        d = fv.to_dict()
        assert d["instrument_name"] == "Bond"
        assert d["carrying_amount"] == "1000000000"
        assert d["fair_value"] == "1100000000"
        assert d["difference"] == "100000000"
        assert d["hierarchy_level"] == "tingkat_2"
        assert d["valuation_technique"] == "DCF"


class TestPSAK60CreditRiskDisclosure:
    def test_construction(self):
        cr = PSAK60CreditRiskDisclosure(
            disclosure_id=uuid4(),
            portfolio_segment="Receivables",
            gross_carrying_amount=Decimal("500000000"),
            loss_allowance=Decimal("25000000"),
            stage=PSAK60CreditRiskStage.STAGE_1,
            past_due_days=0,
            individually_impaired=False,
            collateral_description="None",
        )
        assert cr.portfolio_segment == "Receivables"
        assert cr.gross_carrying_amount == Decimal("500000000")
        # net_carrying_amount should be calculated in __post_init__
        assert cr.net_carrying_amount == Decimal("475000000")

    def test_to_dict(self):
        cr = PSAK60CreditRiskDisclosure(
            disclosure_id=uuid4(),
            portfolio_segment="Receivables",
            gross_carrying_amount=Decimal("500000000"),
            loss_allowance=Decimal("25000000"),
            stage=PSAK60CreditRiskStage.STAGE_2,
            past_due_days=45,
            individually_impaired=True,
            collateral_description="Property",
        )
        d = cr.to_dict()
        assert d["segment"] == "Receivables"
        assert d["gross"] == "500000000"
        assert d["loss_allowance"] == "25000000"
        assert d["net"] == "475000000"
        assert d["stage"] == "tahap_2"
        assert d["past_due_days"] == 45
        assert d["individually_impaired"] is True


class TestPSAK60LiquidityRiskDisclosure:
    def test_construction(self):
        liq = PSAK60LiquidityRiskDisclosure(
            disclosure_id=uuid4(),
            liability_category="Bank Loans",
            total_contractual_undiscounted=Decimal("3000000000"),
            on_demand=Decimal("0"),
            less_than_3_months=Decimal("500000000"),
            between_3_and_12_months=Decimal("1500000000"),
            between_1_and_5_years=Decimal("1000000000"),
            more_than_5_years=Decimal("0"),
        )
        assert liq.liability_category == "Bank Loans"
        assert liq.total_contractual_undiscounted == Decimal("3000000000")

    def test_to_dict(self):
        liq = PSAK60LiquidityRiskDisclosure(
            disclosure_id=uuid4(),
            liability_category="Bank Loans",
            total_contractual_undiscounted=Decimal("3000000000"),
            on_demand=Decimal("0"),
            less_than_3_months=Decimal("500000000"),
            between_3_and_12_months=Decimal("1500000000"),
            between_1_and_5_years=Decimal("1000000000"),
            more_than_5_years=Decimal("0"),
        )
        d = liq.to_dict()
        assert d["category"] == "Bank Loans"
        assert d["total"] == "3000000000"
        assert d["on_demand"] == "0"
        assert d["<3 months"] == "500000000"
        assert d["3-12 months"] == "1500000000"
        assert d["1-5 years"] == "1000000000"
        assert d[">5 years"] == "0"


class TestPSAK60MarketRiskSensitivity:
    def test_construction(self):
        sens = PSAK60MarketRiskSensitivity(
            sensitivity_id=uuid4(),
            risk_type=PSAK60RiskType.INTEREST_RATE_RISK,
            change_in_risk_variable="+100bps",
            effect_on_profit_loss=Decimal("-50000000"),
            effect_on_equity=Decimal("-50000000"),
            assumptions="Constant",
        )
        assert sens.risk_type == PSAK60RiskType.INTEREST_RATE_RISK
        assert sens.effect_on_profit_loss == Decimal("-50000000")

    def test_to_dict(self):
        sens = PSAK60MarketRiskSensitivity(
            sensitivity_id=uuid4(),
            risk_type=PSAK60RiskType.CURRENCY_RISK,
            change_in_risk_variable="+5% USD",
            effect_on_profit_loss=Decimal("-100000000"),
            effect_on_equity=Decimal("-80000000"),
            assumptions="Constant",
        )
        d = sens.to_dict()
        assert d["risk_type"] == "risiko_valuta_asing"
        assert d["change"] == "+5% USD"
        assert d["effect_pnl"] == "-100000000"
        assert d["effect_equity"] == "-80000000"
        assert d["assumptions"] == "Constant"


class TestPSAK60FinancialInstrumentsDisclosure:
    def test_construction(self, entity_id):
        disclosure = PSAK60FinancialInstrumentsDisclosure(
            disclosure_id=uuid4(),
            entity_id=entity_id,
            entity_name="Test Co",
            reporting_date=datetime(2026, 12, 31, tzinfo=UTC),
        )
        assert disclosure.entity_name == "Test Co"
        assert disclosure.risk_exposures == []
        assert disclosure.fair_value_disclosures == []

    def test_total_credit_exposure(self, credit_risk_disclosure):
        disclosure = PSAK60FinancialInstrumentsDisclosure(
            disclosure_id=uuid4(),
            entity_id=uuid4(),
            entity_name="Test",
            reporting_date=datetime.now(UTC),
        )
        disclosure.credit_risk_disclosures = [credit_risk_disclosure]
        # Add another
        cr2 = PSAK60CreditRiskDisclosure(
            disclosure_id=uuid4(),
            portfolio_segment="Other",
            gross_carrying_amount=Decimal("300000000"),
            loss_allowance=Decimal("15000000"),
            stage=PSAK60CreditRiskStage.STAGE_1,
        )
        disclosure.credit_risk_disclosures.append(cr2)
        total = disclosure.total_credit_exposure()
        assert total == Decimal("800000000")  # 500,000,000 + 300,000,000

    def test_total_loss_allowance(self, credit_risk_disclosure):
        disclosure = PSAK60FinancialInstrumentsDisclosure(
            disclosure_id=uuid4(),
            entity_id=uuid4(),
            entity_name="Test",
            reporting_date=datetime.now(UTC),
        )
        disclosure.credit_risk_disclosures = [credit_risk_disclosure]
        cr2 = PSAK60CreditRiskDisclosure(
            disclosure_id=uuid4(),
            portfolio_segment="Other",
            gross_carrying_amount=Decimal("300000000"),
            loss_allowance=Decimal("15000000"),
            stage=PSAK60CreditRiskStage.STAGE_1,
        )
        disclosure.credit_risk_disclosures.append(cr2)
        total = disclosure.total_loss_allowance()
        assert total == Decimal("40000000")  # 25,000,000 + 15,000,000

    def test_to_dict(self, entity_id, risk_exposure, fair_value_disclosure,
                     credit_risk_disclosure, liquidity_risk_disclosure, market_risk_sensitivity):
        disclosure = PSAK60FinancialInstrumentsDisclosure(
            disclosure_id=uuid4(),
            entity_id=entity_id,
            entity_name="Test Co",
            reporting_date=datetime(2026, 12, 31, tzinfo=UTC),
            risk_exposures=[risk_exposure],
            fair_value_disclosures=[fair_value_disclosure],
            credit_risk_disclosures=[credit_risk_disclosure],
            liquidity_risk_disclosures=[liquidity_risk_disclosure],
            market_risk_sensitivities=[market_risk_sensitivity],
            collateral_policies="Test policy",
            default_breaches=["Breach 1"],
        )
        d = disclosure.to_dict()
        assert d["entity_name"] == "Test Co"
        assert d["total_credit_exposure"] == "500000000"
        assert d["total_loss_allowance"] == "25000000"
        assert len(d["risk_exposures"]) == 1
        assert len(d["fair_value"]) == 1
        assert len(d["credit_risk"]) == 1
        assert len(d["liquidity_risk"]) == 1
        assert len(d["market_risk"]) == 1
        assert d["default_breaches"] == ["Breach 1"]


# ============================================================================
# Tests for PSAK60ValidationResult
# ============================================================================

class TestPSAK60ValidationResult:
    def test_initialization(self):
        result = PSAK60ValidationResult(
            is_compliant=True,
            compliance_level=PSAK60ComplianceLevel.FULL,
        )
        assert result.is_compliant is True
        assert result.compliance_level == PSAK60ComplianceLevel.FULL
        assert result.hash_sha256 != ""

    def test_add_error(self):
        result = PSAK60ValidationResult(
            is_compliant=True,
            compliance_level=PSAK60ComplianceLevel.FULL,
        )
        result.add_error("Error message")
        assert result.is_compliant is False
        assert result.compliance_level == PSAK60ComplianceLevel.NON_COMPLIANT
        assert "Error message" in result.errors

    def test_add_warning(self):
        result = PSAK60ValidationResult(
            is_compliant=True,
            compliance_level=PSAK60ComplianceLevel.FULL,
        )
        result.add_warning("Warning message")
        assert result.is_compliant is True
        assert result.compliance_level == PSAK60ComplianceLevel.SUBSTANTIAL
        assert "Warning message" in result.warnings

    def test_to_dict(self):
        result = PSAK60ValidationResult(
            is_compliant=False,
            compliance_level=PSAK60ComplianceLevel.NON_COMPLIANT,
            errors=["e1"],
            warnings=["w1"],
        )
        d = result.to_dict()
        assert d["is_compliant"] is False
        assert d["compliance_level"] == "tidak_patuh"
        assert d["errors"] == ["e1"]
        assert d["warnings"] == ["w1"]
        assert "hash" in d


# ============================================================================
# Tests for PSAK60DisclosureService
# ============================================================================

class TestPSAK60DisclosureService:
    def test_calculate_credit_risk_stage_1(self):
        stage = PSAK60DisclosureService.calculate_credit_risk_stage(
            days_past_due=0,
            significant_increase_in_credit_risk=False,
            credit_impaired=False,
        )
        assert stage == PSAK60CreditRiskStage.STAGE_1

    def test_calculate_credit_risk_stage_2_days_past_due(self):
        stage = PSAK60DisclosureService.calculate_credit_risk_stage(
            days_past_due=35,
            significant_increase_in_credit_risk=False,
            credit_impaired=False,
        )
        assert stage == PSAK60CreditRiskStage.STAGE_2

    def test_calculate_credit_risk_stage_2_significant_increase(self):
        stage = PSAK60DisclosureService.calculate_credit_risk_stage(
            days_past_due=0,
            significant_increase_in_credit_risk=True,
            credit_impaired=False,
        )
        assert stage == PSAK60CreditRiskStage.STAGE_2

    def test_calculate_credit_risk_stage_3(self):
        stage = PSAK60DisclosureService.calculate_credit_risk_stage(
            days_past_due=0,
            significant_increase_in_credit_risk=False,
            credit_impaired=True,
        )
        assert stage == PSAK60CreditRiskStage.STAGE_3

    def test_calculate_market_risk_sensitivity(self):
        result = PSAK60DisclosureService.calculate_market_risk_sensitivity(
            exposure=Decimal("1000000000"),
            risk_factor_change_percent=Decimal("2"),
            correlation_adjustment=Decimal("1"),
        )
        assert result == Decimal("20000000")  # 1B * 2% = 20M

    def test_calculate_market_risk_sensitivity_with_correlation(self):
        result = PSAK60DisclosureService.calculate_market_risk_sensitivity(
            exposure=Decimal("1000000000"),
            risk_factor_change_percent=Decimal("2"),
            correlation_adjustment=Decimal("0.8"),
        )
        assert result == Decimal("16000000")  # 1B * 2% * 0.8 = 16M

    def test_determine_fair_value_hierarchy_level_1(self):
        level = PSAK60DisclosureService.determine_fair_value_hierarchy(
            quoted_price_available=True,
            observable_inputs_available=False,
        )
        assert level == PSAK60FairValueHierarchyLevel.LEVEL_1

    def test_determine_fair_value_hierarchy_level_2(self):
        level = PSAK60DisclosureService.determine_fair_value_hierarchy(
            quoted_price_available=False,
            observable_inputs_available=True,
        )
        assert level == PSAK60FairValueHierarchyLevel.LEVEL_2

    def test_determine_fair_value_hierarchy_level_3(self):
        level = PSAK60DisclosureService.determine_fair_value_hierarchy(
            quoted_price_available=False,
            observable_inputs_available=False,
        )
        assert level == PSAK60FairValueHierarchyLevel.LEVEL_3


# ============================================================================
# Tests for PSAK60Rules
# ============================================================================

class TestPSAK60Rules:
    def test_validate_fair_value_disclosure_ok(self, fair_value_disclosure):
        fair_value_disclosure.fair_value_hierarchy_level = PSAK60FairValueHierarchyLevel.LEVEL_1
        result = PSAK60Rules.validate_fair_value_disclosure(fair_value_disclosure)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK60ComplianceLevel.FULL

    def test_validate_fair_value_disclosure_level_3_missing_inputs(self, fair_value_disclosure):
        fair_value_disclosure.fair_value_hierarchy_level = PSAK60FairValueHierarchyLevel.LEVEL_3
        fair_value_disclosure.significant_unobservable_inputs = None
        result = PSAK60Rules.validate_fair_value_disclosure(fair_value_disclosure)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK60ComplianceLevel.SUBSTANTIAL
        assert "Pengungkapan input tidak terobservasi" in result.warnings[0]

    def test_validate_fair_value_disclosure_level_3_with_inputs(self, fair_value_disclosure):
        fair_value_disclosure.fair_value_hierarchy_level = PSAK60FairValueHierarchyLevel.LEVEL_3
        fair_value_disclosure.significant_unobservable_inputs = {"rate": "8%"}
        result = PSAK60Rules.validate_fair_value_disclosure(fair_value_disclosure)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK60ComplianceLevel.FULL

    def test_validate_credit_risk_disclosure_ok(self, credit_risk_disclosure):
        credit_risk_disclosure.stage = PSAK60CreditRiskStage.STAGE_1
        result = PSAK60Rules.validate_credit_risk_disclosure(credit_risk_disclosure)
        assert result.is_compliant is True

    def test_validate_credit_risk_disclosure_stage_3_missing_collateral(self, credit_risk_disclosure):
        credit_risk_disclosure.stage = PSAK60CreditRiskStage.STAGE_3
        credit_risk_disclosure.collateral_description = ""
        result = PSAK60Rules.validate_credit_risk_disclosure(credit_risk_disclosure)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK60ComplianceLevel.SUBSTANTIAL
        assert "agunan untuk aset kredit tahap 3" in result.warnings[0]

    def test_validate_liquidity_maturity_analysis_ok(self, liquidity_risk_disclosure):
        result = PSAK60Rules.validate_liquidity_maturity_analysis(liquidity_risk_disclosure)
        assert result.is_compliant is True

    def test_validate_liquidity_maturity_analysis_mismatch(self, liquidity_risk_disclosure):
        # Total doesn't match sum of buckets
        liquidity_risk_disclosure.total_contractual_undiscounted = Decimal("4000000000")
        # Sum of buckets = 0 + 500M + 1.5B + 1B + 0 = 3B
        result = PSAK60Rules.validate_liquidity_maturity_analysis(liquidity_risk_disclosure)
        assert result.is_compliant is False
        assert result.compliance_level == PSAK60ComplianceLevel.NON_COMPLIANT
        assert "Total analisis jatuh tempo tidak sesuai" in result.errors[0]


# ============================================================================
# Tests for PSAK60Validator
# ============================================================================

class TestPSAK60Validator:
    def test_create_risk_exposure(self):
        validator = PSAK60Validator()
        exposure = validator.create_risk_exposure(
            risk_type=PSAK60RiskType.CREDIT_RISK,
            carrying_amount=Decimal("1000000000"),
            maximum_exposure=Decimal("1500000000"),
            collateral_held=Decimal("200000000"),
            description="Test",
        )
        assert isinstance(exposure, PSAK60RiskExposure)
        assert exposure.risk_type == PSAK60RiskType.CREDIT_RISK
        assert exposure.carrying_amount == Decimal("1000000000")

    def test_create_fair_value_disclosure(self):
        validator = PSAK60Validator()
        fv = validator.create_fair_value_disclosure(
            instrument_id=uuid4(),
            instrument_name="Bond",
            carrying_amount=Decimal("1000000000"),
            fair_value=Decimal("1100000000"),
            valuation_technique="DCF",
            quoted_price_available=False,
            observable_inputs_available=True,
            significant_unobservable_inputs={"rate": "8%"},
        )
        assert isinstance(fv, PSAK60FairValueDisclosure)
        assert fv.instrument_name == "Bond"
        assert fv.fair_value_hierarchy_level == PSAK60FairValueHierarchyLevel.LEVEL_2

    def test_create_credit_risk_disclosure(self):
        validator = PSAK60Validator()
        cr = validator.create_credit_risk_disclosure(
            portfolio_segment="Receivables",
            gross_carrying_amount=Decimal("500000000"),
            loss_allowance=Decimal("25000000"),
            days_past_due=0,
            significant_increase_in_credit_risk=False,
            credit_impaired=False,
            collateral_description="None",
        )
        assert isinstance(cr, PSAK60CreditRiskDisclosure)
        assert cr.portfolio_segment == "Receivables"
        assert cr.stage == PSAK60CreditRiskStage.STAGE_1

    def test_create_liquidity_risk_disclosure(self):
        validator = PSAK60Validator()
        liq = validator.create_liquidity_risk_disclosure(
            liability_category="Bank Loans",
            total_contractual_undiscounted=Decimal("3000000000"),
            on_demand=Decimal("0"),
            less_than_3_months=Decimal("500000000"),
            between_3_and_12_months=Decimal("1500000000"),
            between_1_and_5_years=Decimal("1000000000"),
            more_than_5_years=Decimal("0"),
        )
        assert isinstance(liq, PSAK60LiquidityRiskDisclosure)
        assert liq.liability_category == "Bank Loans"

    def test_create_market_risk_sensitivity(self):
        validator = PSAK60Validator()
        sens = validator.create_market_risk_sensitivity(
            risk_type=PSAK60RiskType.INTEREST_RATE_RISK,
            change_in_risk_variable="+100 bps",
            effect_on_profit_loss=Decimal("-50000000"),
            effect_on_equity=Decimal("-50000000"),
            assumptions="Constant",
        )
        assert isinstance(sens, PSAK60MarketRiskSensitivity)
        assert sens.risk_type == PSAK60RiskType.INTEREST_RATE_RISK

    def test_create_disclosure(self, entity_id):
        validator = PSAK60Validator()
        disclosure = validator.create_disclosure(
            entity_id=entity_id,
            entity_name="Test Co",
            reporting_date=datetime(2026, 12, 31, tzinfo=UTC),
        )
        assert isinstance(disclosure, PSAK60FinancialInstrumentsDisclosure)
        assert disclosure.entity_id == entity_id
        assert disclosure.entity_name == "Test Co"

    def test_add_risk_exposure(self, disclosure, risk_exposure):
        validator = PSAK60Validator()
        new_disclosure = validator.add_risk_exposure(disclosure, risk_exposure)
        assert len(new_disclosure.risk_exposures) == 1
        assert new_disclosure.risk_exposures[0] is risk_exposure
        # Original unchanged
        assert len(disclosure.risk_exposures) == 0

    def test_add_fair_value(self, disclosure, fair_value_disclosure):
        validator = PSAK60Validator()
        new_disclosure = validator.add_fair_value(disclosure, fair_value_disclosure)
        assert len(new_disclosure.fair_value_disclosures) == 1
        assert new_disclosure.fair_value_disclosures[0] is fair_value_disclosure

    def test_add_credit_risk(self, disclosure, credit_risk_disclosure):
        validator = PSAK60Validator()
        new_disclosure = validator.add_credit_risk(disclosure, credit_risk_disclosure)
        assert len(new_disclosure.credit_risk_disclosures) == 1
        assert new_disclosure.credit_risk_disclosures[0] is credit_risk_disclosure

    def test_add_liquidity_risk(self, disclosure, liquidity_risk_disclosure):
        validator = PSAK60Validator()
        new_disclosure = validator.add_liquidity_risk(disclosure, liquidity_risk_disclosure)
        assert len(new_disclosure.liquidity_risk_disclosures) == 1
        assert new_disclosure.liquidity_risk_disclosures[0] is liquidity_risk_disclosure

    def test_add_market_risk(self, disclosure, market_risk_sensitivity):
        validator = PSAK60Validator()
        new_disclosure = validator.add_market_risk(disclosure, market_risk_sensitivity)
        assert len(new_disclosure.market_risk_sensitivities) == 1
        assert new_disclosure.market_risk_sensitivities[0] is market_risk_sensitivity

    def test_validate_disclosure_valid(self, disclosure, fair_value_disclosure,
                                        credit_risk_disclosure, liquidity_risk_disclosure):
        validator = PSAK60Validator()
        disclosure.fair_value_disclosures = [fair_value_disclosure]
        disclosure.credit_risk_disclosures = [credit_risk_disclosure]
        disclosure.liquidity_risk_disclosures = [liquidity_risk_disclosure]
        result = validator.validate_disclosure(disclosure)
        assert result.is_compliant is True

    def test_validate_disclosure_with_warnings(self, disclosure, fair_value_disclosure,
                                                credit_risk_disclosure):
        validator = PSAK60Validator()
        fair_value_disclosure.fair_value_hierarchy_level = PSAK60FairValueHierarchyLevel.LEVEL_3
        fair_value_disclosure.significant_unobservable_inputs = None
        disclosure.fair_value_disclosures = [fair_value_disclosure]
        credit_risk_disclosure.stage = PSAK60CreditRiskStage.STAGE_3
        credit_risk_disclosure.collateral_description = ""
        disclosure.credit_risk_disclosures = [credit_risk_disclosure]
        result = validator.validate_disclosure(disclosure)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK60ComplianceLevel.SUBSTANTIAL
        assert len(result.warnings) >= 2

    def test_validate_disclosure_with_error(self, disclosure, liquidity_risk_disclosure):
        validator = PSAK60Validator()
        liquidity_risk_disclosure.total_contractual_undiscounted = Decimal("5000000000")
        disclosure.liquidity_risk_disclosures = [liquidity_risk_disclosure]
        result = validator.validate_disclosure(disclosure)
        assert result.is_compliant is False
        assert result.compliance_level == PSAK60ComplianceLevel.NON_COMPLIANT

    def test_merge_results(self):
        validator = PSAK60Validator()
        main = PSAK60ValidationResult(
            is_compliant=True,
            compliance_level=PSAK60ComplianceLevel.FULL,
        )
        other = PSAK60ValidationResult(
            is_compliant=False,
            compliance_level=PSAK60ComplianceLevel.NON_COMPLIANT,
            errors=["e1"],
            warnings=["w1"],
        )
        merged = validator._merge_results(main, other)
        assert merged.is_compliant is False
        assert merged.compliance_level == PSAK60ComplianceLevel.NON_COMPLIANT
        assert len(merged.errors) == 1
        assert len(merged.warnings) == 1

    def test_get_requirements_summary(self):
        validator = PSAK60Validator()
        summary = validator.get_requirements_summary()
        assert "risk_disclosures" in summary
        assert "fair_value_disclosures" in summary
        assert "credit_risk_impairment" in summary
        assert "hedging" in summary
        assert "collateral" in summary
        assert "breaches" in summary


# ============================================================================
# Tests for Compatibility Aliases
# ============================================================================

class TestCompatibilityAliases:
    def test_aliases_exist(self):
        # These are imported from the module
        assert RiskType is PSAK60RiskType
        assert CreditRiskExposure is PSAK60RiskExposure
        assert LiquidityRiskMaturity is PSAK60LiquidityRiskDisclosure
        assert MarketRiskSensitivity is PSAK60MarketRiskSensitivity


# ============================================================================
# Tests for Singleton Accessor
# ============================================================================

def test_get_psak60_validator():
    v1 = get_psak60_validator()
    v2 = get_psak60_validator()
    assert v1 is v2
    assert isinstance(v1, PSAK60Validator)


# ============================================================================
# Integration Tests
# ============================================================================

class TestIntegration:
    def test_full_disclosure_workflow(self, entity_id):
        validator = get_psak60_validator()

        # Create disclosure
        disclosure = validator.create_disclosure(
            entity_id=entity_id,
            entity_name="PT Instrumen Keuangan",
            reporting_date=datetime(2026, 12, 31, tzinfo=UTC),
        )

        # Add risk exposure
        exposure = validator.create_risk_exposure(
            risk_type=PSAK60RiskType.CREDIT_RISK,
            carrying_amount=Decimal("5000000000"),
            maximum_exposure=Decimal("5200000000"),
            collateral_held=Decimal("1000000000"),
        )
        disclosure = validator.add_risk_exposure(disclosure, exposure)

        # Add fair value disclosure
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

        # Add credit risk disclosure
        cr = validator.create_credit_risk_disclosure(
            portfolio_segment="Piutang Usaha",
            gross_carrying_amount=Decimal("2000000000"),
            loss_allowance=Decimal("10000000"),
            days_past_due=15,
            significant_increase_in_credit_risk=False,
        )
        disclosure = validator.add_credit_risk(disclosure, cr)

        # Add liquidity risk
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

        # Add market risk
        sens = validator.create_market_risk_sensitivity(
            risk_type=PSAK60RiskType.INTEREST_RATE_RISK,
            change_in_risk_variable="Kenaikan 100 bps",
            effect_on_profit_loss=Decimal("-50000000"),
            effect_on_equity=Decimal("-50000000"),
            assumptions="Semua variabel lain konstan",
        )
        disclosure = validator.add_market_risk(disclosure, sens)

        # Set collateral policies
        disclosure.collateral_policies = (
            "Entitas menerima agunan berupa kas, efek, dan properti untuk pinjaman yang diberikan"
        )

        # Validate
        result = validator.validate_disclosure(disclosure)
        assert result.is_compliant is True

        # Check totals
        assert disclosure.total_credit_exposure() == Decimal("2000000000")
        assert disclosure.total_loss_allowance() == Decimal("10000000")

        # Export to dict
        d = disclosure.to_dict()
        assert d["entity_name"] == "PT Instrumen Keuangan"
        assert len(d["risk_exposures"]) == 1
        assert len(d["fair_value"]) == 1
        assert len(d["credit_risk"]) == 1
        assert len(d["liquidity_risk"]) == 1
        assert len(d["market_risk"]) == 1
