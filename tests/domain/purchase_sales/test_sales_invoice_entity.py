# test_sales_invoice_entity.py
# Comprehensive tests for sales_invoice_entity.py

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.purchase_sales.sales_invoice_entity import (
    SalesInvoiceEntity,
    SalesInvoiceItem,
    SalesInvoiceRepository,
    SalesInvoiceStatus,
    SalesInvoiceType,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def valid_item():
    """Create a valid SalesInvoiceItem."""
    return SalesInvoiceItem(
        item_id=uuid4(),
        item_code="ITEM-001",
        item_name="Product A",
        so_item_id=uuid4(),
        quantity=Decimal("10"),
        unit_price=Decimal("100"),
        discount_percentage=Decimal("0"),
        tax_rate=Decimal("11"),
        unit_of_measure="PCS",
    )


@pytest.fixture
def another_valid_item():
    """Another valid SalesInvoiceItem."""
    return SalesInvoiceItem(
        item_id=uuid4(),
        item_code="ITEM-002",
        item_name="Product B",
        so_item_id=uuid4(),
        quantity=Decimal("5"),
        unit_price=Decimal("200"),
        discount_percentage=Decimal("10"),
        tax_rate=Decimal("11"),
        unit_of_measure="BOX",
    )


@pytest.fixture
def valid_invoice(valid_item):
    """Create a valid SalesInvoiceEntity with one item."""
    now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
    due = now + timedelta(days=30)
    return SalesInvoiceEntity(
        invoice_id=uuid4(),
        invoice_number="INV-001",
        invoice_type=SalesInvoiceType.STANDARD,
        so_id=uuid4(),
        so_number="SO-001",
        customer_id=uuid4(),
        customer_name="Customer A",
        invoice_date=now,
        due_date=due,
        status=SalesInvoiceStatus.DRAFT,
        items=[valid_item],
        currency="IDR",
        shipping_cost=Decimal("5000"),
        other_costs=Decimal("1000"),
        discount_amount=Decimal("0"),
        notes="Test invoice",
        created_by="system",
    )


@pytest.fixture
def issued_invoice(valid_invoice):
    """Return an issued invoice."""
    return valid_invoice.issue(issued_by="manager")


@pytest.fixture
def sent_invoice(issued_invoice):
    """Return a sent invoice."""
    return issued_invoice.send(sent_by="admin")


@pytest.fixture
def paid_invoice(valid_invoice):
    """Return a fully paid invoice."""
    # First issue and send, then record full payment
    issued = valid_invoice.issue("manager")
    sent = issued.send("admin")
    # Record payment
    return sent.record_payment(
        amount=sent.total_amount,
        payment_id=uuid4(),
        paid_by="customer",
    )


# ============================================================================
# Tests for Enums
# ============================================================================

class TestSalesInvoiceStatus:
    def test_members(self):
        assert SalesInvoiceStatus.DRAFT.value == "draft"
        assert SalesInvoiceStatus.ISSUED.value == "issued"
        assert SalesInvoiceStatus.SENT.value == "sent"
        assert SalesInvoiceStatus.PARTIALLY_PAID.value == "partial"
        assert SalesInvoiceStatus.FULLY_PAID.value == "paid"
        assert SalesInvoiceStatus.OVERDUE.value == "overdue"
        assert SalesInvoiceStatus.CANCELLED.value == "cancelled"


class TestSalesInvoiceType:
    def test_members(self):
        assert SalesInvoiceType.STANDARD.value == "standard"
        assert SalesInvoiceType.PROFORMA.value == "proforma"
        assert SalesInvoiceType.CREDIT_NOTE.value == "credit_note"
        assert SalesInvoiceType.DEBIT_NOTE.value == "debit_note"


# ============================================================================
# Tests for SalesInvoiceItem
# ============================================================================

class TestSalesInvoiceItem:
    def test_construction_valid(self, valid_item):
        assert valid_item.item_code == "ITEM-001"
        assert valid_item.quantity == Decimal("10")
        assert valid_item.unit_price == Decimal("100")
        assert valid_item.discount_percentage == Decimal("0")
        assert valid_item.tax_rate == Decimal("11")

    def test_validation_quantity_zero(self):
        with pytest.raises(ValueError, match="Quantity must be positive"):
            SalesInvoiceItem(
                item_id=uuid4(),
                item_code="ITEM-001",
                item_name="Product",
                so_item_id=uuid4(),
                quantity=Decimal("0"),
                unit_price=Decimal("100"),
            )

    def test_validation_unit_price_negative(self):
        with pytest.raises(ValueError, match="Unit price cannot be negative"):
            SalesInvoiceItem(
                item_id=uuid4(),
                item_code="ITEM-001",
                item_name="Product",
                so_item_id=uuid4(),
                quantity=Decimal("1"),
                unit_price=Decimal("-10"),
            )

    def test_validation_discount_out_of_range(self):
        with pytest.raises(ValueError, match="between 0 and 100"):
            SalesInvoiceItem(
                item_id=uuid4(),
                item_code="ITEM-001",
                item_name="Product",
                so_item_id=uuid4(),
                quantity=Decimal("1"),
                unit_price=Decimal("100"),
                discount_percentage=Decimal("150"),
            )

    def test_validation_tax_rate_out_of_range(self):
        with pytest.raises(ValueError, match="between 0 and 100"):
            SalesInvoiceItem(
                item_id=uuid4(),
                item_code="ITEM-001",
                item_name="Product",
                so_item_id=uuid4(),
                quantity=Decimal("1"),
                unit_price=Decimal("100"),
                tax_rate=Decimal("200"),
            )

    def test_properties(self):
        item = SalesInvoiceItem(
            item_id=uuid4(),
            item_code="ITEM-001",
            item_name="Product",
            so_item_id=uuid4(),
            quantity=Decimal("10"),
            unit_price=Decimal("1000"),
            discount_percentage=Decimal("5"),
            tax_rate=Decimal("11"),
        )
        assert item.subtotal == Decimal("10000")
        assert item.discount_amount == Decimal("500")
        assert item.net_amount == Decimal("9500")
        assert item.tax_amount == Decimal("1045")  # 11% of 9500
        assert item.total_amount == Decimal("10545")  # 9500 + 1045

    def test_to_dict(self, valid_item):
        d = valid_item.to_dict()
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
# Tests for SalesInvoiceEntity
# ============================================================================

class TestSalesInvoiceEntityConstruction:
    def test_construction_valid(self, valid_invoice):
        assert valid_invoice.invoice_number == "INV-001"
        assert valid_invoice.status == SalesInvoiceStatus.DRAFT
        assert len(valid_invoice.items) == 1
        assert valid_invoice.total_amount == Decimal("1110") + Decimal("5000") + Decimal("1000")  # item 1110 + shipping 5000 + other 1000
        assert valid_invoice.outstanding_amount == valid_invoice.total_amount
        assert valid_invoice.is_overdue is False

    def test_validation_invoice_number_too_short(self, valid_item):
        with pytest.raises(ValueError, match="at least 3 characters"):
            SalesInvoiceEntity(
                invoice_id=uuid4(),
                invoice_number="IN",
                invoice_type=SalesInvoiceType.STANDARD,
                so_id=uuid4(),
                so_number="SO-001",
                customer_id=uuid4(),
                customer_name="Customer",
                invoice_date=datetime.now(UTC),
                due_date=datetime.now(UTC) + timedelta(days=30),
                status=SalesInvoiceStatus.DRAFT,
                items=[valid_item],
            )

    def test_validation_due_date_before_invoice_date(self, valid_item):
        invoice_date = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
        due_date = datetime(2025, 1, 10, 10, 0, 0, tzinfo=UTC)
        with pytest.raises(ValueError, match="Due date must be after invoice date"):
            SalesInvoiceEntity(
                invoice_id=uuid4(),
                invoice_number="INV-001",
                invoice_type=SalesInvoiceType.STANDARD,
                so_id=uuid4(),
                so_number="SO-001",
                customer_id=uuid4(),
                customer_name="Customer",
                invoice_date=invoice_date,
                due_date=due_date,
                status=SalesInvoiceStatus.DRAFT,
                items=[valid_item],
            )

    def test_validation_currency_unsupported(self, valid_item):
        with pytest.raises(ValueError, match="Unsupported currency"):
            SalesInvoiceEntity(
                invoice_id=uuid4(),
                invoice_number="INV-001",
                invoice_type=SalesInvoiceType.STANDARD,
                so_id=uuid4(),
                so_number="SO-001",
                customer_id=uuid4(),
                customer_name="Customer",
                invoice_date=datetime.now(UTC),
                due_date=datetime.now(UTC) + timedelta(days=30),
                status=SalesInvoiceStatus.DRAFT,
                items=[valid_item],
                currency="XXX",
            )

    def test_validation_paid_amount_negative(self, valid_item):
        with pytest.raises(ValueError, match="Paid amount cannot be negative"):
            SalesInvoiceEntity(
                invoice_id=uuid4(),
                invoice_number="INV-001",
                invoice_type=SalesInvoiceType.STANDARD,
                so_id=uuid4(),
                so_number="SO-001",
                customer_id=uuid4(),
                customer_name="Customer",
                invoice_date=datetime.now(UTC),
                due_date=datetime.now(UTC) + timedelta(days=30),
                status=SalesInvoiceStatus.DRAFT,
                items=[valid_item],
                paid_amount=Decimal("-100"),
            )

    def test_validation_paid_amount_exceeds_total(self, valid_item):
        with pytest.raises(ValueError, match="Paid amount .* exceeds total amount"):
            SalesInvoiceEntity(
                invoice_id=uuid4(),
                invoice_number="INV-001",
                invoice_type=SalesInvoiceType.STANDARD,
                so_id=uuid4(),
                so_number="SO-001",
                customer_id=uuid4(),
                customer_name="Customer",
                invoice_date=datetime.now(UTC),
                due_date=datetime.now(UTC) + timedelta(days=30),
                status=SalesInvoiceStatus.DRAFT,
                items=[valid_item],
                total_amount=Decimal("100"),
                paid_amount=Decimal("200"),
            )

    def test_validation_version(self, valid_item):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            SalesInvoiceEntity(
                invoice_id=uuid4(),
                invoice_number="INV-001",
                invoice_type=SalesInvoiceType.STANDARD,
                so_id=uuid4(),
                so_number="SO-001",
                customer_id=uuid4(),
                customer_name="Customer",
                invoice_date=datetime.now(UTC),
                due_date=datetime.now(UTC) + timedelta(days=30),
                status=SalesInvoiceStatus.DRAFT,
                items=[valid_item],
                version=0,
            )

    def test_validation_dates_naive(self, valid_item):
        naive = datetime(2025, 1, 15, 10, 0, 0)
        with pytest.raises(ValueError, match="Dates must be timezone-aware"):
            SalesInvoiceEntity(
                invoice_id=uuid4(),
                invoice_number="INV-001",
                invoice_type=SalesInvoiceType.STANDARD,
                so_id=uuid4(),
                so_number="SO-001",
                customer_id=uuid4(),
                customer_name="Customer",
                invoice_date=naive,
                due_date=naive + timedelta(days=30),
                status=SalesInvoiceStatus.DRAFT,
                items=[valid_item],
            )


class TestSalesInvoiceEntityProperties:
    def test_outstanding_amount(self, valid_invoice):
        assert valid_invoice.outstanding_amount == valid_invoice.total_amount

    def test_outstanding_amount_after_payment(self, sent_invoice):
        # Record partial payment
        partial = sent_invoice.record_payment(
            amount=Decimal("500"),
            payment_id=uuid4(),
            paid_by="customer",
        )
        # Total amount is (1110+5000+1000=7110). If we pay 500, outstanding = 6610.
        assert partial.outstanding_amount == Decimal("6610")

    def test_is_overdue(self, valid_invoice):
        # Invoice not overdue
        assert valid_invoice.is_overdue is False
        # Create invoice with due date in the past
        past_due = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC) - timedelta(days=10)
        invoice_past = SalesInvoiceEntity(
            invoice_id=uuid4(),
            invoice_number="INV-002",
            invoice_type=SalesInvoiceType.STANDARD,
            so_id=uuid4(),
            so_number="SO-002",
            customer_id=uuid4(),
            customer_name="Customer",
            invoice_date=past_due - timedelta(days=30),
            due_date=past_due,
            status=SalesInvoiceStatus.SENT,
            items=valid_invoice.items,
            currency="IDR",
        )
        # The invoice is SENT and due date is past, so overdue
        assert invoice_past.is_overdue is True
        # But if fully paid, should not be overdue
        fully_paid = invoice_past.record_payment(
            amount=invoice_past.total_amount,
            payment_id=uuid4(),
            paid_by="customer",
        )
        assert fully_paid.is_overdue is False


class TestSalesInvoiceEntityItemManagement:
    def test_add_item(self, valid_invoice, another_valid_item):
        old_count = len(valid_invoice.items)
        new_invoice = valid_invoice.add_item(another_valid_item, added_by="admin")
        assert len(new_invoice.items) == old_count + 1
        assert new_invoice.items[-1] == another_valid_item
        # Total should be recalculated
        # Original item: 10*100=1000, tax 11% => 1110
        # New item: 5*200=1000, discount 10% => 900, tax 11% => 999
        # Shipping 5000, other 1000
        expected_total = Decimal("1110") + Decimal("999") + Decimal("5000") + Decimal("1000")
        assert new_invoice.total_amount == expected_total
        assert new_invoice.version == valid_invoice.version + 1
        assert new_invoice.created_by == "admin"

    def test_remove_item(self, valid_invoice, valid_item):
        old_count = len(valid_invoice.items)
        item_id = valid_item.item_id
        new_invoice = valid_invoice.remove_item(item_id, removed_by="admin")
        assert len(new_invoice.items) == old_count - 1
        assert item_id not in [i.item_id for i in new_invoice.items]
        # Total should be recalculated (no items, so only shipping+other)
        expected_total = Decimal("5000") + Decimal("1000")
        assert new_invoice.total_amount == expected_total
        assert new_invoice.version == valid_invoice.version + 1

    def test_remove_item_not_found(self, valid_invoice):
        non_existent = uuid4()
        new_invoice = valid_invoice.remove_item(non_existent, removed_by="admin")
        assert len(new_invoice.items) == len(valid_invoice.items)
        assert new_invoice.version == valid_invoice.version + 1


class TestSalesInvoiceEntityStatusTransitions:
    def test_issue_draft(self, valid_invoice):
        issued = valid_invoice.issue(issued_by="manager")
        assert issued.status == SalesInvoiceStatus.ISSUED
        assert issued.version == valid_invoice.version + 1
        assert issued.created_by == "manager"

    def test_issue_non_draft_fails(self, issued_invoice):
        with pytest.raises(ValueError, match="Cannot issue invoice in status issued"):
            issued_invoice.issue("manager")

    def test_send_issued(self, issued_invoice):
        sent = issued_invoice.send(sent_by="admin")
        assert sent.status == SalesInvoiceStatus.SENT
        assert sent.version == issued_invoice.version + 1

    def test_send_non_issued_fails(self, valid_invoice):
        with pytest.raises(ValueError, match="Cannot send invoice in status draft"):
            valid_invoice.send("admin")

    def test_record_payment_partial(self, sent_invoice):
        total = sent_invoice.total_amount
        payment_amount = total / 2
        paid = sent_invoice.record_payment(
            amount=payment_amount,
            payment_id=uuid4(),
            paid_by="customer",
        )
        assert paid.status == SalesInvoiceStatus.PARTIALLY_PAID
        assert paid.paid_amount == payment_amount
        assert paid.outstanding_amount == total - payment_amount
        assert paid.version == sent_invoice.version + 1

    def test_record_payment_full(self, sent_invoice):
        total = sent_invoice.total_amount
        paid = sent_invoice.record_payment(
            amount=total,
            payment_id=uuid4(),
            paid_by="customer",
        )
        assert paid.status == SalesInvoiceStatus.FULLY_PAID
        assert paid.paid_amount == total
        assert paid.outstanding_amount == Decimal("0")

    def test_record_payment_exceeds_outstanding(self, sent_invoice):
        with pytest.raises(ValueError, match="would exceed outstanding"):
            sent_invoice.record_payment(
                amount=sent_invoice.total_amount + Decimal("100"),
                payment_id=uuid4(),
                paid_by="customer",
            )

    def test_record_payment_zero_or_negative(self, sent_invoice):
        with pytest.raises(ValueError, match="Payment amount must be positive"):
            sent_invoice.record_payment(
                amount=Decimal("0"),
                payment_id=uuid4(),
                paid_by="customer",
            )

    def test_mark_overdue_sent(self, sent_invoice):
        overdue = sent_invoice.mark_overdue()
        assert overdue.status == SalesInvoiceStatus.OVERDUE
        assert overdue.version == sent_invoice.version + 1

    def test_mark_overdue_partial(self, sent_invoice):
        partial = sent_invoice.record_payment(
            amount=Decimal("100"),
            payment_id=uuid4(),
            paid_by="customer",
        )
        overdue = partial.mark_overdue()
        assert overdue.status == SalesInvoiceStatus.OVERDUE

    def test_mark_overdue_invalid_status(self, valid_invoice):
        with pytest.raises(ValueError, match="Cannot mark invoice as overdue in status draft"):
            valid_invoice.mark_overdue()

    def test_cancel_draft(self, valid_invoice):
        cancelled = valid_invoice.cancel(cancelled_by="admin", reason="Wrong amount")
        assert cancelled.status == SalesInvoiceStatus.CANCELLED
        assert "Cancelled: Wrong amount" in cancelled.notes
        assert cancelled.version == valid_invoice.version + 1

    def test_cancel_issued(self, issued_invoice):
        cancelled = issued_invoice.cancel(cancelled_by="admin", reason="Customer request")
        assert cancelled.status == SalesInvoiceStatus.CANCELLED

    def test_cancel_paid_invoice(self, paid_invoice):
        with pytest.raises(ValueError, match="Cannot cancel paid invoice"):
            paid_invoice.cancel("admin", "Test")


class TestSalesInvoiceEntitySerialization:
    def test_to_dict(self, valid_invoice):
        d = valid_invoice.to_dict()
        assert d["invoice_number"] == "INV-001"
        assert d["invoice_type"] == "standard"
        assert d["customer_name"] == "Customer A"
        assert d["status"] == "draft"
        assert d["total_amount"] == str(valid_invoice.total_amount)
        assert d["paid_amount"] == "0"
        assert d["outstanding_amount"] == str(valid_invoice.outstanding_amount)
        assert d["is_overdue"] is False
        assert len(d["items"]) == 1
        assert d["items"][0]["item_code"] == "ITEM-001"
        assert d["version"] == valid_invoice.version


# ============================================================================
# Tests for Repository Protocol (abstract)
# ============================================================================

class TestSalesInvoiceRepository:
    def test_abstract_methods_raise(self):
        repo = SalesInvoiceRepository()
        with pytest.raises(NotImplementedError):
            repo.get_by_id(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_number("INV-001", uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_customer(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_so(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.save(MagicMock(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.delete(uuid4(), uuid4())
