# test_currency_vo.py
# Comprehensive tests for currency_vo.py

from decimal import Decimal

import pytest

from domain.shared_value_objects.currency_vo import CurrencyCode, CurrencyVO


class TestCurrencyCode:
    def test_members(self):
        assert CurrencyCode.IDR.value == "IDR"
        assert CurrencyCode.USD.value == "USD"
        assert CurrencyCode.EUR.value == "EUR"
        assert CurrencyCode.GBP.value == "GBP"
        assert CurrencyCode.JPY.value == "JPY"

    def test_from_string(self):
        assert CurrencyCode.from_string("IDR") == CurrencyCode.IDR
        assert CurrencyCode.from_string("usd") == CurrencyCode.USD
        assert CurrencyCode.from_string("EUR") == CurrencyCode.EUR
        assert CurrencyCode.from_string("invalid") is None
        assert CurrencyCode.from_string("") is None

    def test_is_supported(self):
        assert CurrencyCode.is_supported("IDR") is True
        assert CurrencyCode.is_supported("USD") is True
        assert CurrencyCode.is_supported("invalid") is False
        assert CurrencyCode.is_supported("") is False


class TestCurrencyVO:
    def test_construction(self):
        currency = CurrencyVO(CurrencyCode.IDR)
        assert currency.code == CurrencyCode.IDR

    def test_name(self):
        assert CurrencyVO(CurrencyCode.IDR).name == "Indonesian Rupiah"
        assert CurrencyVO(CurrencyCode.USD).name == "United States Dollar"
        assert CurrencyVO(CurrencyCode.EUR).name == "Euro"
        assert CurrencyVO(CurrencyCode.GBP).name == "Pound Sterling"

    def test_symbol(self):
        assert CurrencyVO(CurrencyCode.IDR).symbol == "Rp"
        assert CurrencyVO(CurrencyCode.USD).symbol == "$"
        assert CurrencyVO(CurrencyCode.EUR).symbol == "€"
        assert CurrencyVO(CurrencyCode.GBP).symbol == "£"

    def test_numeric_code(self):
        assert CurrencyVO(CurrencyCode.IDR).numeric_code == 360
        assert CurrencyVO(CurrencyCode.USD).numeric_code == 840
        assert CurrencyVO(CurrencyCode.EUR).numeric_code == 978

    def test_decimal_places(self):
        assert CurrencyVO(CurrencyCode.IDR).decimal_places == 2
        assert CurrencyVO(CurrencyCode.USD).decimal_places == 2
        assert CurrencyVO(CurrencyCode.JPY).decimal_places == 0
        assert CurrencyVO(CurrencyCode.KRW).decimal_places == 0
        assert CurrencyVO(CurrencyCode.EUR).decimal_places == 2

    def test_minor_unit_name(self):
        assert CurrencyVO(CurrencyCode.IDR).minor_unit_name == "sen"
        assert CurrencyVO(CurrencyCode.USD).minor_unit_name == "cent"
        assert CurrencyVO(CurrencyCode.JPY).minor_unit_name == "sen"

    def test_from_code(self):
        currency = CurrencyVO.from_code("IDR")
        assert currency is not None
        assert currency.code == CurrencyCode.IDR
        assert CurrencyVO.from_code("XXX") is None

    def test_from_numeric(self):
        currency = CurrencyVO.from_numeric(360)
        assert currency is not None
        assert currency.code == CurrencyCode.IDR
        assert CurrencyVO.from_numeric(999) is None

    def test_default_currency(self):
        currency = CurrencyVO.default_currency()
        assert currency.code == CurrencyCode.IDR

    def test_format_default(self):
        currency = CurrencyVO(CurrencyCode.IDR)
        result = currency.format(Decimal("1500000.50"))
        assert result == "Rp 1.500.000,50"

    def test_format_without_symbol(self):
        currency = CurrencyVO(CurrencyCode.IDR)
        result = currency.format(Decimal("1500000.50"), include_symbol=False)
        assert result == "1.500.000,50"

    def test_format_with_currency_code(self):
        currency = CurrencyVO(CurrencyCode.IDR)
        result = currency.format(Decimal("1500000.50"), include_currency_code=True)
        assert result == "Rp 1.500.000,50 IDR"

    def test_format_without_symbol_and_with_code(self):
        currency = CurrencyVO(CurrencyCode.IDR)
        result = currency.format(
            Decimal("1500000.50"),
            include_symbol=False,
            include_currency_code=True
        )
        assert result == "1.500.000,50 IDR"

    def test_format_usd(self):
        usd = CurrencyVO(CurrencyCode.USD)
        result = usd.format(Decimal("1234.56"))
        assert result == "$ 1,234.56"

    def test_format_usd_without_symbol(self):
        usd = CurrencyVO(CurrencyCode.USD)
        result = usd.format(Decimal("1234.56"), include_symbol=False)
        assert result == "1,234.56"

    def test_format_jpy_no_decimals(self):
        jpy = CurrencyVO(CurrencyCode.JPY)
        result = jpy.format(Decimal("1500"))
        assert result == "¥ 1,500"

    def test_format_negative(self):
        idr = CurrencyVO(CurrencyCode.IDR)
        result = idr.format(Decimal("-1500000.50"))
        assert result == "Rp -1.500.000,50"

    def test_format_negative_without_symbol(self):
        idr = CurrencyVO(CurrencyCode.IDR)
        result = idr.format(Decimal("-1500000.50"), include_symbol=False)
        assert result == "-1.500.000,50"

    def test_format_custom_separators(self):
        idr = CurrencyVO(CurrencyCode.IDR)
        result = idr.format(
            Decimal("1500000.50"),
            group_separator=",",
            decimal_separator="."
        )
        assert result == "Rp 1,500,000.50"

    def test_format_zero_decimal_currency(self):
        jpy = CurrencyVO(CurrencyCode.JPY)
        result = jpy.format(Decimal("100.50"))  # JPY has 0 decimal places, so rounds
        # 100.50 rounded to 101 (since 0 decimal places)
        assert result == "¥ 101"

    def test_format_rounding(self):
        idr = CurrencyVO(CurrencyCode.IDR)
        # ROUND_HALF_EVEN: 1.005 -> 1.00 (since 5 rounds to even)
        result = idr.format(Decimal("1.005"))
        assert result == "Rp 1,00"  # Actually 1.005 with ROUND_HALF_EVEN -> 1.00

    def test_to_minor_units(self):
        usd = CurrencyVO(CurrencyCode.USD)
        assert usd.to_minor_units(Decimal("1.23")) == 123
        assert usd.to_minor_units(Decimal("100.00")) == 10000

        idr = CurrencyVO(CurrencyCode.IDR)
        assert idr.to_minor_units(Decimal("1000.50")) == 100050

        jpy = CurrencyVO(CurrencyCode.JPY)
        assert jpy.to_minor_units(Decimal("100")) == 100

    def test_from_minor_units(self):
        usd = CurrencyVO(CurrencyCode.USD)
        assert usd.from_minor_units(123) == Decimal("1.23")
        assert usd.from_minor_units(10000) == Decimal("100.00")

        idr = CurrencyVO(CurrencyCode.IDR)
        assert idr.from_minor_units(100050) == Decimal("1000.50")

        jpy = CurrencyVO(CurrencyCode.JPY)
        assert jpy.from_minor_units(100) == Decimal("100")

    def test_to_dict(self):
        currency = CurrencyVO(CurrencyCode.IDR)
        d = currency.to_dict()
        assert d["code"] == "IDR"
        assert d["numeric_code"] == 360
        assert d["name"] == "Indonesian Rupiah"
        assert d["symbol"] == "Rp"
        assert d["decimal_places"] == 2
        assert d["minor_unit_name"] == "sen"

    def test_from_dict(self):
        data = {"code": "USD"}
        currency = CurrencyVO.from_dict(data)
        assert currency.code == CurrencyCode.USD

    def test_str(self):
        assert str(CurrencyVO(CurrencyCode.IDR)) == "IDR"

    def test_repr(self):
        assert repr(CurrencyVO(CurrencyCode.IDR)) == "CurrencyVO('IDR')"

    def test_eq(self):
        c1 = CurrencyVO(CurrencyCode.IDR)
        c2 = CurrencyVO(CurrencyCode.IDR)
        c3 = CurrencyVO(CurrencyCode.USD)
        assert c1 == c2
        assert c1 != c3
        assert c1 != "not a currency"

    def test_hash(self):
        c1 = CurrencyVO(CurrencyCode.IDR)
        c2 = CurrencyVO(CurrencyCode.IDR)
        assert hash(c1) == hash(c2)
        c3 = CurrencyVO(CurrencyCode.USD)
        assert hash(c1) != hash(c3)