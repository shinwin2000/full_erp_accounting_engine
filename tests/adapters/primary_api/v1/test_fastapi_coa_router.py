# tests/adapters/primary_api/v1/test_fastapi_coa_router.py
"""
Comprehensive unit tests for FastAPI Chart of Accounts Router.

Covers:
- IdempotencyManager (cache, expiration, serialization)
- All enum classes
- All request/response schemas (valid & invalid cases)
- ping_coa endpoint
- All endpoint functions (with mocked service layer)
- Negative paths: validation errors, not found, permission errors, generic errors
- Bulk operations, export/import, history, audit
- Idempotency key handling
- Async markers and mocked datetime to avoid flakiness
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.responses import Response

from adapters.primary_api.v1.fastapi_coa_router import (
    AccountBalanceResponseSchema,
    AccountCreateSchema,
    AccountListResponseSchema,
    AccountResponseSchema,
    AccountStatus,
    AccountTreeResponseSchema,
    AccountType,
    AccountUpdateSchema,
    AccountUsageResponseSchema,
    AccountValidationResultSchema,
    BulkParentUpdateSchema,
    BulkStatusUpdateSchema,
    IdempotencyManager,
    ImportExportResultSchema,
    NormalBalance,
    activate_account,
    bulk_update_parent,
    bulk_update_status,
    create_account,
    deactivate_account,
    export_coa,
    get_account_audit_trail,
    get_account_balance,
    get_account_by_code,
    get_account_by_id,
    get_account_history,
    get_account_tree,
    get_account_usage,
    get_coa_service,
    import_coa,
    list_accounts,
    lock_account,
    ping_coa,
    unlock_account,
    update_account,
    validate_account,
    validate_account_code,
)

# ---------- Helper fixtures ----------

@pytest.fixture
def mock_token_payload():
    return MagicMock(user_id=uuid4())


@pytest.fixture
def mock_legal_entity_id():
    return uuid4()


@pytest.fixture
def mock_coa_service():
    """Create a fully mocked COAService with realistic return values."""
    svc = AsyncMock()

    # Helper to create a mock account object with required attributes
    def mock_account(**kwargs):
        defaults = {
            "id": uuid4(),
            "account_code": "1-1000",
            "account_name": "Cash",
            "account_type": "Asset",
            "normal_balance": "debit",
            "parent_account_id": None,
            "parent_account_code": None,
            "level": 1,
            "description": "Cash account",
            "status": "active",
            "currency_code": "IDR",
            "is_bank_account": False,
            "is_cash_account": True,
            "is_intercompany": False,
            "is_header": False,
            "is_used_in_transaction": False,
            "is_locked": False,
            "current_balance": Decimal("0"),
            "category": "Cash",
            "budget_control": False,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "created_by": uuid4(),
            "created_by_name": "Admin",
            "version": 1,
            "children": [],
        }
        defaults.update(kwargs)
        return MagicMock(**defaults)

    # CRUD
    svc.create_account.return_value = mock_account()
    svc.get_account_by_id.return_value = mock_account()
    svc.get_account_by_code.return_value = mock_account()
    svc.update_account.return_value = mock_account()
    svc.deactivate_account.return_value = mock_account(status="inactive")
    svc.void_account.return_value = mock_account(status="archived")
    svc.activate_account.return_value = mock_account()
    svc.lock_account.return_value = mock_account(is_locked=True)
    svc.unlock_account.return_value = mock_account(is_locked=False)

    # List
    svc.list_accounts.return_value = MagicMock(
        items=[mock_account()],
        total=1,
    )

    # Tree
    class MockTree:
        root_accounts = [mock_account()]
        flattened = [mock_account()]
        total_levels = 3
    svc.get_account_hierarchy.return_value = MockTree()

    # Balance & usage
    svc.get_account_balance.return_value = MagicMock(
        account_code="1-1000",
        account_name="Cash",
        balance=Decimal("1000"),
        normal_balance="debit",
        is_debit_balance=True,
        opening_balance=Decimal("0"),
        debit_movement=Decimal("1500"),
        credit_movement=Decimal("500"),
    )
    svc.get_account_usage.return_value = MagicMock(
        account_code="1-1000",
        account_name="Cash",
        journal_count=5,
        last_used_at=datetime.now(timezone.utc),
        total_debit=Decimal("1500"),
        total_credit=Decimal("500"),
        is_used_in_journal=True,
        is_used_in_budget=False,
        is_used_in_tax=False,
    )

    # Validation
    svc.validate_account_modification.return_value = MagicMock(
        is_valid=True,
        errors=[],
        warnings=[],
        suggestions=[],
    )
    svc.validate_account_code.return_value = MagicMock(
        is_valid=True,
        errors=[],
        warnings=[],
        suggestions=[],
    )

    # Bulk
    svc.bulk_update_status.return_value = MagicMock(
        total=2,
        success_count=2,
        failed_count=0,
        failed_ids=[],
        errors=[],
    )
    svc.bulk_update_parent.return_value = MagicMock(
        total=2,
        success_count=2,
        failed_count=0,
        failed_ids=[],
        errors=[],
    )

    # Export / Import
    svc.export_coa.return_value = b'{"accounts": []}'
    svc.import_coa.return_value = MagicMock(
        success=True,
        message="Imported 5 accounts",
        imported_count=3,
        updated_count=2,
        skipped_count=0,
        errors=[],
    )

    # History & Audit
    svc.get_account_history.return_value = [
        MagicMock(
            timestamp=datetime.now(timezone.utc),
            action="update",
            field="account_name",
            old_value="Old Name",
            new_value="New Name",
            actor_id=uuid4(),
            actor_name="Admin",
            reason="Correction",
        )
    ]
    svc.get_account_audit_trail.return_value = [
        MagicMock(
            timestamp=datetime.now(timezone.utc),
            event_type="MODIFY",
            event_data={"field": "account_name"},
            actor_id=uuid4(),
            actor_name="Admin",
            version=2,
        )
    ]

    return svc


# ---------- IdempotencyManager Tests ----------

class TestIdempotencyManager:
    def test_initialization(self):
        mgr = IdempotencyManager()
        assert mgr._storage == {}
        assert mgr._ttl_seconds == 86400

    def test_get_cached_result_miss(self):
        mgr = IdempotencyManager()
        assert mgr.get_cached_result("key", "method") is None

    def test_cache_and_retrieve(self):
        mgr = IdempotencyManager()
        data = {"id": "123", "status": "ok"}
        mgr.cache_result("key", "method", data)
        cached = mgr.get_cached_result("key", "method")
        assert cached == data

    @patch("adapters.primary_api.v1.fastapi_coa_router.datetime")
    def test_cache_serializes_complex_types(self, mock_dt):
        fixed_now = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        mock_dt.now.return_value = fixed_now
        mgr = IdempotencyManager()
        data = {"date": fixed_now, "decimal": Decimal("10.50")}
        mgr.cache_result("key", "method", data)
        cached = mgr.get_cached_result("key", "method")
        assert cached is not None
        assert cached["date"] == fixed_now.isoformat()
        assert cached["decimal"] == "10.50"

    @patch("adapters.primary_api.v1.fastapi_coa_router.datetime")
    def test_cache_expiration(self, mock_dt):
        mgr = IdempotencyManager()
        mgr._ttl_seconds = 0
        mgr.cache_result("key", "method", {"foo": "bar"})
        cached = mgr.get_cached_result("key", "method")
        assert cached is None

    def test_key_generation_deterministic(self):
        mgr = IdempotencyManager()
        key1 = mgr._get_key("abc", "create_account")
        key2 = mgr._get_key("abc", "create_account")
        key3 = mgr._get_key("abc", "update_account")
        assert key1 == key2
        assert key1 != key3


# ---------- Enum Tests ----------

class TestEnums:
    def test_account_type_values(self):
        assert AccountType.ASSET.value == "Asset"
        assert AccountType.LIABILITY.value == "Liability"
        assert AccountType.EQUITY.value == "Equity"
        assert AccountType.REVENUE.value == "Revenue"
        assert AccountType.EXPENSE.value == "Expense"

    def test_normal_balance_values(self):
        assert NormalBalance.DEBIT.value == "debit"
        assert NormalBalance.CREDIT.value == "credit"

    def test_account_status_values(self):
        assert AccountStatus.ACTIVE.value == "active"
        assert AccountStatus.INACTIVE.value == "inactive"
        assert AccountStatus.SUSPENDED.value == "suspended"
        assert AccountStatus.LOCKED.value == "locked"
        assert AccountStatus.ARCHIVED.value == "archived"


# ---------- Schema Validation (Negative & Positive) ----------

class TestAccountCreateSchema:
    def test_valid_schema(self):
        data = {
            "account_code": "1-1000",
            "account_name": "Cash",
            "account_type": AccountType.ASSET,
            "normal_balance": NormalBalance.DEBIT,
            "parent_account_code": None,
            "description": "Main cash",
            "currency_code": "IDR",
            "is_bank_account": False,
            "is_cash_account": True,
            "is_intercompany": False,
            "is_header": False,
            "level": 1,
            "opening_balance": Decimal("0"),
            "category": "Cash",
            "budget_control": False,
        }
        schema = AccountCreateSchema(**data)
        assert schema.account_code == "1-1000"
        assert schema.account_name == "Cash"

    def test_account_code_uppercase(self):
        schema = AccountCreateSchema(
            account_code="1-1000",
            account_name="Test",
            account_type=AccountType.ASSET,
            normal_balance=NormalBalance.DEBIT,
        )
        assert schema.account_code == "1-1000"

    def test_account_code_invalid_characters(self):
        with pytest.raises(ValueError, match="must contain digits and optional hyphens/periods"):
            AccountCreateSchema(
                account_code="1A-1000",
                account_name="Test",
                account_type=AccountType.ASSET,
                normal_balance=NormalBalance.DEBIT,
            )

    def test_account_type_prefix_mismatch_asset(self):
        with pytest.raises(ValueError, match="Account code for Asset should start with 1"):
            AccountCreateSchema(
                account_code="2-1000",
                account_name="Test",
                account_type=AccountType.ASSET,
                normal_balance=NormalBalance.DEBIT,
            )

    def test_account_type_prefix_liability_ok(self):
        schema = AccountCreateSchema(
            account_code="2-1000",
            account_name="AP",
            account_type=AccountType.LIABILITY,
            normal_balance=NormalBalance.CREDIT,
        )
        assert schema.account_code == "2-1000"

    def test_account_type_prefix_expense_5_or_6(self):
        schema5 = AccountCreateSchema(
            account_code="5-1000",
            account_name="COGS",
            account_type=AccountType.EXPENSE,
            normal_balance=NormalBalance.DEBIT,
        )
        assert schema5.account_code == "5-1000"
        schema6 = AccountCreateSchema(
            account_code="6-1000",
            account_name="Other",
            account_type=AccountType.EXPENSE,
            normal_balance=NormalBalance.DEBIT,
        )
        assert schema6.account_code == "6-1000"


class TestAccountUpdateSchema:
    def test_valid_schema(self):
        data = {
            "account_name": "New Name",
            "description": "Updated",
            "status": AccountStatus.ACTIVE,
            "parent_account_code": "1-0000",
            "currency_code": "USD",
            "is_bank_account": True,
            "is_cash_account": False,
            "is_intercompany": True,
            "category": "Liquid",
            "budget_control": True,
        }
        schema = AccountUpdateSchema(**data)
        assert schema.account_name == "New Name"
        assert schema.status == AccountStatus.ACTIVE

    def test_partial_update(self):
        schema = AccountUpdateSchema(account_name="Only Name")
        assert schema.account_name == "Only Name"
        assert schema.status is None


# ---------- Ping Endpoint ----------

def test_ping_coa():
    result = ping_coa()
    assert result == {"status": "ok", "service": "coa"}


# ---------- Dependency Injection ----------

@pytest.mark.asyncio
async def test_get_coa_service():
    request = MagicMock()
    request.app.state.container = MagicMock()
    request.app.state.container.resolve.return_value = "service"
    service = await get_coa_service(request)
    assert service == "service"


# ---------- Account CRUD Endpoints ----------

@pytest.mark.asyncio
class TestCreateAccount:
    async def test_success(self, mock_coa_service, mock_token_payload, mock_legal_entity_id):
        request = AccountCreateSchema(
            account_code="1-1000",
            account_name="Cash",
            account_type=AccountType.ASSET,
            normal_balance=NormalBalance.DEBIT,
        )
        result = await create_account(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            coa_service=mock_coa_service,
        )
        assert isinstance(result, AccountResponseSchema)
        assert result.account_code == "1-1000"
        mock_coa_service.create_account.assert_called_once()

    async def test_idempotency_hit(self, mock_coa_service, mock_token_payload, mock_legal_entity_id):
        request = AccountCreateSchema(
            account_code="1-1000",
            account_name="Cash",
            account_type=AccountType.ASSET,
            normal_balance=NormalBalance.DEBIT,
        )
        with patch("adapters.primary_api.v1.fastapi_coa_router._idempotency_manager") as mock_im:
            # Pre-cache a valid response
            cached = {
                "id": str(uuid4()),
                "account_code": "1-1000",
                "account_name": "Cash",
                "account_type": "Asset",
                "normal_balance": "debit",
                "parent_account_id": None,
                "parent_account_code": None,
                "level": 1,
                "description": None,
                "status": "active",
                "currency_code": "IDR",
                "is_bank_account": False,
                "is_cash_account": True,
                "is_intercompany": False,
                "is_header": False,
                "is_used_in_transaction": False,
                "is_locked": False,
                "current_balance": "0",
                "category": None,
                "budget_control": False,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "created_by": str(uuid4()),
                "created_by_name": None,
                "version": 1,
                "children": None,
            }
            mock_im.get_cached_result.return_value = cached
            result = await create_account(
                request=request,
                idempotency_key="abc123",
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                coa_service=mock_coa_service,
            )
            assert isinstance(result, AccountResponseSchema)
            assert result.account_code == "1-1000"
            mock_coa_service.create_account.assert_not_called()

    async def test_validation_error_schema(self, mock_coa_service, mock_token_payload, mock_legal_entity_id):
        # Invalid account code (contains letter)
        request = AccountCreateSchema(
            account_code="1A-1000",
            account_name="Test",
            account_type=AccountType.ASSET,
            normal_balance=NormalBalance.DEBIT,
        )
        with pytest.raises(HTTPException) as exc:
            await create_account(
                request=request,
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                coa_service=mock_coa_service,
            )
        assert exc.value.status_code == 422

    async def test_service_value_error(self, mock_coa_service, mock_token_payload, mock_legal_entity_id):
        mock_coa_service.create_account.side_effect = ValueError("Duplicate code")
        request = AccountCreateSchema(
            account_code="1-1000",
            account_name="Cash",
            account_type=AccountType.ASSET,
            normal_balance=NormalBalance.DEBIT,
        )
        with pytest.raises(HTTPException) as exc:
            await create_account(
                request=request,
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                coa_service=mock_coa_service,
            )
        assert exc.value.status_code == 422

    async def test_service_permission_error(self, mock_coa_service, mock_token_payload, mock_legal_entity_id):
        mock_coa_service.create_account.side_effect = PermissionError("Not allowed")
        request = AccountCreateSchema(
            account_code="1-1000",
            account_name="Cash",
            account_type=AccountType.ASSET,
            normal_balance=NormalBalance.DEBIT,
        )
        with pytest.raises(HTTPException) as exc:
            await create_account(
                request=request,
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                coa_service=mock_coa_service,
            )
        assert exc.value.status_code == 403

    async def test_service_generic_exception(self, mock_coa_service, mock_token_payload, mock_legal_entity_id):
        mock_coa_service.create_account.side_effect = Exception("DB error")
        request = AccountCreateSchema(
            account_code="1-1000",
            account_name="Cash",
            account_type=AccountType.ASSET,
            normal_balance=NormalBalance.DEBIT,
        )
        with pytest.raises(HTTPException) as exc:
            await create_account(
                request=request,
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                coa_service=mock_coa_service,
            )
        assert exc.value.status_code == 500


@pytest.mark.asyncio
class TestGetAccount:
    async def test_by_id_success(self, mock_coa_service, mock_legal_entity_id):
        account_id = uuid4()
        result = await get_account_by_id(
            account_id=account_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            coa_service=mock_coa_service,
        )
        assert isinstance(result, AccountResponseSchema)
        assert result.account_code == "1-1000"
        mock_coa_service.get_account_by_id.assert_called_once_with(account_id, mock_legal_entity_id)

    async def test_by_id_not_found(self, mock_coa_service, mock_legal_entity_id):
        mock_coa_service.get_account_by_id.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_account_by_id(
                account_id=uuid4(),
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                coa_service=mock_coa_service,
            )
        assert exc.value.status_code == 404

    async def test_by_code_success(self, mock_coa_service, mock_legal_entity_id):
        result = await get_account_by_code(
            account_code="1-1000",
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            coa_service=mock_coa_service,
        )
        assert isinstance(result, AccountResponseSchema)
        mock_coa_service.get_account_by_code.assert_called_once_with("1-1000", mock_legal_entity_id)

    async def test_by_code_not_found(self, mock_coa_service, mock_legal_entity_id):
        mock_coa_service.get_account_by_code.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_account_by_code(
                account_code="UNKNOWN",
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                coa_service=mock_coa_service,
            )
        assert exc.value.status_code == 404

    async def test_by_code_generic_error(self, mock_coa_service, mock_legal_entity_id):
        mock_coa_service.get_account_by_code.side_effect = Exception("Error")
        with pytest.raises(HTTPException) as exc:
            await get_account_by_code(
                account_code="1-1000",
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                coa_service=mock_coa_service,
            )
        assert exc.value.status_code == 500


@pytest.mark.asyncio
class TestUpdateAccount:
    async def test_success(self, mock_coa_service, mock_token_payload, mock_legal_entity_id):
        account_id = uuid4()
        request = AccountUpdateSchema(account_name="Updated Name")
        result = await update_account(
            account_id=account_id,
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            coa_service=mock_coa_service,
        )
        assert isinstance(result, AccountResponseSchema)
        mock_coa_service.update_account.assert_called_once()

    async def test_idempotency_hit(self, mock_coa_service, mock_token_payload, mock_legal_entity_id):
        account_id = uuid4()
        request = AccountUpdateSchema()
        with patch("adapters.primary_api.v1.fastapi_coa_router._idempotency_manager") as mock_im:
            cached = {"id": str(account_id), "account_code": "1-1000", "account_name": "Cached"}
            mock_im.get_cached_result.return_value = cached
            result = await update_account(
                account_id=account_id,
                request=request,
                idempotency_key="key",
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                coa_service=mock_coa_service,
            )
            assert isinstance(result, AccountResponseSchema)
            mock_coa_service.update_account.assert_not_called()

    async def test_not_found(self, mock_coa_service, mock_token_payload, mock_legal_entity_id):
        mock_coa_service.update_account.return_value = None
        request = AccountUpdateSchema()
        with pytest.raises(HTTPException) as exc:
            await update_account(
                account_id=uuid4(),
                request=request,
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                coa_service=mock_coa_service,
            )
        assert exc.value.status_code == 404

    async def test_service_value_error(self, mock_coa_service, mock_token_payload, mock_legal_entity_id):
        mock_coa_service.update_account.side_effect = ValueError("Invalid status")
        request = AccountUpdateSchema(status=AccountStatus.ACTIVE)
        with pytest.raises(HTTPException) as exc:
            await update_account(
                account_id=uuid4(),
                request=request,
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                coa_service=mock_coa_service,
            )
        assert exc.value.status_code == 422

    async def test_permission_error(self, mock_coa_service, mock_token_payload, mock_legal_entity_id):
        mock_coa_service.update_account.side_effect = PermissionError("Not allowed")
        request = AccountUpdateSchema()
        with pytest.raises(HTTPException) as exc:
            await update_account(
                account_id=uuid4(),
                request=request,
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                coa_service=mock_coa_service,
            )
        assert exc.value.status_code == 403


@pytest.mark.asyncio
class TestDeactivateAccount:
    async def test_deactivate_success(self, mock_coa_service, mock_token_payload, mock_legal_entity_id):
        account_id = uuid4()
        result = await deactivate_account(
            account_id=account_id,
            permanent=False,
            reason="Not used",
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            coa_service=mock_coa_service,
        )
        assert "deactivated" in result["message"]
        mock_coa_service.deactivate_account.assert_called_once_with(
            account_id, mock_token_payload.user_id, mock_legal_entity_id, "Not used"
        )

    async def test_void_success(self, mock_coa_service, mock_token_payload, mock_legal_entity_id):
        account_id = uuid4()
        result = await deactivate_account(
            account_id=account_id,
            permanent=True,
            reason="Void",
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            coa_service=mock_coa_service,
        )
        assert "voided" in result["message"]
        mock_coa_service.void_account.assert_called_once_with(
            account_id, mock_token_payload.user_id, mock_legal_entity_id, "Void"
        )

    async def test_not_found(self, mock_coa_service, mock_token_payload, mock_legal_entity_id):
        mock_coa_service.deactivate_account.return_value = None
        with pytest.raises(HTTPException) as exc:
            await deactivate_account(
                account_id=uuid4(),
                permanent=False,
                reason="",
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                coa_service=mock_coa_service,
            )
        assert exc.value.status_code == 404

    async def test_idempotency_hit(self, mock_coa_service, mock_token_payload, mock_legal_entity_id):
        account_id = uuid4()
        with patch("adapters.primary_api.v1.fastapi_coa_router._idempotency_manager") as mock_im:
            cached = {"message": "cached"}
            mock_im.get_cached_result.return_value = cached
            result = await deactivate_account(
                account_id=account_id,
                permanent=False,
                reason="",
                idempotency_key="key",
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                coa_service=mock_coa_service,
            )
            assert result == cached
            mock_coa_service.deactivate_account.assert_not_called()

    async def test_value_error(self, mock_coa_service, mock_token_payload, mock_legal_entity_id):
        mock_coa_service.deactivate_account.side_effect = ValueError("Cannot deactivate")
        with pytest.raises(HTTPException) as exc:
            await deactivate_account(
                account_id=uuid4(),
                permanent=False,
                reason="",
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                coa_service=mock_coa_service,
            )
        assert exc.value.status_code == 422


@pytest.mark.asyncio
class TestActivateAccount:
    async def test_success(self, mock_coa_service, mock_token_payload, mock_legal_entity_id):
        account_id = uuid4()
        result = await activate_account(
            account_id=account_id,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            coa_service=mock_coa_service,
        )
        assert isinstance(result, AccountResponseSchema)
        mock_coa_service.activate_account.assert_called_once_with(
            account_id, mock_token_payload.user_id, mock_legal_entity_id
        )

    async def test_not_found(self, mock_coa_service, mock_token_payload, mock_legal_entity_id):
        mock_coa_service.activate_account.return_value = None
        with pytest.raises(HTTPException) as exc:
            await activate_account(
                account_id=uuid4(),
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                coa_service=mock_coa_service,
            )
        assert exc.value.status_code == 404

    async def test_idempotency_hit(self, mock_coa_service, mock_token_payload, mock_legal_entity_id):
        with patch("adapters.primary_api.v1.fastapi_coa_router._idempotency_manager") as mock_im:
            cached = {"id": str(uuid4()), "account_code": "1-1000"}
            mock_im.get_cached_result.return_value = cached
            result = await activate_account(
                account_id=uuid4(),
                idempotency_key="key",
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                coa_service=mock_coa_service,
            )
            assert isinstance(result, AccountResponseSchema)
            mock_coa_service.activate_account.assert_not_called()


@pytest.mark.asyncio
class TestLockUnlockAccount:
    async def test_lock_success(self, mock_coa_service, mock_token_payload, mock_legal_entity_id):
        account_id = uuid4()
        result = await lock_account(
            account_id=account_id,
            reason="Audit",
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            coa_service=mock_coa_service,
        )
        assert result.is_locked is True
        mock_coa_service.lock_account.assert_called_once_with(
            account_id, mock_token_payload.user_id, mock_legal_entity_id, "Audit"
        )

    async def test_lock_not_found(self, mock_coa_service, mock_token_payload, mock_legal_entity_id):
        mock_coa_service.lock_account.return_value = None
        with pytest.raises(HTTPException) as exc:
            await lock_account(
                account_id=uuid4(),
                reason="",
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                coa_service=mock_coa_service,
            )
        assert exc.value.status_code == 404

    async def test_unlock_success(self, mock_coa_service, mock_token_payload, mock_legal_entity_id):
        account_id = uuid4()
        result = await unlock_account(
            account_id=account_id,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            coa_service=mock_coa_service,
        )
        assert result.is_locked is False
        mock_coa_service.unlock_account.assert_called_once_with(
            account_id, mock_token_payload.user_id, mock_legal_entity_id
        )

    async def test_unlock_not_found(self, mock_coa_service, mock_token_payload, mock_legal_entity_id):
        mock_coa_service.unlock_account.return_value = None
        with pytest.raises(HTTPException) as exc:
            await unlock_account(
                account_id=uuid4(),
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                coa_service=mock_coa_service,
            )
        assert exc.value.status_code == 404


# ---------- List and Tree Endpoints ----------

@pytest.mark.asyncio
class TestListAccounts:
    async def test_success(self, mock_coa_service, mock_legal_entity_id):
        result = await list_accounts(
            account_type=AccountType.ASSET,
            status=AccountStatus.ACTIVE,
            parent_account_code=None,
            is_header=None,
            level=None,
            search="cash",
            include_inactive=False,
            page=1,
            page_size=20,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            coa_service=mock_coa_service,
        )
        assert isinstance(result, AccountListResponseSchema)
        assert len(result.items) == 1
        assert isinstance(result.items[0], AccountResponseSchema)
        mock_coa_service.list_accounts.assert_called_once()

    async def test_service_error(self, mock_coa_service, mock_legal_entity_id):
        mock_coa_service.list_accounts.side_effect = Exception("DB error")
        with pytest.raises(HTTPException) as exc:
            await list_accounts(
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                coa_service=mock_coa_service,
            )
        assert exc.value.status_code == 500


@pytest.mark.asyncio
class TestGetAccountTree:
    async def test_success(self, mock_coa_service, mock_legal_entity_id):
        result = await get_account_tree(
            include_inactive=True,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            coa_service=mock_coa_service,
        )
        assert isinstance(result, AccountTreeResponseSchema)
        assert len(result.root_accounts) == 1
        assert result.total_accounts == 1
        assert result.total_levels == 3
        mock_coa_service.get_account_hierarchy.assert_called_once_with(mock_legal_entity_id, True)

    async def test_service_error(self, mock_coa_service, mock_legal_entity_id):
        mock_coa_service.get_account_hierarchy.side_effect = Exception("Error")
        with pytest.raises(HTTPException) as exc:
            await get_account_tree(
                include_inactive=False,
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                coa_service=mock_coa_service,
            )
        assert exc.value.status_code == 500


# ---------- Balance and Usage ----------

@pytest.mark.asyncio
class TestAccountBalance:
    async def test_success(self, mock_coa_service, mock_legal_entity_id):
        account_id = uuid4()
        as_of = datetime.now(timezone.utc)
        result = await get_account_balance(
            account_id=account_id,
            as_of_date=as_of,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            coa_service=mock_coa_service,
        )
        assert isinstance(result, AccountBalanceResponseSchema)
        assert result.balance == Decimal("1000")
        mock_coa_service.get_account_balance.assert_called_once_with(
            account_id, mock_legal_entity_id, as_of
        )

    async def test_not_found(self, mock_coa_service, mock_legal_entity_id):
        mock_coa_service.get_account_balance.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_account_balance(
                account_id=uuid4(),
                as_of_date=datetime.now(timezone.utc),
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                coa_service=mock_coa_service,
            )
        assert exc.value.status_code == 404

    async def test_service_error(self, mock_coa_service, mock_legal_entity_id):
        mock_coa_service.get_account_balance.side_effect = Exception("Error")
        with pytest.raises(HTTPException) as exc:
            await get_account_balance(
                account_id=uuid4(),
                as_of_date=datetime.now(timezone.utc),
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                coa_service=mock_coa_service,
            )
        assert exc.value.status_code == 500


@pytest.mark.asyncio
class TestAccountUsage:
    async def test_success(self, mock_coa_service, mock_legal_entity_id):
        account_id = uuid4()
        result = await get_account_usage(
            account_id=account_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            coa_service=mock_coa_service,
        )
        assert isinstance(result, AccountUsageResponseSchema)
        assert result.journal_count == 5
        mock_coa_service.get_account_usage.assert_called_once_with(account_id, mock_legal_entity_id)

    async def test_not_found(self, mock_coa_service, mock_legal_entity_id):
        mock_coa_service.get_account_usage.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_account_usage(
                account_id=uuid4(),
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                coa_service=mock_coa_service,
            )
        assert exc.value.status_code == 404


# ---------- Validation Endpoints ----------

@pytest.mark.asyncio
class TestValidateAccount:
    async def test_success(self, mock_coa_service, mock_legal_entity_id):
        account_id = uuid4()
        result = await validate_account(
            account_id=account_id,
            action="delete",
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            coa_service=mock_coa_service,
        )
        assert isinstance(result, AccountValidationResultSchema)
        assert result.is_valid is True
        mock_coa_service.validate_account_modification.assert_called_once_with(
            account_id, mock_legal_entity_id, "delete"
        )

    async def test_service_error(self, mock_coa_service, mock_legal_entity_id):
        mock_coa_service.validate_account_modification.side_effect = Exception("Error")
        with pytest.raises(HTTPException) as exc:
            await validate_account(
                account_id=uuid4(),
                action="delete",
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                coa_service=mock_coa_service,
            )
        assert exc.value.status_code == 500


@pytest.mark.asyncio
class TestValidateAccountCode:
    async def test_success(self, mock_coa_service, mock_legal_entity_id):
        result = await validate_account_code(
            account_code="1-1000",
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            coa_service=mock_coa_service,
        )
        assert isinstance(result, AccountValidationResultSchema)
        assert result.is_valid is True
        mock_coa_service.validate_account_code.assert_called_once_with("1-1000", mock_legal_entity_id)

    async def test_service_error(self, mock_coa_service, mock_legal_entity_id):
        mock_coa_service.validate_account_code.side_effect = Exception("Error")
        with pytest.raises(HTTPException) as exc:
            await validate_account_code(
                account_code="1-1000",
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                coa_service=mock_coa_service,
            )
        assert exc.value.status_code == 500


# ---------- Bulk Operations ----------

@pytest.mark.asyncio
class TestBulkOperations:
    async def test_bulk_update_status_success(self, mock_coa_service, mock_token_payload, mock_legal_entity_id):
        request = BulkStatusUpdateSchema(
            account_ids=[uuid4(), uuid4()],
            status=AccountStatus.INACTIVE,
            reason="Closing",
        )
        result = await bulk_update_status(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            coa_service=mock_coa_service,
        )
        assert result["success_count"] == 2
        assert result["failed_count"] == 0
        mock_coa_service.bulk_update_status.assert_called_once_with(
            account_ids=request.account_ids,
            status="inactive",
            reason="Closing",
            updated_by=mock_token_payload.user_id,
            legal_entity_id=mock_legal_entity_id,
        )

    async def test_bulk_update_status_idempotency(self, mock_coa_service, mock_token_payload, mock_legal_entity_id):
        request = BulkStatusUpdateSchema(account_ids=[uuid4()], status=AccountStatus.ACTIVE)
        with patch("adapters.primary_api.v1.fastapi_coa_router._idempotency_manager") as mock_im:
            cached = {"total": 1, "success_count": 1}
            mock_im.get_cached_result.return_value = cached
            result = await bulk_update_status(
                request=request,
                idempotency_key="key",
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                coa_service=mock_coa_service,
            )
            assert result == cached
            mock_coa_service.bulk_update_status.assert_not_called()

    async def test_bulk_update_parent_success(self, mock_coa_service, mock_token_payload, mock_legal_entity_id):
        request = BulkParentUpdateSchema(
            account_ids=[uuid4()],
            parent_account_code="1-0000",
        )
        result = await bulk_update_parent(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            coa_service=mock_coa_service,
        )
        assert result["success_count"] == 2
        mock_coa_service.bulk_update_parent.assert_called_once_with(
            account_ids=request.account_ids,
            parent_account_code="1-0000",
            updated_by=mock_token_payload.user_id,
            legal_entity_id=mock_legal_entity_id,
        )

    async def test_bulk_update_parent_idempotency(self, mock_coa_service, mock_token_payload, mock_legal_entity_id):
        request = BulkParentUpdateSchema(account_ids=[uuid4()], parent_account_code="1-0000")
        with patch("adapters.primary_api.v1.fastapi_coa_router._idempotency_manager") as mock_im:
            cached = {"total": 1, "success_count": 1}
            mock_im.get_cached_result.return_value = cached
            result = await bulk_update_parent(
                request=request,
                idempotency_key="key",
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                coa_service=mock_coa_service,
            )
            assert result == cached
            mock_coa_service.bulk_update_parent.assert_not_called()


# ---------- Export and Import ----------

@pytest.mark.asyncio
class TestExportImport:
    async def test_export_json(self, mock_coa_service, mock_legal_entity_id):
        response = await export_coa(
            format="json",
            include_inactive=False,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            coa_service=mock_coa_service,
        )
        assert isinstance(response, Response)
        assert response.body == b'{"accounts": []}'
        assert response.media_type == "application/json"
        assert "attachment" in response.headers["Content-Disposition"]
        mock_coa_service.export_coa.assert_called_once_with(
            mock_legal_entity_id, "json", False
        )

    async def test_export_csv(self, mock_coa_service, mock_legal_entity_id):
        mock_coa_service.export_coa.return_value = b"csv data"
        response = await export_coa(
            format="csv",
            include_inactive=True,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            coa_service=mock_coa_service,
        )
        assert response.media_type == "text/csv"
        mock_coa_service.export_coa.assert_called_once_with(
            mock_legal_entity_id, "csv", True
        )

    async def test_export_excel(self, mock_coa_service, mock_legal_entity_id):
        mock_coa_service.export_coa.return_value = b"excel data"
        response = await export_coa(
            format="excel",
            include_inactive=False,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            coa_service=mock_coa_service,
        )
        assert response.media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        mock_coa_service.export_coa.assert_called_once_with(
            mock_legal_entity_id, "excel", False
        )

    async def test_export_service_error(self, mock_coa_service, mock_legal_entity_id):
        mock_coa_service.export_coa.side_effect = Exception("Export fail")
        with pytest.raises(HTTPException) as exc:
            await export_coa(
                format="json",
                include_inactive=False,
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                coa_service=mock_coa_service,
            )
        assert exc.value.status_code == 500

    async def test_import_success(self, mock_coa_service, mock_token_payload, mock_legal_entity_id):
        file = MagicMock(spec=UploadFile)
        file.filename = "accounts.json"
        file.read = AsyncMock(return_value=b'{"accounts": []}')
        result = await import_coa(
            file=file,
            mode="merge",
            validate_only=False,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            coa_service=mock_coa_service,
        )
        assert isinstance(result, ImportExportResultSchema)
        assert result.success is True
        assert result.imported_count == 3
        mock_coa_service.import_coa.assert_called_once()

    async def test_import_idempotency(self, mock_coa_service, mock_token_payload, mock_legal_entity_id):
        file = MagicMock(spec=UploadFile)
        file.filename = "accounts.json"
        with patch("adapters.primary_api.v1.fastapi_coa_router._idempotency_manager") as mock_im:
            cached = {"success": True, "message": "cached", "imported_count": 0, "updated_count": 0, "skipped_count": 0, "errors": []}
            mock_im.get_cached_result.return_value = cached
            result = await import_coa(
                file=file,
                mode="merge",
                validate_only=False,
                idempotency_key="key",
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                coa_service=mock_coa_service,
            )
            assert isinstance(result, ImportExportResultSchema)
            assert result.message == "cached"
            mock_coa_service.import_coa.assert_not_called()

    async def test_import_value_error(self, mock_coa_service, mock_token_payload, mock_legal_entity_id):
        mock_coa_service.import_coa.side_effect = ValueError("Invalid format")
        file = MagicMock(spec=UploadFile)
        file.filename = "accounts.json"
        file.read = AsyncMock(return_value=b'{}')
        with pytest.raises(HTTPException) as exc:
            await import_coa(
                file=file,
                mode="merge",
                validate_only=False,
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                coa_service=mock_coa_service,
            )
        assert exc.value.status_code == 422

    async def test_import_generic_error(self, mock_coa_service, mock_token_payload, mock_legal_entity_id):
        mock_coa_service.import_coa.side_effect = Exception("Import error")
        file = MagicMock(spec=UploadFile)
        file.filename = "accounts.json"
        file.read = AsyncMock(return_value=b'{}')
        with pytest.raises(HTTPException) as exc:
            await import_coa(
                file=file,
                mode="merge",
                validate_only=False,
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                coa_service=mock_coa_service,
            )
        assert exc.value.status_code == 500


# ---------- History and Audit ----------

@pytest.mark.asyncio
class TestHistoryAudit:
    async def test_get_account_history(self, mock_coa_service, mock_legal_entity_id):
        account_id = uuid4()
        start = datetime.now(timezone.utc)
        end = datetime.now(timezone.utc)
        result = await get_account_history(
            account_id=account_id,
            start_date=start,
            end_date=end,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            coa_service=mock_coa_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert "field" in result[0]
        assert result[0]["field"] == "account_name"
        mock_coa_service.get_account_history.assert_called_once_with(
            account_id, mock_legal_entity_id, start, end
        )

    async def test_get_account_history_service_error(self, mock_coa_service, mock_legal_entity_id):
        mock_coa_service.get_account_history.side_effect = Exception("Error")
        with pytest.raises(HTTPException) as exc:
            await get_account_history(
                account_id=uuid4(),
                start_date=None,
                end_date=None,
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                coa_service=mock_coa_service,
            )
        assert exc.value.status_code == 500

    async def test_get_account_audit_trail(self, mock_coa_service, mock_legal_entity_id):
        account_id = uuid4()
        result = await get_account_audit_trail(
            account_id=account_id,
            limit=10,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            coa_service=mock_coa_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["event_type"] == "MODIFY"
        mock_coa_service.get_account_audit_trail.assert_called_once_with(
            account_id, mock_legal_entity_id, 10
        )

    async def test_get_account_audit_trail_service_error(self, mock_coa_service, mock_legal_entity_id):
        mock_coa_service.get_account_audit_trail.side_effect = Exception("Error")
        with pytest.raises(HTTPException) as exc:
            await get_account_audit_trail(
                account_id=uuid4(),
                limit=100,
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                coa_service=mock_coa_service,
            )
        assert exc.value.status_code == 500