# test_invoice_entity.py
# =======================
# Comprehensive tests for domain/subledger_ap/invoice_entity.py.
# Covers all enums, value objects, entity methods, edge cases, and decimal precision.

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from domain.shared_value_objects.money_vo import Money
from domain.subledger_ap.invoice_entity import (
    APInvoice,
    APInvoiceEntity,
    APInvoiceLine,
    APInvoiceRepository,
    APInvoiceStatus,
    APInvoiceType,
)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def sample_money() -> Money:
    return Money(Decimal("100.00"), "IDR")


@pytest.fixture
def sample_invoice_line(sample_money) -> APInvoiceLine:
    return APInvoiceLine(
        id=uuid4(),
        description="Test line",
        quantity=Decimal("2"),
        unit_price=sample_money,
        tax_rate=Decimal("11"),
        discount_percent=Decimal("5"),
        account_code="1010",
        total_amount=Money(Decimal("190.00"), "IDR"),
        purchase_order_line_id=uuid4(),
        goods_receipt_line_id=uuid4(),
        tax_amount=Decimal("20.90"),
        discount_amount=Decimal("10.00"),
        currency="IDR",
    )


@pytest.fixture
def sample_invoice() -> APInvoiceEntity:
    """Create a valid APInvoiceEntity in DRAFT state."""
    now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
    due = now + timedelta(days=30)
    return APInvoiceEntity.create(
        invoice_number="INV-001",
        invoice_type=APInvoiceType.STANDARD,
        vendor_id=uuid4(),
        vendor_name="PT Supplier",
        invoice_date=now,
        due_date=due,
        amount=Decimal("1000.00"),
        currency="IDR",
        created_by="tester",
        description="Test invoice",
        purchase_order_id=uuid4(),
    )


@pytest.fixture
def sample_invoice_with_lines(sample_invoice, sample_invoice_line) -> APInvoiceEntity:
    return sample_invoice.add_line(sample_invoice_line, "tester")


# ----------------------------------------------------------------------
# APInvoiceStatus Enum
# ----------------------------------------------------------------------
class TestAPInvoiceStatus:
    def test_members_exist(self):
        assert hasattr(APInvoiceStatus, "DRAFT")
        assert hasattr(APInvoiceStatus, "RECEIVED")
        assert hasattr(APInvoiceStatus, "VERIFIED")
        assert hasattr(APInvoiceStatus, "PARTIALLY_PAID")
        assert hasattr(APInvoiceStatus, "FULLY_PAID")
        assert hasattr(APInvoiceStatus, "OVERDUE")
        assert hasattr(APInvoiceStatus, "DISPUTED")
        assert hasattr(APInvoiceStatus, "CANCELLED")

    def test_member_is_instance(self):
        assert isinstance(APInvoiceStatus.DRAFT, APInvoiceStatus)

    def test_from_string_valid(self):
        assert APInvoiceStatus.from_string("draft") == APInvoiceStatus.DRAFT
        assert APInvoiceStatus.from_string("DRAFT") == APInvoiceStatus.DRAFT
        assert APInvoiceStatus.from_string("received") == APInvoiceStatus.RECEIVED
        assert APInvoiceStatus.from_string("verified") == APInvoiceStatus.VERIFIED
        assert APInvoiceStatus.from_string("partial") == APInvoiceStatus.PARTIALLY_PAID
        assert APInvoiceStatus.from_string("paid") == APInvoiceStatus.FULLY_PAID
        assert APInvoiceStatus.from_string("overdue") == APInvoiceStatus.OVERDUE
        assert APInvoiceStatus.from_string("disputed") == APInvoiceStatus.DISPUTED
        assert APInvoiceStatus.from_string("cancelled") == APInvoiceStatus.CANCELLED

    def test_from_string_invalid_defaults_draft(self):
        assert APInvoiceStatus.from_string("unknown") == APInvoiceStatus.DRAFT
        assert APInvoiceStatus.from_string("") == APInvoiceStatus.DRAFT


# ----------------------------------------------------------------------
# APInvoiceType Enum
# ----------------------------------------------------------------------
class TestAPInvoiceType:
    def test_members_exist(self):
        assert hasattr(APInvoiceType, "STANDARD")
        assert hasattr(APInvoiceType, "CREDIT")
        assert hasattr(APInvoiceType, "DEBIT")
        assert hasattr(APInvoiceType, "PREPAYMENT")

    def test_member_is_instance(self):
        assert isinstance(APInvoiceType.STANDARD, APInvoiceType)

    def test_from_string_valid(self):
        assert APInvoiceType.from_string("standard") == APInvoiceType.STANDARD
        assert APInvoiceType.from_string("STANDARD") == APInvoiceType.STANDARD
        assert APInvoiceType.from_string("credit") == APInvoiceType.CREDIT
        assert APInvoiceType.from_string("debit") == APInvoiceType.DEBIT
        assert APInvoiceType.from_string("prepayment") == APInvoiceType.PREPAYMENT

    def test_from_string_invalid_defaults_standard(self):
        assert APInvoiceType.from_string("unknown") == APInvoiceType.STANDARD
        assert APInvoiceType.from_string("") == APInvoiceType.STANDARD


# ----------------------------------------------------------------------
# APInvoiceLine Value Object
# ----------------------------------------------------------------------
class TestAPInvoiceLine:
    def test_construction_valid(self, sample_invoice_line):
        assert sample_invoice_line.id is not None
        assert sample_invoice_line.description == "Test line"
        assert sample_invoice_line.quantity == Decimal("2")
        assert sample_invoice_line.unit_price.amount == Decimal("100.00")
        assert sample_invoice_line.tax_rate == Decimal("11")
        assert sample_invoice_line.discount_percent == Decimal("5")
        assert sample_invoice_line.account_code == "1010"
        assert sample_invoice_line.currency == "IDR"

    def test_validation_quantity_zero_raises(self, sample_money):
        with pytest.raises(ValueError, match="Quantity must be positive"):
            APInvoiceLine(
                id=uuid4(),
                description="Test",
                quantity=Decimal("0"),
                unit_price=sample_money,
                tax_rate=Decimal("11"),
                discount_percent=Decimal("0"),
                account_code="1010",
                total_amount=sample_money,
                currency="IDR",
            )

    def test_validation_unit_price_negative_raises(self):
        with pytest.raises(ValueError, match="Unit price cannot be negative"):
            APInvoiceLine(
                id=uuid4(),
                description="Test",
                quantity=Decimal("1"),
                unit_price=Money(Decimal("-10"), "IDR"),
                tax_rate=Decimal("11"),
                discount_percent=Decimal("0"),
                account_code="1010",
                total_amount=Money(Decimal("0"), "IDR"),
                currency="IDR",
            )

    def test_validation_tax_rate_out_of_range_raises(self, sample_money):
        with pytest.raises(ValueError, match="Tax rate must be between 0 and 100"):
            APInvoiceLine(
                id=uuid4(),
                description="Test",
                quantity=Decimal("1"),
                unit_price=sample_money,
                tax_rate=Decimal("101"),
                discount_percent=Decimal("0"),
                account_code="1010",
                total_amount=sample_money,
                currency="IDR",
            )

    def test_validation_discount_percent_out_of_range_raises(self, sample_money):
        with pytest.raises(ValueError, match="Discount percent must be between 0 and 100"):
            APInvoiceLine(
                id=uuid4(),
                description="Test",
                quantity=Decimal("1"),
                unit_price=sample_money,
                tax_rate=Decimal("11"),
                discount_percent=Decimal("-5"),
                account_code="1010",
                total_amount=sample_money,
                currency="IDR",
            )

    def test_validation_account_code_short_raises(self, sample_money):
        with pytest.raises(ValueError, match="Account code must be at least 3 characters"):
            APInvoiceLine(
                id=uuid4(),
                description="Test",
                quantity=Decimal("1"),
                unit_price=sample_money,
                tax_rate=Decimal("11"),
                discount_percent=Decimal("0"),
                account_code="10",
                total_amount=sample_money,
                currency="IDR",
            )

    def test_validation_currency_mismatch_raises(self):
        with pytest.raises(ValueError, match="Currency mismatch"):
            APInvoiceLine(
                id=uuid4(),
                description="Test",
                quantity=Decimal("1"),
                unit_price=Money(Decimal("100"), "USD"),
                tax_rate=Decimal("11"),
                discount_percent=Decimal("0"),
                account_code="1010",
                total_amount=Money(Decimal("100"), "IDR"),
                currency="IDR",
            )

    def test_subtotal_property(self, sample_invoice_line):
        assert sample_invoice_line.subtotal == Decimal("200.00")  # 2 * 100

    def test_discount_amount_calc_property(self, sample_invoice_line):
        # subtotal = 200, discount 5% => 10.00
        assert sample_invoice_line.discount_amount_calc == Decimal("10.00")

    def test_taxable_amount_property(self, sample_invoice_line):
        # subtotal 200 - discount 10 = 190
        assert sample_invoice_line.taxable_amount == Decimal("190.00")

    def test_tax_amount_calc_property(self, sample_invoice_line):
        # taxable 190 * 11% = 20.9
        assert sample_invoice_line.tax_amount_calc == Decimal("20.90")

    def test_line_total_property(self, sample_invoice_line):
        # taxable 190 + tax 20.9 = 210.9
        assert sample_invoice_line.line_total == Decimal("210.90")

    def test_to_dict(self, sample_invoice_line):
        d = sample_invoice_line.to_dict()
        assert d["id"] == str(sample_invoice_line.id)
        assert d["description"] == "Test line"
        assert d["quantity"] == "2"
        assert d["unit_price"] == "100.00"
        assert d["tax_rate"] == "11"
        assert d["discount_percent"] == "5"
        assert d["account_code"] == "1010"
        assert d["subtotal"] == "200.00"
        assert d["tax_amount"] == "20.90"
        assert d["discount_amount"] == "10.00"
        assert d["line_total"] == "210.90"

    def test_from_dict(self, sample_invoice_line):
        d = sample_invoice_line.to_dict()
        # Add missing fields for full reconstruction
        d["total_amount"] = "190.00"
        d["currency"] = "IDR"
        reconstructed = APInvoiceLine.from_dict(d)
        assert reconstructed.id == sample_invoice_line.id
        assert reconstructed.quantity == sample_invoice_line.quantity
        assert reconstructed.unit_price.amount == sample_invoice_line.unit_price.amount
        assert reconstructed.tax_rate == sample_invoice_line.tax_rate
        assert reconstructed.discount_percent == sample_invoice_line.discount_percent
        assert reconstructed.account_code == sample_invoice_line.account_code
        assert reconstructed.total_amount.amount == Decimal("190.00")


# ----------------------------------------------------------------------
# APInvoiceEntity - Construction & Validation
# ----------------------------------------------------------------------
class TestAPInvoiceEntityConstruction:
    def test_create_success(self, sample_invoice):
        assert sample_invoice.invoice_id is not None
        assert sample_invoice.invoice_number == "INV-001"
        assert sample_invoice.invoice_type == APInvoiceType.STANDARD
        assert sample_invoice.vendor_name == "PT Supplier"
        assert sample_invoice.amount == Decimal("1000.00")
        assert sample_invoice.paid_amount == Decimal("0")
        assert sample_invoice.outstanding_amount == Decimal("1000.00")
        assert sample_invoice.status == APInvoiceStatus.DRAFT
        assert sample_invoice.version == 1
        assert sample_invoice.created_at.tzinfo == UTC

    def test_validation_amount_zero_raises(self):
        with pytest.raises(ValueError, match="Invoice amount must be positive"):
            APInvoiceEntity.create(
                invoice_number="INV-001",
                invoice_type=APInvoiceType.STANDARD,
                vendor_id=uuid4(),
                vendor_name="Vendor",
                invoice_date=datetime.now(UTC),
                due_date=datetime.now(UTC) + timedelta(days=1),
                amount=Decimal("0"),
                currency="IDR",
                created_by="tester",
            )

    def test_validation_due_date_before_invoice_raises(self):
        now = datetime.now(UTC)
        with pytest.raises(ValueError, match="Due date must be after invoice date"):
            APInvoiceEntity.create(
                invoice_number="INV-001",
                invoice_type=APInvoiceType.STANDARD,
                vendor_id=uuid4(),
                vendor_name="Vendor",
                invoice_date=now,
                due_date=now - timedelta(days=1),
                amount=Decimal("100"),
                currency="IDR",
                created_by="tester",
            )

    def test_validation_paid_amount_negative_raises(self):
        with pytest.raises(ValueError, match="Paid amount cannot be negative"):
            APInvoiceEntity(
                invoice_id=uuid4(),
                invoice_number="INV-001",
                invoice_type=APInvoiceType.STANDARD,
                vendor_id=uuid4(),
                vendor_name="Vendor",
                invoice_date=datetime.now(UTC),
                due_date=datetime.now(UTC) + timedelta(days=1),
                amount=Decimal("100"),
                currency="IDR",
                paid_amount=Decimal("-10"),
                outstanding_amount=Decimal("110"),
                status=APInvoiceStatus.DRAFT,
                description="Test",
                created_by="system",
            )

    def test_validation_amount_mismatch_raises(self):
        with pytest.raises(ValueError, match="Amount mismatch"):
            APInvoiceEntity(
                invoice_id=uuid4(),
                invoice_number="INV-001",
                invoice_type=APInvoiceType.STANDARD,
                vendor_id=uuid4(),
                vendor_name="Vendor",
                invoice_date=datetime.now(UTC),
                due_date=datetime.now(UTC) + timedelta(days=1),
                amount=Decimal("100"),
                currency="IDR",
                paid_amount=Decimal("30"),
                outstanding_amount=Decimal("80"),
                status=APInvoiceStatus.DRAFT,
                description="Test",
                created_by="system",
            )

    def test_validation_naive_dates_auto_utc(self):
        naive = datetime(2025, 1, 1, 10, 0)
        invoice = APInvoiceEntity(
            invoice_id=uuid4(),
            invoice_number="INV-001",
            invoice_type=APInvoiceType.STANDARD,
            vendor_id=uuid4(),
            vendor_name="Vendor",
            invoice_date=naive,
            due_date=naive + timedelta(days=1),
            amount=Decimal("100"),
            currency="IDR",
            paid_amount=Decimal("0"),
            outstanding_amount=Decimal("100"),
            status=APInvoiceStatus.DRAFT,
            description="Test",
            created_by="system",
        )
        assert invoice.invoice_date.tzinfo == UTC
        assert invoice.due_date.tzinfo == UTC
        assert invoice.created_at.tzinfo == UTC
        assert invoice.updated_at.tzinfo == UTC


# ----------------------------------------------------------------------
# APInvoiceEntity - Audit Trail
# ----------------------------------------------------------------------
class TestAPInvoiceEntityAudit:
    def test_audit_trail_initial_empty(self, sample_invoice):
        trail = sample_invoice.get_audit_trail()
        assert trail == []

    def test_audit_trail_appends_on_receive(self, sample_invoice):
        received = sample_invoice.receive("alice")
        trail = received.get_audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "received"
        assert trail[0]["user_id"] == "alice"
        assert trail[0]["version"] == 2

    def test_audit_trail_appends_on_add_line(self, sample_invoice, sample_invoice_line):
        updated = sample_invoice.add_line(sample_invoice_line, "bob")
        trail = updated.get_audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "line_added"
        assert trail[0]["user_id"] == "bob"
        assert trail[0]["details"]["line_id"] == str(sample_invoice_line.id)


# ----------------------------------------------------------------------
# APInvoiceEntity - Business Methods (add_line, remove_line, record_payment, receive, verify, dispute, cancel, mark_overdue)
# ----------------------------------------------------------------------
class TestAPInvoiceEntityBusiness:
    def test_add_line_recalculates_amount(self, sample_invoice, sample_invoice_line):
        updated = sample_invoice.add_line(sample_invoice_line, "tester")
        # line total = 210.90
        assert updated.amount == Decimal("210.90")
        assert updated.outstanding_amount == Decimal("210.90")
        assert len(updated.lines) == 1
        assert updated.version == sample_invoice.version + 1

    def test_remove_line_success(self, sample_invoice_with_lines):
        line_id = sample_invoice_with_lines.lines[0].id
        updated = sample_invoice_with_lines.remove_line(line_id, "tester")
        assert len(updated.lines) == 0
        assert updated.amount == Decimal("0")
        assert updated.outstanding_amount == Decimal("0")
        assert updated.version == sample_invoice_with_lines.version + 1

    def test_remove_line_not_found_raises(self, sample_invoice_with_lines):
        with pytest.raises(ValueError, match="Line .* not found"):
            sample_invoice_with_lines.remove_line(uuid4(), "tester")

    def test_record_payment_full(self, sample_invoice):
        payment_id = uuid4()
        updated = sample_invoice.record_payment(Decimal("1000.00"), payment_id)
        assert updated.paid_amount == Decimal("1000.00")
        assert updated.outstanding_amount == Decimal("0")
        assert updated.status == APInvoiceStatus.FULLY_PAID
        assert updated.version == sample_invoice.version + 1

    def test_record_payment_partial(self, sample_invoice):
        payment_id = uuid4()
        updated = sample_invoice.record_payment(Decimal("300.00"), payment_id)
        assert updated.paid_amount == Decimal("300.00")
        assert updated.outstanding_amount == Decimal("700.00")
        assert updated.status == APInvoiceStatus.PARTIALLY_PAID

    def test_record_payment_exceeds_outstanding_raises(self, sample_invoice):
        with pytest.raises(ValueError, match="Payment amount .* exceeds outstanding"):
            sample_invoice.record_payment(Decimal("1500.00"), uuid4())

    def test_record_payment_zero_raises(self, sample_invoice):
        with pytest.raises(ValueError, match="Payment amount must be positive"):
            sample_invoice.record_payment(Decimal("0"), uuid4())

    def test_receive_success(self, sample_invoice):
        received = sample_invoice.receive("alice")
        assert received.status == APInvoiceStatus.RECEIVED
        assert received.version == sample_invoice.version + 1

    def test_receive_not_draft_raises(self, sample_invoice):
        received = sample_invoice.receive("alice")
        with pytest.raises(ValueError, match="Cannot receive invoice in status received"):
            received.receive("bob")

    def test_verify_success(self, sample_invoice):
        received = sample_invoice.receive("alice")
        verified = received.verify("bob")
        assert verified.status == APInvoiceStatus.VERIFIED

    def test_verify_not_received_raises(self, sample_invoice):
        with pytest.raises(ValueError, match="Cannot verify invoice in status draft"):
            sample_invoice.verify("bob")

    def test_dispute_success(self, sample_invoice):
        received = sample_invoice.receive("alice")
        disputed = received.dispute("carol", "Price mismatch")
        assert disputed.status == APInvoiceStatus.DISPUTED
        assert "Price mismatch" in disputed.description

    def test_dispute_not_received_or_verified_raises(self, sample_invoice):
        with pytest.raises(ValueError, match="Cannot dispute invoice in status draft"):
            sample_invoice.dispute("carol", "Reason")

    def test_cancel_draft_success(self, sample_invoice):
        cancelled = sample_invoice.cancel("dave", "No longer needed")
        assert cancelled.status == APInvoiceStatus.CANCELLED
        assert "No longer needed" in cancelled.description

    def test_cancel_received_success(self, sample_invoice):
        received = sample_invoice.receive("alice")
        cancelled = received.cancel("dave", "Cancel after receive")
        assert cancelled.status == APInvoiceStatus.CANCELLED

    def test_cancel_disputed_success(self, sample_invoice):
        received = sample_invoice.receive("alice")
        disputed = received.dispute("carol", "Reason")
        cancelled = disputed.cancel("dave", "Resolved")
        assert cancelled.status == APInvoiceStatus.CANCELLED

    def test_cancel_verified_raises(self, sample_invoice):
        received = sample_invoice.receive("alice")
        verified = received.verify("bob")
        with pytest.raises(ValueError, match="Cannot cancel invoice in status verified"):
            verified.cancel("dave", "Reason")

    def test_mark_overdue_success(self, sample_invoice):
        # Set due_date in past
        overdue_invoice = APInvoiceEntity(
            invoice_id=sample_invoice.invoice_id,
            invoice_number=sample_invoice.invoice_number,
            invoice_type=sample_invoice.invoice_type,
            vendor_id=sample_invoice.vendor_id,
            vendor_name=sample_invoice.vendor_name,
            invoice_date=sample_invoice.invoice_date,
            due_date=datetime.now(UTC) - timedelta(days=5),
            amount=sample_invoice.amount,
            currency=sample_invoice.currency,
            paid_amount=sample_invoice.paid_amount,
            outstanding_amount=sample_invoice.outstanding_amount,
            status=sample_invoice.status,
            description=sample_invoice.description,
            created_by=sample_invoice.created_by,
        )
        marked = overdue_invoice.mark_overdue()
        assert marked.status == APInvoiceStatus.OVERDUE
        assert marked.version == overdue_invoice.version + 1

    def test_mark_overdue_paid_raises(self, sample_invoice):
        paid = sample_invoice.record_payment(Decimal("1000.00"), uuid4())
        with pytest.raises(ValueError, match="Cannot mark invoice as overdue in status paid"):
            paid.mark_overdue()


# ----------------------------------------------------------------------
# APInvoiceEntity - Query Methods (is_overdue, days_overdue)
# ----------------------------------------------------------------------
class TestAPInvoiceEntityQueries:
    def test_is_overdue_true(self):
        now = datetime.now(UTC)
        invoice = APInvoiceEntity(
            invoice_id=uuid4(),
            invoice_number="INV-001",
            invoice_type=APInvoiceType.STANDARD,
            vendor_id=uuid4(),
            vendor_name="Vendor",
            invoice_date=now - timedelta(days=30),
            due_date=now - timedelta(days=5),
            amount=Decimal("100"),
            currency="IDR",
            paid_amount=Decimal("0"),
            outstanding_amount=Decimal("100"),
            status=APInvoiceStatus.VERIFIED,
            description="Test",
            created_by="system",
        )
        assert invoice.is_overdue() is True

    def test_is_overdue_false_when_paid(self):
        now = datetime.now(UTC)
        invoice = APInvoiceEntity(
            invoice_id=uuid4(),
            invoice_number="INV-001",
            invoice_type=APInvoiceType.STANDARD,
            vendor_id=uuid4(),
            vendor_name="Vendor",
            invoice_date=now - timedelta(days=30),
            due_date=now - timedelta(days=5),
            amount=Decimal("100"),
            currency="IDR",
            paid_amount=Decimal("100"),
            outstanding_amount=Decimal("0"),
            status=APInvoiceStatus.FULLY_PAID,
            description="Test",
            created_by="system",
        )
        assert invoice.is_overdue() is False

    def test_is_overdue_false_when_cancelled(self, sample_invoice):
        cancelled = sample_invoice.cancel("dave", "Reason")
        assert cancelled.is_overdue() is False

    def test_is_overdue_false_when_not_past_due(self, sample_invoice):
        assert sample_invoice.is_overdue() is False

    def test_days_overdue(self):
        now = datetime.now(UTC)
        due = now - timedelta(days=10)
        invoice = APInvoiceEntity(
            invoice_id=uuid4(),
            invoice_number="INV-001",
            invoice_type=APInvoiceType.STANDARD,
            vendor_id=uuid4(),
            vendor_name="Vendor",
            invoice_date=now - timedelta(days=20),
            due_date=due,
            amount=Decimal("100"),
            currency="IDR",
            paid_amount=Decimal("0"),
            outstanding_amount=Decimal("100"),
            status=APInvoiceStatus.VERIFIED,
            description="Test",
            created_by="system",
        )
        assert invoice.days_overdue() == 10

    def test_days_overdue_zero_when_not_overdue(self, sample_invoice):
        assert sample_invoice.days_overdue() == 0


# ----------------------------------------------------------------------
# APInvoiceEntity - Serialization
# ----------------------------------------------------------------------
class TestAPInvoiceEntitySerialization:
    def test_to_dict(self, sample_invoice):
        d = sample_invoice.to_dict()
        assert d["invoice_id"] == str(sample_invoice.invoice_id)
        assert d["invoice_number"] == "INV-001"
        assert d["amount"] == "1000.00"
        assert d["status"] == "draft"
        assert d["is_overdue"] is False
        assert d["days_overdue"] == 0

    def test_to_dict_with_lines(self, sample_invoice_with_lines):
        d = sample_invoice_with_lines.to_dict()
        assert len(d["lines"]) == 1
        assert d["lines"][0]["description"] == "Test line"

    def test_from_dict(self, sample_invoice):
        d = sample_invoice.to_dict()
        reconstructed = APInvoiceEntity.from_dict(d)
        assert reconstructed.invoice_id == sample_invoice.invoice_id
        assert reconstructed.invoice_number == sample_invoice.invoice_number
        assert reconstructed.amount == sample_invoice.amount
        assert reconstructed.status == sample_invoice.status
        assert reconstructed.version == sample_invoice.version

    def test_from_dict_with_lines(self, sample_invoice_with_lines):
        d = sample_invoice_with_lines.to_dict()
        reconstructed = APInvoiceEntity.from_dict(d)
        assert len(reconstructed.lines) == 1
        assert reconstructed.lines[0].id == sample_invoice_with_lines.lines[0].id


# ----------------------------------------------------------------------
# APInvoiceRepository (Interface)
# ----------------------------------------------------------------------
class TestAPInvoiceRepository:
    @pytest.mark.asyncio
    async def test_get_by_id_not_implemented(self):
        repo = APInvoiceRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_id(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_get_by_number_not_implemented(self):
        repo = APInvoiceRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_number("INV-001", uuid4())

    @pytest.mark.asyncio
    async def test_get_by_vendor_not_implemented(self):
        repo = APInvoiceRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_vendor(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_get_by_po_not_implemented(self):
        repo = APInvoiceRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_po(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_get_overdue_not_implemented(self):
        repo = APInvoiceRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_overdue(uuid4())

    @pytest.mark.asyncio
    async def test_get_by_date_range_not_implemented(self):
        repo = APInvoiceRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_date_range(uuid4(), datetime.now(UTC), datetime.now(UTC))

    @pytest.mark.asyncio
    async def test_save_not_implemented(self):
        repo = APInvoiceRepository()
        with pytest.raises(NotImplementedError):
            await repo.save(MagicMock(), uuid4())

    @pytest.mark.asyncio
    async def test_delete_not_implemented(self):
        repo = APInvoiceRepository()
        with pytest.raises(NotImplementedError):
            await repo.delete(uuid4(), uuid4())


# ----------------------------------------------------------------------
# Edge Cases & Decimal Precision
# ----------------------------------------------------------------------
class TestEdgeCases:
    def test_decimal_precision_discount_amount_calc(self, sample_invoice_line):
        # Test with repeating decimals
        line = APInvoiceLine(
            id=uuid4(),
            description="Test",
            quantity=Decimal("3"),
            unit_price=Money(Decimal("100"), "IDR"),
            tax_rate=Decimal("11"),
            discount_percent=Decimal("33.33"),
            account_code="1010",
            total_amount=Money(Decimal("200"), "IDR"),
            currency="IDR",
        )
        # subtotal = 300, discount = 300 * 0.3333 = 99.99 (quantized to 2 decimals)
        expected_discount = (Decimal("300") * Decimal("33.33") / Decimal("100")).quantize(Decimal("0.01"))
        assert line.discount_amount_calc == expected_discount

    def test_decimal_precision_tax_amount_calc(self, sample_invoice_line):
        # Test with repeating decimals
        line = APInvoiceLine(
            id=uuid4(),
            description="Test",
            quantity=Decimal("1"),
            unit_price=Money(Decimal("100"), "IDR"),
            tax_rate=Decimal("11"),
            discount_percent=Decimal("0"),
            account_code="1010",
            total_amount=Money(Decimal("100"), "IDR"),
            currency="IDR",
        )
        # taxable = 100, tax = 11.00
        assert line.tax_amount_calc == Decimal("11.00")
        # With discount that creates non-terminating decimal
        line2 = APInvoiceLine(
            id=uuid4(),
            description="Test",
            quantity=Decimal("1"),
            unit_price=Money(Decimal("100"), "IDR"),
            tax_rate=Decimal("11"),
            discount_percent=Decimal("33.33"),
            account_code="1010",
            total_amount=Money(Decimal("100"), "IDR"),
            currency="IDR",
        )
        # taxable = 100 - 33.33 = 66.67, tax = 66.67 * 0.11 = 7.3337 -> 7.33
        expected_tax = (Decimal("66.67") * Decimal("11") / Decimal("100")).quantize(Decimal("0.01"))
        assert line2.tax_amount_calc == expected_tax

    def test_large_numbers(self):
        huge = Decimal("9999999999.99")
        invoice = APInvoiceEntity.create(
            invoice_number="INV-001",
            invoice_type=APInvoiceType.STANDARD,
            vendor_id=uuid4(),
            vendor_name="Vendor",
            invoice_date=datetime.now(UTC),
            due_date=datetime.now(UTC) + timedelta(days=1),
            amount=huge,
            currency="IDR",
            created_by="tester",
        )
        assert invoice.amount == huge
        assert invoice.outstanding_amount == huge

    def test_alias_ap_invoice(self):
        assert APInvoice is APInvoiceEntity
