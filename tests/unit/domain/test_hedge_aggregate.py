#!/usr/bin/env python3
"""
Module: test_hedge_aggregate.py
Layer: Tests / Unit / Domain

Responsibility:
    Unit tests untuk Hedge accounting aggregate.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from domain.hedge.hedge_instrument import HedgeInstrument, HedgeType


class TestHedgeAggregate:
    def test_hedge_effectiveness(self):
        instrument = HedgeInstrument(
            id=uuid4(),
            instrument_type="forward",
            notional=Decimal("1000000"),
            currency="USD",  # Sesuai perbaikan positional argument sebelumnya
            hedge_type=HedgeType.CASH_FLOW,
            fair_value=Decimal("0"),
        )

        # Tangkap objek baru hasil dari designate
        instrument = instrument.designate(hedged_item_id=uuid4())

        # Tangkap objek baru hasil dari perubahan fair value
        instrument = instrument.record_fair_value_change(Decimal("50000"))

        # Sekarang pengecekan assertion ini akan sukses karena menguji objek yang baru
        assert instrument.fair_value == Decimal("50000")
        assert instrument.accumulated_oci == Decimal("50000")
