# test_hedge_effectiveness_tester.py
# ===================================
# Comprehensive tests for hedge_effectiveness_tester.py.
# Covers all classes and methods with edge cases.

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_EVEN
from unittest.mock import patch
from uuid import uuid4

import pytest

from domain.hedge.hedge_effectiveness_tester import (
    EffectivenessTestDataPoint,
    EffectivenessTestError,
    EffectivenessTestResult,
    HedgeEffectivenessTester,
)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def sample_data_points() -> list[EffectivenessTestDataPoint]:
    """Sample data points for testing."""
    return [
        EffectivenessTestDataPoint(
            date=date(2025, 1, 1),
            hedge_change=Decimal("100"),
            hedged_change=Decimal("100"),
        ),
        EffectivenessTestDataPoint(
            date=date(2025, 1, 15),
            hedge_change=Decimal("50"),
            hedged_change=Decimal("60"),
        ),
        EffectivenessTestDataPoint(
            date=date(2025, 1, 31),
            hedge_change=Decimal("80"),
            hedged_change=Decimal("90"),
        ),
    ]


@pytest.fixture
def tester() -> HedgeEffectivenessTester:
    """Fresh HedgeEffectivenessTester instance."""
    return HedgeEffectivenessTester()


# ----------------------------------------------------------------------
# EffectivenessTestError
# ----------------------------------------------------------------------
class TestEffectivenessTestError:
    def test_construction(self):
        err = EffectivenessTestError("Test error")
        assert isinstance(err, ValueError)
        assert str(err) == "Test error"


# ----------------------------------------------------------------------
# EffectivenessTestDataPoint
# ----------------------------------------------------------------------
class TestEffectivenessTestDataPoint:
    def test_construction(self):
        dp = EffectivenessTestDataPoint(
            date=date(2025, 1, 1),
            hedge_change=Decimal("100.50"),
            hedged_change=Decimal("200.25"),
        )
        assert dp.date == date(2025, 1, 1)
        assert dp.hedge_change == Decimal("100.50")
        assert dp.hedged_change == Decimal("200.25")

    def test_to_dict(self):
        dp = EffectivenessTestDataPoint(
            date=date(2025, 2, 15),
            hedge_change=Decimal("75.00"),
            hedged_change=Decimal("125.50"),
        )
        d = dp.to_dict()
        assert d["date"] == "2025-02-15"
        assert d["hedge_change"] == "75.00"
        assert d["hedged_change"] == "125.50"

    def test_from_dict(self):
        data = {
            "date": "2025-03-10",
            "hedge_change": "300.25",
            "hedged_change": "400.75",
        }
        dp = EffectivenessTestDataPoint.from_dict(data)
        assert dp.date == date(2025, 3, 10)
        assert dp.hedge_change == Decimal("300.25")
        assert dp.hedged_change == Decimal("400.75")


# ----------------------------------------------------------------------
# EffectivenessTestResult
# ----------------------------------------------------------------------
class TestEffectivenessTestResult:
    @pytest.fixture
    def test_result(self) -> EffectivenessTestResult:
        dp = EffectivenessTestDataPoint(date.today(), Decimal("100"), Decimal("100"))
        return EffectivenessTestResult(
            test_id=uuid4(),
            hedge_id=uuid4(),
            test_type="prospective",
            test_date=datetime(2025, 1, 1, 12, 0, tzinfo=UTC),
            is_effective=True,
            ratio=Decimal("0.95"),
            variance=Decimal("0.05"),
            cumulative_hedge_change=Decimal("230"),
            cumulative_hedged_change=Decimal("250"),
            threshold_lower=Decimal("0.80"),
            threshold_upper=Decimal("1.25"),
            message="Passed",
            tested_by="alice",
            data_points=[dp],
            created_at=datetime(2025, 1, 1, 12, 0, tzinfo=UTC),
        )

    def test_construction(self, test_result):
        assert test_result.is_effective is True
        assert test_result.ratio == Decimal("0.95")
        assert test_result.message == "Passed"
        assert len(test_result.data_points) == 1

    def test_to_dict(self, test_result):
        d = test_result.to_dict()
        assert d["test_type"] == "prospective"
        assert d["is_effective"] is True
        assert d["ratio"] == "0.95"
        assert "data_points" in d
        assert len(d["data_points"]) == 1


# ----------------------------------------------------------------------
# HedgeEffectivenessTester
# ----------------------------------------------------------------------
class TestHedgeEffectivenessTester:
    def test_calculate_effectiveness_ratio_normal(self, tester):
        hedge = [Decimal("100"), Decimal("50"), Decimal("80")]
        hedged = [Decimal("100"), Decimal("60"), Decimal("90")]
        ratio = tester.calculate_effectiveness_ratio(hedge, hedged)
        # total_hedge = 230, total_hedged = 250 => 0.92
        expected = Decimal("0.92")  # 230/250 = 0.92
        assert ratio == expected

    def test_calculate_effectiveness_ratio_with_negative_changes(self, tester):
        hedge = [Decimal("-100"), Decimal("50")]
        hedged = [Decimal("-100"), Decimal("60")]
        ratio = tester.calculate_effectiveness_ratio(hedge, hedged)
        # absolute sums: 150 / 160 = 0.9375
        expected = Decimal("0.9375")
        assert ratio == expected

    def test_calculate_effectiveness_ratio_empty_lists(self, tester):
        ratio = tester.calculate_effectiveness_ratio([], [])
        assert ratio == Decimal("0")

        ratio = tester.calculate_effectiveness_ratio([Decimal("100")], [])
        # hedged empty => total_hedged = 0 => returns 0
        assert ratio == Decimal("0")

    def test_calculate_effectiveness_ratio_zero_hedged(self, tester):
        hedge = [Decimal("100")]
        hedged = [Decimal("0")]
        ratio = tester.calculate_effectiveness_ratio(hedge, hedged)
        assert ratio == Decimal("0")

    # ------------------------------------------------------------------
    # Prospective Test
    # ------------------------------------------------------------------
    def test_prospective_test_passes(self, tester):
        hedge_id = uuid4()
        result = tester.prospective_test(
            hedge_id=hedge_id,
            expected_hedge_changes=[Decimal("80"), Decimal("90")],
            expected_hedged_changes=[Decimal("100"), Decimal("100")],
            threshold_lower=Decimal("0.80"),
            threshold_upper=Decimal("1.25"),
            tested_by="bob",
        )
        assert result.is_effective is True
        assert result.ratio == Decimal("0.85")  # (80+90)/(100+100) = 170/200 = 0.85
        assert result.test_type == "prospective"
        assert result.hedge_id == hedge_id
        assert "Prospective test passed" in result.message
        assert len(result.data_points) == 2
        assert result.tested_by == "bob"

    def test_prospective_test_fails_ratio_outside_range(self, tester):
        hedge_id = uuid4()
        result = tester.prospective_test(
            hedge_id=hedge_id,
            expected_hedge_changes=[Decimal("200")],
            expected_hedged_changes=[Decimal("100")],
            threshold_lower=Decimal("0.80"),
            threshold_upper=Decimal("1.25"),
        )
        assert result.is_effective is False
        assert result.ratio == Decimal("2.0")
        assert "failed" in result.message.lower()

    def test_prospective_test_zero_hedged(self, tester):
        hedge_id = uuid4()
        result = tester.prospective_test(
            hedge_id=hedge_id,
            expected_hedge_changes=[Decimal("100")],
            expected_hedged_changes=[Decimal("0")],
        )
        assert result.is_effective is False
        assert result.ratio == Decimal("0")
        assert "No change in hedged item" in result.message

    def test_prospective_test_length_mismatch(self, tester):
        with pytest.raises(EffectivenessTestError, match="same length"):
            tester.prospective_test(
                hedge_id=uuid4(),
                expected_hedge_changes=[Decimal("1"), Decimal("2")],
                expected_hedged_changes=[Decimal("1")],
            )

    def test_prospective_test_empty_data(self, tester):
        with pytest.raises(EffectivenessTestError, match="No data points"):
            tester.prospective_test(
                hedge_id=uuid4(),
                expected_hedge_changes=[],
                expected_hedged_changes=[],
            )

    # ------------------------------------------------------------------
    # Retrospective Test
    # ------------------------------------------------------------------
    def test_retrospective_test_with_data_points_objects(self, tester, sample_data_points):
        hedge_id = uuid4()
        result = tester.retrospective_test(
            hedge_id=hedge_id,
            data_points=sample_data_points,
            threshold_lower=Decimal("0.80"),
            threshold_upper=Decimal("1.25"),
            tested_by="carol",
        )
        # cumulative hedge: 100+50+80 = 230, hedged: 100+60+90 = 250, ratio = 0.92
        assert result.is_effective is True
        assert result.ratio == Decimal("0.92")
        assert result.test_type == "retrospective"
        assert len(result.data_points) == 3
        assert result.tested_by == "carol"

    def test_retrospective_test_with_tuples(self, tester):
        hedge_id = uuid4()
        data_tuples = [
            (date(2025, 1, 1), Decimal("100"), Decimal("100")),
            (date(2025, 1, 2), Decimal("50"), Decimal("60")),
        ]
        result = tester.retrospective_test(
            hedge_id=hedge_id,
            data_points=data_tuples,
        )
        assert result.is_effective is True
        assert result.ratio == Decimal("0.9375")  # 150/160

    def test_retrospective_test_zero_hedged(self, tester):
        data = [EffectivenessTestDataPoint(date.today(), Decimal("100"), Decimal("0"))]
        result = tester.retrospective_test(hedge_id=uuid4(), data_points=data)
        assert result.is_effective is False
        assert result.ratio == Decimal("0")
        assert "Zero cumulative change" in result.message

    def test_retrospective_test_empty_data(self, tester):
        with pytest.raises(EffectivenessTestError, match="No data points"):
            tester.retrospective_test(hedge_id=uuid4(), data_points=[])

    # ------------------------------------------------------------------
    # Regression Test
    # ------------------------------------------------------------------
    def test_regression_test_passes(self, tester, sample_data_points):
        hedge_id = uuid4()
        result = tester.regression_test(
            hedge_id=hedge_id,
            data_points=sample_data_points,
            threshold=Decimal("0.80"),
            tested_by="dave",
        )
        # R-squared should be calculated; with these values, should be near 1.0
        assert result.is_effective is True
        assert result.ratio >= Decimal("0.80")
        assert result.test_type == "regression"
        assert result.tested_by == "dave"
        assert "R-squared" in result.message

    def test_regression_test_not_enough_points(self, tester):
        data = [
            EffectivenessTestDataPoint(date.today(), Decimal("1"), Decimal("2")),
            EffectivenessTestDataPoint(date.today(), Decimal("2"), Decimal("3")),
        ]
        with pytest.raises(EffectivenessTestError, match="at least 3 data points"):
            tester.regression_test(hedge_id=uuid4(), data_points=data)

    def test_regression_test_zero_variance(self, tester):
        # All values same -> zero variance
        data = [
            EffectivenessTestDataPoint(date.today(), Decimal("100"), Decimal("100")),
            EffectivenessTestDataPoint(date.today(), Decimal("100"), Decimal("100")),
            EffectivenessTestDataPoint(date.today(), Decimal("100"), Decimal("100")),
        ]
        result = tester.regression_test(hedge_id=uuid4(), data_points=data)
        assert result.is_effective is False
        assert result.ratio == Decimal("0")
        assert "zero variance" in result.message

    # ------------------------------------------------------------------
    # Critical Terms Match Test
    # ------------------------------------------------------------------
    def test_critical_terms_match_all_match(self, tester):
        is_match, msg = tester.critical_terms_match_test(
            hedge_notional=Decimal("1000000"),
            hedged_notional=Decimal("1000000"),
            hedge_currency="USD",
            hedged_currency="USD",
            hedge_maturity=date(2026, 1, 1),
            hedged_maturity=date(2026, 1, 1),
            risk_component="interest rate",
        )
        assert is_match is True
        assert msg == "Critical terms match"

    def test_critical_terms_match_currency_mismatch(self, tester):
        is_match, msg = tester.critical_terms_match_test(
            hedge_notional=Decimal("1000000"),
            hedged_notional=Decimal("1000000"),
            hedge_currency="USD",
            hedged_currency="EUR",
            hedge_maturity=date(2026, 1, 1),
            hedged_maturity=date(2026, 1, 1),
            risk_component="interest rate",
        )
        assert is_match is False
        assert "Currency mismatch" in msg

    def test_critical_terms_match_notional_mismatch(self, tester):
        # Notional difference > 10%
        is_match, msg = tester.critical_terms_match_test(
            hedge_notional=Decimal("1200000"),
            hedged_notional=Decimal("1000000"),
            hedge_currency="USD",
            hedged_currency="USD",
            hedge_maturity=date(2026, 1, 1),
            hedged_maturity=date(2026, 1, 1),
            risk_component="interest rate",
        )
        assert is_match is False
        assert "Notional mismatch" in msg

    def test_critical_terms_match_notional_diff_exact_boundary(self, tester):
        # Difference = 10% exactly, should match
        is_match, msg = tester.critical_terms_match_test(
            hedge_notional=Decimal("1100000"),
            hedged_notional=Decimal("1000000"),
            hedge_currency="USD",
            hedged_currency="USD",
            hedge_maturity=date(2026, 1, 1),
            hedged_maturity=date(2026, 1, 1),
            risk_component="interest rate",
        )
        assert is_match is True

    def test_critical_terms_match_maturity_mismatch_small(self, tester):
        # 15 days diff should be okay (<=30)
        is_match, msg = tester.critical_terms_match_test(
            hedge_notional=Decimal("1000000"),
            hedged_notional=Decimal("1000000"),
            hedge_currency="USD",
            hedged_currency="USD",
            hedge_maturity=date(2026, 1, 1),
            hedged_maturity=date(2026, 1, 16),
            risk_component="interest rate",
        )
        assert is_match is True

    def test_critical_terms_match_maturity_mismatch_large(self, tester):
        # 45 days diff should fail
        is_match, msg = tester.critical_terms_match_test(
            hedge_notional=Decimal("1000000"),
            hedged_notional=Decimal("1000000"),
            hedge_currency="USD",
            hedged_currency="USD",
            hedge_maturity=date(2026, 1, 1),
            hedged_maturity=date(2026, 2, 15),
            risk_component="interest rate",
        )
        assert is_match is False
        assert "Maturity mismatch" in msg

    # ------------------------------------------------------------------
    # Test History Methods
    # ------------------------------------------------------------------
    def test_get_test_history_empty(self, tester):
        history = tester.get_test_history()
        assert history == []

    def test_get_test_history_with_tests(self, tester):
        hedge_id = uuid4()
        # Run tests
        tester.prospective_test(hedge_id, [Decimal("100")], [Decimal("100")])
        tester.retrospective_test(hedge_id, [(date.today(), Decimal("100"), Decimal("100"))])
        history = tester.get_test_history()
        assert len(history) == 2

    def test_get_test_history_filter_by_hedge(self, tester):
        hedge_id1 = uuid4()
        hedge_id2 = uuid4()
        tester.prospective_test(hedge_id1, [Decimal("100")], [Decimal("100")])
        tester.prospective_test(hedge_id2, [Decimal("200")], [Decimal("200")])
        history1 = tester.get_test_history(hedge_id1)
        assert len(history1) == 1
        assert history1[0].hedge_id == hedge_id1
        history2 = tester.get_test_history(hedge_id2)
        assert len(history2) == 1
        assert history2[0].hedge_id == hedge_id2

    def test_get_test_history_limit(self, tester):
        hedge_id = uuid4()
        for _ in range(5):
            tester.prospective_test(hedge_id, [Decimal("100")], [Decimal("100")])
        history = tester.get_test_history(hedge_id, limit=3)
        assert len(history) == 3

    def test_get_last_test(self, tester):
        hedge_id = uuid4()
        assert tester.get_last_test(hedge_id) is None
        result1 = tester.prospective_test(hedge_id, [Decimal("100")], [Decimal("100")])
        result2 = tester.prospective_test(hedge_id, [Decimal("200")], [Decimal("200")])
        last = tester.get_last_test(hedge_id)
        assert last is not None
        assert last.test_id == result2.test_id

    def test_get_summary(self, tester):
        hedge_id = uuid4()
        summary = tester.get_summary()
        assert summary["total_tests"] == 0
        assert summary["effectiveness_rate"] == 0

        # Add a failed test (ratio 2.0 -> outside range)
        tester.prospective_test(hedge_id, [Decimal("200")], [Decimal("100")])
        tester.prospective_test(hedge_id, [Decimal("100")], [Decimal("100")])  # passes
        summary = tester.get_summary()
        assert summary["total_tests"] == 2
        assert summary["effective_count"] == 1
        assert summary["ineffective_count"] == 1
        assert summary["effectiveness_rate"] == 50.0
        assert summary["avg_ratio"] == pytest.approx(1.5)  # (2.0 + 1.0)/2

    def test_clear_history(self, tester):
        hedge_id = uuid4()
        tester.prospective_test(hedge_id, [Decimal("100")], [Decimal("100")])
        assert len(tester.get_test_history()) == 1
        tester.clear_history()
        assert len(tester.get_test_history()) == 0

    # ------------------------------------------------------------------
    # Integration: test stores results in history
    # ------------------------------------------------------------------
    def test_test_stored_in_history(self, tester):
        hedge_id = uuid4()
        result = tester.prospective_test(hedge_id, [Decimal("100")], [Decimal("100")])
        history = tester.get_test_history()
        assert len(history) == 1
        assert history[0].test_id == result.test_id
        assert history[0].hedge_id == hedge_id
        assert history[0].test_type == "prospective"

        # retrospective also stored
        tester.retrospective_test(hedge_id, [(date.today(), Decimal("100"), Decimal("100"))])
        history = tester.get_test_history()
        assert len(history) == 2

    # ------------------------------------------------------------------
    # Decimal precision tests
    # ------------------------------------------------------------------
    def test_decimal_precision_in_ratio(self, tester):
        # Test that ratio is quantized to 4 decimal places
        hedge = [Decimal("100"), Decimal("3")]
        hedged = [Decimal("100"), Decimal("7")]
        # Total: 103 / 107 = 0.96261682... -> quantized 0.9626
        expected = Decimal("0.9626")
        result = tester.calculate_effectiveness_ratio(hedge, hedged)
        assert result == expected

        # Prospective test should also quantize
        hedge_id = uuid4()
        res = tester.prospective_test(
            hedge_id,
            expected_hedge_changes=[Decimal("100"), Decimal("3")],
            expected_hedged_changes=[Decimal("100"), Decimal("7")],
        )
        assert res.ratio == expected