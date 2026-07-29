# tests/adapters/secondary_impl/test_sqlalchemy_cash_book_repository.py
"""
Comprehensive tests for adapters/secondary_impl/sqlalchemy_cash_book_repository.py
Covers all public methods, private helpers, edge cases, and exceptions.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from adapters.secondary_impl.sqlalchemy_cash_book_repository import (
    CashBookTable,
    CashTransactionTable,
    SQLAlchemyCashBookRepository,
)
from ports.primary.bank_cash_repository_port import CashBook, CashTransaction

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_session():
    session = AsyncMock(spec=AsyncSession)
    session.begin = AsyncMock()
    session.execute = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    return session


@pytest.fixture
def repo(mock_session):
    return SQLAlchemyCashBookRepository(session=mock_session)


@pytest.fixture
def sample_cash_book():
    return CashBook(
        id=uuid.uuid4(),
        legal_entity_id=uuid.uuid4(),
        cash_type="MAIN_CASH",
        currency_code="IDR",
        opening_balance=Decimal("1000000"),
        current_balance=Decimal("1000000"),
        created_by=uuid.uuid4(),
        updated_by=uuid.uuid4(),
    )


@pytest.fixture
def sample_cash_transaction():
    return CashTransaction(
        id=uuid.uuid4(),
        cash_book_id=uuid.uuid4(),
        transaction_date=date.today(),
        transaction_type="CASH_IN",
        amount=Decimal("500000"),
        description="Deposit",
        reference_type="INVOICE",
        reference_id=uuid.uuid4(),
        journal_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
    )


@pytest.fixture
def mock_cash_book_row(sample_cash_book):
    row = MagicMock(spec=CashBookTable)
    row.id = sample_cash_book.id
    row.legal_entity_id = sample_cash_book.legal_entity_id
    row.cash_type = sample_cash_book.cash_type
    row.currency_code = sample_cash_book.currency_code
    row.opening_balance = sample_cash_book.opening_balance
    row.current_balance = sample_cash_book.current_balance
    row.created_at = datetime.utcnow()
    row.updated_at = None
    row.created_by = sample_cash_book.created_by
    row.updated_by = sample_cash_book.updated_by
    return row


@pytest.fixture
def mock_cash_tx_row(sample_cash_transaction):
    row = MagicMock(spec=CashTransactionTable)
    row.id = sample_cash_transaction.id
    row.cash_book_id = sample_cash_transaction.cash_book_id
    row.transaction_date = sample_cash_transaction.transaction_date
    row.transaction_type = sample_cash_transaction.transaction_type
    row.amount = sample_cash_transaction.amount
    row.description = sample_cash_transaction.description
    row.reference_type = sample_cash_transaction.reference_type
    row.reference_id = sample_cash_transaction.reference_id
    row.journal_id = sample_cash_transaction.journal_id
    row.created_at = datetime.utcnow()
    row.created_by = sample_cash_transaction.created_by
    return row


# ============================================================================
# Test ORM table models
# ============================================================================

class TestCashBookTable:
    def test_tablename_defined(self):
        assert CashBookTable.__tablename__ == "cash_books"

    def test_instantiation(self):
        instance = CashBookTable(
            id=uuid.uuid4(),
            legal_entity_id=uuid.uuid4(),
            cash_type="MAIN_CASH",
            currency_code="IDR",
            opening_balance=Decimal("1000"),
            current_balance=Decimal("1000"),
            created_by=uuid.uuid4(),
        )
        assert isinstance(instance, CashBookTable)


class TestCashTransactionTable:
    def test_tablename_defined(self):
        assert CashTransactionTable.__tablename__ == "cash_transactions"

    def test_instantiation(self):
        instance = CashTransactionTable(
            id=uuid.uuid4(),
            cash_book_id=uuid.uuid4(),
            transaction_date=date.today(),
            transaction_type="CASH_IN",
            amount=Decimal("100"),
            description="Test",
            reference_type="REF",
            reference_id=uuid.uuid4(),
            journal_id=uuid.uuid4(),
            created_by=uuid.uuid4(),
        )
        assert isinstance(instance, CashTransactionTable)


# ============================================================================
# Tests for SQLAlchemyCashBookRepository
# ============================================================================

class TestSQLAlchemyCashBookRepository:
    # ---- Construction and session ----
    def test_construction_with_session(self, mock_session):
        repo = SQLAlchemyCashBookRepository(session=mock_session)
        assert repo._session is mock_session

    def test_construction_without_session(self):
        with patch("adapters.secondary_impl.sqlalchemy_cash_book_repository.get_async_session") as mock_get:
            mock_get.return_value = AsyncMock()
            repo = SQLAlchemyCashBookRepository()
            assert repo._session is None
            # _get_session will initialize later

    @pytest.mark.asyncio
    async def test_get_session_initializes(self, repo):
        with patch("adapters.secondary_impl.sqlalchemy_cash_book_repository.get_async_session") as mock_get:
            mock_session = AsyncMock()
            mock_get.return_value = mock_session
            session = await repo._get_session()
            assert session is mock_session
            assert repo._session is mock_session

    # ---- _log_audit ----
    @pytest.mark.asyncio
    async def test_log_audit(self, repo):
        cash_book_id = uuid.uuid4()
        user_id = uuid.uuid4()
        details = {"key": "value"}
        await repo._log_audit("TEST", cash_book_id, user_id, details)
        assert len(repo._audit_log) == 1
        entry = repo._audit_log[0]
        assert entry["action"] == "TEST"
        assert entry["cash_book_id"] == str(cash_book_id)
        assert entry["user_id"] == str(user_id)
        assert entry["details"] == details
        assert "timestamp" in entry

    # ---- _to_cash_book ----
    def test_to_cash_book(self, repo, mock_cash_book_row, sample_cash_book):
        result = repo._to_cash_book(mock_cash_book_row)
        assert isinstance(result, CashBook)
        assert result.id == sample_cash_book.id
        assert result.legal_entity_id == sample_cash_book.legal_entity_id
        assert result.cash_type == sample_cash_book.cash_type
        assert result.currency_code == sample_cash_book.currency_code
        assert result.opening_balance == sample_cash_book.opening_balance
        assert result.current_balance == sample_cash_book.current_balance
        assert result.created_by == sample_cash_book.created_by
        assert result.updated_by == sample_cash_book.updated_by
        assert result.created_at == mock_cash_book_row.created_at
        assert result.updated_at == mock_cash_book_row.updated_at

    # ---- _to_cash_transaction ----
    def test_to_cash_transaction(self, repo, mock_cash_tx_row, sample_cash_transaction):
        result = repo._to_cash_transaction(mock_cash_tx_row)
        assert isinstance(result, CashTransaction)
        assert result.id == sample_cash_transaction.id
        assert result.cash_book_id == sample_cash_transaction.cash_book_id
        assert result.transaction_date == sample_cash_transaction.transaction_date
        assert result.transaction_type == sample_cash_transaction.transaction_type
        assert result.amount == sample_cash_transaction.amount
        assert result.description == sample_cash_transaction.description
        assert result.reference_type == sample_cash_transaction.reference_type
        assert result.reference_id == sample_cash_transaction.reference_id
        assert result.journal_id == sample_cash_transaction.journal_id
        assert result.created_by == sample_cash_transaction.created_by
        assert result.created_at == mock_cash_tx_row.created_at

    # ---- add ----
    @pytest.mark.asyncio
    async def test_add_success(self, repo, mock_session, sample_cash_book):
        # Mock select to return no existing row
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = AsyncMock(return_value=None)
        mock_session.execute.return_value = mock_result

        await repo.add(sample_cash_book)

        # Verify that select was called
        mock_session.execute.assert_called_once()
        # Verify add was called with CashBookTable
        mock_session.add.assert_called_once()
        args, _ = mock_session.add.call_args
        added_obj = args[0]
        assert isinstance(added_obj, CashBookTable)
        assert added_obj.id == sample_cash_book.id
        assert added_obj.legal_entity_id == sample_cash_book.legal_entity_id
        assert added_obj.cash_type == sample_cash_book.cash_type
        assert added_obj.currency_code == sample_cash_book.currency_code
        assert added_obj.opening_balance == sample_cash_book.opening_balance
        assert added_obj.current_balance == sample_cash_book.current_balance
        assert added_obj.created_by == sample_cash_book.created_by
        mock_session.commit.assert_awaited_once()
        # Check audit log
        assert len(repo._audit_log) == 1
        assert repo._audit_log[0]["action"] == "ADD"

    @pytest.mark.asyncio
    async def test_add_duplicate_raises(self, repo, mock_session, sample_cash_book):
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = AsyncMock(return_value=MagicMock())
        mock_session.execute.return_value = mock_result

        with pytest.raises(ValueError, match="already exists"):
            await repo.add(sample_cash_book)
        mock_session.add.assert_not_called()
        mock_session.commit.assert_not_awaited()

    # ---- get_by_id ----
    @pytest.mark.asyncio
    async def test_get_by_id_found(self, repo, mock_session, mock_cash_book_row, sample_cash_book):
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = AsyncMock(return_value=mock_cash_book_row)
        mock_session.execute.return_value = mock_result

        result = await repo.get_by_id(sample_cash_book.id)
        assert result is not None
        assert result.id == sample_cash_book.id
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, repo, mock_session):
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = AsyncMock(return_value=None)
        mock_session.execute.return_value = mock_result

        result = await repo.get_by_id(uuid.uuid4())
        assert result is None

    # ---- get_by_legal_entity_and_currency ----
    @pytest.mark.asyncio
    async def test_get_by_legal_entity_and_currency_found(self, repo, mock_session, mock_cash_book_row, sample_cash_book):
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = AsyncMock(return_value=mock_cash_book_row)
        mock_session.execute.return_value = mock_result

        result = await repo.get_by_legal_entity_and_currency(
            sample_cash_book.legal_entity_id, "IDR", "MAIN_CASH"
        )
        assert result is not None
        assert result.id == sample_cash_book.id
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_by_legal_entity_and_currency_not_found(self, repo, mock_session):
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = AsyncMock(return_value=None)
        mock_session.execute.return_value = mock_result

        result = await repo.get_by_legal_entity_and_currency(uuid.uuid4(), "IDR")
        assert result is None

    # ---- update ----
    @pytest.mark.asyncio
    async def test_update_success(self, repo, mock_session, sample_cash_book, mock_cash_book_row):
        # Mock the select with locking
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = AsyncMock(return_value=mock_cash_book_row)
        mock_session.execute.return_value = mock_result

        # Update some fields
        sample_cash_book.current_balance = Decimal("2000000")
        sample_cash_book.currency_code = "USD"
        sample_cash_book.cash_type = "PETTY_CASH"
        sample_cash_book.updated_by = uuid.uuid4()

        await repo.update(sample_cash_book)

        # Verify row was updated
        assert mock_cash_book_row.currency_code == "USD"
        assert mock_cash_book_row.cash_type == "PETTY_CASH"
        assert mock_cash_book_row.current_balance == Decimal("2000000")
        assert mock_cash_book_row.updated_by == sample_cash_book.updated_by
        assert mock_cash_book_row.updated_at is not None
        mock_session.flush.assert_awaited_once()
        # Check audit log
        assert len(repo._audit_log) == 1
        assert repo._audit_log[0]["action"] == "UPDATE"
        assert "balance" in repo._audit_log[0]["details"]

    @pytest.mark.asyncio
    async def test_update_not_found_raises(self, repo, mock_session, sample_cash_book):
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = AsyncMock(return_value=None)
        mock_session.execute.return_value = mock_result

        with pytest.raises(ValueError, match="not found"):
            await repo.update(sample_cash_book)
        mock_session.flush.assert_not_awaited()

    # ---- record_transaction ----
    @pytest.mark.asyncio
    async def test_record_transaction_cash_in(self, repo, mock_session, sample_cash_book, mock_cash_book_row):
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = AsyncMock(return_value=mock_cash_book_row)
        mock_session.execute.return_value = mock_result

        cash_book_id = sample_cash_book.id
        amount = Decimal("500000")
        reference_id = uuid.uuid4()
        user_id = uuid.uuid4()

        tx = await repo.record_transaction(
            cash_book_id=cash_book_id,
            transaction_type="CASH_IN",
            amount=amount,
            reference_type="INVOICE",
            reference_id=reference_id,
            description="Test deposit",
            user_id=user_id,
            journal_id=uuid.uuid4(),
        )

        assert isinstance(tx, CashTransaction)
        assert tx.cash_book_id == cash_book_id
        assert tx.amount == amount
        assert tx.transaction_type == "CASH_IN"
        # Check balance update
        assert mock_cash_book_row.current_balance == sample_cash_book.current_balance + amount
        assert mock_cash_book_row.updated_by == user_id
        # Check transaction insert
        mock_session.add.assert_called_once()
        added_obj = mock_session.add.call_args[0][0]
        assert isinstance(added_obj, CashTransactionTable)
        assert added_obj.cash_book_id == cash_book_id
        assert added_obj.amount == amount
        assert added_obj.transaction_type == "CASH_IN"
        mock_session.flush.assert_awaited_once()
        # Audit log
        assert len(repo._audit_log) == 1

    @pytest.mark.asyncio
    async def test_record_transaction_cash_out_success(self, repo, mock_session, sample_cash_book, mock_cash_book_row):
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = AsyncMock(return_value=mock_cash_book_row)
        mock_session.execute.return_value = mock_result

        amount = Decimal("200000")
        cash_book_id = sample_cash_book.id
        user_id = uuid.uuid4()

        tx = await repo.record_transaction(
            cash_book_id=cash_book_id,
            transaction_type="CASH_OUT",
            amount=amount,
            reference_type="PAYMENT",
            reference_id=uuid.uuid4(),
            description="Payment",
            user_id=user_id,
        )
        assert tx.amount == amount
        assert tx.transaction_type == "CASH_OUT"
        expected_balance = sample_cash_book.current_balance - amount
        assert mock_cash_book_row.current_balance == expected_balance

    @pytest.mark.asyncio
    async def test_record_transaction_insufficient_balance(self, repo, mock_session, sample_cash_book, mock_cash_book_row):
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = AsyncMock(return_value=mock_cash_book_row)
        mock_session.execute.return_value = mock_result

        # Set balance low
        mock_cash_book_row.current_balance = Decimal("100")

        with pytest.raises(ValueError, match="Insufficient cash balance"):
            await repo.record_transaction(
                cash_book_id=sample_cash_book.id,
                transaction_type="CASH_OUT",
                amount=Decimal("200"),
                reference_type="PAYMENT",
                reference_id=uuid.uuid4(),
                description="Test",
                user_id=uuid.uuid4(),
            )
        mock_session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_record_transaction_cash_book_not_found(self, repo, mock_session):
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = AsyncMock(return_value=None)
        mock_session.execute.return_value = mock_result

        with pytest.raises(ValueError, match="not found"):
            await repo.record_transaction(
                cash_book_id=uuid.uuid4(),
                transaction_type="CASH_IN",
                amount=Decimal("100"),
                reference_type="REF",
                reference_id=uuid.uuid4(),
                description="Test",
                user_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_record_transaction_invalid_type(self, repo, mock_session, sample_cash_book):
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = AsyncMock(return_value=MagicMock())
        mock_session.execute.return_value = mock_result

        with pytest.raises(ValueError, match="must be CASH_IN or CASH_OUT"):
            await repo.record_transaction(
                cash_book_id=sample_cash_book.id,
                transaction_type="INVALID",
                amount=Decimal("100"),
                reference_type="REF",
                reference_id=uuid.uuid4(),
                description="Test",
                user_id=uuid.uuid4(),
            )

    # ---- get_balance ----
    @pytest.mark.asyncio
    async def test_get_balance(self, repo, mock_session, sample_cash_book):
        # Mock cash_book retrieval
        mock_cash_book_row = MagicMock()
        mock_cash_book_row.opening_balance = Decimal("1000000")
        mock_result_cb = AsyncMock()
        mock_result_cb.scalar_one_or_none = AsyncMock(return_value=mock_cash_book_row)
        mock_session.execute.return_value = mock_result_cb

        # Mock sum queries
        mock_sum_in = AsyncMock()
        mock_sum_in.scalar.return_value = Decimal("500000")
        mock_sum_out = AsyncMock()
        mock_sum_out.scalar.return_value = Decimal("200000")

        # Side effect for execute: first call returns cash_book, second returns sum_in, third returns sum_out
        mock_session.execute.side_effect = [
            mock_result_cb,
            mock_sum_in,
            mock_sum_out,
        ]

        balance = await repo.get_balance(sample_cash_book.id, date(2026, 1, 15))
        expected = Decimal("1000000") + Decimal("500000") - Decimal("200000")  # = 1300000
        assert balance == expected

    @pytest.mark.asyncio
    async def test_get_balance_cash_book_not_found(self, repo, mock_session):
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = AsyncMock(return_value=None)
        mock_session.execute.return_value = mock_result

        with pytest.raises(ValueError, match="not found"):
            await repo.get_balance(uuid.uuid4(), date.today())

    # ---- get_transactions ----
    @pytest.mark.asyncio
    async def test_get_transactions(self, repo, mock_session, mock_cash_tx_row):
        mock_result = AsyncMock()
        mock_result.scalars.return_value.all = MagicMock(return_value=[mock_cash_tx_row])
        mock_session.execute.return_value = mock_result

        start = date(2026, 1, 1)
        end = date(2026, 1, 31)
        cash_book_id = uuid.uuid4()
        transactions = await repo.get_transactions(cash_book_id, start, end)

        assert len(transactions) == 1
        assert isinstance(transactions[0], CashTransaction)
        assert transactions[0].id == mock_cash_tx_row.id
        # Verify query filters
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_transactions_empty(self, repo, mock_session):
        mock_result = AsyncMock()
        mock_result.scalars.return_value.all = MagicMock(return_value=[])
        mock_session.execute.return_value = mock_result

        transactions = await repo.get_transactions(uuid.uuid4(), date.today(), date.today())
        assert transactions == []
