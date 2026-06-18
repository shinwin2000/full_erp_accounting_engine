#!/usr/bin/env python3
"""
E2E: Inventory Management to COGS (FIFO)
Alur: Pembelian barang → penjualan → penghitungan COGS dengan metode FIFO → update nilai persediaan.
"""

from __future__ import annotations

from decimal import Decimal

from domain.inventory.item_entity import InventoryItem
from domain.inventory.valuation_method import FifoValuation


def test_inventory_fifo_cogs():
    # 1. Pembelian batch
    item = InventoryItem(code="ITEM-001", name="Komponen A")
    item.receive(quantity=100, unit_cost=Decimal("10000"), date="2026-01-01")  # batch 1
    item.receive(quantity=50, unit_cost=Decimal("12000"), date="2026-02-01")  # batch 2

    # 2. Penjualan 120 unit
    sold_qty = 120
    fifo = FifoValuation(item.transactions)
    cogs = fifo.calculate_cogs(sold_qty)
    # 100 unit dari batch1 @10.000 = 1.000.000
    # 20 unit dari batch2 @12.000 = 240.000
    assert cogs == Decimal("1240000")

    # 3. Update inventory value
    remaining = fifo.get_remaining()
    assert remaining.quantity == 30  # (100+50-120)
    assert remaining.value == Decimal("360000")  # 30 * 12.000
