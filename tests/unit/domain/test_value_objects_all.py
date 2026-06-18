#!/usr/bin/env python3
"""
Module: test_value_objects_all.py
Layer: Tests / Unit / Domain

Responsibility:
    Unit tests untuk semua Value Objects yang digunakan di domain.
    Menguji validasi, equality, immutability, dan business rules.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from domain.shared_value_objects.accounting_period_vo import AccountingPeriod
from domain.shared_value_objects.date_range_vo import DateRange
from domain.shared_value_objects.document_number_vo import DocumentNumber
from domain.shared_value_objects.exchange_rate_vo import ExchangeRate
from domain.shared_value_objects.hash_chain_link_vo import HashChainLink
from domain.shared_value_objects.idempotency_key_vo import IdempotencyKey
from domain.shared_value_objects.money_vo import Currency, Money
from domain.shared_value_objects.npwp_vo import NPWP
from domain.shared_value_objects.percentage_vo import Percentage
from domain.shared_value_objects.quantity_vo import Quantity


class TestMoneyVO:
    def test_money_creation(self):
        money = Money(amount=Decimal("1000000"), currency=Currency.IDR)
        assert money.amount == Decimal("1000000")
        assert money.currency == Currency.IDR

    def test_money_addition(self):
        m1 = Money(Decimal("1000"), Currency.IDR)
        m2 = Money(Decimal("2000"), Currency.IDR)
        result = m1 + m2
        assert result.amount == Decimal("3000")

    def test_money_different_currency_raises(self):
        m1 = Money(Decimal("1000"), Currency.IDR)
        m2 = Money(Decimal("1000"), Currency.USD)
        with pytest.raises(ValueError, match="different currencies"):
            _ = m1 + m2

    def test_money_equality(self):
        m1 = Money(Decimal("1000"), Currency.IDR)
        m2 = Money(Decimal("1000"), Currency.IDR)
        assert m1 == m2


class TestQuantityVO:
    def test_positive_quantity(self):
        qty = Quantity(Decimal("10"))
        assert qty.value == Decimal("10")

    def test_zero_quantity(self):
        qty = Quantity(Decimal("0"))
        assert qty.value == Decimal("0")

    def test_negative_quantity_raises(self):
        with pytest.raises(ValueError, match="Quantity cannot be negative"):
            Quantity(Decimal("-5"))


class TestDocumentNumberVO:
    def test_valid_document_number(self):
        doc = DocumentNumber("INV-2025-00001")
        assert doc.value == "INV-2025-00001"

    def test_empty_document_number_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            DocumentNumber("")


class TestNPWPVO:
    def test_valid_npwp_15_digits(self):
        npwp = NPWP("123456789012345")
        assert npwp.value == "123456789012345"

    def test_invalid_npwp_wrong_length(self):
        with pytest.raises(ValueError, match="must be 15 digits"):
            NPWP("12345678901234")

    def test_invalid_npwp_non_numeric(self):
        with pytest.raises(ValueError, match="must be numeric"):
            NPWP("ABCDEFGHIJKLMNO")


class TestAccountingPeriodVO:
    def test_valid_period(self):
        period = AccountingPeriod(year=2025, month=3)
        assert period.year == 2025
        assert period.month == 3

    def test_invalid_month(self):
        with pytest.raises(ValueError, match="Month must be between 1 and 12"):
            AccountingPeriod(2025, 13)

    def test_period_string_representation(self):
        period = AccountingPeriod(2025, 3)
        assert str(period) == "2025-03"


class TestDateRangeVO:
    def test_valid_range(self):
        start = date(2025, 1, 1)
        end = date(2025, 12, 31)
        dr = DateRange(start, end)
        assert dr.start_date == start
        assert dr.end_date == end

    def test_end_before_start_raises(self):
        with pytest.raises(ValueError, match="End date must be after start date"):
            DateRange(date(2025, 12, 31), date(2025, 1, 1))

    def test_contains_date(self):
        dr = DateRange(date(2025, 1, 1), date(2025, 1, 31))
        assert dr.contains(date(2025, 1, 15)) is True
        assert dr.contains(date(2025, 2, 1)) is False


class TestPercentageVO:
    def test_valid_percentage(self):
        pct = Percentage(Decimal("75.5"))
        assert pct.value == Decimal("75.5")

    def test_percentage_out_of_range(self):
        with pytest.raises(ValueError, match="must be between 0 and 100"):
            Percentage(Decimal("150"))

    def test_of_method(self):
        pct = Percentage(Decimal("20"))
        result = pct.of(Decimal("1000"))
        assert result == Decimal("200")


class TestIdempotencyKeyVO:
    def test_valid_key(self):
        key = IdempotencyKey("abc-123-def-456")
        assert key.value == "abc-123-def-456"

    def test_empty_key_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            IdempotencyKey("")


class TestHashChainLinkVO:
    def test_hash_chain_link(self):
        link = HashChainLink(
            index=1,
            previous_hash="000000",
            current_hash="abc123",
            data_hash="datahash",
            timestamp=date.today(),
        )
        assert link.index == 1
        assert link.previous_hash == "000000"
        assert link.current_hash == "abc123"


class TestExchangeRateVO:
    def test_exchange_rate_creation(self):
        rate = ExchangeRate(currency="USD", rate=Decimal("15200"), effective_date=date(2025, 3, 1))
        assert rate.currency == "USD"
        assert rate.rate == Decimal("15200")

    def test_exchange_rate_positive(self):
        with pytest.raises(ValueError, match="Rate must be positive"):
            ExchangeRate("USD", Decimal("-1"), date.today())
