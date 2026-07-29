# tests/policy_engine/psak/test_psak_48_impairment.py
"""
Comprehensive tests for PSAK 48: Impairment of Assets.
Covers all methods including allocation, reversal, value in use, and validation.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from policy_engine.psak.psak_48_impairment import (
    CGUNotFoundError,
    PSAK48AssetType,
    PSAK48CashGeneratingUnit,
    PSAK48CashGeneratingUnitType,
    PSAK48ComplianceLevel,
    PSAK48Error,
    PSAK48ImpairmentIndicator,
    PSAK48ImpairmentLoss,
    PSAK48ImpairmentLossAllocation,
    PSAK48ImpairmentService,
    PSAK48ImpairmentTestResult,
    PSAK48ImpairmentTestTiming,
    PSAK48RecoverableAmount,
    PSAK48Rules,
    PSAK48ValidationResult,
    PSAK48Validator,
    RecoverableAmountNotDeterminableError,
    get_psak48_validator,
)

# ============================================================================
# Enum tests
# ============================================================================

class TestPSAK48AssetType:
    def test_members_exist(self):
        assert hasattr(PSAK48AssetType, 'GOODWILL')
        assert hasattr(PSAK48AssetType, 'INTANGIBLE_ASSET')
        assert hasattr(PSAK48AssetType, 'PROPERTY_PLANT_EQUIPMENT')
        assert hasattr(PSAK48AssetType, 'INVESTMENT_PROPERTY')
        assert hasattr(PSAK48AssetType, 'RIGHT_OF_USE_ASSET')
        assert hasattr(PSAK48AssetType, 'OTHER')
        assert PSAK48AssetType.GOODWILL.value == "goodwill"


class TestPSAK48ImpairmentIndicator:
    def test_members_exist(self):
        assert hasattr(PSAK48ImpairmentIndicator, 'EXTERNAL_DECLINE_IN_MARKET_VALUE')
        assert hasattr(PSAK48ImpairmentIndicator, 'EXTERNAL_SIGNIFICANT_CHANGE')
        assert hasattr(PSAK48ImpairmentIndicator, 'EXTERNAL_INTEREST_RATE_INCREASE')
        assert hasattr(PSAK48ImpairmentIndicator, 'INTERNAL_OBSOLESCENCE')
        assert hasattr(PSAK48ImpairmentIndicator, 'INTERNAL_ASSET_IDLE')
        assert hasattr(PSAK48ImpairmentIndicator, 'INTERNAL_ECONOMIC_PERFORMANCE_DECLINE')
        assert hasattr(PSAK48ImpairmentIndicator, 'INTERNAL_RESTRUCTURING')
        assert hasattr(PSAK48ImpairmentIndicator, 'INTERNAL_CASH_FLOW_NEGATIVE')


class TestPSAK48CashGeneratingUnitType:
    def test_members_exist(self):
        assert hasattr(PSAK48CashGeneratingUnitType, 'SINGLE_ASSET')
        assert hasattr(PSAK48CashGeneratingUnitType, 'GROUP_OF_ASSETS')
        assert hasattr(PSAK48CashGeneratingUnitType, 'REPORTING_SEGMENT')


class TestPSAK48ImpairmentTestTiming:
    def test_members_exist(self):
        assert hasattr(PSAK48ImpairmentTestTiming, 'ANNUALLY')
        assert hasattr(PSAK48ImpairmentTestTiming, 'WHEN_INDICATOR')


class TestPSAK48ImpairmentLossAllocation:
    def test_members_exist(self):
        assert hasattr(PSAK48ImpairmentLossAllocation, 'FIRST_TO_GOODWILL')
        assert hasattr(PSAK48ImpairmentLossAllocation, 'PRO_RATA_TO_OTHER_ASSETS')


class TestPSAK48ComplianceLevel:
    def test_members_exist(self):
        assert hasattr(PSAK48ComplianceLevel, 'FULL')
        assert hasattr(PSAK48ComplianceLevel, 'SUBSTANTIAL')
        assert hasattr(PSAK48ComplianceLevel, 'PARTIAL')
        assert hasattr(PSAK48ComplianceLevel, 'NON_COMPLIANT')


# ============================================================================
# Custom exceptions
# ============================================================================

class TestPSAK48Error:
    def test_construction(self):
        error = PSAK48Error("Test message")
        assert str(error) == "Test message"


class TestCGUNotFoundError:
    def test_construction(self):
        error = CGUNotFoundError("CGU not found")
        assert isinstance(error, PSAK48Error)


class TestRecoverableAmountNotDeterminableError:
    def test_construction(self):
        error = RecoverableAmountNotDeterminableError("Cannot determine")
        assert isinstance(error, PSAK48Error)


# ============================================================================
# PSAK48RecoverableAmount tests
# ============================================================================

class TestPSAK48RecoverableAmount:
    def test_construction_with_both(self):
        fvlcs = Decimal("1000000")
        viu = Decimal("1200000")
        ra = PSAK48RecoverableAmount(
            fair_value_less_costs_to_sell=fvlcs,
            value_in_use=viu,
            recoverable_amount=Decimal("1200000"),  # will be recomputed to max
        )
        assert ra.recoverable_amount == Decimal("1200000")
        assert ra.fair_value_less_costs_to_sell == fvlcs
        assert ra.value_in_use == viu

    def test_construction_with_only_fvlcs(self):
        fvlcs = Decimal("1000000")
        ra = PSAK48RecoverableAmount(
            fair_value_less_costs_to_sell=fvlcs,
            value_in_use=None,
            recoverable_amount=Decimal("1000000"),
        )
        assert ra.recoverable_amount == Decimal("1000000")

    def test_construction_with_only_viu(self):
        viu = Decimal("1200000")
        ra = PSAK48RecoverableAmount(
            fair_value_less_costs_to_sell=None,
            value_in_use=viu,
            recoverable_amount=Decimal("1200000"),
        )
        assert ra.recoverable_amount == Decimal("1200000")

    def test_construction_with_no_candidates_raises(self):
        with pytest.raises(RecoverableAmountNotDeterminableError, match="Neither FVLCS nor VIU"):
            PSAK48RecoverableAmount(
                fair_value_less_costs_to_sell=None,
                value_in_use=None,
                recoverable_amount=Decimal(0),
            )

    def test_to_dict(self):
        ra = PSAK48RecoverableAmount(
            fair_value_less_costs_to_sell=Decimal("1000000"),
            value_in_use=Decimal("1200000"),
            recoverable_amount=Decimal("1200000"),
        )
        d = ra.to_dict()
        assert d["fair_value_less_costs_to_sell"] == "1000000"
        assert d["value_in_use"] == "1200000"
        assert d["recoverable_amount"] == "1200000"


# ============================================================================
# PSAK48ImpairmentLoss tests
# ============================================================================

class TestPSAK48ImpairmentLoss:
    def test_construction_no_loss(self):
        loss = PSAK48ImpairmentLoss(
            loss_id=uuid4(),
            asset_id=uuid4(),
            carrying_amount_before=Decimal("1000000"),
            recoverable_amount=Decimal("1200000"),  # higher -> no loss
        )
        assert loss.impairment_loss == Decimal(0)

    def test_construction_with_loss(self):
        loss = PSAK48ImpairmentLoss(
            loss_id=uuid4(),
            asset_id=uuid4(),
            carrying_amount_before=Decimal("1500000"),
            recoverable_amount=Decimal("1000000"),
        )
        assert loss.impairment_loss == Decimal("500000")

    def test_construction_with_allocation(self):
        loss_id = uuid4()
        asset_id = uuid4()
        loss = PSAK48ImpairmentLoss(
            loss_id=loss_id,
            asset_id=asset_id,
            carrying_amount_before=Decimal("2000000"),
            recoverable_amount=Decimal("1200000"),
            allocated_to_goodwill=Decimal("300000"),
            allocated_to_other_assets={uuid4(): Decimal("200000")},
            reversal_allowed=True,
            reversal_amount=Decimal("100000"),
        )
        assert loss.loss_id == loss_id
        assert loss.impairment_loss == Decimal("800000")
        assert loss.allocated_to_goodwill == Decimal("300000")
        assert loss.reversal_allowed is True

    def test_to_dict(self):
        loss = PSAK48ImpairmentLoss(
            loss_id=uuid4(),
            asset_id=uuid4(),
            carrying_amount_before=Decimal("2000000"),
            recoverable_amount=Decimal("1200000"),
            allocated_to_goodwill=Decimal("300000"),
            allocated_to_other_assets={uuid4(): Decimal("200000")},
        )
        d = loss.to_dict()
        assert d["carrying_before"] == "2000000"
        assert d["recoverable_amount"] == "1200000"
        assert d["impairment_loss"] == "800000"
        assert "allocated_to_other_assets" in d


# ============================================================================
# PSAK48CashGeneratingUnit tests (including allocate_impairment_loss)
# ============================================================================

class TestPSAK48CashGeneratingUnit:
    def test_construction(self):
        cgu_id = uuid4()
        cgu = PSAK48CashGeneratingUnit(
            cgu_id=cgu_id,
            cgu_code="CGU-01",
            name="Manufacturing",
            cgu_type=PSAK48CashGeneratingUnitType.GROUP_OF_ASSETS,
        )
        assert cgu.cgu_id == cgu_id
        assert cgu.assets == []
        assert cgu.allocated_goodwill == {}

    def test_total_carrying_amount(self):
        cgu = PSAK48CashGeneratingUnit(
            cgu_id=uuid4(),
            cgu_code="CGU-01",
            name="Test",
            cgu_type=PSAK48CashGeneratingUnitType.GROUP_OF_ASSETS,
            assets=[uuid4(), uuid4()],
            allocated_goodwill={uuid4(): Decimal("100000")},
        )
        asset_map = {
            cgu.assets[0]: Decimal("200000"),
            cgu.assets[1]: Decimal("300000"),
        }
        total = cgu.total_carrying_amount(asset_map)
        assert total == Decimal("600000")  # 200k + 300k + 100k

    def test_allocate_impairment_loss_goodwill_first(self):
        cgu = PSAK48CashGeneratingUnit(
            cgu_id=uuid4(),
            cgu_code="CGU-01",
            name="Test",
            cgu_type=PSAK48CashGeneratingUnitType.GROUP_OF_ASSETS,
            assets=[uuid4(), uuid4()],
            allocated_goodwill={uuid4(): Decimal("100000"), uuid4(): Decimal("200000")},
        )
        asset_carrying = {
            cgu.assets[0]: Decimal("500000"),
            cgu.assets[1]: Decimal("300000"),
        }
        loss = Decimal("300000")
        allocation = cgu.allocate_impairment_loss(loss, asset_carrying, goodwill_first=True)
        # Goodwill total = 300k, loss = 300k -> all allocated to goodwill
        assert sum(allocation.values()) == Decimal("300000")
        # Check proportional allocation to goodwill
        gw_ids = list(cgu.allocated_goodwill.keys())
        # gw1 share = 100/300 * 300k = 100k, gw2 share = 200/300 * 300k = 200k
        assert allocation[gw_ids[0]] == Decimal("100000")
        assert allocation[gw_ids[1]] == Decimal("200000")
        # No allocation to other assets
        assert cgu.assets[0] not in allocation
        assert cgu.assets[1] not in allocation

    def test_allocate_impairment_loss_partial_goodwill(self):
        cgu = PSAK48CashGeneratingUnit(
            cgu_id=uuid4(),
            cgu_code="CGU-01",
            name="Test",
            cgu_type=PSAK48CashGeneratingUnitType.GROUP_OF_ASSETS,
            assets=[uuid4(), uuid4()],
            allocated_goodwill={uuid4(): Decimal("100000")},  # only 100k
        )
        asset_carrying = {
            cgu.assets[0]: Decimal("500000"),
            cgu.assets[1]: Decimal("300000"),
        }
        loss = Decimal("300000")
        allocation = cgu.allocate_impairment_loss(loss, asset_carrying, goodwill_first=True)
        # Goodwill gets 100k, remaining 200k allocated pro-rata to other assets
        gw_ids = list(cgu.allocated_goodwill.keys())
        assert allocation[gw_ids[0]] == Decimal("100000")
        # Other assets: total carrying = 800k, asset0 share = 500/800 * 200k = 125k, asset1 = 300/800 * 200k = 75k
        assert allocation[cgu.assets[0]] == Decimal("125000")
        assert allocation[cgu.assets[1]] == Decimal("75000")
        assert sum(allocation.values()) == Decimal("300000")

    def test_allocate_impairment_loss_no_goodwill(self):
        cgu = PSAK48CashGeneratingUnit(
            cgu_id=uuid4(),
            cgu_code="CGU-01",
            name="Test",
            cgu_type=PSAK48CashGeneratingUnitType.GROUP_OF_ASSETS,
            assets=[uuid4(), uuid4()],
            allocated_goodwill={},
        )
        asset_carrying = {
            cgu.assets[0]: Decimal("500000"),
            cgu.assets[1]: Decimal("300000"),
        }
        loss = Decimal("300000")
        allocation = cgu.allocate_impairment_loss(loss, asset_carrying, goodwill_first=True)
        # No goodwill, all pro-rata
        assert allocation[cgu.assets[0]] == Decimal("187500")  # 500/800 * 300k = 187.5k rounded to 187500? Quantize to integer (0), 500/800*300k=187500 exactly
        assert allocation[cgu.assets[1]] == Decimal("112500")
        assert sum(allocation.values()) == Decimal("300000")

    def test_allocate_impairment_loss_with_goodwill_first_false(self):
        cgu = PSAK48CashGeneratingUnit(
            cgu_id=uuid4(),
            cgu_code="CGU-01",
            name="Test",
            cgu_type=PSAK48CashGeneratingUnitType.GROUP_OF_ASSETS,
            assets=[uuid4(), uuid4()],
            allocated_goodwill={uuid4(): Decimal("100000")},
        )
        asset_carrying = {
            cgu.assets[0]: Decimal("500000"),
            cgu.assets[1]: Decimal("300000"),
        }
        loss = Decimal("300000")
        allocation = cgu.allocate_impairment_loss(loss, asset_carrying, goodwill_first=False)
        # If goodwill_first=False, it still allocates to goodwill? The logic: if goodwill_first True, else it goes to other assets first? Actually code: if goodwill_first and gw exists, allocate to gw first, then remaining to others. If goodwill_first is False, it skips gw and goes to others.
        # So all 300k goes to other assets pro-rata
        assert cgu.assets[0] in allocation
        assert cgu.assets[1] in allocation
        # Goodwill not allocated
        gw_id = list(cgu.allocated_goodwill.keys())[0]
        assert gw_id not in allocation
        assert allocation[cgu.assets[0]] == Decimal("187500")
        assert allocation[cgu.assets[1]] == Decimal("112500")
        assert sum(allocation.values()) == Decimal("300000")

    def test_to_dict(self):
        cgu = PSAK48CashGeneratingUnit(
            cgu_id=uuid4(),
            cgu_code="CGU-01",
            name="Test",
            cgu_type=PSAK48CashGeneratingUnitType.GROUP_OF_ASSETS,
            assets=[uuid4(), uuid4()],
            allocated_goodwill={uuid4(): Decimal("100000")},
            carrying_amount=Decimal("1000000"),
            recoverable_amount=Decimal("900000"),
            impairment_loss_recognized=Decimal("100000"),
        )
        d = cgu.to_dict()
        assert d["cgu_code"] == "CGU-01"
        assert d["name"] == "Test"
        assert d["carrying_amount"] == "1000000"
        assert d["recoverable_amount"] == "900000"
        assert d["impairment_loss"] == "100000"


# ============================================================================
# PSAK48ImpairmentTestResult tests
# ============================================================================

class TestPSAK48ImpairmentTestResult:
    def test_construction_no_loss(self):
        result = PSAK48ImpairmentTestResult(
            test_id=uuid4(),
            entity_id=uuid4(),
            entity_name="Entity",
            test_date=datetime.now(UTC),
            asset_id=uuid4(),
            asset_type=PSAK48AssetType.PROPERTY_PLANT_EQUIPMENT,
            is_cgu=False,
            carrying_amount_before=Decimal("1000000"),
            recoverable_amount=Decimal("1200000"),
        )
        assert result.impairment_loss == Decimal(0)

    def test_construction_with_loss(self):
        result = PSAK48ImpairmentTestResult(
            test_id=uuid4(),
            entity_id=uuid4(),
            entity_name="Entity",
            test_date=datetime.now(UTC),
            asset_id=uuid4(),
            asset_type=PSAK48AssetType.GOODWILL,
            is_cgu=False,
            carrying_amount_before=Decimal("1500000"),
            recoverable_amount=Decimal("1000000"),
            indicators_present=[PSAK48ImpairmentIndicator.EXTERNAL_DECLINE_IN_MARKET_VALUE],
        )
        assert result.impairment_loss == Decimal("500000")
        assert result.indicators_present == [PSAK48ImpairmentIndicator.EXTERNAL_DECLINE_IN_MARKET_VALUE]

    def test_to_dict(self):
        result = PSAK48ImpairmentTestResult(
            test_id=uuid4(),
            entity_id=uuid4(),
            entity_name="Entity",
            test_date=datetime(2026, 12, 31, tzinfo=UTC),
            asset_id=uuid4(),
            asset_type=PSAK48AssetType.PROPERTY_PLANT_EQUIPMENT,
            is_cgu=True,
            carrying_amount_before=Decimal("1500000"),
            recoverable_amount=Decimal("1000000"),
            indicators_present=[PSAK48ImpairmentIndicator.INTERNAL_OBSOLESCENCE],
            fair_value_less_costs_to_sell=Decimal("1100000"),
            value_in_use=Decimal("1000000"),
            discount_rate_used=Decimal("12"),
            growth_rate_used=Decimal("3"),
        )
        d = result.to_dict()
        assert d["carrying_before"] == "1500000"
        assert d["recoverable_amount"] == "1000000"
        assert d["impairment_loss"] == "500000"
        assert d["indicators"] == ["keusangan_fisik_atau_teknis"]
        assert d["fvlcs"] == "1100000"
        assert d["viu"] == "1000000"


# ============================================================================
# PSAK48ValidationResult tests (including add_warning)
# ============================================================================

class TestPSAK48ValidationResult:
    def test_add_error(self):
        result = PSAK48ValidationResult(is_compliant=True, compliance_level=PSAK48ComplianceLevel.FULL)
        result.add_error("Test error")
        assert result.errors == ["Test error"]
        assert result.is_compliant is False
        assert result.compliance_level == PSAK48ComplianceLevel.NON_COMPLIANT

    def test_add_warning(self):
        result = PSAK48ValidationResult(is_compliant=True, compliance_level=PSAK48ComplianceLevel.FULL)
        result.add_warning("Test warning")
        assert result.warnings == ["Test warning"]
        assert result.is_compliant is True  # warnings don't affect
        assert result.compliance_level == PSAK48ComplianceLevel.SUBSTANTIAL

    def test_add_warning_already_substantial(self):
        result = PSAK48ValidationResult(is_compliant=True, compliance_level=PSAK48ComplianceLevel.SUBSTANTIAL)
        result.add_warning("Another warning")
        assert result.compliance_level == PSAK48ComplianceLevel.SUBSTANTIAL  # stays

    def test_hash(self):
        result1 = PSAK48ValidationResult(is_compliant=True, compliance_level=PSAK48ComplianceLevel.FULL)
        result2 = PSAK48ValidationResult(is_compliant=True, compliance_level=PSAK48ComplianceLevel.FULL)
        assert result1.hash_sha256 == result2.hash_sha256
        result1.add_warning("x")
        result2.add_error("y")
        assert result1.hash_sha256 != result2.hash_sha256

    def test_to_dict(self):
        result = PSAK48ValidationResult(is_compliant=False, compliance_level=PSAK48ComplianceLevel.PARTIAL)
        result.add_error("E1")
        result.add_warning("W1")
        d = result.to_dict()
        assert d["is_compliant"] is False
        assert d["compliance_level"] == "sebagian"
        assert d["errors"] == ["E1"]
        assert d["warnings"] == ["W1"]
        assert "hash" in d


# ============================================================================
# PSAK48ImpairmentService tests
# ============================================================================

class TestPSAK48ImpairmentService:
    def test_calculate_value_in_use(self):
        cash_flows = [(1, Decimal("100000")), (2, Decimal("150000")), (3, Decimal("200000"))]
        discount_rate = Decimal("10")  # 10%
        viu = PSAK48ImpairmentService.calculate_value_in_use(cash_flows, discount_rate)
        # Manual: year1: 100k / 1.1 = 90909.09
        # year2: 150k / 1.21 = 123966.94
        # year3: 200k / 1.331 = 150263.71
        # total = 365139.74 -> rounded to 365140
        assert viu == Decimal("365140")

    def test_calculate_value_in_use_with_perpetual_growth(self):
        cash_flows = [(1, Decimal("100000")), (2, Decimal("110000")), (3, Decimal("120000"))]
        discount_rate = Decimal("12")
        perpetual_growth = Decimal("3")
        viu = PSAK48ImpairmentService.calculate_value_in_use(
            cash_flows, discount_rate, perpetual_growth_rate=perpetual_growth
        )
        # Verify it doesn't raise, just check it's positive
        assert viu > 0

    def test_calculate_fair_value_less_costs_to_sell(self):
        fv = Decimal("1000000")
        costs = Decimal("50000")
        fvlcs = PSAK48ImpairmentService.calculate_fair_value_less_costs_to_sell(fv, costs)
        assert fvlcs == Decimal("950000")

    def test_determine_recoverable_amount(self):
        fvlcs = Decimal("1000000")
        viu = Decimal("1200000")
        ra = PSAK48ImpairmentService.determine_recoverable_amount(fvlcs, viu)
        assert ra.recoverable_amount == Decimal("1200000")
        assert ra.fair_value_less_costs_to_sell == fvlcs
        assert ra.value_in_use == viu

    def test_determine_recoverable_amount_missing_both_raises(self):
        with pytest.raises(RecoverableAmountNotDeterminableError, match="Cannot determine recoverable"):
            PSAK48ImpairmentService.determine_recoverable_amount(None, None)

    def test_identify_impairment_indicators(self):
        indicators = PSAK48ImpairmentService.identify_impairment_indicators(
            asset_type=PSAK48AssetType.GOODWILL,
            market_value_decline=True,
            significant_change=True,
            interest_rate_increase=False,
            obsolescence=True,
            idle_asset=False,
            performance_decline=True,
            cash_flow_negative=False,
        )
        expected = [
            PSAK48ImpairmentIndicator.EXTERNAL_DECLINE_IN_MARKET_VALUE,
            PSAK48ImpairmentIndicator.EXTERNAL_SIGNIFICANT_CHANGE,
            PSAK48ImpairmentIndicator.INTERNAL_OBSOLESCENCE,
            PSAK48ImpairmentIndicator.INTERNAL_ECONOMIC_PERFORMANCE_DECLINE,
        ]
        assert indicators == expected

    def test_can_reverse_impairment(self):
        # Goodwill cannot be reversed
        assert PSAK48ImpairmentService.can_reverse_impairment(PSAK48AssetType.GOODWILL) is False
        # Other assets can
        assert PSAK48ImpairmentService.can_reverse_impairment(PSAK48AssetType.PROPERTY_PLANT_EQUIPMENT) is True
        assert PSAK48ImpairmentService.can_reverse_impairment(PSAK48AssetType.INTANGIBLE_ASSET) is True
        assert PSAK48ImpairmentService.can_reverse_impairment(PSAK48AssetType.OTHER) is True


# ============================================================================
# PSAK48Rules tests
# ============================================================================

class TestPSAK48Rules:
    def test_validate_annual_testing_requirement_goodwill_no_last_test(self):
        result = PSAK48Rules.validate_annual_testing_requirement(
            asset_type=PSAK48AssetType.GOODWILL,
            last_test_date=None,
            current_date=datetime.now(UTC),
        )
        assert result.is_compliant is False
        assert "harus diuji penurunan nilai setiap tahun" in result.errors[0]

    def test_validate_annual_testing_requirement_goodwill_within_year(self):
        last_date = datetime.now(UTC) - timedelta(days=100)
        result = PSAK48Rules.validate_annual_testing_requirement(
            asset_type=PSAK48AssetType.GOODWILL,
            last_test_date=last_date,
            current_date=datetime.now(UTC),
        )
        assert result.is_compliant is True

    def test_validate_annual_testing_requirement_goodwill_exceeded_year(self):
        last_date = datetime.now(UTC) - timedelta(days=400)
        result = PSAK48Rules.validate_annual_testing_requirement(
            asset_type=PSAK48AssetType.GOODWILL,
            last_test_date=last_date,
            current_date=datetime.now(UTC),
        )
        assert result.is_compliant is False
        assert "belum diuji penurunan nilai dalam 12 bulan" in result.errors[0]

    def test_validate_cgu_identification_no_assets(self):
        cgu = PSAK48CashGeneratingUnit(
            cgu_id=uuid4(),
            cgu_code="CGU-01",
            name="Test",
            cgu_type=PSAK48CashGeneratingUnitType.GROUP_OF_ASSETS,
            assets=[],
            allocated_goodwill={},
        )
        result = PSAK48Rules.validate_cgu_identification(cgu)
        assert result.is_compliant is False
        assert "CGU tidak memiliki aset atau goodwill" in result.errors[0]

    def test_validate_allocation_method(self):
        result = PSAK48Rules.validate_allocation_method(PSAK48ImpairmentLossAllocation.FIRST_TO_GOODWILL)
        assert result.is_compliant is True
        result2 = PSAK48Rules.validate_allocation_method(PSAK48ImpairmentLossAllocation.PRO_RATA_TO_OTHER_ASSETS)
        assert result2.is_compliant is True
        assert "Alokasi impairment loss harus ke goodwill terlebih dahulu" in result2.warnings[0]

    def test_validate_disclosure_ok(self):
        test_result = PSAK48ImpairmentTestResult(
            test_id=uuid4(),
            entity_id=uuid4(),
            entity_name="Test",
            test_date=datetime.now(UTC),
            asset_id=uuid4(),
            asset_type=PSAK48AssetType.PROPERTY_PLANT_EQUIPMENT,
            is_cgu=False,
            carrying_amount_before=Decimal("1000000"),
            recoverable_amount=Decimal("1200000"),  # no loss
        )
        result = PSAK48Rules.validate_disclosure(test_result)
        assert result.is_compliant is True

    def test_validate_disclosure_warning_if_loss_and_no_discount(self):
        test_result = PSAK48ImpairmentTestResult(
            test_id=uuid4(),
            entity_id=uuid4(),
            entity_name="Test",
            test_date=datetime.now(UTC),
            asset_id=uuid4(),
            asset_type=PSAK48AssetType.PROPERTY_PLANT_EQUIPMENT,
            is_cgu=False,
            carrying_amount_before=Decimal("1500000"),
            recoverable_amount=Decimal("1000000"),  # loss exists
            value_in_use=Decimal("1000000"),
            discount_rate_used=None,  # missing discount
        )
        result = PSAK48Rules.validate_disclosure(test_result)
        assert result.is_compliant is True
        assert "Asumsi diskonto untuk nilai pakai tidak diungkapkan" in result.warnings[0]


# ============================================================================
# PSAK48Validator tests
# ============================================================================

class TestPSAK48Validator:
    @pytest.fixture
    def validator(self):
        return PSAK48Validator()

    def test_create_cgu(self, validator):
        cgu = validator.create_cgu("CGU-01", "Manufacturing", PSAK48CashGeneratingUnitType.GROUP_OF_ASSETS)
        assert cgu.cgu_code == "CGU-01"
        assert cgu.name == "Manufacturing"
        assert cgu.assets == []
        assert cgu.allocated_goodwill == {}

    def test_add_asset_to_cgu(self, validator):
        cgu = validator.create_cgu("CGU-01", "Test")
        asset_id = uuid4()
        new_cgu = validator.add_asset_to_cgu(cgu, asset_id)
        assert new_cgu.assets == [asset_id]
        # Original unchanged
        assert cgu.assets == []

    def test_allocate_goodwill_to_cgu(self, validator):
        cgu = validator.create_cgu("CGU-01", "Test")
        asset_id = uuid4()
        new_cgu = validator.allocate_goodwill_to_cgu(cgu, asset_id, Decimal("100000"))
        assert new_cgu.allocated_goodwill == {asset_id: Decimal("100000")}
        # Original unchanged
        assert cgu.allocated_goodwill == {}

    def test_calculate_value_in_use(self, validator):
        cash_flows = [(1, Decimal("100000")), (2, Decimal("150000")), (3, Decimal("200000"))]
        viu = validator.calculate_value_in_use(cash_flows, discount_rate=Decimal("10"))
        assert viu > 0

    def test_calculate_fair_value_less_costs_to_sell(self, validator):
        result = validator.calculate_fair_value_less_costs_to_sell(Decimal("1000000"), Decimal("50000"))
        assert result == Decimal("950000")

    def test_determine_recoverable_amount(self, validator):
        fvlcs = Decimal("1000000")
        viu = Decimal("1200000")
        ra = validator.determine_recoverable_amount(fvlcs, viu)
        assert ra.recoverable_amount == Decimal("1200000")

    def test_determine_recoverable_amount_raises(self, validator):
        with pytest.raises(RecoverableAmountNotDeterminableError):
            validator.determine_recoverable_amount(None, None)

    def test_perform_impairment_test(self, validator):
        entity_id = uuid4()
        asset_id = uuid4()
        result = validator.perform_impairment_test(
            entity_id=entity_id,
            entity_name="Test",
            asset_id=asset_id,
            asset_type=PSAK48AssetType.PROPERTY_PLANT_EQUIPMENT,
            carrying_amount=Decimal("1500000"),
            is_cgu=False,
            fvlcs=Decimal("1000000"),
            viu=Decimal("1200000"),
            discount_rate=Decimal("12"),
            indicators=[PSAK48ImpairmentIndicator.INTERNAL_OBSOLESCENCE],
        )
        assert result.entity_id == entity_id
        assert result.asset_id == asset_id
        assert result.carrying_amount_before == Decimal("1500000")
        assert result.recoverable_amount == Decimal("1200000")  # max of fvlcs and viu
        assert result.impairment_loss == Decimal("300000")

    def test_allocate_impairment_to_cgu(self, validator):
        cgu = validator.create_cgu("CGU-01", "Test")
        asset_id = uuid4()
        cgu = validator.add_asset_to_cgu(cgu, asset_id)
        cgu = validator.allocate_goodwill_to_cgu(cgu, uuid4(), Decimal("100000"))
        asset_carrying = {asset_id: Decimal("500000")}
        allocation = validator.allocate_impairment_to_cgu(cgu, asset_carrying, Decimal("200000"))
        # Goodwill gets 100k, remaining 100k to asset
        assert sum(allocation.values()) == Decimal("200000")
        # asset gets 100k
        assert allocation[asset_id] == Decimal("100000")

    def test_validate_impairment_test(self, validator):
        test_result = PSAK48ImpairmentTestResult(
            test_id=uuid4(),
            entity_id=uuid4(),
            entity_name="Test",
            test_date=datetime.now(UTC),
            asset_id=uuid4(),
            asset_type=PSAK48AssetType.GOODWILL,
            is_cgu=False,
            carrying_amount_before=Decimal("1500000"),
            recoverable_amount=Decimal("1200000"),
            reversal_recognized=Decimal("100000"),  # reversal on goodwill not allowed
        )
        result = validator.validate_impairment_test(test_result)
        # Should have error because goodwill impairment cannot be reversed
        assert result.is_compliant is False
        assert "Goodwill impairment tidak dapat dibalik" in result.errors[0]

    def test_validate_impairment_test_ok(self, validator):
        test_result = PSAK48ImpairmentTestResult(
            test_id=uuid4(),
            entity_id=uuid4(),
            entity_name="Test",
            test_date=datetime.now(UTC),
            asset_id=uuid4(),
            asset_type=PSAK48AssetType.PROPERTY_PLANT_EQUIPMENT,
            is_cgu=False,
            carrying_amount_before=Decimal("1000000"),
            recoverable_amount=Decimal("1200000"),  # no loss
        )
        result = validator.validate_impairment_test(test_result)
        assert result.is_compliant is True

    def test_get_requirements_summary(self, validator):
        summary = validator.get_requirements_summary()
        assert "scope" in summary
        assert "indicators" in summary
        assert "recoverable_amount" in summary
        assert "annual_testing" in summary
        assert "cgu" in summary
        assert "allocation" in summary
        assert "reversal" in summary
        assert "disclosures" in summary


# ============================================================================
# Singleton accessor test
# ============================================================================

def test_get_psak48_validator():
    v1 = get_psak48_validator()
    v2 = get_psak48_validator()
    assert v1 is v2
    assert isinstance(v1, PSAK48Validator)
