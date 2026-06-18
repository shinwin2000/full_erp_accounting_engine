#!/usr/bin/env python3
"""
Module: test_goodwill_aggregate.py
Layer: Tests / Unit / Domain
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from domain.goodwill.aggregate_root import GoodwillAggregate


class TestGoodwillAggregate:
    def test_initial_goodwill(self):
        agg = GoodwillAggregate.create(
            acquiree_id=uuid4(),
            goodwill_amount=Decimal("500000000"),
            acquisition_date=date(2025, 1, 1),
        )
        assert agg.goodwill.carrying_value == Decimal("500000000")

        def test_impairment(self):
            agg = GoodwillAggregate.create(uuid4(), Decimal("500000000"), date(2025, 1, 1))
            agg.record_impairment(Decimal("100000000"))
            assert agg.goodwill.carrying_value == Decimal("400000000")
            assert agg.goodwill.accumulated_impairment == Decimal("100000000")
