# test_sales_delivery_note_entity.py
# Comprehensive tests for sales_delivery_note_entity.py

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.purchase_sales.sales_delivery_note_entity import (
    DeliveryItem,
    DeliveryStatus,
    SalesDeliveryNoteEntity,
    SalesDeliveryNoteRepository,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def valid_item():
    """Create a valid DeliveryItem."""
    return DeliveryItem(
        item_id=uuid4(),
        item_code="ITEM-001",
        item_name="Product A",
        so_item_id=uuid4(),
        quantity=Decimal("10"),
        unit_price=Decimal("100"),
        unit_of_measure="PCS",
        batch_number="BATCH-001",
        expiry_date=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
    )


@pytest.fixture
def another_valid_item():
    """Another valid DeliveryItem."""
    return DeliveryItem(
        item_id=uuid4(),
        item_code="ITEM-002",
        item_name="Product B",
        so_item_id=uuid4(),
        quantity=Decimal("5"),
        unit_price=Decimal("200"),
        unit_of_measure="BOX",
    )


@pytest.fixture
def valid_delivery_note(valid_item):
    """Create a valid SalesDeliveryNoteEntity with one item."""
    return SalesDeliveryNoteEntity(
        delivery_id=uuid4(),
        delivery_number="DN-001",
        so_id=uuid4(),
        so_number="SO-001",
        customer_id=uuid4(),
        customer_name="Customer A",
        delivery_date=datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC),
        status=DeliveryStatus.DRAFT,
        items=[valid_item],
        warehouse_id=uuid4(),
        warehouse_name="Main Warehouse",
        shipped_by="",
        notes="Initial delivery",
        created_by="system",
    )


@pytest.fixture
def confirmed_delivery_note(valid_delivery_note):
    """Return a confirmed delivery note."""
    return valid_delivery_note.confirm(confirmed_by="manager")


@pytest.fixture
def shipped_delivery_note(confirmed_delivery_note):
    """Return a shipped delivery note."""
    return confirmed_delivery_note.ship(
        shipped_by="warehouse",
        tracking_number="TRK-001",
        courier_name="DHL",
    )


# ============================================================================
# Tests for DeliveryStatus Enum
# ============================================================================

class TestDeliveryStatus:
    def test_members(self):
        assert DeliveryStatus.DRAFT.value == "draft"
        assert DeliveryStatus.CONFIRMED.value == "confirmed"
        assert DeliveryStatus.SHIPPED.value == "shipped"
        assert DeliveryStatus.DELIVERED.value == "delivered"
        assert DeliveryStatus.CANCELLED.value == "cancelled"


# ============================================================================
# Tests for DeliveryItem (Value Object)
# ============================================================================

class TestDeliveryItem:
    def test_construction_valid(self, valid_item):
        assert valid_item.item_code == "ITEM-001"
        assert valid_item.quantity == Decimal("10")
        assert valid_item.unit_price == Decimal("100")
        assert valid_item.total_amount == Decimal("1000")
        assert valid_item.unit_of_measure == "PCS"
        assert valid_item.batch_number == "BATCH-001"
        assert valid_item.expiry_date == datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    def test_validation_quantity_zero(self):
        with pytest.raises(ValueError, match="Quantity must be positive"):
            DeliveryItem(
                item_id=uuid4(),
                item_code="ITEM-001",
                item_name="Product",
                so_item_id=uuid4(),
                quantity=Decimal("0"),
                unit_price=Decimal("100"),
            )

    def test_validation_quantity_negative(self):
        with pytest.raises(ValueError, match="Quantity must be positive"):
            DeliveryItem(
                item_id=uuid4(),
                item_code="ITEM-001",
                item_name="Product",
                so_item_id=uuid4(),
                quantity=Decimal("-1"),
                unit_price=Decimal("100"),
            )

    def test_validation_unit_price_negative(self):
        with pytest.raises(ValueError, match="Unit price cannot be negative"):
            DeliveryItem(
                item_id=uuid4(),
                item_code="ITEM-001",
                item_name="Product",
                so_item_id=uuid4(),
                quantity=Decimal("1"),
                unit_price=Decimal("-10"),
            )

    def test_validation_expiry_date_naive(self):
        naive = datetime(2026, 1, 1, 12, 0, 0)
        with pytest.raises(ValueError, match="expiry_date must be timezone-aware"):
            DeliveryItem(
                item_id=uuid4(),
                item_code="ITEM-001",
                item_name="Product",
                so_item_id=uuid4(),
                quantity=Decimal("1"),
                unit_price=Decimal("100"),
                expiry_date=naive,
            )

    def test_to_dict(self, valid_item):
        d = valid_item.to_dict()
        assert d["item_code"] == "ITEM-001"
        assert d["quantity"] == "10"
        assert d["unit_price"] == "100"
        assert d["total_amount"] == "1000"
        assert d["expiry_date"] == "2026-01-01T12:00:00+00:00"
        assert d["batch_number"] == "BATCH-001"


# ============================================================================
# Tests for SalesDeliveryNoteEntity
# ============================================================================

class TestSalesDeliveryNoteEntityConstruction:
    def test_construction_valid(self, valid_delivery_note):
        assert valid_delivery_note.delivery_number == "DN-001"
        assert valid_delivery_note.status == DeliveryStatus.DRAFT
        assert len(valid_delivery_note.items) == 1
        assert valid_delivery_note.version == 1
        assert valid_delivery_note.total_amount == Decimal("1000")

    def test_validation_delivery_number_too_short(self, valid_item):
        with pytest.raises(ValueError, match="at least 3 characters"):
            SalesDeliveryNoteEntity(
                delivery_id=uuid4(),
                delivery_number="DN",
                so_id=uuid4(),
                so_number="SO-001",
                customer_id=uuid4(),
                customer_name="Customer",
                delivery_date=datetime.now(UTC),
                status=DeliveryStatus.DRAFT,
                items=[valid_item],
            )

    def test_validation_delivery_date_naive(self, valid_item):
        naive = datetime(2025, 1, 15, 10, 0, 0)
        with pytest.raises(ValueError, match="delivery_date must be timezone-aware"):
            SalesDeliveryNoteEntity(
                delivery_id=uuid4(),
                delivery_number="DN-001",
                so_id=uuid4(),
                so_number="SO-001",
                customer_id=uuid4(),
                customer_name="Customer",
                delivery_date=naive,
                status=DeliveryStatus.DRAFT,
                items=[valid_item],
            )

    def test_validation_version(self, valid_item):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            SalesDeliveryNoteEntity(
                delivery_id=uuid4(),
                delivery_number="DN-001",
                so_id=uuid4(),
                so_number="SO-001",
                customer_id=uuid4(),
                customer_name="Customer",
                delivery_date=datetime.now(UTC),
                status=DeliveryStatus.DRAFT,
                items=[valid_item],
                version=0,
            )

    def test_validation_created_at_naive(self, valid_item):
        naive = datetime(2025, 1, 1, 12, 0, 0)
        with pytest.raises(ValueError, match="Timestamps must be timezone-aware"):
            SalesDeliveryNoteEntity(
                delivery_id=uuid4(),
                delivery_number="DN-001",
                so_id=uuid4(),
                so_number="SO-001",
                customer_id=uuid4(),
                customer_name="Customer",
                delivery_date=datetime.now(UTC),
                status=DeliveryStatus.DRAFT,
                items=[valid_item],
                created_at=naive,
                updated_at=datetime.now(UTC),
            )

    def test_validation_received_at_naive(self, valid_item):
        naive = datetime(2025, 1, 1, 12, 0, 0)
        with pytest.raises(ValueError, match="received_at must be timezone-aware"):
            SalesDeliveryNoteEntity(
                delivery_id=uuid4(),
                delivery_number="DN-001",
                so_id=uuid4(),
                so_number="SO-001",
                customer_id=uuid4(),
                customer_name="Customer",
                delivery_date=datetime.now(UTC),
                status=DeliveryStatus.DRAFT,
                items=[valid_item],
                received_at=naive,
            )

    def test_validation_duplicate_item_ids(self, valid_item):
        # Create two items with the same ID (should raise)
        same_id = uuid4()
        item1 = DeliveryItem(
            item_id=same_id,
            item_code="ITEM-001",
            item_name="Product A",
            so_item_id=uuid4(),
            quantity=Decimal("1"),
            unit_price=Decimal("100"),
        )
        item2 = DeliveryItem(
            item_id=same_id,
            item_code="ITEM-001",
            item_name="Product A",
            so_item_id=uuid4(),
            quantity=Decimal("2"),
            unit_price=Decimal("100"),
        )
        with pytest.raises(ValueError, match="Duplicate item IDs"):
            SalesDeliveryNoteEntity(
                delivery_id=uuid4(),
                delivery_number="DN-001",
                so_id=uuid4(),
                so_number="SO-001",
                customer_id=uuid4(),
                customer_name="Customer",
                delivery_date=datetime.now(UTC),
                status=DeliveryStatus.DRAFT,
                items=[item1, item2],
            )


class TestSalesDeliveryNoteEntityTotalAmount:
    def test_total_amount_single_item(self, valid_delivery_note):
        assert valid_delivery_note.total_amount == Decimal("1000")

    def test_total_amount_multiple_items(self, valid_delivery_note, another_valid_item):
        note = valid_delivery_note.add_item(another_valid_item, "admin")
        assert note.total_amount == Decimal("1000") + Decimal("1000")  # 10*100 + 5*200 = 1000+1000=2000


class TestSalesDeliveryNoteEntityItemManagement:
    def test_add_item(self, valid_delivery_note, another_valid_item):
        old_count = len(valid_delivery_note.items)
        new_note = valid_delivery_note.add_item(another_valid_item, added_by="admin")
        assert len(new_note.items) == old_count + 1
        assert new_note.items[-1] == another_valid_item
        assert new_note.version == valid_delivery_note.version + 1
        assert new_note.created_by == "admin"
        assert new_note.updated_at > valid_delivery_note.updated_at

    def test_remove_item(self, valid_delivery_note, valid_item):
        old_count = len(valid_delivery_note.items)
        item_id = valid_item.item_id
        new_note = valid_delivery_note.remove_item(item_id, removed_by="admin")
        assert len(new_note.items) == old_count - 1
        assert item_id not in [i.item_id for i in new_note.items]
        assert new_note.version == valid_delivery_note.version + 1
        assert new_note.created_by == "admin"

    def test_remove_item_not_found(self, valid_delivery_note):
        # Removing a non-existent item should just return a note with same items (no error)
        non_existent_id = uuid4()
        new_note = valid_delivery_note.remove_item(non_existent_id, removed_by="admin")
        assert len(new_note.items) == len(valid_delivery_note.items)
        assert new_note.version == valid_delivery_note.version + 1  # still increments version


class TestSalesDeliveryNoteEntityStatusTransitions:
    def test_confirm_draft(self, valid_delivery_note):
        confirmed = valid_delivery_note.confirm(confirmed_by="manager")
        assert confirmed.status == DeliveryStatus.CONFIRMED
        assert confirmed.shipped_by == "manager"
        assert confirmed.version == valid_delivery_note.version + 1

    def test_confirm_non_draft_fails(self, confirmed_delivery_note):
        with pytest.raises(ValueError, match="Cannot confirm delivery note in status confirmed"):
            confirmed_delivery_note.confirm("manager")

    def test_ship_confirmed(self, confirmed_delivery_note):
        shipped = confirmed_delivery_note.ship(
            shipped_by="warehouse",
            tracking_number="TRK-001",
            courier_name="DHL",
        )
        assert shipped.status == DeliveryStatus.SHIPPED
        assert shipped.shipped_by == "warehouse"
        assert shipped.tracking_number == "TRK-001"
        assert shipped.courier_name == "DHL"
        assert shipped.version == confirmed_delivery_note.version + 1

    def test_ship_confirmed_without_tracking(self, confirmed_delivery_note):
        shipped = confirmed_delivery_note.ship(shipped_by="warehouse")
        assert shipped.status == DeliveryStatus.SHIPPED
        assert shipped.tracking_number is None  # remains None
        assert shipped.courier_name is None

    def test_ship_non_confirmed_fails(self, valid_delivery_note):
        # Can't ship from DRAFT
        with pytest.raises(ValueError, match="Cannot ship delivery note in status draft"):
            valid_delivery_note.ship(shipped_by="warehouse")

    def test_deliver_shipped(self, shipped_delivery_note):
        delivered = shipped_delivery_note.deliver(received_by="customer_rep")
        assert delivered.status == DeliveryStatus.DELIVERED
        assert delivered.received_by == "customer_rep"
        assert delivered.received_at is not None
        assert delivered.version == shipped_delivery_note.version + 1

    def test_deliver_non_shipped_fails(self, confirmed_delivery_note):
        with pytest.raises(ValueError, match="Cannot mark as delivered in status confirmed"):
            confirmed_delivery_note.deliver("customer")

    def test_cancel_draft(self, valid_delivery_note):
        cancelled = valid_delivery_note.cancel(cancelled_by="admin", reason="Order cancelled")
        assert cancelled.status == DeliveryStatus.CANCELLED
        assert "Cancelled: Order cancelled" in cancelled.notes
        assert cancelled.version == valid_delivery_note.version + 1

    def test_cancel_confirmed(self, confirmed_delivery_note):
        cancelled = confirmed_delivery_note.cancel(cancelled_by="admin", reason="Stock issue")
        assert cancelled.status == DeliveryStatus.CANCELLED
        assert "Cancelled: Stock issue" in cancelled.notes

    def test_cancel_delivered_fails(self, shipped_delivery_note):
        delivered = shipped_delivery_note.deliver(received_by="customer")
        with pytest.raises(ValueError, match="Cannot cancel delivery note in status delivered"):
            delivered.cancel("admin", "Too late")

    def test_cancel_already_cancelled_fails(self, valid_delivery_note):
        cancelled = valid_delivery_note.cancel("admin", "Test")
        with pytest.raises(ValueError, match="Cannot cancel delivery note in status cancelled"):
            cancelled.cancel("admin", "Again")


class TestSalesDeliveryNoteEntitySerialization:
    def test_to_dict(self, valid_delivery_note):
        d = valid_delivery_note.to_dict()
        assert d["delivery_number"] == "DN-001"
        assert d["so_number"] == "SO-001"
        assert d["customer_name"] == "Customer A"
        assert d["status"] == "draft"
        assert d["total_amount"] == "1000"
        assert len(d["items"]) == 1
        assert d["items"][0]["item_code"] == "ITEM-001"
        assert d["version"] == 1


# ============================================================================
# Tests for Repository Protocol (abstract)
# ============================================================================

class TestSalesDeliveryNoteRepository:
    def test_abstract_methods_raise(self):
        repo = SalesDeliveryNoteRepository()
        with pytest.raises(NotImplementedError):
            repo.get_by_id(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_number("DN-001", uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_so(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_customer(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.save(MagicMock(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.delete(uuid4(), uuid4())