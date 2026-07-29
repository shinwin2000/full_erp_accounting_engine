# test_sales_order_entity.py
# Comprehensive tests for sales_order_entity.py

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.purchase_sales.sales_order_entity import (
    SalesOrderEntity,
    SalesOrderEntityRepository,
    SOItem,
    SOStatus,
    SOType,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def valid_so_item():
    """Create a valid SOItem."""
    return SOItem(
        item_id=uuid4(),
        item_code="ITEM-001",
        item_name="Product A",
        quantity=Decimal("10"),
        unit_price=Decimal("100"),
        discount_percentage=Decimal("0"),
        tax_rate=Decimal("11"),
        delivered_quantity=Decimal("0"),
        unit_of_measure="PCS",
    )


@pytest.fixture
def another_so_item():
    """Another valid SOItem."""
    return SOItem(
        item_id=uuid4(),
        item_code="ITEM-002",
        item_name="Product B",
        quantity=Decimal("5"),
        unit_price=Decimal("200"),
        discount_percentage=Decimal("10"),
        tax_rate=Decimal("11"),
        delivered_quantity=Decimal("0"),
        unit_of_measure="BOX",
    )


@pytest.fixture
def valid_sales_order(valid_so_item):
    """Create a valid SalesOrderEntity with one item."""
    now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
    delivery_date = now + timedelta(days=30)
    return SalesOrderEntity(
        so_id=uuid4(),
        so_number="SO-001",
        so_type=SOType.STANDARD,
        customer_id=uuid4(),
        customer_name="Customer A",
        order_date=now,
        requested_delivery_date=delivery_date,
        status=SOStatus.DRAFT,
        items=[valid_so_item],
        currency="IDR",
        shipping_address="Jl. Sudirman No. 1",
        billing_address="Jl. Sudirman No. 1",
        notes="Test SO",
        created_by="system",
    )


@pytest.fixture
def approved_so(valid_sales_order):
    """Return an approved SO."""
    return valid_sales_order.approve(approved_by="manager")


@pytest.fixture
def delivered_so(valid_sales_order, valid_so_item):
    """Return an SO with some delivered quantity."""
    # First approve
    approved = valid_sales_order.approve("manager")
    # Update delivered quantity for the item
    so_with_delivery = approved.update_delivered_quantity(
        item_id=valid_so_item.item_id,
        additional_delivered=Decimal("5"),
        updated_by="warehouse",
    )
    # Update status via deliver()
    return so_with_delivery.deliver()


# ============================================================================
# Tests for Enums
# ============================================================================

class TestSOStatus:
    def test_members(self):
        assert SOStatus.DRAFT.value == "draft"
        assert SOStatus.APPROVED.value == "approved"
        assert SOStatus.PARTIALLY_DELIVERED.value == "partial"
        assert SOStatus.FULLY_DELIVERED.value == "fully_delivered"
        assert SOStatus.INVOICED.value == "invoiced"
        assert SOStatus.CANCELLED.value == "cancelled"
        assert SOStatus.CLOSED.value == "closed"


class TestSOType:
    def test_members(self):
        assert SOType.STANDARD.value == "standard"
        assert SOType.RUSH.value == "rush"
        assert SOType.BACKORDER.value == "backorder"
        assert SOType.CONSIGNMENT.value == "consignment"


# ============================================================================
# Tests for SOItem
# ============================================================================

class TestSOItem:
    def test_construction_valid(self, valid_so_item):
        assert valid_so_item.item_code == "ITEM-001"
        assert valid_so_item.quantity == Decimal("10")
        assert valid_so_item.unit_price == Decimal("100")
        assert valid_so_item.discount_percentage == Decimal("0")
        assert valid_so_item.tax_rate == Decimal("11")
        assert valid_so_item.delivered_quantity == Decimal("0")

    def test_validation_quantity_zero(self):
        with pytest.raises(ValueError, match="Quantity must be positive"):
            SOItem(
                item_id=uuid4(),
                item_code="ITEM-001",
                item_name="Product",
                quantity=Decimal("0"),
                unit_price=Decimal("100"),
            )

    def test_validation_quantity_negative(self):
        with pytest.raises(ValueError, match="Quantity must be positive"):
            SOItem(
                item_id=uuid4(),
                item_code="ITEM-001",
                item_name="Product",
                quantity=Decimal("-1"),
                unit_price=Decimal("100"),
            )

    def test_validation_unit_price_negative(self):
        with pytest.raises(ValueError, match="Unit price cannot be negative"):
            SOItem(
                item_id=uuid4(),
                item_code="ITEM-001",
                item_name="Product",
                quantity=Decimal("1"),
                unit_price=Decimal("-10"),
            )

    def test_validation_discount_out_of_range(self):
        with pytest.raises(ValueError, match="between 0 and 100"):
            SOItem(
                item_id=uuid4(),
                item_code="ITEM-001",
                item_name="Product",
                quantity=Decimal("1"),
                unit_price=Decimal("100"),
                discount_percentage=Decimal("150"),
            )

    def test_validation_tax_rate_out_of_range(self):
        with pytest.raises(ValueError, match="between 0 and 100"):
            SOItem(
                item_id=uuid4(),
                item_code="ITEM-001",
                item_name="Product",
                quantity=Decimal("1"),
                unit_price=Decimal("100"),
                tax_rate=Decimal("200"),
            )

    def test_validation_delivered_quantity_negative(self):
        with pytest.raises(ValueError, match="cannot be negative"):
            SOItem(
                item_id=uuid4(),
                item_code="ITEM-001",
                item_name="Product",
                quantity=Decimal("1"),
                unit_price=Decimal("100"),
                delivered_quantity=Decimal("-1"),
            )

    def test_validation_delivered_quantity_exceeds_quantity(self):
        with pytest.raises(ValueError, match="exceeds ordered quantity"):
            SOItem(
                item_id=uuid4(),
                item_code="ITEM-001",
                item_name="Product",
                quantity=Decimal("1"),
                unit_price=Decimal("100"),
                delivered_quantity=Decimal("2"),
            )

    def test_properties(self):
        item = SOItem(
            item_id=uuid4(),
            item_code="ITEM-001",
            item_name="Product",
            quantity=Decimal("10"),
            unit_price=Decimal("1000"),
            discount_percentage=Decimal("5"),
            tax_rate=Decimal("11"),
            delivered_quantity=Decimal("3"),
        )
        assert item.subtotal == Decimal("10000")
        assert item.discount_amount == Decimal("500")
        assert item.net_amount == Decimal("9500")
        assert item.tax_amount == Decimal("1045")
        assert item.total_amount == Decimal("10545")
        assert item.remaining_quantity == Decimal("7")

    def test_to_dict(self, valid_so_item):
        d = valid_so_item.to_dict()
        assert d["item_code"] == "ITEM-001"
        assert d["quantity"] == "10"
        assert d["unit_price"] == "100"
        assert d["discount_percentage"] == "0"
        assert d["tax_rate"] == "11"
        assert d["delivered_quantity"] == "0"
        assert d["remaining_quantity"] == "10"
        assert d["subtotal"] == "1000"
        assert d["net_amount"] == "1000"
        assert d["tax_amount"] == "110"
        assert d["total_amount"] == "1110"


# ============================================================================
# Tests for SalesOrderEntity
# ============================================================================

class TestSalesOrderEntityConstruction:
    def test_construction_valid(self, valid_sales_order):
        assert valid_sales_order.so_number == "SO-001"
        assert valid_sales_order.status == SOStatus.DRAFT
        assert len(valid_sales_order.items) == 1
        assert valid_sales_order.version == 1
        assert valid_sales_order.total_amount == Decimal("1110")  # 10*100 + 11% tax = 1110

    def test_validation_so_number_too_short(self, valid_so_item):
        with pytest.raises(ValueError, match="at least 3 characters"):
            SalesOrderEntity(
                so_id=uuid4(),
                so_number="SO",
                so_type=SOType.STANDARD,
                customer_id=uuid4(),
                customer_name="Customer",
                order_date=datetime.now(UTC),
                requested_delivery_date=datetime.now(UTC) + timedelta(days=30),
                status=SOStatus.DRAFT,
                items=[valid_so_item],
            )

    def test_validation_delivery_date_before_order_date(self, valid_so_item):
        order_date = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
        delivery_date = datetime(2025, 1, 10, 10, 0, 0, tzinfo=UTC)
        with pytest.raises(ValueError, match="Requested delivery date must be after order date"):
            SalesOrderEntity(
                so_id=uuid4(),
                so_number="SO-001",
                so_type=SOType.STANDARD,
                customer_id=uuid4(),
                customer_name="Customer",
                order_date=order_date,
                requested_delivery_date=delivery_date,
                status=SOStatus.DRAFT,
                items=[valid_so_item],
            )

    def test_validation_currency_unsupported(self, valid_so_item):
        with pytest.raises(ValueError, match="Unsupported currency"):
            SalesOrderEntity(
                so_id=uuid4(),
                so_number="SO-001",
                so_type=SOType.STANDARD,
                customer_id=uuid4(),
                customer_name="Customer",
                order_date=datetime.now(UTC),
                requested_delivery_date=datetime.now(UTC) + timedelta(days=30),
                status=SOStatus.DRAFT,
                items=[valid_so_item],
                currency="XXX",
            )

    def test_validation_version(self, valid_so_item):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            SalesOrderEntity(
                so_id=uuid4(),
                so_number="SO-001",
                so_type=SOType.STANDARD,
                customer_id=uuid4(),
                customer_name="Customer",
                order_date=datetime.now(UTC),
                requested_delivery_date=datetime.now(UTC) + timedelta(days=30),
                status=SOStatus.DRAFT,
                items=[valid_so_item],
                version=0,
            )

    def test_validation_dates_naive(self, valid_so_item):
        naive = datetime(2025, 1, 15, 10, 0, 0)
        with pytest.raises(ValueError, match="Dates must be timezone-aware"):
            SalesOrderEntity(
                so_id=uuid4(),
                so_number="SO-001",
                so_type=SOType.STANDARD,
                customer_id=uuid4(),
                customer_name="Customer",
                order_date=naive,
                requested_delivery_date=naive + timedelta(days=30),
                status=SOStatus.DRAFT,
                items=[valid_so_item],
            )

    def test_validation_duplicate_item_ids(self, valid_so_item):
        same_id = uuid4()
        item1 = SOItem(
            item_id=same_id,
            item_code="ITEM-001",
            item_name="Product A",
            quantity=Decimal("1"),
            unit_price=Decimal("100"),
        )
        item2 = SOItem(
            item_id=same_id,
            item_code="ITEM-001",
            item_name="Product A",
            quantity=Decimal("2"),
            unit_price=Decimal("100"),
        )
        with pytest.raises(ValueError, match="Duplicate item IDs"):
            SalesOrderEntity(
                so_id=uuid4(),
                so_number="SO-001",
                so_type=SOType.STANDARD,
                customer_id=uuid4(),
                customer_name="Customer",
                order_date=datetime.now(UTC),
                requested_delivery_date=datetime.now(UTC) + timedelta(days=30),
                status=SOStatus.DRAFT,
                items=[item1, item2],
            )


class TestSalesOrderEntityProperties:
    def test_total_amount(self, valid_sales_order):
        assert valid_sales_order.total_amount == Decimal("1110")

    def test_total_amount_multiple_items(self, valid_sales_order, another_so_item):
        so = valid_sales_order.add_item(another_so_item, "admin")
        # First item: 10*100=1000, tax 11% => 1110
        # Second item: 5*200=1000, discount 10% => 900, tax 11% => 999
        # Total = 2109
        expected = Decimal("1110") + Decimal("999")
        assert so.total_amount == expected

    def test_total_delivered_amount(self, delivered_so, valid_so_item):
        # Item delivered 5 out of 10: ratio 0.5, item total 1110 * 0.5 = 555
        assert delivered_so.total_delivered_amount == Decimal("555")

    def test_is_fully_delivered(self, valid_sales_order, delivered_so):
        # Not fully delivered initially
        assert valid_sales_order.is_fully_delivered() is False
        # After full delivery
        approved = valid_sales_order.approve("manager")
        fully = approved.update_delivered_quantity(
            item_id=valid_sales_order.items[0].item_id,
            additional_delivered=Decimal("10"),
            updated_by="warehouse",
        )
        assert fully.is_fully_delivered() is True

    def test_is_overdue(self, valid_sales_order):
        # Not overdue initially (delivery date in future)
        assert valid_sales_order.is_overdue() is False
        # Create SO with past delivery date
        now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
        past_delivery = now - timedelta(days=10)
        so_past = SalesOrderEntity(
            so_id=uuid4(),
            so_number="SO-002",
            so_type=SOType.STANDARD,
            customer_id=uuid4(),
            customer_name="Customer",
            order_date=now - timedelta(days=30),
            requested_delivery_date=past_delivery,
            status=SOStatus.APPROVED,
            items=valid_sales_order.items,
            currency="IDR",
        )
        assert so_past.is_overdue(as_of=now) is True
        # But if status is fully delivered, should not be overdue
        delivered_status = so_past.update_delivered_quantity(
            item_id=so_past.items[0].item_id,
            additional_delivered=so_past.items[0].quantity,
            updated_by="warehouse",
        ).deliver()
        assert delivered_status.is_overdue(as_of=now) is False

    def test_get_item(self, valid_sales_order, valid_so_item):
        item = valid_sales_order.get_item(valid_so_item.item_id)
        assert item == valid_so_item
        assert valid_sales_order.get_item(uuid4()) is None


class TestSalesOrderEntityItemManagement:
    def test_add_item(self, valid_sales_order, another_so_item):
        old_count = len(valid_sales_order.items)
        new_so = valid_sales_order.add_item(another_so_item, added_by="admin")
        assert len(new_so.items) == old_count + 1
        assert new_so.items[-1] == another_so_item
        assert new_so.version == valid_sales_order.version + 1
        assert new_so.created_by == "admin"

    def test_remove_item(self, valid_sales_order, valid_so_item):
        old_count = len(valid_sales_order.items)
        item_id = valid_so_item.item_id
        new_so = valid_sales_order.remove_item(item_id, removed_by="admin")
        assert len(new_so.items) == old_count - 1
        assert item_id not in [i.item_id for i in new_so.items]
        assert new_so.version == valid_sales_order.version + 1

    def test_remove_item_not_found(self, valid_sales_order):
        non_existent = uuid4()
        new_so = valid_sales_order.remove_item(non_existent, removed_by="admin")
        assert len(new_so.items) == len(valid_sales_order.items)
        assert new_so.version == valid_sales_order.version + 1

    def test_update_item_quantity(self, valid_sales_order, valid_so_item):
        new_quantity = Decimal("20")
        new_so = valid_sales_order.update_item_quantity(
            item_id=valid_so_item.item_id,
            new_quantity=new_quantity,
            updated_by="admin",
        )
        updated_item = new_so.get_item(valid_so_item.item_id)
        assert updated_item.quantity == new_quantity
        assert new_so.version == valid_sales_order.version + 1
        # Total should change
        assert new_so.total_amount == Decimal("2220")  # 20*100 + 11% tax = 2220

    def test_update_item_quantity_less_than_delivered(self, valid_sales_order, valid_so_item):
        # First deliver some
        so_delivered = valid_sales_order.update_delivered_quantity(
            item_id=valid_so_item.item_id,
            additional_delivered=Decimal("5"),
            updated_by="warehouse",
        )
        with pytest.raises(ValueError, match="New quantity .* cannot be less than already delivered"):
            so_delivered.update_item_quantity(
                item_id=valid_so_item.item_id,
                new_quantity=Decimal("3"),
                updated_by="admin",
            )

    def test_update_item_unit_price(self, valid_sales_order, valid_so_item):
        new_price = Decimal("150")
        new_so = valid_sales_order.update_item_unit_price(
            item_id=valid_so_item.item_id,
            new_unit_price=new_price,
            updated_by="admin",
        )
        updated_item = new_so.get_item(valid_so_item.item_id)
        assert updated_item.unit_price == new_price
        assert new_so.version == valid_sales_order.version + 1
        # Total should change
        assert new_so.total_amount == Decimal("1665")  # 10*150 + 11% tax = 1665

    def test_update_delivered_quantity(self, valid_sales_order, valid_so_item):
        additional = Decimal("3")
        new_so = valid_sales_order.update_delivered_quantity(
            item_id=valid_so_item.item_id,
            additional_delivered=additional,
            updated_by="warehouse",
        )
        updated_item = new_so.get_item(valid_so_item.item_id)
        assert updated_item.delivered_quantity == additional
        assert new_so.version == valid_sales_order.version + 1

    def test_update_delivered_quantity_exceeds(self, valid_sales_order, valid_so_item):
        with pytest.raises(ValueError, match="exceeds ordered quantity"):
            valid_sales_order.update_delivered_quantity(
                item_id=valid_so_item.item_id,
                additional_delivered=Decimal("20"),
                updated_by="warehouse",
            )


class TestSalesOrderEntityStatusTransitions:
    def test_approve(self, valid_sales_order):
        approved = valid_sales_order.approve(approved_by="manager")
        assert approved.status == SOStatus.APPROVED
        assert approved.version == valid_sales_order.version + 1
        assert approved.created_by == "manager"

    def test_approve_non_draft_fails(self, approved_so):
        with pytest.raises(ValueError, match="Cannot approve SO in status approved"):
            approved_so.approve("manager")

    def test_deliver_partial(self, valid_sales_order, valid_so_item):
        # Approve first
        approved = valid_sales_order.approve("manager")
        # Update delivered quantity partially
        so_with_delivery = approved.update_delivered_quantity(
            item_id=valid_so_item.item_id,
            additional_delivered=Decimal("5"),
            updated_by="warehouse",
        )
        delivered = so_with_delivery.deliver()
        assert delivered.status == SOStatus.PARTIALLY_DELIVERED
        assert delivered.version == so_with_delivery.version + 1

    def test_deliver_full(self, valid_sales_order, valid_so_item):
        approved = valid_sales_order.approve("manager")
        so_full = approved.update_delivered_quantity(
            item_id=valid_so_item.item_id,
            additional_delivered=Decimal("10"),
            updated_by="warehouse",
        )
        delivered = so_full.deliver()
        assert delivered.status == SOStatus.FULLY_DELIVERED

    def test_invoice(self, valid_sales_order, valid_so_item):
        # Need fully delivered first
        approved = valid_sales_order.approve("manager")
        so_full = approved.update_delivered_quantity(
            item_id=valid_so_item.item_id,
            additional_delivered=Decimal("10"),
            updated_by="warehouse",
        )
        fully_delivered = so_full.deliver()
        invoiced = fully_delivered.invoice(invoiced_by="finance")
        assert invoiced.status == SOStatus.INVOICED
        assert invoiced.version == fully_delivered.version + 1

    def test_invoice_not_fully_delivered_fails(self, delivered_so):
        with pytest.raises(ValueError, match="Cannot invoice SO in status partial"):
            delivered_so.invoice("finance")

    def test_close(self, valid_sales_order, valid_so_item):
        # Must be invoiced first
        approved = valid_sales_order.approve("manager")
        so_full = approved.update_delivered_quantity(
            item_id=valid_so_item.item_id,
            additional_delivered=Decimal("10"),
            updated_by="warehouse",
        )
        fully = so_full.deliver()
        invoiced = fully.invoice("finance")
        closed = invoiced.close("admin")
        assert closed.status == SOStatus.CLOSED
        assert closed.version == invoiced.version + 1

    def test_close_not_invoiced_fails(self, delivered_so):
        with pytest.raises(ValueError, match="Cannot close SO in status partial"):
            delivered_so.close("admin")

    def test_cancel_draft(self, valid_sales_order):
        cancelled = valid_sales_order.cancel(cancelled_by="admin", reason="Customer requested")
        assert cancelled.status == SOStatus.CANCELLED
        assert "Cancelled: Customer requested" in cancelled.notes
        assert cancelled.version == valid_sales_order.version + 1

    def test_cancel_approved(self, approved_so):
        cancelled = approved_so.cancel(cancelled_by="admin", reason="Stock unavailable")
        assert cancelled.status == SOStatus.CANCELLED

    def test_cancel_fully_delivered_fails(self, valid_sales_order, valid_so_item):
        approved = valid_sales_order.approve("manager")
        so_full = approved.update_delivered_quantity(
            item_id=valid_so_item.item_id,
            additional_delivered=Decimal("10"),
            updated_by="warehouse",
        )
        fully = so_full.deliver()
        with pytest.raises(ValueError, match="Cannot cancel SO in status fully_delivered"):
            fully.cancel("admin", "Too late")

    def test_cancel_invoiced_fails(self, valid_sales_order, valid_so_item):
        approved = valid_sales_order.approve("manager")
        so_full = approved.update_delivered_quantity(
            item_id=valid_so_item.item_id,
            additional_delivered=Decimal("10"),
            updated_by="warehouse",
        )
        fully = so_full.deliver()
        invoiced = fully.invoice("finance")
        with pytest.raises(ValueError, match="Cannot cancel SO in status invoiced"):
            invoiced.cancel("admin", "Too late")


class TestSalesOrderEntitySerialization:
    def test_to_dict(self, valid_sales_order):
        d = valid_sales_order.to_dict()
        assert d["so_number"] == "SO-001"
        assert d["so_type"] == "standard"
        assert d["customer_name"] == "Customer A"
        assert d["status"] == "draft"
        assert d["total_amount"] == str(valid_sales_order.total_amount)
        assert d["total_delivered_amount"] == "0"
        assert d["is_overdue"] is False
        assert len(d["items"]) == 1
        assert d["items"][0]["item_code"] == "ITEM-001"
        assert d["version"] == valid_sales_order.version


# ============================================================================
# Tests for Repository Protocol (abstract)
# ============================================================================

class TestSalesOrderEntityRepository:
    def test_abstract_methods_raise(self):
        repo = SalesOrderEntityRepository()
        with pytest.raises(NotImplementedError):
            repo.get_by_id(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_number("SO-001", uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_customer(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_overdue(uuid4())
        with pytest.raises(NotImplementedError):
            repo.save(MagicMock(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.delete(uuid4(), uuid4())
