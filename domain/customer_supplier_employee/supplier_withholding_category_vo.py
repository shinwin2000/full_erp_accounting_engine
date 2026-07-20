# tests/domain/customer_supplier_employee/test_supplier_withholding_category_vo.py
"""
Comprehensive tests for supplier_withholding_category_vo.py.

FIXES:
- All datetime/date.today() replaced with FIXED_DATE.
- Negative path tests for all exceptions.
- Parametrized tests to eliminate structural duplication.
- Tests for all domain-sensitive functions (factory methods, calculate, with_article, etc.).
- Helper functions tested with realistic data.
- Added more assertions for precision (Tier 4).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from domain.customer_supplier_employee.supplier_withholding_category_vo import (
    InvalidWithholdingRateError,
    SupplierWithholdingCategoryVO,
    WithholdingArticle,
    WithholdingCategoryError,
    WithholdingRate,
    calculate_withholding_for_supplier,
    get_default_withholding_for_transaction,
)

# ============================================================================
# FIXED DATE (untuk menghindari flaky tests)
# ============================================================================

FIXED_DATE = date(2026, 1, 1)
FIXED_FUTURE = FIXED_DATE + timedelta(days=30)
FIXED_PAST = FIXED_DATE - timedelta(days=30)


@pytest.fixture(autouse=True)
def mock_date_today():
    """Mock date.today() to return FIXED_DATE."""
    with patch("domain.customer_supplier_employee.supplier_withholding_category_vo.date") as mock_date:
        mock_date.today.return_value = FIXED_DATE
        yield mock_date


# ============================================================================
# TESTS FOR ENUMS
# ============================================================================

class TestWithholdingArticle:
    def test_members(self):
        expected = ["NONE", "PPH_21", "PPH_22", "PPH_23", "PPH_26", "PPH_4_2"]
        for name in expected:
            assert hasattr(WithholdingArticle, name)

    def test_display_name(self):
        assert WithholdingArticle.NONE.display_name() == "Tidak Dipotong"
        assert WithholdingArticle.PPH_23.display_name() == "PPh Pasal 23"
        assert WithholdingArticle.PPH_4_2.display_name() == "PPh Pasal 4(2)"

    @pytest.mark.parametrize("article,expected", [
        (WithholdingArticle.PPH_4_2, True),
        (WithholdingArticle.PPH_23, False),
        (WithholdingArticle.NONE, False),
    ])
    def test_is_final_by_default(self, article, expected):
        assert article.is_final_by_default() == expected

    @pytest.mark.parametrize("article,expected", [
        (WithholdingArticle.PPH_23, True),
        (WithholdingArticle.PPH_22, True),
        (WithholdingArticle.NONE, False),
    ])
    def test_requires_npwp(self, article, expected):
        assert article.requires_npwp() == expected

    @pytest.mark.parametrize("article,expected", [
        (WithholdingArticle.PPH_22, True),
        (WithholdingArticle.PPH_23, True),
        (WithholdingArticle.PPH_21, False),
    ])
    def test_requires_invoice(self, article, expected):
        assert article.requires_invoice() == expected

    @pytest.mark.parametrize("input_str,expected", [
        ("23", WithholdingArticle.PPH_23),
        ("pph 23", WithholdingArticle.PPH_23),
        ("none", WithholdingArticle.NONE),
        ("4(2)", WithholdingArticle.PPH_4_2),
        ("unknown", None),
        ("", None),
    ])
    def test_from_string(self, input_str, expected):
        assert WithholdingArticle.from_string(input_str) == expected


class TestWithholdingRate:
    def test_members(self):
        expected = ["RATE_0", "RATE_0_5", "RATE_1", "RATE_1_5", "RATE_2",
                    "RATE_2_5", "RATE_3", "RATE_4", "RATE_5", "RATE_6",
                    "RATE_10", "RATE_15", "RATE_20", "RATE_25"]
        for name in expected:
            assert hasattr(WithholdingRate, name)

    @pytest.mark.parametrize("rate_enum,expected_decimal", [
        (WithholdingRate.RATE_0, Decimal("0")),
        (WithholdingRate.RATE_0_5, Decimal("0.5")),
        (WithholdingRate.RATE_1, Decimal("1")),
        (WithholdingRate.RATE_1_5, Decimal("1.5")),
        (WithholdingRate.RATE_2, Decimal("2")),
        (WithholdingRate.RATE_2_5, Decimal("2.5")),
        (WithholdingRate.RATE_3, Decimal("3")),
        (WithholdingRate.RATE_4, Decimal("4")),
        (WithholdingRate.RATE_5, Decimal("5")),
        (WithholdingRate.RATE_6, Decimal("6")),
        (WithholdingRate.RATE_10, Decimal("10")),
        (WithholdingRate.RATE_15, Decimal("15")),
        (WithholdingRate.RATE_20, Decimal("20")),
        (WithholdingRate.RATE_25, Decimal("25")),
    ])
    def test_as_decimal(self, rate_enum, expected_decimal):
        assert rate_enum.as_decimal() == expected_decimal

    @pytest.mark.parametrize("rate_enum,expected_display", [
        (WithholdingRate.RATE_0, "0%"),
        (WithholdingRate.RATE_1_5, "1.5%"),
        (WithholdingRate.RATE_25, "25%"),
    ])
    def test_display_name(self, rate_enum, expected_display):
        assert rate_enum.display_name() == expected_display


# ============================================================================
# TESTS FOR EXCEPTIONS (NEGATIVE PATH)
# ============================================================================

class TestExceptions:
    def test_withholding_category_error(self):
        with pytest.raises(WithholdingCategoryError, match="test error"):
            raise WithholdingCategoryError("test error")

    def test_invalid_withholding_rate_error(self):
        with pytest.raises(InvalidWithholdingRateError, match="invalid rate"):
            raise InvalidWithholdingRateError("invalid rate")


# ============================================================================
# TESTS FOR SUPPLIER WITHHOLDING CATEGORY VO
# ============================================================================

class TestSupplierWithholdingCategoryVO:
    # ------------------------------------------------------------------------
    # Construction and validation
    # ------------------------------------------------------------------------

    def test_create_valid(self):
        category = SupplierWithholdingCategoryVO(
            article=WithholdingArticle.PPH_23,
            rate=Decimal("2"),
            is_final=False,
            effective_date=FIXED_DATE,
            notes="Test",
            special_rates={"service": Decimal("1.5")},
        )
        assert category.article == WithholdingArticle.PPH_23
        assert category.rate == Decimal("2")
        assert category.is_final is False
        assert category.effective_date == FIXED_DATE
        assert category.notes == "Test"
        assert category.special_rates == {"service": Decimal("1.5")}

    @pytest.mark.parametrize("invalid_rate,expected_msg", [
        (Decimal("-1"), "between 0 and 100"),
        (Decimal("101"), "between 0 and 100"),
    ])
    def test_validate_rate_out_of_range_raises(self, invalid_rate, expected_msg):
        with pytest.raises(InvalidWithholdingRateError, match=expected_msg):
            SupplierWithholdingCategoryVO(
                article=WithholdingArticle.PPH_23,
                rate=invalid_rate,
            )

    def test_validate_rate_for_none_must_be_zero(self):
        with pytest.raises(InvalidWithholdingRateError, match="Rate must be 0 for article NONE"):
            SupplierWithholdingCategoryVO(
                article=WithholdingArticle.NONE,
                rate=Decimal("5"),
            )

    def test_validate_effective_date_future_raises(self):
        with pytest.raises(WithholdingCategoryError, match="Effective date cannot be in the future"):
            SupplierWithholdingCategoryVO(
                article=WithholdingArticle.PPH_23,
                rate=Decimal("2"),
                effective_date=FIXED_FUTURE,
            )

    @pytest.mark.parametrize("invalid_special_rate", [
        Decimal("-5"),
        Decimal("150"),
    ])
    def test_validate_special_rate_invalid_raises(self, invalid_special_rate):
        with pytest.raises(InvalidWithholdingRateError, match="0-100"):
            SupplierWithholdingCategoryVO(
                article=WithholdingArticle.PPH_23,
                rate=Decimal("2"),
                special_rates={"service": invalid_special_rate},
            )

    def test_validate_special_rate_not_decimal_raises(self):
        with pytest.raises(WithholdingCategoryError, match="must be Decimal"):
            SupplierWithholdingCategoryVO(
                article=WithholdingArticle.PPH_23,
                rate=Decimal("2"),
                special_rates={"service": "not_decimal"},
            )

    def test_validate_rate_not_decimal_raises(self):
        with pytest.raises(WithholdingCategoryError, match="rate must be Decimal"):
            SupplierWithholdingCategoryVO(
                article=WithholdingArticle.PPH_23,
                rate=2,  # int, not Decimal
            )

    def test_validate_article_invalid_raises(self):
        with pytest.raises(WithholdingCategoryError, match="Invalid article"):
            SupplierWithholdingCategoryVO(
                article="invalid",  # type: ignore
                rate=Decimal("2"),
            )

    def test_is_final_default_for_pph4_2(self):
        category = SupplierWithholdingCategoryVO(
            article=WithholdingArticle.PPH_4_2,
            rate=Decimal("10"),
        )
        assert category.is_final is True  # automatically set

    # ------------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------------

    @pytest.mark.parametrize("factory_method,expected_article,expected_rate,expected_final", [
        ("create_none", WithholdingArticle.NONE, Decimal("0"), False),
        ("create_pph21", WithholdingArticle.PPH_21, Decimal("5"), False),
        ("create_pph22", WithholdingArticle.PPH_22, Decimal("1.5"), False),
        ("create_pph23", WithholdingArticle.PPH_23, Decimal("2"), False),
        ("create_pph26", WithholdingArticle.PPH_26, Decimal("20"), False),
        ("create_pph4_2", WithholdingArticle.PPH_4_2, Decimal("10"), True),
    ])
    def test_factory_methods(self, factory_method, expected_article, expected_rate, expected_final):
        method = getattr(SupplierWithholdingCategoryVO, factory_method)
        if factory_method == "create_pph21":
            cat = method(rate=Decimal("5"))
        else:
            cat = method()
        assert cat.article == expected_article
        assert cat.rate == expected_rate
        assert cat.is_final == expected_final
        if factory_method == "create_none":
            assert cat.notes == "No withholding"

    def test_from_dict(self):
        data = {
            "article": "23",
            "rate": "2.5",
            "is_final": False,
            "effective_date": FIXED_DATE.isoformat(),
            "notes": "Test",
            "special_rates": {"rental": "10"},
        }
        cat = SupplierWithholdingCategoryVO.from_dict(data)
        assert cat.article == WithholdingArticle.PPH_23
        assert cat.rate == Decimal("2.5")
        assert cat.is_final is False
        assert cat.effective_date == FIXED_DATE
        assert cat.notes == "Test"
        assert cat.special_rates == {"rental": Decimal("10")}

    def test_from_dict_with_unknown_article_falls_back_to_none(self):
        data = {"article": "unknown"}
        cat = SupplierWithholdingCategoryVO.from_dict(data)
        assert cat.article == WithholdingArticle.NONE
        assert cat.rate == Decimal("0")

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    @pytest.mark.parametrize("article,rate,expected_should_withhold", [
        (WithholdingArticle.PPH_23, Decimal("2"), True),
        (WithholdingArticle.NONE, Decimal("0"), False),
        (WithholdingArticle.PPH_23, Decimal("0"), False),
    ])
    def test_should_withhold(self, article, rate, expected_should_withhold):
        cat = SupplierWithholdingCategoryVO(article=article, rate=rate)
        assert cat.should_withhold == expected_should_withhold

    @pytest.mark.parametrize("rate,expected_percentage", [
        (Decimal("2"), 2.0),
        (Decimal("2.5"), 2.5),
        (Decimal("0"), 0.0),
    ])
    def test_rate_percentage(self, rate, expected_percentage):
        cat = SupplierWithholdingCategoryVO.create_pph23(rate=rate)
        assert cat.rate_percentage == expected_percentage

    @pytest.mark.parametrize("rate,expected_decimal", [
        (Decimal("2"), Decimal("0.02")),
        (Decimal("2.5"), Decimal("0.025")),
        (Decimal("0"), Decimal("0")),
    ])
    def test_rate_decimal(self, rate, expected_decimal):
        cat = SupplierWithholdingCategoryVO.create_pph23(rate=rate)
        assert cat.rate_decimal == expected_decimal

    def test_display_name(self):
        cat = SupplierWithholdingCategoryVO.create_none()
        assert cat.display_name == "Tidak Dipotong"
        cat = SupplierWithholdingCategoryVO.create_pph23(rate=Decimal("2"))
        assert cat.display_name == "PPh Pasal 23 - 2%"

    # ------------------------------------------------------------------------
    # calculate_withholding
    # ------------------------------------------------------------------------

    @pytest.mark.parametrize("article,rate,amount,expected", [
        (WithholdingArticle.NONE, Decimal("0"), Decimal("1000000"), Decimal("0")),
        (WithholdingArticle.PPH_23, Decimal("2"), Decimal("1000000"), Decimal("20000.00")),
        (WithholdingArticle.PPH_23, Decimal("2"), Decimal("999.99"), Decimal("20.00")),
    ])
    def test_calculate_withholding(self, article, rate, amount, expected):
        cat = SupplierWithholdingCategoryVO(article=article, rate=rate)
        result = cat.calculate_withholding(amount)
        assert result == expected

    def test_calculate_withholding_with_special_rate(self):
        cat = SupplierWithholdingCategoryVO.create_pph23(rate=Decimal("2"))
        cat = cat.add_special_rate("service", Decimal("1.5"))
        result = cat.calculate_withholding(Decimal("1000000"), transaction_type="service")
        assert result == Decimal("15000.00")
        result_default = cat.calculate_withholding(Decimal("1000000"), transaction_type="unknown")
        assert result_default == Decimal("20000.00")

    def test_calculate_withholding_negative_amount_raises(self):
        cat = SupplierWithholdingCategoryVO.create_pph23(rate=Decimal("2"))
        with pytest.raises(ValueError, match="Amount cannot be negative"):
            cat.calculate_withholding(Decimal("-100"))

    # ------------------------------------------------------------------------
    # is_applicable
    # ------------------------------------------------------------------------

    def test_is_applicable_no_effective_date(self):
        cat = SupplierWithholdingCategoryVO.create_pph23()
        assert cat.is_applicable() is True
        assert cat.is_applicable(FIXED_DATE) is True

    def test_is_applicable_with_effective_date(self):
        cat = SupplierWithholdingCategoryVO.create_pph23().effective_from(FIXED_DATE)
        assert cat.is_applicable(FIXED_DATE) is True
        assert cat.is_applicable(FIXED_PAST) is False

    # ------------------------------------------------------------------------
    # with_rate, with_article, add_special_rate, remove_special_rate, effective_from
    # ------------------------------------------------------------------------

    def test_with_rate(self):
        cat = SupplierWithholdingCategoryVO.create_pph23(rate=Decimal("2"))
        new_cat = cat.with_rate(Decimal("3"), "admin")
        assert new_cat.rate == Decimal("3")
        assert new_cat.article == WithholdingArticle.PPH_23
        assert new_cat.effective_date == FIXED_DATE
        assert "Rate changed" in new_cat.notes

    @pytest.mark.parametrize("target_article,expected_rate,expected_final", [
        (WithholdingArticle.PPH_4_2, Decimal("10"), True),
        (WithholdingArticle.NONE, Decimal("0"), False),
        (WithholdingArticle.PPH_23, Decimal("2"), False),
    ])
    def test_with_article(self, target_article, expected_rate, expected_final):
        cat = SupplierWithholdingCategoryVO.create_pph23(rate=Decimal("2"))
        new_cat = cat.with_article(target_article, "admin")
        assert new_cat.article == target_article
        assert new_cat.rate == expected_rate
        assert new_cat.is_final == expected_final
        assert "Article changed" in new_cat.notes

    def test_add_special_rate(self):
        cat = SupplierWithholdingCategoryVO.create_pph23(rate=Decimal("2"))
        new_cat = cat.add_special_rate("service", Decimal("1.5"))
        assert new_cat.special_rates == {"service": Decimal("1.5")}
        assert "Added special rate" in new_cat.notes

    def test_add_special_rate_invalid_raises(self):
        cat = SupplierWithholdingCategoryVO.create_pph23(rate=Decimal("2"))
        with pytest.raises(InvalidWithholdingRateError, match="0-100"):
            cat.add_special_rate("service", Decimal("101"))

    def test_remove_special_rate(self):
        cat = SupplierWithholdingCategoryVO.create_pph23(rate=Decimal("2"))
        cat = cat.add_special_rate("service", Decimal("1.5"))
        cat = cat.add_special_rate("rental", Decimal("10"))
        new_cat = cat.remove_special_rate("service")
        assert new_cat.special_rates == {"rental": Decimal("10")}
        assert "Removed special rate" in new_cat.notes

    def test_remove_special_rate_not_found_returns_self(self):
        cat = SupplierWithholdingCategoryVO.create_pph23(rate=Decimal("2"))
        new_cat = cat.remove_special_rate("service")
        assert new_cat is cat  # returns self when not found

    def test_effective_from(self):
        cat = SupplierWithholdingCategoryVO.create_pph23()
        new_cat = cat.effective_from(FIXED_FUTURE)
        assert new_cat.effective_date == FIXED_FUTURE

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def test_to_dict(self):
        cat = SupplierWithholdingCategoryVO(
            article=WithholdingArticle.PPH_23,
            rate=Decimal("2.5"),
            is_final=False,
            effective_date=FIXED_DATE,
            notes="Test",
            special_rates={"service": Decimal("1.5")},
        )
        d = cat.to_dict()
        assert d["article"] == "23"
        assert d["article_display"] == "PPh Pasal 23"
        assert d["rate"] == "2.5"
        assert d["rate_percentage"] == 2.5
        assert d["is_final"] is False
        assert d["should_withhold"] is True
        assert d["effective_date"] == FIXED_DATE.isoformat()
        assert d["notes"] == "Test"
        assert d["special_rates"] == {"service": "1.5"}

    def test_to_db_record(self):
        cat = SupplierWithholdingCategoryVO(
            article=WithholdingArticle.PPH_23,
            rate=Decimal("2.5"),
            is_final=False,
            effective_date=FIXED_DATE,
            notes="Test",
            special_rates={"service": Decimal("1.5")},
        )
        rec = cat.to_db_record()
        assert rec["withholding_article"] == "23"
        assert rec["withholding_rate"] == Decimal("2.5")
        assert rec["withholding_is_final"] is False
        assert rec["withholding_effective_date"] == FIXED_DATE
        assert rec["withholding_notes"] == "Test"
        assert rec["withholding_special_rates"] == "service:1.5"

    def test_to_db_record_no_special_rates(self):
        cat = SupplierWithholdingCategoryVO.create_none()
        rec = cat.to_db_record()
        assert rec["withholding_special_rates"] is None

    def test_from_dict_with_no_effective_date(self):
        data = {"article": "23", "rate": "2"}
        cat = SupplierWithholdingCategoryVO.from_dict(data)
        assert cat.effective_date is None

    # ------------------------------------------------------------------------
    # Dunder methods
    # ------------------------------------------------------------------------

    def test_equality(self):
        cat1 = SupplierWithholdingCategoryVO.create_pph23(rate=Decimal("2"))
        cat2 = SupplierWithholdingCategoryVO.create_pph23(rate=Decimal("2"))
        assert cat1 == cat2
        cat3 = SupplierWithholdingCategoryVO.create_pph21(rate=Decimal("5"))
        assert cat1 != cat3
        assert cat1 != "string"

    def test_hash(self):
        cat = SupplierWithholdingCategoryVO.create_pph23()
        assert hash(cat) is not None

    def test_repr(self):
        cat = SupplierWithholdingCategoryVO.create_pph23(rate=Decimal("2"))
        assert repr(cat) == "SupplierWithholdingCategoryVO(article=23, rate=2, final=False)"

    def test_str(self):
        cat = SupplierWithholdingCategoryVO.create_pph23(rate=Decimal("2"))
        assert str(cat) == "PPh Pasal 23 - 2%"


# ============================================================================
# TESTS FOR HELPER FUNCTIONS
# ============================================================================

class TestHelperFunctions:
    @pytest.mark.parametrize("transaction_type,expected_article,expected_rate", [
        ("service", WithholdingArticle.PPH_23, Decimal("2")),
        ("rental", WithholdingArticle.PPH_23, Decimal("10")),
        ("sale", WithholdingArticle.PPH_22, Decimal("1.5")),
        ("unknown", WithholdingArticle.NONE, Decimal("0")),
    ])
    def test_get_default_withholding_for_transaction(self, transaction_type, expected_article, expected_rate):
        cat = get_default_withholding_for_transaction(transaction_type)
        assert cat.article == expected_article
        assert cat.rate == expected_rate

    def test_calculate_withholding_for_supplier(self):
        cat = SupplierWithholdingCategoryVO.create_pph23(rate=Decimal("2"))
        result = calculate_withholding_for_supplier(cat, Decimal("1000000"))
        assert result == Decimal("20000.00")
        # with special rate
        cat = cat.add_special_rate("service", Decimal("1.5"))
        result = calculate_withholding_for_supplier(cat, Decimal("1000000"), "service")
        assert result == Decimal("15000.00")
        # with None category
        cat = SupplierWithholdingCategoryVO.create_none()
        result = calculate_withholding_for_supplier(cat, Decimal("1000000"))
        assert result == Decimal("0")