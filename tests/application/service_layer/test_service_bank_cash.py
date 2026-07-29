# tests/application/service_layer/test_service_bank_cash.py
"""
Comprehensive tests for application/service_layer/service_bank_cash.py
Covers all public methods, private helpers, edge cases, and exceptions.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from application.service_layer.service_bank_cash import (
    BankAccountClosedError,
    BankAccountNotFoundError,
    BankAccountResponse,
    BankCashService,
    BankCashServiceError,
    BankReconciliationRequest,
    BankReconciliationResponse,
    BankTransactionRequest,
    BankTransactionResponse,
    CashDisbursementRequest,
    CashReceiptRequest,
    CreateBankAccountRequest,
    InsufficientFundsError,
    PettyCashAdjustmentRequest,
    PettyCashDisbursementRequest,
    PettyCashFundError,
    PettyCashRequest,
    UpdateBankAccountRequest,
    create_bank_cash_service,
)
from domain.bank_cash.bank_account_entity import BankAccount, BankAccountStatus, BankAccountType
from domain.bank_cash.bank_aggregate_root import BankAggregate
from domain.bank_cash.bank_transaction_entity import TransactionStatus, TransactionType
from domain.bank_cash.bank_transfer_entity import TransferStatus
from domain.bank_cash.cash_book_entity import CashBook
from domain.bank_cash.cash_disbursement_entity import CashDisbursementEntity as CashDisbursement
from domain.bank_cash.cash_receipt_entity import CashReceiptEntity as CashReceipt
from domain.bank_cash.petty_cash_fund_entity import PettyCashFundEntity as PettyCashFund
from domain.shared_value_objects.currency_vo import Currency

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def fixed_date() -> date:
    return date(2026, 1, 15)


@pytest.fixture
def fixed_datetime() -> datetime:
    return datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def legal_entity_id() -> UUID:
    return uuid4()


@pytest.fixture
def user_id() -> UUID:
    return uuid4()


@pytest.fixture
def bank_account_id() -> UUID:
    return uuid4()


@pytest.fixture
def bank_account(legal_entity_id) -> BankAccount:
    return BankAccount(
        id=uuid4(),
        legal_entity_id=legal_entity_id,
        account_name="Test Account",
        account_number="1234567890",
        bank_name="Test Bank",
        bank_code="TEST",
        branch="Main",
        currency=Currency("IDR"),
        account_type=BankAccountType.CHECKING,
        current_balance=Decimal("1000000"),
        available_balance=Decimal("1000000"),
        status=BankAccountStatus.ACTIVE,
        opening_balance=Decimal("1000000"),
        last_reconciliation_date=None,
        is_locked=False,
        created_by=uuid4(),
        created_at=datetime.now(UTC),
        updated_at=None,
    )


@pytest.fixture
def bank_aggregate(bank_account) -> BankAggregate:
    return BankAggregate(bank_account=bank_account, version=0)


@pytest.fixture
def mock_bank_repo():
    repo = AsyncMock()
    repo.find_account_by_number = AsyncMock(return_value=None)
    repo.get_bank_account_by_id = AsyncMock(return_value=None)
    repo.save_bank_account = AsyncMock()
    repo.save_transaction = AsyncMock()
    repo.list_transactions = AsyncMock(return_value=[])
    repo.list_unreconciled_transactions = AsyncMock(return_value=[])
    repo.save_reconciliation = AsyncMock()
    repo.save_transfer = AsyncMock()
    repo.get_transfer_by_id = AsyncMock(return_value=None)
    repo.save_cash_book = AsyncMock()
    repo.get_cash_book_by_id = AsyncMock(return_value=None)
    repo.save_cash_receipt = AsyncMock()
    repo.get_cash_receipt_by_id = AsyncMock(return_value=None)
    repo.save_cash_disbursement = AsyncMock()
    repo.get_cash_disbursement_by_id = AsyncMock(return_value=None)
    repo.save_petty_cash_fund = AsyncMock()
    repo.get_petty_cash_fund_by_id = AsyncMock(return_value=None)
    repo.list_bank_accounts = AsyncMock(return_value=[])
    repo.find_transaction_by_reference = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_uow():
    uow = AsyncMock()
    uow.commit = AsyncMock()
    uow.rollback = AsyncMock()
    return uow


@pytest.fixture
def mock_event_publisher():
    return AsyncMock()


@pytest.fixture
def service(mock_bank_repo, mock_uow, mock_event_publisher):
    return BankCashService(
        bank_repo=mock_bank_repo,
        ledger_repo=None,
        uow=mock_uow,
        event_publisher=mock_event_publisher,
    )


# ============================================================================
# DTO tests (kept from original, but we can add more)
# ============================================================================

class TestCreateBankAccountRequest:
    def test_construction(self):
        req = CreateBankAccountRequest(
            legal_entity_id=uuid4(),
            account_name="Test",
            account_number="123",
            bank_name="Bank",
            bank_code="BANK",
            branch="Branch",
            currency_code="IDR",
            account_type="CHECKING",
            opening_balance=Decimal("1000"),
            reconciliation_date=date.today(),
        )
        assert req.legal_entity_id is not None
        assert req.account_name == "Test"


# ============================================================================
# Service Tests
# ============================================================================

class TestBankCashService:
    # ---- create_bank_account ----
    @pytest.mark.asyncio
    async def test_create_bank_account_success(self, service, mock_bank_repo, mock_uow, mock_event_publisher, user_id):
        req = CreateBankAccountRequest(
            legal_entity_id=uuid4(),
            account_name="New Account",
            account_number="123456",
            bank_name="Bank",
            bank_code="BANK",
            branch="Branch",
            currency_code="IDR",
            account_type="CHECKING",
            opening_balance=Decimal("1000"),
            reconciliation_date=date.today(),
        )
        mock_bank_repo.find_account_by_number.return_value = None
        mock_bank_repo.save_bank_account = AsyncMock()

        response = await service.create_bank_account(req, user_id)

        assert isinstance(response, BankAccountResponse)
        assert response.account_name == "New Account"
        assert response.account_number == "123456"
        assert response.current_balance == Decimal("1000")
        mock_bank_repo.save_bank_account.assert_called_once()
        mock_uow.commit.assert_awaited_once()
        mock_event_publisher.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_bank_account_duplicate(self, service, mock_bank_repo, user_id):
        req = CreateBankAccountRequest(
            legal_entity_id=uuid4(),
            account_name="Test",
            account_number="123456",
            bank_name="Bank",
            bank_code="BANK",
        )
        mock_bank_repo.find_account_by_number.return_value = MagicMock()

        with pytest.raises(BankCashServiceError, match="already exists"):
            await service.create_bank_account(req, user_id)
        mock_bank_repo.save_bank_account.assert_not_called()

    # ---- update_bank_account ----
    @pytest.mark.asyncio
    async def test_update_bank_account_success(self, service, mock_bank_repo, mock_uow, mock_event_publisher, bank_aggregate, user_id):
        mock_bank_repo.get_bank_account_by_id.return_value = bank_aggregate
        req = UpdateBankAccountRequest(account_name="Updated Name", branch="New Branch")

        response = await service.update_bank_account(bank_aggregate.bank_account.id, req, user_id)

        assert response.account_name == "Updated Name"
        assert bank_aggregate.bank_account.branch == "New Branch"
        mock_bank_repo.save_bank_account.assert_called_once()
        mock_uow.commit.assert_awaited_once()
        mock_event_publisher.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_bank_account_not_found(self, service, mock_bank_repo, user_id):
        mock_bank_repo.get_bank_account_by_id.return_value = None
        req = UpdateBankAccountRequest(account_name="New")
        with pytest.raises(BankAccountNotFoundError):
            await service.update_bank_account(uuid4(), req, user_id)

    @pytest.mark.asyncio
    async def test_update_bank_account_no_changes(self, service, mock_bank_repo, bank_aggregate, user_id):
        mock_bank_repo.get_bank_account_by_id.return_value = bank_aggregate
        req = UpdateBankAccountRequest()
        response = await service.update_bank_account(bank_aggregate.bank_account.id, req, user_id)
        # Should return current account without saving
        mock_bank_repo.save_bank_account.assert_not_called()
        assert response.account_name == bank_aggregate.bank_account.account_name

    # ---- block_bank_account ----
    @pytest.mark.asyncio
    async def test_block_bank_account_success(self, service, mock_bank_repo, mock_uow, mock_event_publisher, bank_aggregate, user_id):
        mock_bank_repo.get_bank_account_by_id.return_value = bank_aggregate
        response = await service.block_bank_account(bank_aggregate.bank_account.id, "Fraud", user_id)

        assert response.is_locked is True
        assert bank_aggregate.bank_account.status == BankAccountStatus.BLOCKED
        mock_bank_repo.save_bank_account.assert_called_once()
        mock_uow.commit.assert_awaited_once()
        mock_event_publisher.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_block_bank_account_already_closed(self, service, mock_bank_repo, bank_aggregate, user_id):
        bank_aggregate.bank_account.status = BankAccountStatus.CLOSED
        mock_bank_repo.get_bank_account_by_id.return_value = bank_aggregate
        with pytest.raises(BankAccountClosedError):
            await service.block_bank_account(bank_aggregate.bank_account.id, "Reason", user_id)

    # ---- close_bank_account ----
    @pytest.mark.asyncio
    async def test_close_bank_account_success(self, service, mock_bank_repo, mock_uow, mock_event_publisher, bank_aggregate, user_id):
        bank_aggregate.bank_account.current_balance = Decimal(0)
        mock_bank_repo.get_bank_account_by_id.return_value = bank_aggregate
        response = await service.close_bank_account(bank_aggregate.bank_account.id, "Closing", user_id)

        assert response.status == "closed"
        assert bank_aggregate.bank_account.status == BankAccountStatus.CLOSED
        mock_bank_repo.save_bank_account.assert_called_once()
        mock_uow.commit.assert_awaited_once()
        mock_event_publisher.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_bank_account_with_balance(self, service, mock_bank_repo, bank_aggregate, user_id):
        bank_aggregate.bank_account.current_balance = Decimal("1000")
        mock_bank_repo.get_bank_account_by_id.return_value = bank_aggregate
        with pytest.raises(BankCashServiceError, match="balance"):
            await service.close_bank_account(bank_aggregate.bank_account.id, "Reason", user_id)

    # ---- get_bank_account ----
    @pytest.mark.asyncio
    async def test_get_bank_account_success(self, service, mock_bank_repo, bank_aggregate):
        mock_bank_repo.get_bank_account_by_id.return_value = bank_aggregate
        response = await service.get_bank_account(bank_aggregate.bank_account.id)
        assert isinstance(response, BankAccountResponse)
        assert response.account_number == bank_aggregate.bank_account.account_number

    @pytest.mark.asyncio
    async def test_get_bank_account_not_found(self, service, mock_bank_repo):
        mock_bank_repo.get_bank_account_by_id.return_value = None
        with pytest.raises(BankAccountNotFoundError):
            await service.get_bank_account(uuid4())

    # ---- list_bank_accounts ----
    @pytest.mark.asyncio
    async def test_list_bank_accounts(self, service, mock_bank_repo, bank_account):
        mock_bank_repo.list_bank_accounts.return_value = [bank_account]
        responses = await service.list_bank_accounts(uuid4(), limit=10)
        assert len(responses) == 1
        assert isinstance(responses[0], BankAccountResponse)

    # ---- record_transaction ----
    @pytest.mark.asyncio
    async def test_record_transaction_success(self, service, mock_bank_repo, mock_uow, mock_event_publisher, bank_aggregate, user_id, fixed_date):
        mock_bank_repo.get_bank_account_by_id.return_value = bank_aggregate
        req = BankTransactionRequest(
            legal_entity_id=uuid4(),
            bank_account_id=bank_aggregate.bank_account.id,
            transaction_date=fixed_date,
            amount=Decimal("50000"),
            description="Deposit",
            transaction_type="DEPOSIT",
        )
        response = await service.record_transaction(req, user_id)
        assert isinstance(response, BankTransactionResponse)
        assert response.amount == Decimal("50000")
        assert bank_aggregate.bank_account.current_balance == Decimal("1050000")
        mock_bank_repo.save_transaction.assert_called_once()
        mock_uow.commit.assert_awaited_once()
        mock_event_publisher.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_transaction_insufficient_funds(self, service, mock_bank_repo, bank_aggregate, user_id, fixed_date):
        bank_aggregate.bank_account.available_balance = Decimal("1000")
        mock_bank_repo.get_bank_account_by_id.return_value = bank_aggregate
        req = BankTransactionRequest(
            legal_entity_id=uuid4(),
            bank_account_id=bank_aggregate.bank_account.id,
            transaction_date=fixed_date,
            amount=Decimal("50000"),
            description="Withdrawal",
            transaction_type="WITHDRAWAL",
        )
        with pytest.raises(InsufficientFundsError):
            await service.record_transaction(req, user_id)

    @pytest.mark.asyncio
    async def test_record_transaction_account_inactive(self, service, mock_bank_repo, bank_aggregate, user_id, fixed_date):
        bank_aggregate.bank_account.status = BankAccountStatus.BLOCKED
        mock_bank_repo.get_bank_account_by_id.return_value = bank_aggregate
        req = BankTransactionRequest(
            legal_entity_id=uuid4(),
            bank_account_id=bank_aggregate.bank_account.id,
            transaction_date=fixed_date,
            amount=Decimal("100"),
            description="Test",
        )
        with pytest.raises(BankCashServiceError, match="not active"):
            await service.record_transaction(req, user_id)

    # ---- get_transactions ----
    @pytest.mark.asyncio
    async def test_get_transactions(self, service, mock_bank_repo):
        mock_tx = MagicMock()
        mock_tx.id = uuid4()
        mock_bank_repo.list_transactions.return_value = [mock_tx]
        responses = await service.get_transactions(uuid4(), limit=5)
        assert len(responses) == 1
        assert isinstance(responses[0], BankTransactionResponse)

    # ---- reconcile_bank_account ----
    @pytest.mark.asyncio
    async def test_reconcile_bank_account_success(self, service, mock_bank_repo, mock_uow, mock_event_publisher, bank_aggregate, user_id, fixed_date):
        mock_bank_repo.get_bank_account_by_id.return_value = bank_aggregate
        mock_bank_repo.list_unreconciled_transactions.return_value = []
        mock_bank_repo.save_reconciliation = AsyncMock()
        # Mock reconciliation engine result
        mock_result = MagicMock()
        mock_result.is_matched = True
        mock_result.matched_count = 5
        mock_result.difference = Decimal(0)
        mock_result.matched_system_ids = []
        mock_result.unmatched_system_ids = []
        mock_result.unmatched_statement_refs = []

        with patch.object(service._reconciliation_engine, 'match', return_value=mock_result):
            request = BankReconciliationRequest(
                bank_account_id=bank_aggregate.bank_account.id,
                statement_date=fixed_date,
                statement_ending_balance=Decimal("1000000"),
                user_id=user_id,
                statement_transactions=[],
            )
            response = await service.reconcile_bank_account(request)
            assert isinstance(response, BankReconciliationResponse)
            assert response.is_matched is True
            mock_bank_repo.save_reconciliation.assert_called_once()
            mock_uow.commit.assert_awaited_once()
            mock_event_publisher.publish.assert_called()

    # ---- transfer_between_accounts ----
    @pytest.mark.asyncio
    async def test_transfer_between_accounts_success(self, service, mock_bank_repo, mock_uow, mock_event_publisher, user_id, fixed_date):
        from_account = bank_aggregate.bank_account
        from_agg = bank_aggregate
        to_account = BankAccount(
            id=uuid4(),
            legal_entity_id=uuid4(),
            account_name="To Account",
            account_number="987654",
            bank_name="Bank",
            bank_code="BANK",
            currency=Currency("IDR"),
            account_type=BankAccountType.CHECKING,
            current_balance=Decimal("0"),
            available_balance=Decimal("0"),
            status=BankAccountStatus.ACTIVE,
            opening_balance=Decimal("0"),
            created_by=user_id,
            created_at=datetime.now(UTC),
        )
        to_agg = BankAggregate(bank_account=to_account, version=0)
        mock_bank_repo.get_bank_account_by_id.side_effect = [from_agg, to_agg]
        mock_bank_repo.save_transfer = AsyncMock()

        transfer = await service.transfer_between_accounts(
            from_account_id=from_account.id,
            to_account_id=to_account.id,
            amount=Decimal("100000"),
            transfer_date=fixed_date,
            description="Transfer",
            user_id=user_id,
        )
        assert transfer.amount == Decimal("100000")
        assert transfer.status == TransferStatus.COMPLETED
        assert from_account.current_balance == Decimal("900000")
        assert to_account.current_balance == Decimal("100000")
        mock_bank_repo.save_transfer.assert_called_once()
        mock_uow.commit.assert_awaited_once()
        mock_event_publisher.publish.assert_called()

    @pytest.mark.asyncio
    async def test_transfer_between_accounts_insufficient_funds(self, service, mock_bank_repo, user_id, fixed_date):
        from_agg = bank_aggregate
        from_agg.bank_account.available_balance = Decimal("1000")
        mock_bank_repo.get_bank_account_by_id.return_value = from_agg
        to_agg = MagicMock()
        to_agg.bank_account = MagicMock()
        mock_bank_repo.get_bank_account_by_id.side_effect = [from_agg, to_agg]
        with pytest.raises(InsufficientFundsError):
            await service.transfer_between_accounts(
                from_account_id=uuid4(),
                to_account_id=uuid4(),
                amount=Decimal("5000"),
                transfer_date=fixed_date,
                description="Test",
                user_id=user_id,
            )

    # ---- cancel_bank_transfer ----
    @pytest.mark.asyncio
    async def test_cancel_bank_transfer_success(self, service, mock_bank_repo, mock_uow, mock_event_publisher, user_id):
        transfer = MagicMock()
        transfer.status = TransferStatus.PENDING
        transfer.from_account_id = uuid4()
        transfer.to_account_id = uuid4()
        transfer.amount = Decimal("1000")
        mock_bank_repo.get_transfer_by_id.return_value = transfer
        await service.cancel_bank_transfer(uuid4(), "Cancel", user_id)
        assert transfer.status == TransferStatus.CANCELLED
        mock_bank_repo.save_transfer.assert_called_once()
        mock_uow.commit.assert_awaited_once()
        mock_event_publisher.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_bank_transfer_not_found(self, service, mock_bank_repo):
        mock_bank_repo.get_transfer_by_id.return_value = None
        with pytest.raises(BankCashServiceError, match="not found"):
            await service.cancel_bank_transfer(uuid4(), "Reason", uuid4())

    # ---- create_cash_book ----
    @pytest.mark.asyncio
    async def test_create_cash_book(self, service, mock_bank_repo, mock_uow, user_id):
        cash_book = await service.create_cash_book(
            legal_entity_id=uuid4(),
            name="Petty Cash",
            currency_code="IDR",
            opening_balance=Decimal("500000"),
            user_id=user_id,
        )
        assert isinstance(cash_book, CashBook)
        assert cash_book.name == "Petty Cash"
        assert cash_book.current_balance == Decimal("500000")
        mock_bank_repo.save_cash_book.assert_called_once()
        mock_uow.commit.assert_awaited_once()

    # ---- update_cash_book ----
    @pytest.mark.asyncio
    async def test_update_cash_book_success(self, service, mock_bank_repo, mock_uow, mock_event_publisher, user_id):
        cash_book = MagicMock(spec=CashBook)
        cash_book.name = "Old Name"
        cash_book.id = uuid4()
        mock_bank_repo.get_cash_book_by_id.return_value = cash_book
        updated = await service.update_cash_book(cash_book.id, "New Name", user_id)
        assert updated.name == "New Name"
        mock_bank_repo.save_cash_book.assert_called_once()
        mock_uow.commit.assert_awaited_once()
        mock_event_publisher.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_cash_book_no_changes(self, service, mock_bank_repo, user_id):
        cash_book = MagicMock(spec=CashBook)
        cash_book.name = "Same"
        cash_book.id = uuid4()
        mock_bank_repo.get_cash_book_by_id.return_value = cash_book
        updated = await service.update_cash_book(cash_book.id, None, user_id)
        assert updated is cash_book
        mock_bank_repo.save_cash_book.assert_not_called()

    # ---- close_cash_book ----
    @pytest.mark.asyncio
    async def test_close_cash_book_success(self, service, mock_bank_repo, mock_uow, mock_event_publisher, user_id):
        cash_book = MagicMock(spec=CashBook)
        cash_book.id = uuid4()
        cash_book.current_balance = Decimal(0)
        mock_bank_repo.get_cash_book_by_id.return_value = cash_book
        closed = await service.close_cash_book(cash_book.id, user_id)
        assert closed.is_closed is True
        mock_bank_repo.save_cash_book.assert_called_once()
        mock_uow.commit.assert_awaited_once()
        mock_event_publisher.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_cash_book_with_balance(self, service, mock_bank_repo, user_id):
        cash_book = MagicMock(spec=CashBook)
        cash_book.id = uuid4()
        cash_book.current_balance = Decimal("100")
        mock_bank_repo.get_cash_book_by_id.return_value = cash_book
        with pytest.raises(BankCashServiceError, match="balance"):
            await service.close_cash_book(cash_book.id, user_id)

    # ---- record_cash_receipt ----
    @pytest.mark.asyncio
    async def test_record_cash_receipt_success(self, service, mock_bank_repo, mock_uow, mock_event_publisher, user_id, fixed_date):
        cash_book = MagicMock(spec=CashBook)
        cash_book.id = uuid4()
        cash_book.current_balance = Decimal("0")
        mock_bank_repo.get_cash_book_by_id.return_value = cash_book
        req = CashReceiptRequest(
            legal_entity_id=uuid4(),
            cash_book_id=cash_book.id,
            receipt_date=fixed_date,
            amount=Decimal("100000"),
            from_party="Customer",
            description="Payment",
        )
        receipt = await service.record_cash_receipt(req, user_id)
        assert isinstance(receipt, CashReceipt)
        assert receipt.amount == Decimal("100000")
        assert cash_book.current_balance == Decimal("100000")
        mock_bank_repo.save_cash_receipt.assert_called_once()
        mock_uow.commit.assert_awaited_once()
        mock_event_publisher.publish.assert_called_once()

    # ---- confirm_cash_receipt ----
    @pytest.mark.asyncio
    async def test_confirm_cash_receipt_success(self, service, mock_bank_repo, mock_uow, mock_event_publisher, user_id):
        receipt = MagicMock(spec=CashReceipt)
        receipt.id = uuid4()
        receipt.cash_book_id = uuid4()
        receipt.amount = Decimal("100")
        receipt.status = "PENDING"
        mock_bank_repo.get_cash_receipt_by_id.return_value = receipt
        confirmed = await service.confirm_cash_receipt(receipt.id, user_id)
        assert confirmed.status == "CONFIRMED"
        mock_bank_repo.save_cash_receipt.assert_called_once()
        mock_uow.commit.assert_awaited_once()
        mock_event_publisher.publish.assert_called_once()

    # ---- cancel_cash_receipt ----
    @pytest.mark.asyncio
    async def test_cancel_cash_receipt_success(self, service, mock_bank_repo, mock_uow, mock_event_publisher, user_id):
        receipt = MagicMock(spec=CashReceipt)
        receipt.id = uuid4()
        receipt.cash_book_id = uuid4()
        receipt.amount = Decimal("100")
        receipt.status = "PENDING"
        mock_bank_repo.get_cash_receipt_by_id.return_value = receipt
        cancelled = await service.cancel_cash_receipt(receipt.id, "Test", user_id)
        assert cancelled.status == "CANCELLED"
        mock_bank_repo.save_cash_receipt.assert_called_once()
        mock_uow.commit.assert_awaited_once()
        mock_event_publisher.publish.assert_called_once()

    # ---- record_cash_disbursement ----
    @pytest.mark.asyncio
    async def test_record_cash_disbursement_success(self, service, mock_bank_repo, mock_uow, mock_event_publisher, user_id, fixed_date):
        cash_book = MagicMock(spec=CashBook)
        cash_book.id = uuid4()
        cash_book.current_balance = Decimal("1000000")
        mock_bank_repo.get_cash_book_by_id.return_value = cash_book
        req = CashDisbursementRequest(
            legal_entity_id=uuid4(),
            cash_book_id=cash_book.id,
            disbursement_date=fixed_date,
            amount=Decimal("200000"),
            to_party="Supplier",
            description="Payment",
        )
        disbursement = await service.record_cash_disbursement(req, user_id)
        assert isinstance(disbursement, CashDisbursement)
        assert disbursement.amount == Decimal("200000")
        assert cash_book.current_balance == Decimal("800000")
        mock_bank_repo.save_cash_disbursement.assert_called_once()
        mock_uow.commit.assert_awaited_once()
        mock_event_publisher.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_cash_disbursement_insufficient_funds(self, service, mock_bank_repo, user_id, fixed_date):
        cash_book = MagicMock(spec=CashBook)
        cash_book.id = uuid4()
        cash_book.current_balance = Decimal("100")
        mock_bank_repo.get_cash_book_by_id.return_value = cash_book
        req = CashDisbursementRequest(
            legal_entity_id=uuid4(),
            cash_book_id=cash_book.id,
            disbursement_date=fixed_date,
            amount=Decimal("200"),
            to_party="Supplier",
            description="Payment",
        )
        with pytest.raises(InsufficientFundsError):
            await service.record_cash_disbursement(req, user_id)

    # ---- approve_cash_disbursement ----
    @pytest.mark.asyncio
    async def test_approve_cash_disbursement_success(self, service, mock_bank_repo, mock_uow, mock_event_publisher, user_id):
        disbursement = MagicMock(spec=CashDisbursement)
        disbursement.id = uuid4()
        disbursement.cash_book_id = uuid4()
        disbursement.amount = Decimal("100")
        disbursement.status = "PENDING"
        mock_bank_repo.get_cash_disbursement_by_id.return_value = disbursement
        approved = await service.approve_cash_disbursement(disbursement.id, user_id)
        assert approved.status == "APPROVED"
        mock_bank_repo.save_cash_disbursement.assert_called_once()
        mock_uow.commit.assert_awaited_once()
        mock_event_publisher.publish.assert_called_once()

    # ---- pay_cash_disbursement ----
    @pytest.mark.asyncio
    async def test_pay_cash_disbursement_success(self, service, mock_bank_repo, mock_uow, mock_event_publisher, user_id):
        disbursement = MagicMock(spec=CashDisbursement)
        disbursement.id = uuid4()
        disbursement.cash_book_id = uuid4()
        disbursement.amount = Decimal("100")
        disbursement.status = "APPROVED"
        mock_bank_repo.get_cash_disbursement_by_id.return_value = disbursement
        paid = await service.pay_cash_disbursement(disbursement.id, user_id)
        assert paid.status == "PAID"
        mock_bank_repo.save_cash_disbursement.assert_called_once()
        mock_uow.commit.assert_awaited_once()
        mock_event_publisher.publish.assert_called_once()

    # ---- cancel_cash_disbursement ----
    @pytest.mark.asyncio
    async def test_cancel_cash_disbursement_success(self, service, mock_bank_repo, mock_uow, mock_event_publisher, user_id):
        disbursement = MagicMock(spec=CashDisbursement)
        disbursement.id = uuid4()
        disbursement.cash_book_id = uuid4()
        disbursement.amount = Decimal("100")
        disbursement.status = "PENDING"
        mock_bank_repo.get_cash_disbursement_by_id.return_value = disbursement
        cancelled = await service.cancel_cash_disbursement(disbursement.id, "Test", user_id)
        assert cancelled.status == "CANCELLED"
        mock_bank_repo.save_cash_disbursement.assert_called_once()
        mock_uow.commit.assert_awaited_once()
        mock_event_publisher.publish.assert_called_once()

    # ---- create_petty_cash_fund ----
    @pytest.mark.asyncio
    async def test_create_petty_cash_fund_success(self, service, mock_bank_repo, mock_uow, mock_event_publisher, user_id):
        req = PettyCashRequest(
            legal_entity_id=uuid4(),
            fund_name="Office Fund",
            initial_amount=Decimal("100000"),
            custodian_id=user_id,
            currency_code="IDR",
        )
        fund = await service.create_petty_cash_fund(req, user_id)
        assert isinstance(fund, PettyCashFund)
        assert fund.fund_name == "Office Fund"
        assert fund.current_balance == Decimal("100000")
        mock_bank_repo.save_petty_cash_fund.assert_called_once()
        mock_uow.commit.assert_awaited_once()
        mock_event_publisher.publish.assert_called_once()

    # ---- adjust_petty_cash ----
    @pytest.mark.asyncio
    async def test_adjust_petty_cash_success(self, service, mock_bank_repo, mock_uow, mock_event_publisher, user_id):
        fund = MagicMock(spec=PettyCashFund)
        fund.id = uuid4()
        fund.current_balance = Decimal("50000")
        fund.version = 0
        mock_bank_repo.get_petty_cash_fund_by_id.return_value = fund
        req = PettyCashAdjustmentRequest(fund_id=fund.id, amount=Decimal("10000"), reason="Top up", user_id=user_id)
        adjusted = await service.adjust_petty_cash(req)
        assert adjusted.current_balance == Decimal("60000")
        mock_bank_repo.save_petty_cash_fund.assert_called_once()
        mock_uow.commit.assert_awaited_once()
        mock_event_publisher.publish.assert_called_once()

    # ---- activate_petty_cash ----
    @pytest.mark.asyncio
    async def test_activate_petty_cash_success(self, service, mock_bank_repo, mock_uow, mock_event_publisher, user_id):
        fund = MagicMock(spec=PettyCashFund)
        fund.id = uuid4()
        fund.is_active = False
        mock_bank_repo.get_petty_cash_fund_by_id.return_value = fund
        activated = await service.activate_petty_cash(fund.id, user_id)
        assert activated.is_active is True
        mock_bank_repo.save_petty_cash_fund.assert_called_once()
        mock_uow.commit.assert_awaited_once()
        mock_event_publisher.publish.assert_called_once()

    # ---- close_petty_cash ----
    @pytest.mark.asyncio
    async def test_close_petty_cash_success(self, service, mock_bank_repo, mock_uow, mock_event_publisher, user_id):
        fund = MagicMock(spec=PettyCashFund)
        fund.id = uuid4()
        fund.current_balance = Decimal(0)
        mock_bank_repo.get_petty_cash_fund_by_id.return_value = fund
        closed = await service.close_petty_cash(fund.id, user_id)
        assert closed.is_closed is True
        assert closed.is_active is False
        mock_bank_repo.save_petty_cash_fund.assert_called_once()
        mock_uow.commit.assert_awaited_once()
        mock_event_publisher.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_petty_cash_with_balance(self, service, mock_bank_repo, user_id):
        fund = MagicMock(spec=PettyCashFund)
        fund.id = uuid4()
        fund.current_balance = Decimal("100")
        mock_bank_repo.get_petty_cash_fund_by_id.return_value = fund
        with pytest.raises(PettyCashFundError, match="balance"):
            await service.close_petty_cash(fund.id, user_id)

    # ---- suspend_petty_cash ----
    @pytest.mark.asyncio
    async def test_suspend_petty_cash_success(self, service, mock_bank_repo, mock_uow, mock_event_publisher, user_id):
        fund = MagicMock(spec=PettyCashFund)
        fund.id = uuid4()
        fund.is_active = True
        mock_bank_repo.get_petty_cash_fund_by_id.return_value = fund
        suspended = await service.suspend_petty_cash(fund.id, "Reason", user_id)
        assert suspended.is_active is False
        mock_bank_repo.save_petty_cash_fund.assert_called_once()
        mock_uow.commit.assert_awaited_once()
        mock_event_publisher.publish.assert_called_once()

    # ---- record_petty_cash_disbursement ----
    @pytest.mark.asyncio
    async def test_record_petty_cash_disbursement_success(self, service, mock_bank_repo, mock_uow, mock_event_publisher, user_id, fixed_date):
        fund = MagicMock(spec=PettyCashFund)
        fund.id = uuid4()
        fund.current_balance = Decimal("50000")
        fund.is_active = True
        fund.version = 0
        mock_bank_repo.get_petty_cash_fund_by_id.return_value = fund
        req = PettyCashDisbursementRequest(
            fund_id=fund.id,
            amount=Decimal("10000"),
            date=fixed_date,
            description="Office supplies",
            recipient="Staff",
            user_id=user_id,
        )
        result = await service.record_petty_cash_disbursement(req)
        assert result["amount"] == Decimal("10000")
        assert result["new_balance"] == Decimal("40000")
        mock_bank_repo.save_petty_cash_fund.assert_called_once()
        mock_uow.commit.assert_awaited_once()
        mock_event_publisher.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_petty_cash_disbursement_inactive_fund(self, service, mock_bank_repo, user_id, fixed_date):
        fund = MagicMock(spec=PettyCashFund)
        fund.id = uuid4()
        fund.current_balance = Decimal("50000")
        fund.is_active = False
        mock_bank_repo.get_petty_cash_fund_by_id.return_value = fund
        req = PettyCashDisbursementRequest(
            fund_id=fund.id,
            amount=Decimal("10000"),
            date=fixed_date,
            description="Test",
            recipient="R",
            user_id=user_id,
        )
        with pytest.raises(PettyCashFundError, match="not active"):
            await service.record_petty_cash_disbursement(req)

    # ---- replenish_petty_cash ----
    @pytest.mark.asyncio
    async def test_replenish_petty_cash_success(self, service, mock_bank_repo, mock_uow, mock_event_publisher, user_id):
        fund = MagicMock(spec=PettyCashFund)
        fund.id = uuid4()
        fund.current_balance = Decimal("10000")
        fund.version = 0
        fund.fund_name = "Test Fund"
        mock_bank_repo.get_petty_cash_fund_by_id.return_value = fund
        with patch.object(service, 'transfer_between_accounts', new_callable=AsyncMock) as mock_transfer:
            mock_transfer.return_value = MagicMock()
            replenished = await service.replenish_petty_cash(fund.id, Decimal("50000"), uuid4(), user_id)
            assert replenished.current_balance == Decimal("60000")
            mock_transfer.assert_called_once()
            mock_bank_repo.save_petty_cash_fund.assert_called_once()
            mock_uow.commit.assert_awaited_once()
            mock_event_publisher.publish.assert_called_once()

    # ---- import_bank_statement ----
    @pytest.mark.asyncio
    async def test_import_bank_statement_success(self, service, mock_bank_repo, mock_uow, mock_event_publisher, bank_aggregate, user_id):
        mock_bank_repo.get_bank_account_by_id.return_value = bank_aggregate
        mock_bank_repo.find_transaction_by_reference.return_value = None
        mock_bank_repo.save_transaction = AsyncMock()

        csv_content = (
            "date,amount,description,reference,counterparty\n"
            "2026-01-01,1000.00,Deposit,REF1,Customer A\n"
            "2026-01-02,-500.00,Withdrawal,REF2,Supplier B\n"
        )
        imported = await service.import_bank_statement(
            bank_account_id=bank_aggregate.bank_account.id,
            file_content=csv_content,
            file_format="CSV",
            user_id=user_id,
        )
        assert imported == 2
        # Verify that record_transaction was called twice
        # We can check that save_transaction called twice
        assert mock_bank_repo.save_transaction.call_count == 2
        mock_uow.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_import_bank_statement_unsupported_format(self, service, bank_aggregate, user_id):
        with pytest.raises(BankCashServiceError, match="Unsupported format"):
            await service.import_bank_statement(
                bank_account_id=bank_aggregate.bank_account.id,
                file_content="",
                file_format="UNKNOWN",
                user_id=user_id,
            )

    @pytest.mark.asyncio
    async def test_import_bank_statement_duplicate_reference(self, service, mock_bank_repo, bank_aggregate, user_id):
        mock_bank_repo.get_bank_account_by_id.return_value = bank_aggregate
        mock_bank_repo.find_transaction_by_reference.return_value = True  # Duplicate
        csv_content = "date,amount,description,reference,counterparty\n2026-01-01,1000.00,Deposit,REF1,Customer A\n"
        imported = await service.import_bank_statement(
            bank_account_id=bank_aggregate.bank_account.id,
            file_content=csv_content,
            file_format="CSV",
            user_id=user_id,
        )
        assert imported == 0  # No new imports because of duplicate

    # ---- _parse_statement ----
    def test_parse_statement_csv(self, service):
        csv_content = (
            "date,amount,description,reference,counterparty\n"
            "2026-01-01,1000.00,Deposit,REF1,Customer A\n"
            "2026-01-02,-500.00,Withdrawal,REF2,Supplier B\n"
        )
        parsed = service._parse_statement(csv_content, "CSV")
        assert len(parsed) == 2
        assert parsed[0]["date"] == date(2026, 1, 1)
        assert parsed[0]["amount"] == Decimal("1000.00")
        assert parsed[0]["type"] == "DEPOSIT"
        assert parsed[0]["reference"] == "REF1"
        assert parsed[1]["date"] == date(2026, 1, 2)
        assert parsed[1]["amount"] == Decimal("-500.00")
        assert parsed[1]["type"] == "WITHDRAWAL"

    def test_parse_statement_unsupported(self, service):
        with pytest.raises(BankCashServiceError, match="Unsupported format"):
            service._parse_statement("", "XML")

    # ---- _to_bank_account_response ----
    def test_to_bank_account_response(self, service, bank_account):
        response = service._to_bank_account_response(bank_account)
        assert isinstance(response, BankAccountResponse)
        assert response.id == bank_account.id
        assert response.account_number == bank_account.account_number
        assert response.current_balance == bank_account.current_balance
        assert response.status == bank_account.status.value
        assert response.is_locked == bank_account.is_locked

    # ---- _to_transaction_response ----
    def test_to_transaction_response(self, service):
        tx = MagicMock(spec=BankTransaction)
        tx.id = uuid4()
        tx.bank_account_id = uuid4()
        tx.transaction_date = date.today()
        tx.amount = Decimal("100")
        tx.transaction_type = TransactionType.DEPOSIT
        tx.description = "Test"
        tx.reference_number = "REF"
        tx.status = TransactionStatus.COMPLETED
        tx.is_reconciled = False
        response = service._to_transaction_response(tx)
        assert isinstance(response, BankTransactionResponse)
        assert response.id == tx.id
        assert response.amount == tx.amount

    # ---- get_stats ----
    def test_get_stats(self, service):
        stats = service.get_stats()
        assert stats["accounts_created"] == 0
        # After some operations, stats should update
        service._stats["accounts_created"] = 5
        stats2 = service.get_stats()
        assert stats2["accounts_created"] == 5

    # ---- get_audit_trail ----
    def test_get_audit_trail(self, service):
        assert service.get_audit_trail() == []
        service._record_audit("test", {"detail": "value"})
        trail = service.get_audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "test"


# ============================================================================
# Factory function test
# ============================================================================

@pytest.mark.asyncio
async def test_create_bank_cash_service():
    mock_repo = AsyncMock()
    mock_ledger = AsyncMock()
    mock_uow = AsyncMock()
    mock_pub = AsyncMock()
    service = await create_bank_cash_service(mock_repo, mock_ledger, mock_uow, mock_pub)
    assert isinstance(service, BankCashService)
    assert service._bank_repo is mock_repo
    assert service._ledger_repo is mock_ledger
    assert service._uow is mock_uow
    assert service._event_publisher is mock_pub
