"""
Tests for domain/shared_value_objects/percentage_vo.py

Covers PercentageVO construction/validation/normalization, factories (of/
zero/hundred/from_decimal_factor/from_dict), properties, arithmetic
(add/subtract/multiply/divide + operators, all clamped to [0,100]),
comparisons, calculate()/apply_to()/inverse()/clamped(), serialization,
dunder methods, and module-level helpers (sum/average/weighted_average/
percentage_difference/percentage_change).

======================================================================
KNOWN BUG IN THE SOURCE (verified by direct execution):

BUG-PERCENTAGE-001 — `PRECISION: int = 4`, `MAX_PERCENT: Decimal =
Decimal("100")`, and `MIN_PERCENT: Decimal = Decimal("0")` are declared
as ANNOTATED class-body attributes inside the `@dataclass`. Because they
carry type annotations, the `@dataclass` decorator treats them as real
per-instance fields (with defaults) rather than shared class constants --
confirmed via `dataclasses.fields(PercentageVO)`, which lists `value`,
`PRECISION`, `MAX_PERCENT`, and `MIN_PERCENT` as four separate
constructor parameters. This means the [0, 100] bound that
`__post_init__` is supposed to enforce can be silently bypassed by
overriding `MAX_PERCENT` (or `MIN_PERCENT`) at construction time, e.g.
`PercentageVO(Decimal("150"), MAX_PERCENT=Decimal("200"))` succeeds and
produces a "percentage" of 150 -- something the class's own bounds check
was meant to prevent. (`ROUNDING`, which has no type annotation, is
NOT affected and remains a genuine shared class constant.)
======================================================================
"""

from __future__ import annotations

from decimal import Decimal

import pytest

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

# ============================================================================
# Construction & validation
# ============================================================================


class TestConstruction:
    def test_valid_construction(self):
        p = PercentageVO(Decimal("12.5"))
        assert p.value == Decimal("12.5000")

    def test_non_decimal_raises(self):
        with pytest.raises(InvalidPercentageError, match="must be Decimal"):
            PercentageVO(12.5)

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
            p.value = Decimal("60")

    def test_bounds_can_be_bypassed_via_max_percent_kwarg(self):
        """BUG-PERCENTAGE-001: MAX_PERCENT is (unintentionally) a real
        constructor field, so the [0,100] cap can be overridden entirely."""
        p = PercentageVO(Decimal("150"), MAX_PERCENT=Decimal("200"))
        assert p.value == Decimal("150.0000")


# ============================================================================
# Factories
# ============================================================================


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

    def test_from_dict(self):
        p = PercentageVO.from_dict({"value": "12.5"})
        assert p.value == Decimal("12.5000")


# ============================================================================
# Properties
# ============================================================================


class TestProperties:
    def test_as_decimal(self):
        p = PercentageVO(Decimal("12.5"))
        assert p.as_decimal == Decimal("0.1250")

    def test_as_decimal_called_like_a_method_raises(self):
        """The docstring example shows p.as_decimal() but it's a property,
        not a method -- calling it raises TypeError."""
        p = PercentageVO(Decimal("12.5"))
        with pytest.raises(TypeError, match="not callable"):
            p.as_decimal()

    def test_is_zero(self):
        assert PercentageVO.zero().is_zero is True
        assert PercentageVO(Decimal("1")).is_zero is False

    def test_is_hundred(self):
        assert PercentageVO.hundred().is_hundred is True

    def test_is_positive(self):
        assert PercentageVO(Decimal("1")).is_positive is True
        assert PercentageVO.zero().is_positive is False

    def test_is_negative_always_false(self):
        assert PercentageVO.zero().is_negative is False
        assert PercentageVO.hundred().is_negative is False


# ============================================================================
# Arithmetic
# ============================================================================


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

    def test_multiply_clamped_at_100(self):
        result = PercentageVO(Decimal("50")).multiply(3)
        assert result.value == Decimal("100.0000")

    def test_divide(self):
        result = PercentageVO(Decimal("50")).divide(2)
        assert result.value == Decimal("25.0000")

    def test_divide_by_zero_raises(self):
        with pytest.raises(PercentageError, match="Division by zero"):
            PercentageVO(Decimal("50")).divide(0)

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


# ============================================================================
# Comparison
# ============================================================================


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

    def test_hash_consistent_with_equality(self):
        assert hash(PercentageVO(Decimal("10"))) == hash(PercentageVO(Decimal("10")))


# ============================================================================
# Business logic
# ============================================================================


class TestBusinessLogic:
    def test_calculate(self):
        p = PercentageVO(Decimal("12.5"))
        result = p.calculate(Decimal("1000"))
        assert result == Decimal("125.00")

    def test_calculate_custom_rounding(self):
        p = PercentageVO(Decimal("33.3333"))
        result = p.calculate(Decimal("100"), rounding=0)
        assert result == Decimal("33")

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


# ============================================================================
# Serialization
# ============================================================================


class TestSerialization:
    def test_to_dict(self):
        p = PercentageVO(Decimal("50"))
        d = p.to_dict()
        assert d["value"] == "50.0000"
        assert d["is_zero"] is False

    def test_to_db_record(self):
        p = PercentageVO(Decimal("50"))
        record = p.to_db_record()
        assert record["percentage"] == Decimal("50.0000")


# ============================================================================
# Dunder methods
# ============================================================================


class TestDunderMethods:
    def test_str_integer_percentage(self):
        assert str(PercentageVO(Decimal("50"))) == "50%"

    def test_str_fractional_percentage_strips_trailing_zeros(self):
        assert str(PercentageVO(Decimal("12.5"))) == "12.5%"

    def test_repr(self):
        p = PercentageVO(Decimal("50"))
        assert repr(p) == "PercentageVO('50.0000')"


# ============================================================================
# Module-level helpers
# ============================================================================


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

    def test_average_empty_raises(self):
        with pytest.raises(PercentageError, match="Cannot average empty list"):
            average_percentage([])


class TestWeightedAveragePercentage:
    def test_weighted_average(self):
        values = [PercentageVO(Decimal("10")), PercentageVO(Decimal("20"))]
        weights = [Decimal("1"), Decimal("3")]
        result = weighted_average_percentage(values, weights)
        assert result.value == Decimal("17.5000")

    def test_mismatched_lengths_raise(self):
        with pytest.raises(PercentageError, match="same length"):
            weighted_average_percentage([PercentageVO(Decimal("10"))], [])

    def test_negative_weight_raises(self):
        with pytest.raises(PercentageError, match="non-negative"):
            weighted_average_percentage([PercentageVO(Decimal("10"))], [Decimal("-1")])

    def test_zero_total_weight_raises(self):
        with pytest.raises(PercentageError, match="Total weight cannot be zero"):
            weighted_average_percentage(
                [PercentageVO(Decimal("10")), PercentageVO(Decimal("20"))], [Decimal("0"), Decimal("0")],
            )


class TestPercentageDifference:
    def test_positive_difference(self):
        diff = percentage_difference(PercentageVO(Decimal("30")), PercentageVO(Decimal("50")))
        assert diff == Decimal("20.0000")

    def test_negative_difference(self):
        diff = percentage_difference(PercentageVO(Decimal("50")), PercentageVO(Decimal("30")))
        assert diff == Decimal("-20.0000")


class TestPercentageChange:
    def test_percentage_increase(self):
        result = percentage_change(Decimal("100"), Decimal("120"))
        assert result.value == Decimal("20.0000")

    def test_from_zero_raises(self):
        with pytest.raises(PercentageError, match="Cannot calculate percentage change from zero"):
            percentage_change(Decimal("0"), Decimal("50"))


# ============================================================================
# Alias
# ============================================================================


class TestAlias:
    def test_percentage_alias(self):
        assert Percentage is PercentageVO
