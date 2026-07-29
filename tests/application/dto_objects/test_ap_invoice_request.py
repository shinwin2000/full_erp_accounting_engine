# test_ap_invoice_request.py
# Comprehensive tests for application/dto_objects/ap_invoice_request.py
# Covers all classes, methods, edge cases, and exceptions.

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from application.dto_objects.ap_invoice_request import (
    APCreditNoteReason,
    APInvoiceLineRequest,
    ApInvoiceRequest,
    APInvoiceRequestFactory,
    APInvoiceResponseDTO,
    APInvoiceStatus,
    APInvoiceStatusDTO,
    APInvoiceType,
    APPaymentMethod,
    APPaymentResponseDTO,
    APPaymentRunRequestDTO,
    ApproveAPInvoiceRequest,
    CreateAPCreditNoteRequest,
    CreateAPInvoiceRequest,
    GetAPAgingRequest,
    GetAPInvoiceRequest,
    ListAPInvoicesRequest,
    RecordAPPaymentRequest,
    ThreeWayMatchRequestDTO,
    UpdateAPInvoiceRequest,
    VerifyAPInvoiceRequest,
    WithholdingArticle,
)


# -------------------- Fixtures --------------------
@pytest.fixture
def sample_item_id():
    return uuid4()


@pytest.fixture
def sample_vendor_id():
    return uuid4()


@pytest.fixture
def sample_invoice_id():
    return uuid4()


@pytest.fixture
def sample_legal_entity_id():
    return uuid4()


@pytest.fixture
def sample_po_id():
    return uuid4()


@pytest.fixture
def sample_grn_id():
    return uuid4()


@pytest.fixture
def sample_line_request(sample_item_id):
    return APInvoiceLineRequest(
        item_id=sample_item_id,
        item_code="ITEM001",
        item_name="Test Item",
        quantity=Decimal("2"),
        unit_price=Decimal("100000"),
        po_item_id=None,
        discount_percentage=Decimal("10"),
        tax_rate=Decimal("11"),
        unit_of_measure="PCS",
        description="Test line",
    )


@pytest.fixture
def sample_create_request(sample_vendor_id, sample_line_request):
    invoice_date = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
    due_date = invoice_date + timedelta(days=30)
    return CreateAPInvoiceRequest(
        invoice_number="AP-INV-001",
        vendor_id=sample_vendor_id,
        vendor_name="Test Vendor",
        invoice_date=invoice_date,
        due_date=due_date,
        amount=Decimal("254800.00"),  # matches calculation
        lines=[sample_line_request],
        invoice_type=APInvoiceType.STANDARD,
        currency="IDR",
        description="Test AP invoice",
        po_id=sample_po_id,
        po_number="PO-001",
        grn_id=sample_grn_id,
        grn_number="GRN-001",
        tax_amount=Decimal("19800.00"),
        discount_amount=Decimal("5000"),
        shipping_cost=Decimal("50000"),
        other_costs=Decimal("10000"),
        withholding_article=WithholdingArticle.PPH_23,
        withholding_rate=Decimal("2"),
        withholding_amount=Decimal("5096.00"),  # 2% of total before withholding
        notes="Test notes",
        idempotency_key="idem123",
    )


@pytest.fixture
def sample_update_request(sample_invoice_id):
    return UpdateAPInvoiceRequest(
        invoice_id=sample_invoice_id,
        due_date=datetime(2025, 2, 1, 0, 0, 0, tzinfo=UTC),
        description="Updated description",
        notes="Updated notes",
        discount_amount=Decimal("6000"),
        shipping_cost=Decimal("60000"),
        other_costs=Decimal("15000"),
    )


@pytest.fixture
def sample_payment_request(sample_vendor_id, sample_invoice_id):
    return RecordAPPaymentRequest(
        payment_number="AP-PAY-001",
        vendor_id=sample_vendor_id,
        vendor_name="Test Vendor",
        payment_date=datetime(2025, 1, 20, 0, 0, 0, tzinfo=UTC),
        amount=Decimal("2000000"),
        payment_method=APPaymentMethod.BANK_TRANSFER,
        currency="IDR",
        invoice_id=sample_invoice_id,
        invoice_number="AP-INV-001",
        bank_account_from="ACC-FROM-001",
        bank_account_to="ACC-TO-001",
        reference_number="REF123",
        notes="Payment notes",
        idempotency_key="paykey",
    )


@pytest.fixture
def sample_credit_note_request(sample_invoice_id, sample_vendor_id):
    return CreateAPCreditNoteRequest(
        credit_note_number="CN-AP-001",
        invoice_id=sample_invoice_id,
        invoice_number="AP-INV-001",
        vendor_id=sample_vendor_id,
        vendor_name="Test Vendor",
        amount=Decimal("500000"),
        reason=APCreditNoteReason.GOODS_RETURN,
        currency="IDR",
        description="Credit note for return",
        tax_amount=Decimal("55000"),
        tax_rate=Decimal("11"),
        notes="Credit notes",
        idempotency_key="cnkey",
    )


@pytest.fixture
def sample_verify_request(sample_invoice_id, sample_po_id, sample_grn_id):
    return VerifyAPInvoiceRequest(
        invoice_id=sample_invoice_id,
        po_id=sample_po_id,
        grn_id=sample_grn_id,
        verified_by="verifier",
    )


@pytest.fixture
def sample_approve_request(sample_invoice_id):
    return ApproveAPInvoiceRequest(
        invoice_id=sample_invoice_id,
        approved_by="approver",
        approval_level=2,
        notes="Approved at level 2",
    )


@pytest.fixture
def sample_response_dto(sample_invoice_id, sample_vendor_id):
    return APInvoiceResponseDTO(
        id=sample_invoice_id,
        invoice_number="AP-INV-001",
        vendor_id=sample_vendor_id,
        vendor_name="Test Vendor",
        invoice_date=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
        due_date=datetime(2025, 1, 31, 0, 0, 0, tzinfo=UTC),
        amount=Decimal("2500000"),
        paid_amount=Decimal("500000"),
        remaining_amount=Decimal("2000000"),
        currency="IDR",
        status="approved",
        tax_amount=Decimal("250000"),
        created_at=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
        version=1,
        tax_code="PPN",
        description="Test AP invoice",
        po_reference="PO-001",
        grn_reference="GRN-001",
    )


# -------------------- Tests for Enums --------------------
class TestEnums:
    def test_ap_invoice_type(self):
        assert APInvoiceType.STANDARD.is_credit() is False
        assert APInvoiceType.STANDARD.is_reduction() is False
        assert APInvoiceType.CREDIT_NOTE.is_credit() is True
        assert APInvoiceType.CREDIT_NOTE.is_reduction() is True
        assert APInvoiceType.DEBIT_NOTE.is_credit() is True
        assert APInvoiceType.DEBIT_NOTE.is_reduction() is False
        assert APInvoiceType.PREPAYMENT.is_credit() is False
        assert APInvoiceType.PREPAYMENT.is_reduction() is False

    def test_ap_invoice_status(self):
        # can_edit
        assert APInvoiceStatus.DRAFT.can_edit() is True
        assert APInvoiceStatus.RECEIVED.can_edit() is True
        assert APInvoiceStatus.VERIFIED.can_edit() is False
        assert APInvoiceStatus.APPROVED.can_edit() is False
        assert APInvoiceStatus.PARTIALLY_PAID.can_edit() is False
        # can_pay
        assert APInvoiceStatus.APPROVED.can_pay() is True
        assert APInvoiceStatus.PARTIALLY_PAID.can_pay() is True
        assert APInvoiceStatus.DRAFT.can_pay() is False
        # is_paid
        assert APInvoiceStatus.FULLY_PAID.is_paid() is True
        assert APInvoiceStatus.DRAFT.is_paid() is False

    def test_ap_payment_method(self):
        assert APPaymentMethod.BANK_TRANSFER.requires_bank_account() is True
        assert APPaymentMethod.CASH.requires_bank_account() is False
        assert APPaymentMethod.CHEQUE.requires_bank_account() is False
        assert APPaymentMethod.WIRE_TRANSFER.requires_bank_account() is True
        assert APPaymentMethod.ONLINE_PAYMENT.requires_bank_account() is True
        assert APPaymentMethod.GIRO.requires_bank_account() is False

    def test_withholding_article(self):
        assert WithholdingArticle.PPH_21.get_rate() == Decimal("5")
        assert WithholdingArticle.PPH_22.get_rate() == Decimal("1.5")
        assert WithholdingArticle.PPH_23.get_rate() == Decimal("2")
        assert WithholdingArticle.PPH_26.get_rate() == Decimal("20")
        assert WithholdingArticle.PPH_4_2.get_rate() == Decimal("10")
        assert WithholdingArticle.NONE.get_rate() == Decimal("0")

    def test_ap_invoice_status_dto_members(self):
        assert hasattr(APInvoiceStatusDTO, 'DRAFT')
        assert hasattr(APInvoiceStatusDTO, 'RECEIVED')
        assert isinstance(APInvoiceStatusDTO.DRAFT, APInvoiceStatusDTO)


# -------------------- Tests for APInvoiceLineRequest --------------------
class TestAPInvoiceLineRequest:
    def test_construction_valid(self, sample_line_request):
        assert sample_line_request.item_id is not None
        assert sample_line_request.quantity == Decimal("2")
        assert sample_line_request.unit_price == Decimal("100000")
        assert sample_line_request.discount_percentage == Decimal("10")
        assert sample_line_request.tax_rate == Decimal("11")

    def test_validation_quantity_positive(self):
        with pytest.raises(ValueError, match="Quantity must be positive"):
            APInvoiceLineRequest(
                item_id=uuid4(),
                item_code="C",
                item_name="N",
                quantity=Decimal("0"),
                unit_price=Decimal("100"),
            )

    def test_validation_unit_price_non_negative(self):
        with pytest.raises(ValueError, match="Unit price cannot be negative"):
            APInvoiceLineRequest(
                item_id=uuid4(),
                item_code="C",
                item_name="N",
                quantity=Decimal("1"),
                unit_price=Decimal("-100"),
            )

    def test_validation_discount_range(self):
        with pytest.raises(ValueError, match="Discount percentage must be between 0 and 100"):
            APInvoiceLineRequest(
                item_id=uuid4(),
                item_code="C",
                item_name="N",
                quantity=Decimal("1"),
                unit_price=Decimal("100"),
                discount_percentage=Decimal("101"),
            )
        with pytest.raises(ValueError, match="Discount percentage must be between 0 and 100"):
            APInvoiceLineRequest(
                item_id=uuid4(),
                item_code="C",
                item_name="N",
                quantity=Decimal("1"),
                unit_price=Decimal("100"),
                discount_percentage=Decimal("-1"),
            )

    def test_validation_tax_range(self):
        with pytest.raises(ValueError, match="Tax rate must be between 0 and 100"):
            APInvoiceLineRequest(
                item_id=uuid4(),
                item_code="C",
                item_name="N",
                quantity=Decimal("1"),
                unit_price=Decimal("100"),
                tax_rate=Decimal("101"),
            )
        with pytest.raises(ValueError, match="Tax rate must be between 0 and 100"):
            APInvoiceLineRequest(
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
        # add po_item_id if needed
        restored = APInvoiceLineRequest.from_dict(d)
        assert restored.item_id == sample_line_request.item_id
        assert restored.item_code == sample_line_request.item_code
        assert restored.quantity == sample_line_request.quantity
        assert restored.unit_price == sample_line_request.unit_price
        assert restored.discount_percentage == sample_line_request.discount_percentage
        assert restored.tax_rate == sample_line_request.tax_rate
        assert restored.unit_of_measure == sample_line_request.unit_of_measure
        assert restored.description == sample_line_request.description


# -------------------- Tests for CreateAPInvoiceRequest --------------------
class TestCreateAPInvoiceRequest:
    def test_construction_valid(self, sample_create_request):
        assert sample_create_request.invoice_number == "AP-INV-001"
        assert len(sample_create_request.lines) == 1
        assert sample_create_request.invoice_date.tzinfo == UTC
        assert sample_create_request.due_date.tzinfo == UTC

    def test_validation_invoice_number_short(self):
        with pytest.raises(ValueError, match="at least 3 characters"):
            CreateAPInvoiceRequest(
                invoice_number="AB",
                vendor_id=uuid4(),
                vendor_name="Vendor",
                invoice_date=datetime.now(UTC),
                due_date=datetime.now(UTC) + timedelta(days=1),
                amount=Decimal("100"),
                lines=[MagicMock()],
            )

    def test_validation_vendor_name_required(self):
        with pytest.raises(ValueError, match="Vendor name is required"):
            CreateAPInvoiceRequest(
                invoice_number="AP-INV-001",
                vendor_id=uuid4(),
                vendor_name="",
                invoice_date=datetime.now(UTC),
                due_date=datetime.now(UTC) + timedelta(days=1),
                amount=Decimal("100"),
                lines=[MagicMock()],
            )

    def test_validation_amount_positive(self):
        with pytest.raises(ValueError, match="Invoice amount must be positive"):
            CreateAPInvoiceRequest(
                invoice_number="AP-INV-001",
                vendor_id=uuid4(),
                vendor_name="Vendor",
                invoice_date=datetime.now(UTC),
                due_date=datetime.now(UTC) + timedelta(days=1),
                amount=Decimal("0"),
                lines=[MagicMock()],
            )

    def test_validation_lines_not_empty(self):
        with pytest.raises(ValueError, match="must have at least one line"):
            CreateAPInvoiceRequest(
                invoice_number="AP-INV-001",
                vendor_id=uuid4(),
                vendor_name="Vendor",
                invoice_date=datetime.now(UTC),
                due_date=datetime.now(UTC) + timedelta(days=1),
                amount=Decimal("100"),
                lines=[],
            )

    def test_validation_due_date_after_invoice_date(self):
        invoice = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        due = invoice - timedelta(days=1)
        with pytest.raises(ValueError, match="must be after"):
            CreateAPInvoiceRequest(
                invoice_number="AP-INV-001",
                vendor_id=uuid4(),
                vendor_name="Vendor",
                invoice_date=invoice,
                due_date=due,
                amount=Decimal("100"),
                lines=[MagicMock()],
            )

    def test_validation_negative_costs(self):
        with pytest.raises(ValueError, match="Tax amount cannot be negative"):
            CreateAPInvoiceRequest(
                invoice_number="AP-INV-001",
                vendor_id=uuid4(),
                vendor_name="Vendor",
                invoice_date=datetime.now(UTC),
                due_date=datetime.now(UTC) + timedelta(days=1),
                amount=Decimal("100"),
                lines=[MagicMock()],
                tax_amount=Decimal("-1"),
            )
        with pytest.raises(ValueError, match="Discount amount cannot be negative"):
            CreateAPInvoiceRequest(
                invoice_number="AP-INV-001",
                vendor_id=uuid4(),
                vendor_name="Vendor",
                invoice_date=datetime.now(UTC),
                due_date=datetime.now(UTC) + timedelta(days=1),
                amount=Decimal("100"),
                lines=[MagicMock()],
                discount_amount=Decimal("-1"),
            )
        with pytest.raises(ValueError, match="Shipping cost cannot be negative"):
            CreateAPInvoiceRequest(
                invoice_number="AP-INV-001",
                vendor_id=uuid4(),
                vendor_name="Vendor",
                invoice_date=datetime.now(UTC),
                due_date=datetime.now(UTC) + timedelta(days=1),
                amount=Decimal("100"),
                lines=[MagicMock()],
                shipping_cost=Decimal("-1"),
            )
        with pytest.raises(ValueError, match="Other costs cannot be negative"):
            CreateAPInvoiceRequest(
                invoice_number="AP-INV-001",
                vendor_id=uuid4(),
                vendor_name="Vendor",
                invoice_date=datetime.now(UTC),
                due_date=datetime.now(UTC) + timedelta(days=1),
                amount=Decimal("100"),
                lines=[MagicMock()],
                other_costs=Decimal("-1"),
            )

    def test_validation_withholding_rate_range(self):
        with pytest.raises(ValueError, match="Withholding rate must be between 0 and 100"):
            CreateAPInvoiceRequest(
                invoice_number="AP-INV-001",
                vendor_id=uuid4(),
                vendor_name="Vendor",
                invoice_date=datetime.now(UTC),
                due_date=datetime.now(UTC) + timedelta(days=1),
                amount=Decimal("100"),
                lines=[MagicMock()],
                withholding_rate=Decimal("101"),
            )

    def test_validation_withholding_amount_negative(self):
        with pytest.raises(ValueError, match="Withholding amount cannot be negative"):
            CreateAPInvoiceRequest(
                invoice_number="AP-INV-001",
                vendor_id=uuid4(),
                vendor_name="Vendor",
                invoice_date=datetime.now(UTC),
                due_date=datetime.now(UTC) + timedelta(days=1),
                amount=Decimal("100"),
                lines=[MagicMock()],
                withholding_amount=Decimal("-1"),
            )

    # ---- Calculation method tests (explicit) ----
    def test_calculate_subtotal(self, sample_create_request):
        # Single line: 2 * 100000 = 200000
        assert sample_create_request.calculate_subtotal() == Decimal("200000.00")

        # Add a second line to verify sum
        second_line = APInvoiceLineRequest(
            item_id=uuid4(),
            item_code="ITEM002",
            item_name="Item 2",
            quantity=Decimal("3"),
            unit_price=Decimal("50000"),
        )
        # Create a new request with two lines
        invoice_date = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        due_date = invoice_date + timedelta(days=30)
        multi_request = CreateAPInvoiceRequest(
            invoice_number="AP-INV-002",
            vendor_id=uuid4(),
            vendor_name="Vendor",
            invoice_date=invoice_date,
            due_date=due_date,
            amount=Decimal("0"),  # placeholder
            lines=[sample_create_request.lines[0], second_line],
        )
        # Subtotal = 200000 + (3*50000)=150000 => 350000
        assert multi_request.calculate_subtotal() == Decimal("350000.00")

    def test_calculate_discount_total(self, sample_create_request):
        # Line discount: 10% of 200000 = 20000, header discount 5000 => total 25000
        assert sample_create_request.calculate_discount_total() == Decimal("25000.00")

        # With zero header discount
        zero_disc = CreateAPInvoiceRequest(
            invoice_number="AP-INV-003",
            vendor_id=uuid4(),
            vendor_name="Vendor",
            invoice_date=datetime.now(UTC),
            due_date=datetime.now(UTC) + timedelta(days=30),
            amount=Decimal("0"),
            lines=[sample_create_request.lines[0]],
            discount_amount=Decimal("0"),
        )
        assert zero_disc.calculate_discount_total() == Decimal("20000.00")  # only line discount

    def test_calculate_tax_total(self, sample_create_request):
        # Line tax: 11% of 180000 = 19800, header tax 19800 => total 39600
        assert sample_create_request.calculate_tax_total() == Decimal("39600.00")

        # No header tax
        zero_tax = CreateAPInvoiceRequest(
            invoice_number="AP-INV-004",
            vendor_id=uuid4(),
            vendor_name="Vendor",
            invoice_date=datetime.now(UTC),
            due_date=datetime.now(UTC) + timedelta(days=30),
            amount=Decimal("0"),
            lines=[sample_create_request.lines[0]],
            tax_amount=Decimal("0"),
        )
        assert zero_tax.calculate_tax_total() == Decimal("19800.00")

    def test_calculate_items_total(self, sample_create_request):
        # Line total: 199800.00
        assert sample_create_request.calculate_items_total() == Decimal("199800.00")

        # Two lines
        second_line = APInvoiceLineRequest(
            item_id=uuid4(),
            item_code="ITEM002",
            item_name="Item 2",
            quantity=Decimal("1"),
            unit_price=Decimal("100000"),
            discount_percentage=Decimal("0"),
            tax_rate=Decimal("11"),
        )
        invoice_date = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        due_date = invoice_date + timedelta(days=30)
        multi_request = CreateAPInvoiceRequest(
            invoice_number="AP-INV-005",
            vendor_id=uuid4(),
            vendor_name="Vendor",
            invoice_date=invoice_date,
            due_date=due_date,
            amount=Decimal("0"),
            lines=[sample_create_request.lines[0], second_line],
        )
        # Line1 total: 199800, Line2: 111000 => 310800
        assert multi_request.calculate_items_total() == Decimal("310800.00")

    def test_is_balanced_with_lines(self, sample_create_request):
        # The fixture amount is 254800, but calculated total is 269504, so not balanced
        assert sample_create_request.is_balanced_with_lines() is False
        # With a tolerance larger than difference, should be True
        assert sample_create_request.is_balanced_with_lines(Decimal("15000")) is True

        # Create a balanced request: adjust amount to match calculation
        balanced_request = CreateAPInvoiceRequest(
            invoice_number="AP-INV-006",
            vendor_id=uuid4(),
            vendor_name="Vendor",
            invoice_date=datetime.now(UTC),
            due_date=datetime.now(UTC) + timedelta(days=30),
            amount=Decimal("269504.00"),  # exactly matches calculated total
            lines=[sample_create_request.lines[0]],
            tax_amount=Decimal("19800.00"),
            discount_amount=Decimal("5000"),
            shipping_cost=Decimal("50000"),
            other_costs=Decimal("10000"),
            withholding_article=WithholdingArticle.PPH_23,
            withholding_rate=Decimal("2"),
            withholding_amount=Decimal("5096.00"),
        )
        assert balanced_request.is_balanced_with_lines() is True
        # With tiny tolerance, still True because exactly equal
        assert balanced_request.is_balanced_with_lines(Decimal("0.001")) is True

    # ---- Existing calculation test that calls all methods ----
    def test_calculation_methods(self, sample_create_request):
        # One line: 2 * 100000 = 200000 subtotal
        assert sample_create_request.calculate_subtotal() == Decimal("200000.00")
        # discount: 10% of 200000 = 20000 + header discount 5000 = 25000
        assert sample_create_request.calculate_discount_total() == Decimal("25000.00")
        # tax: 11% of (200000-20000)=180000 => 19800 + header tax 19800 = 39600
        assert sample_create_request.calculate_tax_total() == Decimal("39600.00")
        # items total: line total = 199800
        assert sample_create_request.calculate_items_total() == Decimal("199800.00")
        # total = items_total + shipping 50000 + other 10000 - discount 5000 + tax 19800 - withholding 5096
        # 199800 + 50000 + 10000 - 5000 + 19800 - 5096 = 269504
        expected = Decimal("269504.00")
        assert sample_create_request.calculate_total_amount() == expected
        # is_balanced
        assert sample_create_request.is_balanced_with_lines() is False
        assert sample_create_request.is_balanced_with_lines(Decimal("15000")) is True

    def test_to_dict(self, sample_create_request):
        d = sample_create_request.to_dict()
        assert d["invoice_number"] == "AP-INV-001"
        assert d["vendor_name"] == "Test Vendor"
        assert "invoice_date" in d
        assert "due_date" in d
        assert len(d["lines"]) == 1
        assert d["subtotal"] == "200000.00"
        assert d["items_total"] == "199800.00"
        assert d["total_amount"] == "269504.00"
        assert d["is_balanced"] is False
        assert d["withholding_article"] == "23"

    def test_from_dict(self, sample_create_request):
        d = sample_create_request.to_dict()
        # lines are dicts, need to reconstruct
        restored = CreateAPInvoiceRequest.from_dict(d)
        assert restored.invoice_number == sample_create_request.invoice_number
        assert restored.vendor_id == sample_create_request.vendor_id
        assert restored.vendor_name == sample_create_request.vendor_name
        assert restored.invoice_date == sample_create_request.invoice_date
        assert restored.due_date == sample_create_request.due_date
        assert len(restored.lines) == 1
        line = restored.lines[0]
        assert line.item_id == sample_create_request.lines[0].item_id
        assert line.quantity == sample_create_request.lines[0].quantity
        assert restored.tax_amount == sample_create_request.tax_amount
        assert restored.discount_amount == sample_create_request.discount_amount
        assert restored.shipping_cost == sample_create_request.shipping_cost
        assert restored.other_costs == sample_create_request.other_costs
        assert restored.withholding_article == sample_create_request.withholding_article
        assert restored.withholding_rate == sample_create_request.withholding_rate
        assert restored.withholding_amount == sample_create_request.withholding_amount
        assert restored.idempotency_key == sample_create_request.idempotency_key


# -------------------- Tests for UpdateAPInvoiceRequest --------------------
class TestUpdateAPInvoiceRequest:
    def test_construction_valid(self, sample_update_request):
        assert sample_update_request.invoice_id is not None
        assert sample_update_request.due_date.tzinfo == UTC

    def test_validation_at_least_one_field(self):
        with pytest.raises(ValueError, match="At least one field to update must be provided"):
            UpdateAPInvoiceRequest(invoice_id=uuid4())

    def test_validation_negative_discount(self):
        with pytest.raises(ValueError, match="Discount amount cannot be negative"):
            UpdateAPInvoiceRequest(invoice_id=uuid4(), discount_amount=Decimal("-1"))

    def test_validation_negative_shipping(self):
        with pytest.raises(ValueError, match="Shipping cost cannot be negative"):
            UpdateAPInvoiceRequest(invoice_id=uuid4(), shipping_cost=Decimal("-1"))

    def test_validation_negative_other(self):
        with pytest.raises(ValueError, match="Other costs cannot be negative"):
            UpdateAPInvoiceRequest(invoice_id=uuid4(), other_costs=Decimal("-1"))

    def test_to_dict(self, sample_update_request):
        d = sample_update_request.to_dict()
        assert d["invoice_id"] == str(sample_update_request.invoice_id)
        assert d["due_date"] == sample_update_request.due_date.isoformat()
        assert d["description"] == "Updated description"
        assert d["notes"] == "Updated notes"
        assert d["discount_amount"] == "6000"
        assert d["shipping_cost"] == "60000"
        assert d["other_costs"] == "15000"

    def test_to_dict_partial(self):
        req = UpdateAPInvoiceRequest(invoice_id=uuid4(), due_date=datetime.now(UTC))
        d = req.to_dict()
        assert "due_date" in d
        assert "description" not in d


# -------------------- Tests for VerifyAPInvoiceRequest --------------------
class TestVerifyAPInvoiceRequest:
    def test_construction_valid(self, sample_verify_request):
        assert sample_verify_request.invoice_id is not None
        assert sample_verify_request.verified_by == "verifier"

    def test_validation_verified_by_required(self):
        with pytest.raises(ValueError, match="verified_by is required"):
            VerifyAPInvoiceRequest(invoice_id=uuid4(), po_id=uuid4(), grn_id=uuid4(), verified_by="")

    def test_to_dict(self, sample_verify_request):
        d = sample_verify_request.to_dict()
        assert d["invoice_id"] == str(sample_verify_request.invoice_id)
        assert d["po_id"] == str(sample_verify_request.po_id)
        assert d["grn_id"] == str(sample_verify_request.grn_id)
        assert d["verified_by"] == "verifier"


# -------------------- Tests for ApproveAPInvoiceRequest --------------------
class TestApproveAPInvoiceRequest:
    def test_construction_valid(self, sample_approve_request):
        assert sample_approve_request.invoice_id is not None
        assert sample_approve_request.approval_level == 2
        assert sample_approve_request.approved_by == "approver"

    def test_validation_approved_by_required(self):
        with pytest.raises(ValueError, match="approved_by is required"):
            ApproveAPInvoiceRequest(invoice_id=uuid4(), approved_by="")

    def test_validation_approval_level_min(self):
        with pytest.raises(ValueError, match="approval_level must be at least 1"):
            ApproveAPInvoiceRequest(invoice_id=uuid4(), approved_by="user", approval_level=0)

    def test_to_dict(self, sample_approve_request):
        d = sample_approve_request.to_dict()
        assert d["invoice_id"] == str(sample_approve_request.invoice_id)
        assert d["approved_by"] == "approver"
        assert d["approval_level"] == 2
        assert d["notes"] == "Approved at level 2"


# -------------------- Tests for RecordAPPaymentRequest --------------------
class TestRecordAPPaymentRequest:
    def test_construction_valid(self, sample_payment_request):
        assert sample_payment_request.payment_number == "AP-PAY-001"
        assert sample_payment_request.payment_date.tzinfo == UTC

    def test_validation_payment_number_short(self):
        with pytest.raises(ValueError, match="at least 3 characters"):
            RecordAPPaymentRequest(
                payment_number="AB",
                vendor_id=uuid4(),
                vendor_name="Vendor",
                payment_date=datetime.now(UTC),
                amount=Decimal("100"),
                payment_method=APPaymentMethod.BANK_TRANSFER,
            )

    def test_validation_vendor_name_required(self):
        with pytest.raises(ValueError, match="Vendor name is required"):
            RecordAPPaymentRequest(
                payment_number="PAY-001",
                vendor_id=uuid4(),
                vendor_name="",
                payment_date=datetime.now(UTC),
                amount=Decimal("100"),
                payment_method=APPaymentMethod.BANK_TRANSFER,
            )

    def test_validation_positive_amount(self):
        with pytest.raises(ValueError, match="Payment amount must be positive"):
            RecordAPPaymentRequest(
                payment_number="PAY-001",
                vendor_id=uuid4(),
                vendor_name="Vendor",
                payment_date=datetime.now(UTC),
                amount=Decimal("-100"),
                payment_method=APPaymentMethod.BANK_TRANSFER,
            )

    def test_to_dict(self, sample_payment_request):
        d = sample_payment_request.to_dict()
        assert d["payment_number"] == "AP-PAY-001"
        assert d["vendor_id"] == str(sample_payment_request.vendor_id)
        assert d["amount"] == "2000000"
        assert d["payment_method"] == "bank_transfer"
        assert d["invoice_id"] == str(sample_payment_request.invoice_id)
        assert d["bank_account_from"] == "ACC-FROM-001"
        assert d["bank_account_to"] == "ACC-TO-001"


# -------------------- Tests for CreateAPCreditNoteRequest --------------------
class TestCreateAPCreditNoteRequest:
    def test_construction_valid(self, sample_credit_note_request):
        assert sample_credit_note_request.credit_note_number == "CN-AP-001"
        assert sample_credit_note_request.tax_rate == Decimal("11")

    def test_validation_credit_note_number_short(self):
        with pytest.raises(ValueError, match="at least 3 characters"):
            CreateAPCreditNoteRequest(
                credit_note_number="CN",
                invoice_id=uuid4(),
                invoice_number="INV-001",
                vendor_id=uuid4(),
                vendor_name="Vendor",
                amount=Decimal("100"),
                reason=APCreditNoteReason.GOODS_RETURN,
            )

    def test_validation_vendor_name_required(self):
        with pytest.raises(ValueError, match="Vendor name is required"):
            CreateAPCreditNoteRequest(
                credit_note_number="CN-001",
                invoice_id=uuid4(),
                invoice_number="INV-001",
                vendor_id=uuid4(),
                vendor_name="",
                amount=Decimal("100"),
                reason=APCreditNoteReason.GOODS_RETURN,
            )

    def test_validation_positive_amount(self):
        with pytest.raises(ValueError, match="Credit note amount must be positive"):
            CreateAPCreditNoteRequest(
                credit_note_number="CN-001",
                invoice_id=uuid4(),
                invoice_number="INV-001",
                vendor_id=uuid4(),
                vendor_name="Vendor",
                amount=Decimal("-100"),
                reason=APCreditNoteReason.GOODS_RETURN,
            )

    def test_validation_negative_tax(self):
        with pytest.raises(ValueError, match="Tax amount cannot be negative"):
            CreateAPCreditNoteRequest(
                credit_note_number="CN-001",
                invoice_id=uuid4(),
                invoice_number="INV-001",
                vendor_id=uuid4(),
                vendor_name="Vendor",
                amount=Decimal("100"),
                reason=APCreditNoteReason.GOODS_RETURN,
                tax_amount=Decimal("-10"),
            )

    def test_validation_tax_rate_range(self):
        with pytest.raises(ValueError, match="Tax rate must be between 0 and 100"):
            CreateAPCreditNoteRequest(
                credit_note_number="CN-001",
                invoice_id=uuid4(),
                invoice_number="INV-001",
                vendor_id=uuid4(),
                vendor_name="Vendor",
                amount=Decimal("100"),
                reason=APCreditNoteReason.GOODS_RETURN,
                tax_rate=Decimal("-5"),
            )
        with pytest.raises(ValueError, match="Tax rate must be between 0 and 100"):
            CreateAPCreditNoteRequest(
                credit_note_number="CN-001",
                invoice_id=uuid4(),
                invoice_number="INV-001",
                vendor_id=uuid4(),
                vendor_name="Vendor",
                amount=Decimal("100"),
                reason=APCreditNoteReason.GOODS_RETURN,
                tax_rate=Decimal("120"),
            )

    def test_calculate_total_amount(self, sample_credit_note_request):
        # amount 500000, tax 55000 => total 555000
        total = sample_credit_note_request.calculate_total_amount()
        assert total == Decimal("555000.00")

    def test_to_dict(self, sample_credit_note_request):
        d = sample_credit_note_request.to_dict()
        assert d["credit_note_number"] == "CN-AP-001"
        assert d["amount"] == "500000"
        assert d["reason"] == "goods_return"
        assert d["tax_amount"] == "55000"
        assert d["total_amount"] == "555000.00"
        assert d["notes"] == "Credit notes"


# -------------------- Tests for GetAPInvoiceRequest --------------------
class TestGetAPInvoiceRequest:
    def test_construction(self):
        req = GetAPInvoiceRequest(invoice_id=uuid4(), legal_entity_id=uuid4())
        assert req.invoice_id is not None
        assert req.legal_entity_id is not None

    def test_to_dict(self):
        invoice_id = uuid4()
        legal_id = uuid4()
        req = GetAPInvoiceRequest(invoice_id=invoice_id, legal_entity_id=legal_id)
        d = req.to_dict()
        assert d["invoice_id"] == str(invoice_id)
        assert d["legal_entity_id"] == str(legal_id)


# -------------------- Tests for ListAPInvoicesRequest --------------------
class TestListAPInvoicesRequest:
    def test_construction_valid(self, sample_legal_entity_id):
        req = ListAPInvoicesRequest(legal_entity_id=sample_legal_entity_id)
        assert req.limit == 100
        assert req.offset == 0

    def test_validation_limit_range(self):
        with pytest.raises(ValueError, match="limit must be between 1 and 1000"):
            ListAPInvoicesRequest(legal_entity_id=uuid4(), limit=0)
        with pytest.raises(ValueError, match="limit must be between 1 and 1000"):
            ListAPInvoicesRequest(legal_entity_id=uuid4(), limit=1001)

    def test_validation_offset_non_negative(self):
        with pytest.raises(ValueError, match="offset must be >= 0"):
            ListAPInvoicesRequest(legal_entity_id=uuid4(), offset=-1)

    def test_validation_date_tz_conversion(self):
        naive = datetime(2025, 1, 1, 0, 0, 0)
        req = ListAPInvoicesRequest(legal_entity_id=uuid4(), from_date=naive, to_date=naive)
        assert req.from_date.tzinfo == UTC
        assert req.to_date.tzinfo == UTC

    def test_to_dict(self, sample_legal_entity_id):
        req = ListAPInvoicesRequest(
            legal_entity_id=sample_legal_entity_id,
            vendor_id=uuid4(),
            from_date=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
            to_date=datetime(2025, 1, 31, 0, 0, 0, tzinfo=UTC),
            status=APInvoiceStatus.APPROVED,
            is_overdue=True,
            limit=50,
            offset=10,
        )
        d = req.to_dict()
        assert d["legal_entity_id"] == str(sample_legal_entity_id)
        assert d["vendor_id"] is not None
        assert d["from_date"] == "2025-01-01T00:00:00+00:00"
        assert d["to_date"] == "2025-01-31T00:00:00+00:00"
        assert d["status"] == "approved"
        assert d["is_overdue"] is True
        assert d["limit"] == 50
        assert d["offset"] == 10


# -------------------- Tests for GetAPAgingRequest --------------------
class TestGetAPAgingRequest:
    def test_construction_default(self, sample_legal_entity_id):
        req = GetAPAgingRequest(legal_entity_id=sample_legal_entity_id)
        assert req.as_of_date is not None
        assert req.as_of_date.tzinfo == UTC

    def test_validation_tz_conversion(self):
        naive = datetime(2025, 1, 1, 0, 0, 0)
        req = GetAPAgingRequest(legal_entity_id=uuid4(), as_of_date=naive)
        assert req.as_of_date.tzinfo == UTC

    def test_to_dict(self, sample_legal_entity_id):
        as_of = datetime(2025, 1, 15, 0, 0, 0, tzinfo=UTC)
        req = GetAPAgingRequest(
            legal_entity_id=sample_legal_entity_id,
            as_of_date=as_of,
            vendor_id=uuid4(),
        )
        d = req.to_dict()
        assert d["legal_entity_id"] == str(sample_legal_entity_id)
        assert d["as_of_date"] == "2025-01-15T00:00:00+00:00"
        assert d["vendor_id"] is not None


# -------------------- Tests for APPaymentRunRequestDTO --------------------
class TestAPPaymentRunRequestDTO:
    def test_construction_valid(self, sample_legal_entity_id):
        req = APPaymentRunRequestDTO(
            legal_entity_id=sample_legal_entity_id,
            payment_date=date(2025, 1, 31),
            payment_method="bank_transfer",
            bank_account_id=uuid4(),
            vendor_id=uuid4(),
            max_total_amount=Decimal("1000000"),
        )
        assert req.legal_entity_id == sample_legal_entity_id
        assert req.max_total_amount == Decimal("1000000")

    def test_validation_payment_method_required(self):
        with pytest.raises(ValueError, match="payment_method is required"):
            APPaymentRunRequestDTO(
                legal_entity_id=uuid4(),
                payment_date=date.today(),
                payment_method="",
            )

    def test_validation_max_total_amount_positive(self):
        with pytest.raises(ValueError, match="max_total_amount must be positive if provided"):
            APPaymentRunRequestDTO(
                legal_entity_id=uuid4(),
                payment_date=date.today(),
                payment_method="bank_transfer",
                max_total_amount=Decimal("0"),
            )

    def test_to_dict(self, sample_legal_entity_id):
        bank_id = uuid4()
        req = APPaymentRunRequestDTO(
            legal_entity_id=sample_legal_entity_id,
            payment_date=date(2025, 1, 31),
            payment_method="wire_transfer",
            bank_account_id=bank_id,
            vendor_id=uuid4(),
            max_total_amount=Decimal("2000000"),
        )
        d = req.to_dict()
        assert d["legal_entity_id"] == str(sample_legal_entity_id)
        assert d["payment_date"] == "2025-01-31"
        assert d["payment_method"] == "wire_transfer"
        assert d["bank_account_id"] == str(bank_id)
        assert d["vendor_id"] is not None
        assert d["max_total_amount"] == "2000000"


# -------------------- Tests for ThreeWayMatchRequestDTO --------------------
class TestThreeWayMatchRequestDTO:
    def test_construction_valid(self, sample_vendor_id):
        req = ThreeWayMatchRequestDTO(
            po_number="PO-001",
            grn_number="GRN-001",
            invoice_amount=Decimal("1000000"),
            vendor_id=sample_vendor_id,
        )
        assert req.po_number == "PO-001"
        assert req.grn_number == "GRN-001"

    def test_validation_po_and_grn_required(self):
        with pytest.raises(ValueError, match="po_number and grn_number are required"):
            ThreeWayMatchRequestDTO(
                po_number="",
                grn_number="GRN-001",
                invoice_amount=Decimal("100"),
                vendor_id=uuid4(),
            )
        with pytest.raises(ValueError, match="po_number and grn_number are required"):
            ThreeWayMatchRequestDTO(
                po_number="PO-001",
                grn_number="",
                invoice_amount=Decimal("100"),
                vendor_id=uuid4(),
            )

    def test_validation_invoice_amount_positive(self):
        with pytest.raises(ValueError, match="invoice_amount must be positive"):
            ThreeWayMatchRequestDTO(
                po_number="PO-001",
                grn_number="GRN-001",
                invoice_amount=Decimal("-100"),
                vendor_id=uuid4(),
            )

    def test_to_dict(self, sample_vendor_id):
        req = ThreeWayMatchRequestDTO(
            po_number="PO-001",
            grn_number="GRN-001",
            invoice_amount=Decimal("1000000"),
            vendor_id=sample_vendor_id,
        )
        d = req.to_dict()
        assert d["po_number"] == "PO-001"
        assert d["grn_number"] == "GRN-001"
        assert d["invoice_amount"] == "1000000"
        assert d["vendor_id"] == str(sample_vendor_id)


# -------------------- Tests for ApInvoiceRequest (simple) --------------------
class TestApInvoiceRequest:
    def test_construction_valid(self):
        req = ApInvoiceRequest(supplier_id="SUP-001", amount=Decimal("1000"), tax=Decimal("100"))
        assert req.supplier_id == "SUP-001"
        assert req.amount == Decimal("1000")
        assert req.tax == Decimal("100")
        assert req.total == Decimal("1100")
        assert req.due_date.tzinfo == UTC

    def test_validation_amount_positive(self):
        with pytest.raises(ValueError, match="Amount must be positive"):
            ApInvoiceRequest(supplier_id="SUP-001", amount=Decimal("-100"))

    def test_validation_tax_non_negative(self):
        with pytest.raises(ValueError, match="Tax cannot be negative"):
            ApInvoiceRequest(supplier_id="SUP-001", amount=Decimal("100"), tax=Decimal("-10"))

    def test_property_total(self):
        req = ApInvoiceRequest(supplier_id="SUP-001", amount=Decimal("1000"), tax=Decimal("0"))
        assert req.total == Decimal("1000")


# -------------------- Tests for APInvoiceRequestFactory --------------------
class TestAPInvoiceRequestFactory:
    def test_create_invoice_line(self):
        item_id = uuid4()
        line = APInvoiceRequestFactory.create_invoice_line(
            item_id=item_id,
            item_code="ITEM002",
            item_name="Product X",
            quantity=Decimal("3"),
            unit_price=Decimal("50000"),
            description="Test",
            po_item_id=uuid4(),
            discount_percentage=Decimal("5"),
            tax_rate=Decimal("11"),
        )
        assert line.item_id == item_id
        assert line.item_code == "ITEM002"
        assert line.quantity == Decimal("3")
        assert line.unit_price == Decimal("50000")
        assert line.discount_percentage == Decimal("5")
        assert line.tax_rate == Decimal("11")
        assert line.po_item_id is not None
        assert line.subtotal == Decimal("150000.00")
        assert line.discount_amount == Decimal("7500.00")
        assert line.net_amount == Decimal("142500.00")
        assert line.tax_amount == Decimal("15675.00")
        assert line.total_amount == Decimal("158175.00")

    def test_create_simple_invoice(self, sample_vendor_id):
        item_id = uuid4()
        invoice_date = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        due_date = invoice_date + timedelta(days=30)
        req = APInvoiceRequestFactory.create_simple_invoice(
            invoice_number="AP-INV-002",
            vendor_id=sample_vendor_id,
            vendor_name="Simple Vendor",
            invoice_date=invoice_date,
            due_date=due_date,
            amount=Decimal("75000"),
            item_id=item_id,
            item_code="ITEM003",
            item_name="Simple Item",
            quantity=Decimal("1"),
            unit_price=Decimal("75000"),
            description="Simple",
        )
        assert req.invoice_number == "AP-INV-002"
        assert len(req.lines) == 1
        line = req.lines[0]
        assert line.item_id == item_id
        assert line.quantity == Decimal("1")
        assert line.unit_price == Decimal("75000")
        # total: 75000 + 11% tax = 83250
        assert req.calculate_total_amount() == Decimal("83250.00")

    def test_create_payment(self, sample_vendor_id, sample_invoice_id):
        payment_date = datetime(2025, 1, 20, 0, 0, 0, tzinfo=UTC)
        req = APInvoiceRequestFactory.create_payment(
            payment_number="AP-PAY-002",
            vendor_id=sample_vendor_id,
            vendor_name="Payment Vendor",
            payment_date=payment_date,
            amount=Decimal("500000"),
            invoice_id=sample_invoice_id,
            payment_method=APPaymentMethod.CHEQUE,
        )
        assert req.payment_number == "AP-PAY-002"
        assert req.vendor_id == sample_vendor_id
        assert req.invoice_id == sample_invoice_id
        assert req.payment_method == APPaymentMethod.CHEQUE
        assert req.amount == Decimal("500000")


# -------------------- Tests for APInvoiceResponseDTO --------------------
class TestAPInvoiceResponseDTO:
    def test_construction_valid(self, sample_response_dto):
        assert sample_response_dto.id is not None
        assert sample_response_dto.created_at.tzinfo == UTC

    def test_is_overdue(self, sample_response_dto):
        # due_date is 2025-01-31, check with future date
        future = datetime(2025, 2, 1, 0, 0, 0, tzinfo=UTC)
        assert sample_response_dto.is_overdue(future) is True
        past = datetime(2025, 1, 15, 0, 0, 0, tzinfo=UTC)
        assert sample_response_dto.is_overdue(past) is False
        # if remaining_amount is 0, not overdue
        dto_zero = APInvoiceResponseDTO(
            id=uuid4(),
            invoice_number="INV",
            vendor_id=uuid4(),
            vendor_name="Vendor",
            invoice_date=datetime.now(UTC),
            due_date=datetime(2025, 1, 31, 0, 0, 0, tzinfo=UTC),
            amount=Decimal("1000"),
            paid_amount=Decimal("1000"),
            remaining_amount=Decimal("0"),
            status="fully_paid",
        )
        assert dto_zero.is_overdue(future) is False

    def test_get_payment_percentage(self, sample_response_dto):
        # paid=500000, amount=2500000 => 20%
        assert sample_response_dto.get_payment_percentage() == Decimal("20.00")
        # fully paid
        dto_full = APInvoiceResponseDTO(
            id=uuid4(),
            invoice_number="INV",
            vendor_id=uuid4(),
            vendor_name="Vendor",
            invoice_date=datetime.now(UTC),
            due_date=datetime.now(UTC),
            amount=Decimal("1000"),
            paid_amount=Decimal("1000"),
            remaining_amount=Decimal("0"),
            status="fully_paid",
        )
        assert dto_full.get_payment_percentage() == Decimal("100.00")
        # zero amount
        dto_zero = APInvoiceResponseDTO(
            id=uuid4(),
            invoice_number="INV",
            vendor_id=uuid4(),
            vendor_name="Vendor",
            invoice_date=datetime.now(UTC),
            due_date=datetime.now(UTC),
            amount=Decimal("0"),
            paid_amount=Decimal("0"),
            remaining_amount=Decimal("0"),
            status="draft",
        )
        assert dto_zero.get_payment_percentage() == Decimal("0")

    def test_to_dict(self, sample_response_dto):
        d = sample_response_dto.to_dict()
        assert d["id"] == str(sample_response_dto.id)
        assert d["invoice_number"] == "AP-INV-001"
        assert d["amount"] == "2500000"
        assert d["paid_amount"] == "500000"
        assert d["remaining_amount"] == "2000000"
        assert d["status"] == "approved"
        assert d["po_reference"] == "PO-001"
        assert d["grn_reference"] == "GRN-001"


# -------------------- Tests for APPaymentResponseDTO --------------------
class TestAPPaymentResponseDTO:
    def test_construction_valid(self):
        dto = APPaymentResponseDTO(
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
        dto = APPaymentResponseDTO(
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
