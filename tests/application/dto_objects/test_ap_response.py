# tests/application/dto_objects/test_ap_response.py
"""
Comprehensive unit tests for application/dto_objects/ap_response.py.
Covers all DTO classes, methods, and edge cases with mocked datetime to avoid flakiness.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from application.dto_objects.ap_response import (
    APAgingBucketDTO,
    APAgingReportDTO,
    APCreditNoteResponseDTO,
    APInvoiceResponseDTO,
    APPaymentResponseDTO,
    APPaymentRunResponseDTO,
    APVendorBalanceDTO,
    ThreeWayMatchResultDTO,
)

# ============================================================================
# Fixed datetime for deterministic tests
# ============================================================================

FIXED_NOW = datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC)
FIXED_DATE = date(2026, 7, 23)
FIXED_PAST_DATE = FIXED_DATE - timedelta(days=10)
FIXED_FUTURE_DATE = FIXED_DATE + timedelta(days=10)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    with patch("application.dto_objects.ap_response.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.UTC = UTC
        yield mock_dt


@pytest.fixture(autouse=True)
def mock_date_today():
    with patch("application.dto_objects.ap_response.date") as mock_date:
        mock_date.today.return_value = FIXED_DATE
        yield mock_date


# ============================================================================
# Fixtures for sample data
# ============================================================================

@pytest.fixture
def vendor_id():
    return uuid4()


@pytest.fixture
def invoice_id():
    return uuid4()


@pytest.fixture
def sample_invoice_data(vendor_id):
    return {
        "id": uuid4(),
        "invoice_number": "INV-001",
        "vendor_id": vendor_id,
        "vendor_name": "PT Supplier",
        "invoice_date": FIXED_DATE - timedelta(days=5),
        "due_date": FIXED_DATE + timedelta(days=10),
        "amount": Decimal("1000000.00"),
        "paid_amount": Decimal("0.00"),
        "remaining_amount": Decimal("1000000.00"),
        "currency": "IDR",
        "status": "OPEN",
        "invoice_type": "PURCHASE",
        "tax_amount": Decimal("110000.00"),
        "withholding_amount": Decimal("0.00"),
        "description": "Test invoice",
        "po_number": "PO-001",
        "grn_number": "GRN-001",
        "created_by": uuid4(),
        "approved_by": uuid4(),
        "approved_at": FIXED_NOW,
        "version": 1,
    }


@pytest.fixture
def sample_invoice(sample_invoice_data):
    return APInvoiceResponseDTO(**sample_invoice_data)


@pytest.fixture
def sample_payment_data(vendor_id):
    return {
        "id": uuid4(),
        "payment_number": "PAY-001",
        "vendor_id": vendor_id,
        "vendor_name": "PT Supplier",
        "payment_date": FIXED_DATE,
        "amount": Decimal("500000.00"),
        "applied_amount": Decimal("500000.00"),
        "remaining_to_allocate": Decimal("0.00"),
        "payment_method": "BANK_TRANSFER",
        "reference_number": "REF-001",
        "status": "COMPLETED",
        "payment_run_id": uuid4(),
        "bank_account_id": uuid4(),
        "notes": "Test payment",
    }


@pytest.fixture
def sample_payment(sample_payment_data):
    return APPaymentResponseDTO(**sample_payment_data)


@pytest.fixture
def sample_credit_note_data(vendor_id):
    return {
        "id": uuid4(),
        "credit_note_number": "CN-001",
        "vendor_id": vendor_id,
        "original_invoice_id": uuid4(),
        "issue_date": FIXED_DATE,
        "amount": Decimal("100000.00"),
        "applied_amount": Decimal("50000.00"),
        "remaining_amount": Decimal("50000.00"),
        "reason": "Price adjustment",
        "tax_amount": Decimal("11000.00"),
        "currency": "IDR",
    }


@pytest.fixture
def sample_credit_note(sample_credit_note_data):
    return APCreditNoteResponseDTO(**sample_credit_note_data)


@pytest.fixture
def sample_vendor_balance_data(vendor_id):
    return {
        "vendor_id": vendor_id,
        "vendor_name": "PT Supplier",
        "vendor_code": "SUP-001",
        "total_invoiced": Decimal("1000000.00"),
        "total_payments": Decimal("500000.00"),
        "total_credit_notes": Decimal("100000.00"),
        "net_balance": Decimal("400000.00"),
        "currency": "IDR",
        "as_of_date": FIXED_DATE,
        "overdue_amount": Decimal("0.00"),
    }


@pytest.fixture
def sample_vendor_balance(sample_vendor_balance_data):
    return APVendorBalanceDTO(**sample_vendor_balance_data)


@pytest.fixture
def sample_aging_buckets():
    return [
        APAgingBucketDTO(bucket_name="CURRENT", amount=Decimal("100000"), percentage=10.0, invoice_count=2),
        APAgingBucketDTO(bucket_name="1-30 DAYS", amount=Decimal("300000"), percentage=30.0, invoice_count=5),
        APAgingBucketDTO(bucket_name="31-60 DAYS", amount=Decimal("400000"), percentage=40.0, invoice_count=3),
        APAgingBucketDTO(bucket_name="OVER 90 DAYS", amount=Decimal("200000"), percentage=20.0, invoice_count=1),
    ]


@pytest.fixture
def sample_aging_report_data(vendor_id, sample_aging_buckets):
    return {
        "legal_entity_id": vendor_id,
        "legal_entity_name": "PT Test Entity",
        "as_of_date": FIXED_DATE,
        "buckets": sample_aging_buckets,
        "total_ap": Decimal("1000000"),
        "vendor_balances": {"vendor1": "400000.00"},
        "vendor_details": [{"vendor_id": "vendor1", "balance": "400000.00"}],
        "generated_at": FIXED_NOW,
    }


@pytest.fixture
def sample_payment_run_data():
    return {
        "run_id": uuid4(),
        "run_number": "PR-001",
        "run_date": FIXED_DATE,
        "total_amount": Decimal("1000000.00"),
        "payment_count": 3,
        "status": "APPROVED",
        "payments": None,
        "created_by": "system",
        "approved_by": "manager",
        "approved_at": FIXED_NOW,
        "processed_at": None,
    }


@pytest.fixture
def sample_three_way_match_data():
    return {
        "is_match": True,
        "discrepancies": [],
        "matched_amount": Decimal("1000.00"),
        "po_amount": Decimal("1000.00"),
        "grn_amount": Decimal("1000.00"),
        "invoice_amount": Decimal("1000.00"),
        "po_number": "PO-001",
        "grn_number": "GRN-001",
        "invoice_number": "INV-001",
        "tolerance": Decimal("0.01"),
    }


# ============================================================================
# Tests for APInvoiceResponseDTO
# ============================================================================

class TestAPInvoiceResponseDTO:
    def test_construction(self, sample_invoice_data):
        dto = APInvoiceResponseDTO(**sample_invoice_data)
        assert dto.id == sample_invoice_data["id"]
        assert dto.remaining_amount == sample_invoice_data["remaining_amount"]
        assert dto.created_at.tzinfo == UTC
        assert dto.approved_at.tzinfo == UTC

    def test_remaining_amount_auto_calc(self, vendor_id):
        dto = APInvoiceResponseDTO(
            id=uuid4(),
            invoice_number="INV-002",
            vendor_id=vendor_id,
            vendor_name="Vendor",
            invoice_date=FIXED_DATE,
            due_date=FIXED_DATE + timedelta(days=30),
            amount=Decimal("1000"),
            paid_amount=Decimal("300"),
            invoice_type="PURCHASE",
            description=None,
            po_number=None,
            grn_number=None,
        )
        # remaining_amount should be auto-calculated as amount - paid_amount = 700
        assert dto.remaining_amount == Decimal("700")

    def test_to_dict(self, sample_invoice):
        d = sample_invoice.to_dict()
        assert d["id"] == str(sample_invoice.id)
        assert d["invoice_number"] == "INV-001"
        assert d["amount"] == "1000000.00"
        assert d["remaining_amount"] == "1000000.00"
        assert d["created_at"] == FIXED_NOW.isoformat()
        assert d["approved_at"] == FIXED_NOW.isoformat()
        assert "version" in d

    def test_is_overdue_false(self, sample_invoice):
        assert sample_invoice.is_overdue() is False  # due_date in future

    def test_is_overdue_true(self, sample_invoice):
        # Change due date to past and remaining > 0
        sample_invoice.due_date = FIXED_DATE - timedelta(days=1)
        assert sample_invoice.is_overdue() is True

    def test_is_overdue_paid(self, sample_invoice):
        sample_invoice.remaining_amount = Decimal("0")
        sample_invoice.due_date = FIXED_DATE - timedelta(days=1)
        assert sample_invoice.is_overdue() is False  # paid

    def test_is_overdue_custom_as_of(self, sample_invoice):
        # due_date is future, as_of in future > due_date
        sample_invoice.due_date = FIXED_DATE + timedelta(days=5)
        assert sample_invoice.is_overdue(as_of_date=FIXED_DATE + timedelta(days=10)) is True

    def test_get_paid_percentage(self, sample_invoice):
        sample_invoice.paid_amount = Decimal("250000")
        assert sample_invoice.get_paid_percentage() == Decimal("25.00")

    def test_get_paid_percentage_zero_amount(self, sample_invoice):
        sample_invoice.amount = Decimal("0")
        sample_invoice.paid_amount = Decimal("0")
        assert sample_invoice.get_paid_percentage() == Decimal("0")

    def test_get_aging_bucket_current(self, sample_invoice):
        # due_date in future => CURRENT
        assert sample_invoice.get_aging_bucket() == "CURRENT"

    def test_get_aging_bucket_1_30(self, sample_invoice):
        sample_invoice.due_date = FIXED_DATE - timedelta(days=15)
        assert sample_invoice.get_aging_bucket() == "1-30 DAYS"

    def test_get_aging_bucket_31_60(self, sample_invoice):
        sample_invoice.due_date = FIXED_DATE - timedelta(days=45)
        assert sample_invoice.get_aging_bucket() == "31-60 DAYS"

    def test_get_aging_bucket_61_90(self, sample_invoice):
        sample_invoice.due_date = FIXED_DATE - timedelta(days=75)
        assert sample_invoice.get_aging_bucket() == "61-90 DAYS"

    def test_get_aging_bucket_over_90(self, sample_invoice):
        sample_invoice.due_date = FIXED_DATE - timedelta(days=95)
        assert sample_invoice.get_aging_bucket() == "OVER 90 DAYS"

    def test_get_aging_bucket_paid(self, sample_invoice):
        sample_invoice.remaining_amount = Decimal("0")
        sample_invoice.due_date = FIXED_DATE - timedelta(days=95)
        assert sample_invoice.get_aging_bucket() == "PAID"

    def test_get_aging_bucket_custom_as_of(self, sample_invoice):
        # due_date is future, but as_of is much later
        sample_invoice.due_date = FIXED_DATE + timedelta(days=10)
        assert sample_invoice.get_aging_bucket(as_of_date=FIXED_DATE + timedelta(days=15)) == "1-30 DAYS"


# ============================================================================
# Tests for APPaymentResponseDTO
# ============================================================================

class TestAPPaymentResponseDTO:
    def test_construction(self, sample_payment_data):
        dto = APPaymentResponseDTO(**sample_payment_data)
        assert dto.id == sample_payment_data["id"]
        assert dto.remaining_to_allocate == sample_payment_data["remaining_to_allocate"]
        assert dto.created_at.tzinfo == UTC

    def test_remaining_to_allocate_auto_calc(self, vendor_id):
        dto = APPaymentResponseDTO(
            id=uuid4(),
            payment_number="PAY-002",
            vendor_id=vendor_id,
            vendor_name="Vendor",
            payment_date=FIXED_DATE,
            amount=Decimal("1000"),
            applied_amount=Decimal("400"),
            remaining_to_allocate=Decimal("0"),  # will be auto-calculated
            payment_method="CASH",
            reference_number="REF",
        )
        assert dto.remaining_to_allocate == Decimal("600")

    def test_to_dict(self, sample_payment):
        d = sample_payment.to_dict()
        assert d["id"] == str(sample_payment.id)
        assert d["payment_number"] == "PAY-001"
        assert d["amount"] == "500000.00"
        assert d["applied_amount"] == "500000.00"
        assert d["remaining_to_allocate"] == "0.00"

    def test_is_fully_applied_true(self, sample_payment):
        assert sample_payment.is_fully_applied() is True

    def test_is_fully_applied_false(self, sample_payment):
        sample_payment.remaining_to_allocate = Decimal("100")
        assert sample_payment.is_fully_applied() is False

    def test_get_applied_percentage(self, sample_payment):
        assert sample_payment.get_applied_percentage() == Decimal("100.00")

    def test_get_applied_percentage_partial(self, sample_payment):
        sample_payment.applied_amount = Decimal("300000")
        sample_payment.amount = Decimal("500000")
        assert sample_payment.get_applied_percentage() == Decimal("60.00")

    def test_get_applied_percentage_zero_amount(self, sample_payment):
        sample_payment.amount = Decimal("0")
        sample_payment.applied_amount = Decimal("0")
        assert sample_payment.get_applied_percentage() == Decimal("0")


# ============================================================================
# Tests for APCreditNoteResponseDTO
# ============================================================================

class TestAPCreditNoteResponseDTO:
    def test_construction(self, sample_credit_note_data):
        dto = APCreditNoteResponseDTO(**sample_credit_note_data)
        assert dto.id == sample_credit_note_data["id"]
        assert dto.remaining_amount == sample_credit_note_data["remaining_amount"]
        assert dto.created_at.tzinfo == UTC

    def test_remaining_amount_auto_calc(self, vendor_id):
        dto = APCreditNoteResponseDTO(
            id=uuid4(),
            credit_note_number="CN-002",
            vendor_id=vendor_id,
            original_invoice_id=uuid4(),
            issue_date=FIXED_DATE,
            amount=Decimal("500"),
            applied_amount=Decimal("200"),
            reason="Test",
            remaining_amount=Decimal("0"),  # will be auto-calc
        )
        assert dto.remaining_amount == Decimal("300")

    def test_to_dict(self, sample_credit_note):
        d = sample_credit_note.to_dict()
        assert d["id"] == str(sample_credit_note.id)
        assert d["credit_note_number"] == "CN-001"
        assert d["amount"] == "100000.00"
        assert d["applied_amount"] == "50000.00"
        assert d["remaining_amount"] == "50000.00"

    def test_is_fully_applied_true(self, sample_credit_note):
        sample_credit_note.remaining_amount = Decimal("0")
        assert sample_credit_note.is_fully_applied() is True

    def test_is_fully_applied_false(self, sample_credit_note):
        assert sample_credit_note.is_fully_applied() is False


# ============================================================================
# Tests for APVendorBalanceDTO
# ============================================================================

class TestAPVendorBalanceDTO:
    def test_construction(self, sample_vendor_balance_data):
        dto = APVendorBalanceDTO(**sample_vendor_balance_data)
        assert dto.vendor_id == sample_vendor_balance_data["vendor_id"]
        assert dto.net_balance == sample_vendor_balance_data["net_balance"]
        assert dto.as_of_date == FIXED_DATE

    def test_to_dict(self, sample_vendor_balance):
        d = sample_vendor_balance.to_dict()
        assert d["vendor_id"] == str(sample_vendor_balance.vendor_id)
        assert d["vendor_name"] == "PT Supplier"
        assert d["net_balance"] == "400000.00"
        assert d["as_of_date"] == FIXED_DATE.isoformat()

    def test_get_balance_direction_credit(self, sample_vendor_balance):
        # net_balance > 0 => CREDIT (we owe)
        assert sample_vendor_balance.get_balance_direction() == "CREDIT"

    def test_get_balance_direction_debit(self, sample_vendor_balance):
        sample_vendor_balance.net_balance = Decimal("-100000")
        assert sample_vendor_balance.get_balance_direction() == "DEBIT"

    def test_get_balance_direction_zero(self, sample_vendor_balance):
        sample_vendor_balance.net_balance = Decimal("0")
        assert sample_vendor_balance.get_balance_direction() == "ZERO"


# ============================================================================
# Tests for APAgingBucketDTO
# ============================================================================

class TestAPAgingBucketDTO:
    def test_construction(self):
        bucket = APAgingBucketDTO(bucket_name="CURRENT", amount=Decimal("1000"), percentage=10.0, invoice_count=5)
        assert bucket.bucket_name == "CURRENT"
        assert bucket.amount == Decimal("1000")
        assert bucket.percentage == 10.0
        assert bucket.invoice_count == 5

    def test_to_dict(self):
        bucket = APAgingBucketDTO(bucket_name="CURRENT", amount=Decimal("1000"), percentage=10.0, invoice_count=5)
        d = bucket.to_dict()
        assert d["bucket_name"] == "CURRENT"
        assert d["amount"] == "1000"
        assert d["percentage"] == 10.0
        assert d["invoice_count"] == 5

    def test_create(self):
        bucket = APAgingBucketDTO.create("CURRENT", Decimal("300"), Decimal("1000"), invoice_count=2)
        assert bucket.amount == Decimal("300")
        assert bucket.percentage == 30.0
        assert bucket.invoice_count == 2

    def test_create_zero_total(self):
        bucket = APAgingBucketDTO.create("CURRENT", Decimal("0"), Decimal("0"))
        assert bucket.percentage == 0.0


# ============================================================================
# Tests for APAgingReportDTO
# ============================================================================

class TestAPAgingReportDTO:
    def test_construction(self, sample_aging_report_data):
        dto = APAgingReportDTO(**sample_aging_report_data)
        assert dto.legal_entity_id == sample_aging_report_data["legal_entity_id"]
        assert len(dto.buckets) == 4
        assert dto.total_ap == Decimal("1000000")
        assert dto.generated_at.tzinfo == UTC

    def test_to_dict(self, sample_aging_report_data, sample_aging_buckets):
        dto = APAgingReportDTO(**sample_aging_report_data)
        d = dto.to_dict()
        assert d["legal_entity_id"] == str(sample_aging_report_data["legal_entity_id"])
        assert d["total_ap"] == "1000000"
        assert len(d["buckets"]) == 4
        assert d["vendor_balances"] == {"vendor1": "400000.00"}

    def test_get_bucket_by_name_found(self, sample_aging_report_data):
        dto = APAgingReportDTO(**sample_aging_report_data)
        bucket = dto.get_bucket_by_name("CURRENT")
        assert bucket is not None
        assert bucket.amount == Decimal("100000")

    def test_get_bucket_by_name_not_found(self, sample_aging_report_data):
        dto = APAgingReportDTO(**sample_aging_report_data)
        bucket = dto.get_bucket_by_name("NONEXISTENT")
        assert bucket is None


# ============================================================================
# Tests for APPaymentRunResponseDTO
# ============================================================================

class TestAPPaymentRunResponseDTO:
    def test_construction(self, sample_payment_run_data):
        dto = APPaymentRunResponseDTO(**sample_payment_run_data)
        assert dto.run_id == sample_payment_run_data["run_id"]
        assert dto.total_amount == Decimal("1000000.00")
        assert dto.payment_count == 3
        assert dto.created_at.tzinfo == UTC
        assert dto.approved_at.tzinfo == UTC
        assert dto.processed_at is None

    def test_to_dict(self, sample_payment_run_data):
        dto = APPaymentRunResponseDTO(**sample_payment_run_data)
        d = dto.to_dict()
        assert d["run_id"] == str(dto.run_id)
        assert d["run_number"] == "PR-001"
        assert d["total_amount"] == "1000000.00"
        assert d["payment_count"] == 3
        assert d["status"] == "APPROVED"
        assert d["payments"] == []

    def test_is_approved_true(self, sample_payment_run_data):
        dto = APPaymentRunResponseDTO(**sample_payment_run_data)
        assert dto.is_approved() is True

    def test_is_approved_false(self, sample_payment_run_data):
        sample_payment_run_data["status"] = "DRAFT"
        dto = APPaymentRunResponseDTO(**sample_payment_run_data)
        assert dto.is_approved() is False

    def test_is_processed_true(self, sample_payment_run_data):
        sample_payment_run_data["status"] = "PROCESSED"
        dto = APPaymentRunResponseDTO(**sample_payment_run_data)
        assert dto.is_processed() is True

    def test_is_processed_false(self, sample_payment_run_data):
        sample_payment_run_data["status"] = "APPROVED"
        dto = APPaymentRunResponseDTO(**sample_payment_run_data)
        assert dto.is_processed() is False


# ============================================================================
# Tests for ThreeWayMatchResultDTO
# ============================================================================

class TestThreeWayMatchResultDTO:
    def test_construction(self, sample_three_way_match_data):
        dto = ThreeWayMatchResultDTO(**sample_three_way_match_data)
        assert dto.is_match is True
        assert dto.matched_amount == Decimal("1000.00")
        assert dto.tolerance == Decimal("0.01")

    def test_to_dict(self, sample_three_way_match_data):
        dto = ThreeWayMatchResultDTO(**sample_three_way_match_data)
        d = dto.to_dict()
        assert d["is_match"] is True
        assert d["po_amount"] == "1000.00"
        assert d["grn_amount"] == "1000.00"
        assert d["invoice_amount"] == "1000.00"

    def test_get_variance_amount(self, sample_three_way_match_data):
        dto = ThreeWayMatchResultDTO(**sample_three_way_match_data)
        # matched_amount = invoice_amount, so variance = 0
        assert dto.get_variance_amount() == Decimal("0")

    def test_get_variance_amount_positive(self, sample_three_way_match_data):
        sample_three_way_match_data["invoice_amount"] = Decimal("1050.00")
        dto = ThreeWayMatchResultDTO(**sample_three_way_match_data)
        assert dto.get_variance_amount() == Decimal("50.00")

    def test_get_variance_percentage(self, sample_three_way_match_data):
        dto = ThreeWayMatchResultDTO(**sample_three_way_match_data)
        assert dto.get_variance_percentage() == Decimal("0.00")

    def test_get_variance_percentage_positive(self, sample_three_way_match_data):
        sample_three_way_match_data["invoice_amount"] = Decimal("1050.00")
        dto = ThreeWayMatchResultDTO(**sample_three_way_match_data)
        # variance = 50 / 1000 * 100 = 5.00%
        assert dto.get_variance_percentage() == Decimal("5.00")

    def test_get_variance_percentage_zero_matched(self, sample_three_way_match_data):
        sample_three_way_match_data["matched_amount"] = Decimal("0")
        dto = ThreeWayMatchResultDTO(**sample_three_way_match_data)
        assert dto.get_variance_percentage() == Decimal("0")


# ============================================================================
# Additional edge cases and integration tests
# ============================================================================

class TestEdgeCases:
    def test_invoice_overdue_with_custom_as_of(self, sample_invoice):
        sample_invoice.due_date = FIXED_DATE - timedelta(days=5)
        # as_of = due_date (not overdue)
        assert sample_invoice.is_overdue(as_of_date=sample_invoice.due_date) is False
        # as_of = due_date + 1 day (overdue)
        assert sample_invoice.is_overdue(as_of_date=sample_invoice.due_date + timedelta(days=1)) is True

    def test_payment_applied_percentage_with_rounding(self, sample_payment_data):
        sample_payment_data["amount"] = Decimal("333.33")
        sample_payment_data["applied_amount"] = Decimal("111.11")
        dto = APPaymentResponseDTO(**sample_payment_data)
        # (111.11 / 333.33) * 100 = 33.33... rounded to 33.33
        assert dto.get_applied_percentage() == Decimal("33.33")

    def test_vendor_balance_with_negative_values(self, vendor_id):
        dto = APVendorBalanceDTO(
            vendor_id=vendor_id,
            vendor_name="Vendor",
            vendor_code="V001",
            total_invoiced=Decimal("0"),
            total_payments=Decimal("100"),
            total_credit_notes=Decimal("0"),
            net_balance=Decimal("-100"),
            currency="IDR",
            as_of_date=FIXED_DATE,
            overdue_amount=Decimal("0"),
        )
        assert dto.get_balance_direction() == "DEBIT"

    def test_aging_report_empty_buckets(self, vendor_id):
        dto = APAgingReportDTO(
            legal_entity_id=vendor_id,
            legal_entity_name="Entity",
            as_of_date=FIXED_DATE,
            buckets=[],
            total_ap=Decimal("0"),
            vendor_balances={},
            vendor_details=[],
        )
        assert len(dto.buckets) == 0
        assert dto.get_bucket_by_name("CURRENT") is None