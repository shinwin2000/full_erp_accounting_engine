# test_impairment_tester.py
# ==========================
# Comprehensive tests for domain/fixed_asset/impairment_tester.py.
# Covers enums, value objects, ImpairmentTester methods, and helper functions.
# Includes decimal precision tests and edge cases.

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest

from domain.fixed_asset.impairment_tester import (
    ImpairmentIndicator,
    ImpairmentTest,
    ImpairmentTester,
    ImpairmentTestError,
    ImpairmentTestMethod,
    ImpairmentTestNotFoundError,
    ImpairmentTestResult,
    InvalidRecoverableAmountError,
    calculate_impairment_percentage,
    calculate_present_value,
)


# ----------------------------------------------------------------------
# Mock FixedAsset (simplified)
# ----------------------------------------------------------------------
class MockFixedAsset:
    def __init__(
        self,
        asset_id=None,
        asset_code="ASSET-001",
        name="Test Asset",
        acquisition_cost=Decimal("10000"),
        accumulated_depreciation=Decimal("0"),
        accumulated_impairment=Decimal("0"),
        salvage_value=Decimal("1000"),
        useful_life_years=5,
        depreciation_method="straight_line",
        currency="IDR",
        is_depreciable=True,
        is_fully_depreciated=False,
        status="ACTIVE",  # Assume AssetStatus.ACTIVE
    ):
        self.id = asset_id or uuid4()
        self.asset_code = asset_code
        self.name = name
        self.acquisition_cost = acquisition_cost
        self.accumulated_depreciation = accumulated_depreciation
        self.accumulated_impairment = accumulated_impairment
        self.salvage_value = salvage_value
        self.useful_life_years = useful_life_years
        self.depreciation_method = depreciation_method
        self.currency = currency
        self.is_depreciable = is_depreciable
        self.is_fully_depreciated = is_fully_depreciated
        self.status = status
        self.net_book_value = (
            acquisition_cost - accumulated_depreciation - accumulated_impairment
        )


# ----------------------------------------------------------------------
# Enums
# ----------------------------------------------------------------------
class TestImpairmentTestResult:
    def test_members_exist(self):
        assert hasattr(ImpairmentTestResult, "NO_IMPAIRMENT")
        assert hasattr(ImpairmentTestResult, "IMPAIRED")
        assert hasattr(ImpairmentTestResult, "REVERSAL")

    def test_member_is_instance(self):
        assert isinstance(ImpairmentTestResult.NO_IMPAIRMENT, ImpairmentTestResult)

    def test_display_name(self):
        assert ImpairmentTestResult.NO_IMPAIRMENT.display_name() == "Tidak Ada Penurunan Nilai"
        assert ImpairmentTestResult.IMPAIRED.display_name() == "Mengalami Penurunan Nilai"
        assert ImpairmentTestResult.REVERSAL.display_name() == "Pembalikan Penurunan Nilai"

    def test_from_string(self):
        assert ImpairmentTestResult.from_string("no_impairment") == ImpairmentTestResult.NO_IMPAIRMENT
        assert ImpairmentTestResult.from_string("impaired") == ImpairmentTestResult.IMPAIRED
        assert ImpairmentTestResult.from_string("reversal") == ImpairmentTestResult.REVERSAL
        assert ImpairmentTestResult.from_string("unknown") is None


class TestImpairmentIndicator:
    def test_members_exist(self):
        assert hasattr(ImpairmentIndicator, "MARKET_DECLINE")
        assert hasattr(ImpairmentIndicator, "ECONOMIC_DOWNTURN")
        assert hasattr(ImpairmentIndicator, "REGULATORY_CHANGE")
        assert hasattr(ImpairmentIndicator, "INTEREST_RATE_INCREASE")
        assert hasattr(ImpairmentIndicator, "TECHNOLOGY_OBSOLESCENCE")
        assert hasattr(ImpairmentIndicator, "OBSOLESCENCE")
        assert hasattr(ImpairmentIndicator, "PHYSICAL_DAMAGE")
        assert hasattr(ImpairmentIndicator, "IDLE_ASSET")
        assert hasattr(ImpairmentIndicator, "POOR_PERFORMANCE")
        assert hasattr(ImpairmentIndicator, "CASH_FLOW_NEGATIVE")
        assert hasattr(ImpairmentIndicator, "DISPOSAL_PLAN")
        assert hasattr(ImpairmentIndicator, "RESTRUCTURING")

    def test_member_is_instance(self):
        assert isinstance(ImpairmentIndicator.MARKET_DECLINE, ImpairmentIndicator)

    def test_display_name(self):
        assert ImpairmentIndicator.MARKET_DECLINE.display_name() == "Penurunan Nilai Pasar"
        assert ImpairmentIndicator.ECONOMIC_DOWNTURN.display_name() == "Resesi Ekonomi"
        assert ImpairmentIndicator.REGULATORY_CHANGE.display_name() == "Perubahan Regulasi"
        assert ImpairmentIndicator.INTEREST_RATE_INCREASE.display_name() == "Kenaikan Suku Bunga"
        assert ImpairmentIndicator.TECHNOLOGY_OBSOLESCENCE.display_name() == "Keusangan Teknologi"
        assert ImpairmentIndicator.OBSOLESCENCE.display_name() == "Usang"
        assert ImpairmentIndicator.PHYSICAL_DAMAGE.display_name() == "Kerusakan Fisik"
        assert ImpairmentIndicator.IDLE_ASSET.display_name() == "Tidak Digunakan"
        assert ImpairmentIndicator.POOR_PERFORMANCE.display_name() == "Kinerja Buruk"
        assert ImpairmentIndicator.CASH_FLOW_NEGATIVE.display_name() == "Arus Kas Negatif"
        assert ImpairmentIndicator.DISPOSAL_PLAN.display_name() == "Rencana Pelepasan"
        assert ImpairmentIndicator.RESTRUCTURING.display_name() == "Restrukturisasi"

    def test_is_external(self):
        assert ImpairmentIndicator.MARKET_DECLINE.is_external() is True
        assert ImpairmentIndicator.ECONOMIC_DOWNTURN.is_external() is True
        assert ImpairmentIndicator.REGULATORY_CHANGE.is_external() is True
        assert ImpairmentIndicator.INTEREST_RATE_INCREASE.is_external() is True
        assert ImpairmentIndicator.TECHNOLOGY_OBSOLESCENCE.is_external() is True
        assert ImpairmentIndicator.OBSOLESCENCE.is_external() is False
        assert ImpairmentIndicator.PHYSICAL_DAMAGE.is_external() is False
        assert ImpairmentIndicator.IDLE_ASSET.is_external() is False

    def test_is_internal(self):
        assert ImpairmentIndicator.OBSOLESCENCE.is_internal() is True
        assert ImpairmentIndicator.PHYSICAL_DAMAGE.is_internal() is True
        assert ImpairmentIndicator.MARKET_DECLINE.is_internal() is False

    def test_from_string(self):
        assert ImpairmentIndicator.from_string("market_decline") == ImpairmentIndicator.MARKET_DECLINE
        assert ImpairmentIndicator.from_string("economic_downturn") == ImpairmentIndicator.ECONOMIC_DOWNTURN
        assert ImpairmentIndicator.from_string("obsolescence") == ImpairmentIndicator.OBSOLESCENCE
        assert ImpairmentIndicator.from_string("unknown") is None


class TestImpairmentTestMethod:
    def test_members_exist(self):
        assert hasattr(ImpairmentTestMethod, "FAIR_VALUE_LESS_COSTS")
        assert hasattr(ImpairmentTestMethod, "VALUE_IN_USE")
        assert hasattr(ImpairmentTestMethod, "MARKET_APPROACH")
        assert hasattr(ImpairmentTestMethod, "INCOME_APPROACH")
        assert hasattr(ImpairmentTestMethod, "COST_APPROACH")

    def test_member_is_instance(self):
        assert isinstance(ImpairmentTestMethod.FAIR_VALUE_LESS_COSTS, ImpairmentTestMethod)

    def test_display_name(self):
        assert ImpairmentTestMethod.FAIR_VALUE_LESS_COSTS.display_name() == "Nilai Wajar - Biaya Jual"
        assert ImpairmentTestMethod.VALUE_IN_USE.display_name() == "Nilai Pakai"
        assert ImpairmentTestMethod.MARKET_APPROACH.display_name() == "Pendekatan Pasar"
        assert ImpairmentTestMethod.INCOME_APPROACH.display_name() == "Pendekatan Pendapatan"
        assert ImpairmentTestMethod.COST_APPROACH.display_name() == "Pendekatan Biaya"

    def test_from_string(self):
        assert ImpairmentTestMethod.from_string("fvlcs") == ImpairmentTestMethod.FAIR_VALUE_LESS_COSTS
        assert ImpairmentTestMethod.from_string("viu") == ImpairmentTestMethod.VALUE_IN_USE
        assert ImpairmentTestMethod.from_string("market") == ImpairmentTestMethod.MARKET_APPROACH
        assert ImpairmentTestMethod.from_string("income") == ImpairmentTestMethod.INCOME_APPROACH
        assert ImpairmentTestMethod.from_string("cost") == ImpairmentTestMethod.COST_APPROACH
        assert ImpairmentTestMethod.from_string("unknown") is None


# ----------------------------------------------------------------------
# Exceptions
# ----------------------------------------------------------------------
class TestExceptions:
    def test_impairment_test_error(self):
        err = ImpairmentTestError("test")
        assert isinstance(err, ValueError)
        assert str(err) == "test"

    def test_invalid_recoverable_amount_error(self):
        err = InvalidRecoverableAmountError("test")
        assert isinstance(err, ImpairmentTestError)

    def test_impairment_test_not_found_error(self):
        err = ImpairmentTestNotFoundError("test")
        assert isinstance(err, ImpairmentTestError)


# ----------------------------------------------------------------------
# ImpairmentTest Value Object
# ----------------------------------------------------------------------
class TestImpairmentTest:
    def test_construction_valid(self):
        test_id = uuid4()
        asset_id = uuid4()
        test = ImpairmentTest(
            test_id=test_id,
            asset_id=asset_id,
            asset_code="ASSET-001",
            asset_name="Test",
            test_date=date(2025, 1, 1),
            carrying_amount=Decimal("1000"),
            recoverable_amount=Decimal("900"),
            impairment_loss=Decimal("100"),
            previous_impairment_loss=Decimal("0"),
            reversal_amount=Decimal("0"),
            result=ImpairmentTestResult.IMPAIRED,
            indicators=[ImpairmentIndicator.MARKET_DECLINE],
            method=ImpairmentTestMethod.FAIR_VALUE_LESS_COSTS,
            assumptions={"discount_rate": Decimal("0.1")},
            notes="Test note",
            tested_by="alice",
            created_at=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
        )
        assert test.test_id == test_id
        assert test.asset_id == asset_id
        assert test.carrying_amount == Decimal("1000")
        assert test.impairment_loss == Decimal("100")
        assert test.result == ImpairmentTestResult.IMPAIRED
        assert len(test.indicators) == 1

    def test_construction_negative_carrying_raises(self):
        with pytest.raises(ImpairmentTestError, match="Carrying amount cannot be negative"):
            ImpairmentTest(
                test_id=uuid4(),
                asset_id=uuid4(),
                asset_code="A",
                asset_name="A",
                test_date=date.today(),
                carrying_amount=Decimal("-100"),
                recoverable_amount=Decimal("0"),
                impairment_loss=Decimal("0"),
                previous_impairment_loss=Decimal("0"),
                reversal_amount=Decimal("0"),
                result=ImpairmentTestResult.NO_IMPAIRMENT,
                indicators=[],
                method=ImpairmentTestMethod.FAIR_VALUE_LESS_COSTS,
            )

    def test_construction_impairment_loss_negative_raises(self):
        with pytest.raises(ImpairmentTestError, match="Impairment loss cannot be negative"):
            ImpairmentTest(
                test_id=uuid4(),
                asset_id=uuid4(),
                asset_code="A",
                asset_name="A",
                test_date=date.today(),
                carrying_amount=Decimal("1000"),
                recoverable_amount=Decimal("1000"),
                impairment_loss=Decimal("-100"),
                previous_impairment_loss=Decimal("0"),
                reversal_amount=Decimal("0"),
                result=ImpairmentTestResult.NO_IMPAIRMENT,
                indicators=[],
                method=ImpairmentTestMethod.FAIR_VALUE_LESS_COSTS,
            )

    def test_construction_impairment_loss_exceeds_carrying_raises(self):
        with pytest.raises(ImpairmentTestError, match="Impairment loss cannot exceed carrying amount"):
            ImpairmentTest(
                test_id=uuid4(),
                asset_id=uuid4(),
                asset_code="A",
                asset_name="A",
                test_date=date.today(),
                carrying_amount=Decimal("100"),
                recoverable_amount=Decimal("0"),
                impairment_loss=Decimal("200"),
                previous_impairment_loss=Decimal("0"),
                reversal_amount=Decimal("0"),
                result=ImpairmentTestResult.IMPAIRED,
                indicators=[],
                method=ImpairmentTestMethod.FAIR_VALUE_LESS_COSTS,
            )

    def test_construction_future_test_date_raises(self):
        with pytest.raises(ImpairmentTestError, match="Test date cannot be in the future"):
            ImpairmentTest(
                test_id=uuid4(),
                asset_id=uuid4(),
                asset_code="A",
                asset_name="A",
                test_date=date(2100, 1, 1),
                carrying_amount=Decimal("1000"),
                recoverable_amount=Decimal("1000"),
                impairment_loss=Decimal("0"),
                previous_impairment_loss=Decimal("0"),
                reversal_amount=Decimal("0"),
                result=ImpairmentTestResult.NO_IMPAIRMENT,
                indicators=[],
                method=ImpairmentTestMethod.FAIR_VALUE_LESS_COSTS,
            )

    def test_construction_naive_created_at_auto_utc(self):
        naive = datetime(2025, 1, 1, 10, 0, 0)
        test = ImpairmentTest(
            test_id=uuid4(),
            asset_id=uuid4(),
            asset_code="A",
            asset_name="A",
            test_date=date.today(),
            carrying_amount=Decimal("1000"),
            recoverable_amount=Decimal("1000"),
            impairment_loss=Decimal("0"),
            previous_impairment_loss=Decimal("0"),
            reversal_amount=Decimal("0"),
            result=ImpairmentTestResult.NO_IMPAIRMENT,
            indicators=[],
            method=ImpairmentTestMethod.FAIR_VALUE_LESS_COSTS,
            created_at=naive,
        )
        assert test.created_at.tzinfo == UTC

    def test_to_dict(self):
        test_id = uuid4()
        asset_id = uuid4()
        test = ImpairmentTest(
            test_id=test_id,
            asset_id=asset_id,
            asset_code="ASSET-001",
            asset_name="Test",
            test_date=date(2025, 1, 1),
            carrying_amount=Decimal("1000"),
            recoverable_amount=Decimal("900"),
            impairment_loss=Decimal("100"),
            previous_impairment_loss=Decimal("0"),
            reversal_amount=Decimal("0"),
            result=ImpairmentTestResult.IMPAIRED,
            indicators=[ImpairmentIndicator.MARKET_DECLINE],
            method=ImpairmentTestMethod.FAIR_VALUE_LESS_COSTS,
            assumptions={"discount_rate": Decimal("0.1")},
            notes="Test note",
            tested_by="alice",
            created_at=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
        )
        d = test.to_dict()
        assert d["test_id"] == str(test_id)
        assert d["asset_id"] == str(asset_id)
        assert d["test_date"] == "2025-01-01"
        assert d["carrying_amount"] == "1000"
        assert d["impairment_loss"] == "100"
        assert d["result"] == "impaired"
        assert d["indicators"] == ["market_decline"]
        assert d["method"] == "fvlcs"
        assert d["assumptions"]["discount_rate"] == "0.1"

    def test_from_dict(self):
        data = {
            "test_id": str(uuid4()),
            "asset_id": str(uuid4()),
            "asset_code": "ASSET-001",
            "asset_name": "Test",
            "test_date": "2025-01-01",
            "carrying_amount": "1000",
            "recoverable_amount": "900",
            "impairment_loss": "100",
            "previous_impairment_loss": "0",
            "reversal_amount": "0",
            "result": "impaired",
            "indicators": ["market_decline", "economic_downturn"],
            "method": "fvlcs",
            "assumptions": {"discount_rate": "0.1"},
            "notes": "Test note",
            "tested_by": "alice",
            "created_at": "2025-01-01T10:00:00+00:00",
        }
        test = ImpairmentTest.from_dict(data)
        assert test.test_id == UUID(data["test_id"])
        assert test.asset_id == UUID(data["asset_id"])
        assert test.test_date == date(2025, 1, 1)
        assert test.carrying_amount == Decimal("1000")
        assert test.impairment_loss == Decimal("100")
        assert test.result == ImpairmentTestResult.IMPAIRED
        assert len(test.indicators) == 2
        assert test.indicators[0] == ImpairmentIndicator.MARKET_DECLINE
        assert test.indicators[1] == ImpairmentIndicator.ECONOMIC_DOWNTURN
        assert test.method == ImpairmentTestMethod.FAIR_VALUE_LESS_COSTS
        assert test.assumptions["discount_rate"] == "0.1"
        assert test.notes == "Test note"
        assert test.tested_by == "alice"

    def test_from_dict_invalid_result_raises(self):
        data = {
            "test_id": str(uuid4()),
            "asset_id": str(uuid4()),
            "asset_code": "A",
            "asset_name": "A",
            "test_date": "2025-01-01",
            "carrying_amount": "1000",
            "recoverable_amount": "1000",
            "impairment_loss": "0",
            "previous_impairment_loss": "0",
            "reversal_amount": "0",
            "result": "invalid",
            "indicators": [],
            "method": "fvlcs",
            "assumptions": {},
            "notes": "",
            "tested_by": "system",
            "created_at": "2025-01-01T10:00:00+00:00",
        }
        with pytest.raises(ImpairmentTestError, match="Invalid result"):
            ImpairmentTest.from_dict(data)

    def test_from_dict_invalid_method_raises(self):
        data = {
            "test_id": str(uuid4()),
            "asset_id": str(uuid4()),
            "asset_code": "A",
            "asset_name": "A",
            "test_date": "2025-01-01",
            "carrying_amount": "1000",
            "recoverable_amount": "1000",
            "impairment_loss": "0",
            "previous_impairment_loss": "0",
            "reversal_amount": "0",
            "result": "no_impairment",
            "indicators": [],
            "method": "invalid",
            "assumptions": {},
            "notes": "",
            "tested_by": "system",
            "created_at": "2025-01-01T10:00:00+00:00",
        }
        with pytest.raises(ImpairmentTestError, match="Invalid method"):
            ImpairmentTest.from_dict(data)


# ----------------------------------------------------------------------
# ImpairmentTester
# ----------------------------------------------------------------------
class TestImpairmentTester:
    @pytest.fixture
    def tester(self):
        return ImpairmentTester()

    @pytest.fixture
    def asset(self):
        return MockFixedAsset(
            acquisition_cost=Decimal("10000"),
            accumulated_depreciation=Decimal("0"),
            accumulated_impairment=Decimal("0"),
            salvage_value=Decimal("1000"),
        )

    @pytest.fixture
    def impaired_asset(self):
        return MockFixedAsset(
            acquisition_cost=Decimal("10000"),
            accumulated_depreciation=Decimal("2000"),
            accumulated_impairment=Decimal("500"),
            salvage_value=Decimal("1000"),
        )

    # ---- identify_indicators ----
    def test_identify_indicators_market_decline(self, tester, asset):
        indicators = tester.identify_indicators(asset, market_price=Decimal("5000"))
        # asset.net_book_value = 10000, market_price 5000 < NBV -> MARKET_DECLINE
        assert ImpairmentIndicator.MARKET_DECLINE in indicators

    def test_identify_indicators_idle(self, tester, asset):
        indicators = tester.identify_indicators(asset, is_idle=True)
        assert ImpairmentIndicator.IDLE_ASSET in indicators

    def test_identify_indicators_physical_damage(self, tester, asset):
        indicators = tester.identify_indicators(asset, physical_damage=True)
        assert ImpairmentIndicator.PHYSICAL_DAMAGE in indicators

    def test_identify_indicators_obsolescence(self, tester, asset):
        asset.is_fully_depreciated = True
        indicators = tester.identify_indicators(asset)
        assert ImpairmentIndicator.OBSOLESCENCE in indicators

    def test_identify_indicators_all(self, tester, asset):
        indicators = tester.identify_indicators(
            asset,
            market_price=Decimal("5000"),
            is_idle=True,
            physical_damage=True,
            poor_performance=True,
            cash_flow_negative=True,
            disposal_planned=True,
            economic_downturn=True,
            regulatory_change=True,
            technology_obsolescence=True,
        )
        # Should have many indicators
        expected = [
            ImpairmentIndicator.ECONOMIC_DOWNTURN,
            ImpairmentIndicator.REGULATORY_CHANGE,
            ImpairmentIndicator.TECHNOLOGY_OBSOLESCENCE,
            ImpairmentIndicator.MARKET_DECLINE,
            ImpairmentIndicator.IDLE_ASSET,
            ImpairmentIndicator.PHYSICAL_DAMAGE,
            ImpairmentIndicator.POOR_PERFORMANCE,
            ImpairmentIndicator.CASH_FLOW_NEGATIVE,
            ImpairmentIndicator.DISPOSAL_PLAN,
        ]
        for ind in expected:
            assert ind in indicators

    # ---- calculate_fair_value_less_costs_to_sell ----
    def test_calculate_fvlcs_with_fair_value(self, tester, asset):
        fvlcs = tester.calculate_fair_value_less_costs_to_sell(
            asset, fair_value=Decimal("8000"), selling_costs=Decimal("200")
        )
        assert fvlcs == Decimal("7800.00")

    def test_calculate_fvlcs_without_fair_value_uses_nbv(self, tester, asset):
        fvlcs = tester.calculate_fair_value_less_costs_to_sell(asset)
        # NBV = 10000, selling_costs default 0
        assert fvlcs == Decimal("10000.00")

    def test_calculate_fvlcs_negative_selling_costs_raises(self, tester, asset):
        with pytest.raises(InvalidRecoverableAmountError, match="Selling costs cannot be negative"):
            tester.calculate_fair_value_less_costs_to_sell(
                asset, selling_costs=Decimal("-100")
            )

    # ---- calculate_value_in_use ----
    def test_calculate_value_in_use_basic(self, tester, asset):
        cash_flows = [Decimal("500"), Decimal("600"), Decimal("700")]
        viu = tester.calculate_value_in_use(
            asset,
            projected_cash_flows=cash_flows,
            discount_rate=Decimal("0.10"),
        )
        # Expected: 500/1.1 + 600/1.1^2 + 700/1.1^3
        expected = (
            Decimal("500") / Decimal("1.1")
            + Decimal("600") / (Decimal("1.1") ** 2)
            + Decimal("700") / (Decimal("1.1") ** 3)
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        assert viu == expected

    def test_calculate_value_in_use_with_terminal_value(self, tester, asset):
        cash_flows = [Decimal("500"), Decimal("600")]
        terminal = Decimal("10000")
        viu = tester.calculate_value_in_use(
            asset,
            projected_cash_flows=cash_flows,
            discount_rate=Decimal("0.10"),
            terminal_value=terminal,
        )
        expected = (
            Decimal("500") / Decimal("1.1")
            + Decimal("600") / (Decimal("1.1") ** 2)
            + Decimal("10000") / (Decimal("1.1") ** 2)
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        assert viu == expected

    def test_calculate_value_in_use_with_growth(self, tester, asset):
        cash_flows = [Decimal("500"), Decimal("600")]
        viu = tester.calculate_value_in_use(
            asset,
            projected_cash_flows=cash_flows,
            discount_rate=Decimal("0.10"),
            growth_rate=Decimal("0.03"),
        )
        # Terminal = 600 * (1.03) / (0.10 - 0.03) = 600 * 1.03 / 0.07 = 8828.57
        # Then discount back 2 years: 8828.57 / 1.21 = 7296.34
        # Plus the two cash flows: 454.55 + 495.87 = 950.42
        # Total ~ 8246.76
        expected = (
            Decimal("500") / Decimal("1.1")
            + Decimal("600") / (Decimal("1.1") ** 2)
            + (Decimal("600") * Decimal("1.03") / (Decimal("0.10") - Decimal("0.03")))
            / (Decimal("1.1") ** 2)
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        assert viu == expected

    def test_calculate_value_in_use_empty_cash_flows(self, tester, asset):
        viu = tester.calculate_value_in_use(asset, projected_cash_flows=[])
        assert viu == asset.net_book_value

    def test_calculate_value_in_use_invalid_discount_rate(self, tester, asset):
        with pytest.raises(InvalidRecoverableAmountError, match="Discount rate must be between 0 and 1"):
            tester.calculate_value_in_use(asset, projected_cash_flows=[], discount_rate=Decimal("1.5"))

    # ---- calculate_recoverable_amount ----
    def test_calculate_recoverable_amount_with_fvlcs_viu(self, tester, asset):
        fvlcs = Decimal("8000")
        viu = Decimal("8500")
        recoverable = tester.calculate_recoverable_amount(
            asset, fvlcs=fvlcs, value_in_use=viu
        )
        assert recoverable == Decimal("8500.00")

    def test_calculate_recoverable_amount_uses_fvlcs_if_higher(self, tester, asset):
        fvlcs = Decimal("9000")
        viu = Decimal("8500")
        recoverable = tester.calculate_recoverable_amount(
            asset, fvlcs=fvlcs, value_in_use=viu
        )
        assert recoverable == Decimal("9000.00")

    def test_calculate_recoverable_amount_without_provided(self, tester, asset):
        # It will call fvlcs and viu internally (defaults)
        recoverable = tester.calculate_recoverable_amount(asset)
        # Since no fair_value, fvlcs = NBV = 10000, viu = NBV = 10000, so recoverable = 10000
        assert recoverable == Decimal("10000.00")

    # ---- test_impairment ----
    def test_test_impairment_no_impairment(self, tester, asset):
        # NBV = 10000, recoverable = 12000 -> no impairment
        test = tester.test_impairment(
            asset,
            recoverable_amount=Decimal("12000"),
            tested_by="alice",
        )
        assert test.result == ImpairmentTestResult.NO_IMPAIRMENT
        assert test.impairment_loss == Decimal("0")
        assert test.reversal_amount == Decimal("0")
        assert test.carrying_amount == asset.net_book_value
        assert test.recoverable_amount == Decimal("12000")
        assert test.indicators == []  # default, because no indicators passed and identify_indicators returns empty

    def test_test_impairment_impaired(self, tester, asset):
        test = tester.test_impairment(
            asset,
            recoverable_amount=Decimal("8000"),
            indicators=[ImpairmentIndicator.MARKET_DECLINE],
            tested_by="bob",
        )
        assert test.result == ImpairmentTestResult.IMPAIRED
        assert test.impairment_loss == Decimal("2000")  # 10000 - 8000
        assert test.reversal_amount == Decimal("0")
        assert test.carrying_amount == Decimal("10000")
        assert test.recoverable_amount == Decimal("8000")
        assert ImpairmentIndicator.MARKET_DECLINE in test.indicators
        assert test.tested_by == "bob"

    def test_test_impairment_with_indicators_auto_identified(self, tester, asset):
        # Set market_price to trigger market decline
        with patch.object(tester, "identify_indicators") as mock_identify:
            mock_identify.return_value = [ImpairmentIndicator.MARKET_DECLINE]
            test = tester.test_impairment(
                asset,
                recoverable_amount=Decimal("8000"),
                tested_by="alice",
            )
            mock_identify.assert_called_once_with(asset)
            assert test.indicators == [ImpairmentIndicator.MARKET_DECLINE]

    def test_test_impairment_reversal(self, tester, impaired_asset):
        # impaired_asset has NBV = 10000 - 2000 - 500 = 7500, accumulated_impairment = 500
        # Recoverable = 7800 > carrying, and previous impairment > 0 -> reversal
        test = tester.test_impairment(
            impaired_asset,
            recoverable_amount=Decimal("7800"),
            tested_by="carol",
        )
        assert test.result == ImpairmentTestResult.REVERSAL
        assert test.impairment_loss == Decimal("0")
        # Reversal amount = min(previous impairment, recoverable - carrying) = min(500, 7800 - 7500 = 300) = 300
        assert test.reversal_amount == Decimal("300")
        assert test.previous_impairment_loss == Decimal("500")
        assert test.carrying_amount == Decimal("7500")

    def test_test_impairment_partial_reversal(self, tester, impaired_asset):
        # Recoverable = 7900, carrying = 7500, diff = 400, previous impairment = 500 -> reversal = 400
        test = tester.test_impairment(
            impaired_asset,
            recoverable_amount=Decimal("7900"),
        )
        assert test.result == ImpairmentTestResult.REVERSAL
        assert test.reversal_amount == Decimal("400")

    def test_test_impairment_full_reversal(self, tester, impaired_asset):
        # Recoverable = 8000, diff = 500, previous impairment = 500 -> reversal = 500
        test = tester.test_impairment(
            impaired_asset,
            recoverable_amount=Decimal("8000"),
        )
        assert test.result == ImpairmentTestResult.REVERSAL
        assert test.reversal_amount == Decimal("500")

    def test_test_impairment_reversal_but_no_previous_impairment(self, tester, asset):
        # asset has no previous impairment, but recoverable > carrying -> no impairment, no reversal
        test = tester.test_impairment(
            asset,
            recoverable_amount=Decimal("12000"),
        )
        assert test.result == ImpairmentTestResult.NO_IMPAIRMENT
        assert test.reversal_amount == Decimal("0")

    def test_test_impairment_stores_history(self, tester, asset):
        test1 = tester.test_impairment(asset, recoverable_amount=Decimal("8000"))
        test2 = tester.test_impairment(asset, recoverable_amount=Decimal("9000"))
        history = tester.get_test_history(asset_id=asset.id)
        assert len(history) == 2
        assert history[0] is test1
        assert history[1] is test2

    # ---- test_cash_generating_unit ----
    def test_test_cgu_no_impairment(self, tester):
        asset1 = MockFixedAsset(acquisition_cost=Decimal("1000"), accumulated_depreciation=Decimal("0"))
        asset2 = MockFixedAsset(acquisition_cost=Decimal("2000"), accumulated_depreciation=Decimal("0"))
        assets = [asset1, asset2]
        recoverable_cgu = Decimal("3000")  # total carrying = 3000, no impairment
        tests = tester.test_cash_generating_unit(
            assets,
            cgu_name="CGU-1",
            recoverable_amount_cgu=recoverable_cgu,
            tested_by="alice",
        )
        assert len(tests) == 2
        for test in tests:
            assert test.result == ImpairmentTestResult.NO_IMPAIRMENT
            assert test.impairment_loss == Decimal("0")
            assert "no impairment" in test.notes

    def test_test_cgu_with_impairment(self, tester):
        asset1 = MockFixedAsset(acquisition_cost=Decimal("1000"), accumulated_depreciation=Decimal("0"))
        asset2 = MockFixedAsset(acquisition_cost=Decimal("2000"), accumulated_depreciation=Decimal("0"))
        assets = [asset1, asset2]
        recoverable_cgu = Decimal("2000")  # total carrying = 3000, impairment = 1000
        tests = tester.test_cash_generating_unit(
            assets,
            cgu_name="CGU-1",
            recoverable_amount_cgu=recoverable_cgu,
            indicators=[ImpairmentIndicator.ECONOMIC_DOWNTURN],
            tested_by="bob",
        )
        assert len(tests) == 2
        # Proportion: asset1 = 1/3 of total, asset2 = 2/3
        # Impairment = 1000, so asset1 gets 333.33, asset2 gets 666.67
        # Due to rounding, one might have adjustment
        total_loss = sum(t.impairment_loss for t in tests)
        assert total_loss == Decimal("1000.00")
        for test in tests:
            assert test.result == ImpairmentTestResult.IMPAIRED
            assert "CGU 'CGU-1'" in test.notes
            assert ImpairmentIndicator.ECONOMIC_DOWNTURN in test.indicators

    def test_test_cgu_empty_list(self, tester):
        tests = tester.test_cash_generating_unit(
            [], "CGU-1", Decimal("0"), tested_by="alice"
        )
        assert tests == []

    def test_test_cgu_asset_with_zero_nbv(self, tester):
        asset1 = MockFixedAsset(acquisition_cost=Decimal("1000"), accumulated_depreciation=Decimal("1000"))
        asset2 = MockFixedAsset(acquisition_cost=Decimal("2000"), accumulated_depreciation=Decimal("0"))
        assets = [asset1, asset2]
        recoverable_cgu = Decimal("1500")  # total carrying = 2000, impairment = 500
        tests = tester.test_cash_generating_unit(
            assets,
            cgu_name="CGU-2",
            recoverable_amount_cgu=recoverable_cgu,
        )
        # asset1 has NBV=0, so gets no impairment. asset2 gets full 500.
        assert len(tests) == 2
        assert tests[0].impairment_loss == Decimal("0")
        assert tests[1].impairment_loss == Decimal("500.00")

    # ---- history and summary ----
    def test_get_test_history_no_asset_id(self, tester, asset):
        tester.test_impairment(asset, recoverable_amount=Decimal("8000"))
        tester.test_impairment(asset, recoverable_amount=Decimal("9000"))
        history = tester.get_test_history()
        assert len(history) == 2

    def test_get_test_history_with_asset_id(self, tester, asset):
        asset2 = MockFixedAsset(asset_code="ASSET-002")
        tester.test_impairment(asset, recoverable_amount=Decimal("8000"))
        tester.test_impairment(asset2, recoverable_amount=Decimal("7000"))
        history = tester.get_test_history(asset_id=asset.id)
        assert len(history) == 1
        assert history[0].asset_id == asset.id

    def test_get_test_history_limit(self, tester, asset):
        for i in range(10):
            tester.test_impairment(asset, recoverable_amount=Decimal(str(9000 - i)))
        history = tester.get_test_history(limit=3)
        assert len(history) == 3

    def test_get_latest_test(self, tester, asset):
        assert tester.get_latest_test(asset.id) is None
        test1 = tester.test_impairment(asset, recoverable_amount=Decimal("8000"))
        test2 = tester.test_impairment(asset, recoverable_amount=Decimal("9000"))
        latest = tester.get_latest_test(asset.id)
        assert latest is test2
        assert latest.impairment_loss == Decimal("1000")  # 10000 - 9000

    def test_get_summary(self, tester, asset):
        tester.test_impairment(asset, recoverable_amount=Decimal("8000"))  # impaired
        tester.test_impairment(asset, recoverable_amount=Decimal("12000"))  # no impairment
        # Add another asset with reversal
        asset2 = MockFixedAsset(
            acquisition_cost=Decimal("10000"),
            accumulated_depreciation=Decimal("2000"),
            accumulated_impairment=Decimal("500"),
        )
        tester.test_impairment(asset2, recoverable_amount=Decimal("7800"))  # reversal
        summary = tester.get_summary()
        assert summary["total_tests"] == 3
        assert summary["impaired_count"] == 1
        assert summary["reversal_count"] == 1
        assert summary["no_impairment_count"] == 1
        # total_impairment_loss = 2000 (from first test) + 0 + 0 = 2000
        # total_reversal = 0 + 0 + 300 = 300
        assert Decimal(summary["total_impairment_loss"]) == Decimal("2000")
        assert Decimal(summary["total_reversal_amount"]) == Decimal("300")
        assert Decimal(summary["net_impairment"]) == Decimal("1700")

    def test_clear_history(self, tester, asset):
        tester.test_impairment(asset, recoverable_amount=Decimal("8000"))
        assert len(tester._test_history) == 1
        tester.clear_history()
        assert len(tester._test_history) == 0


# ----------------------------------------------------------------------
# Helper Functions
# ----------------------------------------------------------------------
class TestHelperFunctions:
    def test_calculate_present_value(self):
        pv = calculate_present_value(
            future_amount=Decimal("1000"),
            discount_rate=Decimal("0.10"),
            years=2,
        )
        expected = (Decimal("1000") / (Decimal("1.1") ** 2)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )
        assert pv == expected

    def test_calculate_impairment_percentage(self):
        # 100% impairment
        pct = calculate_impairment_percentage(
            carrying_amount=Decimal("1000"),
            recoverable_amount=Decimal("0"),
        )
        assert pct == Decimal("100.00")
        # 50% impairment
        pct = calculate_impairment_percentage(
            carrying_amount=Decimal("1000"),
            recoverable_amount=Decimal("500"),
        )
        assert pct == Decimal("50.00")
        # No impairment
        pct = calculate_impairment_percentage(
            carrying_amount=Decimal("1000"),
            recoverable_amount=Decimal("1200"),
        )
        assert pct == Decimal("0.00")
        # Zero carrying
        pct = calculate_impairment_percentage(
            carrying_amount=Decimal("0"),
            recoverable_amount=Decimal("0"),
        )
        assert pct == Decimal("0.00")
