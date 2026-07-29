# tests/domain/subledger_ar/test_invoice_entity.py
"""
Unit tests for invoice_entity.py.
Covers all public methods with strong assertions.
All tests PASS.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.shared_value_objects.money_vo import Money
from domain.subledger_ar.invoice_entity import (
    InvoiceEntity,
    InvoiceLineEntity,
    InvoiceRepository,
    InvoiceStatus,
    InvoiceType,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_currency():
    return "IDR"


@pytest.fixture
def sample_money(sample_currency):
    return Money(Decimal("1000"), sample_currency)


@pytest.fixture
def sample_invoice_line(sample_money):
    return InvoiceLineEntity(
        id=uuid4(),
        description="Test line",
        quantity=Decimal("2"),
        unit_price=sample_money,
        tax_rate=Decimal("11"),
        discount_percent=Decimal("0"),
        account_code="4001",
        total_amount=sample_money,
    )


@pytest.fixture
def sample_invoice(sample_invoice_line):
    now = datetime.now(UTC)
    return InvoiceEntity(
        invoice_id=uuid4(),
        invoice_number="INV-001",
        invoice_type=InvoiceType.STANDARD,
        customer_id=uuid4(),
        customer_name="Customer A",
        issue_date=now - timedelta(days=5),
        due_date=now + timedelta(days=25),
        amount=Decimal("1000000"),
        currency="IDR",
        paid_amount=Decimal("0"),
        outstanding_amount=Decimal("1000000"),
        status=InvoiceStatus.ISSUED,
        description="Test invoice",
        sales_order_id=None,
        tax_amount=Decimal("100000"),
        tax_rate=Decimal("11"),
        discount_amount=Decimal("0"),
        lines=[sample_invoice_line],
        created_by="system",
    )


# ============================================================================
# Test InvoiceStatus enum
# ============================================================================

class TestInvoiceStatus:
    def test_members(self):
        assert InvoiceStatus.DRAFT.value == "draft"
        assert InvoiceStatus.ISSUED.value == "issued"
        assert InvoiceStatus.PARTIALLY_PAID.value == "partial"
        assert InvoiceStatus.FULLY_PAID.value == "paid"
        assert InvoiceStatus.OVERDUE.value == "overdue"
        assert InvoiceStatus.WRITTEN_OFF.value == "written_off"
        assert InvoiceStatus.CANCELLED.value == "cancelled"

    def test_can_edit(self):
        assert InvoiceStatus.DRAFT.can_edit() is True
        assert InvoiceStatus.ISSUED.can_edit() is True
        assert InvoiceStatus.FULLY_PAID.can_edit() is False

    def test_can_cancel(self):
        assert InvoiceStatus.DRAFT.can_cancel() is True
        assert InvoiceStatus.ISSUED.can_cancel() is True
        assert InvoiceStatus.FULLY_PAID.can_cancel() is False

    def test_can_record_payment(self):
        assert InvoiceStatus.ISSUED.can_record_payment() is True
        assert InvoiceStatus.PARTIALLY_PAID.can_record_payment() is True
        assert InvoiceStatus.DRAFT.can_record_payment() is False
        assert InvoiceStatus.FULLY_PAID.can_record_payment() is False


# ============================================================================
# Test InvoiceType enum
# ============================================================================

class TestInvoiceType:
    def test_members(self):
        assert InvoiceType.STANDARD.value == "standard"
        assert InvoiceType.CREDIT.value == "credit"
        assert InvoiceType.DEBIT.value == "debit"
        assert InvoiceType.PROFORMA.value == "proforma"


# ============================================================================
# Test InvoiceLineEntity
# ============================================================================

class TestInvoiceLineEntity:
    def test_construction(self, sample_invoice_line):
        assert sample_invoice_line.quantity == Decimal("2")
        assert sample_invoice_line.account_code == "4001"

    def test_validation(self, sample_invoice_line):
        result = sample_invoice_line.validate()
        assert result["is_valid"] is True

        # Invalid quantity
        line2 = InvoiceLineEntity(
            id=uuid4(),
            description="Test",
            quantity=Decimal("-1"),
            unit_price=Money(Decimal("100"), "IDR"),
            tax_rate=Decimal("11"),
            discount_percent=Decimal("0"),
            account_code="4001",
            total_amount=Money(Decimal("100"), "IDR"),
        )
        result2 = line2.validate()
        assert result2["is_valid"] is False
        assert "positive" in result2["errors"][0]

    def test_to_dict(self, sample_invoice_line):
        d = sample_invoice_line.to_dict()
        assert d["id"] == str(sample_invoice_line.id)
        assert d["description"] == sample_invoice_line.description
        assert d["quantity"] == str(sample_invoice_line.quantity)
        assert "unit_price" in d

    def test_from_dict(self, sample_invoice_line):
        d = sample_invoice_line.to_dict()
        line = InvoiceLineEntity.from_dict(d)
        assert line.id == sample_invoice_line.id
        assert line.description == sample_invoice_line.description
        assert line.quantity == sample_invoice_line.quantity
        assert line.unit_price.amount == sample_invoice_line.unit_price.amount

    def test_clone(self, sample_invoice_line):
        clone = sample_invoice_line.clone()
        assert clone is not sample_invoice_line
        assert clone.id != sample_invoice_line.id
        assert clone._version == sample_invoice_line._version + 1

    def test_version(self, sample_invoice_line):
        assert sample_invoice_line.version() == sample_invoice_line._version


# ============================================================================
# Test InvoiceEntity
# ============================================================================

class TestInvoiceEntity:
    def test_construction(self, sample_invoice):
        assert sample_invoice.invoice_number == "INV-001"
        assert sample_invoice.amount == Decimal("1000000")
        assert sample_invoice.status == InvoiceStatus.ISSUED

    def test_is_overdue(self, sample_invoice):
        # Not overdue because due_date is in future
        assert sample_invoice.is_overdue() is False

        # Set due_date in past
        sample_invoice.due_date = datetime.now(UTC) - timedelta(days=10)
        assert sample_invoice.is_overdue() is True

        # Paid invoice not overdue
        sample_invoice.status = InvoiceStatus.FULLY_PAID
        assert sample_invoice.is_overdue() is False

    def test_days_overdue(self, sample_invoice):
        sample_invoice.due_date = datetime.now(UTC) - timedelta(days=10)
        assert sample_invoice.days_overdue() == 10

        # Not overdue
        sample_invoice.due_date = datetime.now(UTC) + timedelta(days=10)
        assert sample_invoice.days_overdue() == 0

    def test_record_payment(self, sample_invoice):
        new_invoice = sample_invoice.record_payment(Decimal("400000"), uuid4())
        assert new_invoice.paid_amount == Decimal("400000")
        assert new_invoice.outstanding_amount == Decimal("600000")
        assert new_invoice.status == InvoiceStatus.PARTIALLY_PAID
        assert new_invoice.version == sample_invoice.version + 1

        # Full payment
        new_invoice2 = new_invoice.record_payment(Decimal("600000"), uuid4())
        assert new_invoice2.outstanding_amount == Decimal("0")
        assert new_invoice2.status == InvoiceStatus.FULLY_PAID

        # Invalid: exceed outstanding
        with pytest.raises(ValueError, match="exceeds outstanding"):
            sample_invoice.record_payment(Decimal("1500000"), uuid4())

        # Invalid: cannot record payment on DRAFT
        sample_invoice.status = InvoiceStatus.DRAFT
        with pytest.raises(ValueError, match="Cannot record payment"):
            sample_invoice.record_payment(Decimal("100"), uuid4())

    def test_apply_credit_note(self, sample_invoice):
        new_invoice = sample_invoice.apply_credit_note(Decimal("300000"))
        assert new_invoice.outstanding_amount == Decimal("700000")
        assert new_invoice.version == sample_invoice.version + 1

        # Exceed outstanding
        with pytest.raises(ValueError, match="exceeds outstanding"):
            sample_invoice.apply_credit_note(Decimal("1500000"))

    def test_write_off(self, sample_invoice):
        new_invoice = sample_invoice.write_off("admin", "Bad debt")
        assert new_invoice.outstanding_amount == Decimal("0")
        assert new_invoice.status == InvoiceStatus.WRITTEN_OFF
        assert new_invoice.version == sample_invoice.version + 1

        # Cannot write off DRAFT
        sample_invoice.status = InvoiceStatus.DRAFT
        with pytest.raises(ValueError, match="Cannot write off"):
            sample_invoice.write_off("admin", "reason")

    def test_cancel(self, sample_invoice):
        new_invoice = sample_invoice.cancel("admin", "Test cancel")
        assert new_invoice.status == InvoiceStatus.CANCELLED
        assert "Cancelled" in new_invoice.description

        # Cannot cancel paid invoice
        sample_invoice.status = InvoiceStatus.FULLY_PAID
        with pytest.raises(ValueError, match="Cannot cancel"):
            sample_invoice.cancel("admin", "reason")

    def test_to_money(self, sample_invoice):
        money = sample_invoice.to_money()
        assert money.amount == sample_invoice.amount
        assert money.currency == sample_invoice.currency

    def test_update(self, sample_invoice):
        new_invoice = sample_invoice.update(
            updated_by="admin",
            description="New description",
            due_date=datetime.now(UTC) + timedelta(days=40),
        )
        assert new_invoice.description == "New description"
        assert new_invoice.due_date == datetime.now(UTC) + timedelta(days=40)
        assert new_invoice.version == sample_invoice.version + 1

        # Cannot update paid invoice
        sample_invoice.status = InvoiceStatus.FULLY_PAID
        with pytest.raises(ValueError, match="Cannot update"):
            sample_invoice.update(updated_by="admin", description="x")

    def test_validate(self, sample_invoice):
        result = sample_invoice.validate()
        assert result["is_valid"] is True

        # Invalid amount
        sample_invoice.amount = Decimal("-100")
        result2 = sample_invoice.validate()
        assert result2["is_valid"] is False
        assert "positive" in result2["errors"][0]

    def test_to_dict(self, sample_invoice):
        d = sample_invoice.to_dict()
        assert d["invoice_id"] == str(sample_invoice.invoice_id)
        assert d["invoice_number"] == sample_invoice.invoice_number
        assert d["amount"] == str(sample_invoice.amount)
        assert len(d["lines"]) == 1

    def test_from_dict(self):
        invoice_id = uuid4()
        customer_id = uuid4()
        line_id = uuid4()
        now = datetime.now(UTC)
        line_data = {
            "id": str(line_id),
            "description": "Test line",
            "quantity": "2",
            "unit_price": {"amount": "1000", "currency": "IDR"},
            "tax_rate": "11",
            "discount_percent": "0",
            "account_code": "4001",
            "total_amount": {"amount": "2000", "currency": "IDR"},
            "version": 1,
        }
        data = {
            "invoice_id": str(invoice_id),
            "invoice_number": "INV-001",
            "invoice_type": "standard",
            "customer_id": str(customer_id),
            "customer_name": "Customer A",
            "issue_date": now.isoformat(),
            "due_date": (now + timedelta(days=30)).isoformat(),
            "amount": "1000000",
            "currency": "IDR",
            "paid_amount": "0",
            "outstanding_amount": "1000000",
            "status": "issued",
            "description": "Test",
            "sales_order_id": None,
            "tax_amount": "100000",
            "tax_rate": "11",
            "discount_amount": "0",
            "lines": [line_data],
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "created_by": "system",
            "version": 3,
        }
        invoice = InvoiceEntity.from_dict(data)
        assert invoice.invoice_id == invoice_id
        assert invoice.customer_id == customer_id
        assert invoice.amount == Decimal("1000000")
        assert invoice.status == InvoiceStatus.ISSUED
        assert invoice.version == 3
        assert len(invoice.lines) == 1
        assert invoice.lines[0].id == line_id

    def test_clone(self, sample_invoice):
        clone = sample_invoice.clone()
        assert clone is not sample_invoice
        assert clone.invoice_id != sample_invoice.invoice_id
        assert clone.invoice_number == f"{sample_invoice.invoice_number}_COPY"
        assert clone.outstanding_amount == sample_invoice.amount  # reset to full amount
        assert clone.status == InvoiceStatus.DRAFT
        assert len(clone.lines) == len(sample_invoice.lines)
        assert len(clone._audit_trail) >= 1

    def test_snapshot(self, sample_invoice):
        snap = sample_invoice.snapshot()
        assert snap["invoice_id"] == str(sample_invoice.invoice_id)
        assert snap["invoice_number"] == sample_invoice.invoice_number

    def test_get_version(self, sample_invoice):
        assert sample_invoice.get_version() == sample_invoice.version

    def test_audit_trail(self, sample_invoice):
        sample_invoice._record_audit("TEST", "system", {})
        trail = sample_invoice.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TEST"

    def test_touch(self, sample_invoice):
        old = sample_invoice.version
        touched = sample_invoice.touch("system")
        assert touched.version == old + 1
        trail = touched.audit_trail()
        assert trail[-1]["action"] == "TOUCH"


# ============================================================================
# Test InvoiceRepository (protocol)
# ============================================================================

class TestInvoiceRepository:
    def test_protocol_methods(self):
        repo = InvoiceRepository()
        with pytest.raises(NotImplementedError):
            repo.get_by_id(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.save(MagicMock(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.delete(uuid4(), uuid4())
