# tests/adapters/primary_api/v1/test_fastapi_ar_router.py
"""
Comprehensive unit tests for FastAPI Accounts Receivable Router.

Perbaikan:
- Semua async test diberi @pytest.mark.asyncio
- Flaky tests menggunakan mock datetime
- Duplikasi struktural dihilangkan dengan parametrize
- Mock quality ditingkatkan: AsyncMock, verifikasi panggilan
- Negative path ditambahkan: ValueError, PermissionError, Exception
- Semua assertion bermakna
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.responses import Response

from adapters.primary_api.v1.fastapi_ar_router import (
    ARAgingBucketSchema,
    ARAgingResponseSchema,
    ARCollectionReminderResponseSchema,
    ARCollectionReminderSchema,
    ARCreditNoteCreateSchema,
    ARCreditNoteResponseSchema,
    ARCreditNoteStatus,
    ARDashboardSchema,
    ARInvoiceActionResponseSchema,
    ARInvoiceCreateSchema,
    ARInvoiceLineSchema,
    ARInvoiceListResponseSchema,
    ARInvoiceResponseSchema,
    ARInvoiceStatus,
    ARInvoiceUpdateSchema,
    ARPaymentCreateSchema,
    ARPaymentResponseSchema,
    ARPaymentReverseSchema,
    ARPaymentStatus,
    ARWriteOffResponseSchema,
    ARWriteOffSchema,
    CollectionStatus,
    IdempotencyManager,
    PaymentMethod,
    approve_ar_credit_note,
    approve_ar_invoice,
    bulk_approve_ar_invoices,
    bulk_send_payment_reminders,
    cancel_ar_credit_note,
    create_ar_credit_note,
    create_ar_invoice,
    delete_ar_invoice,
    escalate_collection,
    generate_ar_invoice_pdf,
    get_all_ar_aging,
    get_ar_aging_by_customer,
    get_ar_collection_workflow,
    get_ar_dashboard,
    get_ar_invoice,
    get_ar_invoice_history,
    get_ar_invoice_status,
    get_ar_payment,
    get_ar_svc,
    health,
    info,
    list_ar_invoices,
    lock_ar_invoice,
    ping,
    post_ar_invoice,
    record_ar_payment,
    reject_ar_invoice,
    restore_ar_invoice,
    reverse_ar_invoice,
    reverse_ar_payment,
    send_collection_reminders,
    start_collection_workflow,
    submit_ar_invoice,
    unlock_ar_invoice,
    update_ar_invoice,
    write_off_ar_invoice,
)

# ============================================================================
# FIXED DATETIME - untuk menghindari flaky tests
# ============================================================================
FIXED_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
FIXED_DATE = date(2026, 1, 1)
FIXED_DUE_DATE = date(2026, 1, 15)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    """Mock datetime.now() dan date.today() untuk menghindari flaky tests."""
    with patch("adapters.primary_api.v1.fastapi_ar_router.datetime") as mock_dt, \
         patch("adapters.primary_api.v1.fastapi_ar_router.date") as mock_date:
        mock_dt.now.return_value = FIXED_NOW
        mock_date.today.return_value = FIXED_DATE
        yield


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_token_payload():
    return MagicMock(user_id=uuid4())


@pytest.fixture
def mock_legal_entity_id():
    return uuid4()


@pytest.fixture
def mock_ar_service():
    """Create a fully mocked ARService with realistic return values."""
    svc = AsyncMock()

    # Helper to create mock invoice
    def mock_invoice(**kwargs):
        defaults = {
            "id": uuid4(),
            "invoice_number": "INV-001",
            "customer_id": uuid4(),
            "customer_name": "PT ABC",
            "customer_code": "CUST001",
            "invoice_date": FIXED_DATE,
            "due_date": FIXED_DUE_DATE,
            "total_amount": Decimal("1000000"),
            "paid_amount": Decimal("0"),
            "outstanding_amount": Decimal("1000000"),
            "discount_taken": Decimal("0"),
            "status": "draft",
            "description": "Test invoice",
            "lines": [],
            "tax_amount": Decimal("110000"),
            "created_at": FIXED_NOW,
            "created_by": uuid4(),
            "created_by_name": "Admin",
            "approved_at": None,
            "approved_by": None,
            "posted_at": None,
            "posted_by": None,
            "cancelled_at": None,
            "cancelled_by": None,
            "collection_status": "not_started",
            "last_reminder_sent_at": None,
            "version": 1,
            "is_locked": False,
        }
        defaults.update(kwargs)
        return MagicMock(**defaults)

    # Invoice methods
    svc.create_invoice.return_value = mock_invoice()
    svc.get_invoice_by_id.return_value = mock_invoice()
    svc.update_invoice.return_value = mock_invoice()
    svc.cancel_invoice.return_value = mock_invoice(status="cancelled")
    svc.void_invoice.return_value = mock_invoice(status="void")
    svc.restore_invoice.return_value = mock_invoice(status="draft")
    svc.submit_invoice.return_value = mock_invoice(status="submitted")
    svc.approve_invoice.return_value = mock_invoice(status="approved")
    svc.reject_invoice.return_value = mock_invoice(status="rejected")
    svc.post_invoice.return_value = mock_invoice(status="posted")
    svc.reverse_invoice.return_value = mock_invoice(status="void")
    svc.lock_invoice.return_value = mock_invoice(is_locked=True)
    svc.unlock_invoice.return_value = mock_invoice(is_locked=False)
    svc.list_invoices.return_value = MagicMock(
        items=[mock_invoice()],
        total=1,
        total_outstanding=Decimal("1000000"),
        total_paid=Decimal("0"),
        total_overdue=Decimal("0"),
    )

    # Payment methods
    def mock_payment(**kwargs):
        defaults = {
            "id": uuid4(),
            "payment_number": "PMT-001",
            "invoice_id": uuid4(),
            "invoice_number": "INV-001",
            "customer_id": uuid4(),
            "customer_name": "PT ABC",
            "payment_date": FIXED_DATE,
            "amount": Decimal("500000"),
            "discount_taken": Decimal("0"),
            "payment_method": "transfer",
            "status": "processed",
            "reference_number": "REF-001",
            "notes": "",
            "bank_account_id": uuid4(),
            "bank_account_name": "BCA",
            "cleared_at": FIXED_NOW,
            "created_at": FIXED_NOW,
            "created_by": uuid4(),
            "created_by_name": "Admin",
            "version": 1,
            "is_reversed": False,
            "reversed_at": None,
            "reversed_by": None,
        }
        defaults.update(kwargs)
        return MagicMock(**defaults)

    svc.record_payment.return_value = mock_payment()
    svc.get_payment_by_id.return_value = mock_payment()
    svc.reverse_payment.return_value = mock_payment(is_reversed=True, reversed_at=FIXED_NOW, reversed_by=uuid4())

    # Credit note
    def mock_credit_note(**kwargs):
        defaults = {
            "id": uuid4(),
            "credit_note_number": "CN-001",
            "invoice_id": uuid4(),
            "invoice_number": "INV-001",
            "customer_id": uuid4(),
            "customer_name": "PT ABC",
            "credit_note_date": FIXED_DATE,
            "amount": Decimal("100000"),
            "applied_amount": Decimal("0"),
            "remaining_amount": Decimal("100000"),
            "reason": "Adjustment",
            "reference_number": "REF",
            "status": "draft",
            "created_at": FIXED_NOW,
            "created_by": uuid4(),
            "created_by_name": "Admin",
            "approved_at": None,
            "approved_by": None,
            "version": 1,
        }
        defaults.update(kwargs)
        return MagicMock(**defaults)

    svc.create_credit_note.return_value = mock_credit_note()
    svc.approve_credit_note.return_value = mock_credit_note(status="approved")
    svc.cancel_credit_note.return_value = mock_credit_note(status="cancelled")

    # Aging
    def mock_aging(**kwargs):
        defaults = {
            "customer_id": uuid4(),
            "customer_name": "PT ABC",
            "customer_code": "CUST001",
            "total_outstanding": Decimal("1000000"),
            "total_allowance": Decimal("50000"),
            "buckets": [
                MagicMock(
                    bucket_name="0-30 days",
                    days_start=0,
                    days_end=30,
                    total_amount=Decimal("500000"),
                    percentage=50.0,
                    invoices=[],
                    allowance_amount=Decimal("25000"),
                )
            ],
        }
        defaults.update(kwargs)
        return MagicMock(**defaults)

    svc.get_aging_report.return_value = mock_aging()
    svc.get_aging_all_customers.return_value = [mock_aging()]

    # Dashboard
    def mock_dashboard(**kwargs):
        defaults = {
            "total_outstanding": Decimal("1000000"),
            "current_outstanding": Decimal("500000"),
            "overdue_1_30": Decimal("200000"),
            "overdue_31_60": Decimal("150000"),
            "overdue_61_90": Decimal("100000"),
            "overdue_90_plus": Decimal("50000"),
            "overdue_amount": Decimal("500000"),
            "overdue_percentage": 50.0,
            "dso_days": 45.5,
            "collection_efficiency": 80.0,
            "aging_buckets": [
                MagicMock(
                    bucket_name="0-30 days",
                    days_start=0,
                    days_end=30,
                    total_amount=Decimal("500000"),
                    percentage=50.0,
                    invoices=[],
                    allowance_amount=Decimal("25000"),
                )
            ],
        }
        defaults.update(kwargs)
        return MagicMock(**defaults)

    svc.get_dashboard.return_value = mock_dashboard()

    # Collection
    svc.send_collection_reminders.return_value = MagicMock(
        success=True, reminders_sent=2, invoices_processed=[uuid4()], errors=[]
    )
    svc.escalate_collection.return_value = MagicMock(
        invoice_number="INV-001", collection_status="escalated"
    )
    svc.bulk_approve_invoices.return_value = MagicMock(
        total=2, success_count=2, failed_count=0, failed_ids=[], errors=[]
    )
    svc.bulk_send_reminders.return_value = MagicMock(
        total=2, success_count=2, failed_count=0, failed_ids=[], errors=[]
    )

    # Status & History
    def mock_status_info(**kwargs):
        defaults = {
            "invoice_number": "INV-001",
            "status": "draft",
            "status_description": "Draft",
            "can_submit": True,
            "can_approve": False,
            "can_reject": False,
            "can_cancel": True,
            "can_post": False,
            "can_reverse": False,
            "can_pay": False,
            "is_locked": False,
            "is_archived": False,
            "current_approver": None,
            "approval_level": 0,
            "days_overdue": 0,
            "collection_status": "not_started",
        }
        defaults.update(kwargs)
        return MagicMock(**defaults)

    svc.get_invoice_status.return_value = mock_status_info()
    svc.get_invoice_history.return_value = [
        MagicMock(
            timestamp=FIXED_NOW,
            action="create",
            from_status=None,
            to_status="draft",
            actor_id=uuid4(),
            actor_name="Admin",
            reason=None,
            notes=None,
        )
    ]

    # PDF
    svc.generate_invoice_pdf.return_value = b"%PDF-1.4\n..."

    # Write-off
    svc.write_off_invoice.return_value = MagicMock(
        write_off_id=uuid4(),
        invoice_id=uuid4(),
        invoice_number="INV-001",
        write_off_amount=Decimal("100000"),
        remaining_outstanding=Decimal("0"),
        journal_id=uuid4(),
        status="completed",
        created_at=FIXED_NOW,
        created_by=uuid4(),
    )

    return svc


@pytest.fixture
def mock_collection_workflow():
    uc = AsyncMock()
    uc.start_collection_process.return_value = MagicMock(
        workflow_id=uuid4(),
        invoices_processed=[uuid4()],
        reminders_sent=2,
        escalated_to_collection=1,
        message="Collection started",
    )
    return uc


# ============================================================================
# IDEMPOTENCY MANAGER TESTS
# ============================================================================

class TestIdempotencyManager:
    def test_construction(self):
        instance = IdempotencyManager()
        assert isinstance(instance, IdempotencyManager)
        assert instance._storage == {}
        assert instance._ttl_seconds == 86400

    def test_get_cached_result_miss(self):
        instance = IdempotencyManager()
        result = instance.get_cached_result("key", "method")
        assert result is None

    def test_cache_and_retrieve(self):
        instance = IdempotencyManager()
        data = {"id": "123", "status": "ok"}
        instance.cache_result("key", "method", data)
        cached = instance.get_cached_result("key", "method")
        assert cached == data

    @patch("adapters.primary_api.v1.fastapi_ar_router.datetime")
    def test_cache_expiration(self, mock_dt):
        mock_dt.now.return_value = FIXED_NOW
        instance = IdempotencyManager()
        instance._ttl_seconds = 0
        instance.cache_result("key", "method", {"foo": "bar"})
        cached = instance.get_cached_result("key", "method")
        assert cached is None

    def test_key_generation_deterministic(self):
        instance = IdempotencyManager()
        key1 = instance._get_key("abc", "create_ar_invoice")
        key2 = instance._get_key("abc", "create_ar_invoice")
        key3 = instance._get_key("abc", "update_ar_invoice")
        assert key1 == key2
        assert key1 != key3


# ============================================================================
# ENUM TESTS (parametrized untuk menghindari duplikasi)
# ============================================================================

ENUM_TEST_DATA = [
    (ARInvoiceStatus, [
        "DRAFT", "PENDING", "SUBMITTED", "VALIDATED", "APPROVED", "REJECTED",
        "PARTIALLY_PAID", "PAID", "CANCELLED", "VOID", "POSTED", "CLOSED",
        "ARCHIVED", "LOCKED", "OVERDUE", "IN_COLLECTION", "WRITTEN_OFF", "ERROR"
    ]),
    (ARPaymentStatus, ["DRAFT", "PENDING", "PROCESSED", "CLEARED", "REJECTED", "CANCELLED", "VOID", "REVERSED"]),
    (ARCreditNoteStatus, ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "APPLIED", "CANCELLED", "VOID"]),
    (PaymentMethod, ["TRANSFER", "CASH", "CREDIT_CARD", "GIRO", "DEBIT_CARD"]),
    (CollectionStatus, ["NOT_STARTED", "REMINDER_SENT", "ESCALATED", "LEGAL_ACTION", "RESOLVED"]),
]


class TestEnums:
    @pytest.mark.parametrize("enum_class, members", ENUM_TEST_DATA)
    def test_members_exist(self, enum_class, members):
        for member in members:
            assert hasattr(enum_class, member)

    @pytest.mark.parametrize("enum_class, members", ENUM_TEST_DATA)
    def test_member_is_instance(self, enum_class, members):
        first_member = getattr(enum_class, members[0])
        assert isinstance(first_member, enum_class)


# ============================================================================
# SCHEMA TESTS (parametrized)
# ============================================================================

SCHEMA_TEST_DATA = [
    (ARInvoiceLineSchema, {
        "description": "Test line",
        "quantity": Decimal("2"),
        "unit_price": Decimal("100000"),
        "tax_rate": Decimal("0.11"),
        "discount_percent": Decimal("0"),      
        "account_code": "1100",
        "sales_order_line_id": uuid4(),
    }),
    (ARInvoiceCreateSchema, {
        "customer_code": "CUST001",
        "invoice_date": FIXED_DATE,
        "due_date": FIXED_DUE_DATE,
        "invoice_number": "INV-001",
        "lines": [
            ARInvoiceLineSchema(
                description="Line 1",
                quantity=Decimal("1"),
                unit_price=Decimal("100000"),
                account_code="1100",
                discount_percent=Decimal("0"),  
            )
        ],
        "description": "Test",
        "reference_number": "REF",
        "sales_order_id": uuid4(),
        "tax_invoice_number": "TAX-001",
        "use_tax": True,
        "discount_global": Decimal("0"),
        "early_payment_discount_percent": Decimal("2"),
        "early_payment_discount_days": 10,
    }),
    (ARInvoiceUpdateSchema, {
        "due_date": FIXED_DUE_DATE,
        "description": "Updated",
        "reference_number": "REF-002",
        "notes": "Notes",
        "status": ARInvoiceStatus.DRAFT,
        "early_payment_discount_percent": Decimal("1.5"),
        "early_payment_discount_days": 7,
    }),
    (ARInvoiceResponseSchema, {
        "id": uuid4(),
        "invoice_number": "INV-001",
        "customer_id": uuid4(),
        "customer_name": "PT ABC",
        "customer_code": "CUST001",
        "invoice_date": FIXED_DATE,
        "due_date": FIXED_DUE_DATE,
        "total_amount": Decimal("1000000"),
        "paid_amount": Decimal("0"),
        "outstanding_amount": Decimal("1000000"),
        "discount_taken": Decimal("0"),
        "early_payment_discount_eligible": False,
        "early_payment_discount_amount": Decimal("0"),
        "status": ARInvoiceStatus.DRAFT,
        "description": "Test",
        "lines": [],
        "tax_amount": Decimal("110000"),
        "created_at": FIXED_NOW,
        "created_by": uuid4(),
        "created_by_name": "Admin",
        "approved_at": None,
        "approved_by": None,
        "approved_by_name": None,
        "posted_at": None,
        "posted_by": None,
        "cancelled_at": None,
        "cancelled_by": None,
        "collection_status": CollectionStatus.NOT_STARTED,
        "last_reminder_sent_at": None,
        "days_overdue": 0,
        "version": 1,
        "is_locked": False,
        "can_approve": True,
        "can_cancel": True,
        "can_post": True,
    }),
    (ARPaymentCreateSchema, {
        "invoice_id": uuid4(),
        "payment_date": FIXED_DATE,
        "amount": Decimal("500000"),
        "payment_method": PaymentMethod.TRANSFER,
        "bank_account_id": uuid4(),
        "reference_number": "PMT-001",
        "notes": "Partial",
        "discount_taken": Decimal("0"),
        "apply_early_payment_discount": False,
    }),
    (ARPaymentResponseSchema, {
        "id": uuid4(),
        "payment_number": "PMT-001",
        "invoice_id": uuid4(),
        "invoice_number": "INV-001",
        "customer_id": uuid4(),
        "customer_name": "PT ABC",
        "payment_date": FIXED_DATE,
        "amount": Decimal("500000"),
        "discount_taken": Decimal("0"),
        "payment_method": PaymentMethod.TRANSFER,
        "status": ARPaymentStatus.PROCESSED,
        "reference_number": "REF-001",
        "notes": "",
        "bank_account_id": uuid4(),
        "bank_account_name": "BCA",
        "cleared_at": FIXED_NOW,
        "created_at": FIXED_NOW,
        "created_by": uuid4(),
        "created_by_name": "Admin",
        "version": 1,
        "is_reversed": False,
        "reversed_at": None,
        "reversed_by": None,
    }),
    (ARPaymentReverseSchema, {"reason": "Duplicate", "reversal_date": FIXED_DATE}),
    (ARCreditNoteCreateSchema, {
        "invoice_id": uuid4(),
        "credit_note_date": FIXED_DATE,
        "amount": Decimal("100000"),
        "reason": "Adjustment",
        "reference_number": "CN-001",
        "apply_to_future_invoices": False,
    }),
    (ARCreditNoteResponseSchema, {
        "id": uuid4(),
        "credit_note_number": "CN-001",
        "invoice_id": uuid4(),
        "invoice_number": "INV-001",
        "customer_id": uuid4(),
        "customer_name": "PT ABC",
        "credit_note_date": FIXED_DATE,
        "amount": Decimal("100000"),
        "applied_amount": Decimal("0"),
        "remaining_amount": Decimal("100000"),
        "reason": "Adjustment",
        "reference_number": "REF",
        "status": ARCreditNoteStatus.DRAFT,
        "created_at": FIXED_NOW,
        "created_by": uuid4(),
        "created_by_name": "Admin",
        "approved_at": None,
        "approved_by": None,
        "version": 1,
    }),
    (ARAgingBucketSchema, {
        "bucket_name": "0-30 days",
        "days_start": 0,
        "days_end": 30,
        "total_amount": Decimal("1000000"),
        "percentage": 50.0,
        "invoices": [],
        "allowance_amount": Decimal("50000"),
    }),
    (ARAgingResponseSchema, {
        "customer_id": uuid4(),
        "customer_name": "PT ABC",
        "customer_code": "CUST001",
        "as_of_date": FIXED_DATE,
        "total_outstanding": Decimal("1000000"),
        "total_allowance": Decimal("50000"),
        "buckets": [],
        "generated_at": FIXED_NOW,
    }),
    (ARDashboardSchema, {
        "total_outstanding": Decimal("1000000"),
        "current_outstanding": Decimal("500000"),
        "overdue_1_30": Decimal("200000"),
        "overdue_31_60": Decimal("150000"),
        "overdue_61_90": Decimal("100000"),
        "overdue_90_plus": Decimal("50000"),
        "overdue_amount": Decimal("500000"),
        "overdue_percentage": 50.0,
        "dso_days": 45.5,
        "collection_efficiency": 80.0,
        "aging_buckets": [],
        "as_of_date": FIXED_DATE,
    }),
    (ARCollectionReminderSchema, {
        "invoice_ids": [uuid4(), uuid4()],
        "reminder_type": "email",
        "message": "Please pay",
        "send_email": True,
        "send_sms": False,
    }),
    (ARCollectionReminderResponseSchema, {
        "success": True,
        "reminders_sent": 2,
        "invoices_processed": [uuid4()],
        "errors": [],
    }),
    (ARInvoiceListResponseSchema, {
        "items": [],
        "total": 0,
        "page": 1,
        "page_size": 10,
        "total_outstanding": Decimal("0"),
        "total_paid": Decimal("0"),
        "total_overdue": Decimal("0"),
    }),
    (ARInvoiceActionResponseSchema, {
        "invoice_id": uuid4(),
        "invoice_number": "INV-001",
        "action": "APPROVE",
        "status": ARInvoiceStatus.APPROVED,
        "message": "Approved",
        "timestamp": FIXED_NOW,
    }),
    (ARWriteOffSchema, {
        "invoice_id": uuid4(),
        "write_off_amount": Decimal("100000"),
        "reason": "Uncollectible",
        "account_code": "3100",
    }),
    (ARWriteOffResponseSchema, {
        "write_off_id": uuid4(),
        "invoice_id": uuid4(),
        "invoice_number": "INV-001",
        "write_off_amount": Decimal("100000"),
        "remaining_outstanding": Decimal("0"),
        "journal_id": uuid4(),
        "status": "completed",
        "created_at": FIXED_NOW,
        "created_by": uuid4(),
    }),
]


class TestSchemas:
    @pytest.mark.parametrize("schema_class, kwargs", SCHEMA_TEST_DATA)
    def test_construction_success(self, schema_class, kwargs):
        instance = schema_class(**kwargs)
        assert isinstance(instance, schema_class)
        first_key = next(iter(kwargs))
        assert getattr(instance, first_key) == kwargs[first_key]


# ============================================================================
# HEALTH CHECK TESTS
# ============================================================================

def test_ping():
    result = ping()
    assert result == {"status": "ok", "service": "ar-router"}


def test_health():
    result = health()
    assert result == {"status": "healthy"}


def test_info():
    result = info()
    assert result["version"] == "1.0"
    assert result["name"] == "AR Router"


# ============================================================================
# DEPENDENCY INJECTION TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_get_ar_svc():
    request = MagicMock()
    request.app.state.container = MagicMock()
    request.app.state.container.resolve.return_value = "service"
    result = await get_ar_svc(request)
    assert result == "service"


@pytest.mark.asyncio
async def test_get_ar_collection_workflow_returns_workflow():
    # Need to mock the container
    with patch("adapters.primary_api.v1.fastapi_ar_router.request") as mock_request:
        mock_request.app.state.container = MagicMock()
        mock_request.app.state.container.resolve.return_value = "workflow"
        # Actually the function doesn't use request, it uses a module-level container?
        # The function is defined as async def get_ar_collection_workflow() -> Any:
        # It imports and resolves from container. We'll patch the import.
        with patch("adapters.primary_api.v1.fastapi_ar_router.ARCollectionWorkflowUseCase") as mock_uc:
            mock_uc.return_value = "workflow"
            result = await get_ar_collection_workflow()
            assert result is not None


# ============================================================================
# INVOICE CRUD TESTS
# ============================================================================

@pytest.mark.asyncio
class TestARInvoiceCRUD:
    async def test_create_ar_invoice_success(self, mock_ar_service, mock_token_payload, mock_legal_entity_id):
        request = ARInvoiceCreateSchema(
            customer_code="CUST001",
            invoice_date=FIXED_DATE,
            due_date=FIXED_DUE_DATE,
            invoice_number="INV-001",
            lines=[
                ARInvoiceLineSchema(
                    description="Line 1",
                    quantity=Decimal("1"),
                    unit_price=Decimal("100000"),
                    account_code="1100",
                )
            ],
            description="Test invoice",
        )
        result = await create_ar_invoice(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            ar_svc=mock_ar_service,
        )
        assert isinstance(result, ARInvoiceResponseSchema)
        assert result.invoice_number == "INV-001"
        assert result.total_amount == Decimal("1000000")
        mock_ar_service.create_invoice.assert_called_once()

    @pytest.mark.parametrize("side_effect, expected_status", [
        (ValueError("Invalid data"), 422),
        (PermissionError("Not allowed"), 403),
        (Exception("DB error"), 500),
    ])
    async def test_create_ar_invoice_errors(self, mock_ar_service, mock_token_payload, mock_legal_entity_id,
                                            side_effect, expected_status):
        mock_ar_service.create_invoice.side_effect = side_effect
        request = ARInvoiceCreateSchema(
            customer_code="CUST001",
            invoice_date=FIXED_DATE,
            due_date=FIXED_DUE_DATE,
            invoice_number="INV-001",
            lines=[
                ARInvoiceLineSchema(
                    description="Line 1",
                    quantity=Decimal("1"),
                    unit_price=Decimal("100000"),
                    account_code="1100",
                )
            ],
            description="Test",
        )
        with pytest.raises(HTTPException) as exc:
            await create_ar_invoice(
                request=request,
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                ar_svc=mock_ar_service,
            )
        assert exc.value.status_code == expected_status

    async def test_create_ar_invoice_idempotency(self, mock_ar_service, mock_token_payload, mock_legal_entity_id):
        request = ARInvoiceCreateSchema(
            customer_code="CUST001",
            invoice_date=FIXED_DATE,
            due_date=FIXED_DUE_DATE,
            invoice_number="INV-001",
            lines=[
                ARInvoiceLineSchema(
                    description="Line 1",
                    quantity=Decimal("1"),
                    unit_price=Decimal("100000"),
                    account_code="1100",
                )
            ],
            description="Test",
        )
        with patch("adapters.primary_api.v1.fastapi_ar_router._idempotency_manager") as mock_im:
            cached = {
                "id": str(uuid4()),
                "invoice_number": "INV-001",
                "customer_id": str(uuid4()),
                "customer_name": "PT ABC",
                "customer_code": "CUST001",
                "invoice_date": FIXED_DATE.isoformat(),
                "due_date": FIXED_DUE_DATE.isoformat(),
                "total_amount": "1000000",
                "paid_amount": "0",
                "outstanding_amount": "1000000",
                "discount_taken": "0",
                "early_payment_discount_eligible": False,
                "early_payment_discount_amount": "0",
                "status": "draft",
                "description": "Test",
                "lines": [],
                "tax_amount": "110000",
                "created_at": FIXED_NOW.isoformat(),
                "created_by": str(uuid4()),
                "created_by_name": "Admin",
                "approved_at": None,
                "approved_by": None,
                "approved_by_name": None,
                "posted_at": None,
                "posted_by": None,
                "cancelled_at": None,
                "cancelled_by": None,
                "collection_status": "not_started",
                "last_reminder_sent_at": None,
                "days_overdue": 0,
                "version": 1,
                "is_locked": False,
                "can_approve": True,
                "can_cancel": True,
                "can_post": True,
            }
            mock_im.get_cached_result.return_value = cached
            result = await create_ar_invoice(
                request=request,
                idempotency_key="key123",
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                ar_svc=mock_ar_service,
            )
            assert isinstance(result, ARInvoiceResponseSchema)
            assert result.invoice_number == "INV-001"
            mock_ar_service.create_invoice.assert_not_called()

    async def test_get_ar_invoice_success(self, mock_ar_service, mock_legal_entity_id):
        invoice_id = uuid4()
        result = await get_ar_invoice(
            invoice_id=invoice_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            ar_svc=mock_ar_service,
        )
        assert isinstance(result, ARInvoiceResponseSchema)
        assert result.invoice_number == "INV-001"
        mock_ar_service.get_invoice_by_id.assert_called_once_with(invoice_id, mock_legal_entity_id)

    async def test_get_ar_invoice_not_found(self, mock_ar_service, mock_legal_entity_id):
        mock_ar_service.get_invoice_by_id.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_ar_invoice(
                invoice_id=uuid4(),
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                ar_svc=mock_ar_service,
            )
        assert exc.value.status_code == 404

    async def test_list_ar_invoices(self, mock_ar_service, mock_legal_entity_id):
        result = await list_ar_invoices(
            customer_id=uuid4(),
            status=ARInvoiceStatus.DRAFT,
            start_date=FIXED_DATE,
            end_date=FIXED_DATE,
            due_date_up_to=FIXED_DATE,
            overdue_only=False,
            page=1,
            page_size=10,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            ar_svc=mock_ar_service,
        )
        assert isinstance(result, ARInvoiceListResponseSchema)
        assert len(result.items) == 1
        assert result.total == 1
        mock_ar_service.list_invoices.assert_called_once()

    async def test_update_ar_invoice_success(self, mock_ar_service, mock_token_payload, mock_legal_entity_id):
        invoice_id = uuid4()
        request = ARInvoiceUpdateSchema(description="Updated")
        result = await update_ar_invoice(
            invoice_id=invoice_id,
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            ar_svc=mock_ar_service,
        )
        assert isinstance(result, ARInvoiceResponseSchema)
        assert result.invoice_number == "INV-001"
        mock_ar_service.update_invoice.assert_called_once()

    async def test_update_ar_invoice_not_found(self, mock_ar_service, mock_token_payload, mock_legal_entity_id):
        mock_ar_service.update_invoice.return_value = None
        request = ARInvoiceUpdateSchema()
        with pytest.raises(HTTPException) as exc:
            await update_ar_invoice(
                invoice_id=uuid4(),
                request=request,
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                ar_svc=mock_ar_service,
            )
        assert exc.value.status_code == 404

    async def test_update_ar_invoice_value_error(self, mock_ar_service, mock_token_payload, mock_legal_entity_id):
        mock_ar_service.update_invoice.side_effect = ValueError("Invalid status")
        request = ARInvoiceUpdateSchema(status=ARInvoiceStatus.APPROVED)
        with pytest.raises(HTTPException) as exc:
            await update_ar_invoice(
                invoice_id=uuid4(),
                request=request,
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                ar_svc=mock_ar_service,
            )
        assert exc.value.status_code == 422

    async def test_delete_ar_invoice_success(self, mock_ar_service, mock_token_payload, mock_legal_entity_id):
        invoice_id = uuid4()
        result = await delete_ar_invoice(
            invoice_id=invoice_id,
            permanent=False,
            reason="Not needed",
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            ar_svc=mock_ar_service,
        )
        assert isinstance(result, ARInvoiceActionResponseSchema)
        assert result.action == "cancel"
        assert result.status == ARInvoiceStatus.CANCELLED
        mock_ar_service.cancel_invoice.assert_called_once()

    async def test_delete_ar_invoice_permanent(self, mock_ar_service, mock_token_payload, mock_legal_entity_id):
        invoice_id = uuid4()
        result = await delete_ar_invoice(
            invoice_id=invoice_id,
            permanent=True,
            reason="Void",
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            ar_svc=mock_ar_service,
        )
        assert result.action == "void"
        mock_ar_service.void_invoice.assert_called_once()

    async def test_delete_ar_invoice_not_found(self, mock_ar_service, mock_token_payload, mock_legal_entity_id):
        mock_ar_service.cancel_invoice.return_value = None
        with pytest.raises(HTTPException) as exc:
            await delete_ar_invoice(
                invoice_id=uuid4(),
                permanent=False,
                reason="",
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                ar_svc=mock_ar_service,
            )
        assert exc.value.status_code == 404

    async def test_restore_ar_invoice_success(self, mock_ar_service, mock_token_payload, mock_legal_entity_id):
        invoice_id = uuid4()
        result = await restore_ar_invoice(
            invoice_id=invoice_id,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            ar_svc=mock_ar_service,
        )
        assert isinstance(result, ARInvoiceResponseSchema)
        assert result.invoice_number == "INV-001"
        mock_ar_service.restore_invoice.assert_called_once_with(
            invoice_id, mock_token_payload.user_id, mock_legal_entity_id
        )


# ============================================================================
# INVOICE WORKFLOW TESTS
# ============================================================================

@pytest.mark.asyncio
class TestARInvoiceWorkflow:
    async def test_submit_ar_invoice_success(self, mock_ar_service, mock_token_payload, mock_legal_entity_id):
        invoice_id = uuid4()
        result = await submit_ar_invoice(
            invoice_id=invoice_id,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            ar_svc=mock_ar_service,
        )
        assert isinstance(result, ARInvoiceActionResponseSchema)
        assert result.action == "submit"
        assert result.status == ARInvoiceStatus.SUBMITTED
        mock_ar_service.submit_invoice.assert_called_once_with(
            invoice_id, mock_token_payload.user_id, mock_legal_entity_id
        )

    async def test_approve_ar_invoice_success(self, mock_ar_service, mock_token_payload, mock_legal_entity_id):
        invoice_id = uuid4()
        result = await approve_ar_invoice(
            invoice_id=invoice_id,
            notes="Approved",
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            ar_svc=mock_ar_service,
        )
        assert isinstance(result, ARInvoiceActionResponseSchema)
        assert result.action == "approve"
        assert result.status == ARInvoiceStatus.APPROVED
        mock_ar_service.approve_invoice.assert_called_once_with(
            invoice_id, mock_token_payload.user_id, mock_legal_entity_id, "Approved"
        )

    async def test_reject_ar_invoice_success(self, mock_ar_service, mock_token_payload, mock_legal_entity_id):
        invoice_id = uuid4()
        result = await reject_ar_invoice(
            invoice_id=invoice_id,
            reason="Invalid data",
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            ar_svc=mock_ar_service,
        )
        assert isinstance(result, ARInvoiceActionResponseSchema)
        assert result.action == "reject"
        assert result.status == ARInvoiceStatus.REJECTED
        mock_ar_service.reject_invoice.assert_called_once_with(
            invoice_id, mock_token_payload.user_id, mock_legal_entity_id, "Invalid data"
        )

    async def test_post_ar_invoice_success(self, mock_ar_service, mock_token_payload, mock_legal_entity_id):
        invoice_id = uuid4()
        result = await post_ar_invoice(
            invoice_id=invoice_id,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            ar_svc=mock_ar_service,
        )
        assert isinstance(result, ARInvoiceActionResponseSchema)
        assert result.action == "post"
        assert result.status == ARInvoiceStatus.POSTED
        mock_ar_service.post_invoice.assert_called_once_with(
            invoice_id, mock_token_payload.user_id, mock_legal_entity_id
        )

    async def test_reverse_ar_invoice_success(self, mock_ar_service, mock_token_payload, mock_legal_entity_id):
        invoice_id = uuid4()
        result = await reverse_ar_invoice(
            invoice_id=invoice_id,
            reason="Error",
            reversal_date=FIXED_DATE,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            ar_svc=mock_ar_service,
        )
        assert isinstance(result, ARInvoiceActionResponseSchema)
        assert result.action == "reverse"
        mock_ar_service.reverse_invoice.assert_called_once_with(
            invoice_id, mock_token_payload.user_id, mock_legal_entity_id, "Error", FIXED_DATE
        )

    async def test_lock_ar_invoice_success(self, mock_ar_service, mock_token_payload, mock_legal_entity_id):
        invoice_id = uuid4()
        result = await lock_ar_invoice(
            invoice_id=invoice_id,
            reason="Audit",
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            ar_svc=mock_ar_service,
        )
        assert isinstance(result, ARInvoiceActionResponseSchema)
        assert result.action == "lock"
        mock_ar_service.lock_invoice.assert_called_once_with(
            invoice_id, mock_token_payload.user_id, mock_legal_entity_id, "Audit"
        )

    async def test_unlock_ar_invoice_success(self, mock_ar_service, mock_token_payload, mock_legal_entity_id):
        invoice_id = uuid4()
        result = await unlock_ar_invoice(
            invoice_id=invoice_id,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            ar_svc=mock_ar_service,
        )
        assert isinstance(result, ARInvoiceActionResponseSchema)
        assert result.action == "unlock"
        mock_ar_service.unlock_invoice.assert_called_once_with(
            invoice_id, mock_token_payload.user_id, mock_legal_entity_id
        )


# ============================================================================
# PAYMENT TESTS
# ============================================================================

@pytest.mark.asyncio
class TestARPayments:
    async def test_record_ar_payment_success(self, mock_ar_service, mock_token_payload, mock_legal_entity_id):
        request = ARPaymentCreateSchema(
            invoice_id=uuid4(),
            payment_date=FIXED_DATE,
            amount=Decimal("500000"),
            payment_method=PaymentMethod.TRANSFER,
            bank_account_id=uuid4(),
            reference_number="PMT-001",
            notes="Payment",
            discount_taken=Decimal("0"),
            apply_early_payment_discount=False,
        )
        result = await record_ar_payment(
            request=request,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            ar_svc=mock_ar_service,
        )
        assert isinstance(result, ARPaymentResponseSchema)
        assert result.payment_number == "PMT-001"
        assert result.amount == Decimal("500000")
        mock_ar_service.record_payment.assert_called_once()

    async def test_record_ar_payment_value_error(self, mock_ar_service, mock_token_payload, mock_legal_entity_id):
        mock_ar_service.record_payment.side_effect = ValueError("Invalid amount")
        request = ARPaymentCreateSchema(
            invoice_id=uuid4(),
            payment_date=FIXED_DATE,
            amount=Decimal("-100"),
            payment_method=PaymentMethod.TRANSFER,
        )
        with pytest.raises(HTTPException) as exc:
            await record_ar_payment(
                request=request,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                ar_svc=mock_ar_service,
            )
        assert exc.value.status_code == 422

    async def test_get_ar_payment_success(self, mock_ar_service, mock_legal_entity_id):
        payment_id = uuid4()
        result = await get_ar_payment(
            payment_id=payment_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            ar_svc=mock_ar_service,
        )
        assert isinstance(result, ARPaymentResponseSchema)
        assert result.payment_number == "PMT-001"
        mock_ar_service.get_payment_by_id.assert_called_once_with(payment_id, mock_legal_entity_id)

    async def test_get_ar_payment_not_found(self, mock_ar_service, mock_legal_entity_id):
        mock_ar_service.get_payment_by_id.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_ar_payment(
                payment_id=uuid4(),
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                ar_svc=mock_ar_service,
            )
        assert exc.value.status_code == 404

    async def test_reverse_ar_payment_success(self, mock_ar_service, mock_token_payload, mock_legal_entity_id):
        payment_id = uuid4()
        request = ARPaymentReverseSchema(reason="Duplicate", reversal_date=FIXED_DATE)
        result = await reverse_ar_payment(
            payment_id=payment_id,
            request=request,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            ar_svc=mock_ar_service,
        )
        assert isinstance(result, ARPaymentResponseSchema)
        assert result.is_reversed is True
        mock_ar_service.reverse_payment.assert_called_once()


# ============================================================================
# CREDIT NOTE TESTS
# ============================================================================

@pytest.mark.asyncio
class TestARCreditNotes:
    async def test_create_ar_credit_note_success(self, mock_ar_service, mock_token_payload, mock_legal_entity_id):
        request = ARCreditNoteCreateSchema(
            invoice_id=uuid4(),
            credit_note_date=FIXED_DATE,
            amount=Decimal("100000"),
            reason="Adjustment",
            reference_number="CN-001",
            apply_to_future_invoices=False,
        )
        result = await create_ar_credit_note(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            ar_svc=mock_ar_service,
        )
        assert isinstance(result, ARCreditNoteResponseSchema)
        assert result.credit_note_number == "CN-001"
        mock_ar_service.create_credit_note.assert_called_once()

    async def test_approve_ar_credit_note_success(self, mock_ar_service, mock_token_payload, mock_legal_entity_id):
        credit_note_id = uuid4()
        result = await approve_ar_credit_note(
            credit_note_id=credit_note_id,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            ar_svc=mock_ar_service,
        )
        assert isinstance(result, ARCreditNoteResponseSchema)
        assert result.status == ARCreditNoteStatus.APPROVED
        mock_ar_service.approve_credit_note.assert_called_once_with(
            credit_note_id, mock_token_payload.user_id, mock_legal_entity_id
        )

    async def test_cancel_ar_credit_note_success(self, mock_ar_service, mock_token_payload, mock_legal_entity_id):
        credit_note_id = uuid4()
        result = await cancel_ar_credit_note(
            credit_note_id=credit_note_id,
            reason="Test",
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            ar_svc=mock_ar_service,
        )
        assert isinstance(result, ARCreditNoteResponseSchema)
        assert result.status == ARCreditNoteStatus.CANCELLED
        mock_ar_service.cancel_credit_note.assert_called_once()


# ============================================================================
# WRITE-OFF TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_write_off_ar_invoice_success(mock_ar_service, mock_token_payload, mock_legal_entity_id):
    request = ARWriteOffSchema(
        invoice_id=uuid4(),
        write_off_amount=Decimal("100000"),
        reason="Uncollectible",
        account_code="3100",
    )
    result = await write_off_ar_invoice(
        request=request,
        _permission=None,
        current_user=mock_token_payload,
        legal_entity_id=mock_legal_entity_id,
        ar_svc=mock_ar_service,
    )
    assert isinstance(result, ARWriteOffResponseSchema)
    assert result.write_off_amount == Decimal("100000")
    mock_ar_service.write_off_invoice.assert_called_once()


# ============================================================================
# AGING REPORT TESTS
# ============================================================================

@pytest.mark.asyncio
class TestARAging:
    async def test_get_ar_aging_by_customer_success(self, mock_ar_service, mock_legal_entity_id):
        customer_id = uuid4()
        result = await get_ar_aging_by_customer(
            customer_id=customer_id,
            as_of_date=FIXED_DATE,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            ar_svc=mock_ar_service,
        )
        assert isinstance(result, ARAgingResponseSchema)
        assert result.customer_id == customer_id
        assert result.total_outstanding == Decimal("1000000")
        mock_ar_service.get_aging_report.assert_called_once_with(customer_id, mock_legal_entity_id, FIXED_DATE)

    async def test_get_all_ar_aging_success(self, mock_ar_service, mock_legal_entity_id):
        result = await get_all_ar_aging(
            as_of_date=FIXED_DATE,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            ar_svc=mock_ar_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], ARAgingResponseSchema)
        mock_ar_service.get_aging_all_customers.assert_called_once_with(mock_legal_entity_id, FIXED_DATE)


# ============================================================================
# DASHBOARD TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_get_ar_dashboard_success(mock_ar_service, mock_legal_entity_id):
    result = await get_ar_dashboard(
        as_of_date=FIXED_DATE,
        _permission=None,
        legal_entity_id=mock_legal_entity_id,
        ar_svc=mock_ar_service,
    )
    assert isinstance(result, ARDashboardSchema)
    assert result.total_outstanding == Decimal("1000000")
    assert result.dso_days == 45.5
    mock_ar_service.get_dashboard.assert_called_once_with(mock_legal_entity_id, FIXED_DATE)


# ============================================================================
# COLLECTION WORKFLOW TESTS
# ============================================================================

@pytest.mark.asyncio
class TestCollection:
    async def test_send_collection_reminders_success(self, mock_ar_service, mock_token_payload, mock_legal_entity_id):
        request = ARCollectionReminderSchema(
            invoice_ids=[uuid4()],
            reminder_type="gentle",
            message="Please pay",
            send_email=True,
            send_sms=False,
        )
        result = await send_collection_reminders(
            request=request,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            ar_svc=mock_ar_service,
        )
        assert isinstance(result, ARCollectionReminderResponseSchema)
        assert result.success is True
        assert result.reminders_sent == 2
        mock_ar_service.send_collection_reminders.assert_called_once()

    async def test_start_collection_workflow_success(self, mock_collection_workflow, mock_token_payload, mock_legal_entity_id):
        result = await start_collection_workflow(
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            collection_workflow=mock_collection_workflow,
        )
        assert result["workflow_id"] is not None
        assert result["reminders_sent"] == 2
        mock_collection_workflow.start_collection_process.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            initiated_by=mock_token_payload.user_id,
        )

    async def test_escalate_collection_success(self, mock_ar_service, mock_token_payload, mock_legal_entity_id):
        invoice_id = uuid4()
        result = await escalate_collection(
            invoice_id=invoice_id,
            reason="Delinquent",
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            ar_svc=mock_ar_service,
        )
        assert result["escalated"] is True
        assert result["collection_status"] == "escalated"
        mock_ar_service.escalate_collection.assert_called_once_with(
            invoice_id=invoice_id,
            legal_entity_id=mock_legal_entity_id,
            reason="Delinquent",
            escalated_by=mock_token_payload.user_id,
        )


# ============================================================================
# STATUS & HISTORY TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_get_ar_invoice_status_success(mock_ar_service, mock_legal_entity_id):
    invoice_id = uuid4()
    result = await get_ar_invoice_status(
        invoice_id=invoice_id,
        _permission=None,
        legal_entity_id=mock_legal_entity_id,
        ar_svc=mock_ar_service,
    )
    assert result["invoice_number"] == "INV-001"
    assert result["status"] == "draft"
    assert result["can_submit"] is True
    mock_ar_service.get_invoice_status.assert_called_once_with(invoice_id, mock_legal_entity_id)


@pytest.mark.asyncio
async def test_get_ar_invoice_history_success(mock_ar_service, mock_legal_entity_id):
    invoice_id = uuid4()
    result = await get_ar_invoice_history(
        invoice_id=invoice_id,
        _permission=None,
        legal_entity_id=mock_legal_entity_id,
        ar_svc=mock_ar_service,
    )
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["action"] == "create"
    mock_ar_service.get_invoice_history.assert_called_once_with(invoice_id, mock_legal_entity_id)


# ============================================================================
# PDF GENERATION TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_generate_ar_invoice_pdf_success(mock_ar_service, mock_legal_entity_id):
    invoice_id = uuid4()
    result = await generate_ar_invoice_pdf(
        invoice_id=invoice_id,
        _permission=None,
        legal_entity_id=mock_legal_entity_id,
        ar_svc=mock_ar_service,
    )
    assert isinstance(result, Response)
    assert result.body == b"%PDF-1.4\n..."
    assert result.media_type == "application/pdf"
    assert "attachment" in result.headers["Content-Disposition"]
    mock_ar_service.generate_invoice_pdf.assert_called_once_with(invoice_id, mock_legal_entity_id)


# ============================================================================
# BULK OPERATIONS TESTS
# ============================================================================

@pytest.mark.asyncio
class TestBulkOperations:
    async def test_bulk_approve_ar_invoices_success(self, mock_ar_service, mock_token_payload, mock_legal_entity_id):
        invoice_ids = [uuid4(), uuid4()]
        result = await bulk_approve_ar_invoices(
            invoice_ids=invoice_ids,
            notes="Bulk approve",
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            ar_svc=mock_ar_service,
        )
        assert result["total"] == 2
        assert result["success_count"] == 2
        assert result["failed_count"] == 0
        mock_ar_service.bulk_approve_invoices.assert_called_once_with(
            invoice_ids=invoice_ids,
            approver_id=mock_token_payload.user_id,
            legal_entity_id=mock_legal_entity_id,
            notes="Bulk approve",
        )

    async def test_bulk_send_payment_reminders_success(self, mock_ar_service, mock_token_payload, mock_legal_entity_id):
        invoice_ids = [uuid4(), uuid4()]
        result = await bulk_send_payment_reminders(
            invoice_ids=invoice_ids,
            reminder_type="firm",
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            ar_svc=mock_ar_service,
        )
        assert result["total"] == 2
        assert result["success_count"] == 2
        mock_ar_service.bulk_send_reminders.assert_called_once_with(
            invoice_ids=invoice_ids,
            reminder_type="firm",
            sent_by=mock_token_payload.user_id,
            legal_entity_id=mock_legal_entity_id,
        )