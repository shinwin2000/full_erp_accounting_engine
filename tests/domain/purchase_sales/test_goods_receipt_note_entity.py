# test_goods_receipt_note_entity.py
# Comprehensive tests for goods_receipt_note_entity.py

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.purchase_sales.goods_receipt_note_entity import (
    GoodsReceiptNoteEntity,
    GoodsReceiptNoteRepository,
    GRNItem,
    GRNStatus,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def valid_grn_item():
    """Create a valid GRNItem."""
    return GRNItem(
        item_id=uuid4(),
        item_code="ITEM-001",
        item_name="Product A",
        po_item_id=uuid4(),
        quantity=Decimal("10"),
        unit_price=Decimal("100"),
        unit_of_measure="PCS",
        batch_number="BATCH-001",
        expiry_date=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        condition="GOOD",
    )


@pytest.fixture
def another_grn_item():
    """Another valid GRNItem."""
    return GRNItem(
        item_id=uuid4(),
        item_code="ITEM-002",
        item_name="Product B",
        po_item_id=uuid4(),
        quantity=Decimal("5"),
        unit_price=Decimal("200"),
        unit_of_measure="BOX",
        condition="GOOD",
    )


@pytest.fixture
def valid_grn(valid_grn_item):
    """Create a valid GoodsReceiptNoteEntity with one item."""
    return GoodsReceiptNoteEntity(
        grn_id=uuid4(),
        grn_number="GRN-001",
        po_id=uuid4(),
        po_number="PO-001",
        supplier_id=uuid4(),
        supplier_name="Supplier A",
        receipt_date=datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC),
        status=GRNStatus.DRAFT,
        items=[valid_grn_item],
        warehouse_id=uuid4(),
        warehouse_name="Main Warehouse",
        received_by="",
        notes="Initial receipt",
        created_by="system",
    )


@pytest.fixture
def confirmed_grn(valid_grn):
    """Return a confirmed GRN."""
    return valid_grn.confirm(confirmed_by="manager")


# ============================================================================
# Tests for GRNStatus Enum
# ============================================================================

class TestGRNStatus:
    def test_members(self):
        assert GRNStatus.DRAFT.value == "draft"
        assert GRNStatus.CONFIRMED.value == "confirmed"
        assert GRNStatus.CANCELLED.value == "cancelled"


# ============================================================================
# Tests for GRNItem (Value Object)
# ============================================================================

class TestGRNItem:
    def test_construction_valid(self, valid_grn_item):
        assert valid_grn_item.item_code == "ITEM-001"
        assert valid_grn_item.quantity == Decimal("10")
        assert valid_grn_item.unit_price == Decimal("100")
        assert valid_grn_item.total_amount == Decimal("1000")
        assert valid_grn_item.condition == "GOOD"
        assert valid_grn_item.batch_number == "BATCH-001"
        assert valid_grn_item.expiry_date == datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    def test_validation_quantity_zero(self):
        with pytest.raises(ValueError, match="Quantity must be positive"):
            GRNItem(
                item_id=uuid4(),
                item_code="ITEM-001",
                item_name="Product",
                po_item_id=uuid4(),
                quantity=Decimal("0"),
                unit_price=Decimal("100"),
            )

    def test_validation_quantity_negative(self):
        with pytest.raises(ValueError, match="Quantity must be positive"):
            GRNItem(
                item_id=uuid4(),
                item_code="ITEM-001",
                item_name="Product",
                po_item_id=uuid4(),
                quantity=Decimal("-1"),
                unit_price=Decimal("100"),
            )

    def test_validation_unit_price_negative(self):
        with pytest.raises(ValueError, match="Unit price cannot be negative"):
            GRNItem(
                item_id=uuid4(),
                item_code="ITEM-001",
                item_name="Product",
                po_item_id=uuid4(),
                quantity=Decimal("1"),
                unit_price=Decimal("-10"),
            )

    def test_validation_condition_invalid(self):
        with pytest.raises(ValueError, match="Invalid condition"):
            GRNItem(
                item_id=uuid4(),
                item_code="ITEM-001",
                item_name="Product",
                po_item_id=uuid4(),
                quantity=Decimal("1"),
                unit_price=Decimal("100"),
                condition="UNKNOWN",
            )

    def test_validation_expiry_date_naive(self):
        naive = datetime(2026, 1, 1, 12, 0, 0)
        with pytest.raises(ValueError, match="expiry_date must be timezone-aware"):
            GRNItem(
                item_id=uuid4(),
                item_code="ITEM-001",
                item_name="Product",
                po_item_id=uuid4(),
                quantity=Decimal("1"),
                unit_price=Decimal("100"),
                expiry_date=naive,
            )

    def test_to_dict(self, valid_grn_item):
        d = valid_grn_item.to_dict()
        assert d["item_code"] == "ITEM-001"
        assert d["quantity"] == "10"
        assert d["unit_price"] == "100"
        assert d["total_amount"] == "1000"
        assert d["expiry_date"] == "2026-01-01T12:00:00+00:00"
        assert d["condition"] == "GOOD"
        assert d["batch_number"] == "BATCH-001"


# ============================================================================
# Tests for GoodsReceiptNoteEntity
# ============================================================================

class TestGoodsReceiptNoteEntityConstruction:
    def test_construction_valid(self, valid_grn):
        assert valid_grn.grn_number == "GRN-001"
        assert valid_grn.status == GRNStatus.DRAFT
        assert len(valid_grn.items) == 1
        assert valid_grn.version == 1
        assert valid_grn.total_amount == Decimal("1000")

    def test_validation_grn_number_too_short(self, valid_grn_item):
        with pytest.raises(ValueError, match="at least 3 characters"):
            GoodsReceiptNoteEntity(
                grn_id=uuid4(),
                grn_number="GR",
                po_id=uuid4(),
                po_number="PO-001",
                supplier_id=uuid4(),
                supplier_name="Supplier",
                receipt_date=datetime.now(UTC),
                status=GRNStatus.DRAFT,
                items=[valid_grn_item],
            )

    def test_validation_receipt_date_naive(self, valid_grn_item):
        naive = datetime(2025, 1, 15, 10, 0, 0)
        with pytest.raises(ValueError, match="receipt_date must be timezone-aware"):
            GoodsReceiptNoteEntity(
                grn_id=uuid4(),
                grn_number="GRN-001",
                po_id=uuid4(),
                po_number="PO-001",
                supplier_id=uuid4(),
                supplier_name="Supplier",
                receipt_date=naive,
                status=GRNStatus.DRAFT,
                items=[valid_grn_item],
            )

    def test_validation_version(self, valid_grn_item):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            GoodsReceiptNoteEntity(
                grn_id=uuid4(),
                grn_number="GRN-001",
                po_id=uuid4(),
                po_number="PO-001",
                supplier_id=uuid4(),
                supplier_name="Supplier",
                receipt_date=datetime.now(UTC),
                status=GRNStatus.DRAFT,
                items=[valid_grn_item],
                version=0,
            )

    def test_validation_created_at_naive(self, valid_grn_item):
        naive = datetime(2025, 1, 1, 12, 0, 0)
        with pytest.raises(ValueError, match="Timestamps must be timezone-aware"):
            GoodsReceiptNoteEntity(
                grn_id=uuid4(),
                grn_number="GRN-001",
                po_id=uuid4(),
                po_number="PO-001",
                supplier_id=uuid4(),
                supplier_name="Supplier",
                receipt_date=datetime.now(UTC),
                status=GRNStatus.DRAFT,
                items=[valid_grn_item],
                created_at=naive,
                updated_at=datetime.now(UTC),
            )

    def test_validation_duplicate_item_ids(self, valid_grn_item):
        same_id = uuid4()
        item1 = GRNItem(
            item_id=same_id,
            item_code="ITEM-001",
            item_name="Product A",
            po_item_id=uuid4(),
            quantity=Decimal("1"),
            unit_price=Decimal("100"),
        )
        item2 = GRNItem(
            item_id=same_id,
            item_code="ITEM-001",
            item_name="Product A",
            po_item_id=uuid4(),
            quantity=Decimal("2"),
            unit_price=Decimal("100"),
        )
        with pytest.raises(ValueError, match="Duplicate item IDs"):
            GoodsReceiptNoteEntity(
                grn_id=uuid4(),
                grn_number="GRN-001",
                po_id=uuid4(),
                po_number="PO-001",
                supplier_id=uuid4(),
                supplier_name="Supplier",
                receipt_date=datetime.now(UTC),
                status=GRNStatus.DRAFT,
                items=[item1, item2],
            )


class TestGoodsReceiptNoteEntityTotalAmount:
    def test_total_amount_single_item(self, valid_grn):
        assert valid_grn.total_amount == Decimal("1000")

    def test_total_amount_multiple_items(self, valid_grn, another_grn_item):
        grn = valid_grn.add_item(another_grn_item, "admin")
        expected = Decimal("1000") + Decimal("1000")  # 10*100 + 5*200 = 1000+1000=2000
        assert grn.total_amount == expected


class TestGoodsReceiptNoteEntityItemManagement:
    def test_add_item(self, valid_grn, another_grn_item):
        old_count = len(valid_grn.items)
        new_grn = valid_grn.add_item(another_grn_item, added_by="admin")
        assert len(new_grn.items) == old_count + 1
        assert new_grn.items[-1] == another_grn_item
        assert new_grn.version == valid_grn.version + 1
        assert new_grn.created_by == "admin"
        assert new_grn.updated_at > valid_grn.updated_at

    def test_remove_item(self, valid_grn, valid_grn_item):
        old_count = len(valid_grn.items)
        item_id = valid_grn_item.item_id
        new_grn = valid_grn.remove_item(item_id, removed_by="admin")
        assert len(new_grn.items) == old_count - 1
        assert item_id not in [i.item_id for i in new_grn.items]
        assert new_grn.version == valid_grn.version + 1
        assert new_grn.created_by == "admin"

    def test_remove_item_not_found(self, valid_grn):
        non_existent = uuid4()
        new_grn = valid_grn.remove_item(non_existent, removed_by="admin")
        assert len(new_grn.items) == len(valid_grn.items)
        assert new_grn.version == valid_grn.version + 1


class TestGoodsReceiptNoteEntityStatusTransitions:
    def test_confirm_draft(self, valid_grn):
        confirmed = valid_grn.confirm(confirmed_by="manager")
        assert confirmed.status == GRNStatus.CONFIRMED
        assert confirmed.received_by == "manager"
        assert confirmed.version == valid_grn.version + 1

    def test_confirm_non_draft_fails(self, confirmed_grn):
        with pytest.raises(ValueError, match="Cannot confirm GRN in status confirmed"):
            confirmed_grn.confirm("manager")

    def test_cancel_draft(self, valid_grn):
        cancelled = valid_grn.cancel(cancelled_by="admin", reason="Order cancelled")
        assert cancelled.status == GRNStatus.CANCELLED
        assert "Cancelled: Order cancelled" in cancelled.notes
        assert cancelled.version == valid_grn.version + 1

    def test_cancel_confirmed(self, confirmed_grn):
        cancelled = confirmed_grn.cancel(cancelled_by="admin", reason="Wrong goods")
        assert cancelled.status == GRNStatus.CANCELLED
        assert "Cancelled: Wrong goods" in cancelled.notes

    def test_cancel_already_cancelled_fails(self, valid_grn):
        cancelled = valid_grn.cancel("admin", "Test")
        with pytest.raises(ValueError, match="GRN already cancelled"):
            cancelled.cancel("admin", "Again")


class TestGoodsReceiptNoteEntitySerialization:
    def test_to_dict(self, valid_grn):
        d = valid_grn.to_dict()
        assert d["grn_number"] == "GRN-001"
        assert d["po_number"] == "PO-001"
        assert d["supplier_name"] == "Supplier A"
        assert d["status"] == "draft"
        assert d["total_amount"] == "1000"
        assert len(d["items"]) == 1
        assert d["items"][0]["item_code"] == "ITEM-001"
        assert d["version"] == 1


# ============================================================================
# Tests for Repository Protocol (abstract)
# ============================================================================

class TestGoodsReceiptNoteRepository:
    def test_abstract_methods_raise(self):
        repo = GoodsReceiptNoteRepository()
        with pytest.raises(NotImplementedError):
            repo.get_by_id(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_number("GRN-001", uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_po(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.save(MagicMock(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.delete(uuid4(), uuid4())
