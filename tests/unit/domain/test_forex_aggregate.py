#!/usr/bin/env python3
"""
Module: test_forex_aggregate.py
Layer: Tests / Unit / Domain

Responsibility:
    Unit tests untuk Foreign Exchange aggregate.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from domain.forex.exchange_rate_vo import ExchangeRate
from domain.forex.forex_transaction_entity import ForexTransaction, ForexTransactionType


class TestForexAggregate:
    def test_exchange_rate_retrieval(self):
        rate = ExchangeRate(currency="USD", rate=Decimal("15200"), effective_date=date.today())
        assert rate.rate == Decimal("15200")

    def test_forex_transaction_gain(self):
        tx = ForexTransaction(
            id=uuid4(),
            amount_fcy=Decimal("10000"),
            rate_buy=Decimal("15000"),
            rate_sell=Decimal("15200"),
            transaction_type=ForexTransactionType.REVALUATION,
        )
        gain = (tx.rate_sell - tx.rate_buy) * tx.amount_fcy
        assert gain == Decimal("2000000")
