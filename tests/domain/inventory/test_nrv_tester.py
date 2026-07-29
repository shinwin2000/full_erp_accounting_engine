# tests/domain/inventory/test_nrv_tester.py
"""
Comprehensive unit tests for NRV Tester.

Covers:
- Enums: NRVTestResult, WriteDownMethod (members, from_string)
- NRVTestItem: construction, to_dict, dummy fields
- NRVTestResultSummary: construction, to_dict
- NRVTester: test_item, test_items (with PER_ITEM, PER_CATEGORY, PER_WAREHOUSE),
  identify_obsolete_items, calculate_provision_for_obsolescence, generate_report
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from domain.inventory.nrv_tester import (
    NRVTester,
    NRVTestItem,
    NRVTestResult,
    NRVTestResultSummary,
    WriteDownMethod,
)

# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def item_mock() -> MagicMock:
    """Mock item with typical inventory attributes."""
    item = MagicMock()
    item.item_id = uuid4()
    item.id = item.item_id
    item.sku = "SKU-001"
    item.name = "Test Item"
    item.category = "Electronics"
    item.unit_cost = Decimal("100.00")
    item.standard_cost = Decimal("95.00")
    item.selling_price = Decimal("150.00")
    return item


@pytest.fixture
def item_no_selling_price() -> MagicMock:
    """Item without selling price (uses standard_cost * 1.2)."""
    item = MagicMock()
    item.item_id = uuid4()
    item.sku = "SKU-002"
    item.name = "No Price Item"
    item.category = "Hardware"
    item.unit_cost = Decimal("50.00")
    item.standard_cost = Decimal("50.00")
    item.selling_price = Decimal(0)  # no selling price
    return item


@pytest.fixture
def nrv_tester() -> NRVTester:
    return NRVTester(default_cost_to_sell_percentage=Decimal("5"))


# -----------------------------------------------------------------------------
# Tests for Enums
# -----------------------------------------------------------------------------

class TestNRVTestResult:
    def test_members(self):
        assert NRVTestResult.PASS.value == "pass"
        assert NRVTestResult.FAIL.value == "fail"
        assert NRVTestResult.PARTIAL.value == "partial"
        assert NRVTestResult.NOT_APPLICABLE.value == "na"

    def test_from_string(self):
        assert NRVTestResult.from_string("pass") == NRVTestResult.PASS
        assert NRVTestResult.from_string("FAIL") == NRVTestResult.FAIL
        assert NRVTestResult.from_string("partial") == NRVTestResult.PARTIAL
        assert NRVTestResult.from_string("na") == NRVTestResult.NOT_APPLICABLE
        # Unknown -> NOT_APPLICABLE
        assert NRVTestResult.from_string("unknown") == NRVTestResult.NOT_APPLICABLE


class TestWriteDownMethod:
    def test_members(self):
        assert WriteDownMethod.PER_ITEM.value == "per_item"
        assert WriteDownMethod.PER_CATEGORY.value == "per_category"
        assert WriteDownMethod.PER_WAREHOUSE.value == "per_warehouse"

    def test_from_string(self):
        assert WriteDownMethod.from_string("per_item") == WriteDownMethod.PER_ITEM
        assert WriteDownMethod.from_string("PER_CATEGORY") == WriteDownMethod.PER_CATEGORY
        assert WriteDownMethod.from_string("per_warehouse") == WriteDownMethod.PER_WAREHOUSE
        # Unknown -> PER_ITEM
        assert WriteDownMethod.from_string("unknown") == WriteDownMethod.PER_ITEM


# -----------------------------------------------------------------------------
# Tests for NRVTestItem
# -----------------------------------------------------------------------------

class TestNRVTestItem:
    def test_construction(self):
        item_id = uuid4()
        item = NRVTestItem(
            item_id=item_id,
            item_sku="SKU-003",
            item_name="Test",
            item_category="CatA",
            quantity=Decimal("10"),
            unit_cost=Decimal("100"),
            total_cost=Decimal("1000"),
            estimated_selling_price=Decimal("120"),
            estimated_cost_to_sell=Decimal("10"),
            nrv_per_unit=Decimal("110"),
            nrv_total=Decimal("1100"),
            write_down_needed=False,
            write_down_amount=Decimal(0),
            result=NRVTestResult.PASS,
        )
        assert item.item_id == item_id
        assert item.reorder_point == Decimal(0)
        assert item.safety_stock == Decimal(0)

    def test_to_dict(self):
        item_id = uuid4()
        item = NRVTestItem(
            item_id=item_id,
            item_sku="SKU-004",
            item_name="Dict Test",
            item_category="CatB",
            quantity=Decimal("5"),
            unit_cost=Decimal("200"),
            total_cost=Decimal("1000"),
            estimated_selling_price=Decimal("250"),
            estimated_cost_to_sell=Decimal("20"),
            nrv_per_unit=Decimal("230"),
            nrv_total=Decimal("1150"),
            write_down_needed=False,
            write_down_amount=Decimal(0),
            result=NRVTestResult.PASS,
            reorder_point=Decimal("10"),
            safety_stock=Decimal("5"),
        )
        d = item.to_dict()
        assert d["item_id"] == str(item_id)
        assert d["item_sku"] == "SKU-004"
        assert d["quantity"] == "5"
        assert d["total_cost"] == "1000"
        assert d["nrv_total"] == "1150"
        assert d["reorder_point"] == "10"
        assert d["safety_stock"] == "5"


# -----------------------------------------------------------------------------
# Tests for NRVTestResultSummary
# -----------------------------------------------------------------------------

class TestNRVTestResultSummary:
    def test_construction(self):
        item = NRVTestItem(
            item_id=uuid4(),
            item_sku="SKU-005",
            item_name="Sample",
            quantity=Decimal(1),
            unit_cost=Decimal(100),
            total_cost=Decimal(100),
            estimated_selling_price=Decimal(120),
            estimated_cost_to_sell=Decimal(10),
            nrv_per_unit=Decimal(110),
            nrv_total=Decimal(110),
            write_down_needed=False,
            write_down_amount=Decimal(0),
            result=NRVTestResult.PASS,
        )
        summary = NRVTestResultSummary(
            test_date=datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
            total_items_tested=1,
            items_with_write_down=0,
            total_cost_before=Decimal("100"),
            total_nrv=Decimal("110"),
            total_write_down=Decimal("0"),
            write_down_method=WriteDownMethod.PER_ITEM,
            details=[item],
        )
        assert summary.total_items_tested == 1
        assert summary.details[0] is item

    def test_to_dict(self):
        item = NRVTestItem(
            item_id=uuid4(),
            item_sku="SKU-006",
            item_name="Summary Item",
            quantity=Decimal(2),
            unit_cost=Decimal(50),
            total_cost=Decimal(100),
            estimated_selling_price=Decimal(60),
            estimated_cost_to_sell=Decimal(5),
            nrv_per_unit=Decimal(55),
            nrv_total=Decimal(110),
            write_down_needed=False,
            write_down_amount=Decimal(0),
            result=NRVTestResult.PASS,
        )
        summary = NRVTestResultSummary(
            test_date=datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
            total_items_tested=1,
            items_with_write_down=0,
            total_cost_before=Decimal("100"),
            total_nrv=Decimal("110"),
            total_write_down=Decimal("0"),
            write_down_method=WriteDownMethod.PER_ITEM,
            details=[item],
        )
        d = summary.to_dict()
        assert d["test_date"] == "2026-01-15T10:00:00+00:00"
        assert d["total_items_tested"] == 1
        assert d["total_nrv"] == "110"
        assert len(d["details"]) == 1


# -----------------------------------------------------------------------------
# Tests for NRVTester
# -----------------------------------------------------------------------------

class TestNRVTester:
    def test_init_default(self):
        tester = NRVTester()
        assert tester.default_cost_to_sell_percentage == Decimal("5")

    def test_init_custom(self):
        tester = NRVTester(Decimal("10"))
        assert tester.default_cost_to_sell_percentage == Decimal("10")

    # ---- test_item ----

    def test_test_item_with_selling_price(self, nrv_tester, item_mock):
        result = nrv_tester.test_item(
            item_mock,
            quantity=Decimal("10"),
            estimated_selling_price=Decimal("150"),
            estimated_cost_to_sell=Decimal("10"),
        )
        assert result.item_id == item_mock.item_id
        assert result.item_sku == "SKU-001"
        assert result.quantity == Decimal("10")
        assert result.unit_cost == Decimal("100")
        assert result.total_cost == Decimal("1000")
        assert result.estimated_selling_price == Decimal("150")
        assert result.estimated_cost_to_sell == Decimal("10")
        assert result.nrv_per_unit == Decimal("140")  # 150-10
        assert result.nrv_total == Decimal("1400")    # 140*10
        assert result.write_down_needed is False
        assert result.write_down_amount == Decimal(0)
        assert result.result == NRVTestResult.PASS

    def test_test_item_no_selling_price(self, nrv_tester, item_no_selling_price):
        # selling_price is 0, so default = standard_cost * 1.2 = 60
        # cost_to_sell = selling_price * 5% = 60 * 0.05 = 3
        # nrv_per_unit = 60 - 3 = 57
        # total_cost = 50 * 10 = 500, nrv_total = 57 * 10 = 570 -> no write-down
        result = nrv_tester.test_item(
            item_no_selling_price,
            quantity=Decimal("10"),
        )
        assert result.estimated_selling_price == Decimal("60")  # 50 * 1.2
        assert result.estimated_cost_to_sell == Decimal("3")   # 60 * 0.05
        assert result.nrv_per_unit == Decimal("57")
        assert result.nrv_total == Decimal("570")
        assert result.write_down_needed is False
        assert result.result == NRVTestResult.PASS

    def test_test_item_with_write_down(self, nrv_tester, item_mock):
        # Set selling_price low to trigger write-down
        result = nrv_tester.test_item(
            item_mock,
            quantity=Decimal("10"),
            estimated_selling_price=Decimal("80"),
            estimated_cost_to_sell=Decimal("10"),
        )
        assert result.estimated_selling_price == Decimal("80")
        assert result.nrv_per_unit == Decimal("70")  # 80-10
        assert result.nrv_total == Decimal("700")
        assert result.total_cost == Decimal("1000")
        assert result.write_down_needed is True
        assert result.write_down_amount == Decimal("300")  # 1000-700
        assert result.result == NRVTestResult.FAIL

    # ---- test_items ----

    def test_test_items_per_item(self, nrv_tester, item_mock, item_no_selling_price):
        items = [
            (item_mock, Decimal("10")),   # cost 100, selling 150 -> no write-down
            (item_no_selling_price, Decimal("5")),  # cost 50, sell ~60 -> no write-down
        ]
        summary = nrv_tester.test_items(items, method=WriteDownMethod.PER_ITEM)
        assert summary.total_items_tested == 2
        assert summary.items_with_write_down == 0
        assert summary.total_write_down == Decimal(0)
        assert summary.write_down_method == WriteDownMethod.PER_ITEM
        # total_cost_before = (100*10) + (50*5) = 1000 + 250 = 1250
        assert summary.total_cost_before == Decimal("1250.00")
        # total_nrv = (140*10) + (57*5) = 1400 + 285 = 1685
        assert summary.total_nrv == Decimal("1685.00")

    def test_test_items_per_item_with_write_down(self, nrv_tester, item_mock):
        # Make first item have write-down (selling price low)
        # Second item normal
        item2 = MagicMock()
        item2.item_id = uuid4()
        item2.sku = "SKU-003"
        item2.name = "Item2"
        item2.category = "Category A"
        item2.unit_cost = Decimal("50")
        item2.selling_price = Decimal("120")
        items = [
            (item_mock, Decimal("10")),   # cost 100, sell 80 -> write-down
            (item2, Decimal("5")),        # cost 50, sell 120 -> no write-down
        ]
        summary = nrv_tester.test_items(
            items,
            method=WriteDownMethod.PER_ITEM,
            estimated_selling_price=Decimal("80"),  # only for first? but test_items doesn't accept per-item, it uses test_item with default selling_price. So we need to set selling_price on the mock.
            # Actually test_items uses test_item which uses item.selling_price. So we set it on mocks.
        )
        # We need to set selling_price on item_mock to 80
        item_mock.selling_price = Decimal("80")
        summary = nrv_tester.test_items(items, method=WriteDownMethod.PER_ITEM)
        # First item: total_cost = 100*10=1000, nrv = (80 - 80*0.05)*10 = (80-4)*10 = 760, write-down = 240
        # Second item: cost 50*5=250, nrv = (120 - 120*0.05)*5 = (120-6)*5 = 570, no write-down
        assert summary.total_write_down == Decimal("240.00")
        assert summary.items_with_write_down == 1

    def test_test_items_per_category(self, nrv_tester, item_mock):
        # Create two items in same category, one with write-down
        item1 = item_mock
        item1.category = "Electronics"
        item1.selling_price = Decimal("80")  # will cause write-down
        item1.unit_cost = Decimal("100")
        item2 = MagicMock()
        item2.item_id = uuid4()
        item2.sku = "SKU-004"
        item2.name = "Item4"
        item2.category = "Electronics"
        item2.unit_cost = Decimal("80")
        item2.selling_price = Decimal("150")
        items = [(item1, Decimal("10")), (item2, Decimal("5"))]
        summary = nrv_tester.test_items(items, method=WriteDownMethod.PER_CATEGORY)
        # Per category: total cost = 1000 + 400 = 1400, total nrv = (80-4)*10 + (150-7.5)*5 = 760 + 712.5 = 1472.5, no category write-down because total cost < total nrv.
        # So total_write_down = 0
        assert summary.total_write_down == Decimal("0")
        # But if we make category loss:
        item1.selling_price = Decimal("50")  # nrv per unit = 50-2.5=47.5, total nrv=475
        # item2 selling 150 -> nrv total=712.5, total nrv=1187.5, total cost=1400, loss=212.5 -> write-down
        summary2 = nrv_tester.test_items(items, method=WriteDownMethod.PER_CATEGORY)
        assert summary2.total_write_down == Decimal("212.50")

    def test_test_items_per_warehouse(self, nrv_tester, item_mock):
        item1 = item_mock
        item1.selling_price = Decimal("50")
        item1.unit_cost = Decimal("100")
        item2 = MagicMock()
        item2.item_id = uuid4()
        item2.sku = "SKU-005"
        item2.name = "Item5"
        item2.category = "Misc"
        item2.unit_cost = Decimal("80")
        item2.selling_price = Decimal("60")
        items = [(item1, Decimal("10")), (item2, Decimal("5"))]
        summary = nrv_tester.test_items(items, method=WriteDownMethod.PER_WAREHOUSE)
        # Total cost = 1000 + 400 = 1400
        # total nrv = (50-2.5)*10 + (60-3)*5 = 475 + 285 = 760
        # total_write_down = 1400 - 760 = 640
        assert summary.total_write_down == Decimal("640.00")

    # ---- identify_obsolete_items ----

    def test_identify_obsolete_items(self, nrv_tester, item_mock):
        # Set selling price to 100, cost 80, so no write-down normally
        item_mock.selling_price = Decimal("100")
        item_mock.unit_cost = Decimal("80")
        # Use last_movement_date old enough
        old_date = date.today() - timedelta(days=400)
        items = [(item_mock, Decimal("10"))]
        obsolete = nrv_tester.identify_obsolete_items(
            items,
            slow_moving_days=365,
            last_movement_date=old_date,
        )
        # Should markdown 50%: selling_price becomes 50, cost_to_sell = 50*5% = 2.5, nrv = 47.5, total nrv = 475, cost = 800, write-down = 325
        assert len(obsolete) == 1
        assert obsolete[0].item_id == item_mock.item_id
        assert obsolete[0].estimated_selling_price == Decimal("50")  # 100 * 0.5
        assert obsolete[0].write_down_needed is True
        assert obsolete[0].write_down_amount == Decimal("325.00")

        # If last_movement_date is recent, no items obsolete
        recent_date = date.today() - timedelta(days=10)
        obsolete2 = nrv_tester.identify_obsolete_items(
            items,
            slow_moving_days=365,
            last_movement_date=recent_date,
        )
        assert len(obsolete2) == 0

    # ---- calculate_provision_for_obsolescence ----

    def test_calculate_provision_for_obsolescence(self, nrv_tester, item_mock):
        item_mock.unit_cost = Decimal("100")
        items = [(item_mock, Decimal("10"))]
        provision_percentages = {
            0: Decimal("0.05"),   # 5% for 0+ days
            90: Decimal("0.10"),  # 10% for 90+ days
            180: Decimal("0.20"), # 20% for 180+ days
        }

        # Without aging_getter, days_in_stock=0 -> uses 0 threshold -> 5%
        provision = nrv_tester.calculate_provision_for_obsolescence(
            items, provision_percentages
        )
        # cost = 100*10 = 1000, provision = 1000 * 0.05 = 50
        assert provision == Decimal("50.00")

        # With aging_getter that returns 100 days -> uses 10%
        def aging_getter(item):
            return 100
        provision2 = nrv_tester.calculate_provision_for_obsolescence(
            items, provision_percentages, aging_days_getter=aging_getter
        )
        assert provision2 == Decimal("100.00")  # 1000 * 0.1

        # If aging_getter returns 200 days -> 20%
        def aging_getter2(item):
            return 200
        provision3 = nrv_tester.calculate_provision_for_obsolescence(
            items, provision_percentages, aging_days_getter=aging_getter2
        )
        assert provision3 == Decimal("200.00")  # 1000 * 0.2

    # ---- generate_report ----

    def test_generate_report(self, nrv_tester, item_mock):
        item_mock.selling_price = Decimal("80")
        item_mock.unit_cost = Decimal("100")
        items = [(item_mock, Decimal("10"))]
        summary = nrv_tester.test_items(items, method=WriteDownMethod.PER_ITEM)
        report = nrv_tester.generate_report(summary)
        assert report["test_date"] == summary.test_date.isoformat()
        assert report["total_items_tested"] == 1
        assert report["items_with_write_down"] == 1
        assert report["total_write_down"] == "240.00"  # from earlier calculation
        assert report["write_down_method"] == "per_item"
        assert "write_down_percentage" in report
        assert len(report["items"]) == 1
        assert report["items"][0]["item_sku"] == "SKU-001"
        assert report["items"][0]["write_down_needed"] is True
