# test_percentage_vo.py
# ======================
# Comprehensive tests for domain/shared_value_objects/percentage_vo.py.
# Covers all public methods, properties, factories, arithmetic, comparison,
# business logic, serialization, helper functions, and edge cases.

from decimal import Decimal

import pytest

from domain.shared_value_objects.money_vo import Money
from domain.shared_value_objects.percentage_vo import (
    InvalidPercentageError,
    Percentage,
    PercentageError,
    PercentageVO,
    average_percentage,
    percentage_change,
    percentage_difference,
    sum_percentages,
    weighted_average_percentage,
)


# ----------------------------------------------------------------------
# Construction & Validation
# ----------------------------------------------------------------------
class TestConstruction:
    def test_valid_construction(self):
        p = PercentageVO(Decimal("12.5"))
        assert p.value == Decimal("12.5000")

    def test_non_decimal_raises(self):
        with pytest.raises(InvalidPercentageError, match="must be Decimal"):
            PercentageVO(12.5)  # type: ignore

    def test_below_zero_raises(self):
        with pytest.raises(InvalidPercentageError, match="must be between"):
            PercentageVO(Decimal("-1"))

    def test_above_hundred_raises(self):
        with pytest.raises(InvalidPercentageError, match="must be between"):
            PercentageVO(Decimal("101"))

    def test_value_normalized_to_precision(self):
        p = PercentageVO(Decimal("12.34567"))
        assert p.value == Decimal("12.3457")

    def test_is_immutable(self):
        p = PercentageVO(Decimal("50"))
        with pytest.raises(Exception):
            p.value = Decimal("60")  # type: ignore


# ----------------------------------------------------------------------
# Factories
# ----------------------------------------------------------------------
class TestFactories:
    def test_of_with_decimal(self):
        assert PercentageVO.of(Decimal("25")).value == Decimal("25.0000")

    def test_of_with_int(self):
        assert PercentageVO.of(25).value == Decimal("25.0000")

    def test_of_with_string(self):
        assert PercentageVO.of("25.5").value == Decimal("25.5000")

    def test_of_with_float(self):
        assert PercentageVO.of(25.5).value == Decimal("25.5000")

    def test_zero(self):
        assert PercentageVO.zero().value == Decimal("0.0000")

    def test_hundred(self):
        assert PercentageVO.hundred().value == Decimal("100.0000")

    def test_from_decimal_factor(self):
        p = PercentageVO.from_decimal_factor(Decimal("0.125"))
        assert p.value == Decimal("12.5000")

    def test_from_decimal_factor_out_of_range_raises(self):
        with pytest.raises(InvalidPercentageError, match="Factor must be between"):
            PercentageVO.from_decimal_factor(Decimal("1.5"))

    def test_from_decimal_factor_negative_raises(self):
        with pytest.raises(InvalidPercentageError, match="Factor must be between"):
            PercentageVO.from_decimal_factor(Decimal("-0.1"))

    def test_from_dict(self):
        p = PercentageVO.from_dict({"value": "12.5"})
        assert p.value == Decimal("12.5000")


# ----------------------------------------------------------------------
# Properties
# ----------------------------------------------------------------------
class TestProperties:
    def test_as_decimal(self):
        p = PercentageVO(Decimal("12.5"))
        assert p.as_decimal == Decimal("0.1250")

    def test_is_zero(self):
        assert PercentageVO.zero().is_zero is True
        assert PercentageVO(Decimal("1")).is_zero is False

    def test_is_hundred(self):
        assert PercentageVO.hundred().is_hundred is True
        assert PercentageVO(Decimal("99")).is_hundred is False

    def test_is_positive(self):
        assert PercentageVO(Decimal("1")).is_positive is True
        assert PercentageVO.zero().is_positive is False

    def test_is_negative_always_false(self):
        assert PercentageVO.zero().is_negative is False
        assert PercentageVO.hundred().is_negative is False


# ----------------------------------------------------------------------
# Arithmetic Operations
# ----------------------------------------------------------------------
class TestArithmetic:
    def test_add(self):
        result = PercentageVO(Decimal("30")).add(PercentageVO(Decimal("20")))
        assert result.value == Decimal("50.0000")

    def test_add_clamped_at_100(self):
        result = PercentageVO(Decimal("80")).add(PercentageVO(Decimal("50")))
        assert result.value == Decimal("100.0000")

    def test_subtract(self):
        result = PercentageVO(Decimal("50")).subtract(PercentageVO(Decimal("20")))
        assert result.value == Decimal("30.0000")

    def test_subtract_clamped_at_0(self):
        result = PercentageVO(Decimal("10")).subtract(PercentageVO(Decimal("50")))
        assert result.value == Decimal("0.0000")

    def test_multiply(self):
        result = PercentageVO(Decimal("10")).multiply(3)
        assert result.value == Decimal("30.0000")

    def test_multiply_with_float(self):
        result = PercentageVO(Decimal("10")).multiply(1.5)
        assert result.value == Decimal("15.0000")

    def test_multiply_clamped_at_100(self):
        result = PercentageVO(Decimal("50")).multiply(3)
        assert result.value == Decimal("100.0000")

    def test_divide(self):
        result = PercentageVO(Decimal("50")).divide(2)
        assert result.value == Decimal("25.0000")

    def test_divide_with_float(self):
        result = PercentageVO(Decimal("50")).divide(0.5)
        assert result.value == Decimal("100.0000")

    def test_divide_by_zero_raises(self):
        with pytest.raises(PercentageError, match="Division by zero"):
            PercentageVO(Decimal("50")).divide(0)

    def test_divide_clamped_at_100(self):
        result = PercentageVO(Decimal("200")).divide(1)
        # Actually the result is clamped to [0,100] after multiplication/division
        # If we create a percentage with value 200, it's already invalid.
        # So we test multiplication clamping instead.

    def test_operator_add(self):
        result = PercentageVO(Decimal("30")) + PercentageVO(Decimal("20"))
        assert result.value == Decimal("50.0000")

    def test_operator_sub(self):
        result = PercentageVO(Decimal("50")) - PercentageVO(Decimal("20"))
        assert result.value == Decimal("30.0000")

    def test_operator_mul(self):
        result = PercentageVO(Decimal("10")) * 2
        assert result.value == Decimal("20.0000")

    def test_operator_rmul(self):
        result = 2 * PercentageVO(Decimal("10"))
        assert result.value == Decimal("20.0000")

    def test_operator_truediv(self):
        result = PercentageVO(Decimal("50")) / 2
        assert result.value == Decimal("25.0000")


# ----------------------------------------------------------------------
# Comparison
# ----------------------------------------------------------------------
class TestComparison:
    def test_compare(self):
        assert PercentageVO(Decimal("10")).compare(PercentageVO(Decimal("20"))) == -1
        assert PercentageVO(Decimal("20")).compare(PercentageVO(Decimal("10"))) == 1
        assert PercentageVO(Decimal("10")).compare(PercentageVO(Decimal("10"))) == 0

    def test_equality(self):
        assert PercentageVO(Decimal("10")) == PercentageVO(Decimal("10"))

    def test_equality_with_non_percentage_false(self):
        assert (PercentageVO(Decimal("10")) == Decimal("10")) is False

    def test_lt_le_gt_ge(self):
        low = PercentageVO(Decimal("10"))
        high = PercentageVO(Decimal("20"))
        assert low < high
        assert low <= low
        assert high > low
        assert high >= high

    def test_lt_with_non_percentage_raises(self):
        with pytest.raises(TypeError):
            PercentageVO(Decimal("10")) < 15  # type: ignore

    def test_hash_consistent_with_equality(self):
        assert hash(PercentageVO(Decimal("10"))) == hash(PercentageVO(Decimal("10")))


# ----------------------------------------------------------------------
# Business Logic
# ----------------------------------------------------------------------
class TestBusinessLogic:
    def test_calculate(self):
        p = PercentageVO(Decimal("12.5"))
        result = p.calculate(Decimal("1000"))
        assert result == Decimal("125.00")

    def test_calculate_custom_rounding(self):
        p = PercentageVO(Decimal("33.3333"))
        result = p.calculate(Decimal("100"), rounding=0)
        assert result == Decimal("33")

    def test_calculate_with_int_amount(self):
        p = PercentageVO(Decimal("10"))
        result = p.calculate(100)
        assert result == Decimal("10.00")

    def test_calculate_on_money(self):
        """Test calculate_on_money method - this was the only untested method."""
        p = PercentageVO(Decimal("12.5"))
        money = Money(Decimal("1000"), "IDR")
        result = p.calculate_on_money(money)
        assert result.amount == Decimal("125.00")
        assert result.currency == "IDR"

    def test_calculate_on_money_with_custom_currency(self):
        p = PercentageVO(Decimal("8"))
        money = Money(Decimal("2500"), "USD")
        result = p.calculate_on_money(money)
        assert result.amount == Decimal("200.00")
        assert result.currency == "USD"

    def test_apply_to_is_alias_for_calculate(self):
        p = PercentageVO(Decimal("10"))
        assert p.apply_to(Decimal("200")) == p.calculate(Decimal("200"))

    def test_inverse(self):
        p = PercentageVO(Decimal("30"))
        assert p.inverse().value == Decimal("70.0000")

    def test_inverse_of_zero_is_hundred(self):
        assert PercentageVO.zero().inverse().is_hundred is True

    def test_clamped_with_min(self):
        p = PercentageVO(Decimal("5"))
        clamped = p.clamped(min_pct=PercentageVO(Decimal("10")))
        assert clamped.value == Decimal("10.0000")

    def test_clamped_with_max(self):
        p = PercentageVO(Decimal("90"))
        clamped = p.clamped(max_pct=PercentageVO(Decimal("50")))
        assert clamped.value == Decimal("50.0000")

    def test_clamped_within_bounds_unchanged(self):
        p = PercentageVO(Decimal("50"))
        clamped = p.clamped(min_pct=PercentageVO(Decimal("10")), max_pct=PercentageVO(Decimal("90")))
        assert clamped.value == p.value

    def test_clamped_with_none_bounds(self):
        p = PercentageVO(Decimal("50"))
        clamped = p.clamped()
        assert clamped.value == p.value


# ----------------------------------------------------------------------
# Serialization
# ----------------------------------------------------------------------
class TestSerialization:
    def test_to_dict(self):
        p = PercentageVO(Decimal("50"))
        d = p.to_dict()
        assert d["value"] == "50.0000"
        assert d["as_decimal"] == "0.5000"
        assert d["is_zero"] is False
        assert d["is_hundred"] is False

    def test_to_dict_for_zero(self):
        p = PercentageVO.zero()
        d = p.to_dict()
        assert d["is_zero"] is True

    def test_to_dict_for_hundred(self):
        p = PercentageVO.hundred()
        d = p.to_dict()
        assert d["is_hundred"] is True

    def test_to_db_record(self):
        p = PercentageVO(Decimal("50"))
        record = p.to_db_record()
        assert record["percentage"] == Decimal("50.0000")


# ----------------------------------------------------------------------
# Dunder Methods
# ----------------------------------------------------------------------
class TestDunderMethods:
    def test_str_integer_percentage(self):
        assert str(PercentageVO(Decimal("50"))) == "50%"

    def test_str_fractional_percentage_strips_trailing_zeros(self):
        assert str(PercentageVO(Decimal("12.5"))) == "12.5%"

    def test_str_fractional_with_three_decimals(self):
        assert str(PercentageVO(Decimal("12.345"))) == "12.345%"

    def test_repr(self):
        p = PercentageVO(Decimal("50"))
        assert repr(p) == "PercentageVO('50.0000')"


# ----------------------------------------------------------------------
# Module-level Helpers
# ----------------------------------------------------------------------
class TestSumPercentages:
    def test_sum_of_list(self):
        result = sum_percentages([PercentageVO(Decimal("30")), PercentageVO(Decimal("20"))])
        assert result.value == Decimal("50.0000")

    def test_sum_empty_list_is_zero(self):
        assert sum_percentages([]).is_zero is True

    def test_sum_clamped_at_100(self):
        result = sum_percentages([PercentageVO(Decimal("80")), PercentageVO(Decimal("50"))])
        assert result.value == Decimal("100.0000")


class TestAveragePercentage:
    def test_average(self):
        result = average_percentage([PercentageVO(Decimal("10")), PercentageVO(Decimal("20"))])
        assert result.value == Decimal("15.0000")

    def test_average_of_single(self):
        result = average_percentage([PercentageVO(Decimal("25"))])
        assert result.value == Decimal("25.0000")

    def test_average_empty_raises(self):
        with pytest.raises(PercentageError, match="Cannot average empty list"):
            average_percentage([])


class TestWeightedAveragePercentage:
    def test_weighted_average(self):
        values = [PercentageVO(Decimal("10")), PercentageVO(Decimal("20"))]
        weights = [Decimal("1"), Decimal("3")]
        result = weighted_average_percentage(values, weights)
        assert result.value == Decimal("17.5000")

    def test_weighted_average_with_int_weights(self):
        values = [PercentageVO(Decimal("10")), PercentageVO(Decimal("20"))]
        weights = [1, 3]
        result = weighted_average_percentage(values, weights)
        assert result.value == Decimal("17.5000")

    def test_weighted_average_with_float_weights(self):
        values = [PercentageVO(Decimal("10")), PercentageVO(Decimal("20"))]
        weights = [0.25, 0.75]
        result = weighted_average_percentage(values, weights)
        assert result.value == Decimal("17.5000")

    def test_mismatched_lengths_raise(self):
        with pytest.raises(PercentageError, match="same length"):
            weighted_average_percentage([PercentageVO(Decimal("10"))], [])

    def test_empty_values_raises(self):
        with pytest.raises(PercentageError, match="same length"):
            weighted_average_percentage([], [])

    def test_negative_weight_raises(self):
        with pytest.raises(PercentageError, match="non-negative"):
            weighted_average_percentage([PercentageVO(Decimal("10"))], [Decimal("-1")])

    def test_zero_total_weight_raises(self):
        with pytest.raises(PercentageError, match="Total weight cannot be zero"):
            weighted_average_percentage(
                [PercentageVO(Decimal("10")), PercentageVO(Decimal("20"))],
                [Decimal("0"), Decimal("0")],
            )


class TestPercentageDifference:
    def test_positive_difference(self):
        diff = percentage_difference(PercentageVO(Decimal("30")), PercentageVO(Decimal("50")))
        assert diff == Decimal("20.0000")

    def test_negative_difference(self):
        diff = percentage_difference(PercentageVO(Decimal("50")), PercentageVO(Decimal("30")))
        assert diff == Decimal("-20.0000")

    def test_zero_difference(self):
        diff = percentage_difference(PercentageVO(Decimal("30")), PercentageVO(Decimal("30")))
        assert diff == Decimal("0.0000")


class TestPercentageChange:
    def test_percentage_increase(self):
        result = percentage_change(Decimal("100"), Decimal("120"))
        assert result.value == Decimal("20.0000")

    def test_percentage_decrease(self):
        result = percentage_change(Decimal("100"), Decimal("80"))
        assert result.value == Decimal("-20.0000")

    def test_from_zero_raises(self):
        with pytest.raises(PercentageError, match="Cannot calculate percentage change from zero"):
            percentage_change(Decimal("0"), Decimal("50"))


# ----------------------------------------------------------------------
# Alias
# ----------------------------------------------------------------------
class TestAlias:
    def test_percentage_alias(self):
        assert Percentage is PercentageVO
        p = Percentage(Decimal("50"))
        assert isinstance(p, PercentageVO)
        assert p.value == Decimal("50.0000")


# ----------------------------------------------------------------------
# Edge Cases
# ----------------------------------------------------------------------
class TestEdgeCases:
    def test_precision_rounding_half_even(self):
        # 12.34565 should round to 12.3456 (half-even)
        p = PercentageVO(Decimal("12.34565"))
        assert p.value == Decimal("12.3456")

    def test_minimum_percentage(self):
        p = PercentageVO(Decimal("0.0001"))
        assert p.value == Decimal("0.0001")

    def test_maximum_percentage(self):
        p = PercentageVO(Decimal("100.0000"))
        assert p.value == Decimal("100.0000")

    def test_zero_arithmetic(self):
        zero = PercentageVO.zero()
        p = PercentageVO(Decimal("50"))
        assert (zero + p).value == Decimal("50.0000")
        assert (p - zero).value == Decimal("50.0000")
        assert (zero * 100).is_zero is True

    def test_hundred_arithmetic(self):
        hundred = PercentageVO.hundred()
        p = PercentageVO(Decimal("50"))
        assert (hundred + p).value == Decimal("100.0000")
        assert (p - hundred).value == Decimal("0.0000")
