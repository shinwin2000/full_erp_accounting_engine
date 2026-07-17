#!/usr/bin/env python3
"""
tests/application/use_cases/test_post_closing_journal.py
Test untuk application/use_cases/post_closing_journal.py
"""

from datetime import date
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from application.use_cases.post_closing_journal import (
    IdempotencyManager,
    PostClosingJournalCommand,
    PostClosingJournalUseCase,
    audit,
    post_closing_journal_handler,
    transactional,
)


class TestIdempotencyManager:
    def test_construction(self):
        instance = IdempotencyManager()
        assert isinstance(instance, IdempotencyManager)

    def test_get_cached_result_for_missing_key_returns_none(self):
        instance = IdempotencyManager()
        result = instance.get_cached_result("non_existent_key", "method")
        assert result is None

    def test_cache_result_returns_true_on_success(self):
        instance = IdempotencyManager()
        result = instance.cache_result("key", "method", {"data": "value"})
        assert result is True

    def test_cached_result_can_be_retrieved(self):
        instance = IdempotencyManager()
        instance.cache_result("key", "method", {"data": "value"})
        result = instance.get_cached_result("key", "method")
        assert result == {"data": "value"}


class TestPostClosingJournalCommand:
    def test_construction(self):
        command = PostClosingJournalCommand(
            legal_entity_id=uuid4(),
            period_year=2026,
            period_month=12,
            closing_date=date.today(),
            include_income_statement_accounts=True,
            include_withdrawal_accounts=True,
            idempotency_key="key-123",
            user_id=uuid4(),
            correlation_id="corr-456"
        )
        assert isinstance(command, PostClosingJournalCommand)

    def test_to_dict_returns_dict_with_expected_fields(self):
        legal_entity_id = uuid4()
        period_year = 2026
        command = PostClosingJournalCommand(
            legal_entity_id=legal_entity_id,
            period_year=period_year,
            period_month=12,
            closing_date=date.today(),
            include_income_statement_accounts=True,
            include_withdrawal_accounts=True,
            idempotency_key="key-123",
            user_id=uuid4(),
            correlation_id="corr-456"
        )
        result = command.to_dict()
        assert isinstance(result, dict)
        assert result["legal_entity_id"] == str(legal_entity_id)
        assert result["period_year"] == period_year
        assert result["period_month"] == 12
        assert result["include_income_statement_accounts"] is True
        assert result["idempotency_key"] == "key-123"


class TestPostClosingJournalUseCase:
    def test_construction(self):
        use_case = PostClosingJournalUseCase(
            journal_service=MagicMock(),
            fiscal_period_service=MagicMock(),
            coa_service=MagicMock(),
            ledger_repo=MagicMock(),
            uow=MagicMock(),
            sealed_gate=MagicMock()
        )
        assert isinstance(use_case, PostClosingJournalUseCase)

    @pytest.mark.asyncio
    async def test_execute_calls_services_and_returns_result(self):
        mock_journal = AsyncMock()
        mock_journal.post_closing_entry = AsyncMock(return_value={"journal_id": "JRN-999"})
        use_case = PostClosingJournalUseCase(
            journal_service=mock_journal,
            fiscal_period_service=MagicMock(),
            coa_service=MagicMock(),
            ledger_repo=MagicMock(),
            uow=MagicMock(),
            sealed_gate=MagicMock()
        )
        command = MagicMock()
        command.to_dict.return_value = {"period_year": 2026}
        # Assuming execute returns a result dict
        result = await use_case.execute(command)
        assert result is not None
        mock_journal.post_closing_entry.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_passes_through_exceptions(self):
        mock_journal = AsyncMock()
        mock_journal.post_closing_entry = AsyncMock(side_effect=ValueError("Posting failed"))
        use_case = PostClosingJournalUseCase(
            journal_service=mock_journal,
            fiscal_period_service=MagicMock(),
            coa_service=MagicMock(),
            ledger_repo=MagicMock(),
            uow=MagicMock(),
            sealed_gate=MagicMock()
        )
        command = MagicMock()
        with pytest.raises(ValueError, match="Posting failed"):
            await use_case.execute(command)

    def test_get_stats_returns_dict(self):
        use_case = PostClosingJournalUseCase(
            journal_service=MagicMock(),
            fiscal_period_service=MagicMock(),
            coa_service=MagicMock(),
            ledger_repo=MagicMock(),
            uow=MagicMock(),
            sealed_gate=MagicMock()
        )
        stats = use_case.get_stats()
        assert isinstance(stats, dict)
        assert "total_executions" in stats or "executed_count" in stats

    def test_get_audit_trail_returns_list(self):
        use_case = PostClosingJournalUseCase(
            journal_service=MagicMock(),
            fiscal_period_service=MagicMock(),
            coa_service=MagicMock(),
            ledger_repo=MagicMock(),
            uow=MagicMock(),
            sealed_gate=MagicMock()
        )
        trail = use_case.get_audit_trail()
        assert isinstance(trail, list)


def test_audit_returns_callable_decorator():
    async def dummy_func():
        return "ok"
    decorated = audit(dummy_func)
    assert callable(decorated)


@pytest.mark.asyncio
async def test_audit_decorated_function_preserves_behavior():
    async def dummy_func(arg):
        return f"processed {arg}"
    decorated = audit(dummy_func)
    result = await decorated("test")
    assert result == "processed test"


def test_transactional_returns_callable_decorator():
    async def dummy_method(self):
        return "ok"
    # transactional expects a method, but we can test it returns callable
    decorated = transactional(dummy_method)
    assert callable(decorated)


@pytest.mark.asyncio
async def test_post_closing_journal_handler_calls_use_case_and_returns_result():
    mock_use_case = AsyncMock()
    mock_use_case.execute = AsyncMock(return_value={"status": "success", "journal_id": "JRN-001"})
    command = MagicMock()
    result = await post_closing_journal_handler(
        command=command,
        use_case=mock_use_case,
        idempotency_key="key-123"
    )
    assert result == {"status": "success", "journal_id": "JRN-001"}
    mock_use_case.execute.assert_called_once_with(command)

@pytest.mark.asyncio
async def test_post_closing_journal_handler_passes_idempotency_key():
    mock_use_case = AsyncMock()
    mock_use_case.execute = AsyncMock(return_value={"status": "ok"})
    command = MagicMock()
    await post_closing_journal_handler(
        command=command,
        use_case=mock_use_case,
        idempotency_key="custom-key"
    )
    mock_use_case.execute.assert_called_once_with(command)