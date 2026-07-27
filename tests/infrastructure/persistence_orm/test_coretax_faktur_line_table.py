# tests/infrastructure/persistence_orm/test_coretax_faktur_line_table.py
"""
Comprehensive tests for infrastructure/persistence_orm/coretax_faktur_line_table.py
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from infrastructure.persistence_orm.coretax_faktur_line_table import CoretaxFakturLineTable


class TestCoretaxFakturLineTable:
    """Tests for the CoretaxFakturLineTable ORM model."""

    def test_tablename_defined(self):
        assert hasattr(CoretaxFakturLineTable, "__tablename__")
        assert isinstance(CoretaxFakturLineTable.__tablename__, str)
        assert len(CoretaxFakturLineTable.__tablename__) > 0

    def test_instantiation(self):
        instance = CoretaxFakturLineTable(
            id=uuid4(),
            faktur_id=uuid4(),
            line_number=1,
            description="Test line",
            quantity=Decimal("2"),
            unit_price=Decimal("100000"),
            amount=Decimal("200000"),
            tax_amount=Decimal("22000"),
            currency="IDR",
        )
        assert isinstance(instance, CoretaxFakturLineTable)
        assert instance.line_number == 1
        assert instance.quantity == Decimal("2")
        assert instance.unit_price == Decimal("100000")

    # -------------------- Fixtures --------------------
    @pytest.fixture
    def line(self):
        return CoretaxFakturLineTable(
            id=uuid4(),
            faktur_id=uuid4(),
            line_number=1,
            description="Test product",
            quantity=Decimal("3"),
            unit_price=Decimal("150000"),
            amount=Decimal("450000"),
            tax_amount=Decimal("49500"),  # 11% of 450,000
            currency="IDR",
            version=1,
        )

    @pytest.fixture
    def line_zero_amount(self):
        return CoretaxFakturLineTable(
            id=uuid4(),
            faktur_id=uuid4(),
            line_number=2,
            description="Zero amount",
            quantity=Decimal("0"),
            unit_price=Decimal("0"),
            amount=Decimal("0"),
            tax_amount=Decimal("0"),
            currency="IDR",
            version=1,
        )

    # -------------------- Property Tests --------------------
    def test_total_amount(self, line):
        # amount 450,000 + tax 49,500 = 499,500
        assert line.total_amount == Decimal("499500")

    def test_ppn_rate_calculation(self, line):
        # tax_amount / amount * 100 = 49,500 / 450,000 * 100 = 11.0
        assert line.ppn_rate == Decimal("11")

    def test_ppn_rate_zero_amount(self, line_zero_amount):
        # When amount is 0, ppn_rate should be 0
        assert line_zero_amount.ppn_rate == Decimal(0)

    def test_ppn_rate_high_precision(self):
        # Test with non-integer tax rate
        line = CoretaxFakturLineTable(
            amount=Decimal("1000000"),
            tax_amount=Decimal("110000"),
        )
        # 110,000 / 1,000,000 * 100 = 11.0
        assert line.ppn_rate == Decimal("11")

        # With fractional tax
        line2 = CoretaxFakturLineTable(
            amount=Decimal("333333"),
            tax_amount=Decimal("36666"),
        )
        # 36,666 / 333,333 * 100 ≈ 11.000011... but we'll just check it's a Decimal
        assert isinstance(line2.ppn_rate, Decimal)

    # -------------------- Method Tests --------------------
    def test_calculate_amount(self, line):
        # Initially amount = 450,000 (3 * 150,000)
        # Change quantity and unit_price
        line.quantity = Decimal("5")
        line.unit_price = Decimal("200000")
        line.calculate_amount()
        # New amount should be 5 * 200,000 = 1,000,000
        assert line.amount == Decimal("1000000")
        # Version should be incremented
        assert line.version == 2

    def test_calculate_amount_with_zero(self, line):
        line.quantity = Decimal("0")
        line.unit_price = Decimal("150000")
        line.calculate_amount()
        assert line.amount == Decimal("0")
        assert line.version == 2

    def test_set_tax(self, line):
        # amount = 450,000, set tax rate 10%
        line.set_tax(Decimal("10"))
        # tax_amount = 450,000 * 10 / 100 = 45,000
        assert line.tax_amount == Decimal("45000")
        assert line.version == 2

    def test_set_tax_with_zero_amount(self, line_zero_amount):
        # amount = 0, set tax rate 11%
        line_zero_amount.set_tax(Decimal("11"))
        assert line_zero_amount.tax_amount == Decimal("0")
        assert line_zero_amount.version == 2

    def test_set_tax_rounding(self, line):
        # amount = 450,000, tax rate 11% -> 49,500 exactly
        line.set_tax(Decimal("11"))
        assert line.tax_amount == Decimal("49500")
        # Test with amount that gives fractional result
        line2 = CoretaxFakturLineTable(
            amount=Decimal("1000000"),
            tax_amount=Decimal("0"),
            version=1,
        )
        line2.set_tax(Decimal("10.5"))
        # 1,000,000 * 10.5 / 100 = 105,000
        assert line2.tax_amount == Decimal("105000")

        # Fractional case: 1,000,000 * 11.11 / 100 = 111,100
        line2.set_tax(Decimal("11.11"))
        assert line2.tax_amount == Decimal("111100")

    # -------------------- to_dict Tests --------------------
    def test_to_dict(self, line):
        d = line.to_dict()
        assert d["id"] == str(line.id)
        assert d["faktur_id"] == str(line.faktur_id)
        assert d["line_number"] == 1
        assert d["description"] == "Test product"
        # Check monetary values are strings (precision)
        assert d["quantity"] == "3"
        assert d["unit_price"] == "150000"
        assert d["amount"] == "450000"
        assert d["tax_amount"] == "49500"
        assert d["currency"] == "IDR"
        assert d["total_amount"] == "499500"
        assert d["ppn_rate"] == "11"

    def test_to_dict_zero_line(self, line_zero_amount):
        d = line_zero_amount.to_dict()
        assert d["quantity"] == "0"
        assert d["unit_price"] == "0"
        assert d["amount"] == "0"
        assert d["tax_amount"] == "0"
        assert d["total_amount"] == "0"
        assert d["ppn_rate"] == "0"

    # -------------------- Edge Cases --------------------
    def test_calculate_amount_with_decimal_precision(self):
        line = CoretaxFakturLineTable(
            quantity=Decimal("1.5"),
            unit_price=Decimal("12345.67"),
            amount=Decimal("0"),
            version=1,
        )
        line.calculate_amount()
        # 1.5 * 12345.67 = 18518.505
        expected = Decimal("18518.505")
        assert line.amount == expected

    def test_set_tax_with_decimal_rate(self):
        line = CoretaxFakturLineTable(
            amount=Decimal("1000000"),
            tax_amount=Decimal("0"),
            version=1,
        )
        line.set_tax(Decimal("11.11"))
        # 1,000,000 * 11.11 / 100 = 111,100
        assert line.tax_amount == Decimal("111100")

    def test_version_increment_on_calculate_and_set_tax(self, line):
        # Start version 1
        line.calculate_amount()
        assert line.version == 2
        line.set_tax(Decimal("11"))
        assert line.version == 3

    def test_ppn_rate_after_set_tax(self, line):
        # Initially 11%
        assert line.ppn_rate == Decimal("11")
        line.set_tax(Decimal("10"))
        # tax_amount becomes 45,000, ppn_rate should be 10%
        assert line.ppn_rate == Decimal("10")