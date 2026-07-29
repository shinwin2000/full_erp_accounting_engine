#!/usr/bin/env python3
"""
tests/policy_engine/psak/test_psak_19_intangible_assets.py
Comprehensive tests for policy_engine/psak/psak_19_intangible_assets.py

Covers:
- All enums (PSAK19IntangibleType, PSAK19AcquisitionMethod, PSAK19MeasurementModel,
  PSAK19AmortizationMethod, PSAK19UsefulLifeType, PSAK19DevelopmentPhaseCriteria,
  PSAK19ComplianceLevel)
- Exceptions (PSAK19Error, IntangibleAssetNotFoundError, InvalidAmortizationError,
  DevelopmentCostNotCapitalizableError)
- Data classes: PSAK19RevaluationSurplus, PSAK19IntangibleAsset, PSAK19IntangibleRegister,
  PSAK19ValidationResult
- Domain services: PSAK19IntangibleService
- Rules: PSAK19Rules
- Validator: PSAK19Validator (create_asset, create_register, add_asset, record_amortization,
  record_research_expense, record_development_capitalization, revalue_asset, dispose_asset,
  validate_register, get_requirements_summary)
- PSAK19 wrapper
- Singleton get_psak19_validator
- All edge cases and negative paths
- No flaky tests (datetime mocked)
- No duplicate test structures (parametrized where appropriate)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest

from policy_engine.psak.psak_19_intangible_assets import (
    PSAK19,
    DevelopmentCostNotCapitalizableError,
    IntangibleAssetNotFoundError,
    InvalidAmortizationError,
    PSAK19AcquisitionMethod,
    PSAK19AmortizationMethod,
    PSAK19ComplianceLevel,
    PSAK19DevelopmentPhaseCriteria,
    PSAK19Error,
    PSAK19IntangibleAsset,
    PSAK19IntangibleRegister,
    PSAK19IntangibleService,
    PSAK19IntangibleType,
    PSAK19MeasurementModel,
    PSAK19RevaluationSurplus,
    PSAK19Rules,
    PSAK19UsefulLifeType,
    PSAK19ValidationResult,
    PSAK19Validator,
    get_psak19_validator,
)

# =============================================================================
# Fixtures
# =============================================================================

FIXED_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
FIXED_DATE = FIXED_NOW.date()


@pytest.fixture(autouse=True)
def mock_datetime_now():
    """Mock datetime.now and datetime.utcnow to return a fixed datetime."""
    with patch("policy_engine.psak.psak_19_intangible_assets.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.utcnow.return_value = FIXED_NOW
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        yield mock_dt


@pytest.fixture
def sample_asset():
    """Create a basic PSAK19IntangibleAsset with finite useful life."""
    return PSAK19IntangibleAsset(
        asset_id=uuid.uuid4(),
        asset_code="PAT-001",
        name="Sample Patent",
        asset_type=PSAK19IntangibleType.PATENT,
        acquisition_method=PSAK19AcquisitionMethod.SEPARATE_PURCHASE,
        measurement_model=PSAK19MeasurementModel.COST,
        acquisition_date=FIXED_NOW - timedelta(days=365 * 4),  # 4 years ago
        cost=Decimal("200000000"),
        useful_life_type=PSAK19UsefulLifeType.FINITE,
        useful_life_years=10,
        residual_value=Decimal("0"),
        amortization_method=PSAK19AmortizationMethod.STRAIGHT_LINE,
        accumulated_amortization=Decimal("0"),
        accumulated_impairment=Decimal("0"),
        revaluation_surplus_history=[],
        current_revaluation_surplus=Decimal("0"),
        last_revaluation_date=None,
        is_active=True,
        disposal_date=None,
        disposal_proceeds=Decimal("0"),
        disposal_cost=Decimal("0"),
        development_criteria_met=False,
        development_criteria_details=[],
    )


@pytest.fixture
def sample_asset_indefinite():
    """Asset with indefinite useful life."""
    return PSAK19IntangibleAsset(
        asset_id=uuid.uuid4(),
        asset_code="BRAND-001",
        name="Brand Name",
        asset_type=PSAK19IntangibleType.BRAND,
        acquisition_method=PSAK19AcquisitionMethod.INTERNALLY_GENERATED,
        measurement_model=PSAK19MeasurementModel.COST,
        acquisition_date=FIXED_NOW - timedelta(days=365),
        cost=Decimal("100000000"),
        useful_life_type=PSAK19UsefulLifeType.INDEFINITE,
        useful_life_years=None,
        residual_value=Decimal("0"),
        amortization_method=PSAK19AmortizationMethod.STRAIGHT_LINE,
    )


@pytest.fixture
def sample_asset_revaluation():
    """Asset with revaluation model and allowed type (PATENT)."""
    return PSAK19IntangibleAsset(
        asset_id=uuid.uuid4(),
        asset_code="PAT-REV-001",
        name="Revaluable Patent",
        asset_type=PSAK19IntangibleType.PATENT,
        acquisition_method=PSAK19AcquisitionMethod.SEPARATE_PURCHASE,
        measurement_model=PSAK19MeasurementModel.REVALUATION,
        acquisition_date=FIXED_NOW - timedelta(days=365 * 3),
        cost=Decimal("300000000"),
        useful_life_type=PSAK19UsefulLifeType.FINITE,
        useful_life_years=15,
        residual_value=Decimal("0"),
        amortization_method=PSAK19AmortizationMethod.STRAIGHT_LINE,
        accumulated_amortization=Decimal("0"),
        accumulated_impairment=Decimal("0"),
        revaluation_surplus_history=[],
        current_revaluation_surplus=Decimal("0"),
        last_revaluation_date=None,
        is_active=True,
        disposal_date=None,
        disposal_proceeds=Decimal("0"),
        disposal_cost=Decimal("0"),
        development_criteria_met=False,
        development_criteria_details=[],
    )


@pytest.fixture
def sample_register():
    """Create a register with one sample asset."""
    validator = PSAK19Validator()
    entity_id = uuid.uuid4()
    register = validator.create_register(
        entity_id=entity_id,
        entity_name="PT Inovasi Digital",
        reporting_date=FIXED_NOW,
    )
    asset = validator.create_asset(
        asset_code="PAT-001",
        name="Paten Teknologi XYZ",
        asset_type=PSAK19IntangibleType.PATENT,
        acquisition_method=PSAK19AcquisitionMethod.SEPARATE_PURCHASE,
        measurement_model=PSAK19MeasurementModel.COST,
        acquisition_date=FIXED_NOW - timedelta(days=365 * 4),
        cost=Decimal("200000000"),
        useful_life_type=PSAK19UsefulLifeType.FINITE,
        useful_life_years=10,
    )
    register = validator.add_asset(register, asset)
    return register


# =============================================================================
# Tests for Enums (parametrized to avoid duplicates)
# =============================================================================

class TestEnums:
    @pytest.mark.parametrize(
        "enum_cls, expected_members",
        [
            (PSAK19IntangibleType, ["PATENT", "TRADEMARK", "COPYRIGHT", "SOFTWARE", "LICENSE",
                                     "FRANCHISE", "CUSTOMER_RELATIONSHIP", "BRAND", "GOODWILL",
                                     "RESEARCH", "DEVELOPMENT", "OTHER"]),
            (PSAK19AcquisitionMethod, ["SEPARATE_PURCHASE", "BUSINESS_COMBINATION",
                                       "INTERNALLY_GENERATED", "GOVERNMENT_GRANT", "EXCHANGE"]),
            (PSAK19MeasurementModel, ["COST", "REVALUATION"]),
            (PSAK19AmortizationMethod, ["STRAIGHT_LINE", "DECLINING_BALANCE", "UNITS_OF_PRODUCTION"]),
            (PSAK19UsefulLifeType, ["FINITE", "INDEFINITE"]),
            (PSAK19DevelopmentPhaseCriteria, ["TECHNICAL_FEASIBILITY", "INTENTION_TO_COMPLETE",
                                              "ABILITY_TO_USE_SELL", "FUTURE_ECONOMIC_BENEFITS",
                                              "RESOURCES_AVAILABLE", "EXPENDITURE_MEASURABLE"]),
            (PSAK19ComplianceLevel, ["FULL", "SUBSTANTIAL", "PARTIAL", "NON_COMPLIANT"]),
        ]
    )
    def test_members_exist(self, enum_cls, expected_members):
        for member in expected_members:
            assert hasattr(enum_cls, member)
        instance = getattr(enum_cls, expected_members[0])
        assert isinstance(instance, enum_cls)


# =============================================================================
# Tests for Exceptions (parametrized)
# =============================================================================

class TestExceptions:
    @pytest.mark.parametrize(
        "exc_class",
        [
            PSAK19Error,
            IntangibleAssetNotFoundError,
            InvalidAmortizationError,
            DevelopmentCostNotCapitalizableError,
        ]
    )
    def test_construction(self, exc_class):
        with pytest.raises(exc_class):
            raise exc_class("test")


# =============================================================================
# Tests for Value Objects / Models
# =============================================================================

class TestPSAK19RevaluationSurplus:
    def test_construction(self):
        surplus_id = uuid.uuid4()
        surplus = PSAK19RevaluationSurplus(
            surplus_id=surplus_id,
            revaluation_date=FIXED_NOW,
            fair_value_before=Decimal("100"),
            fair_value_after=Decimal("150"),
            increase_amount=Decimal("50"),
            performed_by="admin",
            effective_date=FIXED_NOW,
            notes="Test",
        )
        assert surplus.surplus_id == surplus_id
        assert surplus.increase_amount == Decimal("50")
        d = surplus.to_dict()
        assert d["surplus_id"] == str(surplus_id)
        assert d["increase_amount"] == "50"


class TestPSAK19IntangibleAsset:
    def test_properties(self, sample_asset):
        asset = sample_asset
        assert asset.carrying_amount == asset.cost - asset.accumulated_amortization - asset.accumulated_impairment
        assert asset.carrying_amount == asset.carrying_amount_cost_model
        assert asset.net_book_value == asset.carrying_amount
        assert asset.amortizable_amount == asset.cost - asset.residual_value
        expected_annual = (asset.cost - asset.residual_value) / Decimal(asset.useful_life_years)
        assert asset.annual_amortization() == expected_annual

    def test_revaluation_model_carrying(self, sample_asset_revaluation):
        asset = sample_asset_revaluation
        assert asset.carrying_amount == asset.carrying_amount_cost_model
        # Add surplus
        surplus = PSAK19RevaluationSurplus(
            surplus_id=uuid.uuid4(),
            revaluation_date=FIXED_NOW,
            fair_value_before=asset.carrying_amount,
            fair_value_after=Decimal("400000000"),
            increase_amount=Decimal("100000000"),
            performed_by="admin",
            effective_date=FIXED_NOW,
        )
        asset.revaluation_surplus_history.append(surplus)
        asset.current_revaluation_surplus = Decimal("100000000")
        expected = surplus.fair_value_after - asset.accumulated_amortization - asset.accumulated_impairment
        assert asset.carrying_amount_revaluation_model == expected
        assert asset.carrying_amount == expected

    def test_to_dict(self, sample_asset):
        data = sample_asset.to_dict()
        assert data["asset_code"] == "PAT-001"
        assert data["asset_type"] == "paten"
        assert "carrying_amount" in data


class TestPSAK19IntangibleRegister:
    def test_totals(self, sample_register):
        register = sample_register
        assert register.total_cost() == Decimal("200000000")
        assert register.total_accumulated_amortization() == Decimal("0")
        assert register.total_carrying_amount() == Decimal("200000000")
        assert register.total_revaluation_surplus() == Decimal("0")

    def test_to_dict(self, sample_register):
        data = sample_register.to_dict()
        assert data["entity_name"] == "PT Inovasi Digital"
        assert "total_cost" in data
        assert len(data["assets"]) == 1


class TestPSAK19ValidationResult:
    def test_initial_state(self):
        result = PSAK19ValidationResult(is_compliant=True, compliance_level=PSAK19ComplianceLevel.FULL)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK19ComplianceLevel.FULL
        assert result.errors == []
        assert result.warnings == []
        assert result.hash_sha256 != ""

    def test_add_error(self):
        result = PSAK19ValidationResult(is_compliant=True, compliance_level=PSAK19ComplianceLevel.FULL)
        result.add_error("Test error")
        assert result.is_compliant is False
        assert result.compliance_level == PSAK19ComplianceLevel.NON_COMPLIANT
        assert "Test error" in result.errors

    def test_add_warning(self):
        result = PSAK19ValidationResult(is_compliant=True, compliance_level=PSAK19ComplianceLevel.FULL)
        result.add_warning("Test warning")
        assert result.is_compliant is True
        assert result.compliance_level == PSAK19ComplianceLevel.SUBSTANTIAL
        assert "Test warning" in result.warnings


# =============================================================================
# Domain Services
# =============================================================================

class TestPSAK19IntangibleService:
    def test_calculate_amortization_for_period_finite(self, sample_asset):
        service = PSAK19IntangibleService()
        start = FIXED_NOW - timedelta(days=365 * 4)
        end = FIXED_NOW - timedelta(days=365 * 3)
        amort = service.calculate_amortization_for_period(sample_asset, start, end)
        # Annual amortization = 20,000,000, full year
        assert amort == Decimal("20000000")

    def test_calculate_amortization_for_period_indefinite(self, sample_asset_indefinite):
        service = PSAK19IntangibleService()
        start = FIXED_NOW - timedelta(days=365)
        end = FIXED_NOW
        amort = service.calculate_amortization_for_period(sample_asset_indefinite, start, end)
        assert amort == Decimal("0")

    def test_check_development_capitalization_criteria_all_met(self):
        service = PSAK19IntangibleService()
        criteria = {
            PSAK19DevelopmentPhaseCriteria.TECHNICAL_FEASIBILITY: True,
            PSAK19DevelopmentPhaseCriteria.INTENTION_TO_COMPLETE: True,
            PSAK19DevelopmentPhaseCriteria.ABILITY_TO_USE_SELL: True,
            PSAK19DevelopmentPhaseCriteria.FUTURE_ECONOMIC_BENEFITS: True,
            PSAK19DevelopmentPhaseCriteria.RESOURCES_AVAILABLE: True,
            PSAK19DevelopmentPhaseCriteria.EXPENDITURE_MEASURABLE: True,
        }
        met, details = service.check_development_capitalization_criteria(criteria)
        assert met is True
        assert len(details) == 6

    def test_check_development_capitalization_criteria_some_missing(self):
        service = PSAK19IntangibleService()
        criteria = {
            PSAK19DevelopmentPhaseCriteria.TECHNICAL_FEASIBILITY: True,
            PSAK19DevelopmentPhaseCriteria.INTENTION_TO_COMPLETE: False,
            PSAK19DevelopmentPhaseCriteria.ABILITY_TO_USE_SELL: True,
            PSAK19DevelopmentPhaseCriteria.FUTURE_ECONOMIC_BENEFITS: True,
            PSAK19DevelopmentPhaseCriteria.RESOURCES_AVAILABLE: True,
            PSAK19DevelopmentPhaseCriteria.EXPENDITURE_MEASURABLE: True,
        }
        met, details = service.check_development_capitalization_criteria(criteria)
        assert met is False
        assert len(details) == 5

    def test_calculate_gain_loss_on_disposal(self, sample_asset):
        asset = sample_asset
        asset.disposal_proceeds = Decimal("250000000")
        asset.disposal_cost = Decimal("5000000")
        gain = PSAK19IntangibleService.calculate_gain_loss_on_disposal(asset)
        # Carrying amount = 200,000,000, net proceeds = 245,000,000 => gain = 45,000,000
        assert gain == Decimal("45000000")

    def test_revalue_asset_increase(self, sample_asset_revaluation):
        service = PSAK19IntangibleService()
        asset = sample_asset_revaluation
        new_fair_value = Decimal("400000000")
        valuation_date = FIXED_NOW
        updated_asset = service.revalue_asset(asset, new_fair_value, valuation_date, "admin")
        assert updated_asset.current_revaluation_surplus == Decimal("100000000")
        assert updated_asset.last_revaluation_date == valuation_date
        assert updated_asset.accumulated_amortization == Decimal("0")
        assert updated_asset.carrying_amount == new_fair_value

    def test_revalue_asset_decrease(self, sample_asset_revaluation):
        service = PSAK19IntangibleService()
        asset = sample_asset_revaluation
        new_fair_value = Decimal("250000000")
        valuation_date = FIXED_NOW
        updated_asset = service.revalue_asset(asset, new_fair_value, valuation_date, "admin")
        assert updated_asset.accumulated_impairment == Decimal("50000000")
        assert updated_asset.current_revaluation_surplus == Decimal("0")
        assert updated_asset.carrying_amount == new_fair_value

    def test_revalue_asset_not_on_revaluation_model_raises(self, sample_asset):
        service = PSAK19IntangibleService()
        with pytest.raises(PSAK19Error, match="Aset tidak menggunakan model revaluasi"):
            service.revalue_asset(sample_asset, Decimal("300000000"), FIXED_NOW, "admin")


# =============================================================================
# Rules
# =============================================================================

class TestPSAK19Rules:
    def test_validate_separate_acquisition_valid(self, sample_asset):
        rules = PSAK19Rules()
        result = rules.validate_separate_acquisition(sample_asset)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK19ComplianceLevel.FULL
        assert result.errors == []

    def test_validate_separate_acquisition_invalid_cost_zero(self):
        asset = PSAK19IntangibleAsset(
            asset_id=uuid.uuid4(),
            asset_code="TEST",
            name="Test",
            asset_type=PSAK19IntangibleType.PATENT,
            acquisition_method=PSAK19AcquisitionMethod.SEPARATE_PURCHASE,
            measurement_model=PSAK19MeasurementModel.COST,
            acquisition_date=FIXED_NOW,
            cost=Decimal("0"),
            useful_life_type=PSAK19UsefulLifeType.FINITE,
            useful_life_years=5,
        )
        rules = PSAK19Rules()
        result = rules.validate_separate_acquisition(asset)
        assert result.is_compliant is False
        assert "Biaya perolehan aset tak berwujud harus positif" in result.errors

    def test_validate_internally_generated_development_met(self):
        asset = PSAK19IntangibleAsset(
            asset_id=uuid.uuid4(),
            asset_code="DEV-001",
            name="Development",
            asset_type=PSAK19IntangibleType.DEVELOPMENT,
            acquisition_method=PSAK19AcquisitionMethod.INTERNALLY_GENERATED,
            measurement_model=PSAK19MeasurementModel.COST,
            acquisition_date=FIXED_NOW,
            cost=Decimal("100000000"),
            useful_life_type=PSAK19UsefulLifeType.FINITE,
            useful_life_years=5,
            development_criteria_met=True,
            development_criteria_details=[PSAK19DevelopmentPhaseCriteria.TECHNICAL_FEASIBILITY],
        )
        rules = PSAK19Rules()
        result = rules.validate_internally_generated(asset)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK19ComplianceLevel.FULL

    def test_validate_internally_generated_research_warning(self):
        asset = PSAK19IntangibleAsset(
            asset_id=uuid.uuid4(),
            asset_code="RES-001",
            name="Research",
            asset_type=PSAK19IntangibleType.RESEARCH,
            acquisition_method=PSAK19AcquisitionMethod.INTERNALLY_GENERATED,
            measurement_model=PSAK19MeasurementModel.COST,
            acquisition_date=FIXED_NOW,
            cost=Decimal("50000000"),
            useful_life_type=PSAK19UsefulLifeType.INDEFINITE,
        )
        rules = PSAK19Rules()
        result = rules.validate_internally_generated(asset)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK19ComplianceLevel.SUBSTANTIAL
        assert "Biaya riset harus diakui sebagai beban" in result.warnings[0]

    def test_validate_internally_generated_other_type_error(self):
        asset = PSAK19IntangibleAsset(
            asset_id=uuid.uuid4(),
            asset_code="BRAND-INT",
            name="Brand",
            asset_type=PSAK19IntangibleType.BRAND,
            acquisition_method=PSAK19AcquisitionMethod.INTERNALLY_GENERATED,
            measurement_model=PSAK19MeasurementModel.COST,
            acquisition_date=FIXED_NOW,
            cost=Decimal("100000000"),
            useful_life_type=PSAK19UsefulLifeType.INDEFINITE,
        )
        rules = PSAK19Rules()
        result = rules.validate_internally_generated(asset)
        assert result.is_compliant is False
        assert "tidak dapat dihasilkan secara internal" in result.errors[0]

    def test_validate_useful_life_finite_missing_years(self):
        asset = PSAK19IntangibleAsset(
            asset_id=uuid.uuid4(),
            asset_code="TEST",
            name="Test",
            asset_type=PSAK19IntangibleType.PATENT,
            acquisition_method=PSAK19AcquisitionMethod.SEPARATE_PURCHASE,
            measurement_model=PSAK19MeasurementModel.COST,
            acquisition_date=FIXED_NOW,
            cost=Decimal("100000"),
            useful_life_type=PSAK19UsefulLifeType.FINITE,
            useful_life_years=None,
        )
        rules = PSAK19Rules()
        result = rules.validate_useful_life(asset)
        assert result.is_compliant is False
        assert "harus memiliki estimasi masa manfaat" in result.errors[0]

    def test_validate_useful_life_indefinite_warning(self, sample_asset_indefinite):
        rules = PSAK19Rules()
        result = rules.validate_useful_life(sample_asset_indefinite)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK19ComplianceLevel.SUBSTANTIAL
        assert "Aset dengan masa manfaat tidak terbatas tidak diamortisasi" in result.warnings[0]

    def test_validate_revaluation_model_allowed_type(self, sample_asset_revaluation):
        rules = PSAK19Rules()
        result = rules.validate_revaluation_model(sample_asset_revaluation)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK19ComplianceLevel.FULL

    def test_validate_revaluation_model_disallowed_type(self):
        asset = PSAK19IntangibleAsset(
            asset_id=uuid.uuid4(),
            asset_code="SW-REV",
            name="Software",
            asset_type=PSAK19IntangibleType.SOFTWARE,
            acquisition_method=PSAK19AcquisitionMethod.SEPARATE_PURCHASE,
            measurement_model=PSAK19MeasurementModel.REVALUATION,
            acquisition_date=FIXED_NOW,
            cost=Decimal("100000"),
            useful_life_type=PSAK19UsefulLifeType.FINITE,
            useful_life_years=5,
        )
        rules = PSAK19Rules()
        result = rules.validate_revaluation_model(asset)
        assert result.is_compliant is False
        assert "tidak memiliki pasar aktif, tidak boleh menggunakan model revaluasi" in result.errors[0]

    def test_validate_amortization_residual_greater_than_cost(self):
        asset = PSAK19IntangibleAsset(
            asset_id=uuid.uuid4(),
            asset_code="TEST",
            name="Test",
            asset_type=PSAK19IntangibleType.PATENT,
            acquisition_method=PSAK19AcquisitionMethod.SEPARATE_PURCHASE,
            measurement_model=PSAK19MeasurementModel.COST,
            acquisition_date=FIXED_NOW,
            cost=Decimal("100000"),
            useful_life_type=PSAK19UsefulLifeType.FINITE,
            useful_life_years=5,
            residual_value=Decimal("150000"),
        )
        rules = PSAK19Rules()
        result = rules.validate_amortization(asset)
        assert result.is_compliant is False
        assert "Nilai residu tidak boleh melebihi biaya perolehan" in result.errors[0]


# =============================================================================
# Validator
# =============================================================================

class TestPSAK19Validator:
    def test_create_asset(self):
        validator = PSAK19Validator()
        asset = validator.create_asset(
            asset_code="PAT-002",
            name="New Patent",
            asset_type=PSAK19IntangibleType.PATENT,
            acquisition_method=PSAK19AcquisitionMethod.SEPARATE_PURCHASE,
            measurement_model=PSAK19MeasurementModel.COST,
            acquisition_date=FIXED_NOW,
            cost=Decimal("50000000"),
            useful_life_type=PSAK19UsefulLifeType.FINITE,
            useful_life_years=8,
        )
        assert isinstance(asset, PSAK19IntangibleAsset)
        assert asset.asset_code == "PAT-002"
        assert asset.cost == Decimal("50000000")
        assert asset.useful_life_years == 8
        assert asset.asset_id is not None

    def test_create_asset_with_development_criteria(self):
        validator = PSAK19Validator()
        criteria = {
            PSAK19DevelopmentPhaseCriteria.TECHNICAL_FEASIBILITY: True,
            PSAK19DevelopmentPhaseCriteria.INTENTION_TO_COMPLETE: True,
            PSAK19DevelopmentPhaseCriteria.ABILITY_TO_USE_SELL: True,
            PSAK19DevelopmentPhaseCriteria.FUTURE_ECONOMIC_BENEFITS: True,
            PSAK19DevelopmentPhaseCriteria.RESOURCES_AVAILABLE: True,
            PSAK19DevelopmentPhaseCriteria.EXPENDITURE_MEASURABLE: True,
        }
        asset = validator.create_asset(
            asset_code="DEV-002",
            name="Development Project",
            asset_type=PSAK19IntangibleType.DEVELOPMENT,
            acquisition_method=PSAK19AcquisitionMethod.INTERNALLY_GENERATED,
            measurement_model=PSAK19MeasurementModel.COST,
            acquisition_date=FIXED_NOW,
            cost=Decimal("75000000"),
            useful_life_type=PSAK19UsefulLifeType.FINITE,
            useful_life_years=5,
            development_criteria=criteria,
        )
        assert asset.development_criteria_met is True
        assert len(asset.development_criteria_details) == 6

    def test_create_register(self):
        validator = PSAK19Validator()
        entity_id = uuid.uuid4()
        register = validator.create_register(
            entity_id=entity_id,
            entity_name="PT Maju Jaya",
            reporting_date=FIXED_NOW,
        )
        assert isinstance(register, PSAK19IntangibleRegister)
        assert register.entity_id == entity_id
        assert register.entity_name == "PT Maju Jaya"
        assert register.register_id is not None

    def test_add_asset(self, sample_register, sample_asset):
        validator = PSAK19Validator()
        new_register = validator.add_asset(sample_register, sample_asset)
        assert len(new_register.assets) == 2
        assert new_register.assets[-1].asset_code == sample_asset.asset_code

    def test_record_amortization(self, sample_register):
        validator = PSAK19Validator()
        asset_id = sample_register.assets[0].asset_id
        period_end = FIXED_NOW
        new_register = validator.record_amortization(sample_register, asset_id, period_end)
        # 4 years have passed, each 20,000,000 => 80,000,000
        updated_asset = new_register.assets[0]
        assert updated_asset.accumulated_amortization == Decimal("80000000")

    def test_record_research_expense(self, sample_register):
        validator = PSAK19Validator()
        new_register = validator.record_research_expense(sample_register, Decimal("10000000"))
        assert new_register.research_expense_ytd == Decimal("10000000")

    def test_record_development_capitalization(self, sample_register):
        validator = PSAK19Validator()
        new_register = validator.record_development_capitalization(sample_register, Decimal("25000000"))
        assert new_register.development_cost_capitalized_ytd == Decimal("25000000")

    def test_revalue_asset(self, sample_register, sample_asset_revaluation):
        validator = PSAK19Validator()
        register = validator.add_asset(sample_register, sample_asset_revaluation)
        asset_id = sample_asset_revaluation.asset_id
        new_fair_value = Decimal("400000000")
        valuation_date = FIXED_NOW
        new_register = validator.revalue_asset(register, asset_id, new_fair_value, valuation_date, "admin")
        updated_asset = next(a for a in new_register.assets if a.asset_id == asset_id)
        assert updated_asset.current_revaluation_surplus == Decimal("100000000")
        assert updated_asset.carrying_amount == new_fair_value

    def test_dispose_asset(self, sample_register):
        validator = PSAK19Validator()
        asset_id = sample_register.assets[0].asset_id
        disposal_date = FIXED_NOW
        proceeds = Decimal("220000000")
        cost = Decimal("5000000")
        new_register, gain_loss = validator.dispose_asset(
            sample_register, asset_id, disposal_date, proceeds, cost
        )
        disposed_asset = next(a for a in new_register.assets if a.asset_id == asset_id)
        assert disposed_asset.is_active is False
        assert disposed_asset.disposal_date == disposal_date
        assert disposed_asset.disposal_proceeds == proceeds
        # Gain/loss = net proceeds - carrying amount = (220M - 5M) - 200M = 15M
        assert gain_loss == Decimal("15000000")

    def test_dispose_asset_already_inactive_raises(self, sample_register):
        validator = PSAK19Validator()
        asset_id = sample_register.assets[0].asset_id
        new_register, _ = validator.dispose_asset(
            sample_register, asset_id, FIXED_NOW, Decimal("100"), Decimal("0")
        )
        with pytest.raises(PSAK19Error, match="sudah tidak aktif"):
            validator.dispose_asset(new_register, asset_id, FIXED_NOW, Decimal("100"), Decimal("0"))

    def test_validate_register_full_compliant(self, sample_register):
        validator = PSAK19Validator()
        result = validator.validate_register(sample_register)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK19ComplianceLevel.FULL
        assert result.errors == []

    def test_validate_register_with_errors(self):
        validator = PSAK19Validator()
        asset = PSAK19IntangibleAsset(
            asset_id=uuid.uuid4(),
            asset_code="RES-ERR",
            name="Research",
            asset_type=PSAK19IntangibleType.RESEARCH,
            acquisition_method=PSAK19AcquisitionMethod.INTERNALLY_GENERATED,
            measurement_model=PSAK19MeasurementModel.COST,
            acquisition_date=FIXED_NOW,
            cost=Decimal("100000"),
            useful_life_type=PSAK19UsefulLifeType.INDEFINITE,
        )
        register = PSAK19IntangibleRegister(
            register_id=uuid.uuid4(),
            entity_id=uuid.uuid4(),
            entity_name="Test",
            reporting_date=FIXED_NOW,
            assets=[asset],
        )
        result = validator.validate_register(register)
        assert result.is_compliant is True  # only warning for research
        assert result.compliance_level == PSAK19ComplianceLevel.SUBSTANTIAL
        assert len(result.warnings) > 0

    def test_get_requirements_summary(self):
        validator = PSAK19Validator()
        summary = validator.get_requirements_summary()
        assert "recognition" in summary
        assert "research_vs_development" in summary
        assert "amortization" in summary
        assert isinstance(summary["disclosures"], list)


# =============================================================================
# PSAK19 wrapper
# =============================================================================

class TestPSAK19:
    def test_amortize_straight_line(self):
        result = PSAK19.amortize(
            cost=Decimal("200000000"),
            residual_value=Decimal("0"),
            useful_life=10,
            method="straight_line"
        )
        assert result.annual == Decimal("20000000")

    def test_amortize_with_residual(self):
        result = PSAK19.amortize(
            cost=Decimal("150000000"),
            residual_value=Decimal("10000000"),
            useful_life=5,
        )
        assert result.annual == Decimal("28000000")

    def test_amortize_indefinite_raises(self):
        with pytest.raises(ValueError, match="indefinite life"):
            PSAK19.amortize(cost=Decimal("100"), useful_life=None)


# =============================================================================
# Singleton
# =============================================================================

def test_get_psak19_validator():
    validator1 = get_psak19_validator()
    validator2 = get_psak19_validator()
    assert validator1 is validator2
    assert isinstance(validator1, PSAK19Validator)
