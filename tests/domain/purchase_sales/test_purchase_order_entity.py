# tests/domain/purchase_sales/test_purchase_order_entity.py
"""
Comprehensive unit tests for Purchase Order entity.

Covers:
- POItem value object (construction, properties, validation, serialization)
- PurchaseOrderEntity (construction, computed props, item management, status transitions, serialization)
- Repository protocol (abstract method stubs)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from domain.purchase_sales.purchase_order_entity import (
    POItem,
    POStatus,
    POType,
    PurchaseOrderEntity,
    PurchaseOrderEntityRepository,
)

# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def valid_item_kwargs() -> dict[str, Any]:
    """Valid arguments for creating a POItem."""
    return {
        "item_id": uuid4(),
        "item_code": "ITEM-001",
        "item_name": "Test Product",
        "quantity": Decimal("10.000"),
        "unit_price": Decimal("150.00"),
        "discount_percentage": Decimal("10.0"),
        "tax_rate": Decimal("11.0"),
        "received_quantity": Decimal("0"),
        "unit_of_measure": "PCS",
        "expected_delivery_date": datetime.now(UTC) + timedelta(days=7),
    }


@pytest.fixture
def valid_item(valid_item_kwargs) -> POItem:
    """A fully valid POItem instance."""
    return POItem(**valid_item_kwargs)


@pytest.fixture
def valid_po_kwargs(valid_item) -> dict[str, Any]:
    """Valid arguments for creating a PurchaseOrderEntity with one item."""
    now = datetime.now(UTC)
    return {
        "po_id": uuid4(),
        "po_number": "PO-2026-001",
        "po_type": POType.STANDARD,
        "supplier_id": uuid4(),
        "supplier_name": "Supplier XYZ",
        "order_date": now,
        "expected_delivery_date": now + timedelta(days=14),
        "status": POStatus.DRAFT,
        "items": [valid_item],
        "currency": "IDR",
        "shipping_address": "123 Main St",
        "billing_address": "456 Billing Ave",
        "terms": "Net 30",
        "notes": "Initial order",
        "created_at": now,
        "updated_at": now,
        "created_by": "tester",
        "version": 1,
    }


@pytest.fixture
def valid_po(valid_po_kwargs) -> PurchaseOrderEntity:
    """A fully valid PurchaseOrderEntity instance."""
    return PurchaseOrderEntity(**valid_po_kwargs)


@pytest.fixture
def another_item() -> POItem:
    """A second distinct item for testing additions."""
    return POItem(
        item_id=uuid4(),
        item_code="ITEM-002",
        item_name="Another Product",
        quantity=Decimal("5"),
        unit_price=Decimal("200.00"),
        discount_percentage=Decimal("0"),
        tax_rate=Decimal("11"),
        received_quantity=Decimal("0"),
        unit_of_measure="PCS",
        expected_delivery_date=datetime.now(UTC) + timedelta(days=10),
    )


# -----------------------------------------------------------------------------
# Tests for POItem (Value Object)
# -----------------------------------------------------------------------------

class TestPOItem:
    """Test the POItem immutable value object."""

    def test_construction_success(self, valid_item_kwargs):
        """POItem can be constructed with valid data."""
        item = POItem(**valid_item_kwargs)
        assert isinstance(item, POItem)
        assert item.item_id == valid_item_kwargs["item_id"]

    @pytest.mark.parametrize(
        "field, value, expected_error",
        [
            ("quantity", Decimal("0"), "Quantity must be positive"),
            ("quantity", Decimal("-1"), "Quantity must be positive"),
            ("unit_price", Decimal("-5"), "Unit price cannot be negative"),
            ("discount_percentage", Decimal("-1"), "Discount percentage must be between 0 and 100"),
            ("discount_percentage", Decimal("101"), "Discount percentage must be between 0 and 100"),
            ("tax_rate", Decimal("-1"), "Tax rate must be between 0 and 100"),
            ("tax_rate", Decimal("101"), "Tax rate must be between 0 and 100"),
            ("received_quantity", Decimal("-1"), "Received quantity cannot be negative"),
            ("received_quantity", Decimal("999"), "Received quantity 999 exceeds ordered quantity"),
        ],
    )
    def test_validation_raises(self, valid_item_kwargs, field, value, expected_error):
        """Invalid field values raise ValueError."""
        kwargs = valid_item_kwargs.copy()
        kwargs[field] = value
        with pytest.raises(ValueError, match=expected_error):
            POItem(**kwargs)

    def test_timezone_aware_required(self, valid_item_kwargs):
        """expected_delivery_date must be timezone-aware."""
        kwargs = valid_item_kwargs.copy()
        kwargs["expected_delivery_date"] = datetime.now()  # naive
        with pytest.raises(ValueError, match="expected_delivery_date must be timezone-aware"):
            POItem(**kwargs)

    def test_properties(self, valid_item):
        """Computed properties return correct values."""
        item = valid_item
        # Given: quantity=10, unit_price=150, discount=10%, tax=11%
        expected_subtotal = Decimal("1500.000")
        expected_discount = Decimal("150.000")
        expected_net = Decimal("1350.000")
        expected_tax = Decimal("148.500")  # 1350 * 0.11
        expected_total = Decimal("1498.500")
        expected_remaining = Decimal("10.000")

        assert item.subtotal == expected_subtotal
        assert item.discount_amount == expected_discount
        assert item.net_amount == expected_net
        assert item.tax_amount == expected_tax
        assert item.total_amount == expected_total
        assert item.remaining_quantity == expected_remaining

    def test_to_dict(self, valid_item):
        """to_dict returns a serializable dictionary."""
        d = valid_item.to_dict()
        assert d["item_id"] == str(valid_item.item_id)
        assert d["item_code"] == valid_item.item_code
        assert d["quantity"] == str(valid_item.quantity)
        assert d["subtotal"] == str(valid_item.subtotal)
        assert d["expected_delivery_date"] is not None  # our fixture has it


# -----------------------------------------------------------------------------
# Tests for PurchaseOrderEntity (Aggregate Root)
# -----------------------------------------------------------------------------

class TestPurchaseOrderEntity:
    """Test the PurchaseOrderEntity immutable aggregate."""

    def test_construction_success(self, valid_po_kwargs):
        """PurchaseOrderEntity can be constructed with valid data."""
        po = PurchaseOrderEntity(**valid_po_kwargs)
        assert isinstance(po, PurchaseOrderEntity)
        assert po.po_id == valid_po_kwargs["po_id"]
        assert po.status == POStatus.DRAFT
        assert len(po.items) == 1

    @pytest.mark.parametrize(
        "field, value, expected_error",
        [
            ("po_number", "AB", "PO number must be at least 3 characters"),
            ("order_date", None, "order_date"),  # will fail type check, but we'll handle
            ("expected_delivery_date", None, "expected_delivery_date"),
            ("currency", "JPY", "Unsupported currency"),
            ("version", 0, "Version must be >= 1"),
        ],
    )
    def test_validation_raises(self, valid_po_kwargs, field, value, expected_error):
        """Invalid field values raise ValueError."""
        kwargs = valid_po_kwargs.copy()
        if field in ("order_date", "expected_delivery_date"):
            # Set a datetime that violates the invariant
            if field == "order_date":
                kwargs["order_date"] = kwargs["expected_delivery_date"] + timedelta(days=1)
                with pytest.raises(ValueError, match="Expected delivery date must be after order date"):
                    PurchaseOrderEntity(**kwargs)
                return
            else:
                kwargs["expected_delivery_date"] = kwargs["order_date"] - timedelta(days=1)
                with pytest.raises(ValueError, match="Expected delivery date must be after order date"):
                    PurchaseOrderEntity(**kwargs)
                return
        kwargs[field] = value
        with pytest.raises(ValueError, match=expected_error):
            PurchaseOrderEntity(**kwargs)

    def test_duplicate_item_ids_raises(self, valid_po_kwargs, valid_item):
        """Duplicate item IDs in items list trigger ValueError."""
        items = [valid_item, valid_item]  # same id
        valid_po_kwargs["items"] = items
        with pytest.raises(ValueError, match="Duplicate item IDs found"):
            PurchaseOrderEntity(**valid_po_kwargs)

    def test_timezone_aware_required(self, valid_po_kwargs):
        """All datetimes must be timezone-aware."""
        # order_date naive
        kwargs = valid_po_kwargs.copy()
        kwargs["order_date"] = datetime.now()
        with pytest.raises(ValueError, match="Dates must be timezone-aware"):
            PurchaseOrderEntity(**kwargs)

        # created_at naive
        kwargs = valid_po_kwargs.copy()
        kwargs["created_at"] = datetime.now()
        with pytest.raises(ValueError, match="Timestamps must be timezone-aware"):
            PurchaseOrderEntity(**kwargs)

    def test_total_amount(self, valid_po, another_item):
        """total_amount sums all item totals."""
        po = valid_po
        initial_total = po.total_amount
        # Add another item
        po2 = po.add_item(another_item, "tester")
        assert po2.total_amount == initial_total + another_item.total_amount

    def test_total_received_amount(self, valid_po):
        """total_received_amount sums proportional received value."""
        # Initially no received quantity => 0
        assert valid_po.total_received_amount == Decimal(0)

        # Receive half of the item
        item = valid_po.items[0]
        po2 = valid_po.update_received_quantity(item.item_id, Decimal("5"), "tester")
        # total_received_amount should be 50% of the item's total
        expected = item.total_amount * Decimal("0.5")
        assert po2.total_received_amount == expected

        # Receive full quantity
        po3 = po2.update_received_quantity(item.item_id, Decimal("5"), "tester")
        assert po3.total_received_amount == item.total_amount

    def test_is_fully_received(self, valid_po):
        """is_fully_received returns True only when all items are fully received."""
        assert valid_po.is_fully_received() is False
        item = valid_po.items[0]
        po2 = valid_po.update_received_quantity(item.item_id, item.quantity, "tester")
        assert po2.is_fully_received() is True

    def test_is_overdue(self, valid_po):
        """is_overdue checks delivery date and status."""
        # Not overdue if not past delivery date
        assert valid_po.is_overdue() is False

        # Past delivery date and not fully received/closed/cancelled => overdue
        future = valid_po.expected_delivery_date + timedelta(days=1)
        assert valid_po.is_overdue(as_of=future) is True

        # Fully received => not overdue even if past date
        item = valid_po.items[0]
        po2 = valid_po.update_received_quantity(item.item_id, item.quantity, "tester")
        po3 = po2.receive()  # status becomes FULLY_RECEIVED
        assert po3.is_overdue(as_of=future) is False

        # Cancelled => not overdue
        cancelled = valid_po.cancel("tester", "test")
        assert cancelled.is_overdue(as_of=future) is False

    def test_get_item(self, valid_po, another_item):
        """get_item returns the item if found, else None."""
        item = valid_po.items[0]
        assert valid_po.get_item(item.item_id) == item
        assert valid_po.get_item(uuid4()) is None

    def test_add_item(self, valid_po, another_item):
        """add_item returns a new PO with the item added, version incremented."""
        po2 = valid_po.add_item(another_item, "tester")
        assert po2 is not valid_po
        assert len(po2.items) == len(valid_po.items) + 1
        assert po2.items[-1] == another_item
        assert po2.version == valid_po.version + 1
        assert po2.updated_at > valid_po.updated_at

    def test_remove_item(self, valid_po):
        """remove_item removes an item by ID."""
        item_id = valid_po.items[0].item_id
        po2 = valid_po.remove_item(item_id, "tester")
        assert len(po2.items) == 0
        assert po2.version == valid_po.version + 1

    def test_update_item_quantity(self, valid_po):
        """update_item_quantity changes quantity, preserving other fields."""
        item = valid_po.items[0]
        new_qty = Decimal("20")
        po2 = valid_po.update_item_quantity(item.item_id, new_qty, "tester")
        updated = po2.get_item(item.item_id)
        assert updated is not None
        assert updated.quantity == new_qty
        assert updated.unit_price == item.unit_price
        assert updated.received_quantity == item.received_quantity
        assert po2.version == valid_po.version + 1

        # Cannot reduce below received quantity
        with pytest.raises(ValueError, match="cannot be less than already received"):
            valid_po.update_item_quantity(item.item_id, Decimal("5"), "tester")

    def test_update_item_unit_price(self, valid_po):
        """update_item_unit_price changes unit price, preserves other fields."""
        item = valid_po.items[0]
        new_price = Decimal("200")
        po2 = valid_po.update_item_unit_price(item.item_id, new_price, "tester")
        updated = po2.get_item(item.item_id)
        assert updated is not None
        assert updated.unit_price == new_price
        assert updated.quantity == item.quantity
        assert po2.version == valid_po.version + 1

    def test_update_received_quantity(self, valid_po):
        """update_received_quantity increases received quantity and updates status on receive."""
        item = valid_po.items[0]
        additional = Decimal("3")
        po2 = valid_po.update_received_quantity(item.item_id, additional, "tester")
        updated = po2.get_item(item.item_id)
        assert updated.received_quantity == additional
        assert po2.version == valid_po.version + 1

        # Exceeding quantity raises
        with pytest.raises(ValueError, match="Received quantity .* exceeds ordered quantity"):
            valid_po.update_received_quantity(item.item_id, Decimal("999"), "tester")

        # After full receipt, status changes via receive()
        po3 = valid_po.update_received_quantity(item.item_id, item.quantity, "tester")
        po4 = po3.receive()
        assert po4.status == POStatus.FULLY_RECEIVED

    # ---- Status transitions ----

    def test_submit(self, valid_po):
        """submit transitions DRAFT -> SUBMITTED."""
        po2 = valid_po.submit("tester")
        assert po2.status == POStatus.SUBMITTED
        assert po2.version == valid_po.version + 1
        # Cannot submit from non-DRAFT
        with pytest.raises(ValueError, match="Cannot submit PO in status"):
            po2.submit("tester")

    def test_approve(self, valid_po):
        """approve transitions SUBMITTED -> APPROVED."""
        po_submitted = valid_po.submit("tester")
        po2 = po_submitted.approve("approver")
        assert po2.status == POStatus.APPROVED
        # Cannot approve from non-SUBMITTED
        with pytest.raises(ValueError, match="Cannot approve PO in status"):
            valid_po.approve("approver")  # DRAFT

    def test_receive(self, valid_po):
        """receive sets status to PARTIALLY_RECEIVED or FULLY_RECEIVED."""
        item = valid_po.items[0]
        # Partial receipt
        po2 = valid_po.update_received_quantity(item.item_id, Decimal("5"), "tester")
        po3 = po2.receive()
        assert po3.status == POStatus.PARTIALLY_RECEIVED

        # Full receipt
        po4 = po3.update_received_quantity(item.item_id, Decimal("5"), "tester")
        po5 = po4.receive()
        assert po5.status == POStatus.FULLY_RECEIVED

    def test_close(self, valid_po):
        """close transitions FULLY_RECEIVED -> CLOSED."""
        item = valid_po.items[0]
        po2 = valid_po.update_received_quantity(item.item_id, item.quantity, "tester")
        po3 = po2.receive()
        po4 = po3.close("tester")
        assert po4.status == POStatus.CLOSED

        # Cannot close from non-FULLY_RECEIVED
        with pytest.raises(ValueError, match="Cannot close PO in status"):
            valid_po.close("tester")

    def test_cancel(self, valid_po):
        """cancel transitions to CANCELLED from allowed statuses."""
        # From DRAFT
        cancelled = valid_po.cancel("tester", "test reason")
        assert cancelled.status == POStatus.CANCELLED
        assert "Cancelled: test reason" in cancelled.notes

        # From SUBMITTED
        submitted = valid_po.submit("tester")
        cancelled2 = submitted.cancel("tester", "change mind")
        assert cancelled2.status == POStatus.CANCELLED

        # Cannot cancel from FULLY_RECEIVED or CLOSED
        item = valid_po.items[0]
        po2 = valid_po.update_received_quantity(item.item_id, item.quantity, "tester")
        po3 = po2.receive()
        with pytest.raises(ValueError, match="Cannot cancel PO in status"):
            po3.cancel("tester", "too late")

    def test_to_dict(self, valid_po):
        """to_dict returns a serializable dictionary."""
        d = valid_po.to_dict()
        assert d["po_id"] == str(valid_po.po_id)
        assert d["po_number"] == valid_po.po_number
        assert d["status"] == valid_po.status.value
        assert d["total_amount"] == str(valid_po.total_amount)
        assert "items" in d
        assert len(d["items"]) == len(valid_po.items)
        assert d["version"] == valid_po.version


# -----------------------------------------------------------------------------
# Tests for Repository Protocol
# -----------------------------------------------------------------------------

class TestPurchaseOrderEntityRepository:
    """Test the abstract repository protocol."""

    def test_methods_raise_not_implemented(self):
        """All repository methods raise NotImplementedError."""
        repo = PurchaseOrderEntityRepository()
        with pytest.raises(NotImplementedError):
            repo.get_by_id(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_number("PO-123", uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_supplier(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_overdue(uuid4())
        with pytest.raises(NotImplementedError):
            repo.save(valid_po, uuid4())
        with pytest.raises(NotImplementedError):
            repo.delete(uuid4(), uuid4())
