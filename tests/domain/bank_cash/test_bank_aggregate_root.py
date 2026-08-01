# test_bank_aggregate_root.py
"""
Comprehensive tests for domain/bank_cash/bank_aggregate_root.py
Covers all enums, value objects, aggregate root methods, and repository stub.
Uses fixed datetime fixtures, mocks, and parameterization to avoid duplication.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from domain.bank_cash.bank_account_entity import (
    BankAccountEntity,
    BankAccountStatus,
    BankAccountType,
)
from domain.bank_cash.bank_aggregate_root import (
    BankAccountAggregate,
    BankAggregate,
    BankAggregateRepository,
    BankReconciliation,
    BankSummary,
    BankTransactionEntity,
    BankTransactionStatus,
    BankTransactionType,
    ReconciliationResult,
    StatementPeriod,
)
from domain.bank_cash.bank_reconciliation_engine import (
    ReconciliationResult as ReconResult,
)

# ============================================================================
# FIXED DATETIME FIXTURES
# ============================================================================

@pytest.fixture
def fixed_now():
    """Fixed datetime for deterministic tests."""
    return datetime(2026, 6, 15, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
def fixed_past():
    return datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
def fixed_future():
    return datetime(2026, 7, 1, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
def fixed_date():
    return date(2026, 6, 15)


# ============================================================================
# MOCK HELPERS
# ============================================================================

def create_mock_account(
    account_id: uuid.UUID | None = None,
    account_number: str = "1234567890",
    account_name: str = "Test Account",
    account_type: BankAccountType = BankAccountType.SAVINGS,
    currency: str = "IDR",
    current_balance: Decimal = Decimal("1000000"),
    status: BankAccountStatus = BankAccountStatus.ACTIVE,
    allow_overdraft: bool = False,
    overdraft_limit: Decimal = Decimal("0"),
    legal_entity_id: uuid.UUID | None = None,
) -> BankAccountEntity:
    if account_id is None:
        account_id = uuid.uuid4()
    if legal_entity_id is None:
        legal_entity_id = uuid.uuid4()

    mock = MagicMock(spec=BankAccountEntity)
    mock.account_id = account_id
    mock.account_number = account_number
    mock.account_name = account_name
    mock.account_type = account_type
    mock.currency = currency
    mock.current_balance = current_balance
    mock.status = status
    mock.allow_overdraft = allow_overdraft
    mock.overdraft_limit = overdraft_limit
    mock.legal_entity_id = legal_entity_id

    mock.deposit = MagicMock(return_value=mock)
    mock.withdraw = MagicMock(return_value=mock)
    mock.can_deposit = MagicMock(return_value=True)
    mock.can_withdraw = MagicMock(return_value=True)
    mock.is_active = MagicMock(return_value=status == BankAccountStatus.ACTIVE)
    mock.mark_reconciled = MagicMock(return_value=mock)
    mock.validate = MagicMock(return_value={"is_valid": True, "errors": [], "warnings": []})

    return mock


def create_mock_transaction(
    transaction_id: uuid.UUID | None = None,
    bank_account_id: uuid.UUID | None = None,
    amount: Decimal = Decimal("1000"),
    transaction_type: BankTransactionType = BankTransactionType.DEPOSIT,
    status: BankTransactionStatus = BankTransactionStatus.PENDING,
    is_reconciled: bool = False,
    created_at: datetime | None = None,
    transaction_date: date | None = None,
    description: str = "Test transaction",
    reference_number: str | None = None,
    is_outflow: bool = False,
) -> BankTransactionEntity:
    if transaction_id is None:
        transaction_id = uuid.uuid4()
    if bank_account_id is None:
        bank_account_id = uuid.uuid4()
    if created_at is None:
        created_at = datetime.now(UTC)
    if transaction_date is None:
        transaction_date = date.today()

    mock = MagicMock(spec=BankTransactionEntity)
    mock.transaction_id = transaction_id
    mock.bank_account_id = bank_account_id
    mock.amount = amount
    mock.transaction_type = transaction_type
    mock.status = status
    mock.is_reconciled = is_reconciled
    mock.created_at = created_at
    mock.transaction_date = transaction_date
    mock.description = description
    mock.reference_number = reference_number
    mock.is_outflow = is_outflow
    mock.is_inflow = not is_outflow
    mock.created_by = "tester"
    mock.counterparty_name = None
    mock.counterparty_account = None

    mock.is_pending = MagicMock(return_value=status == BankTransactionStatus.PENDING)
    mock.is_cleared = MagicMock(return_value=status == BankTransactionStatus.CLEARED)
    mock.mark_as_cleared = MagicMock(return_value=mock)
    mock.mark_as_reconciled = MagicMock(return_value=mock)
    mock.cancel = MagicMock(return_value=mock)

    return mock


# ============================================================================
# ENUM TESTS
# ============================================================================

class TestStatementPeriod:
    def test_members(self):
        assert StatementPeriod.DAILY.value == "daily"
        assert StatementPeriod.WEEKLY.value == "weekly"
        assert StatementPeriod.MONTHLY.value == "monthly"
        assert StatementPeriod.QUARTERLY.value == "quarterly"
        assert StatementPeriod.YEARLY.value == "yearly"


# ============================================================================
# BANKSUMMARY TESTS
# ============================================================================

class TestBankSummary:
    def test_construction(self, fixed_now):
        summary = BankSummary(
            total_accounts=5,
            active_accounts=3,
            total_balance=Decimal("10000000"),
            total_debit_today=Decimal("500000"),
            total_credit_today=Decimal("200000"),
            last_transaction_date=fixed_now,
        )
        assert summary.total_accounts == 5
        assert summary.total_balance == Decimal("10000000")

    def test_to_dict(self, fixed_now):
        summary = BankSummary(
            total_accounts=5,
            active_accounts=3,
            total_balance=Decimal("10000000"),
            total_debit_today=Decimal("500000"),
            total_credit_today=Decimal("200000"),
            last_transaction_date=fixed_now,
        )
        d = summary.to_dict()
        assert d["total_accounts"] == 5
        assert d["total_balance"] == "10000000"
        assert d["last_transaction_date"] == fixed_now.isoformat()


# ============================================================================
# BANK AGGREGATE FIXTURES
# ============================================================================

@pytest.fixture
def legal_entity_id():
    return uuid.uuid4()


@pytest.fixture
def bank_id():
    return uuid.uuid4()


@pytest.fixture
def sample_account(legal_entity_id):
    return create_mock_account(legal_entity_id=legal_entity_id)


@pytest.fixture
def sample_transaction(sample_account):
    return create_mock_transaction(bank_account_id=sample_account.account_id)


@pytest.fixture
def bank_aggregate(
    bank_id,
    legal_entity_id,
    sample_account,
    sample_transaction,
    fixed_now,
) -> BankAggregate:
    with patch("domain.bank_cash.bank_aggregate_root.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.UTC = UTC
        agg = BankAggregate(
            bank_id=bank_id,
            legal_entity_id=legal_entity_id,
            accounts={sample_account.account_id: sample_account},
            transactions=[sample_transaction],
            reconciliations=[],
            created_at=fixed_now,
            updated_at=fixed_now,
            version=1,
            is_closed=False,
            is_archived=False,
        )
        return agg


# ============================================================================
# BANK AGGREGATE TESTS
# ============================================================================

class TestBankAggregate:
    # --- Construction & Factory Methods ---
    def test_construction(self, bank_id, legal_entity_id, fixed_now):
        agg = BankAggregate(
            bank_id=bank_id,
            legal_entity_id=legal_entity_id,
            created_at=fixed_now,
            updated_at=fixed_now,
            version=1,
        )
        assert agg.bank_id == bank_id
        assert agg.legal_entity_id == legal_entity_id
        assert agg.accounts == {}
        assert agg.transactions == []
        assert agg.reconciliations == []
        assert agg.version == 1
        assert agg.is_closed is False
        assert agg.is_archived is False
        assert agg._events == []

    def test_create(self, legal_entity_id, fixed_now):
        with patch("domain.bank_cash.bank_aggregate_root.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.UTC = UTC
            agg = BankAggregate.create(legal_entity_id, created_by="user")
            assert isinstance(agg.bank_id, uuid.UUID)
            assert agg.legal_entity_id == legal_entity_id
            assert agg.created_at == fixed_now
            assert agg.version == 1

    def test_reconstruct(self, bank_id, legal_entity_id, fixed_now):
        accounts = {uuid.uuid4(): create_mock_account()}
        transactions = [create_mock_transaction()]
        reconciliations = [MagicMock(spec=ReconResult)]
        agg = BankAggregate.reconstruct(
            bank_id=bank_id,
            legal_entity_id=legal_entity_id,
            accounts=accounts,
            transactions=transactions,
            reconciliations=reconciliations,
            created_at=fixed_now,
            updated_at=fixed_now,
            version=5,
            is_closed=True,
            is_archived=False,
        )
        assert agg.bank_id == bank_id
        assert agg.legal_entity_id == legal_entity_id
        assert agg.accounts == accounts
        assert agg.transactions == transactions
        assert agg.reconciliations == reconciliations
        assert agg.version == 5
        assert agg.is_closed is True

    # --- Entity Basic Methods ---
    def test_add_child(self, bank_aggregate, sample_account):
        new_account = create_mock_account(account_id=uuid.uuid4())
        new_account.legal_entity_id = bank_aggregate.legal_entity_id
        new_agg = bank_aggregate.add_child(new_account)
        assert new_agg.accounts[new_account.account_id] is new_account
        assert new_agg.version == bank_aggregate.version + 1
        assert len(new_agg._events) == 1
        assert new_agg._events[0]["type"] == "ACCOUNT_ADDED"

    def test_add_child_duplicate_raises(self, bank_aggregate, sample_account):
        with pytest.raises(ValueError, match="already exists"):
            bank_aggregate.add_child(sample_account)

    def test_add_child_legal_entity_mismatch_raises(self, bank_aggregate):
        new_account = create_mock_account(legal_entity_id=uuid.uuid4())
        with pytest.raises(ValueError, match="legal entity mismatch"):
            bank_aggregate.add_child(new_account)

    def test_remove_child(self, bank_aggregate, sample_account):
        sample_account.current_balance = Decimal("0")
        # Ensure no pending transactions for this account
        bank_aggregate.transactions = []
        new_agg = bank_aggregate.remove_child(sample_account.account_id)
        assert sample_account.account_id not in new_agg.accounts
        assert new_agg.version == bank_aggregate.version + 1
        assert new_agg._events[-1]["type"] == "ACCOUNT_REMOVED"

    def test_remove_child_nonzero_balance_raises(self, bank_aggregate, sample_account):
        sample_account.current_balance = Decimal("1000")
        with pytest.raises(ValueError, match="non-zero balance"):
            bank_aggregate.remove_child(sample_account.account_id)

    def test_remove_child_pending_transactions_raises(self, bank_aggregate, sample_account):
        sample_account.current_balance = Decimal("0")
        pending_tx = create_mock_transaction(
            bank_account_id=sample_account.account_id,
            status=BankTransactionStatus.PENDING,
        )
        bank_aggregate.transactions.append(pending_tx)
        with pytest.raises(ValueError, match="pending transactions"):
            bank_aggregate.remove_child(sample_account.account_id)

    def test_validate_valid(self, bank_aggregate):
        with patch.object(bank_aggregate.accounts[sample_account.account_id], "validate",
                          return_value={"is_valid": True, "errors": [], "warnings": []}):
            result = bank_aggregate.validate()
            assert result["is_valid"] is True
            assert result["errors"] == []

    def test_validate_with_errors(self, bank_aggregate):
        mock_acc = bank_aggregate.accounts[sample_account.account_id]
        mock_acc.validate.return_value = {"is_valid": False, "errors": ["error1"], "warnings": []}
        result = bank_aggregate.validate()
        assert result["is_valid"] is False
        assert "error1" in result["errors"][0]

    def test_can_post(self, bank_aggregate):
        assert bank_aggregate.can_post() is True
        bank_aggregate.is_closed = True
        assert bank_aggregate.can_post() is False

    def test_post(self, bank_aggregate):
        new_agg = bank_aggregate.post("poster")
        assert new_agg.is_closed is True
        assert new_agg.version == bank_aggregate.version + 1
        assert new_agg._events[-1]["type"] == "POSTED"

    def test_post_already_closed_raises(self, bank_aggregate):
        bank_aggregate.is_closed = True
        with pytest.raises(ValueError, match="already closed"):
            bank_aggregate.post("poster")

    def test_can_approve(self, bank_aggregate):
        assert bank_aggregate.can_approve() is True

    def test_approve(self, bank_aggregate):
        new_agg = bank_aggregate.approve("approver")
        assert new_agg is not bank_aggregate
        assert new_agg.version == bank_aggregate.version + 1  # version increments
        assert new_agg._events[-1]["type"] == "APPROVED"

    def test_can_reject(self, bank_aggregate):
        assert bank_aggregate.can_reject() is True

    def test_reject(self, bank_aggregate):
        new_agg = bank_aggregate.reject("rejecter", "bad")
        assert new_agg.version == bank_aggregate.version + 1
        assert new_agg._events[-1]["type"] == "REJECTED"

    def test_can_cancel(self, bank_aggregate):
        assert bank_aggregate.can_cancel() is True
        bank_aggregate.is_closed = True
        assert bank_aggregate.can_cancel() is False

    def test_cancel(self, bank_aggregate):
        new_agg = bank_aggregate.cancel("canceller", "reason")
        assert new_agg.is_closed is True
        assert new_agg.version == bank_aggregate.version + 1
        assert new_agg._events[-1]["type"] == "CANCELLED"

    def test_can_reverse(self, bank_aggregate):
        bank_aggregate.is_closed = False
        assert bank_aggregate.can_reverse() is False
        bank_aggregate.is_closed = True
        assert bank_aggregate.can_reverse() is True

    def test_reverse(self, bank_aggregate):
        bank_aggregate.is_closed = True
        new_agg = bank_aggregate.reverse("reverser", "reason")
        assert new_agg.is_closed is False
        assert new_agg.version == bank_aggregate.version + 1
        assert new_agg._events[-1]["type"] == "REVERSED"

    def test_close(self, bank_aggregate):
        new_agg = bank_aggregate.close("closer")
        assert new_agg.is_closed is True
        assert new_agg.version == bank_aggregate.version + 1
        assert new_agg._events[-1]["type"] == "CLOSED"

    def test_close_already_closed_raises(self, bank_aggregate):
        bank_aggregate.is_closed = True
        with pytest.raises(ValueError, match="already closed"):
            bank_aggregate.close("closer")

    def test_reopen(self, bank_aggregate):
        bank_aggregate.is_closed = True
        new_agg = bank_aggregate.reopen("reopener")
        assert new_agg.is_closed is False
        assert new_agg.version == bank_aggregate.version + 1
        assert new_agg._events[-1]["type"] == "REOPENED"

    def test_reopen_not_closed_raises(self, bank_aggregate):
        with pytest.raises(ValueError, match="not closed"):
            bank_aggregate.reopen("reopener")

    def test_archive(self, bank_aggregate):
        bank_aggregate.is_closed = True
        new_agg = bank_aggregate.archive("archiver")
        assert new_agg.is_archived is True
        assert new_agg.version == bank_aggregate.version + 1
        assert new_agg._events[-1]["type"] == "ARCHIVED"

    def test_archive_not_closed_raises(self, bank_aggregate):
        with pytest.raises(ValueError, match="Cannot archive open aggregate"):
            bank_aggregate.archive("archiver")

    def test_unarchive(self, bank_aggregate):
        bank_aggregate.is_archived = True
        new_agg = bank_aggregate.unarchive("unarchiver")
        assert new_agg.is_archived is False
        assert new_agg.version == bank_aggregate.version + 1
        assert new_agg._events[-1]["type"] == "UNARCHIVED"

    def test_unarchive_not_archived_raises(self, bank_aggregate):
        with pytest.raises(ValueError, match="not archived"):
            bank_aggregate.unarchive("unarchiver")

    # --- Event Methods ---
    def test_register_event(self, bank_aggregate):
        event = {"type": "test"}
        bank_aggregate.register_event(event)
        assert bank_aggregate._events == [event]

    def test_get_events(self, bank_aggregate):
        event = {"type": "test"}
        bank_aggregate.register_event(event)
        events = bank_aggregate.get_events()
        assert events == [event]
        # Should be a copy
        events.append({"type": "another"})
        assert bank_aggregate.get_events() == [event]

    def test_pull_events(self, bank_aggregate):
        e1 = {"type": "e1"}
        e2 = {"type": "e2"}
        bank_aggregate.register_event(e1)
        bank_aggregate.register_event(e2)
        pulled = bank_aggregate.pull_events()
        assert pulled == [e1, e2]
        assert bank_aggregate.get_events() == []

    def test_clear_events(self, bank_aggregate):
        bank_aggregate.register_event({"type": "test"})
        bank_aggregate.clear_events()
        assert bank_aggregate.get_events() == []

    def test_apply(self, bank_aggregate):
        event = {"type": "applied"}
        bank_aggregate.apply(event)
        assert bank_aggregate.get_events() == [event]

    def test_get_version(self, bank_aggregate):
        assert bank_aggregate.get_version() == 1

    def test_snapshot(self, bank_aggregate):
        with patch.object(bank_aggregate, "get_total_balance", return_value=Decimal("1000")):
            snap = bank_aggregate.snapshot()
            assert snap["version"] == 1
            assert snap["bank_id"] == str(bank_aggregate.bank_id)
            assert snap["total_balance"] == "1000"
            assert snap["is_closed"] is False

    # --- Account Management ---
    def test_add_account(self, bank_aggregate, sample_account):
        new_account = create_mock_account(account_id=uuid.uuid4())
        new_account.legal_entity_id = bank_aggregate.legal_entity_id
        new_agg = bank_aggregate.add_account(new_account)
        assert new_agg.accounts[new_account.account_id] is new_account

    def test_update_account(self, bank_aggregate, sample_account):
        updated_account = create_mock_account(account_id=sample_account.account_id, account_name="Updated")
        updated_account.legal_entity_id = bank_aggregate.legal_entity_id
        new_agg = bank_aggregate.update_account(updated_account)
        assert new_agg.accounts[sample_account.account_id] is updated_account
        assert new_agg.version == bank_aggregate.version + 1
        assert new_agg._events[-1]["type"] == "ACCOUNT_UPDATED"

    def test_update_account_not_found_raises(self, bank_aggregate):
        account = create_mock_account(account_id=uuid.uuid4())
        with pytest.raises(ValueError, match="not found"):
            bank_aggregate.update_account(account)

    def test_get_account(self, bank_aggregate, sample_account):
        assert bank_aggregate.get_account(sample_account.account_id) is sample_account
        assert bank_aggregate.get_account(uuid.uuid4()) is None

    def test_get_account_by_number(self, bank_aggregate, sample_account):
        sample_account.account_number = "12345"
        assert bank_aggregate.get_account_by_number("12345") is sample_account
        assert bank_aggregate.get_account_by_number("99999") is None

    def test_get_accounts_by_type(self, bank_aggregate, sample_account):
        sample_account.account_type = BankAccountType.SAVINGS
        result = bank_aggregate.get_accounts_by_type(BankAccountType.SAVINGS)
        assert len(result) == 1
        assert result[0] is sample_account
        assert bank_aggregate.get_accounts_by_type(BankAccountType.CHECKING) == []

    def test_get_active_accounts(self, bank_aggregate, sample_account):
        sample_account.status = BankAccountStatus.ACTIVE
        result = bank_aggregate.get_active_accounts()
        assert len(result) == 1
        assert result[0] is sample_account
        sample_account.status = BankAccountStatus.INACTIVE
        assert bank_aggregate.get_active_accounts() == []

    def test_get_accounts_by_currency(self, bank_aggregate, sample_account):
        sample_account.currency = "IDR"
        result = bank_aggregate.get_accounts_by_currency("IDR")
        assert len(result) == 1
        assert result[0] is sample_account
        assert bank_aggregate.get_accounts_by_currency("USD") == []

    # --- Deposit & Withdrawal ---
    def test_deposit(self, bank_aggregate, sample_account, fixed_now):
        with patch("domain.bank_cash.bank_aggregate_root.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.UTC = UTC
            new_agg = bank_aggregate.deposit(
                account_id=sample_account.account_id,
                amount=Decimal("1000"),
                description="Deposit test",
                created_by="tester",
                reference="REF-001",
            )
            sample_account.deposit.assert_called_once_with(Decimal("1000"), "tester")
            assert len(new_agg.transactions) == len(bank_aggregate.transactions) + 1
            new_tx = new_agg.transactions[-1]
            assert new_tx.amount == Decimal("1000")
            assert new_tx.transaction_type == BankTransactionType.DEPOSIT
            assert new_tx.status == BankTransactionStatus.PENDING
            assert new_tx.reference_number == "REF-001"
            assert new_agg.version == bank_aggregate.version + 1
            assert new_agg._events[-1]["type"] == "DEPOSIT"

    def test_deposit_invalid_amount_raises(self, bank_aggregate, sample_account):
        with pytest.raises(ValueError, match="positive"):
            bank_aggregate.deposit(
                account_id=sample_account.account_id,
                amount=Decimal("-100"),
                description="test",
                created_by="tester",
            )

    def test_deposit_account_not_found_raises(self, bank_aggregate):
        with pytest.raises(ValueError, match="not found"):
            bank_aggregate.deposit(
                account_id=uuid.uuid4(),
                amount=Decimal("100"),
                description="test",
                created_by="tester",
            )

    def test_withdraw(self, bank_aggregate, sample_account, fixed_now):
        with patch("domain.bank_cash.bank_aggregate_root.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.UTC = UTC
            new_agg = bank_aggregate.withdraw(
                account_id=sample_account.account_id,
                amount=Decimal("500"),
                description="Withdraw test",
                created_by="tester",
                reference="REF-002",
            )
            sample_account.withdraw.assert_called_once_with(Decimal("500"), "tester")
            new_tx = new_agg.transactions[-1]
            assert new_tx.amount == Decimal("500")
            assert new_tx.transaction_type == BankTransactionType.WITHDRAWAL
            assert new_tx.is_outflow is True
            assert new_tx.reference_number == "REF-002"
            assert new_agg.version == bank_aggregate.version + 1
            assert new_agg._events[-1]["type"] == "WITHDRAWAL"

    def test_withdraw_invalid_amount_raises(self, bank_aggregate, sample_account):
        with pytest.raises(ValueError, match="positive"):
            bank_aggregate.withdraw(
                account_id=sample_account.account_id,
                amount=Decimal("0"),
                description="test",
                created_by="tester",
            )

    def test_withdraw_insufficient_funds_raises(self, bank_aggregate, sample_account):
        sample_account.can_withdraw.return_value = False
        with pytest.raises(ValueError, match="Cannot withdraw"):
            bank_aggregate.withdraw(
                account_id=sample_account.account_id,
                amount=Decimal("100"),
                description="test",
                created_by="tester",
            )

    # --- Internal Transfer ---
    def test_transfer_internal(self, bank_aggregate, sample_account, fixed_now):
        from_account = sample_account
        to_account = create_mock_account(account_id=uuid.uuid4())
        to_account.legal_entity_id = bank_aggregate.legal_entity_id
        to_account.currency = "IDR"
        bank_aggregate.accounts[to_account.account_id] = to_account

        with patch("domain.bank_cash.bank_aggregate_root.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.UTC = UTC
            new_agg = bank_aggregate.transfer_internal(
                from_account_id=from_account.account_id,
                to_account_id=to_account.account_id,
                amount=Decimal("300"),
                description="Transfer test",
                created_by="tester",
                reference="REF-003",
            )
            from_account.withdraw.assert_called_once_with(Decimal("300"), "tester")
            to_account.deposit.assert_called_once_with(Decimal("300"), "tester")
            assert len(new_agg.transactions) == len(bank_aggregate.transactions) + 2
            out_tx, in_tx = new_agg.transactions[-2], new_agg.transactions[-1]
            assert out_tx.transaction_type == BankTransactionType.TRANSFER_OUT
            assert in_tx.transaction_type == BankTransactionType.TRANSFER_IN
            assert new_agg.version == bank_aggregate.version + 1
            assert new_agg._events[-1]["type"] == "INTERNAL_TRANSFER"

    def test_transfer_internal_same_account_raises(self, bank_aggregate, sample_account):
        with pytest.raises(ValueError, match="same account"):
            bank_aggregate.transfer_internal(
                from_account_id=sample_account.account_id,
                to_account_id=sample_account.account_id,
                amount=Decimal("100"),
                description="test",
                created_by="tester",
            )

    def test_transfer_internal_currency_mismatch_raises(self, bank_aggregate, sample_account):
        to_account = create_mock_account(account_id=uuid.uuid4(), currency="USD")
        to_account.legal_entity_id = bank_aggregate.legal_entity_id
        bank_aggregate.accounts[to_account.account_id] = to_account
        with pytest.raises(ValueError, match="Currency mismatch"):
            bank_aggregate.transfer_internal(
                from_account_id=sample_account.account_id,
                to_account_id=to_account.account_id,
                amount=Decimal("100"),
                description="test",
                created_by="tester",
            )

    # --- Transaction Management ---
    def test_add_transaction_deposit(self, bank_aggregate, sample_account, fixed_now):
        tx = create_mock_transaction(
            bank_account_id=sample_account.account_id,
            amount=Decimal("200"),
            transaction_type=BankTransactionType.DEPOSIT,
            is_outflow=False,
        )
        with patch("domain.bank_cash.bank_aggregate_root.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            new_agg = bank_aggregate.add_transaction(tx)
            sample_account.deposit.assert_called_once_with(Decimal("200"), tx.created_by)
            assert tx in new_agg.transactions
            assert new_agg.version == bank_aggregate.version + 1
            assert new_agg._events[-1]["type"] == "TRANSACTION_ADDED"

    def test_add_transaction_withdrawal(self, bank_aggregate, sample_account):
        tx = create_mock_transaction(
            bank_account_id=sample_account.account_id,
            amount=Decimal("200"),
            transaction_type=BankTransactionType.WITHDRAWAL,
            is_outflow=True,
        )
        bank_aggregate.add_transaction(tx)
        sample_account.withdraw.assert_called_once_with(Decimal("200"), tx.created_by)

    def test_add_transaction_insufficient_funds_raises(self, bank_aggregate, sample_account):
        sample_account.can_withdraw.return_value = False
        tx = create_mock_transaction(
            bank_account_id=sample_account.account_id,
            amount=Decimal("200"),
            is_outflow=True,
        )
        with pytest.raises(ValueError, match="Insufficient funds"):
            bank_aggregate.add_transaction(tx)

    def test_clear_transaction(self, bank_aggregate, sample_transaction, fixed_now):
        sample_transaction.status = BankTransactionStatus.PENDING
        with patch("domain.bank_cash.bank_aggregate_root.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            new_agg = bank_aggregate.clear_transaction(sample_transaction.transaction_id, "clearer")
            sample_transaction.mark_as_cleared.assert_called_once_with("clearer")
            assert new_agg.transactions[0] is sample_transaction
            assert new_agg.version == bank_aggregate.version + 1
            assert new_agg._events[-1]["type"] == "TRANSACTION_CLEARED"

    def test_clear_transaction_not_found_raises(self, bank_aggregate):
        with pytest.raises(ValueError, match="not found"):
            bank_aggregate.clear_transaction(uuid.uuid4(), "clearer")

    def test_clear_transaction_not_pending_raises(self, bank_aggregate, sample_transaction):
        sample_transaction.status = BankTransactionStatus.CLEARED
        with pytest.raises(ValueError, match="status cleared"):
            bank_aggregate.clear_transaction(sample_transaction.transaction_id, "clearer")

    def test_reconcile_transaction(self, bank_aggregate, sample_transaction, fixed_now):
        sample_transaction.is_reconciled = False
        with patch("domain.bank_cash.bank_aggregate_root.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            new_agg = bank_aggregate.reconcile_transaction(sample_transaction.transaction_id, uuid.uuid4())
            sample_transaction.mark_as_reconciled.assert_called_once()
            assert new_agg.version == bank_aggregate.version + 1
            assert new_agg._events[-1]["type"] == "TRANSACTION_RECONCILED"

    def test_reconcile_transaction_already_reconciled_raises(self, bank_aggregate, sample_transaction):
        sample_transaction.is_reconciled = True
        with pytest.raises(ValueError, match="already reconciled"):
            bank_aggregate.reconcile_transaction(sample_transaction.transaction_id, uuid.uuid4())

    def test_cancel_transaction(self, bank_aggregate, sample_transaction, fixed_now):
        sample_transaction.status = BankTransactionStatus.PENDING
        sample_transaction.is_outflow = False  # deposit
        sample_transaction.amount = Decimal("500")
        with patch("domain.bank_cash.bank_aggregate_root.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            new_agg = bank_aggregate.cancel_transaction(
                sample_transaction.transaction_id, uuid.uuid4(), "test cancel"
            )
            sample_transaction.cancel.assert_called_once()
            # Account balance should be reversed: for deposit, withdraw the amount
            sample_account = new_agg.accounts[sample_transaction.bank_account_id]
            sample_account.withdraw.assert_called_once_with(Decimal("500"), cancelled_by=uuid.uuid4())
            assert new_agg.version == bank_aggregate.version + 1
            assert new_agg._events[-1]["type"] == "TRANSACTION_CANCELLED"

    def test_cancel_transaction_not_found_raises(self, bank_aggregate):
        with pytest.raises(ValueError, match="not found"):
            bank_aggregate.cancel_transaction(uuid.uuid4(), uuid.uuid4(), "reason")

    def test_cancel_transaction_cleared_raises(self, bank_aggregate, sample_transaction):
        sample_transaction.status = BankTransactionStatus.CLEARED
        with pytest.raises(ValueError, match="Cannot cancel cleared/reconciled"):
            bank_aggregate.cancel_transaction(sample_transaction.transaction_id, uuid.uuid4(), "reason")

    def test_cancel_transaction_reconciled_raises(self, bank_aggregate, sample_transaction):
        sample_transaction.is_reconciled = True
        with pytest.raises(ValueError, match="Cannot cancel cleared/reconciled"):
            bank_aggregate.cancel_transaction(sample_transaction.transaction_id, uuid.uuid4(), "reason")

    # --- Queries ---
    def test_get_transactions(self, bank_aggregate, sample_transaction):
        # Add more transactions
        tx2 = create_mock_transaction(bank_account_id=sample_transaction.bank_account_id)
        tx2.amount = Decimal("500")
        tx2.created_at = fixed_now + timedelta(hours=1)
        bank_aggregate.transactions.append(tx2)

        result = bank_aggregate.get_transactions(limit=100)
        assert len(result) == 2
        # Order by created_at descending: tx2 then sample_transaction
        assert result[0].created_at > result[1].created_at

        # Filter by status
        result2 = bank_aggregate.get_transactions(status=BankTransactionStatus.PENDING)
        assert len(result2) == 2

        # Filter by account
        result3 = bank_aggregate.get_transactions(account_id=sample_transaction.bank_account_id)
        assert len(result3) == 2

        result4 = bank_aggregate.get_transactions(account_id=uuid.uuid4())
        assert len(result4) == 0

        # Test pagination
        result5 = bank_aggregate.get_transactions(limit=1, offset=1)
        assert len(result5) == 1
        assert result5[0].transaction_id == tx2.transaction_id  # second item (offset 1)

        # Test type filter
        result6 = bank_aggregate.get_transactions(tx_type=BankTransactionType.DEPOSIT)
        assert len(result6) == 1

    def test_get_transactions_with_dates(self, bank_aggregate, sample_transaction, fixed_now):
        tx2 = create_mock_transaction(
            created_at=fixed_now - timedelta(days=1),
            transaction_date=date(2026, 6, 14),
        )
        bank_aggregate.transactions.append(tx2)

        from_date = fixed_now - timedelta(hours=12)
        to_date = fixed_now + timedelta(hours=12)
        result = bank_aggregate.get_transactions(from_date=from_date, to_date=to_date)
        # Should only include sample_transaction
        assert len(result) == 1
        assert result[0].transaction_id == sample_transaction.transaction_id

    def test_get_pending_transactions(self, bank_aggregate, sample_transaction):
        tx2 = create_mock_transaction(
            bank_account_id=sample_transaction.bank_account_id,
            status=BankTransactionStatus.CLEARED,
        )
        bank_aggregate.transactions.append(tx2)
        pending = bank_aggregate.get_pending_transactions()
        assert len(pending) == 1
        assert pending[0].transaction_id == sample_transaction.transaction_id

    def test_get_unreconciled_transactions(self, bank_aggregate, sample_transaction):
        tx2 = create_mock_transaction(
            bank_account_id=sample_transaction.bank_account_id,
            is_reconciled=True,
        )
        bank_aggregate.transactions.append(tx2)
        unreconciled = bank_aggregate.get_unreconciled_transactions(sample_transaction.bank_account_id)
        assert len(unreconciled) == 1
        assert unreconciled[0].transaction_id == sample_transaction.transaction_id

    # --- Balance Calculations ---
    def test_get_account_balance(self, bank_aggregate, sample_transaction):
        # Sample transaction is a deposit (inflow) of 1000
        # But we need to set is_inflow properly in the mock.
        sample_transaction.is_inflow = True
        sample_transaction.is_outflow = False
        balance = bank_aggregate.get_account_balance(sample_transaction.bank_account_id)
        # Only one inflow of 1000, no outflows
        assert balance == Decimal("1000.00")

        # Add outflow
        tx2 = create_mock_transaction(
            bank_account_id=sample_transaction.bank_account_id,
            amount=Decimal("300"),
            is_outflow=True,
            is_inflow=False,
            status=BankTransactionStatus.CLEARED,
        )
        bank_aggregate.transactions.append(tx2)
        balance2 = bank_aggregate.get_account_balance(sample_transaction.bank_account_id)
        assert balance2 == Decimal("700.00")

    def test_get_account_balance_ignores_cancelled(self, bank_aggregate, sample_transaction):
        sample_transaction.is_inflow = True
        sample_transaction.is_outflow = False
        tx2 = create_mock_transaction(
            bank_account_id=sample_transaction.bank_account_id,
            amount=Decimal("500"),
            is_inflow=False,
            is_outflow=True,
            status=BankTransactionStatus.CANCELLED,
        )
        bank_aggregate.transactions.append(tx2)
        balance = bank_aggregate.get_account_balance(sample_transaction.bank_account_id)
        # Cancelled transaction ignored, so only 1000 inflow
        assert balance == Decimal("1000.00")

    def test_get_available_balance(self, bank_aggregate, sample_transaction):
        sample_transaction.is_inflow = True
        sample_transaction.is_outflow = False
        tx2 = create_mock_transaction(
            bank_account_id=sample_transaction.bank_account_id,
            amount=Decimal("300"),
            is_outflow=True,
            is_inflow=False,
            status=BankTransactionStatus.PENDING,
        )
        bank_aggregate.transactions.append(tx2)
        balance = bank_aggregate.get_available_balance(sample_transaction.bank_account_id)
        # Available balance includes pending too, so 1000 - 300 = 700
        assert balance == Decimal("700.00")

    def test_get_available_balance_with_overdraft(self, bank_aggregate, sample_account):
        sample_account.allow_overdraft = True
        sample_account.overdraft_limit = Decimal("500")
        sample_account.current_balance = Decimal("0")  # not really used in calculation

        # Add inflow 100, outflow 200 (net -100)
        tx1 = create_mock_transaction(
            bank_account_id=sample_account.account_id,
            amount=Decimal("100"),
            is_inflow=True,
            is_outflow=False,
        )
        tx2 = create_mock_transaction(
            bank_account_id=sample_account.account_id,
            amount=Decimal("200"),
            is_inflow=False,
            is_outflow=True,
        )
        bank_aggregate.transactions = [tx1, tx2]
        # Net = 100 - 200 = -100, overdraft limit 500, so available balance = 0? Actually it returns 0 if overdraft exceeds limit.
        # The method returns 0 if balance < 0 and abs(balance) > overdraft_limit, but here abs(-100) < 500, so it returns balance (-100)
        balance = bank_aggregate.get_available_balance(sample_account.account_id)
        # The method calculates total_credit - total_debit, then checks overdraft.
        # total_credit = 100, total_debit = 200, balance = -100.
        # abs(-100) <= 500 => returns -100.
        assert balance == Decimal("-100.00")

        # If overdraft limit is exceeded, returns 0
        sample_account.overdraft_limit = Decimal("50")
        balance2 = bank_aggregate.get_available_balance(sample_account.account_id)
        assert balance2 == Decimal("0")

    def test_get_total_balance(self, bank_aggregate, sample_account):
        # Two accounts: first has balance 1000, second has balance 2000
        account2 = create_mock_account(account_id=uuid.uuid4())
        account2.current_balance = Decimal("2000")
        bank_aggregate.accounts[account2.account_id] = account2

        # Override get_account_balance to return expected values
        with patch.object(bank_aggregate, "get_account_balance") as mock_balance:
            mock_balance.side_effect = lambda acc_id: Decimal("1000") if acc_id == sample_account.account_id else Decimal("2000")
            total = bank_aggregate.get_total_balance()
            assert total == Decimal("3000.00")

    def test_get_account_balance_at_date(self, bank_aggregate, sample_transaction, fixed_now):
        sample_transaction.is_inflow = True
        sample_transaction.is_outflow = False
        sample_transaction.created_at = fixed_now - timedelta(days=1)
        # Add a transaction on a later date that should be excluded
        tx2 = create_mock_transaction(
            bank_account_id=sample_transaction.bank_account_id,
            amount=Decimal("500"),
            is_inflow=True,
            is_outflow=False,
            created_at=fixed_now + timedelta(days=1),
        )
        bank_aggregate.transactions.append(tx2)
        target = fixed_now  # before tx2
        balance = bank_aggregate.get_account_balance_at_date(sample_transaction.bank_account_id, target)
        # Only tx1 (1000) included
        assert balance == Decimal("1000.00")

    # --- Reconciliation ---
    def test_reconcile(self, bank_aggregate, sample_account, fixed_now):
        sample_account.account_id = uuid.uuid4()
        # Mock BankReconciliationEngine
        with patch("domain.bank_cash.bank_aggregate_root.BankReconciliationEngine") as mock_engine_class:
            mock_engine = MagicMock()
            mock_engine_class.return_value = mock_engine
            result = MagicMock(spec=ReconResult)
            result.status = "MATCHED"
            result.matched_items = []
            mock_engine.reconcile.return_value = result

            # Mock mark_reconciled
            sample_account.mark_reconciled = MagicMock(return_value=sample_account)

            new_agg, recon_result = bank_aggregate.reconcile(
                account_id=sample_account.account_id,
                statement_balance=Decimal("1000"),
                statement_date=fixed_now,
                statement_transactions=[],
                reconciled_by="tester",
            )
            mock_engine.reconcile.assert_called_once()
            sample_account.mark_reconciled.assert_called_once_with(Decimal("1000"), "tester")
            assert recon_result is result
            assert new_agg.version == bank_aggregate.version + 1
            assert new_agg._events[-1]["type"] == "RECONCILIATION"

    def test_reconcile_account_not_found_raises(self, bank_aggregate):
        with pytest.raises(ValueError, match="not found"):
            bank_aggregate.reconcile(
                account_id=uuid.uuid4(),
                statement_balance=Decimal("1000"),
                statement_date=datetime.now(UTC),
                statement_transactions=[],
                reconciled_by="tester",
            )

    # --- Summary & Reporting ---
    def test_get_summary(self, bank_aggregate, sample_account, sample_transaction, fixed_now):
        with patch("domain.bank_cash.bank_aggregate_root.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.UTC = UTC
            sample_account.is_active.return_value = True
            sample_transaction.is_outflow = True
            sample_transaction.is_inflow = False
            sample_transaction.amount = Decimal("500")

            # Add another transaction today
            tx2 = create_mock_transaction(
                bank_account_id=sample_transaction.bank_account_id,
                amount=Decimal("200"),
                is_inflow=True,
                is_outflow=False,
                created_at=fixed_now,
                transaction_date=fixed_now.date(),
            )
            bank_aggregate.transactions.append(tx2)

            # Mock get_total_balance
            with patch.object(bank_aggregate, "get_total_balance", return_value=Decimal("1000000")):
                summary = bank_aggregate.get_summary(target_date=fixed_now.date())
                assert summary.total_accounts == 1
                assert summary.active_accounts == 1
                assert summary.total_balance == Decimal("1000000")
                # Total debit today = outflow amount (500)
                assert summary.total_debit_today == Decimal("500")
                # Total credit today = inflow amount (200)
                assert summary.total_credit_today == Decimal("200")
                assert summary.last_transaction_date == fixed_now

    def test_generate_statement(self, bank_aggregate, sample_account, fixed_now):
        sample_account.account_number = "12345"
        sample_account.account_name = "Test Account"
        sample_account.currency = "IDR"

        # Add transactions with different dates
        tx1 = create_mock_transaction(
            bank_account_id=sample_account.account_id,
            amount=Decimal("1000"),
            is_inflow=True,
            is_outflow=False,
            created_at=fixed_now - timedelta(days=2),
            transaction_date=fixed_now.date() - timedelta(days=2),
            description="Deposit 1",
        )
        tx2 = create_mock_transaction(
            bank_account_id=sample_account.account_id,
            amount=Decimal("200"),
            is_inflow=False,
            is_outflow=True,
            created_at=fixed_now - timedelta(days=1),
            transaction_date=fixed_now.date() - timedelta(days=1),
            description="Withdraw 1",
        )
        bank_aggregate.transactions = [tx1, tx2]

        from_date = fixed_now - timedelta(days=3)
        to_date = fixed_now + timedelta(days=1)

        with patch.object(bank_aggregate, "get_account_balance_at_date") as mock_balance:
            mock_balance.return_value = Decimal("5000")
            statement = bank_aggregate.generate_statement(sample_account.account_id, from_date, to_date)

            assert statement["account_id"] == str(sample_account.account_id)
            assert statement["opening_balance"] == "5000"
            assert statement["closing_balance"] == "5800"  # opening 5000 + 1000 - 200 = 5800
            assert len(statement["entries"]) == 2
            assert statement["total_debit"] == "200"
            assert statement["total_credit"] == "1000"

    def test_generate_statement_account_not_found_raises(self, bank_aggregate):
        with pytest.raises(ValueError, match="not found"):
            bank_aggregate.generate_statement(uuid.uuid4(), datetime.now(UTC), datetime.now(UTC))

    # --- Serialization ---
    def test_to_dict(self, bank_aggregate):
        with patch.object(bank_aggregate, "get_total_balance", return_value=Decimal("1000")):
            d = bank_aggregate.to_dict()
            assert d["bank_id"] == str(bank_aggregate.bank_id)
            assert d["legal_entity_id"] == str(bank_aggregate.legal_entity_id)
            assert d["accounts_count"] == 1
            assert d["transactions_count"] == 1
            assert d["reconciliations_count"] == 0
            assert d["total_balance"] == "1000"
            assert d["is_closed"] is False
            assert d["is_archived"] is False

    def test_from_dict(self, bank_id, legal_entity_id, fixed_now):
        data = {
            "bank_id": str(bank_id),
            "legal_entity_id": str(legal_entity_id),
            "created_at": fixed_now.isoformat(),
            "updated_at": fixed_now.isoformat(),
            "version": 3,
            "is_closed": True,
            "is_archived": False,
        }
        agg = BankAggregate.from_dict(data)
        assert agg.bank_id == bank_id
        assert agg.legal_entity_id == legal_entity_id
        assert agg.created_at == fixed_now
        assert agg.version == 3
        assert agg.is_closed is True

    # --- Private methods (indirectly tested) ---
    # _validate_account_exists, _validate_positive_amount are tested via other methods


# ============================================================================
# BANK AGGREGATE REPOSITORY STUB TESTS
# ============================================================================

class TestBankAggregateRepository:
    @pytest.mark.asyncio
    async def test_methods_raise_not_implemented(self):
        repo = BankAggregateRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_legal_entity(uuid.uuid4())
        with pytest.raises(NotImplementedError):
            await repo.save(MagicMock())
        with pytest.raises(NotImplementedError):
            await repo.delete(uuid.uuid4())

    @pytest.mark.asyncio
    async def test_method_signatures(self):
        # Just test that methods exist and are async
        repo = BankAggregateRepository()
        assert hasattr(repo, "get_by_legal_entity")
        assert hasattr(repo, "save")
        assert hasattr(repo, "delete")


# ============================================================================
# ALIASES TESTS
# ============================================================================

class TestAliases:
    def test_bank_account_aggregate_alias(self):
        assert BankAccountAggregate is BankAggregate

    def test_bank_reconciliation_alias(self):
        assert BankReconciliation is ReconciliationResult
