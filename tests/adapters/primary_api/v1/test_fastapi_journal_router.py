# tests/adapters/primary_api/v1/test_fastapi_journal_router.py
"""
Comprehensive tests for adapters/primary_api/v1/fastapi_journal_router.py.
Covers enums, schemas, validators, dependency injections, and all route handlers.
All validator functions are explicitly invoked to satisfy coverage analysis.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from adapters.primary_api.v1.fastapi_journal_router import (
    IdempotencyManager,
    JournalActionResponseSchema,
    JournalApproveSchema,
    JournalCreateSchema,
    JournalLineSchema,
    JournalListResponseSchema,
    JournalRejectSchema,
    JournalResponseSchema,
    JournalReverseSchema,
    JournalSource,
    JournalStatus,
    JournalType,
    JournalUpdateSchema,
    approve_journal,
    cancel_journal,
    create_journal,
    export_journals,
    get_approve_journal_use_case,
    get_journal,
    get_journal_by_number,
    get_journal_history,
    get_journal_ledger_entries,
    get_journal_service,
    get_journal_status,
    get_post_journal_use_case,
    get_reverse_journal_use_case,
    health,
    info,
    list_journals,
    lock_journal,
    ping,
    post_journal,
    reject_journal,
    restore_journal,
    reverse_journal,
    submit_journal,
    unlock_journal,
    unpost_journal,
    update_journal,
    validate_balance,
    validate_journal,
)

# ============================================================================
# IdempotencyManager
# ============================================================================

class TestIdempotencyManager:
    def test_construction(self):
        instance = IdempotencyManager()
        assert isinstance(instance, IdempotencyManager)

    def test_get_cached_result_returns_none_for_missing_key(self):
        instance = IdempotencyManager()
        result = instance.get_cached_result("non_existent_key", "method")
        assert result is None

    def test_cache_result_returns_true_on_success(self):
        instance = IdempotencyManager()
        result = instance.cache_result("key", "method", {"data": "value"})
        assert result is True


# ============================================================================
# Enums
# ============================================================================

class TestJournalStatus:
    def test_members_exist(self):
        assert hasattr(JournalStatus, 'DRAFT')
        assert hasattr(JournalStatus, 'PENDING')
        assert hasattr(JournalStatus, 'SUBMITTED')
        assert hasattr(JournalStatus, 'VALIDATED')
        assert hasattr(JournalStatus, 'APPROVED')
        assert hasattr(JournalStatus, 'REJECTED')
        assert hasattr(JournalStatus, 'POSTED')
        assert hasattr(JournalStatus, 'REVERSED')
        assert hasattr(JournalStatus, 'CANCELLED')
        assert hasattr(JournalStatus, 'VOID')
        assert hasattr(JournalStatus, 'CLOSED')
        assert hasattr(JournalStatus, 'ARCHIVED')
        assert hasattr(JournalStatus, 'LOCKED')
        assert hasattr(JournalStatus, 'ERROR')

    def test_member_is_instance(self):
        assert isinstance(JournalStatus.DRAFT, JournalStatus)


class TestJournalType:
    def test_members_exist(self):
        assert hasattr(JournalType, 'GENERAL')
        assert hasattr(JournalType, 'ADJUSTMENT')
        assert hasattr(JournalType, 'CLOSING')
        assert hasattr(JournalType, 'REVERSING')
        assert hasattr(JournalType, 'CORRECTION')
        assert hasattr(JournalType, 'TRANSFER')
        assert hasattr(JournalType, 'ACCRUAL')
        assert hasattr(JournalType, 'DEFERRAL')
        assert hasattr(JournalType, 'DEPRECIATION')
        assert hasattr(JournalType, 'AMORTIZATION')
        assert hasattr(JournalType, 'PAYROLL')
        assert hasattr(JournalType, 'TAX')
        assert hasattr(JournalType, 'INTERCOMPANY')
        assert hasattr(JournalType, 'BUDGET')

    def test_member_is_instance(self):
        assert isinstance(JournalType.GENERAL, JournalType)


class TestJournalSource:
    def test_members_exist(self):
        assert hasattr(JournalSource, 'MANUAL')
        assert hasattr(JournalSource, 'AP_INVOICE')
        assert hasattr(JournalSource, 'AR_INVOICE')
        assert hasattr(JournalSource, 'PAYMENT')
        assert hasattr(JournalSource, 'RECEIPT')
        assert hasattr(JournalSource, 'BANK_RECONCILIATION')
        assert hasattr(JournalSource, 'FIXED_ASSET')
        assert hasattr(JournalSource, 'INVENTORY')
        assert hasattr(JournalSource, 'PAYROLL')
        assert hasattr(JournalSource, 'TAX')
        assert hasattr(JournalSource, 'MANUFACTURING')
        assert hasattr(JournalSource, 'PROJECT')
        assert hasattr(JournalSource, 'SYSTEM')
        assert hasattr(JournalSource, 'IMPORT')

    def test_member_is_instance(self):
        assert isinstance(JournalSource.MANUAL, JournalSource)


# ============================================================================
# Pydantic Schemas & Validators
# ============================================================================

class TestJournalLineSchema:
    def test_construction_success(self):
        kwargs = {
            "account_code": "1100",
            "debit_amount": Decimal("1000"),
            "credit_amount": Decimal("0"),
            "cost_center": "CC001",
            "department": "DEPT01",
            "project_id": uuid4(),
            "description": "Test line",
            "tax_id": uuid4(),
        }
        instance = JournalLineSchema(**kwargs)
        assert isinstance(instance, JournalLineSchema)
        assert instance.account_code == kwargs["account_code"]

    # ---- Explicit call to validate_amount_non_negative ----
    def test_validate_amount_non_negative_direct_call_valid(self):
        # Direct invocation of the classmethod validator
        result = JournalLineSchema.validate_amount_non_negative(Decimal("100"))
        assert result == Decimal("100")

    def test_validate_amount_non_negative_direct_call_invalid(self):
        with pytest.raises(ValueError, match="Amount cannot be negative"):
            JournalLineSchema.validate_amount_non_negative(Decimal("-1"))

    # ---- validate_amount_non_negative via Pydantic (already covered, but keep) ----
    def test_validate_amount_non_negative_raises_on_negative_debit(self):
        with pytest.raises(ValidationError) as exc_info:
            JournalLineSchema(
                account_code="1100",
                debit_amount=Decimal("-100"),
                credit_amount=Decimal("0"),
            )
        errors = exc_info.value.errors()
        assert any("Amount cannot be negative" in e["msg"] for e in errors)

    def test_validate_amount_non_negative_raises_on_negative_credit(self):
        with pytest.raises(ValidationError) as exc_info:
            JournalLineSchema(
                account_code="1100",
                debit_amount=Decimal("0"),
                credit_amount=Decimal("-100"),
            )
        errors = exc_info.value.errors()
        assert any("Amount cannot be negative" in e["msg"] for e in errors)

    # ---- Explicit call to validate_one_amount ----
    def test_validate_one_amount_direct_call_valid(self):
        instance = JournalLineSchema(
            account_code="1100",
            debit_amount=Decimal("100"),
            credit_amount=Decimal("0"),
        )
        # Call the model_validator method directly
        result = instance.validate_one_amount()
        assert result is instance  # returns self

    def test_validate_one_amount_direct_call_invalid_both_nonzero(self):
        instance = JournalLineSchema(
            account_code="1100",
            debit_amount=Decimal("100"),
            credit_amount=Decimal("100"),
        )
        with pytest.raises(ValueError, match="cannot have both debit and credit amounts"):
            instance.validate_one_amount()

    def test_validate_one_amount_direct_call_invalid_both_zero(self):
        instance = JournalLineSchema(
            account_code="1100",
            debit_amount=Decimal("0"),
            credit_amount=Decimal("0"),
        )
        with pytest.raises(ValueError, match="must have either debit or credit amount"):
            instance.validate_one_amount()

    # ---- validate_one_amount via Pydantic (keep) ----
    def test_validate_one_amount_raises_when_both_debit_and_credit_set(self):
        with pytest.raises(ValidationError) as exc_info:
            JournalLineSchema(
                account_code="1100",
                debit_amount=Decimal("100"),
                credit_amount=Decimal("100"),
            )
        errors = exc_info.value.errors()
        assert any("cannot have both debit and credit amounts" in e["msg"] for e in errors)

    def test_validate_one_amount_raises_when_both_zero(self):
        with pytest.raises(ValidationError) as exc_info:
            JournalLineSchema(
                account_code="1100",
                debit_amount=Decimal("0"),
                credit_amount=Decimal("0"),
            )
        errors = exc_info.value.errors()
        assert any("must have either debit or credit amount" in e["msg"] for e in errors)


class TestJournalCreateSchema:
    def test_construction_success(self):
        line = JournalLineSchema(
            account_code="1100",
            debit_amount=Decimal("100"),
            credit_amount=Decimal("0"),
        )
        line2 = JournalLineSchema(
            account_code="2100",
            debit_amount=Decimal("0"),
            credit_amount=Decimal("100"),
        )
        kwargs = {
            "journal_date": date.today(),
            "description": "Test journal",
            "journal_type": JournalType.GENERAL,
            "lines": [line, line2],
            "reference_number": "REF-001",
            "source_type": JournalSource.MANUAL,
            "source_id": "SRC-001",
            "notes": "Test notes",
            "attachment_ids": [uuid4()],
        }
        instance = JournalCreateSchema(**kwargs)
        assert isinstance(instance, JournalCreateSchema)

    # ---- Explicit call to validate_double_entry ----
    def test_validate_double_entry_direct_call_valid(self):
        line1 = JournalLineSchema(
            account_code="1100",
            debit_amount=Decimal("100"),
            credit_amount=Decimal("0"),
        )
        line2 = JournalLineSchema(
            account_code="2100",
            debit_amount=Decimal("0"),
            credit_amount=Decimal("100"),
        )
        schema = JournalCreateSchema(
            journal_date=date.today(),
            description="Balanced",
            journal_type=JournalType.GENERAL,
            lines=[line1, line2],
        )
        # Direct call to the model_validator
        result = schema.validate_double_entry()
        assert result is schema

    def test_validate_double_entry_direct_call_invalid(self):
        line1 = JournalLineSchema(
            account_code="1100",
            debit_amount=Decimal("100"),
            credit_amount=Decimal("0"),
        )
        line2 = JournalLineSchema(
            account_code="2100",
            debit_amount=Decimal("0"),
            credit_amount=Decimal("90"),
        )
        schema = JournalCreateSchema(
            journal_date=date.today(),
            description="Unbalanced",
            journal_type=JournalType.GENERAL,
            lines=[line1, line2],
        )
        with pytest.raises(ValueError, match="Total debit .* must equal total credit"):
            schema.validate_double_entry()

    # ---- validate_double_entry via Pydantic (keep) ----
    def test_validate_double_entry_raises_when_unbalanced(self):
        line1 = JournalLineSchema(
            account_code="1100",
            debit_amount=Decimal("100"),
            credit_amount=Decimal("0"),
        )
        line2 = JournalLineSchema(
            account_code="2100",
            debit_amount=Decimal("0"),
            credit_amount=Decimal("90"),
        )
        with pytest.raises(ValidationError) as exc_info:
            JournalCreateSchema(
                journal_date=date.today(),
                description="Unbalanced",
                journal_type=JournalType.GENERAL,
                lines=[line1, line2],
            )
        errors = exc_info.value.errors()
        assert any("Total debit (100.00) must equal total credit (90.00)" in e["msg"] for e in errors)

    def test_validate_double_entry_passes_when_balanced(self):
        line1 = JournalLineSchema(
            account_code="1100",
            debit_amount=Decimal("100"),
            credit_amount=Decimal("0"),
        )
        line2 = JournalLineSchema(
            account_code="2100",
            debit_amount=Decimal("0"),
            credit_amount=Decimal("100"),
        )
        schema = JournalCreateSchema(
            journal_date=date.today(),
            description="Balanced",
            journal_type=JournalType.GENERAL,
            lines=[line1, line2],
        )
        assert schema is not None


class TestJournalUpdateSchema:
    def test_construction_success(self):
        kwargs = {
            "journal_date": date.today(),
            "description": "Updated journal",
            "journal_type": JournalType.ADJUSTMENT,
            "lines": [MagicMock()],
            "reference_number": "REF-002",
            "notes": "Updated notes",
            "attachment_ids": [uuid4()],
        }
        instance = JournalUpdateSchema(**kwargs)
        assert isinstance(instance, JournalUpdateSchema)
        assert instance.journal_date == kwargs["journal_date"]


class TestJournalResponseSchema:
    def test_construction_success(self):
        journal_id = uuid4()
        kwargs = {
            "id": journal_id,
            "journal_number": "JRN-2026-001",
            "journal_date": date.today(),
            "description": "Test journal",
            "journal_type": JournalType.GENERAL,
            "status": JournalStatus.DRAFT,
            "total_debit": Decimal("1000"),
            "total_credit": Decimal("1000"),
            "reference_number": "REF-001",
            "source_type": JournalSource.MANUAL,
            "source_id": "SRC-001",
            "notes": "Test notes",
            "attachment_ids": [uuid4()],
            "created_by": uuid4(),
            "created_by_name": "admin",
            "created_at": datetime.now(UTC),
            "submitted_by": None,
            "submitted_at": None,
            "approved_by": None,
            "approved_by_name": None,
            "approved_at": None,
            "rejected_by": None,
            "rejected_at": None,
            "rejection_reason": None,
            "posted_by": None,
            "posted_by_name": None,
            "posted_at": None,
            "reversed_by": None,
            "reversed_at": None,
            "reversal_reason": None,
            "reversal_journal_id": None,
            "original_journal_id": None,
            "cancelled_by": None,
            "cancelled_at": None,
            "cancellation_reason": None,
            "is_locked": False,
            "is_balanced": True,
            "version": 1,
            "lines": [],
        }
        instance = JournalResponseSchema(**kwargs)
        assert isinstance(instance, JournalResponseSchema)
        assert instance.id == journal_id


class TestJournalActionResponseSchema:
    def test_construction_success(self):
        journal_id = uuid4()
        kwargs = {
            "journal_id": journal_id,
            "journal_number": "JRN-001",
            "action": "POST",
            "status": JournalStatus.POSTED,
            "message": "Journal posted successfully",
            "timestamp": datetime.now(UTC),
        }
        instance = JournalActionResponseSchema(**kwargs)
        assert isinstance(instance, JournalActionResponseSchema)
        assert instance.journal_id == journal_id


class TestJournalListResponseSchema:
    def test_construction_success(self):
        kwargs = {
            "items": [],
            "total": 0,
            "page": 1,
            "page_size": 10,
            "total_debit": Decimal("0"),
            "total_credit": Decimal("0"),
        }
        instance = JournalListResponseSchema(**kwargs)
        assert isinstance(instance, JournalListResponseSchema)
        assert instance.items == kwargs["items"]


class TestJournalApproveSchema:
    def test_construction_success(self):
        kwargs = {"notes": "Approved"}
        instance = JournalApproveSchema(**kwargs)
        assert isinstance(instance, JournalApproveSchema)
        assert instance.notes == kwargs["notes"]


class TestJournalRejectSchema:
    def test_construction_success(self):
        kwargs = {"reason": "Invalid entries"}
        instance = JournalRejectSchema(**kwargs)
        assert isinstance(instance, JournalRejectSchema)
        assert instance.reason == kwargs["reason"]


class TestJournalReverseSchema:
    def test_construction_success(self):
        kwargs = {
            "reversal_date": date.today(),
            "reason": "Correction needed",
            "post_immediately": True,
        }
        instance = JournalReverseSchema(**kwargs)
        assert isinstance(instance, JournalReverseSchema)
        assert instance.reversal_date == kwargs["reversal_date"]


# ============================================================================
# Validation helper
# ============================================================================

def test_validate_balance_returns_boolean():
    # balanced case
    result = validate_balance(debit=Decimal("100"), credit=Decimal("100"))
    assert result is True
    # unbalanced case
    result = validate_balance(debit=Decimal("100"), credit=Decimal("90"))
    assert result is False


# ============================================================================
# Dependency injections (all async)
# ============================================================================

@pytest.mark.asyncio
async def test_get_journal_service_returns_service():
    request = MagicMock()
    request.app.state.container = MagicMock()
    request.app.state.container.resolve = MagicMock(return_value="service")
    result = await get_journal_service(request=request)
    assert result == "service"


@pytest.mark.asyncio
async def test_get_post_journal_use_case_returns_use_case():
    request = MagicMock()
    request.app.state.container = MagicMock()
    request.app.state.container.resolve = MagicMock(return_value="use_case")
    result = await get_post_journal_use_case(request=request, idempotency_key="key")
    assert result == "use_case"


@pytest.mark.asyncio
async def test_get_approve_journal_use_case_returns_use_case():
    request = MagicMock()
    request.app.state.container = MagicMock()
    request.app.state.container.resolve = MagicMock(return_value="use_case")
    result = await get_approve_journal_use_case(request=request)
    assert result == "use_case"


@pytest.mark.asyncio
async def test_get_reverse_journal_use_case_returns_use_case():
    request = MagicMock()
    request.app.state.container = MagicMock()
    request.app.state.container.resolve = MagicMock(return_value="use_case")
    result = await get_reverse_journal_use_case(request=request)
    assert result == "use_case"


# ============================================================================
# Health / Ping / Info
# ============================================================================

def test_ping_returns_dict():
    result = ping()
    assert result == {"status": "ok", "service": "journal-router"}


def test_health_returns_dict():
    result = health()
    assert result == {"status": "healthy"}


def test_info_returns_dict():
    result = info()
    assert result == {"version": "1.0", "name": "Journal Router"}


# ============================================================================
# Route handlers (async) - proper mocking with AsyncMock
# ============================================================================

@pytest.fixture
def mock_journal_service():
    svc = AsyncMock()
    svc.create_journal = AsyncMock(return_value=MagicMock(
        id=uuid4(),
        journal_number="JRN-001",
        journal_date=date.today(),
        description="Test",
        journal_type="general",
        status="draft",
        total_debit=Decimal("100"),
        total_credit=Decimal("100"),
        reference_number=None,
        source_type="manual",
        source_id=None,
        notes=None,
        attachment_ids=[],
        created_by=uuid4(),
        created_by_name="Admin",
        created_at=datetime.now(UTC),
        submitted_by=None,
        submitted_at=None,
        approved_by=None,
        approved_by_name=None,
        approved_at=None,
        rejected_by=None,
        rejected_at=None,
        rejection_reason=None,
        posted_by=None,
        posted_by_name=None,
        posted_at=None,
        reversed_by=None,
        reversed_at=None,
        reversal_reason=None,
        reversal_journal_id=None,
        original_journal_id=None,
        cancelled_by=None,
        cancelled_at=None,
        cancellation_reason=None,
        is_locked=False,
        is_balanced=True,
        version=1,
        lines=[],
    ))
    svc.get_journal_by_id = AsyncMock(return_value=MagicMock(
        id=uuid4(),
        journal_number="JRN-001",
        journal_date=date.today(),
        description="Test",
        journal_type="general",
        status="draft",
        total_debit=Decimal("100"),
        total_credit=Decimal("100"),
        reference_number=None,
        source_type="manual",
        source_id=None,
        notes=None,
        attachment_ids=[],
        created_by=uuid4(),
        created_by_name="Admin",
        created_at=datetime.now(UTC),
        submitted_by=None,
        submitted_at=None,
        approved_by=None,
        approved_by_name=None,
        approved_at=None,
        rejected_by=None,
        rejected_at=None,
        rejection_reason=None,
        posted_by=None,
        posted_by_name=None,
        posted_at=None,
        reversed_by=None,
        reversed_at=None,
        reversal_reason=None,
        reversal_journal_id=None,
        original_journal_id=None,
        cancelled_by=None,
        cancelled_at=None,
        cancellation_reason=None,
        is_locked=False,
        is_balanced=True,
        version=1,
        lines=[],
    ))
    svc.update_journal = AsyncMock(return_value=svc.get_journal_by_id.return_value)
    svc.cancel_journal = AsyncMock(return_value=svc.get_journal_by_id.return_value)
    svc.restore_journal = AsyncMock(return_value=svc.get_journal_by_id.return_value)
    svc.submit_journal = AsyncMock(return_value=svc.get_journal_by_id.return_value)
    svc.reject_journal = AsyncMock(return_value=svc.get_journal_by_id.return_value)
    svc.unpost_journal = AsyncMock(return_value=svc.get_journal_by_id.return_value)
    svc.lock_journal = AsyncMock(return_value=svc.get_journal_by_id.return_value)
    svc.unlock_journal = AsyncMock(return_value=svc.get_journal_by_id.return_value)
    svc.list_journals = AsyncMock(return_value=MagicMock(
        items=[svc.get_journal_by_id.return_value],
        total=1,
        total_debit=Decimal("100"),
        total_credit=Decimal("100"),
    ))
    svc.validate_journal = AsyncMock(return_value=MagicMock(
        journal_number="JRN-001",
        is_valid=True,
        is_balanced=True,
        total_debit=Decimal("100"),
        total_credit=Decimal("100"),
        errors=[],
        warnings=[],
    ))
    svc.get_journal_status = AsyncMock(return_value=MagicMock(
        journal_number="JRN-001",
        status="draft",
        status_description="Draft",
        can_submit=True,
        can_approve=False,
        can_reject=False,
        can_post=False,
        can_reverse=False,
        can_cancel=True,
        is_locked=False,
        is_archived=False,
        submitted_by=None,
        submitted_at=None,
        approved_by=None,
        approved_at=None,
        posted_by=None,
        posted_at=None,
        approval_level=0,
    ))
    svc.get_journal_history = AsyncMock(return_value=[])
    svc.get_ledger_entries = AsyncMock(return_value=[])
    svc.export_journals = AsyncMock(return_value=b"csvdata")
    return svc


@pytest.fixture
def mock_use_case():
    uc = AsyncMock()
    uc.execute = AsyncMock(return_value=MagicMock(
        id=uuid4(),
        journal_number="JRN-001",
        status="approved",
    ))
    uc.get_journal = AsyncMock(return_value=MagicMock(
        total_debit=Decimal("100"),
        total_credit=Decimal("100"),
    ))
    return uc


@pytest.mark.asyncio
async def test_create_journal_success(mock_journal_service):
    request = JournalCreateSchema(
        journal_date=date.today(),
        description="Test",
        journal_type=JournalType.GENERAL,
        lines=[
            JournalLineSchema(account_code="1100", debit_amount=Decimal("100"), credit_amount=Decimal("0")),
            JournalLineSchema(account_code="2100", debit_amount=Decimal("0"), credit_amount=Decimal("100")),
        ],
    )
    result = await create_journal(
        request=request,
        idempotency_key=None,
        _permission=None,
        current_user=MagicMock(user_id=uuid4()),
        legal_entity_id=uuid4(),
        journal_service=mock_journal_service,
    )
    assert isinstance(result, JournalResponseSchema)
    assert result.journal_number == "JRN-001"
    mock_journal_service.create_journal.assert_called_once()


@pytest.mark.asyncio
async def test_create_journal_value_error_raises_422(mock_journal_service):
    mock_journal_service.create_journal.side_effect = ValueError("Invalid data")
    request = JournalCreateSchema(
        journal_date=date.today(),
        description="Test",
        journal_type=JournalType.GENERAL,
        lines=[
            JournalLineSchema(account_code="1100", debit_amount=Decimal("100"), credit_amount=Decimal("0")),
            JournalLineSchema(account_code="2100", debit_amount=Decimal("0"), credit_amount=Decimal("100")),
        ],
    )
    with pytest.raises(HTTPException) as exc:
        await create_journal(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=MagicMock(user_id=uuid4()),
            legal_entity_id=uuid4(),
            journal_service=mock_journal_service,
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_get_journal_success(mock_journal_service):
    journal_id = uuid4()
    result = await get_journal(
        journal_id=journal_id,
        _permission=None,
        legal_entity_id=uuid4(),
        journal_service=mock_journal_service,
    )
    assert isinstance(result, JournalResponseSchema)
    assert result.journal_number == "JRN-001"
    mock_journal_service.get_journal_by_id.assert_called_once_with(journal_id, uuid4())


@pytest.mark.asyncio
async def test_get_journal_not_found(mock_journal_service):
    mock_journal_service.get_journal_by_id.return_value = None
    with pytest.raises(HTTPException) as exc:
        await get_journal(
            journal_id=uuid4(),
            _permission=None,
            legal_entity_id=uuid4(),
            journal_service=mock_journal_service,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_journal_by_number_success(mock_journal_service):
    result = await get_journal_by_number(
        journal_number="JRN-001",
        _permission=None,
        legal_entity_id=uuid4(),
        journal_service=mock_journal_service,
    )
    assert isinstance(result, JournalResponseSchema)
    assert result.journal_number == "JRN-001"
    mock_journal_service.get_journal_by_number.assert_called_once()


@pytest.mark.asyncio
async def test_get_journal_by_number_not_found(mock_journal_service):
    mock_journal_service.get_journal_by_number.return_value = None
    with pytest.raises(HTTPException) as exc:
        await get_journal_by_number(
            journal_number="JRN-001",
            _permission=None,
            legal_entity_id=uuid4(),
            journal_service=mock_journal_service,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_journal_success(mock_journal_service):
    request = JournalUpdateSchema(description="Updated")
    result = await update_journal(
        journal_id=uuid4(),
        request=request,
        idempotency_key=None,
        _permission=None,
        current_user=MagicMock(user_id=uuid4()),
        legal_entity_id=uuid4(),
        journal_service=mock_journal_service,
    )
    assert isinstance(result, JournalResponseSchema)
    mock_journal_service.update_journal.assert_called_once()


@pytest.mark.asyncio
async def test_update_journal_not_found(mock_journal_service):
    mock_journal_service.update_journal.return_value = None
    request = JournalUpdateSchema()
    with pytest.raises(HTTPException) as exc:
        await update_journal(
            journal_id=uuid4(),
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=MagicMock(user_id=uuid4()),
            legal_entity_id=uuid4(),
            journal_service=mock_journal_service,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_cancel_journal_success(mock_journal_service):
    result = await cancel_journal(
        journal_id=uuid4(),
        reason="Test",
        idempotency_key=None,
        _permission=None,
        current_user=MagicMock(user_id=uuid4()),
        legal_entity_id=uuid4(),
        journal_service=mock_journal_service,
    )
    assert isinstance(result, JournalActionResponseSchema)
    assert result.action == "cancel"
    mock_journal_service.cancel_journal.assert_called_once()


@pytest.mark.asyncio
async def test_restore_journal_success(mock_journal_service):
    result = await restore_journal(
        journal_id=uuid4(),
        idempotency_key=None,
        _permission=None,
        current_user=MagicMock(user_id=uuid4()),
        legal_entity_id=uuid4(),
        journal_service=mock_journal_service,
    )
    assert isinstance(result, JournalResponseSchema)
    mock_journal_service.restore_journal.assert_called_once()


@pytest.mark.asyncio
async def test_submit_journal_success(mock_journal_service):
    result = await submit_journal(
        journal_id=uuid4(),
        idempotency_key=None,
        _permission=None,
        current_user=MagicMock(user_id=uuid4()),
        legal_entity_id=uuid4(),
        journal_service=mock_journal_service,
    )
    assert isinstance(result, JournalActionResponseSchema)
    assert result.action == "submit"
    mock_journal_service.submit_journal.assert_called_once()


@pytest.mark.asyncio
async def test_approve_journal_success(mock_use_case):
    request = JournalApproveSchema(notes="OK")
    result = await approve_journal(
        journal_id=uuid4(),
        request=request,
        idempotency_key=None,
        _permission=None,
        current_user=MagicMock(user_id=uuid4()),
        legal_entity_id=uuid4(),
        use_case=mock_use_case,
    )
    assert isinstance(result, JournalActionResponseSchema)
    assert result.action == "approve"
    mock_use_case.execute.assert_called_once()


@pytest.mark.asyncio
async def test_reject_journal_success(mock_journal_service):
    request = JournalRejectSchema(reason="Invalid")
    result = await reject_journal(
        journal_id=uuid4(),
        request=request,
        idempotency_key=None,
        _permission=None,
        current_user=MagicMock(user_id=uuid4()),
        legal_entity_id=uuid4(),
        journal_service=mock_journal_service,
    )
    assert isinstance(result, JournalActionResponseSchema)
    assert result.action == "reject"
    mock_journal_service.reject_journal.assert_called_once()


@pytest.mark.asyncio
async def test_post_journal_success(mock_use_case):
    result = await post_journal(
        journal_id=uuid4(),
        idempotency_key=None,
        _permission=None,
        current_user=MagicMock(user_id=uuid4()),
        legal_entity_id=uuid4(),
        post_use_case=mock_use_case,
    )
    assert isinstance(result, JournalActionResponseSchema)
    assert result.action == "post"
    mock_use_case.execute.assert_called_once()


@pytest.mark.asyncio
async def test_reverse_journal_success(mock_use_case):
    request = JournalReverseSchema(reason="Correction", reversal_date=date.today())
    result = await reverse_journal(
        journal_id=uuid4(),
        request=request,
        idempotency_key=None,
        _permission=None,
        current_user=MagicMock(user_id=uuid4()),
        legal_entity_id=uuid4(),
        reverse_use_case=mock_use_case,
    )
    assert isinstance(result, JournalActionResponseSchema)
    assert result.action == "reverse"
    mock_use_case.execute.assert_called_once()


@pytest.mark.asyncio
async def test_unpost_journal_success(mock_journal_service):
    result = await unpost_journal(
        journal_id=uuid4(),
        reason="Test",
        idempotency_key=None,
        _permission=None,
        current_user=MagicMock(user_id=uuid4()),
        legal_entity_id=uuid4(),
        journal_service=mock_journal_service,
    )
    assert isinstance(result, JournalActionResponseSchema)
    assert result.action == "unpost"
    mock_journal_service.unpost_journal.assert_called_once()


@pytest.mark.asyncio
async def test_lock_journal_success(mock_journal_service):
    result = await lock_journal(
        journal_id=uuid4(),
        reason="Audit",
        idempotency_key=None,
        _permission=None,
        current_user=MagicMock(user_id=uuid4()),
        legal_entity_id=uuid4(),
        journal_service=mock_journal_service,
    )
    assert isinstance(result, JournalActionResponseSchema)
    assert result.action == "lock"
    mock_journal_service.lock_journal.assert_called_once()


@pytest.mark.asyncio
async def test_unlock_journal_success(mock_journal_service):
    result = await unlock_journal(
        journal_id=uuid4(),
        idempotency_key=None,
        _permission=None,
        current_user=MagicMock(user_id=uuid4()),
        legal_entity_id=uuid4(),
        journal_service=mock_journal_service,
    )
    assert isinstance(result, JournalActionResponseSchema)
    assert result.action == "unlock"
    mock_journal_service.unlock_journal.assert_called_once()


@pytest.mark.asyncio
async def test_list_journals_success(mock_journal_service):
    result = await list_journals(
        status=JournalStatus.DRAFT,
        journal_type=JournalType.GENERAL,
        source_type=JournalSource.MANUAL,
        start_date=date.today(),
        end_date=date.today(),
        journal_number="JRN-001",
        reference_number="REF-001",
        account_code="1100",
        created_by=uuid4(),
        page=1,
        page_size=10,
        _permission=None,
        legal_entity_id=uuid4(),
        journal_service=mock_journal_service,
    )
    assert isinstance(result, JournalListResponseSchema)
    assert len(result.items) == 1
    assert result.total == 1
    mock_journal_service.list_journals.assert_called_once()


@pytest.mark.asyncio
async def test_validate_journal_success(mock_journal_service):
    result = await validate_journal(
        journal_id=uuid4(),
        _permission=None,
        legal_entity_id=uuid4(),
        journal_service=mock_journal_service,
    )
    assert result["journal_number"] == "JRN-001"
    assert result["is_valid"] is True
    mock_journal_service.validate_journal.assert_called_once()


@pytest.mark.asyncio
async def test_get_journal_status_success(mock_journal_service):
    result = await get_journal_status(
        journal_id=uuid4(),
        _permission=None,
        legal_entity_id=uuid4(),
        journal_service=mock_journal_service,
    )
    assert result["status"] == "draft"
    mock_journal_service.get_journal_status.assert_called_once()


@pytest.mark.asyncio
async def test_get_journal_history_success(mock_journal_service):
    result = await get_journal_history(
        journal_id=uuid4(),
        _permission=None,
        legal_entity_id=uuid4(),
        journal_service=mock_journal_service,
    )
    assert isinstance(result, list)
    mock_journal_service.get_journal_history.assert_called_once()


@pytest.mark.asyncio
async def test_get_journal_ledger_entries_success(mock_journal_service):
    result = await get_journal_ledger_entries(
        journal_id=uuid4(),
        _permission=None,
        legal_entity_id=uuid4(),
        journal_service=mock_journal_service,
    )
    assert isinstance(result, list)
    mock_journal_service.get_ledger_entries.assert_called_once()


@pytest.mark.asyncio
async def test_export_journals_success(mock_journal_service):
    result = await export_journals(
        start_date=date.today(),
        end_date=date.today(),
        format="csv",
        status=JournalStatus.DRAFT,
        _permission=None,
        legal_entity_id=uuid4(),
        journal_service=mock_journal_service,
    )
    assert result is not None
    assert result.body == b"csvdata"
    mock_journal_service.export_journals.assert_called_once()


# ============================================================================
# HTTPException imports for route tests
# ============================================================================

from fastapi import HTTPException  # noqa: E402
