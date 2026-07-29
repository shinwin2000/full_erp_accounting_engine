# test_psak_55_financial_instruments_recognition.py
# =====================================================
# Comprehensive tests for PSAK 55 Financial Instruments Recognition.
# Covers all public methods, edge cases, and domain logic.

from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from uuid import uuid4

import pytest

from policy_engine.psak.psak_55_financial_instruments_recognition import (
    ClassificationChangeError,
    DerecognitionResult,
    HedgeEffectivenessError,
    ModificationResult,
    PSAK55ComplianceLevel,
    PSAK55Error,
    PSAK55FinancialAsset,
    PSAK55FinancialAssetCategory,
    PSAK55FinancialInstrumentService,
    PSAK55FinancialLiability,
    PSAK55FinancialLiabilityCategory,
    PSAK55HedgeEffectivenessStatus,
    PSAK55HedgeRelationship,
    PSAK55HedgeType,
    PSAK55ImpairmentAssessment,
    PSAK55ImpairmentStatus,
    PSAK55Rules,
    PSAK55ValidationResult,
    PSAK55Validator,
    get_psak55_validator,
)


# ----------------------------------------------------------------------
# Enums
# ----------------------------------------------------------------------
class TestPSAK55FinancialAssetCategory:
    def test_members_exist(self):
        assert hasattr(PSAK55FinancialAssetCategory, "LOAN_AND_RECEIVABLE")
        assert hasattr(PSAK55FinancialAssetCategory, "HELD_TO_MATURITY")
        assert hasattr(PSAK55FinancialAssetCategory, "AVAILABLE_FOR_SALE")
        assert hasattr(PSAK55FinancialAssetCategory, "FAIR_VALUE_THROUGH_PROFIT_LOSS")

    def test_member_is_instance(self):
        assert isinstance(
            PSAK55FinancialAssetCategory.LOAN_AND_RECEIVABLE,
            PSAK55FinancialAssetCategory,
        )


class TestPSAK55FinancialLiabilityCategory:
    def test_members_exist(self):
        assert hasattr(PSAK55FinancialLiabilityCategory, "FAIR_VALUE_THROUGH_PROFIT_LOSS")
        assert hasattr(PSAK55FinancialLiabilityCategory, "OTHER_LIABILITIES")

    def test_member_is_instance(self):
        assert isinstance(
            PSAK55FinancialLiabilityCategory.FAIR_VALUE_THROUGH_PROFIT_LOSS,
            PSAK55FinancialLiabilityCategory,
        )


class TestPSAK55HedgeType:
    def test_members_exist(self):
        assert hasattr(PSAK55HedgeType, "FAIR_VALUE_HEDGE")
        assert hasattr(PSAK55HedgeType, "CASH_FLOW_HEDGE")
        assert hasattr(PSAK55HedgeType, "NET_INVESTMENT_HEDGE")

    def test_member_is_instance(self):
        assert isinstance(PSAK55HedgeType.FAIR_VALUE_HEDGE, PSAK55HedgeType)


class TestPSAK55HedgeEffectivenessStatus:
    def test_members_exist(self):
        assert hasattr(PSAK55HedgeEffectivenessStatus, "HIGHLY_EFFECTIVE")
        assert hasattr(PSAK55HedgeEffectivenessStatus, "PARTIALLY_EFFECTIVE")
        assert hasattr(PSAK55HedgeEffectivenessStatus, "INEFFECTIVE")

    def test_member_is_instance(self):
        assert isinstance(
            PSAK55HedgeEffectivenessStatus.HIGHLY_EFFECTIVE,
            PSAK55HedgeEffectivenessStatus,
        )


class TestPSAK55ImpairmentStatus:
    def test_members_exist(self):
        assert hasattr(PSAK55ImpairmentStatus, "NOT_IMPAIRED")
        assert hasattr(PSAK55ImpairmentStatus, "INDIVIDUAL_IMPAIRED")
        assert hasattr(PSAK55ImpairmentStatus, "COLLECTIVE_IMPAIRED")

    def test_member_is_instance(self):
        assert isinstance(PSAK55ImpairmentStatus.NOT_IMPAIRED, PSAK55ImpairmentStatus)


class TestPSAK55ComplianceLevel:
    def test_members_exist(self):
        assert hasattr(PSAK55ComplianceLevel, "FULL")
        assert hasattr(PSAK55ComplianceLevel, "SUBSTANTIAL")
        assert hasattr(PSAK55ComplianceLevel, "PARTIAL")
        assert hasattr(PSAK55ComplianceLevel, "NON_COMPLIANT")

    def test_member_is_instance(self):
        assert isinstance(PSAK55ComplianceLevel.FULL, PSAK55ComplianceLevel)


# ----------------------------------------------------------------------
# Exceptions
# ----------------------------------------------------------------------
class TestPSAK55Error:
    def test_construction(self):
        err = PSAK55Error("test")
        assert str(err) == "test"


class TestClassificationChangeError:
    def test_construction(self):
        err = ClassificationChangeError("change not allowed")
        assert str(err) == "change not allowed"


class TestHedgeEffectivenessError:
    def test_construction(self):
        err = HedgeEffectivenessError("not effective")
        assert str(err) == "not effective"


# ----------------------------------------------------------------------
# Value Objects
# ----------------------------------------------------------------------
class TestPSAK55FinancialAsset:
    @pytest.fixture
    def asset(self) -> PSAK55FinancialAsset:
        return PSAK55FinancialAsset(
            asset_id=uuid4(),
            asset_name="Test Loan",
            category=PSAK55FinancialAssetCategory.LOAN_AND_RECEIVABLE,
            principal=Decimal("1000000"),
            interest_rate=Decimal("10"),
            acquisition_date=datetime(2025, 1, 1, tzinfo=UTC),
            maturity_date=datetime(2026, 1, 1, tzinfo=UTC),
        )

    def test_construction(self, asset):
        assert asset.asset_name == "Test Loan"
        assert asset.amortized_cost == Decimal("1000000")
        assert asset.effective_interest_rate == Decimal("10")

    def test_carrying_amount_amortized_cost(self, asset):
        # For LOAN_AND_RECEIVABLE, carrying = amortized cost - impairment
        assert asset.carrying_amount() == Decimal("1000000")
        asset.accumulated_impairment = Decimal("100000")
        assert asset.carrying_amount() == Decimal("900000")

    def test_carrying_amount_fair_value(self):
        asset = PSAK55FinancialAsset(
            asset_id=uuid4(),
            asset_name="Test FVTPL",
            category=PSAK55FinancialAssetCategory.FAIR_VALUE_THROUGH_PROFIT_LOSS,
            principal=Decimal("1000000"),
            interest_rate=Decimal("5"),
            acquisition_date=datetime(2025, 1, 1, tzinfo=UTC),
            fair_value=Decimal("1050000"),
        )
        assert asset.carrying_amount() == Decimal("1050000")

        asset.fair_value = None
        assert asset.carrying_amount() == asset.amortized_cost

    def test_interest_revenue(self, asset):
        # Full year interest: 1,000,000 * 10% = 100,000
        start = datetime(2025, 1, 1, tzinfo=UTC)
        end = datetime(2026, 1, 1, tzinfo=UTC)
        interest = asset.interest_revenue(start, end)
        assert interest == Decimal("100000")  # Rounded to integer

        # Half year: ~50,000
        end = datetime(2025, 7, 1, tzinfo=UTC)
        # Days = 181 (2025 is not leap year)
        interest = asset.interest_revenue(start, end)
        # 1,000,000 * (10/100) * (181/365) ≈ 49589.04 -> rounded 49589
        expected = (Decimal("1000000") * Decimal("0.10") * Decimal("181") / Decimal("365")).quantize(
            Decimal("0"), rounding=ROUND_HALF_EVEN
        )
        assert interest == expected

        # Zero rate
        asset.effective_interest_rate = Decimal("0")
        assert asset.interest_revenue(start, end) == Decimal("0")

        # Zero principal
        asset.amortized_cost = Decimal("0")
        assert asset.interest_revenue(start, end) == Decimal("0")

    def test_to_dict(self, asset):
        d = asset.to_dict()
        assert d["asset_name"] == "Test Loan"
        assert d["category"] == "pinjaman_dan_piutang"
        assert d["principal"] == "1000000"
        assert d["carrying_amount"] == "1000000"


class TestPSAK55FinancialLiability:
    @pytest.fixture
    def liability(self) -> PSAK55FinancialLiability:
        return PSAK55FinancialLiability(
            liability_id=uuid4(),
            liability_name="Test Bond",
            category=PSAK55FinancialLiabilityCategory.OTHER_LIABILITIES,
            principal=Decimal("2000000"),
            interest_rate=Decimal("8"),
            acquisition_date=datetime(2025, 1, 1, tzinfo=UTC),
            maturity_date=datetime(2027, 1, 1, tzinfo=UTC),
        )

    def test_construction(self, liability):
        assert liability.liability_name == "Test Bond"
        assert liability.amortized_cost == Decimal("2000000")
        assert liability.effective_interest_rate == Decimal("8")

    def test_carrying_amount(self, liability):
        # For OTHER_LIABILITIES, carrying = amortized cost
        assert liability.carrying_amount() == Decimal("2000000")

        liability.fair_value = Decimal("1900000")
        # Still amortized cost unless FVTPL
        assert liability.carrying_amount() == Decimal("2000000")

        # FVTPL category
        liability.category = PSAK55FinancialLiabilityCategory.FAIR_VALUE_THROUGH_PROFIT_LOSS
        assert liability.carrying_amount() == Decimal("1900000")

    def test_interest_expense(self, liability):
        start = datetime(2025, 1, 1, tzinfo=UTC)
        end = datetime(2026, 1, 1, tzinfo=UTC)
        expense = liability.interest_expense(start, end)
        # 2,000,000 * 8% = 160,000
        assert expense == Decimal("160000")

        # Half year
        end = datetime(2025, 7, 1, tzinfo=UTC)
        expected = (Decimal("2000000") * Decimal("0.08") * Decimal("181") / Decimal("365")).quantize(
            Decimal("0"), rounding=ROUND_HALF_EVEN
        )
        assert liability.interest_expense(start, end) == expected

        # Zero rate
        liability.effective_interest_rate = Decimal("0")
        assert liability.interest_expense(start, end) == Decimal("0")

    def test_to_dict(self, liability):
        d = liability.to_dict()
        assert d["liability_name"] == "Test Bond"
        assert d["principal"] == "2000000"
        assert d["carrying_amount"] == "2000000"


class TestPSAK55ImpairmentAssessment:
    def test_construction_and_calculation(self):
        assessment_date = datetime(2025, 12, 31, tzinfo=UTC)
        future_cf = [
            (datetime(2026, 12, 31, tzinfo=UTC), Decimal("800000")),
        ]
        assessment = PSAK55ImpairmentAssessment(
            assessment_id=uuid4(),
            asset_id=uuid4(),
            assessment_date=assessment_date,
            objective_evidence=["Financial difficulty"],
            estimated_future_cash_flows=future_cf,
            discount_rate_original=Decimal("10"),
            present_value_expected_cash_flows=Decimal(0),  # will be computed
            carrying_amount_before=Decimal("1000000"),
        )
        # PV: 800,000 / (1.10)^1 ≈ 727,272.72 -> rounded to 727273
        expected_pv = (Decimal("800000") / Decimal("1.10")).quantize(
            Decimal("0"), rounding=ROUND_HALF_EVEN
        )
        assert assessment.present_value_expected_cash_flows == expected_pv
        expected_loss = Decimal("1000000") - expected_pv
        assert assessment.impairment_loss == expected_loss

        # If impairment loss would be negative, it becomes 0
        assessment.carrying_amount_before = Decimal("700000")
        # Re-run __post_init__ manually? We'll create a new one.
        assessment2 = PSAK55ImpairmentAssessment(
            assessment_id=uuid4(),
            asset_id=uuid4(),
            assessment_date=assessment_date,
            objective_evidence=["Financial difficulty"],
            estimated_future_cash_flows=future_cf,
            discount_rate_original=Decimal("10"),
            present_value_expected_cash_flows=Decimal(0),
            carrying_amount_before=Decimal("700000"),
        )
        assert assessment2.impairment_loss == Decimal("0")

    def test_to_dict(self):
        assessment = PSAK55ImpairmentAssessment(
            assessment_id=uuid4(),
            asset_id=uuid4(),
            assessment_date=datetime(2025, 12, 31, tzinfo=UTC),
            objective_evidence=["Evidence1"],
            estimated_future_cash_flows=[],
            discount_rate_original=Decimal("5"),
            present_value_expected_cash_flows=Decimal("100000"),
            carrying_amount_before=Decimal("200000"),
            impairment_loss=Decimal("100000"),
        )
        d = assessment.to_dict()
        assert d["impairment_loss"] == "100000"
        assert d["carrying_before"] == "200000"


class TestPSAK55HedgeRelationship:
    def test_effectiveness_status_auto(self):
        # Highly effective: 0.95
        hedge = PSAK55HedgeRelationship(
            hedge_id=uuid4(),
            hedge_type=PSAK55HedgeType.FAIR_VALUE_HEDGE,
            hedged_item_id=uuid4(),
            hedging_instrument_id=uuid4(),
            designation_date=datetime(2025, 1, 1, tzinfo=UTC),
            effectiveness_ratio=Decimal("0.95"),
            effectiveness_status=PSAK55HedgeEffectivenessStatus.HIGHLY_EFFECTIVE,
        )
        assert hedge.effectiveness_status == PSAK55HedgeEffectivenessStatus.HIGHLY_EFFECTIVE

        # Ineffective: 0.7
        hedge2 = PSAK55HedgeRelationship(
            hedge_id=uuid4(),
            hedge_type=PSAK55HedgeType.CASH_FLOW_HEDGE,
            hedged_item_id=uuid4(),
            hedging_instrument_id=uuid4(),
            designation_date=datetime(2025, 1, 1, tzinfo=UTC),
            effectiveness_ratio=Decimal("0.7"),
            effectiveness_status=PSAK55HedgeEffectivenessStatus.HIGHLY_EFFECTIVE,
        )
        assert hedge2.effectiveness_status == PSAK55HedgeEffectivenessStatus.INEFFECTIVE

        # Partially effective: 0.79
        hedge3 = PSAK55HedgeRelationship(
            hedge_id=uuid4(),
            hedge_type=PSAK55HedgeType.NET_INVESTMENT_HEDGE,
            hedged_item_id=uuid4(),
            hedging_instrument_id=uuid4(),
            designation_date=datetime(2025, 1, 1, tzinfo=UTC),
            effectiveness_ratio=Decimal("0.79"),
            effectiveness_status=PSAK55HedgeEffectivenessStatus.HIGHLY_EFFECTIVE,
        )
        assert hedge3.effectiveness_status == PSAK55HedgeEffectivenessStatus.PARTIALLY_EFFECTIVE

    def test_to_dict(self):
        hedge = PSAK55HedgeRelationship(
            hedge_id=uuid4(),
            hedge_type=PSAK55HedgeType.FAIR_VALUE_HEDGE,
            hedged_item_id=uuid4(),
            hedging_instrument_id=uuid4(),
            designation_date=datetime(2025, 1, 1, tzinfo=UTC),
            effectiveness_ratio=Decimal("1.1"),
            effectiveness_status=PSAK55HedgeEffectivenessStatus.HIGHLY_EFFECTIVE,
        )
        d = hedge.to_dict()
        assert d["hedge_type"] == "lindung_nilai_nilai_wajar"
        assert d["effectiveness_ratio"] == "1.1"


class TestPSAK55ValidationResult:
    def test_construction(self):
        result = PSAK55ValidationResult(
            is_compliant=True,
            compliance_level=PSAK55ComplianceLevel.FULL,
            errors=[],
            warnings=[],
        )
        assert result.is_compliant is True
        assert result.compliance_level == PSAK55ComplianceLevel.FULL
        assert result.hash_sha256 != ""

    def test_add_error(self):
        result = PSAK55ValidationResult(
            is_compliant=True,
            compliance_level=PSAK55ComplianceLevel.FULL,
        )
        result.add_error("Test error")
        assert result.is_compliant is False
        assert result.compliance_level == PSAK55ComplianceLevel.NON_COMPLIANT
        assert "Test error" in result.errors

    def test_add_warning(self):
        result = PSAK55ValidationResult(
            is_compliant=True,
            compliance_level=PSAK55ComplianceLevel.FULL,
        )
        result.add_warning("Test warning")
        # is_compliant remains True
        assert result.is_compliant is True
        # compliance level degrades from FULL to SUBSTANTIAL
        assert result.compliance_level == PSAK55ComplianceLevel.SUBSTANTIAL
        assert "Test warning" in result.warnings

        # If already SUBSTANTIAL, adding warning stays SUBSTANTIAL
        result.add_warning("Another warning")
        assert result.compliance_level == PSAK55ComplianceLevel.SUBSTANTIAL
        assert len(result.warnings) == 2

    def test_to_dict(self):
        result = PSAK55ValidationResult(
            is_compliant=False,
            compliance_level=PSAK55ComplianceLevel.NON_COMPLIANT,
            errors=["err1"],
            warnings=["warn1"],
        )
        d = result.to_dict()
        assert d["is_compliant"] is False
        assert d["compliance_level"] == "tidak_patuh"
        assert d["errors"] == ["err1"]
        assert d["warnings"] == ["warn1"]
        assert d["hash"] == result.hash_sha256


# ----------------------------------------------------------------------
# Domain Service: PSAK55FinancialInstrumentService
# ----------------------------------------------------------------------
class TestPSAK55FinancialInstrumentService:
    @pytest.fixture
    def service(self) -> PSAK55FinancialInstrumentService:
        return PSAK55FinancialInstrumentService()

    def test_effective_interest_rate_single_cashflow(self, service):
        now = datetime.now(UTC)
        maturity = now + timedelta(days=365)
        cash_flows = [(maturity, Decimal("1100"))]
        principal = Decimal("1000")
        # EIR = (1100/1000)^(1/1) - 1 = 10%
        eir = service.effective_interest_rate(principal, cash_flows)
        assert eir == Decimal("10.00")  # Quantized to 0.01

        # Zero days: should return 0
        cash_flows = [(now, Decimal("1000"))]
        eir = service.effective_interest_rate(principal, cash_flows)
        assert eir == Decimal("0")

        # Multiple cash flows: placeholder returns 5%
        cash_flows = [(now + timedelta(days=180), Decimal("500")),
                      (now + timedelta(days=365), Decimal("600"))]
        eir = service.effective_interest_rate(principal, cash_flows)
        assert eir == Decimal("5.00")  # default placeholder

    def test_classify_asset(self, service):
        # hold_to_collect + contractual = LOAN_AND_RECEIVABLE
        cat = service.classify_asset("hold_to_collect", True)
        assert cat == PSAK55FinancialAssetCategory.LOAN_AND_RECEIVABLE

        # hold_to_collect + non-contractual = HELD_TO_MATURITY
        cat = service.classify_asset("hold_to_collect", False)
        assert cat == PSAK55FinancialAssetCategory.HELD_TO_MATURITY

        # hold_to_collect_and_sell + contractual = AVAILABLE_FOR_SALE
        cat = service.classify_asset("hold_to_collect_and_sell", True)
        assert cat == PSAK55FinancialAssetCategory.AVAILABLE_FOR_SALE

        # hold_to_collect_and_sell + non-contractual = AVAILABLE_FOR_SALE
        cat = service.classify_asset("hold_to_collect_and_sell", False)
        assert cat == PSAK55FinancialAssetCategory.AVAILABLE_FOR_SALE

        # other -> FVTPL
        cat = service.classify_asset("trading", True)
        assert cat == PSAK55FinancialAssetCategory.FAIR_VALUE_THROUGH_PROFIT_LOSS

    def test_calculate_impairment_collective(self, service):
        # Create a portfolio of loans
        asset1 = PSAK55FinancialAsset(
            asset_id=uuid4(),
            asset_name="Loan1",
            category=PSAK55FinancialAssetCategory.LOAN_AND_RECEIVABLE,
            principal=Decimal("1000000"),
            interest_rate=Decimal("5"),
            acquisition_date=datetime(2025, 1, 1, tzinfo=UTC),
        )
        asset2 = PSAK55FinancialAsset(
            asset_id=uuid4(),
            asset_name="Loan2",
            category=PSAK55FinancialAssetCategory.HELD_TO_MATURITY,
            principal=Decimal("500000"),
            interest_rate=Decimal("6"),
            acquisition_date=datetime(2025, 1, 1, tzinfo=UTC),
        )
        # An FVTPL asset should be excluded
        asset3 = PSAK55FinancialAsset(
            asset_id=uuid4(),
            asset_name="FVTPL",
            category=PSAK55FinancialAssetCategory.FAIR_VALUE_THROUGH_PROFIT_LOSS,
            principal=Decimal("200000"),
            interest_rate=Decimal("4"),
            acquisition_date=datetime(2025, 1, 1, tzinfo=UTC),
        )
        portfolio = [asset1, asset2, asset3]
        loss_rate = Decimal("2")  # 2%
        impairment = service.calculate_impairment_collective(portfolio, loss_rate, Decimal("0"))
        # Only asset1 and asset2 are impaired: (1,000,000 + 500,000) * 2% = 30,000
        expected = (Decimal("1500000") * Decimal("2") / 100).quantize(
            Decimal("0"), rounding=ROUND_HALF_EVEN
        )
        assert impairment == expected

        # If loss_rate is 0
        impairment = service.calculate_impairment_collective(portfolio, Decimal("0"), Decimal("0"))
        assert impairment == Decimal("0")


# ----------------------------------------------------------------------
# Rules
# ----------------------------------------------------------------------
class TestPSAK55Rules:
    @pytest.fixture
    def rules(self) -> PSAK55Rules:
        return PSAK55Rules()

    def test_validate_classification_change_valid(self, rules):
        # Changing from LOAN to FVTPL is allowed (no specific restriction)
        result = rules.validate_classification_change(
            PSAK55FinancialAssetCategory.LOAN_AND_RECEIVABLE,
            PSAK55FinancialAssetCategory.FAIR_VALUE_THROUGH_PROFIT_LOSS,
        )
        assert result.is_compliant is True
        assert result.compliance_level == PSAK55ComplianceLevel.FULL
        assert len(result.errors) == 0

    def test_validate_classification_change_invalid(self, rules):
        # Changing from HELD_TO_MATURITY to anything else should fail
        result = rules.validate_classification_change(
            PSAK55FinancialAssetCategory.HELD_TO_MATURITY,
            PSAK55FinancialAssetCategory.AVAILABLE_FOR_SALE,
        )
        assert result.is_compliant is False
        assert result.compliance_level == PSAK55ComplianceLevel.NON_COMPLIANT
        assert any("held-to-maturity" in err.lower() for err in result.errors)

    def test_validate_impairment_evidence(self, rules):
        # Evidence provided => pass
        result = rules.validate_impairment_evidence(["Significant financial difficulty"])
        assert result.is_compliant is True
        assert result.compliance_level == PSAK55ComplianceLevel.FULL
        assert len(result.warnings) == 0

        # No evidence => warning
        result = rules.validate_impairment_evidence([])
        assert result.is_compliant is True
        assert result.compliance_level == PSAK55ComplianceLevel.SUBSTANTIAL
        assert any("bukti objektif" in w.lower() for w in result.warnings)

    def test_validate_hedge_effectiveness(self, rules):
        # Within range => pass
        result = rules.validate_hedge_effectiveness(Decimal("0.95"))
        assert result.is_compliant is True
        assert result.compliance_level == PSAK55ComplianceLevel.FULL

        result = rules.validate_hedge_effectiveness(Decimal("1.20"))
        assert result.is_compliant is True

        # Outside range => error
        result = rules.validate_hedge_effectiveness(Decimal("0.79"))
        assert result.is_compliant is False
        assert result.compliance_level == PSAK55ComplianceLevel.NON_COMPLIANT
        assert any("80-125" in err for err in result.errors)

        result = rules.validate_hedge_effectiveness(Decimal("1.26"))
        assert result.is_compliant is False


# ----------------------------------------------------------------------
# Validator
# ----------------------------------------------------------------------
class TestPSAK55Validator:
    @pytest.fixture
    def validator(self) -> PSAK55Validator:
        return PSAK55Validator()

    def test_create_asset(self, validator):
        asset = validator.create_asset(
            asset_name="Test Asset",
            category=PSAK55FinancialAssetCategory.LOAN_AND_RECEIVABLE,
            principal=Decimal("100000"),
            interest_rate=Decimal("12"),
            acquisition_date=datetime(2025, 1, 1, tzinfo=UTC),
            maturity_date=datetime(2026, 1, 1, tzinfo=UTC),
            fair_value=Decimal("105000"),
        )
        assert isinstance(asset, PSAK55FinancialAsset)
        assert asset.asset_name == "Test Asset"
        assert asset.principal == Decimal("100000")
        assert asset.amortized_cost == Decimal("100000")

    def test_create_liability(self, validator):
        liability = validator.create_liability(
            liability_name="Test Liability",
            category=PSAK55FinancialLiabilityCategory.OTHER_LIABILITIES,
            principal=Decimal("500000"),
            interest_rate=Decimal("7"),
            acquisition_date=datetime(2025, 1, 1, tzinfo=UTC),
            maturity_date=datetime(2027, 1, 1, tzinfo=UTC),
            fair_value=Decimal("480000"),
        )
        assert isinstance(liability, PSAK55FinancialLiability)
        assert liability.liability_name == "Test Liability"
        assert liability.principal == Decimal("500000")

    def test_classify_asset(self, validator):
        cat = validator.classify_asset("hold_to_collect", True)
        assert cat == PSAK55FinancialAssetCategory.LOAN_AND_RECEIVABLE

    def test_record_amortization(self, validator):
        asset = PSAK55FinancialAsset(
            asset_id=uuid4(),
            asset_name="Amort Test",
            category=PSAK55FinancialAssetCategory.LOAN_AND_RECEIVABLE,
            principal=Decimal("1000000"),
            interest_rate=Decimal("10"),
            acquisition_date=datetime(2025, 1, 1, tzinfo=UTC),
            maturity_date=datetime(2026, 1, 1, tzinfo=UTC),
        )
        period_end = datetime(2025, 12, 31, tzinfo=UTC)
        updated = validator.record_amortization(asset, period_end)
        # Interest = 1,000,000 * 10% = 100,000 (rounded to integer)
        expected_cost = Decimal("1100000")
        assert updated.amortized_cost == expected_cost
        # Other fields preserved
        assert updated.asset_id == asset.asset_id
        assert updated.asset_name == asset.asset_name
        assert updated.principal == asset.principal
        assert updated.accumulated_impairment == asset.accumulated_impairment

    def test_assess_impairment(self, validator):
        asset = PSAK55FinancialAsset(
            asset_id=uuid4(),
            asset_name="Impaired Asset",
            category=PSAK55FinancialAssetCategory.LOAN_AND_RECEIVABLE,
            principal=Decimal("1000000"),
            interest_rate=Decimal("10"),
            acquisition_date=datetime(2025, 1, 1, tzinfo=UTC),
            maturity_date=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assessment_date = datetime(2025, 12, 31, tzinfo=UTC)
        evidence = ["Borrower in default"]
        future_cf = [(datetime(2026, 12, 31, tzinfo=UTC), Decimal("700000"))]

        assessment = validator.assess_impairment(
            asset=asset,
            objective_evidence=evidence,
            estimated_future_cash_flows=future_cf,
            assessment_date=assessment_date,
        )
        assert isinstance(assessment, PSAK55ImpairmentAssessment)
        assert assessment.asset_id == asset.asset_id
        assert assessment.carrying_amount_before == asset.carrying_amount()
        # PV = 700,000 / 1.10 = 636,363.63 -> rounded 636364
        expected_pv = (Decimal("700000") / Decimal("1.10")).quantize(
            Decimal("0"), rounding=ROUND_HALF_EVEN
        )
        assert assessment.present_value_expected_cash_flows == expected_pv
        expected_loss = Decimal("1000000") - expected_pv
        assert assessment.impairment_loss == expected_loss

    def test_create_hedge_relationship(self, validator):
        hedge = validator.create_hedge_relationship(
            hedge_type=PSAK55HedgeType.CASH_FLOW_HEDGE,
            hedged_item_id=uuid4(),
            hedging_instrument_id=uuid4(),
            effectiveness_ratio=Decimal("0.95"),
            designation_date=datetime(2025, 1, 1, tzinfo=UTC),
        )
        assert isinstance(hedge, PSAK55HedgeRelationship)
        assert hedge.hedge_type == PSAK55HedgeType.CASH_FLOW_HEDGE
        assert hedge.effectiveness_status == PSAK55HedgeEffectivenessStatus.HIGHLY_EFFECTIVE

    def test_validate_impairment(self, validator):
        # Create an impairment assessment with loss
        asset = PSAK55FinancialAsset(
            asset_id=uuid4(),
            asset_name="Test",
            category=PSAK55FinancialAssetCategory.LOAN_AND_RECEIVABLE,
            principal=Decimal("1000000"),
            interest_rate=Decimal("10"),
            acquisition_date=datetime(2025, 1, 1, tzinfo=UTC),
        )
        assessment = PSAK55ImpairmentAssessment(
            assessment_id=uuid4(),
            asset_id=asset.asset_id,
            assessment_date=datetime(2025, 12, 31, tzinfo=UTC),
            objective_evidence=["Evidence"],
            estimated_future_cash_flows=[(datetime(2026, 12, 31, tzinfo=UTC), Decimal("800000"))],
            discount_rate_original=Decimal("10"),
            present_value_expected_cash_flows=Decimal(0),
            carrying_amount_before=Decimal("1000000"),
        )
        # Force present value calculation? It's done in __post_init__.
        # We'll just use the assessment's own loss.
        result = validator.validate_impairment(assessment)
        # Should add warning about impairment loss
        assert result.is_compliant is True
        assert result.compliance_level == PSAK55ComplianceLevel.SUBSTANTIAL  # due to warning
        assert any("kerugian penurunan nilai" in w for w in result.warnings)

        # If no evidence, warning about evidence
        assessment.objective_evidence = []
        result = validator.validate_impairment(assessment)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK55ComplianceLevel.SUBSTANTIAL
        # Should have warning about no evidence and about impairment loss
        assert any("bukti objektif" in w for w in result.warnings)
        assert any("kerugian penurunan nilai" in w for w in result.warnings)

    def test_validate_hedge(self, validator):
        hedge = PSAK55HedgeRelationship(
            hedge_id=uuid4(),
            hedge_type=PSAK55HedgeType.FAIR_VALUE_HEDGE,
            hedged_item_id=uuid4(),
            hedging_instrument_id=uuid4(),
            designation_date=datetime(2025, 1, 1, tzinfo=UTC),
            effectiveness_ratio=Decimal("0.95"),
            effectiveness_status=PSAK55HedgeEffectivenessStatus.HIGHLY_EFFECTIVE,
        )
        result = validator.validate_hedge(hedge)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK55ComplianceLevel.FULL

        # Ineffective hedge
        hedge.effectiveness_ratio = Decimal("0.7")
        result = validator.validate_hedge(hedge)
        assert result.is_compliant is False
        assert result.compliance_level == PSAK55ComplianceLevel.NON_COMPLIANT
        assert any("80-125" in err for err in result.errors)

    def test_validate_asset(self, validator):
        asset = PSAK55FinancialAsset(
            asset_id=uuid4(),
            asset_name="Good",
            category=PSAK55FinancialAssetCategory.LOAN_AND_RECEIVABLE,
            principal=Decimal("1000"),
            interest_rate=Decimal("5"),
            acquisition_date=datetime(2025, 1, 1, tzinfo=UTC),
            maturity_date=datetime(2026, 1, 1, tzinfo=UTC),
        )
        result = validator.validate_asset(asset)
        assert result.is_compliant is True

        # HTM without maturity date -> error
        asset.category = PSAK55FinancialAssetCategory.HELD_TO_MATURITY
        asset.maturity_date = None
        result = validator.validate_asset(asset)
        assert result.is_compliant is False
        assert any("jatuh tempo" in err for err in result.errors)

    def test_get_requirements_summary(self, validator):
        summary = validator.get_requirements_summary()
        assert "classification" in summary
        assert "impairment" in summary
        assert "hedge_accounting" in summary
        assert isinstance(summary["disclosures"], list)


# ----------------------------------------------------------------------
# Compatibility Stubs
# ----------------------------------------------------------------------
class TestDerecognitionResult:
    def test_construction(self):
        result = DerecognitionResult(
            is_derecognized=True,
            gain_loss=Decimal("1000"),
            carrying_amount_derecognized=Decimal("5000"),
            notes="Test",
        )
        assert result.is_derecognized is True
        assert result.gain_loss == Decimal("1000")


class TestModificationResult:
    def test_construction(self):
        result = ModificationResult(
            is_substantial=True,
            modification_gain_loss=Decimal("200"),
            new_amortized_cost=Decimal("800"),
            notes="Modified",
        )
        assert result.is_substantial is True
        assert result.new_amortized_cost == Decimal("800")


# ----------------------------------------------------------------------
# Singleton Accessor
# ----------------------------------------------------------------------
def test_get_psak55_validator_singleton():
    v1 = get_psak55_validator()
    v2 = get_psak55_validator()
    assert v1 is v2
    assert isinstance(v1, PSAK55Validator)
