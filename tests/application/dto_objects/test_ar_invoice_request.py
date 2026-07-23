# test_ar_invoice_request.py
# Comprehensive tests for application/dto_objects/ar_invoice_request.py
# Covers all classes, methods, properties, edge cases, and exceptions.

import pytest
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_EVEN
from uuid import UUID, uuid4

from application.dto_objects.ar_invoice_request import (
    ARInvoiceLineRequest,
    ARInvoiceRequestFactory,
    ARInvoiceResponseDTO,
    ARInvoiceStatus,
    ARInvoiceStatusDTO,
    ARInvoiceType,
    ARPaymentResponseDTO,
    CreateARCreditNoteRequest,
    CreateARInvoiceRequest,
    CreditNoteReason,
    GetARAgingRequest,
    GetARInvoiceRequest,
    ListARInvoicesRequest,
    PaymentMethod,
    PaymentStatus,
    RecordARPaymentRequest,
    UpdateARInvoiceRequest,
    WriteOffARInvoiceRequest,
)


# -------------------- Fixtures --------------------
@pytest.fixture
def sample_item_id():
    return uuid4()


@pytest.fixture
def sample_customer_id():
    return uuid4()


@pytest.fixture
def sample_invoice_id():
    return uuid4()


@pytest.fixture
def sample_legal_entity_id():
    return uuid4()


@pytest.fixture
def sample_line_request(sample_item_id):
    return ARInvoiceLineRequest(
        item_id=sample_item_id,
        item_code="ITEM001",
        item_name="Test Item",
        quantity=Decimal("2"),
        unit_price=Decimal("100000"),
        discount_percentage=Decimal("10"),
        tax_rate=Decimal("11"),
        unit_of_measure="PCS",
        description="Test line",
    )


@pytest.fixture
def sample_create_request(sample_customer_id, sample_line_request):
    issue_date = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
    due_date = issue_date + timedelta(days=30)
    return CreateARInvoiceRequest(
        invoice_number="INV-001",
        customer_id=sample_customer_id,
        customer_name="Test Customer",
        issue_date=issue_date,
        due_date=due_date,
        lines=[sample_line_request],
        invoice_type=ARInvoiceType.STANDARD,
        currency="IDR",
        description="Test invoice",
        sales_order_id=uuid4(),
        sales_order_number="SO-001",
        shipping_cost=Decimal("50000"),
        other_costs=Decimal("10000"),
        discount_amount=Decimal("5000"),
        notes="Test notes",
        idempotency_key="key123",
    )


@pytest.fixture
def sample_update_request(sample_invoice_id):
    return UpdateARInvoiceRequest(
        invoice_id=sample_invoice_id,
        due_date=datetime(2025, 2, 1, 0, 0, 0, tzinfo=UTC),
        description="Updated desc",
        notes="Updated notes",
        shipping_cost=Decimal("60000"),
        other_costs=Decimal("15000"),
        discount_amount=Decimal("6000"),
    )


@pytest.fixture
def sample_payment_request(sample_customer_id, sample_invoice_id):
    return RecordARPaymentRequest(
        payment_number="PAY-001",
        customer_id=sample_customer_id,
        customer_name="Test Customer",
        payment_date=datetime(2025, 1, 15, 0, 0, 0, tzinfo=UTC),
        amount=Decimal("2000000"),
        payment_method=PaymentMethod.BANK_TRANSFER,
        currency="IDR",
        invoice_id=sample_invoice_id,
        invoice_number="INV-001",
        reference_number="REF123",
        bank_reference="BK123",
        notes="Payment notes",
        idempotency_key="paykey",
    )


@pytest.fixture
def sample_credit_note_request(sample_invoice_id, sample_customer_id):
    return CreateARCreditNoteRequest(
        credit_note_number="CN-001",
        invoice_id=sample_invoice_id,
        invoice_number="INV-001",
        customer_id=sample_customer_id,
        customer_name="Test Customer",
        amount=Decimal("500000"),
        reason=CreditNoteReason.GOODS_RETURN,
        currency="IDR",
        description="Credit note for return",
        tax_amount=Decimal("55000"),
        tax_rate=Decimal("11"),
        notes="Credit notes",
        idempotency_key="cnkey",
    )


@pytest.fixture
def sample_write_off_request(sample_invoice_id, sample_customer_id):
    return WriteOffARInvoiceRequest(
        invoice_id=sample_invoice_id,
        invoice_number="INV-001",
        customer_id=sample_customer_id,
        customer_name="Test Customer",
        amount=Decimal("1000000"),
        reason="Customer bankrupt",
        written_off_by="admin",
        notes="Write-off approved",
        approval_reference="APP-001",
    )


@pytest.fixture
def sample_response_dto(sample_invoice_id, sample_customer_id):
    return ARInvoiceResponseDTO(
        id=sample_invoice_id,
        invoice_number="INV-001",
        customer_id=sample_customer_id,
        customer_name="Test Customer",
        invoice_date=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
        due_date=datetime(2025, 1, 31, 0, 0, 0, tzinfo=UTC),
        amount=Decimal("2500000"),
        paid_amount=Decimal("500000"),
        remaining_amount=Decimal("2000000"),
        currency="IDR",
        status="issued",
        tax_amount=Decimal("250000"),
        created_at=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
        version=1,
        tax_code="PPN",
        description="Test invoice",
    )


# -------------------- Tests for Enums --------------------
class TestEnums:
    def test_ar_invoice_type(self):
        assert ARInvoiceType.STANDARD.is_credit() is False
        assert ARInvoiceType.STANDARD.is_debit() is False
        assert ARInvoiceType.CREDIT_NOTE.is_credit() is True
        assert ARInvoiceType.DEBIT_NOTE.is_debit() is True

    def test_ar_invoice_status(self):
        # can_edit
        assert ARInvoiceStatus.DRAFT.can_edit() is True
        assert ARInvoiceStatus.ISSUED.can_edit() is True
        assert ARInvoiceStatus.SENT.can_edit() is False
        assert ARInvoiceStatus.PARTIALLY_PAID.can_edit() is False
        # can_collect
        assert ARInvoiceStatus.DRAFT.can_collect() is False
        assert ARInvoiceStatus.ISSUED.can_collect() is True
        assert ARInvoiceStatus.SENT.can_collect() is True
        assert ARInvoiceStatus.PARTIALLY_PAID.can_collect() is True
        assert ARInvoiceStatus.OVERDUE.can_collect() is True
        assert ARInvoiceStatus.FULLY_PAID.can_collect() is False
        # is_paid
        assert ARInvoiceStatus.FULLY_PAID.is_paid() is True
        assert ARInvoiceStatus.DRAFT.is_paid() is False

    def test_payment_method(self):
        assert PaymentMethod.CASH.requires_bank_account() is False
        assert PaymentMethod.BANK_TRANSFER.requires_bank_account() is True
        assert PaymentMethod.CREDIT_CARD.requires_bank_account() is True
        assert PaymentMethod.DEBIT_CARD.requires_bank_account() is True
        assert PaymentMethod.CHEQUE.requires_bank_account() is False

    def test_payment_status(self):
        assert PaymentStatus.PENDING.is_success() is False
        assert PaymentStatus.CONFIRMED.is_success() is True
        assert PaymentStatus.FAILED.is_success() is False
        assert PaymentStatus.REFUNDED.is_success() is False


# -------------------- Tests for ARInvoiceLineRequest --------------------
class TestARInvoiceLineRequest:
    def test_construction_valid(self, sample_line_request):
        assert sample_line_request.item_id is not None
        assert sample_line_request.quantity == Decimal("2")
        assert sample_line_request.unit_price == Decimal("100000")
        assert sample_line_request.discount_percentage == Decimal("10")
        assert sample_line_request.tax_rate == Decimal("11")

    def test_validation_quantity_positive(self):
        with pytest.raises(ValueError, match="Quantity must be positive"):
            ARInvoiceLineRequest(
                item_id=uuid4(),
                item_code="C",
                item_name="N",
                quantity=Decimal("0"),
                unit_price=Decimal("100"),
            )

    def test_validation_unit_price_non_negative(self):
        with pytest.raises(ValueError, match="Unit price cannot be negative"):
            ARInvoiceLineRequest(
                item_id=uuid4(),
                item_code="C",
                item_name="N",
                quantity=Decimal("1"),
                unit_price=Decimal("-100"),
            )

    def test_validation_discount_range(self):
        with pytest.raises(ValueError, match="Discount percentage must be between 0 and 100"):
            ARInvoiceLineRequest(
                item_id=uuid4(),
                item_code="C",
                item_name="N",
                quantity=Decimal("1"),
                unit_price=Decimal("100"),
                discount_percentage=Decimal("101"),
            )
        with pytest.raises(ValueError, match="Discount percentage must be between 0 and 100"):
            ARInvoiceLineRequest(
                item_id=uuid4(),
                item_code="C",
                item_name="N",
                quantity=Decimal("1"),
                unit_price=Decimal("100"),
                discount_percentage=Decimal("-1"),
            )

    def test_validation_tax_range(self):
        with pytest.raises(ValueError, match="Tax rate must be between 0 and 100"):
            ARInvoiceLineRequest(
                item_id=uuid4(),
                item_code="C",
                item_name="N",
                quantity=Decimal("1"),
                unit_price=Decimal("100"),
                tax_rate=Decimal("101"),
            )
        with pytest.raises(ValueError, match="Tax rate must be between 0 and 100"):
            ARInvoiceLineRequest(
                item_id=uuid4(),
                item_code="C",
                item_name="N",
                quantity=Decimal("1"),
                unit_price=Decimal("100"),
                tax_rate=Decimal("-5"),
            )

    def test_properties(self, sample_line_request):
        # quantity=2, unit_price=100000 => subtotal=200000
        assert sample_line_request.subtotal == Decimal("200000.00")
        # discount=10% => 20000
        assert sample_line_request.discount_amount == Decimal("20000.00")
        # net = 200000 - 20000 = 180000
        assert sample_line_request.net_amount == Decimal("180000.00")
        # tax=11% of 180000 = 19800
        assert sample_line_request.tax_amount == Decimal("19800.00")
        # total = 180000 + 19800 = 199800
        assert sample_line_request.total_amount == Decimal("199800.00")

    def test_to_dict(self, sample_line_request):
        d = sample_line_request.to_dict()
        assert d["item_id"] == str(sample_line_request.item_id)
        assert d["item_code"] == "ITEM001"
        assert d["quantity"] == "2"
        assert d["unit_price"] == "100000"
        assert d["discount_percentage"] == "10"
        assert d["tax_rate"] == "11"
        assert d["subtotal"] == "200000.00"
        assert d["discount_amount"] == "20000.00"
        assert d["net_amount"] == "180000.00"
        assert d["tax_amount"] == "19800.00"
        assert d["total_amount"] == "199800.00"

    def test_from_dict(self, sample_line_request):
        d = sample_line_request.to_dict()
        restored = ARInvoiceLineRequest.from_dict(d)
        assert restored.item_id == sample_line_request.item_id
        assert restored.item_code == sample_line_request.item_code
        assert restored.quantity == sample_line_request.quantity
        assert restored.unit_price == sample_line_request.unit_price
        assert restored.discount_percentage == sample_line_request.discount_percentage
        assert restored.tax_rate == sample_line_request.tax_rate
        assert restored.unit_of_measure == sample_line_request.unit_of_measure
        assert restored.description == sample_line_request.description


# -------------------- Tests for CreateARInvoiceRequest --------------------
class TestCreateARInvoiceRequest:
    def test_construction_valid(self, sample_create_request):
        assert sample_create_request.invoice_number == "INV-001"
        assert len(sample_create_request.lines) == 1
        assert sample_create_request.issue_date.tzinfo == UTC
        assert sample_create_request.due_date.tzinfo == UTC

    def test_validation_invoice_number_short(self):
        with pytest.raises(ValueError, match="at least 3 characters"):
            CreateARInvoiceRequest(
                invoice_number="AB",
                customer_id=uuid4(),
                customer_name="Cust",
                issue_date=datetime.now(UTC),
                due_date=datetime.now(UTC) + timedelta(days=1),
                lines=[MagicMock()],
            )

    def test_validation_customer_name_required(self):
        with pytest.raises(ValueError, match="Customer name is required"):
            CreateARInvoiceRequest(
                invoice_number="INV-001",
                customer_id=uuid4(),
                customer_name="",
                issue_date=datetime.now(UTC),
                due_date=datetime.now(UTC) + timedelta(days=1),
                lines=[MagicMock()],
            )

    def test_validation_lines_not_empty(self):
        with pytest.raises(ValueError, match="must have at least one line"):
            CreateARInvoiceRequest(
                invoice_number="INV-001",
                customer_id=uuid4(),
                customer_name="Cust",
                issue_date=datetime.now(UTC),
                due_date=datetime.now(UTC) + timedelta(days=1),
                lines=[],
            )

    def test_validation_due_date_after_issue_date(self):
        issue = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        due = issue - timedelta(days=1)
        with pytest.raises(ValueError, match="must be after"):
            CreateARInvoiceRequest(
                invoice_number="INV-001",
                customer_id=uuid4(),
                customer_name="Cust",
                issue_date=issue,
                due_date=due,
                lines=[MagicMock()],
            )

    def test_validation_negative_costs(self):
        with pytest.raises(ValueError, match="Shipping cost cannot be negative"):
            CreateARInvoiceRequest(
                invoice_number="INV-001",
                customer_id=uuid4(),
                customer_name="Cust",
                issue_date=datetime.now(UTC),
                due_date=datetime.now(UTC) + timedelta(days=1),
                lines=[MagicMock()],
                shipping_cost=Decimal("-1"),
            )
        with pytest.raises(ValueError, match="Other costs cannot be negative"):
            CreateARInvoiceRequest(
                invoice_number="INV-001",
                customer_id=uuid4(),
                customer_name="Cust",
                issue_date=datetime.now(UTC),
                due_date=datetime.now(UTC) + timedelta(days=1),
                lines=[MagicMock()],
                other_costs=Decimal("-1"),
            )
        with pytest.raises(ValueError, match="Discount amount cannot be negative"):
            CreateARInvoiceRequest(
                invoice_number="INV-001",
                customer_id=uuid4(),
                customer_name="Cust",
                issue_date=datetime.now(UTC),
                due_date=datetime.now(UTC) + timedelta(days=1),
                lines=[MagicMock()],
                discount_amount=Decimal("-1"),
            )

    def test_calculation_methods(self, sample_create_request):
        # One line: 2 * 100000 = 200000 subtotal
        assert sample_create_request.calculate_subtotal() == Decimal("200000.00")
        # discount: 10% of 200000 = 20000 + header discount 5000 = 25000
        assert sample_create_request.calculate_discount_total() == Decimal("25000.00")
        # tax: 11% of (200000-20000)=180000 => 19800
        assert sample_create_request.calculate_tax_total() == Decimal("19800.00")
        # items total: line total = 199800
        assert sample_create_request.calculate_items_total() == Decimal("199800.00")
        # total = items_total + shipping 50000 + other 10000 - header discount 5000 = 199800+50000+10000-5000 = 254800
        assert sample_create_request.calculate_total_amount() == Decimal("254800.00")
        # is_balanced_with_lines always returns True (no pre-calc amount)
        assert sample_create_request.is_balanced_with_lines() is True
        # with tolerance doesn't matter
        assert sample_create_request.is_balanced_with_lines(Decimal("0.01")) is True

    def test_to_dict(self, sample_create_request):
        d = sample_create_request.to_dict()
        assert d["invoice_number"] == "INV-001"
        assert d["customer_name"] == "Test Customer"
        assert "issue_date" in d
        assert "due_date" in d
        assert len(d["lines"]) == 1
        assert d["subtotal"] == "200000.00"
        assert d["discount_total"] == "25000.00"
        assert d["tax_total"] == "19800.00"
        assert d["items_total"] == "199800.00"
        assert d["total_amount"] == "254800.00"

    def test_from_dict(self, sample_create_request):
        d = sample_create_request.to_dict()
        # Need to reconstruct properly: lines are dicts
        restored = CreateARInvoiceRequest.from_dict(d)
        assert restored.invoice_number == sample_create_request.invoice_number
        assert restored.customer_id == sample_create_request.customer_id
        assert restored.customer_name == sample_create_request.customer_name
        assert restored.issue_date == sample_create_request.issue_date
        assert restored.due_date == sample_create_request.due_date
        assert len(restored.lines) == 1
        line = restored.lines[0]
        assert line.item_id == sample_create_request.lines[0].item_id
        assert line.quantity == sample_create_request.lines[0].quantity
        assert line.unit_price == sample_create_request.lines[0].unit_price
        assert restored.shipping_cost == sample_create_request.shipping_cost
        assert restored.other_costs == sample_create_request.other_costs
        assert restored.discount_amount == sample_create_request.discount_amount
        assert restored.notes == sample_create_request.notes
        assert restored.idempotency_key == sample_create_request.idempotency_key


# -------------------- Tests for UpdateARInvoiceRequest --------------------
class TestUpdateARInvoiceRequest:
    def test_construction_valid(self, sample_update_request):
        assert sample_update_request.invoice_id is not None
        assert sample_update_request.due_date.tzinfo == UTC

    def test_validation_at_least_one_field(self):
        with pytest.raises(ValueError, match="At least one field to update must be provided"):
            UpdateARInvoiceRequest(invoice_id=uuid4())

    def test_validation_negative_shipping(self):
        with pytest.raises(ValueError, match="Shipping cost cannot be negative"):
            UpdateARInvoiceRequest(invoice_id=uuid4(), shipping_cost=Decimal("-1"))

    def test_validation_negative_other(self):
        with pytest.raises(ValueError, match="Other costs cannot be negative"):
            UpdateARInvoiceRequest(invoice_id=uuid4(), other_costs=Decimal("-1"))

    def test_validation_negative_discount(self):
        with pytest.raises(ValueError, match="Discount amount cannot be negative"):
            UpdateARInvoiceRequest(invoice_id=uuid4(), discount_amount=Decimal("-1"))

    def test_to_dict(self, sample_update_request):
        d = sample_update_request.to_dict()
        assert d["invoice_id"] == str(sample_update_request.invoice_id)
        assert d["due_date"] == sample_update_request.due_date.isoformat()
        assert d["description"] == "Updated desc"
        assert d["notes"] == "Updated notes"
        assert d["shipping_cost"] == "60000"
        assert d["other_costs"] == "15000"
        assert d["discount_amount"] == "6000"

    def test_to_dict_partial(self):
        req = UpdateARInvoiceRequest(invoice_id=uuid4(), due_date=datetime.now(UTC))
        d = req.to_dict()
        assert "due_date" in d
        assert "description" not in d


# -------------------- Tests for RecordARPaymentRequest --------------------
class TestRecordARPaymentRequest:
    def test_construction_valid(self, sample_payment_request):
        assert sample_payment_request.payment_number == "PAY-001"
        assert sample_payment_request.payment_date.tzinfo == UTC

    def test_validation_payment_number_short(self):
        with pytest.raises(ValueError, match="at least 3 characters"):
            RecordARPaymentRequest(
                payment_number="AB",
                customer_id=uuid4(),
                customer_name="Cust",
                payment_date=datetime.now(UTC),
                amount=Decimal("100"),
                payment_method=PaymentMethod.CASH,
            )

    def test_validation_customer_name_required(self):
        with pytest.raises(ValueError, match="Customer name is required"):
            RecordARPaymentRequest(
                payment_number="PAY-001",
                customer_id=uuid4(),
                customer_name="",
                payment_date=datetime.now(UTC),
                amount=Decimal("100"),
                payment_method=PaymentMethod.CASH,
            )

    def test_validation_positive_amount(self):
        with pytest.raises(ValueError, match="Payment amount must be positive"):
            RecordARPaymentRequest(
                payment_number="PAY-001",
                customer_id=uuid4(),
                customer_name="Cust",
                payment_date=datetime.now(UTC),
                amount=Decimal("-100"),
                payment_method=PaymentMethod.CASH,
            )
        with pytest.raises(ValueError, match="Payment amount must be positive"):
            RecordARPaymentRequest(
                payment_number="PAY-001",
                customer_id=uuid4(),
                customer_name="Cust",
                payment_date=datetime.now(UTC),
                amount=Decimal("0"),
                payment_method=PaymentMethod.CASH,
            )

    def test_to_dict(self, sample_payment_request):
        d = sample_payment_request.to_dict()
        assert d["payment_number"] == "PAY-001"
        assert d["customer_id"] == str(sample_payment_request.customer_id)
        assert d["amount"] == "2000000"
        assert d["payment_method"] == "bank_transfer"
        assert d["invoice_id"] == str(sample_payment_request.invoice_id)
        assert d["reference_number"] == "REF123"


# -------------------- Tests for CreateARCreditNoteRequest --------------------
class TestCreateARCreditNoteRequest:
    def test_construction_valid(self, sample_credit_note_request):
        assert sample_credit_note_request.credit_note_number == "CN-001"
        assert sample_credit_note_request.tax_rate == Decimal("11")

    def test_validation_credit_note_number_short(self):
        with pytest.raises(ValueError, match="at least 3 characters"):
            CreateARCreditNoteRequest(
                credit_note_number="CN",
                invoice_id=uuid4(),
                invoice_number="INV-001",
                customer_id=uuid4(),
                customer_name="Cust",
                amount=Decimal("100"),
                reason=CreditNoteReason.GOODS_RETURN,
            )

    def test_validation_customer_name_required(self):
        with pytest.raises(ValueError, match="Customer name is required"):
            CreateARCreditNoteRequest(
                credit_note_number="CN-001",
                invoice_id=uuid4(),
                invoice_number="INV-001",
                customer_id=uuid4(),
                customer_name="",
                amount=Decimal("100"),
                reason=CreditNoteReason.GOODS_RETURN,
            )

    def test_validation_positive_amount(self):
        with pytest.raises(ValueError, match="Credit note amount must be positive"):
            CreateARCreditNoteRequest(
                credit_note_number="CN-001",
                invoice_id=uuid4(),
                invoice_number="INV-001",
                customer_id=uuid4(),
                customer_name="Cust",
                amount=Decimal("-100"),
                reason=CreditNoteReason.GOODS_RETURN,
            )

    def test_validation_negative_tax(self):
        with pytest.raises(ValueError, match="Tax amount cannot be negative"):
            CreateARCreditNoteRequest(
                credit_note_number="CN-001",
                invoice_id=uuid4(),
                invoice_number="INV-001",
                customer_id=uuid4(),
                customer_name="Cust",
                amount=Decimal("100"),
                reason=CreditNoteReason.GOODS_RETURN,
                tax_amount=Decimal("-10"),
            )

    def test_validation_tax_rate_range(self):
        with pytest.raises(ValueError, match="Tax rate must be between 0 and 100"):
            CreateARCreditNoteRequest(
                credit_note_number="CN-001",
                invoice_id=uuid4(),
                invoice_number="INV-001",
                customer_id=uuid4(),
                customer_name="Cust",
                amount=Decimal("100"),
                reason=CreditNoteReason.GOODS_RETURN,
                tax_rate=Decimal("-5"),
            )
        with pytest.raises(ValueError, match="Tax rate must be between 0 and 100"):
            CreateARCreditNoteRequest(
                credit_note_number="CN-001",
                invoice_id=uuid4(),
                invoice_number="INV-001",
                customer_id=uuid4(),
                customer_name="Cust",
                amount=Decimal("100"),
                reason=CreditNoteReason.GOODS_RETURN,
                tax_rate=Decimal("120"),
            )

    def test_calculate_total_amount(self, sample_credit_note_request):
        # amount 500000, tax 55000 => total 555000
        total = sample_credit_note_request.calculate_total_amount()
        assert total == Decimal("555000.00")

    def test_to_dict(self, sample_credit_note_request):
        d = sample_credit_note_request.to_dict()
        assert d["credit_note_number"] == "CN-001"
        assert d["amount"] == "500000"
        assert d["reason"] == "goods_return"
        assert d["tax_amount"] == "55000"
        assert d["total_amount"] == "555000.00"
        assert d["notes"] == "Credit notes"


# -------------------- Tests for WriteOffARInvoiceRequest --------------------
class TestWriteOffARInvoiceRequest:
    def test_construction_valid(self, sample_write_off_request):
        assert sample_write_off_request.amount == Decimal("1000000")
        assert sample_write_off_request.written_off_by == "admin"

    def test_validation_positive_amount(self):
        with pytest.raises(ValueError, match="Write-off amount must be positive"):
            WriteOffARInvoiceRequest(
                invoice_id=uuid4(),
                invoice_number="INV-001",
                customer_id=uuid4(),
                customer_name="Cust",
                amount=Decimal("-500"),
                reason="Reason",
                written_off_by="admin",
            )

    def test_validation_reason_too_short(self):
        with pytest.raises(ValueError, match="at least 5 characters"):
            WriteOffARInvoiceRequest(
                invoice_id=uuid4(),
                invoice_number="INV-001",
                customer_id=uuid4(),
                customer_name="Cust",
                amount=Decimal("500"),
                reason="No",
                written_off_by="admin",
            )

    def test_validation_written_off_by_required(self):
        with pytest.raises(ValueError, match="written_off_by is required"):
            WriteOffARInvoiceRequest(
                invoice_id=uuid4(),
                invoice_number="INV-001",
                customer_id=uuid4(),
                customer_name="Cust",
                amount=Decimal("500"),
                reason="Valid reason",
                written_off_by="",
            )

    def test_to_dict(self, sample_write_off_request):
        d = sample_write_off_request.to_dict()
        assert d["invoice_id"] == str(sample_write_off_request.invoice_id)
        assert d["amount"] == "1000000"
        assert d["reason"] == "Customer bankrupt"
        assert d["written_off_by"] == "admin"
        assert d["approval_reference"] == "APP-001"


# -------------------- Tests for GetARInvoiceRequest --------------------
class TestGetARInvoiceRequest:
    def test_construction(self):
        req = GetARInvoiceRequest(invoice_id=uuid4(), legal_entity_id=uuid4())
        assert req.invoice_id is not None
        assert req.legal_entity_id is not None

    def test_to_dict(self):
        invoice_id = uuid4()
        legal_id = uuid4()
        req = GetARInvoiceRequest(invoice_id=invoice_id, legal_entity_id=legal_id)
        d = req.to_dict()
        assert d["invoice_id"] == str(invoice_id)
        assert d["legal_entity_id"] == str(legal_id)


# -------------------- Tests for ListARInvoicesRequest --------------------
class TestListARInvoicesRequest:
    def test_construction_valid(self, sample_legal_entity_id):
        req = ListARInvoicesRequest(legal_entity_id=sample_legal_entity_id)
        assert req.limit == 100
        assert req.offset == 0

    def test_validation_limit_range(self):
        with pytest.raises(ValueError, match="limit must be between 1 and 1000"):
            ListARInvoicesRequest(legal_entity_id=uuid4(), limit=0)
        with pytest.raises(ValueError, match="limit must be between 1 and 1000"):
            ListARInvoicesRequest(legal_entity_id=uuid4(), limit=1001)

    def test_validation_offset_non_negative(self):
        with pytest.raises(ValueError, match="offset must be >= 0"):
            ListARInvoicesRequest(legal_entity_id=uuid4(), offset=-1)

    def test_validation_date_tz_conversion(self):
        # naive dates become UTC
        naive = datetime(2025, 1, 1, 0, 0, 0)
        req = ListARInvoicesRequest(legal_entity_id=uuid4(), from_date=naive, to_date=naive)
        assert req.from_date.tzinfo == UTC
        assert req.to_date.tzinfo == UTC

    def test_to_dict(self, sample_legal_entity_id):
        req = ListARInvoicesRequest(
            legal_entity_id=sample_legal_entity_id,
            customer_id=uuid4(),
            from_date=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
            to_date=datetime(2025, 1, 31, 0, 0, 0, tzinfo=UTC),
            status=ARInvoiceStatus.ISSUED,
            is_overdue=True,
            limit=50,
            offset=10,
        )
        d = req.to_dict()
        assert d["legal_entity_id"] == str(sample_legal_entity_id)
        assert d["customer_id"] is not None
        assert d["from_date"] == "2025-01-01T00:00:00+00:00"
        assert d["to_date"] == "2025-01-31T00:00:00+00:00"
        assert d["status"] == "issued"
        assert d["is_overdue"] is True
        assert d["limit"] == 50
        assert d["offset"] == 10


# -------------------- Tests for GetARAgingRequest --------------------
class TestGetARAgingRequest:
    def test_construction_default(self, sample_legal_entity_id):
        req = GetARAgingRequest(legal_entity_id=sample_legal_entity_id)
        assert req.as_of_date is not None
        assert req.as_of_date.tzinfo == UTC

    def test_validation_tz_conversion(self):
        naive = datetime(2025, 1, 1, 0, 0, 0)
        req = GetARAgingRequest(legal_entity_id=uuid4(), as_of_date=naive)
        assert req.as_of_date.tzinfo == UTC

    def test_to_dict(self, sample_legal_entity_id):
        as_of = datetime(2025, 1, 15, 0, 0, 0, tzinfo=UTC)
        req = GetARAgingRequest(
            legal_entity_id=sample_legal_entity_id,
            as_of_date=as_of,
            customer_id=uuid4(),
        )
        d = req.to_dict()
        assert d["legal_entity_id"] == str(sample_legal_entity_id)
        assert d["as_of_date"] == "2025-01-15T00:00:00+00:00"
        assert d["customer_id"] is not None


# -------------------- Tests for ARInvoiceResponseDTO --------------------
class TestARInvoiceResponseDTO:
    def test_construction_valid(self, sample_response_dto):
        assert sample_response_dto.id is not None
        assert sample_response_dto.created_at.tzinfo == UTC

    def test_remaining_amount_computed_if_zero(self):
        # If remaining_amount is 0 but amount > paid, compute
        dto = ARInvoiceResponseDTO(
            id=uuid4(),
            invoice_number="INV",
            customer_id=uuid4(),
            customer_name="Cust",
            invoice_date=datetime.now(UTC),
            due_date=datetime.now(UTC),
            amount=Decimal("1000"),
            paid_amount=Decimal("300"),
            remaining_amount=Decimal("0"),  # will be recomputed to 700
            status="issued",
        )
        assert dto.remaining_amount == Decimal("700.00")

    def test_is_overdue(self, sample_response_dto):
        # due_date is 2025-01-31, current date is after -> overdue
        future = datetime(2025, 2, 1, 0, 0, 0, tzinfo=UTC)
        assert sample_response_dto.is_overdue(future) is True
        # before due date
        past = datetime(2025, 1, 15, 0, 0, 0, tzinfo=UTC)
        assert sample_response_dto.is_overdue(past) is False
        # if remaining amount is 0, not overdue
        dto_zero = ARInvoiceResponseDTO(
            id=uuid4(),
            invoice_number="INV",
            customer_id=uuid4(),
            customer_name="Cust",
            invoice_date=datetime.now(UTC),
            due_date=datetime(2025, 1, 31, 0, 0, 0, tzinfo=UTC),
            amount=Decimal("1000"),
            paid_amount=Decimal("1000"),
            remaining_amount=Decimal("0"),
            status="fully_paid",
        )
        assert dto_zero.is_overdue(future) is False

    def test_get_paid_percentage(self, sample_response_dto):
        # paid=500000, amount=2500000 => 20%
        assert sample_response_dto.get_paid_percentage() == Decimal("20.00")
        # fully paid
        dto_full = ARInvoiceResponseDTO(
            id=uuid4(),
            invoice_number="INV",
            customer_id=uuid4(),
            customer_name="Cust",
            invoice_date=datetime.now(UTC),
            due_date=datetime.now(UTC),
            amount=Decimal("1000"),
            paid_amount=Decimal("1000"),
            remaining_amount=Decimal("0"),
            status="fully_paid",
        )
        assert dto_full.get_paid_percentage() == Decimal("100.00")
        # zero amount (avoid division by zero)
        dto_zero = ARInvoiceResponseDTO(
            id=uuid4(),
            invoice_number="INV",
            customer_id=uuid4(),
            customer_name="Cust",
            invoice_date=datetime.now(UTC),
            due_date=datetime.now(UTC),
            amount=Decimal("0"),
            paid_amount=Decimal("0"),
            remaining_amount=Decimal("0"),
            status="draft",
        )
        assert dto_zero.get_paid_percentage() == Decimal("0")

    def test_to_dict(self, sample_response_dto):
        d = sample_response_dto.to_dict()
        assert d["id"] == str(sample_response_dto.id)
        assert d["invoice_number"] == "INV-001"
        assert d["amount"] == "2500000"
        assert d["paid_amount"] == "500000"
        assert d["remaining_amount"] == "2000000"
        assert d["status"] == "issued"
        assert d["tax_code"] == "PPN"


# -------------------- Tests for ARPaymentResponseDTO --------------------
class TestARPaymentResponseDTO:
    def test_construction_valid(self):
        dto = ARPaymentResponseDTO(
            id=uuid4(),
            invoice_id=uuid4(),
            payment_number="PAY-001",
            payment_date=datetime.now(UTC),
            amount=Decimal("1000"),
            payment_method="bank_transfer",
        )
        assert dto.created_at.tzinfo == UTC

    def test_to_dict(self):
        payment_id = uuid4()
        invoice_id = uuid4()
        bank_id = uuid4()
        dto = ARPaymentResponseDTO(
            id=payment_id,
            invoice_id=invoice_id,
            payment_number="PAY-001",
            payment_date=datetime(2025, 1, 15, 0, 0, 0, tzinfo=UTC),
            amount=Decimal("1500"),
            payment_method="cash",
            status="confirmed",
            created_at=datetime(2025, 1, 15, 0, 0, 0, tzinfo=UTC),
            reference_number="REF123",
            bank_account_id=bank_id,
        )
        d = dto.to_dict()
        assert d["id"] == str(payment_id)
        assert d["invoice_id"] == str(invoice_id)
        assert d["amount"] == "1500"
        assert d["payment_method"] == "cash"
        assert d["status"] == "confirmed"
        assert d["bank_account_id"] == str(bank_id)


# -------------------- Tests for ARInvoiceRequestFactory --------------------
class TestARInvoiceRequestFactory:
    def test_create_invoice_line(self):
        item_id = uuid4()
        line = ARInvoiceRequestFactory.create_invoice_line(
            item_id=item_id,
            item_code="ITEM002",
            item_name="Product X",
            quantity=Decimal("3"),
            unit_price=Decimal("50000"),
            description="Test",
            discount_percentage=Decimal("5"),
            tax_rate=Decimal("11"),
        )
        assert line.item_id == item_id
        assert line.item_code == "ITEM002"
        assert line.quantity == Decimal("3")
        assert line.unit_price == Decimal("50000")
        assert line.discount_percentage == Decimal("5")
        assert line.tax_rate == Decimal("11")
        # check calculation
        assert line.subtotal == Decimal("150000.00")
        assert line.discount_amount == Decimal("7500.00")
        assert line.net_amount == Decimal("142500.00")
        assert line.tax_amount == Decimal("15675.00")  # 11% of 142500
        assert line.total_amount == Decimal("158175.00")

    def test_create_simple_invoice(self, sample_customer_id):
        item_id = uuid4()
        issue = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        due = issue + timedelta(days=30)
        req = ARInvoiceRequestFactory.create_simple_invoice(
            invoice_number="INV-002",
            customer_id=sample_customer_id,
            customer_name="Simple Customer",
            issue_date=issue,
            due_date=due,
            item_id=item_id,
            item_code="ITEM003",
            item_name="Simple Item",
            quantity=Decimal("1"),
            unit_price=Decimal("75000"),
            description="Simple",
        )
        assert req.invoice_number == "INV-002"
        assert len(req.lines) == 1
        line = req.lines[0]
        assert line.item_id == item_id
        assert line.quantity == Decimal("1")
        assert line.unit_price == Decimal("75000")
        assert req.calculate_total_amount() == Decimal("83250.00")  # 75000 + 11% tax = 83250

    def test_create_payment(self, sample_customer_id, sample_invoice_id):
        payment_date = datetime(2025, 1, 20, 0, 0, 0, tzinfo=UTC)
        req = ARInvoiceRequestFactory.create_payment(
            payment_number="PAY-002",
            customer_id=sample_customer_id,
            customer_name="Payment Customer",
            payment_date=payment_date,
            amount=Decimal("500000"),
            invoice_id=sample_invoice_id,
            payment_method=PaymentMethod.QRIS,
        )
        assert req.payment_number == "PAY-002"
        assert req.customer_id == sample_customer_id
        assert req.invoice_id == sample_invoice_id
        assert req.payment_method == PaymentMethod.QRIS
        assert req.amount == Decimal("500000")