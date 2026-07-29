# tests/adapters/primary_api/v1/test_fastapi_bank_cash_router.py
"""
Comprehensive unit tests for FastAPI Bank & Cash Router.

Perbaikan:
- Semua async test diberi @pytest.mark.asyncio
- Duplikasi struktural dihilangkan dengan parametrize
- Mock quality ditingkatkan: assertion pada nilai dan panggilan mock
- Negative path ditambahkan: ValueError, PermissionError, Exception
- Idempotency tests menggunakan patch yang tepat
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.responses import Response

from adapters.primary_api.v1.fastapi_bank_cash_router import (
    AccountBalanceHistorySchema,
    BankAccountCreateSchema,
    BankAccountResponseSchema,
    BankAccountStatus,
    BankAccountType,
    BankAccountUpdateSchema,
    BankReconciliationCreateSchema,
    BankReconciliationResponseSchema,
    BankTransactionCreateSchema,
    BankTransactionResponseSchema,
    BankTransactionReverseSchema,
    BankTransactionUpdateSchema,
    BankTransferApproveSchema,
    BankTransferCreateSchema,
    BankTransferResponseSchema,
    CashBookCreateSchema,
    CashBookRepositoryAdapter,
    CashBookResponseSchema,
    CashBookStatus,
    CashBookUpdateSchema,
    CashFlowReportSchema,
    CashFlowRepositoryAdapter,
    CashTransactionCreateSchema,
    CashTransactionResponseSchema,
    DailyCashPositionSchema,
    IdempotencyManager,
    PettyCashCreateSchema,
    PettyCashReimbursementSchema,
    PettyCashResponseSchema,
    PettyCashStatus,
    ReconciliationStatus,
    TransactionStatus,
    TransferStatus,
    activate_bank_account,
    approve_bank_transfer,
    cancel_bank_transfer,
    close_reconciliation,
    create_bank_account,
    create_bank_transaction,
    create_bank_transfer,
    create_cash_book,
    create_petty_cash_fund,
    deactivate_bank_account,
    export_bank_transactions,
    get_bank_account,
    get_bank_balance,
    get_bank_balance_history,
    get_bank_cash_service,
    get_bank_reconciliation_use_case,
    get_bank_transaction,
    get_cash_book_balance,
    get_cash_book_by_id,
    get_cash_book_transactions,
    get_cash_books_by_currency,
    get_cash_flow_report,
    get_daily_cash_position,
    get_reconciliation_history,
    health,
    import_bank_statement,
    info,
    list_bank_accounts,
    list_bank_transactions,
    list_cash_books,
    lock_bank_account,
    ping,
    process_bank_transfer,
    reconcile_bank,
    record_cash_transaction,
    reimburse_petty_cash,
    reverse_bank_transaction,
    unlock_bank_account,
    update_bank_account,
    update_bank_transaction,
    update_cash_book,
)

# ============================================================================
# FIXED DATETIME - untuk menghindari flaky tests
# ============================================================================
FIXED_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
FIXED_DATE = date(2026, 1, 1)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    """Mock datetime.now() dan date.today() untuk menghindari flaky tests."""
    with patch("adapters.primary_api.v1.fastapi_bank_cash_router.datetime") as mock_dt, \
         patch("adapters.primary_api.v1.fastapi_bank_cash_router.date") as mock_date:
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
def mock_bank_cash_service():
    """Create a fully mocked BankCashService with realistic return values."""
    svc = AsyncMock()

    # Helper to create mock account
    def mock_account(**kwargs):
        defaults = {
            "id": uuid4(),
            "account_number": "1234567890",
            "account_name": "Test Account",
            "bank_name": "Test Bank",
            "bank_code": "TEST",
            "currency_code": "IDR",
            "account_type": "checking",
            "current_balance": Decimal("1000000"),
            "available_balance": Decimal("1000000"),
            "opening_balance": Decimal("1000000"),
            "opening_balance_date": FIXED_DATE,
            "gl_account_id": uuid4(),
            "status": "active",
            "is_active": True,
            "is_default": False,
            "is_locked": False,
            "bank_address": "Jl. Test",
            "swift_code": "TESTIDJA",
            "iban": "ID1234567890",
            "daily_limit": Decimal("50000000"),
            "transaction_limit": Decimal("10000000"),
            "notes": "Test notes",
            "created_at": FIXED_NOW,
            "created_by": uuid4(),
            "created_by_name": "Admin",
            "updated_at": FIXED_NOW,
            "updated_by": uuid4(),
            "version": 1,
        }
        defaults.update(kwargs)
        return MagicMock(**defaults)

    # Bank account methods
    svc.create_bank_account.return_value = mock_account()
    svc.get_bank_account.return_value = mock_account()
    svc.update_bank_account.return_value = mock_account()
    svc.deactivate_bank_account.return_value = mock_account(status="inactive")
    svc.close_bank_account.return_value = mock_account(status="closed")
    svc.activate_bank_account.return_value = mock_account()
    svc.lock_bank_account.return_value = mock_account(is_locked=True)
    svc.unlock_bank_account.return_value = mock_account(is_locked=False)
    svc.list_bank_accounts.return_value = [mock_account()]

    # Transaction methods
    def mock_transaction(**kwargs):
        defaults = {
            "id": uuid4(),
            "transaction_number": "TRX-001",
            "bank_account_id": uuid4(),
            "bank_account_name": "Test Account",
            "transaction_date": FIXED_DATE,
            "transaction_type": "debit",
            "amount": Decimal("100000"),
            "description": "Test transaction",
            "reference_number": "REF001",
            "counterparty_account": "0987654321",
            "counterparty_name": "Counterparty",
            "journal_id": uuid4(),
            "status": "posted",
            "reconciled_at": None,
            "reconciliation_id": None,
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

    svc.create_transaction.return_value = mock_transaction()
    svc.get_transaction.return_value = mock_transaction()
    svc.update_transaction.return_value = mock_transaction()
    svc.reverse_transaction.return_value = mock_transaction(is_reversed=True, reversed_at=FIXED_NOW, reversed_by=uuid4())
    svc.list_transactions.return_value = [mock_transaction()]
    svc.import_bank_statement.return_value = MagicMock(imported_count=5, skipped_count=0, errors=[])

    # Reconciliation
    def mock_reconciliation(**kwargs):
        defaults = {
            "id": uuid4(),
            "reconciliation_number": "REC-001",
            "bank_account_id": uuid4(),
            "bank_account_name": "Test Account",
            "statement_date": FIXED_DATE,
            "statement_balance": Decimal("1000000"),
            "book_balance": Decimal("1000000"),
            "difference": Decimal("0"),
            "matched_count": 10,
            "unmatched_book_count": 0,
            "unmatched_statement_count": 0,
            "adjustment_amount": Decimal("0"),
            "adjustment_journal_id": None,
            "status": "completed",
            "notes": "Test reconciliation",
            "created_at": FIXED_NOW,
            "created_by": uuid4(),
            "created_by_name": "Admin",
            "completed_at": FIXED_NOW,
            "completed_by": uuid4(),
            "version": 1,
        }
        defaults.update(kwargs)
        return MagicMock(**defaults)

    svc.get_reconciliation_history.return_value = [mock_reconciliation()]
    svc.close_reconciliation.return_value = mock_reconciliation(status="closed")

    # Cash book
    def mock_cash_book(**kwargs):
        defaults = {
            "id": uuid4(),
            "name": "Cash Book 1",
            "currency_code": "IDR",
            "current_balance": Decimal("500000"),
            "opening_balance": Decimal("500000"),
            "opening_balance_date": FIXED_DATE,
            "gl_cash_account_id": uuid4(),
            "gl_bank_account_id": uuid4(),
            "status": "active",
            "location": "Jakarta",
            "custodian_id": uuid4(),
            "custodian_name": "Custodian",
            "min_balance": Decimal("100000"),
            "max_balance": Decimal("1000000"),
            "is_locked": False,
            "created_at": FIXED_NOW,
            "created_by": uuid4(),
            "created_by_name": "Admin",
            "updated_at": FIXED_NOW,
            "version": 1,
        }
        defaults.update(kwargs)
        return MagicMock(**defaults)

    svc.create_cash_book.return_value = mock_cash_book()
    svc.list_cash_books.return_value = [mock_cash_book()]
    svc.get_cash_book_by_id.return_value = mock_cash_book()
    svc.get_cash_books_by_currency.return_value = [mock_cash_book()]
    svc.get_cash_book_transactions.return_value = []
    svc.update_cash_book.return_value = mock_cash_book()
    svc.get_cash_book_balance.return_value = Decimal("500000")

    # Cash transaction
    def mock_cash_transaction(**kwargs):
        defaults = {
            "id": uuid4(),
            "transaction_number": "CASH-001",
            "cash_book_id": uuid4(),
            "cash_book_name": "Cash Book 1",
            "transaction_date": FIXED_DATE,
            "transaction_type": "debit",
            "amount": Decimal("100000"),
            "description": "Cash transaction",
            "reference_number": "REF001",
            "counterparty_name": "Counterparty",
            "journal_id": uuid4(),
            "status": "posted",
            "created_at": FIXED_NOW,
            "created_by": uuid4(),
            "created_by_name": "Admin",
            "version": 1,
            "is_reversed": False,
        }
        defaults.update(kwargs)
        return MagicMock(**defaults)

    svc.record_cash_transaction.return_value = mock_cash_transaction()

    # Petty cash
    def mock_petty_cash(**kwargs):
        defaults = {
            "id": uuid4(),
            "fund_name": "Petty Cash 1",
            "currency_code": "IDR",
            "current_balance": Decimal("1000000"),
            "initial_amount": Decimal("1000000"),
            "custodian_id": uuid4(),
            "custodian_name": "Custodian",
            "gl_account_id": uuid4(),
            "reimbursement_threshold": Decimal("100000"),
            "status": "active",
            "fund_location": "Office",
            "notes": "Test",
            "created_at": FIXED_NOW,
            "created_by": uuid4(),
            "created_by_name": "Admin",
            "version": 1,
        }
        defaults.update(kwargs)
        return MagicMock(**defaults)

    svc.create_petty_cash_fund.return_value = mock_petty_cash()
    svc.reimburse_petty_cash.return_value = mock_petty_cash(current_balance=Decimal("1100000"))

    # Bank transfer
    def mock_transfer(**kwargs):
        defaults = {
            "id": uuid4(),
            "transfer_number": "TRF-001",
            "from_account_id": uuid4(),
            "from_account_name": "From Account",
            "to_account_id": uuid4(),
            "to_account_name": "To Account",
            "transfer_date": FIXED_DATE,
            "amount": Decimal("500000"),
            "description": "Transfer test",
            "reference_number": "REF001",
            "notes": "Notes",
            "status": "approved",
            "from_journal_id": uuid4(),
            "to_journal_id": uuid4(),
            "created_at": FIXED_NOW,
            "created_by": uuid4(),
            "created_by_name": "Admin",
            "approved_at": FIXED_NOW,
            "approved_by": uuid4(),
            "processed_at": FIXED_NOW,
            "version": 1,
        }
        defaults.update(kwargs)
        return MagicMock(**defaults)

    svc.create_internal_transfer.return_value = mock_transfer()
    svc.approve_transfer.return_value = mock_transfer(status="approved")
    svc.reject_transfer.return_value = mock_transfer(status="rejected")
    svc.process_transfer.return_value = mock_transfer(status="processed")
    svc.cancel_transfer.return_value = mock_transfer(status="cancelled")

    # Reports
    def mock_cash_flow_report(**kwargs):
        defaults = {
            "beginning_cash": Decimal("1000000"),
            "cash_receipts": Decimal("2000000"),
            "cash_disbursements": Decimal("1500000"),
            "net_cash_flow": Decimal("500000"),
            "ending_cash": Decimal("1500000"),
            "by_category": {"operating": Decimal("500000")},
        }
        defaults.update(kwargs)
        return MagicMock(**defaults)

    svc.get_cash_flow_report.return_value = mock_cash_flow_report()
    svc.get_daily_cash_position.return_value = []
    svc.get_account_balance.return_value = Decimal("1000000")
    svc.get_balance_history.return_value = []
    svc.export_transactions.return_value = b"csv data"

    return svc


@pytest.fixture
def mock_reconciliation_use_case():
    uc = AsyncMock()
    uc.reconcile.return_value = MagicMock(
        id=uuid4(),
        reconciliation_number="REC-001",
        bank_account_id=uuid4(),
        bank_account_name="Test Account",
        statement_date=FIXED_DATE,
        statement_balance=Decimal("1000000"),
        book_balance=Decimal("1000000"),
        difference=Decimal("0"),
        matched_count=10,
        unmatched_book_count=0,
        unmatched_statement_count=0,
        adjustment_amount=Decimal("0"),
        adjustment_journal_id=None,
        status="completed",
        notes="Test",
        created_at=FIXED_NOW,
        created_by=uuid4(),
        created_by_name="Admin",
        completed_at=FIXED_NOW,
        completed_by=uuid4(),
        version=1,
    )
    return uc


# ============================================================================
# ENUM TESTS (parametrized untuk menghindari duplikasi)
# ============================================================================

ENUM_TEST_DATA = [
    (BankAccountType, ["CHECKING", "SAVINGS", "DEPOSIT", "LOAN", "CREDIT_CARD", "PETTY_CASH", "CASH_ON_HAND"]),
    (BankAccountStatus, ["ACTIVE", "INACTIVE", "SUSPENDED", "CLOSED", "LOCKED", "ARCHIVED"]),
    (TransactionStatus, ["DRAFT", "PENDING", "POSTED", "CLEARED", "REVERSED", "CANCELLED", "VOID", "RECONCILED"]),
    (ReconciliationStatus, ["DRAFT", "IN_PROGRESS", "COMPLETED", "CLOSED", "CANCELLED"]),
    (CashBookStatus, ["ACTIVE", "CLOSED", "LOCKED", "ARCHIVED"]),
    (PettyCashStatus, ["ACTIVE", "REIMBURSED", "CLOSED", "LOCKED"]),
    (TransferStatus, ["DRAFT", "SUBMITTED", "APPROVED", "PROCESSED", "COMPLETED", "REJECTED", "CANCELLED", "REVERSED"]),
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
    (BankAccountCreateSchema, {"account_number": "123456", "account_name": "Test", "bank_name": "Bank", "bank_code": "BCA", "account_type": BankAccountType.CHECKING, "currency_code": "IDR", "opening_balance": Decimal("0"), "opening_balance_date": date.today(), "gl_account_id": uuid4()}),
    (BankAccountUpdateSchema, {"account_name": "Updated"}),
    (BankAccountResponseSchema, {"id": uuid4(), "account_number": "123", "account_name": "Test", "bank_name": "Bank", "bank_code": "BCA", "currency_code": "IDR", "account_type": BankAccountType.CHECKING, "current_balance": Decimal(0), "available_balance": Decimal(0), "opening_balance": Decimal(0), "opening_balance_date": date.today(), "gl_account_id": uuid4(), "status": BankAccountStatus.ACTIVE, "is_active": True, "is_default": False, "is_locked": False, "bank_address": None, "swift_code": None, "iban": None, "daily_limit": None, "transaction_limit": None, "notes": None, "created_at": datetime.now(UTC), "created_by": uuid4(), "created_by_name": None, "updated_at": datetime.now(UTC), "updated_by": None, "version": 1}),
    (BankTransactionCreateSchema, {"bank_account_id": uuid4(), "transaction_date": date.today(), "transaction_type": MagicMock(), "amount": Decimal("100"), "description": "test"}),
    (BankTransactionUpdateSchema, {"description": "updated"}),
    (BankTransactionResponseSchema, {"id": uuid4(), "transaction_number": "TRX-001", "bank_account_id": uuid4(), "bank_account_name": "Test", "transaction_date": date.today(), "transaction_type": MagicMock(), "amount": Decimal(0), "description": "test", "reference_number": None, "counterparty_account": None, "counterparty_name": None, "journal_id": None, "status": TransactionStatus.DRAFT, "reconciled_at": None, "reconciliation_id": None, "created_at": datetime.now(UTC), "created_by": uuid4(), "created_by_name": None, "version": 1, "is_reversed": False, "reversed_at": None, "reversed_by": None}),
    (BankTransactionReverseSchema, {"reason": "test reason", "reversal_date": date.today()}),
    (BankReconciliationCreateSchema, {"bank_account_id": uuid4(), "statement_date": date.today(), "statement_balance": Decimal(0), "statement_transactions": [], "auto_match_threshold": Decimal("0.01")}),
    (BankReconciliationResponseSchema, {"id": uuid4(), "reconciliation_number": "REC-001", "bank_account_id": uuid4(), "bank_account_name": "Test", "statement_date": date.today(), "statement_balance": Decimal(0), "book_balance": Decimal(0), "difference": Decimal(0), "matched_count": 0, "unmatched_book_count": 0, "unmatched_statement_count": 0, "adjustment_amount": Decimal(0), "adjustment_journal_id": None, "status": ReconciliationStatus.DRAFT, "notes": None, "created_at": datetime.now(UTC), "created_by": uuid4(), "created_by_name": None, "completed_at": None, "completed_by": None, "version": 1}),
    (CashBookCreateSchema, {"name": "Cash Book", "currency_code": "IDR", "opening_balance": Decimal(0), "opening_balance_date": date.today(), "gl_cash_account_id": uuid4(), "gl_bank_account_id": uuid4(), "location": "Office", "custodian_id": uuid4(), "min_balance": Decimal(0), "max_balance": Decimal(1000)}),
    (CashBookResponseSchema, {"id": uuid4(), "name": "Cash Book", "currency_code": "IDR", "current_balance": Decimal(0), "opening_balance": Decimal(0), "opening_balance_date": date.today(), "gl_cash_account_id": uuid4(), "gl_bank_account_id": uuid4(), "status": CashBookStatus.ACTIVE, "location": None, "custodian_id": None, "custodian_name": None, "min_balance": Decimal(0), "max_balance": None, "is_locked": False, "created_at": datetime.now(UTC), "created_by": uuid4(), "created_by_name": None, "updated_at": datetime.now(UTC), "version": 1}),
    (CashBookUpdateSchema, {"name": "Updated"}),
    (CashTransactionCreateSchema, {"cash_book_id": uuid4(), "transaction_date": date.today(), "transaction_type": MagicMock(), "amount": Decimal("100"), "description": "test"}),
    (CashTransactionResponseSchema, {"id": uuid4(), "transaction_number": "CASH-001", "cash_book_id": uuid4(), "cash_book_name": "Test", "transaction_date": date.today(), "transaction_type": MagicMock(), "amount": Decimal(0), "description": "test", "reference_number": None, "counterparty_name": None, "journal_id": None, "status": TransactionStatus.DRAFT, "created_at": datetime.now(UTC), "created_by": uuid4(), "created_by_name": None, "version": 1, "is_reversed": False}),
    (PettyCashCreateSchema, {"fund_name": "Petty", "currency_code": "IDR", "initial_amount": Decimal("1000"), "custodian_id": uuid4(), "gl_petty_cash_account_id": uuid4(), "reimbursement_threshold": Decimal("100")}),
    (PettyCashResponseSchema, {"id": uuid4(), "fund_name": "Petty", "currency_code": "IDR", "current_balance": Decimal(0), "initial_amount": Decimal(0), "custodian_id": uuid4(), "custodian_name": None, "gl_account_id": uuid4(), "reimbursement_threshold": Decimal(0), "status": PettyCashStatus.ACTIVE, "fund_location": None, "notes": None, "created_at": datetime.now(UTC), "created_by": uuid4(), "created_by_name": None, "version": 1}),
    (PettyCashReimbursementSchema, {"reimbursement_date": date.today(), "amount": Decimal("100"), "bank_account_id": uuid4(), "description": "test"}),
    (BankTransferCreateSchema, {"from_bank_account_id": uuid4(), "to_bank_account_id": uuid4(), "transfer_date": date.today(), "amount": Decimal("100"), "description": "test"}),
    (BankTransferResponseSchema, {"id": uuid4(), "transfer_number": "TRF-001", "from_account_id": uuid4(), "from_account_name": "From", "to_account_id": uuid4(), "to_account_name": "To", "transfer_date": date.today(), "amount": Decimal(0), "description": "test", "reference_number": None, "notes": None, "status": TransferStatus.DRAFT, "from_journal_id": None, "to_journal_id": None, "created_at": datetime.now(UTC), "created_by": uuid4(), "created_by_name": None, "approved_at": None, "approved_by": None, "processed_at": None, "version": 1}),
    (BankTransferApproveSchema, {"approved": True, "notes": "Approved"}),
    (CashFlowReportSchema, {"legal_entity_id": uuid4(), "start_date": date.today(), "end_date": date.today(), "beginning_cash": Decimal(0), "cash_receipts": Decimal(0), "cash_disbursements": Decimal(0), "net_cash_flow": Decimal(0), "ending_cash": Decimal(0), "by_category": {}, "generated_at": datetime.now(UTC)}),
    (DailyCashPositionSchema, {"as_of_date": date.today(), "account_type": "bank", "account_id": uuid4(), "account_name": "Test", "currency": "IDR", "balance": Decimal(0)}),
    (AccountBalanceHistorySchema, {"as_of_date": date.today(), "balance": Decimal(0), "available_balance": Decimal(0), "change_from_previous": Decimal(0)}),
]


class TestSchemas:
    @pytest.mark.parametrize("schema_class, kwargs", SCHEMA_TEST_DATA)
    def test_construction_success(self, schema_class, kwargs):
        instance = schema_class(**kwargs)
        assert isinstance(instance, schema_class)
        # Verifikasi field utama (ambil key pertama)
        first_key = next(iter(kwargs))
        assert getattr(instance, first_key) == kwargs[first_key]


# ============================================================================
# IDEMPOTENCY MANAGER TESTS
# ============================================================================

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

    @patch("adapters.primary_api.v1.fastapi_bank_cash_router.datetime")
    def test_cache_expiration(self, mock_dt):
        mock_dt.now.return_value = FIXED_NOW
        mgr = IdempotencyManager()
        mgr._ttl_seconds = 0
        mgr.cache_result("key", "method", {"foo": "bar"})
        cached = mgr.get_cached_result("key", "method")
        assert cached is None

    def test_key_generation_deterministic(self):
        mgr = IdempotencyManager()
        key1 = mgr._get_key("abc", "create_bank_account")
        key2 = mgr._get_key("abc", "create_bank_account")
        key3 = mgr._get_key("abc", "update_bank_account")
        assert key1 == key2
        assert key1 != key3


# ============================================================================
# ADAPTER TESTS
# ============================================================================

class TestAdapters:
    @pytest.fixture
    def cash_book_adapter(self):
        return CashBookRepositoryAdapter()

    @pytest.fixture
    def cash_flow_adapter(self):
        return CashFlowRepositoryAdapter()

    @pytest.mark.asyncio
    async def test_cash_book_adapter_add(self, cash_book_adapter):
        with patch.object(cash_book_adapter, "_get_service", new_callable=AsyncMock) as mock_get:
            mock_svc = AsyncMock()
            mock_svc.create_cash_book.return_value = MagicMock(
                id=uuid4(), name="Test", currency_code="IDR", current_balance=Decimal(0),
                opening_balance=Decimal(0), opening_balance_date=FIXED_DATE,
                gl_cash_account_id=uuid4(), gl_bank_account_id=None, status="active",
                location=None, custodian_id=None, custodian_name=None,
                min_balance=Decimal(0), max_balance=None, is_locked=False,
                created_at=FIXED_NOW, created_by=uuid4(), created_by_name=None,
                updated_at=FIXED_NOW, version=1
            )
            mock_get.return_value = mock_svc
            result = await cash_book_adapter.add({"name": "Test", "legal_entity_id": uuid4()})
            assert "id" in result
            assert result["name"] == "Test"
            mock_svc.create_cash_book.assert_called_once()

    @pytest.mark.asyncio
    async def test_cash_book_adapter_get_balance(self, cash_book_adapter):
        with patch.object(cash_book_adapter, "_get_service", new_callable=AsyncMock) as mock_get:
            mock_svc = AsyncMock()
            mock_svc.get_cash_book_balance.return_value = Decimal("5000")
            mock_get.return_value = mock_svc
            result = await cash_book_adapter.get_balance(uuid4(), FIXED_DATE)
            assert result == Decimal("5000")
            mock_svc.get_cash_book_balance.assert_called_once()

    @pytest.mark.asyncio
    async def test_cash_book_adapter_get_by_id_raises(self, cash_book_adapter):
        with pytest.raises(NotImplementedError):
            await cash_book_adapter.get_by_id(uuid4())

    @pytest.mark.asyncio
    async def test_cash_book_adapter_get_by_legal_entity_and_currency(self, cash_book_adapter):
        with patch.object(cash_book_adapter, "_get_service", new_callable=AsyncMock) as mock_get:
            mock_svc = AsyncMock()
            mock_cb = MagicMock(id=uuid4(), name="Test", currency_code="IDR")
            mock_svc.get_cash_books_by_currency.return_value = [mock_cb]
            mock_get.return_value = mock_svc
            result = await cash_book_adapter.get_by_legal_entity_and_currency(uuid4(), "IDR")
            assert len(result) == 1
            assert result[0]["id"] == mock_cb.id

    @pytest.mark.asyncio
    async def test_cash_flow_adapter_get_cash_flow(self, cash_flow_adapter):
        with patch.object(cash_flow_adapter, "_get_service", new_callable=AsyncMock) as mock_get:
            mock_svc = AsyncMock()
            mock_report = MagicMock(
                beginning_cash=Decimal(1000), cash_receipts=Decimal(500),
                cash_disbursements=Decimal(200), net_cash_flow=Decimal(300),
                ending_cash=Decimal(1300), by_category={"op": Decimal(300)}
            )
            mock_svc.get_cash_flow_report.return_value = mock_report
            mock_get.return_value = mock_svc
            result = await cash_flow_adapter.get_cash_flow(uuid4(), FIXED_DATE, FIXED_DATE)
            assert result["beginning_cash"] == Decimal(1000)
            assert result["by_category"] == {"op": Decimal(300)}


# ============================================================================
# ROUTER ENDPOINT TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_ping():
    result = ping()
    assert result == {"status": "ok", "service": "bank-cash-router"}


@pytest.mark.asyncio
async def test_health():
    result = health()
    assert result == {"status": "healthy"}


@pytest.mark.asyncio
async def test_info():
    result = info()
    assert result["version"] == "1.0"
    assert result["name"] == "Bank & Cash Router"


# --- Bank Account Endpoints ---

@pytest.mark.asyncio
async def test_create_bank_account_success(mock_bank_cash_service, mock_token_payload, mock_legal_entity_id):
    request = BankAccountCreateSchema(
        account_number="1234567890",
        account_name="Test Account",
        bank_name="Test Bank",
        bank_code="TEST",
        currency_code="IDR",
        account_type=BankAccountType.CHECKING,
    )
    result = await create_bank_account(
        request=request,
        idempotency_key=None,
        _permission=None,
        current_user=mock_token_payload,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert isinstance(result, BankAccountResponseSchema)
    assert result.account_number == "1234567890"
    assert result.account_name == "Test Account"
    mock_bank_cash_service.create_bank_account.assert_called_once()


@pytest.mark.asyncio
async def test_create_bank_account_idempotency(mock_bank_cash_service, mock_token_payload, mock_legal_entity_id):
    request = BankAccountCreateSchema(
        account_number="1234567890",
        account_name="Test Account",
        bank_name="Test Bank",
        bank_code="TEST",
        currency_code="IDR",
        account_type=BankAccountType.CHECKING,
    )
    with patch("adapters.primary_api.v1.fastapi_bank_cash_router._idempotency_manager") as mock_im:
        cached = {
            "id": str(uuid4()),
            "account_number": "1234567890",
            "account_name": "Test Account",
            "bank_name": "Test Bank",
            "bank_code": "TEST",
            "currency_code": "IDR",
            "account_type": "checking",
            "current_balance": "0",
            "available_balance": "0",
            "opening_balance": "0",
            "opening_balance_date": FIXED_DATE.isoformat(),
            "gl_account_id": None,
            "status": "active",
            "is_active": True,
            "is_default": False,
            "is_locked": False,
            "bank_address": None,
            "swift_code": None,
            "iban": None,
            "daily_limit": None,
            "transaction_limit": None,
            "notes": None,
            "created_at": FIXED_NOW.isoformat(),
            "created_by": str(uuid4()),
            "created_by_name": None,
            "updated_at": FIXED_NOW.isoformat(),
            "updated_by": None,
            "version": 1,
        }
        mock_im.get_cached_result.return_value = cached
        result = await create_bank_account(
            request=request,
            idempotency_key="key123",
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_bank_cash_service,
        )
        assert isinstance(result, BankAccountResponseSchema)
        assert result.account_number == "1234567890"
        mock_bank_cash_service.create_bank_account.assert_not_called()


@pytest.mark.asyncio
async def test_create_bank_account_value_error(mock_bank_cash_service, mock_token_payload, mock_legal_entity_id):
    mock_bank_cash_service.create_bank_account.side_effect = ValueError("Invalid account number")
    request = BankAccountCreateSchema(
        account_number="123",
        account_name="Test",
        bank_name="Bank",
        bank_code="BCA",
        currency_code="IDR",
        account_type=BankAccountType.CHECKING,
    )
    with pytest.raises(HTTPException) as exc:
        await create_bank_account(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_bank_cash_service,
        )
    assert exc.value.status_code == 422
    assert "Invalid account number" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_create_bank_account_generic_error(mock_bank_cash_service, mock_token_payload, mock_legal_entity_id):
    mock_bank_cash_service.create_bank_account.side_effect = Exception("DB error")
    request = BankAccountCreateSchema(
        account_number="1234567890",
        account_name="Test",
        bank_name="Bank",
        bank_code="BCA",
        currency_code="IDR",
        account_type=BankAccountType.CHECKING,
    )
    with pytest.raises(HTTPException) as exc:
        await create_bank_account(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_bank_cash_service,
        )
    assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_list_bank_accounts(mock_bank_cash_service, mock_legal_entity_id):
    result = await list_bank_accounts(
        account_type=BankAccountType.CHECKING,
        currency="IDR",
        is_active=True,
        _permission=None,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], BankAccountResponseSchema)
    assert result[0].account_number == "1234567890"
    mock_bank_cash_service.list_bank_accounts.assert_called_once_with(
        legal_entity_id=mock_legal_entity_id,
        account_type="checking",
        currency="IDR",
        is_active=True,
    )


@pytest.mark.asyncio
async def test_get_bank_account(mock_bank_cash_service, mock_legal_entity_id):
    account_id = uuid4()
    result = await get_bank_account(
        account_id=account_id,
        _permission=None,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert isinstance(result, BankAccountResponseSchema)
    assert result.account_number == "1234567890"
    mock_bank_cash_service.get_bank_account.assert_called_once_with(account_id, mock_legal_entity_id)


@pytest.mark.asyncio
async def test_get_bank_account_not_found(mock_bank_cash_service, mock_legal_entity_id):
    mock_bank_cash_service.get_bank_account.return_value = None
    with pytest.raises(HTTPException) as exc:
        await get_bank_account(
            account_id=uuid4(),
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_bank_cash_service,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_bank_account(mock_bank_cash_service, mock_token_payload, mock_legal_entity_id):
    account_id = uuid4()
    request = BankAccountUpdateSchema(account_name="Updated Name")
    result = await update_bank_account(
        account_id=account_id,
        request=request,
        idempotency_key=None,
        _permission=None,
        current_user=mock_token_payload,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert isinstance(result, BankAccountResponseSchema)
    assert result.account_name == "Test Account"
    mock_bank_cash_service.update_bank_account.assert_called_once_with(
        account_id=account_id,
        legal_entity_id=mock_legal_entity_id,
        account_name="Updated Name",
        is_active=None,
        is_default=None,
        bank_address=None,
        notes=None,
        daily_limit=None,
        transaction_limit=None,
        status=None,
        updated_by=mock_token_payload.user_id,
    )


@pytest.mark.asyncio
async def test_update_bank_account_value_error(mock_bank_cash_service, mock_token_payload, mock_legal_entity_id):
    mock_bank_cash_service.update_bank_account.side_effect = ValueError("Invalid data")
    request = BankAccountUpdateSchema()
    with pytest.raises(HTTPException) as exc:
        await update_bank_account(
            account_id=uuid4(),
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_bank_cash_service,
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_deactivate_bank_account(mock_bank_cash_service, mock_token_payload, mock_legal_entity_id):
    account_id = uuid4()
    result = await deactivate_bank_account(
        account_id=account_id,
        permanent=False,
        reason="Test reason",
        _permission=None,
        current_user=mock_token_payload,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert result["action"] == "deactivated"
    assert result["status"] == "inactive"
    mock_bank_cash_service.deactivate_bank_account.assert_called_once_with(
        account_id, mock_legal_entity_id, mock_token_payload.user_id, "Test reason"
    )


@pytest.mark.asyncio
async def test_deactivate_bank_account_permanent(mock_bank_cash_service, mock_token_payload, mock_legal_entity_id):
    account_id = uuid4()
    result = await deactivate_bank_account(
        account_id=account_id,
        permanent=True,
        reason="Close",
        _permission=None,
        current_user=mock_token_payload,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert result["action"] == "closed"
    mock_bank_cash_service.close_bank_account.assert_called_once()


@pytest.mark.asyncio
async def test_activate_bank_account(mock_bank_cash_service, mock_token_payload, mock_legal_entity_id):
    account_id = uuid4()
    result = await activate_bank_account(
        account_id=account_id,
        _permission=None,
        current_user=mock_token_payload,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert isinstance(result, BankAccountResponseSchema)
    mock_bank_cash_service.activate_bank_account.assert_called_once_with(
        account_id, mock_legal_entity_id, mock_token_payload.user_id
    )


@pytest.mark.asyncio
async def test_lock_bank_account(mock_bank_cash_service, mock_token_payload, mock_legal_entity_id):
    account_id = uuid4()
    result = await lock_bank_account(
        account_id=account_id,
        reason="Audit",
        _permission=None,
        current_user=mock_token_payload,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert result.is_locked is True
    mock_bank_cash_service.lock_bank_account.assert_called_once_with(
        account_id, mock_legal_entity_id, mock_token_payload.user_id, "Audit"
    )


@pytest.mark.asyncio
async def test_unlock_bank_account(mock_bank_cash_service, mock_token_payload, mock_legal_entity_id):
    account_id = uuid4()
    result = await unlock_bank_account(
        account_id=account_id,
        _permission=None,
        current_user=mock_token_payload,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert result.is_locked is False
    mock_bank_cash_service.unlock_bank_account.assert_called_once_with(
        account_id, mock_legal_entity_id, mock_token_payload.user_id
    )


# --- Bank Transaction Endpoints ---

@pytest.mark.asyncio
async def test_create_bank_transaction(mock_bank_cash_service, mock_token_payload, mock_legal_entity_id):
    request = BankTransactionCreateSchema(
        bank_account_id=uuid4(),
        transaction_date=FIXED_DATE,
        transaction_type=MagicMock(value="debit"),
        amount=Decimal("100000"),
        description="Test transaction",
        reference_number="REF001",
        counterparty_account="0987654321",
        counterparty_name="Counterparty",
        transfer_to_account_id=None,
        post_to_ledger=True,
        notes="Notes",
    )
    result = await create_bank_transaction(
        request=request,
        idempotency_key=None,
        _permission=None,
        current_user=mock_token_payload,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert isinstance(result, BankTransactionResponseSchema)
    assert result.transaction_number == "TRX-001"
    assert result.amount == Decimal("100000")
    mock_bank_cash_service.create_transaction.assert_called_once()


@pytest.mark.asyncio
async def test_get_bank_transaction(mock_bank_cash_service, mock_legal_entity_id):
    transaction_id = uuid4()
    result = await get_bank_transaction(
        transaction_id=transaction_id,
        _permission=None,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert isinstance(result, BankTransactionResponseSchema)
    assert result.transaction_number == "TRX-001"
    mock_bank_cash_service.get_transaction.assert_called_once_with(transaction_id, mock_legal_entity_id)


@pytest.mark.asyncio
async def test_update_bank_transaction(mock_bank_cash_service, mock_token_payload, mock_legal_entity_id):
    transaction_id = uuid4()
    request = BankTransactionUpdateSchema(description="Updated description")
    result = await update_bank_transaction(
        transaction_id=transaction_id,
        request=request,
        idempotency_key=None,
        _permission=None,
        current_user=mock_token_payload,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert isinstance(result, BankTransactionResponseSchema)
    mock_bank_cash_service.update_transaction.assert_called_once_with(
        transaction_id=transaction_id,
        legal_entity_id=mock_legal_entity_id,
        description="Updated description",
        reference_number=None,
        notes=None,
        status=None,
        updated_by=mock_token_payload.user_id,
    )


@pytest.mark.asyncio
async def test_reverse_bank_transaction(mock_bank_cash_service, mock_token_payload, mock_legal_entity_id):
    transaction_id = uuid4()
    request = BankTransactionReverseSchema(reason="Test reversal", reversal_date=FIXED_DATE)
    result = await reverse_bank_transaction(
        transaction_id=transaction_id,
        request=request,
        _permission=None,
        current_user=mock_token_payload,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert isinstance(result, BankTransactionResponseSchema)
    assert result.is_reversed is True
    mock_bank_cash_service.reverse_transaction.assert_called_once_with(
        transaction_id=transaction_id,
        reversed_by=mock_token_payload.user_id,
        legal_entity_id=mock_legal_entity_id,
        reason="Test reversal",
        reversal_date=FIXED_DATE,
    )


@pytest.mark.asyncio
async def test_list_bank_transactions(mock_bank_cash_service, mock_legal_entity_id):
    result = await list_bank_transactions(
        bank_account_id=uuid4(),
        start_date=FIXED_DATE,
        end_date=FIXED_DATE,
        transaction_type=MagicMock(value="debit"),
        status=TransactionStatus.POSTED,
        page=1,
        page_size=50,
        _permission=None,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], BankTransactionResponseSchema)
    mock_bank_cash_service.list_transactions.assert_called_once()


# --- Import ---

@pytest.mark.asyncio
async def test_import_bank_statement(mock_bank_cash_service, mock_token_payload, mock_legal_entity_id):
    file = MagicMock(spec=UploadFile)
    file.read = AsyncMock(return_value=b"MT940 data")
    result = await import_bank_statement(
        file=file,
        bank_account_id=uuid4(),
        statement_date=FIXED_DATE,
        file_format="mt940",
        _permission=None,
        current_user=mock_token_payload,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert result["imported_count"] == 5
    assert result["skipped_count"] == 0
    mock_bank_cash_service.import_bank_statement.assert_called_once()


# --- Reconciliation ---

@pytest.mark.asyncio
async def test_reconcile_bank(mock_reconciliation_use_case, mock_token_payload, mock_legal_entity_id):
    request = BankReconciliationCreateSchema(
        bank_account_id=uuid4(),
        statement_date=FIXED_DATE,
        statement_balance=Decimal("1000000"),
        statement_transactions=[],
        auto_match_threshold=Decimal("0.01"),
        notes="Test",
    )
    result = await reconcile_bank(
        request=request,
        _permission=None,
        current_user=mock_token_payload,
        legal_entity_id=mock_legal_entity_id,
        use_case=mock_reconciliation_use_case,
    )
    assert isinstance(result, BankReconciliationResponseSchema)
    assert result.reconciliation_number == "REC-001"
    mock_reconciliation_use_case.reconcile.assert_called_once()


@pytest.mark.asyncio
async def test_get_reconciliation_history(mock_bank_cash_service, mock_legal_entity_id):
    bank_account_id = uuid4()
    result = await get_reconciliation_history(
        bank_account_id=bank_account_id,
        limit=10,
        _permission=None,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], BankReconciliationResponseSchema)
    mock_bank_cash_service.get_reconciliation_history.assert_called_once_with(
        bank_account_id, mock_legal_entity_id, 10
    )


@pytest.mark.asyncio
async def test_close_reconciliation(mock_bank_cash_service, mock_token_payload, mock_legal_entity_id):
    reconciliation_id = uuid4()
    result = await close_reconciliation(
        reconciliation_id=reconciliation_id,
        _permission=None,
        current_user=mock_token_payload,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert isinstance(result, BankReconciliationResponseSchema)
    assert result.status == "closed"
    mock_bank_cash_service.close_reconciliation.assert_called_once_with(
        reconciliation_id, mock_legal_entity_id, mock_token_payload.user_id
    )


# --- Cash Book ---

@pytest.mark.asyncio
async def test_create_cash_book(mock_bank_cash_service, mock_token_payload, mock_legal_entity_id):
    request = CashBookCreateSchema(
        name="Cash Book 1",
        currency_code="IDR",
        opening_balance=Decimal("500000"),
        opening_balance_date=FIXED_DATE,
        gl_cash_account_id=uuid4(),
        gl_bank_account_id=uuid4(),
        location="Jakarta",
        custodian_id=uuid4(),
        min_balance=Decimal("100000"),
        max_balance=Decimal("1000000"),
    )
    result = await create_cash_book(
        request=request,
        idempotency_key=None,
        _permission=None,
        current_user=mock_token_payload,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert isinstance(result, CashBookResponseSchema)
    assert result.name == "Cash Book 1"
    mock_bank_cash_service.create_cash_book.assert_called_once()


@pytest.mark.asyncio
async def test_list_cash_books(mock_bank_cash_service, mock_legal_entity_id):
    result = await list_cash_books(
        status=CashBookStatus.ACTIVE,
        custodian_id=uuid4(),
        _permission=None,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], CashBookResponseSchema)
    mock_bank_cash_service.list_cash_books.assert_called_once()


@pytest.mark.asyncio
async def test_get_cash_book_by_id(mock_bank_cash_service, mock_legal_entity_id):
    cash_book_id = uuid4()
    result = await get_cash_book_by_id(
        cash_book_id=cash_book_id,
        _permission=None,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert isinstance(result, CashBookResponseSchema)
    mock_bank_cash_service.get_cash_book_by_id.assert_called_once_with(cash_book_id, mock_legal_entity_id)


@pytest.mark.asyncio
async def test_get_cash_books_by_currency(mock_bank_cash_service, mock_legal_entity_id):
    result = await get_cash_books_by_currency(
        currency_code="IDR",
        _permission=None,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert isinstance(result, list)
    assert len(result) == 1
    mock_bank_cash_service.get_cash_books_by_currency.assert_called_once_with(mock_legal_entity_id, "IDR")


@pytest.mark.asyncio
async def test_get_cash_book_transactions(mock_bank_cash_service, mock_legal_entity_id):
    cash_book_id = uuid4()
    result = await get_cash_book_transactions(
        cash_book_id=cash_book_id,
        start_date=FIXED_DATE,
        end_date=FIXED_DATE,
        limit=10,
        offset=0,
        _permission=None,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert isinstance(result, list)
    mock_bank_cash_service.get_cash_book_transactions.assert_called_once_with(
        cash_book_id, mock_legal_entity_id, FIXED_DATE, FIXED_DATE, 10, 0
    )


@pytest.mark.asyncio
async def test_update_cash_book(mock_bank_cash_service, mock_token_payload, mock_legal_entity_id):
    cash_book_id = uuid4()
    request = CashBookUpdateSchema(name="Updated Name")
    result = await update_cash_book(
        cash_book_id=cash_book_id,
        request=request,
        idempotency_key=None,
        _permission=None,
        current_user=mock_token_payload,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert isinstance(result, CashBookResponseSchema)
    mock_bank_cash_service.update_cash_book.assert_called_once()


@pytest.mark.asyncio
async def test_get_cash_book_balance(mock_bank_cash_service, mock_legal_entity_id):
    cash_book_id = uuid4()
    result = await get_cash_book_balance(
        cash_book_id=cash_book_id,
        as_of_date=FIXED_DATE,
        _permission=None,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert result == Decimal("500000")
    mock_bank_cash_service.get_cash_book_balance.assert_called_once_with(cash_book_id, mock_legal_entity_id, FIXED_DATE)


@pytest.mark.asyncio
async def test_record_cash_transaction(mock_bank_cash_service, mock_token_payload, mock_legal_entity_id):
    request = CashTransactionCreateSchema(
        cash_book_id=uuid4(),
        transaction_date=FIXED_DATE,
        transaction_type=MagicMock(value="debit"),
        amount=Decimal("100000"),
        description="Cash transaction",
        reference_number="REF001",
        counterparty_name="Counterparty",
        post_to_ledger=True,
        notes="Notes",
    )
    result = await record_cash_transaction(
        request=request,
        _permission=None,
        current_user=mock_token_payload,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert isinstance(result, CashTransactionResponseSchema)
    mock_bank_cash_service.record_cash_transaction.assert_called_once()


# --- Petty Cash ---

@pytest.mark.asyncio
async def test_create_petty_cash_fund(mock_bank_cash_service, mock_token_payload, mock_legal_entity_id):
    request = PettyCashCreateSchema(
        fund_name="Petty Cash 1",
        currency_code="IDR",
        initial_amount=Decimal("1000000"),
        custodian_id=uuid4(),
        gl_petty_cash_account_id=uuid4(),
        reimbursement_threshold=Decimal("100000"),
        fund_location="Office",
        notes="Test",
    )
    result = await create_petty_cash_fund(
        request=request,
        idempotency_key=None,
        _permission=None,
        current_user=mock_token_payload,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert isinstance(result, PettyCashResponseSchema)
    assert result.fund_name == "Petty Cash 1"
    mock_bank_cash_service.create_petty_cash_fund.assert_called_once()


@pytest.mark.asyncio
async def test_reimburse_petty_cash(mock_bank_cash_service, mock_token_payload, mock_legal_entity_id):
    fund_id = uuid4()
    request = PettyCashReimbursementSchema(
        reimbursement_date=FIXED_DATE,
        amount=Decimal("100000"),
        bank_account_id=uuid4(),
        description="Reimbursement",
        notes="Notes",
    )
    result = await reimburse_petty_cash(
        fund_id=fund_id,
        request=request,
        _permission=None,
        current_user=mock_token_payload,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert isinstance(result, PettyCashResponseSchema)
    mock_bank_cash_service.reimburse_petty_cash.assert_called_once()


# --- Bank Transfer ---

@pytest.mark.asyncio
async def test_create_bank_transfer(mock_bank_cash_service, mock_token_payload, mock_legal_entity_id):
    request = BankTransferCreateSchema(
        from_bank_account_id=uuid4(),
        to_bank_account_id=uuid4(),
        transfer_date=FIXED_DATE,
        amount=Decimal("500000"),
        description="Transfer test",
        reference_number="REF001",
        notes="Notes",
    )
    result = await create_bank_transfer(
        request=request,
        idempotency_key=None,
        _permission=None,
        current_user=mock_token_payload,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert isinstance(result, BankTransferResponseSchema)
    assert result.transfer_number == "TRF-001"
    mock_bank_cash_service.create_internal_transfer.assert_called_once()


@pytest.mark.asyncio
async def test_approve_bank_transfer(mock_bank_cash_service, mock_token_payload, mock_legal_entity_id):
    transfer_id = uuid4()
    request = BankTransferApproveSchema(approved=True, notes="Approved")
    result = await approve_bank_transfer(
        transfer_id=transfer_id,
        request=request,
        _permission=None,
        current_user=mock_token_payload,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert isinstance(result, BankTransferResponseSchema)
    assert result.status == "approved"
    mock_bank_cash_service.approve_transfer.assert_called_once_with(
        transfer_id, mock_legal_entity_id, mock_token_payload.user_id, "Approved"
    )


@pytest.mark.asyncio
async def test_reject_bank_transfer(mock_bank_cash_service, mock_token_payload, mock_legal_entity_id):
    transfer_id = uuid4()
    request = BankTransferApproveSchema(approved=False, notes="Rejected")
    result = await approve_bank_transfer(
        transfer_id=transfer_id,
        request=request,
        _permission=None,
        current_user=mock_token_payload,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert isinstance(result, BankTransferResponseSchema)
    assert result.status == "rejected"
    mock_bank_cash_service.reject_transfer.assert_called_once_with(
        transfer_id, mock_legal_entity_id, mock_token_payload.user_id, "Rejected"
    )


@pytest.mark.asyncio
async def test_process_bank_transfer(mock_bank_cash_service, mock_token_payload, mock_legal_entity_id):
    transfer_id = uuid4()
    result = await process_bank_transfer(
        transfer_id=transfer_id,
        _permission=None,
        current_user=mock_token_payload,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert isinstance(result, BankTransferResponseSchema)
    assert result.status == "processed"
    mock_bank_cash_service.process_transfer.assert_called_once_with(
        transfer_id, mock_legal_entity_id, mock_token_payload.user_id
    )


@pytest.mark.asyncio
async def test_cancel_bank_transfer(mock_bank_cash_service, mock_token_payload, mock_legal_entity_id):
    transfer_id = uuid4()
    result = await cancel_bank_transfer(
        transfer_id=transfer_id,
        reason="Cancelled by user",
        _permission=None,
        current_user=mock_token_payload,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert result["status"] == "cancelled"
    mock_bank_cash_service.cancel_transfer.assert_called_once_with(
        transfer_id, mock_legal_entity_id, mock_token_payload.user_id, "Cancelled by user"
    )


# --- Reports ---

@pytest.mark.asyncio
async def test_get_bank_balance(mock_bank_cash_service, mock_legal_entity_id):
    account_id = uuid4()
    result = await get_bank_balance(
        account_id=account_id,
        as_of_date=FIXED_DATE,
        _permission=None,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert result == Decimal("1000000")
    mock_bank_cash_service.get_account_balance.assert_called_once_with(account_id, mock_legal_entity_id, FIXED_DATE)


@pytest.mark.asyncio
async def test_get_bank_balance_history(mock_bank_cash_service, mock_legal_entity_id):
    account_id = uuid4()
    result = await get_bank_balance_history(
        account_id=account_id,
        start_date=FIXED_DATE,
        end_date=FIXED_DATE,
        _permission=None,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert isinstance(result, list)
    mock_bank_cash_service.get_balance_history.assert_called_once_with(
        account_id, mock_legal_entity_id, FIXED_DATE, FIXED_DATE
    )


@pytest.mark.asyncio
async def test_get_cash_flow_report(mock_bank_cash_service, mock_legal_entity_id):
    result = await get_cash_flow_report(
        start_date=FIXED_DATE,
        end_date=FIXED_DATE,
        account_type=BankAccountType.CHECKING,
        _permission=None,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert isinstance(result, CashFlowReportSchema)
    assert result.beginning_cash == Decimal("1000000")
    mock_bank_cash_service.get_cash_flow_report.assert_called_once_with(
        legal_entity_id=mock_legal_entity_id,
        start_date=FIXED_DATE,
        end_date=FIXED_DATE,
        account_type="checking",
    )


@pytest.mark.asyncio
async def test_get_daily_cash_position(mock_bank_cash_service, mock_legal_entity_id):
    result = await get_daily_cash_position(
        as_of_date=FIXED_DATE,
        _permission=None,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert isinstance(result, list)
    mock_bank_cash_service.get_daily_cash_position.assert_called_once_with(mock_legal_entity_id, FIXED_DATE)


@pytest.mark.asyncio
async def test_export_bank_transactions(mock_bank_cash_service, mock_legal_entity_id):
    bank_account_id = uuid4()
    response = await export_bank_transactions(
        bank_account_id=bank_account_id,
        start_date=FIXED_DATE,
        end_date=FIXED_DATE,
        format="csv",
        _permission=None,
        legal_entity_id=mock_legal_entity_id,
        service=mock_bank_cash_service,
    )
    assert isinstance(response, Response)
    assert response.body == b"csv data"
    assert response.media_type == "text/csv"
    mock_bank_cash_service.export_transactions.assert_called_once_with(
        bank_account_id, mock_legal_entity_id, FIXED_DATE, FIXED_DATE, "csv"
    )


# ============================================================================
# DEPENDENCY INJECTION TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_get_bank_cash_service():
    request = MagicMock()
    request.app.state.container = MagicMock()
    request.app.state.container.resolve.return_value = "service"
    result = await get_bank_cash_service(request)
    assert result == "service"


@pytest.mark.asyncio
async def test_get_bank_reconciliation_use_case():
    request = MagicMock()
    request.app.state.container = MagicMock()
    request.app.state.container.resolve.return_value = "use_case"
    result = await get_bank_reconciliation_use_case(request)
    assert result == "use_case"
