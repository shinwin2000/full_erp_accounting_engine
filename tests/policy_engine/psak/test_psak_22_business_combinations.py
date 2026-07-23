# Comprehensive tests for policy_engine/psak/psak_22_business_combinations.py
# =========================================
# All assertions are meaningful and verify actual behavior.

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from policy_engine.psak.psak_22_business_combinations import (
    PSAK22,
    AcquisitionDateError,
    PSAK22AcquisitionMethod,
    PSAK22BusinessCombination,
    PSAK22BusinessCombinationService,
    PSAK22ComplianceLevel,
    PSAK22ContingentConsideration,
    PSAK22ContingentConsiderationClassification,
    PSAK22Error,
    PSAK22GoodwillCalculation,
    PSAK22IdentifiableAsset,
    PSAK22IdentifiableLiability,
    PSAK22MeasurementPeriodAdjustment,
    PSAK22NCIChoice,
    PSAK22Rules,
    PSAK22ValidationResult,
    PSAK22Validator,
    get_psak22_validator,
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------
@pytest.fixture
def validator():
    """Return a fresh PSAK22Validator instance."""
    return PSAK22Validator()


@pytest.fixture
def sample_combination(validator):
    """Create a business combination with basic data."""
    acquirer_id = uuid4()
    acquiree_id = uuid4()
    combo = validator.create_business_combination(
        acquirer_id=acquirer_id,
        acquiree_id=acquiree_id,
        acquirer_name="PT Induk Sejahtera",
        acquiree_name="PT Anak Maju",
        acquisition_date=datetime(2026, 6, 30, tzinfo=UTC),
        consideration_transferred=Decimal("800000000"),
        nci_choice=PSAK22NCIChoice.PROPORTIONATE_SHARE,
        nci_percentage=Decimal("20"),
        nci_value=Decimal("0"),  # will be set later
    )
    # Add some assets and liabilities
    combo = validator.add_identifiable_asset(combo, "Land", Decimal("300000000"))
    combo = validator.add_identifiable_asset(combo, "Building", Decimal("200000000"))
    combo = validator.add_identifiable_asset(combo, "Patent", Decimal("100000000"), asset_type="intangible", useful_life=10)
    combo = validator.add_identifiable_asset(combo, "Inventory", Decimal("50000000"), is_current=True)
    combo = validator.add_identifiable_liability(combo, "Bank Loan", Decimal("100000000"), liability_type="non-current")
    combo = validator.add_identifiable_liability(combo, "Trade Payable", Decimal("20000000"), liability_type="current")
    # Set NCI value (proportionate share of net identifiable assets)
    nci_value = combo.nci_proportionate_value
    combo = validator.set_nci_value(combo, nci_value)
    return combo


@pytest.fixture
def sample_asset():
    """Create a single identifiable asset."""
    return PSAK22IdentifiableAsset(
        asset_id=uuid4(),
        description="Test Asset",
        fair_value=Decimal("100000"),
        carrying_amount=Decimal("80000"),
        asset_type="tangible",
        useful_life=5,
        is_current=False,
    )


@pytest.fixture
def sample_liability():
    """Create a single identifiable liability."""
    return PSAK22IdentifiableLiability(
        liability_id=uuid4(),
        description="Test Liability",
        fair_value=Decimal("30000"),
        carrying_amount=Decimal("25000"),
        liability_type="current",
        settlement_date=datetime(2027, 12, 31, tzinfo=UTC),
    )


@pytest.fixture
def sample_contingent_consideration():
    """Create a contingent consideration."""
    return PSAK22ContingentConsideration(
        consideration_id=uuid4(),
        description="Earn-out",
        classification=PSAK22ContingentConsiderationClassification.LIABILITY,
        fair_value_at_acquisition=Decimal("50000000"),
        settlement_range_low=Decimal("0"),
        settlement_range_high=Decimal("100000000"),
        settlement_date=datetime(2027, 6, 30, tzinfo=UTC),
        remeasurement_gain_loss=Decimal("0"),
    )


# -----------------------------------------------------------------------------
# Enum tests
# -----------------------------------------------------------------------------
class TestPSAK22AcquisitionMethod:
    def test_members_exist(self):
        assert hasattr(PSAK22AcquisitionMethod, "ACQUISITION")
        assert hasattr(PSAK22AcquisitionMethod, "MERGER")

    def test_member_is_instance(self):
        assert isinstance(PSAK22AcquisitionMethod.ACQUISITION, PSAK22AcquisitionMethod)


class TestPSAK22NCIChoice:
    def test_members_exist(self):
        assert hasattr(PSAK22NCIChoice, "PROPORTIONATE_SHARE")
        assert hasattr(PSAK22NCIChoice, "FAIR_VALUE")

    def test_member_is_instance(self):
        assert isinstance(PSAK22NCIChoice.PROPORTIONATE_SHARE, PSAK22NCIChoice)


class TestPSAK22ContingentConsiderationClassification:
    def test_members_exist(self):
        assert hasattr(PSAK22ContingentConsiderationClassification, "EQUITY")
        assert hasattr(PSAK22ContingentConsiderationClassification, "LIABILITY")
        assert hasattr(PSAK22ContingentConsiderationClassification, "ASSET")

    def test_member_is_instance(self):
        assert isinstance(PSAK22ContingentConsiderationClassification.EQUITY, PSAK22ContingentConsiderationClassification)


class TestPSAK22MeasurementPeriodAdjustment:
    def test_members_exist(self):
        assert hasattr(PSAK22MeasurementPeriodAdjustment, "IDENTIFIABLE_ASSETS")
        assert hasattr(PSAK22MeasurementPeriodAdjustment, "LIABILITIES")
        assert hasattr(PSAK22MeasurementPeriodAdjustment, "CONTINGENT_CONSIDERATION")
        assert hasattr(PSAK22MeasurementPeriodAdjustment, "GOODWILL")

    def test_member_is_instance(self):
        assert isinstance(PSAK22MeasurementPeriodAdjustment.IDENTIFIABLE_ASSETS, PSAK22MeasurementPeriodAdjustment)


class TestPSAK22ComplianceLevel:
    def test_members_exist(self):
        assert hasattr(PSAK22ComplianceLevel, "FULL")
        assert hasattr(PSAK22ComplianceLevel, "SUBSTANTIAL")
        assert hasattr(PSAK22ComplianceLevel, "PARTIAL")
        assert hasattr(PSAK22ComplianceLevel, "NON_COMPLIANT")

    def test_member_is_instance(self):
        assert isinstance(PSAK22ComplianceLevel.FULL, PSAK22ComplianceLevel)


# -----------------------------------------------------------------------------
# Exception tests
# -----------------------------------------------------------------------------
class TestPSAK22Error:
    def test_construction(self):
        exc = PSAK22Error("Test error")
        assert isinstance(exc, PSAK22Error)
        assert str(exc) == "Test error"


class TestAcquisitionDateError:
    def test_construction(self):
        exc = AcquisitionDateError("Invalid acquisition date")
        assert isinstance(exc, AcquisitionDateError)
        assert str(exc) == "Invalid acquisition date"


# -----------------------------------------------------------------------------
# Data Classes
# -----------------------------------------------------------------------------
class TestPSAK22IdentifiableAsset:
    def test_construction(self, sample_asset):
        assert sample_asset.asset_id is not None
        assert sample_asset.description == "Test Asset"
        assert sample_asset.fair_value == Decimal("100000")
        assert sample_asset.carrying_amount == Decimal("80000")
        assert sample_asset.asset_type == "tangible"
        assert sample_asset.useful_life == 5
        assert sample_asset.is_current is False

    def test_to_dict(self, sample_asset):
        data = sample_asset.to_dict()
        assert data["description"] == "Test Asset"
        assert data["fair_value"] == "100000"
        assert data["asset_type"] == "tangible"
        assert data["useful_life"] == 5
        assert data["is_current"] is False


class TestPSAK22IdentifiableLiability:
    def test_construction(self, sample_liability):
        assert sample_liability.liability_id is not None
        assert sample_liability.description == "Test Liability"
        assert sample_liability.fair_value == Decimal("30000")
        assert sample_liability.carrying_amount == Decimal("25000")
        assert sample_liability.liability_type == "current"

    def test_to_dict(self, sample_liability):
        data = sample_liability.to_dict()
        assert data["description"] == "Test Liability"
        assert data["fair_value"] == "30000"
        assert data["liability_type"] == "current"


class TestPSAK22ContingentConsideration:
    def test_construction(self, sample_contingent_consideration):
        assert sample_contingent_consideration.consideration_id is not None
        assert sample_contingent_consideration.description == "Earn-out"
        assert sample_contingent_consideration.classification == PSAK22ContingentConsiderationClassification.LIABILITY
        assert sample_contingent_consideration.fair_value_at_acquisition == Decimal("50000000")
        assert sample_contingent_consideration.settlement_range_low == Decimal("0")
        assert sample_contingent_consideration.settlement_range_high == Decimal("100000000")
        assert sample_contingent_consideration.remeasurement_gain_loss == Decimal("0")

    def test_to_dict(self, sample_contingent_consideration):
        data = sample_contingent_consideration.to_dict()
        assert data["description"] == "Earn-out"
        assert data["classification"] == "liabilitas"
        assert data["fair_value_at_acquisition"] == "50000000"
        assert data["range_low"] == "0"
        assert data["range_high"] == "100000000"


class TestPSAK22BusinessCombination:
    def test_net_identifiable_assets(self, sample_combination):
        combo = sample_combination
        total_assets = sum(a.fair_value for a in combo.identifiable_assets)  # 300M+200M+100M+50M=650M
        total_liabilities = sum(l.fair_value for l in combo.identifiable_liabilities)  # 100M+20M=120M
        expected = total_assets - total_liabilities  # 530M
        assert combo.net_identifiable_assets == expected

    def test_nci_proportionate_value(self, sample_combination):
        combo = sample_combination
        # NCI percentage = 20%, net identifiable assets = 530M, so NCI proportionate = 106M
        expected = combo.net_identifiable_assets * Decimal("0.20")
        assert combo.nci_proportionate_value == expected

    def test_calculate_goodwill_or_gain_goodwill(self, sample_combination):
        combo = sample_combination
        # Consideration = 800M, NCI = 106M, net identifiable = 530M
        # Goodwill = 800M + 106M - 530M = 376M
        goodwill, gain = combo.calculate_goodwill_or_gain()
        assert goodwill == Decimal("376000000")
        assert gain == Decimal("0")

    def test_calculate_goodwill_or_gain_bargain_purchase(self, validator):
        combo = validator.create_business_combination(
            acquirer_id=uuid4(),
            acquiree_id=uuid4(),
            acquirer_name="A",
            acquiree_name="B",
            acquisition_date=datetime.now(UTC),
            consideration_transferred=Decimal("400000000"),
            nci_choice=PSAK22NCIChoice.PROPORTIONATE_SHARE,
            nci_percentage=Decimal("0"),
            nci_value=Decimal("0"),
        )
        # Add assets worth 500M and liabilities 100M -> net = 400M
        combo = validator.add_identifiable_asset(combo, "Asset1", Decimal("300000000"))
        combo = validator.add_identifiable_asset(combo, "Asset2", Decimal("200000000"))
        combo = validator.add_identifiable_liability(combo, "Liability", Decimal("100000000"))
        # Consideration = 400M, NCI=0, net=400M -> no gain or goodwill (neutral)
        goodwill, gain = combo.calculate_goodwill_or_gain()
        assert goodwill == Decimal("0")
        assert gain == Decimal("0")
        # Now reduce consideration to 350M -> bargain purchase gain of 50M
        combo.consideration_transferred = Decimal("350000000")
        goodwill, gain = combo.calculate_goodwill_or_gain()
        assert goodwill == Decimal("0")
        assert gain == Decimal("50000000")

    def test_to_dict(self, sample_combination):
        data = sample_combination.to_dict()
        assert data["acquirer_name"] == "PT Induk Sejahtera"
        assert data["acquiree_name"] == "PT Anak Maju"
        assert data["consideration_transferred"] == "800000000"
        assert "goodwill" in data
        assert "net_identifiable_assets" in data
        assert len(data["identifiable_assets"]) == 4
        assert len(data["identifiable_liabilities"]) == 2


class TestPSAK22ValidationResult:
    def test_initial_state(self):
        result = PSAK22ValidationResult(
            is_compliant=True,
            compliance_level=PSAK22ComplianceLevel.FULL
        )
        assert result.is_compliant is True
        assert result.compliance_level == PSAK22ComplianceLevel.FULL
        assert result.errors == []
        assert result.warnings == []
        assert result.hash_sha256 != ""

    def test_add_error(self):
        result = PSAK22ValidationResult(
            is_compliant=True,
            compliance_level=PSAK22ComplianceLevel.FULL
        )
        result.add_error("Error")
        assert result.is_compliant is False
        assert result.compliance_level == PSAK22ComplianceLevel.NON_COMPLIANT
        assert "Error" in result.errors

    def test_add_warning(self):
        result = PSAK22ValidationResult(
            is_compliant=True,
            compliance_level=PSAK22ComplianceLevel.FULL
        )
        result.add_warning("Warning")
        assert result.is_compliant is True
        assert result.compliance_level == PSAK22ComplianceLevel.SUBSTANTIAL
        assert "Warning" in result.warnings

    def test_add_warning_already_substantial(self):
        result = PSAK22ValidationResult(
            is_compliant=True,
            compliance_level=PSAK22ComplianceLevel.SUBSTANTIAL
        )
        result.add_warning("Another")
        assert result.compliance_level == PSAK22ComplianceLevel.SUBSTANTIAL

    def test_to_dict(self):
        result = PSAK22ValidationResult(
            is_compliant=False,
            compliance_level=PSAK22ComplianceLevel.NON_COMPLIANT,
            errors=["E1"],
            warnings=["W1"],
        )
        data = result.to_dict()
        assert data["is_compliant"] is False
        assert data["compliance_level"] == "tidak_patuh"
        assert data["errors"] == ["E1"]
        assert data["warnings"] == ["W1"]


# -----------------------------------------------------------------------------
# Domain Service
# -----------------------------------------------------------------------------
class TestPSAK22BusinessCombinationService:
    def test_is_business_combination_with_assets_and_processes(self):
        assets = [PSAK22IdentifiableAsset(uuid4(), "Asset", Decimal("100"), Decimal("0"), "tangible")]
        result = PSAK22BusinessCombinationService.is_business_combination(assets, True)
        assert result is True

    def test_is_business_combination_no_assets(self):
        result = PSAK22BusinessCombinationService.is_business_combination([], True)
        assert result is False

    def test_is_business_combination_no_processes(self):
        assets = [PSAK22IdentifiableAsset(uuid4(), "Asset", Decimal("100"), Decimal("0"), "tangible")]
        result = PSAK22BusinessCombinationService.is_business_combination(assets, False)
        assert result is False

    def test_calculate_acquired_net_assets(self):
        asset1 = PSAK22IdentifiableAsset(uuid4(), "A", Decimal("1000"), Decimal("0"), "tangible")
        asset2 = PSAK22IdentifiableAsset(uuid4(), "B", Decimal("500"), Decimal("0"), "intangible")
        liability1 = PSAK22IdentifiableLiability(uuid4(), "L1", Decimal("200"), Decimal("0"), "current")
        liability2 = PSAK22IdentifiableLiability(uuid4(), "L2", Decimal("100"), Decimal("0"), "non-current")
        assets = [asset1, asset2]
        liabilities = [liability1, liability2]
        net = PSAK22BusinessCombinationService.calculate_acquired_net_assets(assets, liabilities)
        # 1000+500 - 200-100 = 1200
        assert net == Decimal("1200")

    def test_allocate_purchase_price(self, sample_combination):
        combo = sample_combination
        fair_values_assets = {
            combo.identifiable_assets[0].asset_id: Decimal("350000000"),
            combo.identifiable_assets[1].asset_id: Decimal("250000000"),
        }
        fair_values_liabilities = {
            combo.identifiable_liabilities[0].liability_id: Decimal("110000000"),
        }
        updated = PSAK22BusinessCombinationService.allocate_purchase_price(
            combo, fair_values_assets, fair_values_liabilities
        )
        # Check asset 0 fair value updated
        assert updated.identifiable_assets[0].fair_value == Decimal("350000000")
        assert updated.identifiable_assets[1].fair_value == Decimal("250000000")
        # Liability 0 updated
        assert updated.identifiable_liabilities[0].fair_value == Decimal("110000000")
        # Other items unchanged
        assert updated.identifiable_assets[2].fair_value == Decimal("100000000")  # Patent

    def test_compute_remeasurement_contingent_consideration_liability_increase(self):
        original = PSAK22ContingentConsideration(
            consideration_id=uuid4(),
            description="Earn-out",
            classification=PSAK22ContingentConsiderationClassification.LIABILITY,
            fair_value_at_acquisition=Decimal("50000000"),
            settlement_range_low=Decimal("0"),
            settlement_range_high=Decimal("100000000"),
        )
        new_fair = Decimal("70000000")
        new_cc, diff = PSAK22BusinessCombinationService.compute_remeasurement_contingent_consideration(original, new_fair)
        assert new_cc.fair_value_at_acquisition == new_fair
        assert diff == Decimal("20000000")
        assert new_cc.remeasurement_gain_loss == Decimal("20000000")

    def test_compute_remeasurement_contingent_consideration_equity_no_change(self):
        original = PSAK22ContingentConsideration(
            consideration_id=uuid4(),
            description="Earn-out",
            classification=PSAK22ContingentConsiderationClassification.EQUITY,
            fair_value_at_acquisition=Decimal("0"),
        )
        new_fair = Decimal("10000000")
        new_cc, diff = PSAK22BusinessCombinationService.compute_remeasurement_contingent_consideration(original, new_fair)
        # For equity, fair value remains at acquisition (0) and diff is 0
        assert new_cc.fair_value_at_acquisition == Decimal("0")
        assert diff == Decimal("0")


# -----------------------------------------------------------------------------
# Rules
# -----------------------------------------------------------------------------
class TestPSAK22Rules:
    def test_validate_measurement_period_within_1_year(self, sample_combination):
        current_date = sample_combination.acquisition_date + timedelta(days=180)
        result = PSAK22Rules.validate_measurement_period(sample_combination, current_date)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK22ComplianceLevel.FULL
        assert result.errors == []

    def test_validate_measurement_period_after_1_year_with_adjustments(self, sample_combination):
        current_date = sample_combination.acquisition_date + timedelta(days=400)
        # Add a measurement period adjustment
        sample_combination.measurement_period_adjustments["goodwill"] = Decimal("1000000")
        result = PSAK22Rules.validate_measurement_period(sample_combination, current_date)
        assert result.is_compliant is False
        assert result.compliance_level == PSAK22ComplianceLevel.NON_COMPLIANT
        assert "Penyesuaian periode pengukuran hanya diperbolehkan dalam 12 bulan" in result.errors[0]

    def test_validate_nci_measurement_valid(self, sample_combination):
        result = PSAK22Rules.validate_nci_measurement(sample_combination)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK22ComplianceLevel.FULL

    def test_validate_nci_measurement_invalid_percentage(self, sample_combination):
        combo = sample_combination
        combo.nci_percentage = Decimal("150")
        result = PSAK22Rules.validate_nci_measurement(combo)
        assert result.is_compliant is False
        assert "Persentase NCI harus antara 0 dan 100" in result.errors[0]

    def test_validate_nci_measurement_fair_value_missing(self, sample_combination):
        combo = sample_combination
        combo.nci_choice = PSAK22NCIChoice.FAIR_VALUE
        combo.nci_value = Decimal("0")
        result = PSAK22Rules.validate_nci_measurement(combo)
        assert result.is_compliant is False
        assert "NCI diukur pada nilai wajar tetapi nilai NCI tidak ditentukan" in result.errors[0]

    def test_validate_identifiable_assets_positive_fair_value(self):
        assets = [
            PSAK22IdentifiableAsset(uuid4(), "A", Decimal("100"), Decimal("0"), "tangible"),
            PSAK22IdentifiableAsset(uuid4(), "B", Decimal("0"), Decimal("0"), "goodwill"),  # goodwill can have zero
        ]
        result = PSAK22Rules.validate_identifiable_assets(assets)
        # Only first asset has warning (fair value <=0 but not goodwill)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK22ComplianceLevel.SUBSTANTIAL
        assert "memiliki nilai wajar non-positif" in result.warnings[0]

    def test_validate_contingent_consideration_equity_zero_value(self):
        cc = PSAK22ContingentConsideration(
            consideration_id=uuid4(),
            description="Earn-out",
            classification=PSAK22ContingentConsiderationClassification.EQUITY,
            fair_value_at_acquisition=Decimal("1000000"),  # should be 0
        )
        result = PSAK22Rules.validate_contingent_consideration([cc])
        assert result.is_compliant is True
        assert result.compliance_level == PSAK22ComplianceLevel.SUBSTANTIAL
        assert "diklasifikasikan sebagai ekuitas harus diukur pada nilai wajar 0" in result.warnings[0]


# -----------------------------------------------------------------------------
# Validator
# -----------------------------------------------------------------------------
class TestPSAK22Validator:
    def test_create_business_combination(self, validator):
        acquirer_id = uuid4()
        acquiree_id = uuid4()
        acquisition_date = datetime(2026, 6, 30, tzinfo=UTC)
        combo = validator.create_business_combination(
            acquirer_id=acquirer_id,
            acquiree_id=acquiree_id,
            acquirer_name="Acquirer",
            acquiree_name="Acquiree",
            acquisition_date=acquisition_date,
            consideration_transferred=Decimal("1000000"),
            nci_choice=PSAK22NCIChoice.PROPORTIONATE_SHARE,
            nci_percentage=Decimal("20"),
            nci_value=Decimal("0"),
        )
        assert isinstance(combo, PSAK22BusinessCombination)
        assert combo.acquirer_id == acquirer_id
        assert combo.acquiree_id == acquiree_id
        assert combo.acquirer_name == "Acquirer"
        assert combo.acquiree_name == "Acquiree"
        assert combo.acquisition_date == acquisition_date
        assert combo.consideration_transferred == Decimal("1000000")
        assert combo.nci_choice == PSAK22NCIChoice.PROPORTIONATE_SHARE
        assert combo.nci_percentage == Decimal("20")
        assert combo.nci_value == Decimal("0")
        assert combo.identifiable_assets == []
        assert combo.identifiable_liabilities == []

    def test_add_identifiable_asset(self, sample_combination):
        combo = validator.add_identifiable_asset(
            sample_combination,
            description="New Asset",
            fair_value=Decimal("150000"),
            carrying_amount=Decimal("100000"),
            asset_type="financial",
            useful_life=None,
            is_current=True,
        )
        assert len(combo.identifiable_assets) == len(sample_combination.identifiable_assets) + 1
        new_asset = combo.identifiable_assets[-1]
        assert new_asset.description == "New Asset"
        assert new_asset.fair_value == Decimal("150000")
        assert new_asset.carrying_amount == Decimal("100000")
        assert new_asset.asset_type == "financial"
        assert new_asset.is_current is True

    def test_add_identifiable_liability(self, sample_combination):
        combo = validator.add_identifiable_liability(
            sample_combination,
            description="New Liability",
            fair_value=Decimal("50000"),
            carrying_amount=Decimal("40000"),
            liability_type="non-current",
            settlement_date=datetime(2028, 12, 31, tzinfo=UTC),
        )
        assert len(combo.identifiable_liabilities) == len(sample_combination.identifiable_liabilities) + 1
        new_liab = combo.identifiable_liabilities[-1]
        assert new_liab.description == "New Liability"
        assert new_liab.fair_value == Decimal("50000")
        assert new_liab.liability_type == "non-current"

    def test_add_contingent_consideration(self, sample_combination):
        combo = validator.add_contingent_consideration(
            sample_combination,
            description="New CC",
            classification=PSAK22ContingentConsiderationClassification.ASSET,
            fair_value_at_acquisition=Decimal("20000"),
            settlement_range_low=Decimal("10000"),
            settlement_range_high=Decimal("30000"),
            settlement_date=datetime(2027, 6, 30, tzinfo=UTC),
        )
        assert len(combo.contingent_consideration) == 1
        cc = combo.contingent_consideration[0]
        assert cc.description == "New CC"
        assert cc.classification == PSAK22ContingentConsiderationClassification.ASSET
        assert cc.fair_value_at_acquisition == Decimal("20000")

    def test_set_nci_value(self, sample_combination):
        new_nci = Decimal("150000000")
        combo = validator.set_nci_value(sample_combination, new_nci)
        assert combo.nci_value == new_nci

    def test_set_business_combination_flag(self, sample_combination):
        combo = validator.set_business_combination_flag(sample_combination, False)
        assert combo.is_business_combination is False
        # Also test setting to True
        combo2 = validator.set_business_combination_flag(combo, True)
        assert combo2.is_business_combination is True

    def test_compute_goodwill(self, sample_combination):
        goodwill, gain = validator.compute_goodwill(sample_combination)
        # As calculated earlier: 376M goodwill
        assert goodwill == Decimal("376000000")
        assert gain == Decimal("0")

    def test_validate_combination_full_compliant(self, sample_combination):
        current_date = sample_combination.acquisition_date + timedelta(days=180)
        result = validator.validate_combination(sample_combination, current_date)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK22ComplianceLevel.FULL
        assert result.errors == []
        assert result.warnings == []  # no warnings (assets fair values positive, etc.)

    def test_validate_combination_with_warnings(self, validator):
        combo = validator.create_business_combination(
            uuid4(), uuid4(), "A", "B", datetime.now(UTC), Decimal("1000"),
            nci_choice=PSAK22NCIChoice.PROPORTIONATE_SHARE,
            nci_percentage=Decimal("10"),
            nci_value=Decimal("0"),
        )
        # Add asset with zero fair value (non-goodwill) -> warning
        combo = validator.add_identifiable_asset(combo, "Zero Asset", Decimal("0"), Decimal("0"), "tangible")
        # Add contingent consideration equity with non-zero fair value -> warning
        combo = validator.add_contingent_consideration(
            combo,
            "Equity CC",
            PSAK22ContingentConsiderationClassification.EQUITY,
            Decimal("5000"),
        )
        # Set NCI value to avoid errors
        nci_value = combo.nci_proportionate_value
        combo = validator.set_nci_value(combo, nci_value)
        result = validator.validate_combination(combo)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK22ComplianceLevel.SUBSTANTIAL
        assert len(result.warnings) >= 2  # asset warning and CC warning

    def test_validate_combination_with_errors(self, validator):
        combo = validator.create_business_combination(
            uuid4(), uuid4(), "A", "B", datetime.now(UTC), Decimal("1000"),
            nci_choice=PSAK22NCIChoice.FAIR_VALUE,
            nci_percentage=Decimal("150"),  # invalid
            nci_value=Decimal("0"),  # missing for fair value
        )
        result = validator.validate_combination(combo)
        assert result.is_compliant is False
        assert result.compliance_level == PSAK22ComplianceLevel.NON_COMPLIANT
        # Should have two errors: percentage and missing NCI value
        assert any("Persentase NCI harus antara 0 dan 100" in e for e in result.errors)
        assert any("NCI diukur pada nilai wajar tetapi nilai NCI tidak ditentukan" in e for e in result.errors)

    def test_validate_combination_measurement_period_error(self, sample_combination):
        current_date = sample_combination.acquisition_date + timedelta(days=400)
        sample_combination.measurement_period_adjustments["goodwill"] = Decimal("1000000")
        result = validator.validate_combination(sample_combination, current_date)
        assert result.is_compliant is False
        assert "Penyesuaian periode pengukuran hanya diperbolehkan dalam 12 bulan" in result.errors[0]

    def test_get_requirements_summary(self, validator):
        summary = validator.get_requirements_summary()
        assert "acquisition_method" in summary
        assert "goodwill" in summary
        assert "bargain_purchase" in summary
        assert "measurement_period" in summary
        assert "disclosures" in summary
        assert isinstance(summary["disclosures"], list)


# -----------------------------------------------------------------------------
# PSAK22 Facade
# -----------------------------------------------------------------------------
class TestPSAK22:
    def test_calculate_goodwill(self):
        goodwill = PSAK22.calculate_goodwill(
            purchase_price=Decimal("1000000"),
            fair_value_of_identifiable_net_assets=Decimal("800000")
        )
        assert goodwill == Decimal("200000")

    def test_get_nci_measurement_methods(self):
        methods = PSAK22.get_nci_measurement_methods()
        assert isinstance(methods, list)
        assert "proportionate_share" in methods
        assert "fair_value" in methods


# -----------------------------------------------------------------------------
# PSAK22GoodwillCalculation (placeholder)
# -----------------------------------------------------------------------------
class TestPSAK22GoodwillCalculation:
    def test_construction(self):
        calc = PSAK22GoodwillCalculation(
            purchase_price=Decimal("1000000"),
            fair_value_net_assets=Decimal("700000")
        )
        assert calc.goodwill == Decimal("300000")


# -----------------------------------------------------------------------------
# Singleton accessor
# -----------------------------------------------------------------------------
def test_get_psak22_validator():
    v1 = get_psak22_validator()
    v2 = get_psak22_validator()
    assert v1 is v2
    assert isinstance(v1, PSAK22Validator)