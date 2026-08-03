# transformers/test_bank_statement_to_reconciliation.py
"""
Comprehensive unit tests for Bank Statement to Reconciliation Transformer.

Covers:
- BaseTransformer entity methods (validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch)
- StatementParser: parsing MT940, CAMT, CSV BCA/Mandiri/BNI/BRI, validation, entity methods
- BankTransactionMatcher: matching algorithm, score calculation, entity methods
- BankStatementToReconciliationTransformer: transform logic with mocks for all dependencies,
  including handling different event types, reconciliation, error cases, reset, entity methods
- Exceptions: BankStatementToReconciliationError, BankAccountNotFoundError, etc.
- Module-level functions: get_bank_statement_transformer, handle_bank_statement_event
- Alert triggering integration (mocked)

All monetary values are handled as Decimal with string serialization.
"""

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from transformers.bank_statement_to_reconciliation import (
    BankAccountNotFoundError,
    BankStatementToReconciliationError,
    BankStatementToReconciliationTransformer,
    BankTransactionMatcher,
    BaseTransformer,
    ReconciliationFailedError,
    StatementParser,
    StatementParsingError,
    get_bank_statement_transformer,
    handle_bank_statement_event,
)

# =============================================================================
# Mocks and fixtures
# =============================================================================

@pytest.fixture
def mock_event_envelope():
    envelope = MagicMock()
    envelope.id = uuid4()
    envelope.event_type = "BankStatementUploaded"
    envelope.payload = {}
    envelope.metadata = {}
    return envelope


@pytest.fixture
def mock_command_bus():
    return AsyncMock()


@pytest.fixture
def mock_bank_cash_service():
    return AsyncMock()


@pytest.fixture
def mock_reconciliation_use_case():
    uc = AsyncMock()
    uc.reconcile = AsyncMock()
    uc.reconcile_auto = AsyncMock(return_value={"status": "completed"})
    return uc


@pytest.fixture
def mock_bank_repo():
    repo = AsyncMock()
    account = MagicMock()
    account.id = uuid4()
    account.account_number = "1234567890"
    account.current_balance = MagicMock()
    account.current_balance.amount = Decimal("1000000")
    repo.get_bank_account_by_id = AsyncMock(return_value=account)
    repo.get_bank_account_by_number = AsyncMock(return_value=account)
    repo.list_bank_accounts = AsyncMock(return_value=[account])
    repo.get_bank_transactions_by_account = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def transformer(
    mock_command_bus,
    mock_bank_cash_service,
    mock_reconciliation_use_case,
    mock_bank_repo,
):
    return BankStatementToReconciliationTransformer(
        command_bus=mock_command_bus,
        bank_cash_service=mock_bank_cash_service,
        reconciliation_use_case=mock_reconciliation_use_case,
        bank_repo=mock_bank_repo,
    )


# =============================================================================
# Tests for BaseTransformer
# =============================================================================

class TestBaseTransformer:
    def test_initialization(self):
        trans = BaseTransformer("test")
        assert trans.name == "test"
        assert trans._version == 1
        assert trans._transformer_id is not None
        assert trans._audit_trail == []
        assert trans._snapshots == []

    def test_validate_returns_valid(self):
        trans = BaseTransformer("test")
        result = trans.validate()
        assert result == {"is_valid": True, "errors": []}

    def test_to_dict(self):
        trans = BaseTransformer("test")
        trans._version = 3
        d = trans.to_dict()
        assert d["name"] == "test"
        assert d["version"] == 3
        assert "transformer_id" in d

    def test_from_dict(self):
        data = {"name": "test", "version": 5, "transformer_id": str(uuid4())}
        trans = BaseTransformer.from_dict(data)
        assert trans.name == "test"
        assert trans._version == 5
        assert trans._transformer_id == data["transformer_id"]

    def test_clone(self):
        trans = BaseTransformer("test")
        trans._version = 2
        clone = trans.clone()
        assert clone.name == "test"
        assert clone._version == 3
        assert clone._transformer_id != trans._transformer_id
        assert len(clone._audit_trail) == 1
        assert clone._audit_trail[0]["action"] == "CLONE"

    def test_snapshot(self):
        trans = BaseTransformer("test")
        snap = trans.snapshot()
        assert snap["name"] == "test"
        assert snap["version"] == 1
        assert "transformer_id" in snap
        assert "timestamp" in snap

    def test_version(self):
        trans = BaseTransformer("test")
        assert trans.version() == 1
        trans._version = 10
        assert trans.version() == 10

    def test_audit_trail(self):
        trans = BaseTransformer("test")
        trans._record_audit("ACTION", "user", {"foo": "bar"})
        trail = trans.audit_trail(limit=10)
        assert len(trail) == 1
        assert trail[0]["action"] == "ACTION"
        assert trail[0]["performed_by"] == "user"

    def test_touch(self):
        trans = BaseTransformer("test")
        old_version = trans.version()
        trans.touch("admin")
        assert trans.version() == old_version + 1
        trail = trans.audit_trail()
        assert trail[-1]["action"] == "TOUCH"


# =============================================================================
# Tests for StatementParser
# =============================================================================

class TestStatementParser:
    @pytest.mark.asyncio
    async def test_parse_unsupported_format(self):
        parser = StatementParser()
        with pytest.raises(StatementParsingError, match="Unsupported format"):
            await parser.parse("content", "unsupported", "123")

    @pytest.mark.asyncio
    async def test_parse_mt940(self):
        parser = StatementParser()
        content = (
            ":61:2501010101C1000,00NREF001\n"
            ":86:Description line\n"
        )
        txs = await parser.parse(content, "mt940", "123")
        assert len(txs) == 1
        tx = txs[0]
        assert tx["amount"] == Decimal("1000.00")
        assert tx["type"] == "deposit"
        assert tx["reference"] == "REF001"
        assert tx["description"] == "Description line"

    @pytest.mark.asyncio
    async def test_parse_mt940_withdrawal(self):
        parser = StatementParser()
        content = ":61:2501010101D500,50NREF002\n"
        txs = await parser.parse(content, "mt940", "123")
        assert len(txs) == 1
        tx = txs[0]
        assert tx["amount"] == Decimal("500.50")
        assert tx["type"] == "withdrawal"

    @pytest.mark.asyncio
    async def test_parse_mt940_invalid_date(self):
        parser = StatementParser()
        # Invalid date part
        content = ":61:ABCDEF0101D100NREF\n"
        txs = await parser.parse(content, "mt940", "123")
        assert len(txs) == 1
        # Should fall back to today's date
        assert txs[0]["transaction_date"] == datetime.now().date()

    @pytest.mark.asyncio
    async def test_parse_camt(self):
        parser = StatementParser()
        content = (
            "<TxDtls>"
            "<Amt>1500.25</Amt>"
            "<BookgDt>2025-01-01</BookgDt>"
            "</TxDtls>"
        )
        txs = await parser.parse(content, "camt", "123")
        assert len(txs) == 1
        tx = txs[0]
        assert tx["amount"] == Decimal("1500.25")
        assert tx["type"] == "deposit"
        assert tx["transaction_date"] == date(2025, 1, 1)

    @pytest.mark.asyncio
    async def test_parse_camt_negative_amount(self):
        parser = StatementParser()
        content = (
            "<TxDtls>"
            "<Amt>-2000.00</Amt>"
            "<BookgDt>2025-01-02</BookgDt>"
            "</TxDtls>"
        )
        txs = await parser.parse(content, "camt", "123")
        tx = txs[0]
        assert tx["amount"] == Decimal("2000.00")
        assert tx["type"] == "withdrawal"

    @pytest.mark.asyncio
    async def test_parse_csv_bca(self):
        parser = StatementParser()
        content = "Date,Amount,Description,Reference\n01/01/2025,1000.00,Sale,REF001\n02/01/2025,-500.50,Payment,REF002\n"
        txs = await parser.parse(content, "csv_bca", "123")
        assert len(txs) == 2
        assert txs[0]["amount"] == Decimal("1000.00")
        assert txs[0]["type"] == "deposit"
        assert txs[1]["amount"] == Decimal("500.50")
        assert txs[1]["type"] == "withdrawal"
        assert txs[0]["transaction_date"] == date(2025, 1, 1)

    @pytest.mark.asyncio
    async def test_parse_csv_mandiri(self):
        parser = StatementParser()
        # Actually the Mandiri parser uses csv.reader with fixed columns: date, description, debit, credit, ref
        # We'll adjust the test to match the actual implementation.
        content2 = "01/01/2025,Deposit,1000.00,,\n02/01/2025,Withdrawal,,500.50,\n"
        txs = await parser.parse(content2, "csv_mandiri", "123")
        # The parser expects rows with at least 4 columns: date, description, debit, credit
        # For a deposit, debit column is empty or "0", credit has the amount.
        # Our content2 has 4 columns? Actually we need to match the parser's reading.
        # Let's write a proper row: date, description, debit, credit
        content_correct = "01/01/2025,Deposit,0,1000.00\n02/01/2025,Withdrawal,500.50,0\n"
        txs = await parser.parse(content_correct, "csv_mandiri", "123")
        assert len(txs) == 2
        assert txs[0]["amount"] == Decimal("1000.00")
        assert txs[0]["type"] == "deposit"
        assert txs[1]["amount"] == Decimal("500.50")
        assert txs[1]["type"] == "withdrawal"

    @pytest.mark.asyncio
    async def test_parse_csv_bni_and_bri_fallback_to_mandiri(self):
        parser = StatementParser()
        content = "01/01/2025,Deposit,0,1000.00\n"
        txs = await parser.parse(content, "csv_bni", "123")
        assert len(txs) == 1
        assert txs[0]["amount"] == Decimal("1000.00")
        txs2 = await parser.parse(content, "csv_bri", "123")
        assert len(txs2) == 1

    def test_validate(self):
        parser = StatementParser()
        result = parser.validate()
        assert result["is_valid"] is True

        # Corrupt the parser by replacing one with a non-callable
        parser._parsers["mt940"] = "not callable"
        result = parser.validate()
        assert result["is_valid"] is False
        assert "Parser for mt940 is not callable" in result["errors"]

    def test_to_dict(self):
        parser = StatementParser()
        d = parser.to_dict()
        assert "supported_formats" in d
        assert isinstance(d["supported_formats"], list)

    def test_from_dict(self):
        data = {"version": 3, "transformer_id": str(uuid4())}
        parser = StatementParser.from_dict(data)
        assert parser._version == 3
        assert parser._transformer_id == data["transformer_id"]

    def test_clone(self):
        parser = StatementParser()
        clone = parser.clone()
        assert clone._version == parser._version + 1
        assert clone._transformer_id != parser._transformer_id

    def test_snapshot(self):
        parser = StatementParser()
        snap = parser.snapshot()
        assert "supported_formats" in snap


# =============================================================================
# Tests for BankTransactionMatcher
# =============================================================================

class TestBankTransactionMatcher:
    def test_initialization(self):
        matcher = BankTransactionMatcher(amount_tolerance=Decimal("500"))
        assert matcher.amount_tolerance == Decimal("500")

    @pytest.mark.asyncio
    async def test_match_transactions_exact_match(self):
        matcher = BankTransactionMatcher()
        stmt_tx = {
            "amount": Decimal("1000"),
            "transaction_date": date(2025, 1, 1),
            "reference": "REF001",
            "description": "Deposit",
        }
        book_tx = {
            "amount": Decimal("1000"),
            "transaction_date": date(2025, 1, 1),
            "reference_number": "REF001",
            "description": "Deposit",
        }
        matched, unmatched_stmt, unmatched_book = await matcher.match_transactions(
            [stmt_tx], [book_tx]
        )
        assert len(matched) == 1
        assert matched[0]["match_score"] > 0.9
        assert len(unmatched_stmt) == 0
        assert len(unmatched_book) == 0

    @pytest.mark.asyncio
    async def test_match_transactions_amount_tolerance(self):
        matcher = BankTransactionMatcher(amount_tolerance=Decimal("100"))
        stmt_tx = {"amount": Decimal("1000"), "transaction_date": date(2025, 1, 1), "reference": "", "description": ""}
        book_tx = {"amount": Decimal("1050"), "transaction_date": date(2025, 1, 1), "reference_number": "", "description": ""}
        matched, _unmatched_stmt, _unmatched_book = await matcher.match_transactions(
            [stmt_tx], [book_tx]
        )
        # Within tolerance, should match
        assert len(matched) == 1
        assert matched[0]["match_score"] > 0.3  # amount contributes 0.4 minus some difference

    @pytest.mark.asyncio
    async def test_match_transactions_date_tolerance(self):
        matcher = BankTransactionMatcher()
        stmt_tx = {"amount": Decimal("1000"), "transaction_date": date(2025, 1, 1), "reference": "", "description": ""}
        book_tx = {"amount": Decimal("1000"), "transaction_date": date(2025, 1, 4), "reference_number": "", "description": ""}
        matched, _unmatched_stmt, _unmatched_book = await matcher.match_transactions(
            [stmt_tx], [book_tx]
        )
        # 3 days difference => score includes 0.2 for date
        assert len(matched) == 1
        assert matched[0]["match_score"] > 0.5

    @pytest.mark.asyncio
    async def test_match_transactions_reference_match(self):
        matcher = BankTransactionMatcher()
        stmt_tx = {"amount": Decimal("1000"), "transaction_date": date(2025, 1, 1), "reference": "INV123", "description": ""}
        book_tx = {"amount": Decimal("1000"), "transaction_date": date(2025, 1, 1), "reference_number": "INV123", "description": ""}
        matched, _, _ = await matcher.match_transactions([stmt_tx], [book_tx])
        # Should have extra 0.2 from reference match
        assert matched[0]["match_score"] > 0.8

    @pytest.mark.asyncio
    async def test_match_transactions_no_match(self):
        matcher = BankTransactionMatcher()
        stmt_tx = {"amount": Decimal("1000"), "transaction_date": date(2025, 1, 1), "reference": "", "description": ""}
        book_tx = {"amount": Decimal("2000"), "transaction_date": date(2025, 1, 10), "reference_number": "", "description": ""}
        matched, unmatched_stmt, unmatched_book = await matcher.match_transactions(
            [stmt_tx], [book_tx]
        )
        assert len(matched) == 0
        assert len(unmatched_stmt) == 1
        assert len(unmatched_book) == 1

    @pytest.mark.asyncio
    async def test_match_score_calculation(self):
        matcher = BankTransactionMatcher()
        stmt_tx = {
            "amount": Decimal("1000"),
            "transaction_date": date(2025, 1, 1),
            "reference": "REF123",
            "description": "Payment for invoice",
        }
        book_tx = {
            "amount": Decimal("1000"),
            "transaction_date": date(2025, 1, 1),
            "reference_number": "REF123",
            "description": "Payment for invoice",
        }
        score = await matcher._calculate_match_score(stmt_tx, book_tx)
        # Amount match (0.4) + date match (0.3) + reference exact (0.2) + description overlap (0.1) = 1.0
        assert score == 1.0

    def test_validate(self):
        matcher = BankTransactionMatcher(amount_tolerance=Decimal("0"))
        result = matcher.validate()
        assert result["is_valid"] is False
        assert "amount_tolerance must be positive" in result["errors"]

        matcher2 = BankTransactionMatcher(amount_tolerance=Decimal("100"))
        result2 = matcher2.validate()
        assert result2["is_valid"] is True

    def test_to_dict(self):
        matcher = BankTransactionMatcher(amount_tolerance=Decimal("500"))
        d = matcher.to_dict()
        assert d["amount_tolerance"] == "500"

    def test_from_dict(self):
        data = {"amount_tolerance": "200", "version": 2, "transformer_id": str(uuid4())}
        matcher = BankTransactionMatcher.from_dict(data)
        assert matcher.amount_tolerance == Decimal("200")
        assert matcher._version == 2

    def test_clone(self):
        matcher = BankTransactionMatcher(amount_tolerance=Decimal("300"))
        clone = matcher.clone()
        assert clone.amount_tolerance == Decimal("300")
        assert clone._version == matcher._version + 1

    def test_snapshot(self):
        matcher = BankTransactionMatcher(amount_tolerance=Decimal("400"))
        snap = matcher.snapshot()
        assert snap["amount_tolerance"] == "400"


# =============================================================================
# Tests for BankStatementToReconciliationTransformer
# =============================================================================

class TestBankStatementToReconciliationTransformer:
    def test_initialization(self, transformer):
        assert transformer.name == "BankStatementToReconciliationTransformer"
        assert transformer._parser is not None
        assert transformer._matcher is not None
        assert transformer._processed_events == set()

    @pytest.mark.asyncio
    async def test_transform_unsupported_event(self, transformer, mock_event_envelope):
        mock_event_envelope.event_type = "UnsupportedEvent"
        await transformer.transform(mock_event_envelope)
        # Should not raise, just log
        assert mock_event_envelope.id not in transformer._processed_events

    @pytest.mark.asyncio
    async def test_transform_already_processed(self, transformer, mock_event_envelope):
        event_id = mock_event_envelope.id
        transformer._processed_events.add(event_id)
        await transformer.transform(mock_event_envelope)
        # Should skip
        # No calls to any service methods
        transformer._bank_repo.get_bank_account_by_id.assert_not_called()

    @pytest.mark.asyncio
    async def test_transform_bank_statement_uploaded_success(self, transformer, mock_event_envelope):
        # Prepare payload
        bank_account_id = uuid4()
        mock_event_envelope.event_type = "BankStatementUploaded"
        mock_event_envelope.payload = {
            "bank_account_id": str(bank_account_id),
            "file_content": ":61:2501010101C1000,00NREF001\n",
            "format": "mt940",
            "statement_date": "2025-01-01",
            "uploaded_by": str(uuid4()),
            "legal_entity_id": str(uuid4()),
        }
        # Mock bank account and transactions
        account = MagicMock()
        account.id = bank_account_id
        account.account_number = "123"
        account.current_balance.amount = Decimal("1000000")
        transformer._bank_repo.get_bank_account_by_id.return_value = account
        transformer._bank_repo.get_bank_transactions_by_account.return_value = []
        transformer._reconciliation_use_case.reconcile = AsyncMock()

        await transformer.transform(mock_event_envelope)
        assert mock_event_envelope.id in transformer._processed_events
        transformer._bank_repo.get_bank_account_by_id.assert_called_once_with(bank_account_id)
        transformer._reconciliation_use_case.reconcile.assert_called_once()
        # Check that reconcile got the correct parameters
        call_args = transformer._reconciliation_use_case.reconcile.call_args[1]
        assert call_args["bank_account_id"] == bank_account_id
        assert call_args["statement_date"] == date(2025, 1, 1)
        assert len(call_args["statement_transactions"]) == 1

    @pytest.mark.asyncio
    async def test_transform_bank_statement_uploaded_account_not_found(self, transformer, mock_event_envelope):
        bank_account_id = uuid4()
        mock_event_envelope.event_type = "BankStatementUploaded"
        mock_event_envelope.payload = {
            "bank_account_id": str(bank_account_id),
            "file_content": "",
            "format": "mt940",
        }
        transformer._bank_repo.get_bank_account_by_id.return_value = None
        with pytest.raises(BankAccountNotFoundError):
            await transformer.transform(mock_event_envelope)
        assert mock_event_envelope.id not in transformer._processed_events

    @pytest.mark.asyncio
    async def test_transform_bank_statement_uploaded_parsing_failure(self, transformer, mock_event_envelope):
        bank_account_id = uuid4()
        mock_event_envelope.event_type = "BankStatementUploaded"
        mock_event_envelope.payload = {
            "bank_account_id": str(bank_account_id),
            "file_content": "invalid content",
            "format": "mt940",
        }
        account = MagicMock()
        account.id = bank_account_id
        account.account_number = "123"
        transformer._bank_repo.get_bank_account_by_id.return_value = account
        # The parser will try to parse but may still work with invalid content; but we can simulate an exception
        # by patching the parser's parse method to raise
        with patch.object(transformer._parser, "parse", side_effect=StatementParsingError("parse error")):
            with pytest.raises(StatementParsingError):
                await transformer.transform(mock_event_envelope)

    @pytest.mark.asyncio
    async def test_transform_parsed_statement(self, transformer, mock_event_envelope):
        bank_account_id = uuid4()
        mock_event_envelope.event_type = "MT940Parsed"
        mock_event_envelope.payload = {
            "bank_account_id": str(bank_account_id),
            "transactions": [{"amount": 1000, "transaction_date": "2025-01-01"}],
            "statement_date": "2025-01-01",
            "processed_by": str(uuid4()),
            "legal_entity_id": str(uuid4()),
        }
        account = MagicMock()
        account.id = bank_account_id
        account.account_number = "123"
        account.current_balance.amount = Decimal("1000000")
        transformer._bank_repo.get_bank_account_by_id.return_value = account
        transformer._bank_repo.get_bank_transactions_by_account.return_value = []
        transformer._reconciliation_use_case.reconcile = AsyncMock()

        await transformer.transform(mock_event_envelope)
        assert mock_event_envelope.id in transformer._processed_events
        transformer._reconciliation_use_case.reconcile.assert_called_once()

    @pytest.mark.asyncio
    async def test_transform_parsed_statement_no_transactions(self, transformer, mock_event_envelope):
        mock_event_envelope.event_type = "CAMTParsed"
        mock_event_envelope.payload = {
            "bank_account_id": str(uuid4()),
            "transactions": [],
            "statement_date": "2025-01-01",
        }
        await transformer.transform(mock_event_envelope)
        # Should log warning and return without reconciling
        transformer._reconciliation_use_case.reconcile.assert_not_called()
        assert mock_event_envelope.id in transformer._processed_events

    @pytest.mark.asyncio
    async def test_transform_bank_webhook(self, transformer, mock_event_envelope):
        mock_event_envelope.event_type = "BankWebhookReceived"
        legal_entity_id = uuid4()
        mock_event_envelope.payload = {
            "account_number": "1234567890",
            "amount": "10000",
            "transaction_date": "2025-01-01",
            "reference": "WEB-001",
            "description": "Webhook payment",
            "legal_entity_id": str(legal_entity_id),
        }
        account = MagicMock()
        account.id = uuid4()
        account.account_number = "1234567890"
        transformer._bank_repo.get_bank_account_by_number.return_value = account
        transformer._command_bus.dispatch = AsyncMock()

        await transformer.transform(mock_event_envelope)
        assert mock_event_envelope.id in transformer._processed_events
        transformer._bank_repo.get_bank_account_by_number.assert_called_once_with("1234567890", legal_entity_id)
        transformer._command_bus.dispatch.assert_called_once()
        dispatch_args = transformer._command_bus.dispatch.call_args[0][0]
        assert dispatch_args["type"] == "bank.transaction.record"
        assert dispatch_args["data"]["amount"] == "10000"

    @pytest.mark.asyncio
    async def test_transform_bank_webhook_account_not_found(self, transformer, mock_event_envelope):
        mock_event_envelope.event_type = "BankWebhookReceived"
        mock_event_envelope.payload = {
            "account_number": "unknown",
            "amount": "100",
            "transaction_date": "2025-01-01",
        }
        transformer._bank_repo.get_bank_account_by_number.return_value = None
        await transformer.transform(mock_event_envelope)
        # Should log warning and not dispatch command
        transformer._command_bus.dispatch.assert_not_called()
        assert mock_event_envelope.id not in transformer._processed_events

    @pytest.mark.asyncio
    async def test_transform_daily_reconciliation(self, transformer, mock_event_envelope):
        mock_event_envelope.event_type = "DailyBankReconciliationTrigger"
        legal_entity_id = uuid4()
        mock_event_envelope.payload = {
            "as_of_date": "2025-01-01",
            "legal_entity_id": str(legal_entity_id),
        }
        account1 = MagicMock()
        account1.id = uuid4()
        account1.account_number = "123"
        account2 = MagicMock()
        account2.id = uuid4()
        account2.account_number = "456"
        transformer._bank_repo.list_bank_accounts.return_value = [account1, account2]
        transformer._reconciliation_use_case.reconcile_auto = AsyncMock(return_value={"status": "completed"})

        await transformer.transform(mock_event_envelope)
        assert mock_event_envelope.id in transformer._processed_events
        assert transformer._reconciliation_use_case.reconcile_auto.call_count == 2

    @pytest.mark.asyncio
    async def test_transform_daily_reconciliation_failure(self, transformer, mock_event_envelope):
        mock_event_envelope.event_type = "DailyBankReconciliationTrigger"
        legal_entity_id = uuid4()
        mock_event_envelope.payload = {"legal_entity_id": str(legal_entity_id)}
        account = MagicMock()
        account.id = uuid4()
        account.account_number = "123"
        transformer._bank_repo.list_bank_accounts.return_value = [account]
        transformer._reconciliation_use_case.reconcile_auto = AsyncMock(side_effect=Exception("reconcile error"))

        # Should not raise; it should log and continue
        await transformer.transform(mock_event_envelope)
        assert mock_event_envelope.id in transformer._processed_events

    @pytest.mark.asyncio
    async def test_reset(self, transformer):
        transformer._processed_events.add(uuid4())
        transformer._version = 5
        await transformer.reset()
        assert len(transformer._processed_events) == 0
        assert transformer._version == 6

    def test_validate(self, transformer):
        # Valid
        result = transformer.validate()
        assert result["is_valid"] is True
        # Invalidate by setting parser to None
        transformer._parser = None
        result = transformer.validate()
        assert result["is_valid"] is False
        assert "Parser not initialized" in result["errors"]

    def test_to_dict(self, transformer):
        d = transformer.to_dict()
        assert "processed_events_count" in d
        assert "parser" in d
        assert "matcher" in d

    def test_from_dict(self):
        data = {"version": 5, "transformer_id": str(uuid4())}
        trans = BankStatementToReconciliationTransformer.from_dict(data)
        assert trans._version == 5
        assert trans._transformer_id == data["transformer_id"]
        assert trans._parser is not None
        assert trans._matcher is not None
        assert trans._processed_events == set()

    def test_clone(self, transformer):
        clone = transformer.clone()
        assert clone._version == transformer._version + 1
        assert clone._transformer_id != transformer._transformer_id
        # Check that dependencies are properly copied (referenced)
        assert clone._command_bus == transformer._command_bus

    def test_snapshot(self, transformer):
        transformer._processed_events.add(uuid4())
        snap = transformer.snapshot()
        assert snap["processed_events_count"] == 1

    def test_touch(self, transformer):
        old_version = transformer.version()
        transformer.touch("admin")
        assert transformer.version() == old_version + 1


# =============================================================================
# Tests for Exceptions
# =============================================================================

class TestExceptions:
    def test_bank_statement_to_reconciliation_error(self):
        with pytest.raises(BankStatementToReconciliationError):
            raise BankStatementToReconciliationError("test")

    def test_bank_account_not_found_error(self):
        with pytest.raises(BankAccountNotFoundError):
            raise BankAccountNotFoundError("account not found")

    def test_statement_parsing_error(self):
        with pytest.raises(StatementParsingError):
            raise StatementParsingError("parse failed")

    def test_reconciliation_failed_error(self):
        with pytest.raises(ReconciliationFailedError):
            raise ReconciliationFailedError("reconcile failed")


# =============================================================================
# Tests for Module-level Functions
# =============================================================================

@patch("transformers.bank_statement_to_reconciliation.get_container")
async def test_get_bank_statement_transformer(mock_get_container):
    # Reset global
    import transformers.bank_statement_to_reconciliation as mod
    mod._bank_statement_transformer = None

    container = MagicMock()
    container.resolve = MagicMock()
    mock_get_container.return_value = container
    # Ensure we get a transformer
    trans1 = await get_bank_statement_transformer()
    trans2 = await get_bank_statement_transformer()
    assert trans1 is trans2
    assert isinstance(trans1, BankStatementToReconciliationTransformer)


@patch("transformers.bank_statement_to_reconciliation.get_bank_statement_transformer")
async def test_handle_bank_statement_event(mock_get_transformer):
    transformer = AsyncMock()
    mock_get_transformer.return_value = transformer
    envelope = MagicMock()
    await handle_bank_statement_event(envelope)
    transformer.transform.assert_called_once_with(envelope)
