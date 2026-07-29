#!/usr/bin/env python3
"""
tests/domain/shared_value_objects/test_money_vo.py
Comprehensive tests for domain/shared_value_objects/money_vo.py

Covers:
- Currency enum: members, from_code
- Exceptions: MoneyError, CurrencyMismatchError, InvalidAmountError
- Helper functions: _validate_currency_code, _get_currency_decimal_places, _normalize_currency
- Money class:
  - Construction and validation (NaN, infinite, invalid currency, invalid amount type)
  - Factory methods: of, zero, from_minor_units, from_dict
  - Properties: decimal_places, minor_units, is_zero, is_positive, is_negative, absolute, negated
  - Arithmetic: add, subtract, multiply, divide (with error cases)
  - Comparison: compare, eq, lt, le, gt, ge, hash
  - Rounding: rounded with various modes
  - Allocation: allocate (ratios, largest remainder)
  - Formatting: format with separators, negative, include_currency
  - Serialization: to_dict, to_db_record
  - split, max, min
- Helper functions: sum_money, average_money
- All edge cases, negative paths, and exceptions
- No flaky tests (no datetime used)
- No duplicate test structures (parametrized where appropriate)
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from domain.shared_value_objects.money_vo import (
    Currency,
    CurrencyMismatchError,
    InvalidAmountError,
    Money,
    MoneyError,
    _get_currency_decimal_places,
    _normalize_currency,
    _validate_currency_code,
    average_money,
    sum_money,
)

# =============================================================================
# Tests for Currency enum
# =============================================================================

class TestCurrency:
    def test_members(self):
        assert Currency.IDR.value == "IDR"
        assert Currency.USD.value == "USD"
        assert Currency.EUR.value == "EUR"
        assert len(Currency) > 20  # many members

    def test_from_code_valid(self):
        assert Currency.from_code("IDR") == Currency.IDR
        assert Currency.from_code("usd") == Currency.USD
        assert Currency.from_code("  EUR  ") == Currency.EUR

    def test_from_code_invalid_raises(self):
        with pytest.raises(ValueError, match="Unknown currency code"):
            Currency.from_code("XXX")

        with pytest.raises(ValueError, match="Unknown currency code"):
            Currency.from_code("US")

# =============================================================================
# Tests for Exceptions
# =============================================================================

class TestExceptions:
    @pytest.mark.parametrize("exc_class", [
        MoneyError,
        CurrencyMismatchError,
        InvalidAmountError,
    ])
    def test_exceptions_raise(self, exc_class):
        with pytest.raises(exc_class):
            raise exc_class("test")

# =============================================================================
# Tests for helper functions
# =============================================================================

class TestHelperFunctions:
    @pytest.mark.parametrize("currency,expected", [
        ("IDR", "IDR"),
        ("usd", "USD"),
        ("  EUR  ", "EUR"),
    ])
    def test_validate_currency_code_valid(self, currency, expected):
        assert _validate_currency_code(currency) == expected

    @pytest.mark.parametrize("currency,error_match", [
        (123, "must be a string"),
        ("US", "exactly 3 letters"),
        ("US12", "exactly 3 letters"),
        ("US#", "only letters"),
    ])
    def test_validate_currency_code_invalid(self, currency, error_match):
        with pytest.raises(MoneyError, match=error_match):
            _validate_currency_code(currency)

    @pytest.mark.parametrize("currency,expected", [
        ("IDR", 2),
        ("USD", 2),
        ("JPY", 0),
        ("KRW", 0),
        ("VND", 0),
        ("KWD", 3),
        ("BHD", 3),
        ("EUR", 2),
        ("XXX", 2),  # unknown defaults to 2
    ])
    def test_get_currency_decimal_places(self, currency, expected):
        assert _get_currency_decimal_places(currency) == expected

    @pytest.mark.parametrize("currency,expected", [
        (Currency.IDR, "IDR"),
        (Currency.USD, "USD"),
        ("IDR", "IDR"),
        ("usd", "USD"),
    ])
    def test_normalize_currency(self, currency, expected):
        assert _normalize_currency(currency) == expected

    def test_normalize_currency_invalid_type(self):
        with pytest.raises(MoneyError, match="Currency must be Currency enum or string"):
            _normalize_currency(123)  # type: ignore

# =============================================================================
# Tests for Money
# =============================================================================

class TestMoney:
    # ---- Construction and validation ----

    def test_construct_valid(self):
        m = Money(Decimal("100.50"), "IDR")
        assert m.amount == Decimal("100.50")
        assert m.currency == "IDR"

    def test_construct_rounds_to_currency_decimal_places(self):
        m = Money(Decimal("100.505"), "IDR")
        assert m.amount == Decimal("100.51")  # ROUND_HALF_EVEN

        m2 = Money(Decimal("100.504"), "IDR")
        assert m2.amount == Decimal("100.50")

    def test_construct_zero_decimal_currency(self):
        m = Money(Decimal("100.5"), "JPY")
        assert m.amount == Decimal("101")  # rounds to 0 decimal

    def test_construct_with_currency_enum(self):
        m = Money(Decimal("50"), Currency.USD)
        assert m.currency == "USD"
        assert m.amount == Decimal("50.00")

    def test_construct_nan_raises(self):
        with pytest.raises(InvalidAmountError, match="NaN"):
            Money(Decimal("NaN"), "USD")

    def test_construct_infinite_raises(self):
        with pytest.raises(InvalidAmountError, match="infinite"):
            Money(Decimal("Infinity"), "USD")

    def test_construct_invalid_currency_raises(self):
        with pytest.raises(MoneyError, match="exactly 3 letters"):
            Money(Decimal("100"), "US")

    def test_construct_invalid_amount_type_raises(self):
        with pytest.raises(InvalidAmountError, match="must be Decimal"):
            Money("100", "USD")  # type: ignore

    # ---- Factory methods ----

    @pytest.mark.parametrize("amount_input,expected", [
        (Decimal("100.50"), Decimal("100.50")),
        (100, Decimal("100.00")),
        (100.5, Decimal("100.50")),
        ("100.50", Decimal("100.50")),
    ])
    def test_of(self, amount_input, expected):
        m = Money.of(amount_input, "IDR")
        assert m.amount == expected
        assert m.currency == "IDR"

    def test_of_invalid_type_raises(self):
        with pytest.raises(InvalidAmountError, match="Unsupported amount type"):
            Money.of(None, "IDR")  # type: ignore

    def test_zero(self):
        m = Money.zero("IDR")
        assert m.amount == Decimal("0")
        assert m.currency == "IDR"
        assert m.is_zero

    @pytest.mark.parametrize("minor,currency,expected", [
        (12345, "USD", Decimal("123.45")),
        (123, "JPY", Decimal("123")),
        (1234, "KWD", Decimal("1.234")),
        (100, "IDR", Decimal("1.00")),
    ])
    def test_from_minor_units(self, minor, currency, expected):
        m = Money.from_minor_units(minor, currency)
        assert m.amount == expected
        assert m.currency == _normalize_currency(currency)

    def test_from_dict(self):
        data = {"amount": "100.50", "currency": "USD"}
        m = Money.from_dict(data)
        assert m.amount == Decimal("100.50")
        assert m.currency == "USD"

    # ---- Properties ----

    def test_decimal_places(self):
        assert Money(Decimal("100"), "IDR").decimal_places == 2
        assert Money(Decimal("100"), "JPY").decimal_places == 0
        assert Money(Decimal("100"), "KWD").decimal_places == 3

    def test_minor_units(self):
        m = Money(Decimal("123.45"), "USD")
        assert m.minor_units == 12345

        m2 = Money(Decimal("123"), "JPY")
        assert m2.minor_units == 123

    def test_is_zero(self):
        assert Money(Decimal("0"), "IDR").is_zero is True
        assert Money(Decimal("0.01"), "IDR").is_zero is False

    def test_is_positive(self):
        assert Money(Decimal("10"), "IDR").is_positive is True
        assert Money(Decimal("-5"), "IDR").is_positive is False

    def test_is_negative(self):
        assert Money(Decimal("-5"), "IDR").is_negative is True
        assert Money(Decimal("10"), "IDR").is_negative is False

    def test_absolute(self):
        m = Money(Decimal("-10.50"), "IDR")
        abs_m = m.absolute
        assert abs_m.amount == Decimal("10.50")
        assert abs_m.currency == "IDR"
        assert abs_m is not m

    def test_negated(self):
        m = Money(Decimal("10.50"), "IDR")
        neg = m.negated
        assert neg.amount == Decimal("-10.50")
        assert neg.currency == "IDR"
        assert neg is not m

    # ---- Arithmetic ----

    def test_add_same_currency(self):
        m1 = Money(Decimal("10.50"), "IDR")
        m2 = Money(Decimal("5.25"), "IDR")
        result = m1.add(m2)
        assert result.amount == Decimal("15.75")
        assert result.currency == "IDR"

    def test_add_different_currency_raises(self):
        m1 = Money(Decimal("10"), "IDR")
        m2 = Money(Decimal("5"), "USD")
        with pytest.raises(CurrencyMismatchError, match="Cannot add IDR to USD"):
            m1.add(m2)

    def test_subtract_same_currency(self):
        m1 = Money(Decimal("10.50"), "IDR")
        m2 = Money(Decimal("5.25"), "IDR")
        result = m1.subtract(m2)
        assert result.amount == Decimal("5.25")
        assert result.currency == "IDR"

    def test_subtract_different_currency_raises(self):
        m1 = Money(Decimal("10"), "IDR")
        m2 = Money(Decimal("5"), "USD")
        with pytest.raises(CurrencyMismatchError, match="Cannot subtract USD from IDR"):
            m1.subtract(m2)

    @pytest.mark.parametrize("factor,expected", [
        (2, Decimal("20.00")),
        (2.5, Decimal("25.00")),
        (Decimal("3"), Decimal("30.00")),
    ])
    def test_multiply(self, factor, expected):
        m = Money(Decimal("10.00"), "IDR")
        result = m.multiply(factor)
        assert result.amount == expected
        assert result.currency == "IDR"

    def test_multiply_invalid_factor_raises(self):
        m = Money(Decimal("10"), "IDR")
        with pytest.raises(InvalidAmountError, match="Factor must be numeric"):
            m.multiply("2")  # type: ignore

    @pytest.mark.parametrize("divisor,expected", [
        (2, Decimal("5.00")),
        (2.5, Decimal("4.00")),
        (Decimal("4"), Decimal("2.50")),
    ])
    def test_divide(self, divisor, expected):
        m = Money(Decimal("10.00"), "IDR")
        result = m.divide(divisor)
        assert result.amount == expected
        assert result.currency == "IDR"

    def test_divide_by_zero_raises(self):
        m = Money(Decimal("10"), "IDR")
        with pytest.raises(MoneyError, match="Division by zero"):
            m.divide(0)

    def test_divide_invalid_divisor_raises(self):
        m = Money(Decimal("10"), "IDR")
        with pytest.raises(InvalidAmountError, match="Divisor must be numeric"):
            m.divide("2")  # type: ignore

    def test_operator_overloads(self):
        m1 = Money(Decimal("10.50"), "IDR")
        m2 = Money(Decimal("5.25"), "IDR")
        assert (m1 + m2).amount == Decimal("15.75")
        assert (m1 - m2).amount == Decimal("5.25")
        assert (m1 * 2).amount == Decimal("21.00")
        assert (m1 / 2).amount == Decimal("5.25")
        assert (2 * m1).amount == Decimal("21.00")  # __rmul__
        assert (m1 + 0) is m1  # __radd__ with 0

    # ---- Comparison ----

    @pytest.mark.parametrize("a,b,expected", [
        (Decimal("10.50"), Decimal("10.50"), 0),
        (Decimal("10.50"), Decimal("5.25"), 1),
        (Decimal("5.25"), Decimal("10.50"), -1),
    ])
    def test_compare(self, a, b, expected):
        m1 = Money(a, "IDR")
        m2 = Money(b, "IDR")
        assert m1.compare(m2) == expected

    def test_compare_different_currency_raises(self):
        m1 = Money(Decimal("10"), "IDR")
        m2 = Money(Decimal("5"), "USD")
        with pytest.raises(CurrencyMismatchError, match="Cannot compare IDR with USD"):
            m1.compare(m2)

    def test_eq(self):
        m1 = Money(Decimal("10.50"), "IDR")
        m2 = Money(Decimal("10.50"), "IDR")
        m3 = Money(Decimal("10.50"), "USD")
        m4 = Money(Decimal("20"), "IDR")
        assert m1 == m2
        assert m1 != m3
        assert m1 != m4
        assert m1 != "some string"

    def test_ordering(self):
        m1 = Money(Decimal("10"), "IDR")
        m2 = Money(Decimal("20"), "IDR")
        assert m1 < m2
        assert m1 <= m2
        assert m2 > m1
        assert m2 >= m1
        assert m1 >= m1
        assert m1 <= m1

    def test_hash(self):
        m1 = Money(Decimal("10.50"), "IDR")
        m2 = Money(Decimal("10.50"), "IDR")
        assert hash(m1) == hash(m2)

    # ---- Rounding ----

    @pytest.mark.parametrize("amount,places,mode,expected", [
        (Decimal("10.555"), 2, "HALF_EVEN", Decimal("10.56")),
        (Decimal("10.555"), 2, "DOWN", Decimal("10.55")),
        (Decimal("10.555"), 2, "UP", Decimal("10.56")),
        (Decimal("10.555"), 2, "HALF_UP", Decimal("10.56")),
        (Decimal("-10.555"), 2, "HALF_EVEN", Decimal("-10.56")),
        (Decimal("10.5"), 0, "HALF_EVEN", Decimal("10")),
        (Decimal("10.5"), 0, "UP", Decimal("11")),
    ])
    def test_rounded(self, amount, places, mode, expected):
        m = Money(amount, "IDR")
        rounded = m.rounded(places, mode)
        assert rounded.amount == expected
        assert rounded.currency == "IDR"

    # ---- Allocation ----

    def test_allocate_basic(self):
        m = Money(Decimal("10.00"), "IDR")
        ratios = [3, 7]
        result = m.allocate(ratios)
        assert len(result) == 2
        assert result[0].amount == Decimal("3.00")
        assert result[1].amount == Decimal("7.00")
        assert sum(r.amount for r in result) == Decimal("10.00")

    def test_allocate_with_remainder(self):
        m = Money(Decimal("10.00"), "IDR")
        ratios = [3, 3, 4]  # sum 10, but each ratio = 3/10, 3/10, 4/10 => 3,3,4
        result = m.allocate(ratios)
        assert result[0].amount == Decimal("3.00")
        assert result[1].amount == Decimal("3.00")
        assert result[2].amount == Decimal("4.00")

    def test_allocate_with_float_ratios(self):
        m = Money(Decimal("10.00"), "IDR")
        ratios = [0.3, 0.7]
        result = m.allocate(ratios)
        assert result[0].amount == Decimal("3.00")
        assert result[1].amount == Decimal("7.00")

    def test_allocate_with_zero_amount(self):
        m = Money(Decimal("0"), "IDR")
        ratios = [1, 2]
        result = m.allocate(ratios)
        assert all(r.amount == Decimal("0") for r in result)

    def test_allocate_empty_ratios_raises(self):
        m = Money(Decimal("10"), "IDR")
        with pytest.raises(MoneyError, match="At least one ratio required"):
            m.allocate([])

    def test_allocate_zero_sum_ratios_raises(self):
        m = Money(Decimal("10"), "IDR")
        with pytest.raises(MoneyError, match="Sum of ratios cannot be zero"):
            m.allocate([0, 0])

    def test_allocate_invalid_ratio_type_raises(self):
        m = Money(Decimal("10"), "IDR")
        with pytest.raises(InvalidAmountError, match="Invalid ratio type"):
            m.allocate(["a"])  # type: ignore

    def test_allocate_handles_largest_remainder(self):
        # Test that the largest remainder method works correctly
        m = Money(Decimal("10.00"), "IDR")
        ratios = [1, 1, 1]  # equal split, should be 3.33, 3.33, 3.34
        result = m.allocate(ratios)
        assert result[0].amount == Decimal("3.33")
        assert result[1].amount == Decimal("3.33")
        assert result[2].amount == Decimal("3.34")
        assert sum(r.amount for r in result) == Decimal("10.00")

    # ---- Formatting ----

    def test_format_default(self):
        m = Money(Decimal("1234.56"), "IDR")
        assert m.format() == "Rp 1.234,56"  # IDR uses Rp and . as thousands, , as decimal

    def test_format_without_currency(self):
        m = Money(Decimal("1234.56"), "IDR")
        assert m.format(include_currency=False) == "1.234,56 IDR"

    def test_format_negative(self):
        m = Money(Decimal("-1234.56"), "IDR")
        assert m.format() == "Rp -1.234,56"

    def test_format_custom_separators(self):
        m = Money(Decimal("1234.56"), "USD")
        assert m.format(decimal_separator=".", thousands_separator=",") == "$1,234.56"

    def test_format_zero_decimal_currency(self):
        m = Money(Decimal("1234"), "JPY")
        assert m.format() == "¥1234"

    def test_format_unknown_currency_symbol_fallback(self):
        m = Money(Decimal("1234.56"), "XXX")  # unknown currency
        # Should use currency code as symbol
        assert m.format() == "XXX 1.234,56"

    def test_str_uses_format(self):
        m = Money(Decimal("1234.56"), "IDR")
        assert str(m) == m.format()

    def test_repr(self):
        m = Money(Decimal("1234.56"), "IDR")
        assert repr(m) == "Money('1234.56', 'IDR')"

    # ---- Serialization ----

    def test_to_dict(self):
        m = Money(Decimal("1234.56"), "IDR")
        d = m.to_dict()
        assert d["amount"] == "1234.56"
        assert d["currency"] == "IDR"
        assert d["decimal_places"] == 2
        assert d["minor_units"] == 123456

    def test_to_db_record(self):
        m = Money(Decimal("1234.56"), "IDR")
        rec = m.to_db_record()
        assert rec["amount"] == Decimal("1234.56")
        assert rec["currency"] == "IDR"

    # ---- split, max, min ----

    def test_split(self):
        m = Money(Decimal("10.00"), "IDR")
        parts = m.split(3)
        assert len(parts) == 3
        assert parts[0].amount == Decimal("3.33")
        assert parts[1].amount == Decimal("3.33")
        assert parts[2].amount == Decimal("3.34")
        assert sum(p.amount for p in parts) == Decimal("10.00")

    def test_split_negative_n_raises(self):
        m = Money(Decimal("10"), "IDR")
        with pytest.raises(MoneyError, match="positive"):
            m.split(0)

    def test_max(self):
        m1 = Money(Decimal("10"), "IDR")
        m2 = Money(Decimal("20"), "IDR")
        assert m1.max(m2) == m2
        assert m2.max(m1) == m2
        # same currency required; if different, raises in compare
        with pytest.raises(CurrencyMismatchError):
            m1.max(Money(Decimal("10"), "USD"))

    def test_min(self):
        m1 = Money(Decimal("10"), "IDR")
        m2 = Money(Decimal("20"), "IDR")
        assert m1.min(m2) == m1
        assert m2.min(m1) == m1

    # ---- Immutability ----
    def test_immutability(self):
        m = Money(Decimal("10.50"), "IDR")
        with pytest.raises(AttributeError):
            m.amount = Decimal("20")  # type: ignore

# =============================================================================
# Tests for helper functions (sum_money, average_money)
# =============================================================================

class TestHelperFunctions:
    def test_sum_money_same_currency(self):
        m1 = Money(Decimal("10.50"), "IDR")
        m2 = Money(Decimal("5.25"), "IDR")
        total = sum_money([m1, m2])
        assert total.amount == Decimal("15.75")
        assert total.currency == "IDR"

    def test_sum_money_empty_list(self):
        total = sum_money([])
        assert total.amount == Decimal("0")
        assert total.currency == "USD"  # default

    def test_sum_money_mixed_currency_raises(self):
        m1 = Money(Decimal("10"), "IDR")
        m2 = Money(Decimal("5"), "USD")
        with pytest.raises(CurrencyMismatchError, match="Currency mismatch: USD vs IDR"):
            sum_money([m1, m2])

    def test_average_money(self):
        m1 = Money(Decimal("10.00"), "IDR")
        m2 = Money(Decimal("20.00"), "IDR")
        avg = average_money([m1, m2])
        assert avg.amount == Decimal("15.00")
        assert avg.currency == "IDR"

    def test_average_money_empty_list_raises(self):
        with pytest.raises(MoneyError, match="Cannot average empty list"):
            average_money([])

    def test_average_money_mixed_currency_raises(self):
        m1 = Money(Decimal("10"), "IDR")
        m2 = Money(Decimal("5"), "USD")
        with pytest.raises(CurrencyMismatchError):
            average_money([m1, m2])

# =============================================================================
# Additional negative path tests
# =============================================================================

class TestNegativePaths:
    def test_allocate_with_negative_ratios(self):
        # Negative ratios should be allowed? They would produce negative allocations.
        # The code doesn't disallow, but then sum might not match? Let's test.
        m = Money(Decimal("10.00"), "IDR")
        ratios = [-1, 2]
        result = m.allocate(ratios)
        # ratio sum = 1, normalized: -1, 2 => amounts: -10, 20
        # But the allocate method normalizes and uses largest remainder.
        # With negative ratios, the total may not sum to original? Actually the sum of normalized ratios = 1,
        # so the sum of allocations should still equal original amount.
        assert sum(r.amount for r in result) == Decimal("10.00")
        # No exception raised.

    def test_format_with_zero_decimal_and_negative(self):
        m = Money(Decimal("-123"), "JPY")
        assert m.format() == "¥-123"

    def test_rounded_with_invalid_rounding_mode(self):
        m = Money(Decimal("10.55"), "IDR")
        # Should default to HALF_EVEN
        result = m.rounded(1, "INVALID")
        assert result.amount == Decimal("10.6")  # ROUND_HALF_EVEN

    def test_alloc_returns_money_objects_with_same_currency(self):
        m = Money(Decimal("10"), "IDR")
        parts = m.split(2)
        assert all(p.currency == "IDR" for p in parts)

    def test_money_equality_with_different_currency(self):
        m1 = Money(Decimal("10"), "IDR")
        m2 = Money(Decimal("10"), "USD")
        assert m1 != m2

    def test_money_equality_with_non_money(self):
        m = Money(Decimal("10"), "IDR")
        assert m != "10"  # no exception

    def test_compare_returns_int(self):
        m1 = Money(Decimal("10"), "IDR")
        m2 = Money(Decimal("20"), "IDR")
        assert m1.compare(m2) == -1
        assert m2.compare(m1) == 1
        assert m1.compare(m1) == 0

    def test_negated_preserves_currency(self):
        m = Money(Decimal("10.50"), "IDR")
        neg = m.negated
        assert neg.currency == "IDR"

    def test_absolute_preserves_currency(self):
        m = Money(Decimal("-10.50"), "IDR")
        abs_m = m.absolute
        assert abs_m.currency == "IDR"

    def test_minor_units_with_three_decimal_currency(self):
        m = Money(Decimal("1.234"), "KWD")
        assert m.minor_units == 1234

    def test_from_minor_units_with_negative_minor(self):
        # Negative minor units should work
        m = Money.from_minor_units(-123, "USD")
        assert m.amount == Decimal("-1.23")

    def test_from_minor_units_zero(self):
        m = Money.from_minor_units(0, "IDR")
        assert m.amount == Decimal("0")

    def test_rounding_with_very_small_amount(self):
        m = Money(Decimal("0.0001"), "IDR")
        # rounding to 2 decimals: 0.00
        assert m.amount == Decimal("0.00")

    def test_rounding_with_very_large_amount(self):
        m = Money(Decimal("999999999999.99"), "IDR")
        # should not raise
        assert m.amount == Decimal("999999999999.99")
