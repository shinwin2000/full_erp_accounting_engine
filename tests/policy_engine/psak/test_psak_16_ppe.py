# tests/policy_engine/psak/test_psak_16_ppe.py
# Comprehensive tests for policy_engine/psak/psak_16_ppe.py
# Fixed: All datetime.now() calls are mocked to avoid flaky tests.

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest

from policy_engine.psak.psak_16_ppe import (
    PSAK16,
    AssetNotFoundError,
    InvalidRevaluationError,
    PSAK16Asset,
    PSAK16AssetCategory,
    PSAK16AssetRegister,
    PSAK16AssetService,
    PSAK16ComplianceLevel,
    PSAK16Component,
    PSAK16DepreciationMethod,
    PSAK16Error,
    PSAK16MeasurementModel,
    PSAK16RevaluationFrequency,
    PSAK16RevaluationSurplus,
    PSAK16Rules,
    PSAK16ValidationResult,
    PSAK16Validator,
    get_psak16_validator,
)

# ============================================================================
# FIXED DATETIME (untuk menghindari flaky tests)
# ============================================================================

FIXED_NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
FIXED_ACQUISITION_DATE = datetime(2020, 1, 1, 0, 0, 0, tzinfo=UTC)
FIXED_REPORTING_DATE = datetime(2026, 12, 31, 0, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mock_datetime():
    """Mock datetime.now and datetime.utcnow to fixed values."""
    with patch("policy_engine.psak.psak_16_ppe.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.utcnow.return_value = FIXED_NOW
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        yield mock_dt


# ============================================================================
# Fixtures
# ============================================================================
@pytest.fixture
def validator():
    """Return a fresh PSAK16Validator instance."""
    return PSAK16Validator()


@pytest.fixture
def sample_asset(validator):
    """Create a basic asset with cost model."""
    return validator.create_asset(
        asset_code="ASSET-001",
        name="Test Asset",
        category=PSAK16AssetCategory.MACHINERY,
        acquisition_date=FIXED_ACQUISITION_DATE,
        cost=Decimal("1000000"),
        measurement_model=PSAK16MeasurementModel.COST,
        useful_life_years=10,
        residual_value=Decimal("100000"),
        depreciation_method=PSAK16DepreciationMethod.STRAIGHT_LINE,
    )


@pytest.fixture
def sample_asset_with_components(validator):
    """Asset with components."""
    asset = validator.create_asset(
        asset_code="ASSET-002",
        name="Building",
        category=PSAK16AssetCategory.BUILDING,
        acquisition_date=FIXED_ACQUISITION_DATE,
        cost=Decimal("5000000"),
        measurement_model=PSAK16MeasurementModel.COST,
    )
    asset = validator.add_component(
        asset,
        component_name="Structure",
        cost=Decimal("3000000"),
        useful_life_years=50,
        residual_value=Decimal("300000"),
    )
    asset = validator.add_component(
        asset,
        component_name="Elevator",
        cost=Decimal("1000000"),
        useful_life_years=20,
        residual_value=Decimal("0"),
    )
    return asset


@pytest.fixture
def sample_register(validator, sample_asset):
    """Register with one asset."""
    register = validator.create_register(
        entity_id=uuid.uuid4(),
        entity_name="PT Test",
        reporting_date=FIXED_REPORTING_DATE,
        revaluation_frequency=PSAK16RevaluationFrequency.ANNUALLY,
    )
    register = validator.add_asset(register, sample_asset)
    return register


@pytest.fixture
def revaluation_asset(validator):
    """Asset using revaluation model."""
    return validator.create_asset(
        asset_code="REVAL-001",
        name="Revaluable Asset",
        category=PSAK16AssetCategory.LAND,
        acquisition_date=FIXED_ACQUISITION_DATE,
        cost=Decimal("2000000"),
        measurement_model=PSAK16MeasurementModel.REVALUATION,
    )


# ============================================================================
# Enum tests
# ============================================================================
class TestPSAK16MeasurementModel:
    def test_members_exist(self):
        assert hasattr(PSAK16MeasurementModel, "COST")
        assert hasattr(PSAK16MeasurementModel, "REVALUATION")

    def test_member_is_instance(self):
        assert isinstance(PSAK16MeasurementModel.COST, PSAK16MeasurementModel)


class TestPSAK16DepreciationMethod:
    def test_members_exist(self):
        assert hasattr(PSAK16DepreciationMethod, "STRAIGHT_LINE")
        assert hasattr(PSAK16DepreciationMethod, "DECLINING_BALANCE")
        assert hasattr(PSAK16DepreciationMethod, "UNITS_OF_PRODUCTION")

    def test_member_is_instance(self):
        assert isinstance(PSAK16DepreciationMethod.STRAIGHT_LINE, PSAK16DepreciationMethod)


class TestPSAK16AssetCategory:
    def test_members_exist(self):
        assert hasattr(PSAK16AssetCategory, "LAND")
        assert hasattr(PSAK16AssetCategory, "BUILDING")
        assert hasattr(PSAK16AssetCategory, "MACHINERY")
        assert hasattr(PSAK16AssetCategory, "VEHICLE")
        assert hasattr(PSAK16AssetCategory, "FURNITURE")
        assert hasattr(PSAK16AssetCategory, "COMPUTER")
        assert hasattr(PSAK16AssetCategory, "LEASEHOLD_IMPROVEMENT")
        assert hasattr(PSAK16AssetCategory, "OTHER")

    def test_member_is_instance(self):
        assert isinstance(PSAK16AssetCategory.LAND, PSAK16AssetCategory)


class TestPSAK16RevaluationFrequency:
    def test_members_exist(self):
        assert hasattr(PSAK16RevaluationFrequency, "ANNUALLY")
        assert hasattr(PSAK16RevaluationFrequency, "EVERY_3_YEARS")
        assert hasattr(PSAK16RevaluationFrequency, "EVERY_5_YEARS")
        assert hasattr(PSAK16RevaluationFrequency, "IRREGULAR")

    def test_member_is_instance(self):
        assert isinstance(PSAK16RevaluationFrequency.ANNUALLY, PSAK16RevaluationFrequency)


class TestPSAK16ComplianceLevel:
    def test_members_exist(self):
        assert hasattr(PSAK16ComplianceLevel, "FULL")
        assert hasattr(PSAK16ComplianceLevel, "SUBSTANTIAL")
        assert hasattr(PSAK16ComplianceLevel, "PARTIAL")
        assert hasattr(PSAK16ComplianceLevel, "NON_COMPLIANT")

    def test_member_is_instance(self):
        assert isinstance(PSAK16ComplianceLevel.FULL, PSAK16ComplianceLevel)


# ============================================================================
# Exception tests
# ============================================================================
class TestPSAK16Error:
    def test_construction(self):
        exc = PSAK16Error("Test error")
        assert isinstance(exc, PSAK16Error)
        assert str(exc) == "Test error"


class TestInvalidRevaluationError:
    def test_construction(self):
        exc = InvalidRevaluationError("Invalid revaluation")
        assert isinstance(exc, InvalidRevaluationError)
        assert str(exc) == "Invalid revaluation"


class TestAssetNotFoundError:
    def test_construction(self):
        exc = AssetNotFoundError("Asset not found")
        assert isinstance(exc, AssetNotFoundError)
        assert str(exc) == "Asset not found"


# ============================================================================
# Data Classes
# ============================================================================
class TestPSAK16Component:
    def test_annual_depreciation_straight_line(self):
        component = PSAK16Component(
            component_id=uuid.uuid4(),
            name="Structure",
            cost=Decimal("3000000"),
            useful_life_years=50,
            residual_value=Decimal("300000"),
            depreciation_method=PSAK16DepreciationMethod.STRAIGHT_LINE,
        )
        expected = (Decimal("3000000") - Decimal("300000")) / Decimal(50)
        assert component.annual_depreciation() == expected

    def test_annual_depreciation_declining_balance(self):
        component = PSAK16Component(
            component_id=uuid.uuid4(),
            name="Machine",
            cost=Decimal("1000000"),
            useful_life_years=10,
            residual_value=Decimal("0"),
            depreciation_method=PSAK16DepreciationMethod.DECLINING_BALANCE,
        )
        rate = Decimal(2) / Decimal(10)
        expected = Decimal("1000000") * rate
        assert component.annual_depreciation() == expected

    def test_annual_depreciation_zero_life(self):
        component = PSAK16Component(
            component_id=uuid.uuid4(),
            name="Test",
            cost=Decimal("1000"),
            useful_life_years=0,
            residual_value=Decimal("0"),
        )
        assert component.annual_depreciation() == Decimal("0")

    def test_to_dict(self):
        component = PSAK16Component(
            component_id=uuid.uuid4(),
            name="Structure",
            cost=Decimal("3000000"),
            useful_life_years=50,
            residual_value=Decimal("300000"),
        )
        data = component.to_dict()
        assert data["name"] == "Structure"
        assert data["cost"] == "3000000"
        assert data["useful_life_years"] == 50
        assert data["residual_value"] == "300000"


class TestPSAK16RevaluationSurplus:
    def test_construction(self):
        surplus_id = uuid.uuid4()
        surplus = PSAK16RevaluationSurplus(
            surplus_id=surplus_id,
            revaluation_date=FIXED_NOW,
            fair_value_before=Decimal("1000"),
            fair_value_after=Decimal("1500"),
            increase_amount=Decimal("500"),
            performed_by="appraiser",
            effective_date=FIXED_NOW,
            notes="Revaluation done",
        )
        assert surplus.surplus_id == surplus_id
        assert surplus.increase_amount == Decimal("500")
        data = surplus.to_dict()
        assert data["surplus_id"] == str(surplus_id)
        assert data["increase_amount"] == "500"


class TestPSAK16Asset:
    def test_carrying_amount_cost_model(self, sample_asset):
        asset = sample_asset
        expected = asset.cost - asset.accumulated_depreciation - asset.accumulated_impairment
        assert asset.carrying_amount_cost_model == expected
        assert asset.carrying_amount == expected
        assert asset.net_book_value == expected

    def test_carrying_amount_revaluation_model(self, revaluation_asset):
        asset = revaluation_asset
        # Initially no revaluation, so it falls back to cost model
        assert asset.carrying_amount_revaluation_model == asset.carrying_amount_cost_model
        # Simulate a revaluation
        surplus = PSAK16RevaluationSurplus(
            surplus_id=uuid.uuid4(),
            revaluation_date=FIXED_NOW,
            fair_value_before=asset.carrying_amount,
            fair_value_after=Decimal("2500000"),
            increase_amount=Decimal("500000"),
            performed_by="appraiser",
            effective_date=FIXED_NOW,
        )
        asset.revaluation_surplus_history.append(surplus)
        asset.current_revaluation_surplus = Decimal("500000")
        expected = surplus.fair_value_after - asset.accumulated_depreciation - asset.accumulated_impairment
        assert asset.carrying_amount_revaluation_model == expected
        # Since model is REVALUATION, carrying_amount uses revaluation model
        assert asset.carrying_amount == expected

    def test_total_useful_life_from_components(self, sample_asset_with_components):
        asset = sample_asset_with_components
        max_life = max(c.useful_life_years for c in asset.components)
        assert asset.total_useful_life_from_components == max_life

    def test_annual_depreciation_with_components(self, sample_asset_with_components):
        asset = sample_asset_with_components
        expected_sum = sum(c.annual_depreciation() for c in asset.components)
        assert asset.annual_depreciation() == expected_sum

    def test_annual_depreciation_no_components(self, sample_asset):
        assert sample_asset.annual_depreciation() == Decimal("0")

    def test_to_dict(self, sample_asset):
        data = sample_asset.to_dict()
        assert data["asset_code"] == "ASSET-001"
        assert data["category"] == "mesin"
        assert "carrying_amount" in data
        assert data["is_active"] is True


class TestPSAK16AssetRegister:
    def test_totals(self, sample_register, sample_asset):
        register = sample_register
        assert register.total_cost() == sample_asset.cost
        assert register.total_accumulated_depreciation() == Decimal("0")
        assert register.total_carrying_amount() == sample_asset.cost
        assert register.total_revaluation_surplus() == Decimal("0")

    def test_totals_with_multiple_assets(self, validator):
        asset1 = validator.create_asset("A1", "Asset1", PSAK16AssetCategory.MACHINERY, FIXED_NOW, Decimal("1000"))
        asset2 = validator.create_asset("A2", "Asset2", PSAK16AssetCategory.VEHICLE, FIXED_NOW, Decimal("2000"))
        register = validator.create_register(uuid.uuid4(), "Test", FIXED_NOW)
        register = validator.add_asset(register, asset1)
        register = validator.add_asset(register, asset2)
        assert register.total_cost() == Decimal("3000")
        assert register.total_accumulated_depreciation() == Decimal("0")
        assert register.total_carrying_amount() == Decimal("3000")

    def test_to_dict(self, sample_register):
        data = sample_register.to_dict()
        assert data["entity_name"] == "PT Test"
        assert data["total_cost"] == "1000000"
        assert len(data["assets"]) == 1


class TestPSAK16ValidationResult:
    def test_initial_state(self):
        result = PSAK16ValidationResult(
            is_compliant=True,
            compliance_level=PSAK16ComplianceLevel.FULL
        )
        assert result.is_compliant is True
        assert result.compliance_level == PSAK16ComplianceLevel.FULL
        assert result.errors == []
        assert result.warnings == []
        assert result.hash_sha256 != ""

    def test_add_error(self):
        result = PSAK16ValidationResult(
            is_compliant=True,
            compliance_level=PSAK16ComplianceLevel.FULL
        )
        result.add_error("Error")
        assert result.is_compliant is False
        assert result.compliance_level == PSAK16ComplianceLevel.NON_COMPLIANT
        assert "Error" in result.errors

    def test_add_warning(self):
        result = PSAK16ValidationResult(
            is_compliant=True,
            compliance_level=PSAK16ComplianceLevel.FULL
        )
        result.add_warning("Warning")
        assert result.is_compliant is True
        assert result.compliance_level == PSAK16ComplianceLevel.SUBSTANTIAL
        assert "Warning" in result.warnings

    def test_add_warning_already_substantial(self):
        result = PSAK16ValidationResult(
            is_compliant=True,
            compliance_level=PSAK16ComplianceLevel.SUBSTANTIAL
        )
        result.add_warning("Another")
        assert result.compliance_level == PSAK16ComplianceLevel.SUBSTANTIAL

    def test_to_dict(self):
        result = PSAK16ValidationResult(
            is_compliant=False,
            compliance_level=PSAK16ComplianceLevel.NON_COMPLIANT,
            errors=["E1"],
            warnings=["W1"],
        )
        data = result.to_dict()
        assert data["is_compliant"] is False
        assert data["compliance_level"] == "tidak_patuh"
        assert data["errors"] == ["E1"]


# ============================================================================
# Domain Service
# ============================================================================
class TestPSAK16AssetService:
    def test_calculate_depreciation_for_period_full_year(self, sample_asset):
        service = PSAK16AssetService()
        start = FIXED_ACQUISITION_DATE
        end = FIXED_ACQUISITION_DATE.replace(year=FIXED_ACQUISITION_DATE.year + 1)
        dep = service.calculate_depreciation_for_period(sample_asset, start, end)
        assert dep == Decimal("0")  # No components

    def test_calculate_depreciation_for_period_with_components(self, sample_asset_with_components):
        service = PSAK16AssetService()
        asset = sample_asset_with_components
        start = FIXED_ACQUISITION_DATE
        end = FIXED_ACQUISITION_DATE.replace(year=FIXED_ACQUISITION_DATE.year + 1)
        dep = service.calculate_depreciation_for_period(asset, start, end)
        total_annual = sum(c.annual_depreciation() for c in asset.components)
        assert dep == total_annual

    def test_calculate_depreciation_for_period_partial_year(self, sample_asset_with_components):
        service = PSAK16AssetService()
        asset = sample_asset_with_components
        start = FIXED_ACQUISITION_DATE
        end = FIXED_ACQUISITION_DATE.replace(month=6, day=30)
        dep = service.calculate_depreciation_for_period(asset, start, end)
        total_annual = sum(c.annual_depreciation() for c in asset.components)
        expected = (total_annual * Decimal(181) / Decimal(365)).quantize(Decimal("0"))
        assert dep == expected

    def test_calculate_depreciation_for_period_after_disposal(self, sample_asset):
        asset = sample_asset
        asset.is_active = False
        asset.disposal_date = FIXED_ACQUISITION_DATE.replace(year=2020, month=6, day=30)
        service = PSAK16AssetService()
        dep = service.calculate_depreciation_for_period(
            asset, FIXED_ACQUISITION_DATE, FIXED_ACQUISITION_DATE.replace(year=2020, month=12, day=31)
        )
        assert dep == Decimal("0")

    def test_revalue_asset_increase(self, revaluation_asset):
        service = PSAK16AssetService()
        asset = revaluation_asset
        new_fair_value = Decimal("2500000")
        updated = service.revalue_asset(asset, new_fair_value, FIXED_NOW, "appraiser")
        assert updated.current_revaluation_surplus == Decimal("500000")
        assert updated.last_revaluation_date == FIXED_NOW
        assert updated.accumulated_depreciation == Decimal("0")
        assert updated.accumulated_impairment == Decimal("0")
        assert updated.carrying_amount == new_fair_value

    def test_revalue_asset_decrease_impairment(self, revaluation_asset):
        service = PSAK16AssetService()
        asset = revaluation_asset
        asset.accumulated_depreciation = Decimal("200000")
        new_fair_value = Decimal("1500000")
        updated = service.revalue_asset(asset, new_fair_value, FIXED_NOW, "appraiser")
        # Carrying before = 2,000,000 - 200,000 = 1,800,000
        # New fair = 1,500,000, decrease = 300,000 -> impairment 300,000
        assert updated.accumulated_impairment == Decimal("300000")
        assert updated.current_revaluation_surplus == Decimal("0")
        assert updated.carrying_amount == Decimal("1500000")

    def test_revalue_asset_not_on_revaluation_model_raises(self, sample_asset):
        service = PSAK16AssetService()
        with pytest.raises(InvalidRevaluationError, match="Aset tidak menggunakan model revaluasi"):
            service.revalue_asset(sample_asset, Decimal("1000"), FIXED_NOW, "tester")

    def test_calculate_gain_loss_on_disposal(self, sample_asset):
        asset = sample_asset
        asset.disposal_proceeds = Decimal("800000")
        asset.disposal_cost = Decimal("50000")
        gain = PSAK16AssetService.calculate_gain_loss_on_disposal(asset)
        # Carrying amount = 1,000,000; net proceeds = 750,000; loss = -250,000
        assert gain == Decimal("-250000")

    def test_calculate_gain_loss_on_disposal_with_components(self, sample_asset_with_components):
        asset = sample_asset_with_components
        asset.disposal_proceeds = Decimal("4500000")
        asset.disposal_cost = Decimal("100000")
        gain = PSAK16AssetService.calculate_gain_loss_on_disposal(asset)
        net = Decimal("4500000") - Decimal("100000")
        assert gain == net - Decimal("5000000")  # -600,000


# ============================================================================
# Rules
# ============================================================================
class TestPSAK16Rules:
    def test_validate_measurement_consistency_same_model(self, sample_register):
        result = PSAK16Rules.validate_measurement_consistency(sample_register)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK16ComplianceLevel.FULL
        assert result.warnings == []

    def test_validate_measurement_consistency_mixed_models(self, validator):
        asset1 = validator.create_asset("A1", "A", PSAK16AssetCategory.MACHINERY, FIXED_NOW, Decimal("1000"), measurement_model=PSAK16MeasurementModel.COST)
        asset2 = validator.create_asset("A2", "B", PSAK16AssetCategory.BUILDING, FIXED_NOW, Decimal("2000"), measurement_model=PSAK16MeasurementModel.REVALUATION)
        register = validator.create_register(uuid.uuid4(), "Test", FIXED_NOW)
        register = validator.add_asset(register, asset1)
        register = validator.add_asset(register, asset2)
        result = PSAK16Rules.validate_measurement_consistency(register)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK16ComplianceLevel.SUBSTANTIAL
        assert "Beberapa aset menggunakan model pengukuran berbeda" in result.warnings[0]

    def test_validate_revaluation_frequency_annually_compliant(self, revaluation_asset):
        register = PSAK16AssetRegister(
            register_id=uuid.uuid4(),
            entity_id=uuid.uuid4(),
            entity_name="Test",
            reporting_date=FIXED_REPORTING_DATE,
            assets=[revaluation_asset],
            revaluation_frequency=PSAK16RevaluationFrequency.ANNUALLY,
        )
        revaluation_asset.last_revaluation_date = FIXED_REPORTING_DATE - timedelta(days=180)
        result = PSAK16Rules.validate_revaluation_frequency(register)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK16ComplianceLevel.FULL

    def test_validate_revaluation_frequency_annually_warning(self, revaluation_asset):
        register = PSAK16AssetRegister(
            register_id=uuid.uuid4(),
            entity_id=uuid.uuid4(),
            entity_name="Test",
            reporting_date=FIXED_REPORTING_DATE,
            assets=[revaluation_asset],
            revaluation_frequency=PSAK16RevaluationFrequency.ANNUALLY,
        )
        revaluation_asset.last_revaluation_date = FIXED_REPORTING_DATE - timedelta(days=400)
        result = PSAK16Rules.validate_revaluation_frequency(register)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK16ComplianceLevel.SUBSTANTIAL
        assert "belum direvaluasi dalam 1 tahun" in result.warnings[0]

    def test_validate_component_depreciation_large_asset_no_components_warning(self):
        asset = PSAK16Asset(
            asset_id=uuid.uuid4(),
            asset_code="BIG",
            name="Big Asset",
            category=PSAK16AssetCategory.MACHINERY,
            acquisition_date=FIXED_NOW,
            cost=Decimal("1500000000"),
            measurement_model=PSAK16MeasurementModel.COST,
            components=[],
        )
        result = PSAK16Rules.validate_component_depreciation(asset)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK16ComplianceLevel.SUBSTANTIAL
        assert "bernilai besar tanpa identifikasi komponen" in result.warnings[0]

    def test_validate_component_depreciation_with_components_ok(self, sample_asset_with_components):
        result = PSAK16Rules.validate_component_depreciation(sample_asset_with_components)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK16ComplianceLevel.FULL
        assert result.warnings == []

    def test_validate_disclosure_no_assets_warning(self):
        register = PSAK16AssetRegister(
            register_id=uuid.uuid4(),
            entity_id=uuid.uuid4(),
            entity_name="Test",
            reporting_date=FIXED_NOW,
            assets=[],
        )
        result = PSAK16Rules.validate_disclosure(register)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK16ComplianceLevel.SUBSTANTIAL
        assert "Tidak ada aset tetap yang dicatat" in result.warnings[0]

    def test_validate_disclosure_with_assets_ok(self, sample_register):
        result = PSAK16Rules.validate_disclosure(sample_register)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK16ComplianceLevel.FULL
        assert result.warnings == []

    def test_calculate_depreciation_straight_line(self):
        result = PSAK16Rules.calculate_depreciation(
            cost=Decimal("100000"),
            salvage_value=Decimal("10000"),
            useful_life_years=10,
            method=PSAK16DepreciationMethod.STRAIGHT_LINE,
            current_year=1,
        )
        assert result == Decimal("9000")

    def test_calculate_depreciation_declining_balance(self):
        result = PSAK16Rules.calculate_depreciation(
            cost=Decimal("100000"),
            salvage_value=Decimal("0"),
            useful_life_years=5,
            method=PSAK16DepreciationMethod.DECLINING_BALANCE,
            current_year=1,
        )
        rate = Decimal(2) / Decimal(5)
        assert result == Decimal("100000") * rate  # 40,000

    def test_validate_revaluation_model_valid(self):
        result = PSAK16Rules.validate_revaluation_model(
            fair_value=Decimal("150000"),
            carrying_amount=Decimal("100000"),
            has_appraisal=True,
        )
        assert result.is_compliant is True
        assert result.compliance_level == PSAK16ComplianceLevel.FULL
        assert result.errors == []

    def test_validate_revaluation_model_no_appraisal(self):
        result = PSAK16Rules.validate_revaluation_model(
            fair_value=Decimal("150000"),
            carrying_amount=Decimal("100000"),
            has_appraisal=False,
        )
        assert result.is_compliant is False
        assert result.compliance_level == PSAK16ComplianceLevel.NON_COMPLIANT
        assert "independent appraisal" in result.errors[0]

    def test_validate_revaluation_model_non_positive_fair_value(self):
        result = PSAK16Rules.validate_revaluation_model(
            fair_value=Decimal("0"),
            carrying_amount=Decimal("100000"),
            has_appraisal=True,
        )
        assert result.is_compliant is False
        assert "Fair value must be positive" in result.errors[0]


# ============================================================================
# Validator
# ============================================================================
class TestPSAK16Validator:
    def test_create_asset(self, validator):
        asset = validator.create_asset(
            asset_code="NEW",
            name="New Asset",
            category=PSAK16AssetCategory.VEHICLE,
            acquisition_date=FIXED_ACQUISITION_DATE,
            cost=Decimal("500000"),
            measurement_model=PSAK16MeasurementModel.COST,
            useful_life_years=8,
            residual_value=Decimal("50000"),
            depreciation_method=PSAK16DepreciationMethod.DECLINING_BALANCE,
        )
        assert isinstance(asset, PSAK16Asset)
        assert asset.asset_code == "NEW"
        assert asset.cost == Decimal("500000")
        assert asset.measurement_model == PSAK16MeasurementModel.COST
        assert asset.components == []
        assert asset.asset_id is not None

    def test_add_component(self, sample_asset):
        asset = validator.add_component(
            sample_asset,
            component_name="Engine",
            cost=Decimal("200000"),
            useful_life_years=5,
            residual_value=Decimal("20000"),
            depreciation_method=PSAK16DepreciationMethod.STRAIGHT_LINE,
        )
        assert len(asset.components) == 1
        comp = asset.components[0]
        assert comp.name == "Engine"
        assert comp.cost == Decimal("200000")
        assert comp.useful_life_years == 5

    def test_create_register(self, validator):
        entity_id = uuid.uuid4()
        register = validator.create_register(
            entity_id=entity_id,
            entity_name="PT ABC",
            reporting_date=FIXED_REPORTING_DATE,
            revaluation_frequency=PSAK16RevaluationFrequency.EVERY_3_YEARS,
        )
        assert isinstance(register, PSAK16AssetRegister)
        assert register.entity_id == entity_id
        assert register.entity_name == "PT ABC"
        assert register.reporting_date == FIXED_REPORTING_DATE
        assert register.revaluation_frequency == PSAK16RevaluationFrequency.EVERY_3_YEARS

    def test_add_asset(self, sample_register, sample_asset):
        new_register = validator.add_asset(sample_register, sample_asset)
        # sample_register already has one asset (from fixture), so now two
        assert len(new_register.assets) == 2
        assert new_register.assets[-1].asset_code == sample_asset.asset_code

    def test_record_depreciation(self, sample_register, sample_asset_with_components):
        register2 = validator.create_register(uuid.uuid4(), "Test", FIXED_REPORTING_DATE)
        register2 = validator.add_asset(register2, sample_asset_with_components)
        asset_id = sample_asset_with_components.asset_id
        period_end = FIXED_REPORTING_DATE
        new_register = validator.record_depreciation(register2, asset_id, period_end)
        service = PSAK16AssetService()
        expected_dep = service.calculate_depreciation_for_period(
            sample_asset_with_components,
            sample_asset_with_components.acquisition_date,
            period_end
        )
        updated_asset = next(a for a in new_register.assets if a.asset_id == asset_id)
        assert updated_asset.accumulated_depreciation == expected_dep

    def test_revalue_asset(self, validator, revaluation_asset):
        register = validator.create_register(uuid.uuid4(), "Test", FIXED_NOW)
        register = validator.add_asset(register, revaluation_asset)
        new_fair = Decimal("2500000")
        new_register = validator.revalue_asset(register, revaluation_asset.asset_id, new_fair, FIXED_NOW, "appraiser")
        updated_asset = next(a for a in new_register.assets if a.asset_id == revaluation_asset.asset_id)
        assert updated_asset.carrying_amount == new_fair
        assert updated_asset.current_revaluation_surplus == Decimal("500000")

    def test_dispose_asset(self, sample_register, sample_asset):
        register = sample_register
        asset_id = sample_asset.asset_id
        disposal_date = FIXED_NOW
        proceeds = Decimal("900000")
        cost = Decimal("50000")
        new_register, gain_loss = validator.dispose_asset(register, asset_id, disposal_date, proceeds, cost)
        updated_asset = next(a for a in new_register.assets if a.asset_id == asset_id)
        assert updated_asset.is_active is False
        assert updated_asset.disposal_date == disposal_date
        net = proceeds - cost
        assert gain_loss == net - Decimal("1000000")  # = -150,000

    def test_dispose_asset_already_inactive_raises(self, sample_register, sample_asset):
        register = sample_register
        asset_id = sample_asset.asset_id
        new_register, _ = validator.dispose_asset(register, asset_id, FIXED_NOW, Decimal("0"), Decimal("0"))
        with pytest.raises(PSAK16Error, match="sudah tidak aktif"):
            validator.dispose_asset(new_register, asset_id, FIXED_NOW, Decimal("0"), Decimal("0"))

    def test_validate_register_full_compliant(self, sample_register):
        result = validator.validate_register(sample_register)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK16ComplianceLevel.FULL
        assert result.errors == []

    def test_validate_register_with_mixed_models(self, validator):
        asset1 = validator.create_asset("A1", "A", PSAK16AssetCategory.MACHINERY, FIXED_NOW, Decimal("1000"), measurement_model=PSAK16MeasurementModel.COST)
        asset2 = validator.create_asset("A2", "B", PSAK16AssetCategory.BUILDING, FIXED_NOW, Decimal("2000"), measurement_model=PSAK16MeasurementModel.REVALUATION)
        register = validator.create_register(uuid.uuid4(), "Test", FIXED_NOW)
        register = validator.add_asset(register, asset1)
        register = validator.add_asset(register, asset2)
        result = validator.validate_register(register)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK16ComplianceLevel.SUBSTANTIAL
        assert any("model pengukuran berbeda" in w for w in result.warnings)

    def test_validate_register_with_revaluation_frequency_warning(self, validator, revaluation_asset):
        register = validator.create_register(uuid.uuid4(), "Test", FIXED_REPORTING_DATE, PSAK16RevaluationFrequency.ANNUALLY)
        revaluation_asset.last_revaluation_date = FIXED_REPORTING_DATE - timedelta(days=400)
        register = validator.add_asset(register, revaluation_asset)
        result = validator.validate_register(register)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK16ComplianceLevel.SUBSTANTIAL
        assert any("belum direvaluasi dalam 1 tahun" in w for w in result.warnings)

    def test_get_requirements_summary(self, validator):
        summary = validator.get_requirements_summary()
        assert "recognition" in summary
        assert "initial_measurement" in summary
        assert "depreciation" in summary
        assert "component_approach" in summary
        assert "disclosures" in summary
        assert isinstance(summary["disclosures"], list)


# ============================================================================
# PSAK16 Facade
# ============================================================================
class TestPSAK16:
    def test_depreciate_straight_line(self):
        result = PSAK16.depreciate(
            cost=Decimal("1000000"),
            residual_value=Decimal("100000"),
            useful_life=10,
            method="straight_line",
        )
        expected = (Decimal("1000000") - Decimal("100000")) / Decimal(10)
        assert result.annual == expected

    def test_depreciate_declining_balance(self):
        result = PSAK16.depreciate(
            cost=Decimal("1000000"),
            residual_value=Decimal("0"),
            useful_life=5,
            method="declining_balance",
        )
        rate = Decimal(2) / Decimal(5)
        expected = Decimal("1000000") * rate
        assert result.annual == expected

    def test_is_revaluation_allowed(self):
        assert PSAK16.is_revaluation_allowed("land") is True
        assert PSAK16.is_revaluation_allowed("building") is True
        assert PSAK16.is_revaluation_allowed("machinery") is True


# ============================================================================
# Singleton Accessor
# ============================================================================
def test_get_psak16_validator():
    v1 = get_psak16_validator()
    v2 = get_psak16_validator()
    assert v1 is v2
    assert isinstance(v1, PSAK16Validator)
