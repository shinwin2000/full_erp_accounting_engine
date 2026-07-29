# test_purchase_invoice_entity.py
# Comprehensive tests for purchase_invoice_entity.py

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.purchase_sales.purchase_invoice_entity import (
    PurchaseInvoiceEntity,
    PurchaseInvoiceItem,
    PurchaseInvoiceRepository,
    PurchaseInvoiceStatus,
    PurchaseInvoiceType,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def valid_purchase_item():
    """Create a valid PurchaseInvoiceItem."""
    return PurchaseInvoiceItem(
        item_id=uuid4(),
        item_code="ITEM-001",
        item_name="Product A",
        po_item_id=uuid4(),
        quantity=Decimal("10"),
        unit_price=Decimal("100"),
        discount_percentage=Decimal("0"),
        tax_rate=Decimal("11"),
        unit_of_measure="PCS",
    )


@pytest.fixture
def another_purchase_item():
    """Another valid PurchaseInvoiceItem."""
    return PurchaseInvoiceItem(
        item_id=uuid4(),
        item_code="ITEM-002",
        item_name="Product B",
        po_item_id=uuid4(),
        quantity=Decimal("5"),
        unit_price=Decimal("200"),
        discount_percentage=Decimal("10"),
        tax_rate=Decimal("11"),
        unit_of_measure="BOX",
    )


@pytest.fixture
def valid_purchase_invoice(valid_purchase_item):
    """Create a valid PurchaseInvoiceEntity with one item."""
    now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
    due = now + timedelta(days=30)
    return PurchaseInvoiceEntity(
        invoice_id=uuid4(),
        invoice_number="PI-001",
        invoice_type=PurchaseInvoiceType.STANDARD,
        po_id=uuid4(),
        po_number="PO-001",
        supplier_id=uuid4(),
        supplier_name="Supplier A",
        invoice_date=now,
        due_date=due,
        status=PurchaseInvoiceStatus.DRAFT,
        items=[valid_purchase_item],
        currency="IDR",
        shipping_cost=Decimal("5000"),
        other_costs=Decimal("1000"),
        discount_amount=Decimal("0"),
        notes="Test invoice",
        created_by="system",
    )


@pytest.fixture
def received_invoice(valid_purchase_invoice):
    """Return a received invoice."""
    return valid_purchase_invoice.receive(received_by="receiving")


@pytest.fixture
def verified_invoice(received_invoice):
    """Return a verified invoice."""
    return received_invoice.verify(verified_by="auditor")


@pytest.fixture
def approved_invoice(verified_invoice):
    """Return an approved invoice."""
    return verified_invoice.approve(approved_by="manager")


@pytest.fixture
def paid_invoice(valid_purchase_invoice):
    """Return a fully paid invoice."""
    # Need to go through stages to pay
    received = valid_purchase_invoice.receive("receiving")
    verified = received.verify("auditor")
    approved = verified.approve("manager")
    return approved.record_payment(
        amount=approved.total_amount,
        payment_id=uuid4(),
        paid_by="finance",
    )


# ============================================================================
# Tests for Enums
# ============================================================================

class TestPurchaseInvoiceStatus:
    def test_members(self):
        assert PurchaseInvoiceStatus.DRAFT.value == "draft"
        assert PurchaseInvoiceStatus.RECEIVED.value == "received"
        assert PurchaseInvoiceStatus.VERIFIED.value == "verified"
        assert PurchaseInvoiceStatus.APPROVED.value == "approved"
        assert PurchaseInvoiceStatus.PAID.value == "paid"
        assert PurchaseInvoiceStatus.CANCELLED.value == "cancelled"
        assert PurchaseInvoiceStatus.DISPUTED.value == "disputed"


class TestPurchaseInvoiceType:
    def test_members(self):
        assert PurchaseInvoiceType.STANDARD.value == "standard"
        assert PurchaseInvoiceType.CREDIT_NOTE.value == "credit_note"
        assert PurchaseInvoiceType.DEBIT_NOTE.value == "debit_note"


# ============================================================================
# Tests for PurchaseInvoiceItem
# ============================================================================

class TestPurchaseInvoiceItem:
    def test_construction_valid(self, valid_purchase_item):
        assert valid_purchase_item.item_code == "ITEM-001"
        assert valid_purchase_item.quantity == Decimal("10")
        assert valid_purchase_item.unit_price == Decimal("100")
        assert valid_purchase_item.discount_percentage == Decimal("0")
        assert valid_purchase_item.tax_rate == Decimal("11")

    def test_validation_quantity_zero(self):
        with pytest.raises(ValueError, match="Quantity must be positive"):
            PurchaseInvoiceItem(
                item_id=uuid4(),
                item_code="ITEM-001",
                item_name="Product",
                po_item_id=uuid4(),
                quantity=Decimal("0"),
                unit_price=Decimal("100"),
            )

    def test_validation_unit_price_negative(self):
        with pytest.raises(ValueError, match="Unit price cannot be negative"):
            PurchaseInvoiceItem(
                item_id=uuid4(),
                item_code="ITEM-001",
                item_name="Product",
                po_item_id=uuid4(),
                quantity=Decimal("1"),
                unit_price=Decimal("-10"),
            )

    def test_validation_discount_out_of_range(self):
        with pytest.raises(ValueError, match="between 0 and 100"):
            PurchaseInvoiceItem(
                item_id=uuid4(),
                item_code="ITEM-001",
                item_name="Product",
                po_item_id=uuid4(),
                quantity=Decimal("1"),
                unit_price=Decimal("100"),
                discount_percentage=Decimal("150"),
            )

    def test_validation_tax_rate_out_of_range(self):
        with pytest.raises(ValueError, match="between 0 and 100"):
            PurchaseInvoiceItem(
                item_id=uuid4(),
                item_code="ITEM-001",
                item_name="Product",
                po_item_id=uuid4(),
                quantity=Decimal("1"),
                unit_price=Decimal("100"),
                tax_rate=Decimal("200"),
            )

    def test_properties(self):
        item = PurchaseInvoiceItem(
            item_id=uuid4(),
            item_code="ITEM-001",
            item_name="Product",
            po_item_id=uuid4(),
            quantity=Decimal("10"),
            unit_price=Decimal("1000"),
            discount_percentage=Decimal("5"),
            tax_rate=Decimal("11"),
        )
        assert item.subtotal == Decimal("10000")
        assert item.discount_amount == Decimal("500")
        assert item.net_amount == Decimal("9500")
        assert item.tax_amount == Decimal("1045")
        assert item.total_amount == Decimal("10545")

    def test_to_dict(self, valid_purchase_item):
        d = valid_purchase_item.to_dict()
        assert d["item_code"] == "ITEM-001"
        assert d["quantity"] == "10"
        assert d["unit_price"] == "100"
        assert d["discount_percentage"] == "0"
        assert d["tax_rate"] == "11"
        assert d["subtotal"] == "1000"
        assert d["discount_amount"] == "0"
        assert d["net_amount"] == "1000"
        assert d["tax_amount"] == "110"
        assert d["total_amount"] == "1110"


# ============================================================================
# Tests for PurchaseInvoiceEntity
# ============================================================================

class TestPurchaseInvoiceEntityConstruction:
    def test_construction_valid(self, valid_purchase_invoice):
        assert valid_purchase_invoice.invoice_number == "PI-001"
        assert valid_purchase_invoice.status == PurchaseInvoiceStatus.DRAFT
        assert len(valid_purchase_invoice.items) == 1
        assert valid_purchase_invoice.total_amount == Decimal("1110") + Decimal("5000") + Decimal("1000")
        assert valid_purchase_invoice.outstanding_amount == valid_purchase_invoice.total_amount
        assert valid_purchase_invoice.is_overdue is False

    def test_validation_invoice_number_too_short(self, valid_purchase_item):
        with pytest.raises(ValueError, match="at least 3 characters"):
            PurchaseInvoiceEntity(
                invoice_id=uuid4(),
                invoice_number="PI",
                invoice_type=PurchaseInvoiceType.STANDARD,
                po_id=uuid4(),
                po_number="PO-001",
                supplier_id=uuid4(),
                supplier_name="Supplier",
                invoice_date=datetime.now(UTC),
                due_date=datetime.now(UTC) + timedelta(days=30),
                status=PurchaseInvoiceStatus.DRAFT,
                items=[valid_purchase_item],
            )

    def test_validation_due_date_before_invoice_date(self, valid_purchase_item):
        invoice_date = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
        due_date = datetime(2025, 1, 10, 10, 0, 0, tzinfo=UTC)
        with pytest.raises(ValueError, match="Due date must be after invoice date"):
            PurchaseInvoiceEntity(
                invoice_id=uuid4(),
                invoice_number="PI-001",
                invoice_type=PurchaseInvoiceType.STANDARD,
                po_id=uuid4(),
                po_number="PO-001",
                supplier_id=uuid4(),
                supplier_name="Supplier",
                invoice_date=invoice_date,
                due_date=due_date,
                status=PurchaseInvoiceStatus.DRAFT,
                items=[valid_purchase_item],
            )

    def test_validation_currency_unsupported(self, valid_purchase_item):
        with pytest.raises(ValueError, match="Unsupported currency"):
            PurchaseInvoiceEntity(
                invoice_id=uuid4(),
                invoice_number="PI-001",
                invoice_type=PurchaseInvoiceType.STANDARD,
                po_id=uuid4(),
                po_number="PO-001",
                supplier_id=uuid4(),
                supplier_name="Supplier",
                invoice_date=datetime.now(UTC),
                due_date=datetime.now(UTC) + timedelta(days=30),
                status=PurchaseInvoiceStatus.DRAFT,
                items=[valid_purchase_item],
                currency="XXX",
            )

    def test_validation_paid_amount_negative(self, valid_purchase_item):
        with pytest.raises(ValueError, match="Paid amount cannot be negative"):
            PurchaseInvoiceEntity(
                invoice_id=uuid4(),
                invoice_number="PI-001",
                invoice_type=PurchaseInvoiceType.STANDARD,
                po_id=uuid4(),
                po_number="PO-001",
                supplier_id=uuid4(),
                supplier_name="Supplier",
                invoice_date=datetime.now(UTC),
                due_date=datetime.now(UTC) + timedelta(days=30),
                status=PurchaseInvoiceStatus.DRAFT,
                items=[valid_purchase_item],
                paid_amount=Decimal("-100"),
            )

    def test_validation_paid_amount_exceeds_total(self, valid_purchase_item):
        with pytest.raises(ValueError, match="Paid amount .* exceeds total amount"):
            PurchaseInvoiceEntity(
                invoice_id=uuid4(),
                invoice_number="PI-001",
                invoice_type=PurchaseInvoiceType.STANDARD,
                po_id=uuid4(),
                po_number="PO-001",
                supplier_id=uuid4(),
                supplier_name="Supplier",
                invoice_date=datetime.now(UTC),
                due_date=datetime.now(UTC) + timedelta(days=30),
                status=PurchaseInvoiceStatus.DRAFT,
                items=[valid_purchase_item],
                total_amount=Decimal("100"),
                paid_amount=Decimal("200"),
            )

    def test_validation_version(self, valid_purchase_item):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            PurchaseInvoiceEntity(
                invoice_id=uuid4(),
                invoice_number="PI-001",
                invoice_type=PurchaseInvoiceType.STANDARD,
                po_id=uuid4(),
                po_number="PO-001",
                supplier_id=uuid4(),
                supplier_name="Supplier",
                invoice_date=datetime.now(UTC),
                due_date=datetime.now(UTC) + timedelta(days=30),
                status=PurchaseInvoiceStatus.DRAFT,
                items=[valid_purchase_item],
                version=0,
            )

    def test_validation_dates_naive(self, valid_purchase_item):
        naive = datetime(2025, 1, 15, 10, 0, 0)
        with pytest.raises(ValueError, match="Dates must be timezone-aware"):
            PurchaseInvoiceEntity(
                invoice_id=uuid4(),
                invoice_number="PI-001",
                invoice_type=PurchaseInvoiceType.STANDARD,
                po_id=uuid4(),
                po_number="PO-001",
                supplier_id=uuid4(),
                supplier_name="Supplier",
                invoice_date=naive,
                due_date=naive + timedelta(days=30),
                status=PurchaseInvoiceStatus.DRAFT,
                items=[valid_purchase_item],
            )


class TestPurchaseInvoiceEntityProperties:
    def test_outstanding_amount(self, valid_purchase_invoice):
        assert valid_purchase_invoice.outstanding_amount == valid_purchase_invoice.total_amount

    def test_outstanding_amount_after_payment(self, approved_invoice):
        # Record partial payment
        partial = approved_invoice.record_payment(
            amount=Decimal("500"),
            payment_id=uuid4(),
            paid_by="finance",
        )
        total = approved_invoice.total_amount
        assert partial.outstanding_amount == total - Decimal("500")

    def test_is_overdue(self, valid_purchase_invoice):
        assert valid_purchase_invoice.is_overdue is False
        # Create invoice with past due date
        past_due = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC) - timedelta(days=10)
        invoice_past = PurchaseInvoiceEntity(
            invoice_id=uuid4(),
            invoice_number="PI-002",
            invoice_type=PurchaseInvoiceType.STANDARD,
            po_id=uuid4(),
            po_number="PO-002",
            supplier_id=uuid4(),
            supplier_name="Supplier",
            invoice_date=past_due - timedelta(days=30),
            due_date=past_due,
            status=PurchaseInvoiceStatus.APPROVED,
            items=valid_purchase_invoice.items,
            currency="IDR",
        )
        assert invoice_past.is_overdue is True
        # If paid, not overdue
        paid = invoice_past.record_payment(
            amount=invoice_past.total_amount,
            payment_id=uuid4(),
            paid_by="finance",
        )
        assert paid.is_overdue is False


class TestPurchaseInvoiceEntityItemManagement:
    def test_add_item(self, valid_purchase_invoice, another_purchase_item):
        old_count = len(valid_purchase_invoice.items)
        new_invoice = valid_purchase_invoice.add_item(another_purchase_item, added_by="admin")
        assert len(new_invoice.items) == old_count + 1
        assert new_invoice.items[-1] == another_purchase_item
        # Recalculate total
        original_item_total = Decimal("1110")
        new_item_total = Decimal("999")  # 5*200=1000, discount 10% => 900, tax 11% => 999
        expected_total = original_item_total + new_item_total + Decimal("5000") + Decimal("1000")
        assert new_invoice.total_amount == expected_total
        assert new_invoice.version == valid_purchase_invoice.version + 1
        assert new_invoice.created_by == "admin"

    def test_remove_item(self, valid_purchase_invoice, valid_purchase_item):
        old_count = len(valid_purchase_invoice.items)
        item_id = valid_purchase_item.item_id
        new_invoice = valid_purchase_invoice.remove_item(item_id, removed_by="admin")
        assert len(new_invoice.items) == old_count - 1
        assert item_id not in [i.item_id for i in new_invoice.items]
        # Total should be only shipping+other
        expected_total = Decimal("5000") + Decimal("1000")
        assert new_invoice.total_amount == expected_total
        assert new_invoice.version == valid_purchase_invoice.version + 1

    def test_remove_item_not_found(self, valid_purchase_invoice):
        non_existent = uuid4()
        new_invoice = valid_purchase_invoice.remove_item(non_existent, removed_by="admin")
        assert len(new_invoice.items) == len(valid_purchase_invoice.items)
        assert new_invoice.version == valid_purchase_invoice.version + 1


class TestPurchaseInvoiceEntityStatusTransitions:
    def test_receive(self, valid_purchase_invoice):
        received = valid_purchase_invoice.receive(received_by="receiving")
        assert received.status == PurchaseInvoiceStatus.RECEIVED
        assert received.version == valid_purchase_invoice.version + 1
        assert received.created_by == "receiving"

    def test_receive_non_draft_fails(self, received_invoice):
        with pytest.raises(ValueError, match="Cannot receive invoice in status received"):
            received_invoice.receive("receiving")

    def test_verify(self, received_invoice):
        verified = received_invoice.verify(verified_by="auditor")
        assert verified.status == PurchaseInvoiceStatus.VERIFIED
        assert verified.version == received_invoice.version + 1

    def test_verify_non_received_fails(self, valid_purchase_invoice):
        with pytest.raises(ValueError, match="Cannot verify invoice in status draft"):
            valid_purchase_invoice.verify("auditor")

    def test_approve(self, verified_invoice):
        approved = verified_invoice.approve(approved_by="manager")
        assert approved.status == PurchaseInvoiceStatus.APPROVED
        assert approved.version == verified_invoice.version + 1

    def test_approve_non_verified_fails(self, received_invoice):
        with pytest.raises(ValueError, match="Cannot approve invoice in status received"):
            received_invoice.approve("manager")

    def test_record_payment_partial(self, approved_invoice):
        total = approved_invoice.total_amount
        payment_amount = total / 2
        paid = approved_invoice.record_payment(
            amount=payment_amount,
            payment_id=uuid4(),
            paid_by="finance",
        )
        # Status should remain APPROVED (not PAID) because not fully paid
        assert paid.status == PurchaseInvoiceStatus.APPROVED
        assert paid.paid_amount == payment_amount
        assert paid.outstanding_amount == total - payment_amount
        assert paid.version == approved_invoice.version + 1

    def test_record_payment_full(self, approved_invoice):
        total = approved_invoice.total_amount
        paid = approved_invoice.record_payment(
            amount=total,
            payment_id=uuid4(),
            paid_by="finance",
        )
        assert paid.status == PurchaseInvoiceStatus.PAID
        assert paid.paid_amount == total
        assert paid.outstanding_amount == Decimal("0")

    def test_record_payment_exceeds_outstanding(self, approved_invoice):
        with pytest.raises(ValueError, match="would exceed outstanding"):
            approved_invoice.record_payment(
                amount=approved_invoice.total_amount + Decimal("100"),
                payment_id=uuid4(),
                paid_by="finance",
            )

    def test_record_payment_zero_or_negative(self, approved_invoice):
        with pytest.raises(ValueError, match="Payment amount must be positive"):
            approved_invoice.record_payment(
                amount=Decimal("0"),
                payment_id=uuid4(),
                paid_by="finance",
            )

    def test_dispute(self, approved_invoice):
        disputed = approved_invoice.dispute(disputed_by="procurement", reason="Price mismatch")
        assert disputed.status == PurchaseInvoiceStatus.DISPUTED
        assert "Disputed: Price mismatch" in disputed.notes
        assert disputed.version == approved_invoice.version + 1

    def test_dispute_paid_fails(self, paid_invoice):
        with pytest.raises(ValueError, match="Cannot dispute invoice in status paid"):
            paid_invoice.dispute("procurement", "Reason")

    def test_dispute_cancelled_fails(self, valid_purchase_invoice):
        cancelled = valid_purchase_invoice.cancel("admin", "Test")
        with pytest.raises(ValueError, match="Cannot dispute invoice in status cancelled"):
            cancelled.dispute("procurement", "Reason")

    def test_cancel_draft(self, valid_purchase_invoice):
        cancelled = valid_purchase_invoice.cancel(cancelled_by="admin", reason="Wrong details")
        assert cancelled.status == PurchaseInvoiceStatus.CANCELLED
        assert "Cancelled: Wrong details" in cancelled.notes
        assert cancelled.version == valid_purchase_invoice.version + 1

    def test_cancel_paid_invoice(self, paid_invoice):
        with pytest.raises(ValueError, match="Cannot cancel paid invoice"):
            paid_invoice.cancel("admin", "Test")


class TestPurchaseInvoiceEntitySerialization:
    def test_to_dict(self, valid_purchase_invoice):
        d = valid_purchase_invoice.to_dict()
        assert d["invoice_number"] == "PI-001"
        assert d["invoice_type"] == "standard"
        assert d["supplier_name"] == "Supplier A"
        assert d["status"] == "draft"
        assert d["total_amount"] == str(valid_purchase_invoice.total_amount)
        assert d["paid_amount"] == "0"
        assert d["outstanding_amount"] == str(valid_purchase_invoice.outstanding_amount)
        assert d["is_overdue"] is False
        assert len(d["items"]) == 1
        assert d["items"][0]["item_code"] == "ITEM-001"
        assert d["version"] == valid_purchase_invoice.version


# ============================================================================
# Tests for Repository Protocol (abstract)
# ============================================================================

class TestPurchaseInvoiceRepository:
    def test_abstract_methods_raise(self):
        repo = PurchaseInvoiceRepository()
        with pytest.raises(NotImplementedError):
            repo.get_by_id(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_number("PI-001", uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_supplier(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_po(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.save(MagicMock(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.delete(uuid4(), uuid4())
