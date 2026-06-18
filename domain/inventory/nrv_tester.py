#!/usr/bin/env python3
"""
Module: nrv_tester.py
Layer: 6 - Domain / Inventory
Responsibility: Uji nilai realisasi bersih (lower of cost or NRV).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


# === 1. CONSTANTS & ENUMS ===


class NRVTestResult(Enum):
    """Hasil uji NRV."""

    PASS = "pass"  # Cost <= NRV, no write-down needed
    FAIL = "fail"  # Cost > NRV, write-down needed
    PARTIAL = "partial"  # Some items need write-down
    NOT_APPLICABLE = "na"  # Not applicable for this item

    @classmethod
    def from_string(cls, value: str) -> NRVTestResult:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.NOT_APPLICABLE


class WriteDownMethod(Enum):
    """Metode penurunan nilai."""

    PER_ITEM = "per_item"  # Per item basis
    PER_CATEGORY = "per_category"  # Per kategori
    PER_WAREHOUSE = "per_warehouse"  # Per gudang

    @classmethod
    def from_string(cls, value: str) -> WriteDownMethod:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.PER_ITEM


@dataclass(kw_only=True)
class NRVTestItem:
    """Item yang diuji NRV."""

    item_id: UUID
    item_sku: str
    item_name: str
    item_category: str | None = None
    quantity: Decimal
    unit_cost: Decimal
    total_cost: Decimal
    estimated_selling_price: Decimal
    estimated_cost_to_sell: Decimal
    nrv_per_unit: Decimal
    nrv_total: Decimal
    write_down_needed: bool
    write_down_amount: Decimal
    result: NRVTestResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": str(self.item_id),
            "item_sku": self.item_sku,
            "item_name": self.item_name,
            "item_category": self.item_category,
            "quantity": str(self.quantity),
            "unit_cost": str(self.unit_cost),
            "total_cost": str(self.total_cost),
            "estimated_selling_price": str(self.estimated_selling_price),
            "estimated_cost_to_sell": str(self.estimated_cost_to_sell),
            "nrv_per_unit": str(self.nrv_per_unit),
            "nrv_total": str(self.nrv_total),
            "write_down_needed": self.write_down_needed,
            "write_down_amount": str(self.write_down_amount),
            "result": self.result.value,
        }


@dataclass(kw_only=True)
class NRVTestResultSummary:
    """Ringkasan hasil uji NRV."""

    test_date: datetime
    total_items_tested: int
    items_with_write_down: int
    total_cost_before: Decimal
    total_nrv: Decimal
    total_write_down: Decimal
    write_down_method: WriteDownMethod
    details: list[NRVTestItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_date": self.test_date.isoformat(),
            "total_items_tested": self.total_items_tested,
            "items_with_write_down": self.items_with_write_down,
            "total_cost_before": str(self.total_cost_before),
            "total_nrv": str(self.total_nrv),
            "total_write_down": str(self.total_write_down),
            "write_down_method": self.write_down_method.value,
            "details": [d.to_dict() for d in self.details],
        }


# === 2. NRV TESTER ===


class NRVTester:
    """
    Tester untuk nilai realisasi bersih (NRV).
    """

    def __init__(self, default_cost_to_sell_percentage: Decimal = Decimal("5")):
        """
        Args:
            default_cost_to_sell_percentage: Persentase default biaya penjualan
        """
        self.default_cost_to_sell_percentage = default_cost_to_sell_percentage

    def test_item(
        self,
        item: Any,  # ItemEntity-like
        quantity: Decimal,
        estimated_selling_price: Decimal | None = None,
        estimated_cost_to_sell: Decimal | None = None,
    ) -> NRVTestItem:
        """
        Menguji NRV untuk satu item.
        """
        selling_price = estimated_selling_price or getattr(item, "selling_price", Decimal(0))
        if selling_price <= 0:
            selling_price = getattr(item, "standard_cost", Decimal(0)) * Decimal("1.2")

        cost_to_sell = estimated_cost_to_sell or (
            selling_price * self.default_cost_to_sell_percentage / 100
        )

        nrv_per_unit = selling_price - cost_to_sell
        nrv_total = nrv_per_unit * quantity
        unit_cost = getattr(item, "unit_cost", getattr(item, "standard_cost", Decimal(0)))
        total_cost = unit_cost * quantity

        write_down_needed = total_cost > nrv_total
        write_down_amount = total_cost - nrv_total if write_down_needed else Decimal(0)
        result = NRVTestResult.FAIL if write_down_needed else NRVTestResult.PASS

        return NRVTestItem(
            item_id=getattr(item, "item_id", getattr(item, "id", UUID(int=0))),
            item_sku=getattr(item, "sku", ""),
            item_name=getattr(item, "name", ""),
            item_category=getattr(item, "category", None),
            quantity=quantity,
            unit_cost=unit_cost,
            total_cost=total_cost,
            estimated_selling_price=selling_price,
            estimated_cost_to_sell=cost_to_sell,
            nrv_per_unit=nrv_per_unit,
            nrv_total=nrv_total,
            write_down_needed=write_down_needed,
            write_down_amount=write_down_amount,
            result=result,
        )

    def test_items(
        self,
        items: list[tuple[Any, Decimal]],  # list of (item, quantity)
        method: WriteDownMethod = WriteDownMethod.PER_ITEM,
    ) -> NRVTestResultSummary:
        """
        Menguji NRV untuk multiple items.
        """
        test_items = []
        total_cost_before = Decimal(0)
        total_nrv = Decimal(0)

        for item, quantity in items:
            test_item = self.test_item(item, quantity)
            test_items.append(test_item)
            total_cost_before += test_item.total_cost
            total_nrv += test_item.nrv_total

        # Calculate write-down based on method
        if method == WriteDownMethod.PER_ITEM:
            total_write_down = sum(
                ti.write_down_amount for ti in test_items if ti.write_down_needed
            )
        elif method == WriteDownMethod.PER_CATEGORY:
            category_groups: dict[str, dict[str, Decimal]] = {}
            for ti in test_items:
                cat = ti.item_category or "UNCATEGORIZED"
                if cat not in category_groups:
                    category_groups[cat] = {"cost": Decimal(0), "nrv": Decimal(0)}
                category_groups[cat]["cost"] += ti.total_cost
                category_groups[cat]["nrv"] += ti.nrv_total
            total_write_down = Decimal(0)
            for group in category_groups.values():
                if group["cost"] > group["nrv"]:
                    total_write_down += group["cost"] - group["nrv"]
        else:  # PER_WAREHOUSE or other - treat as total
            total_write_down = max(Decimal(0), total_cost_before - total_nrv)

        items_with_write_down = len([ti for ti in test_items if ti.write_down_needed])

        return NRVTestResultSummary(
            test_date=datetime.now(UTC),
            total_items_tested=len(test_items),
            items_with_write_down=items_with_write_down,
            total_cost_before=total_cost_before.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            total_nrv=total_nrv.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            total_write_down=total_write_down.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            write_down_method=method,
            details=test_items,
        )

    def identify_obsolete_items(
        self,
        items: list[tuple[Any, Decimal]],
        slow_moving_days: int = 365,
        last_movement_date: date | None = None,
    ) -> list[NRVTestItem]:
        """
        Mengidentifikasi item yang mungkin usang (obsolete).
        """
        obsolete_items = []
        today = date.today()
        for item, quantity in items:
            # In production, would check actual last movement date
            # For now, use placeholder
            days_since_last_movement = 0
            if last_movement_date:
                days_since_last_movement = (today - last_movement_date).days

            if days_since_last_movement > slow_moving_days:
                # Markdown 50% for obsolete items
                markdown_price = getattr(item, "selling_price", Decimal(0)) * Decimal("0.5")
                test_item = self.test_item(
                    item,
                    quantity,
                    estimated_selling_price=markdown_price,
                )
                obsolete_items.append(test_item)

        return obsolete_items

    def calculate_provision_for_obsolescence(
        self,
        items: list[tuple[Any, Decimal]],
        provision_percentages: dict[int, Decimal],
        aging_days_getter: callable = None,
    ) -> Decimal:
        """
        Menghitung penyisihan untuk keusangan persediaan.
        """
        provision = Decimal(0)
        today = date.today()

        for item, quantity in items:
            # Get aging days
            if aging_days_getter:
                days_in_stock = aging_days_getter(item)
            else:
                days_in_stock = 0

            for threshold, percentage in sorted(provision_percentages.items()):
                if days_in_stock >= threshold:
                    provision += getattr(item, "unit_cost", Decimal(0)) * quantity * percentage
                    break

        return provision.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def generate_report(self, summary: NRVTestResultSummary) -> dict[str, Any]:
        """
        Menghasilkan laporan uji NRV.
        """
        write_down_percentage = Decimal(0)
        if summary.total_cost_before > 0:
            write_down_percentage = (summary.total_write_down / summary.total_cost_before) * 100

        return {
            "test_date": summary.test_date.isoformat(),
            "total_items_tested": summary.total_items_tested,
            "items_with_write_down": summary.items_with_write_down,
            "total_cost_before": str(summary.total_cost_before),
            "total_nrv": str(summary.total_nrv),
            "total_write_down": str(summary.total_write_down),
            "write_down_method": summary.write_down_method.value,
            "write_down_percentage": str(write_down_percentage.quantize(Decimal("0.01"))),
            "items": [item.to_dict() for item in summary.details],
        }


# === 3. EXPORTS ===

__all__ = [
    "NRVTestItem",
    "NRVTestResult",
    "NRVTestResultSummary",
    "NRVTester",
    "WriteDownMethod",
]
