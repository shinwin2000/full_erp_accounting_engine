#!/usr/bin/env python3
"""
tests/application/use_cases/test_year_end_closing.py
Test untuk application/use_cases/year_end_closing.py
"""

from datetime import date
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from application.use_cases.year_end_closing import (
    YearEndClosingCommand,
    YearEndClosingResult,
    YearEndClosingUseCase,
    audit,
    year_end_closing_handler,
)


# ============================================================================
# Test YearEndClosingCommand
# ============================================================================

class TestYearEndClosingCommand:
    def test_construction(self):
        command = YearEndClosingCommand(
            legal_entity_id=uuid4(),
            closing_year=2026,
            closing_date=date.today(),
            reverse_opening_balances=True,
            adjust_tax=True,
            impairment_test=True,
            revaluation_assets=True,
            generate_financial_statements=True,
            dry_run=False,
            user_id=uuid4(),
            correlation_id="corr-123"
        )
        assert isinstance(command, YearEndClosingCommand)

    def test_to_dict_returns_dict_with_expected_fields(self):
        legal_entity_id = uuid4()
        user_id = uuid4()
        closing_date = date.today()
        command = YearEndClosingCommand(
            legal_entity_id=legal_entity_id,
            closing_year=2026,
            closing_date=closing_date,
            reverse_opening_balances=True,
            adjust_tax=True,
            impairment_test=False,
            revaluation_assets=True,
            generate_financial_statements=True,
            dry_run=False,
            user_id=user_id,
            correlation_id="corr-123"
        )
        result = command.to_dict()
        assert isinstance(result, dict)
        assert result["legal_entity_id"] == str(legal_entity_id)
        assert result["closing_year"] == 2026
        assert result["closing_date"] == closing_date.isoformat()
        assert result["reverse_opening_balances"] is True
        assert result["adjust_tax"] is True
        assert result["impairment_test"] is False
        assert result["revaluation_assets"] is True
        assert result["generate_financial_statements"] is True
        assert result["dry_run"] is False
        assert result["user_id"] == str(user_id)
        assert result["correlation_id"] == "corr-123"


# ============================================================================
# Test YearEndClosingResult
# ============================================================================

class TestYearEndClosingResult:
    def test_construction(self):
        result = YearEndClosingResult(
            periods_closed=["2026-01", "2026-02"],
            closing_journal_ids=[uuid4(), uuid4()],
            tax_adjustment_journal_id=uuid4(),
            reversal_journal_ids=[uuid4()],
            impairment_journal_ids=[uuid4()],
            financial_statement_paths=["/path/to/statement1.pdf"],
            message="Year-end closing completed successfully"
        )
        assert isinstance(result, YearEndClosingResult)
        assert len(result.periods_closed) == 2
        assert len(result.closing_journal_ids) == 2
        assert result.message == "Year-end closing completed successfully"


# ============================================================================
# Test YearEndClosingUseCase
# ============================================================================

class TestYearEndClosingUseCase:
    def test_construction(self):
        use_case = YearEndClosingUseCase(
            period_close_uc=MagicMock(),
            post_closing_uc=MagicMock(),
            fiscal_period_service=MagicMock(),
            tax_service=MagicMock(),
            fixed_asset_service=MagicMock(),
            journal_service=MagicMock(),
            sealed_gate=MagicMock()
        )
        assert isinstance(use_case, YearEndClosingUseCase)

    @pytest.mark.asyncio
    async def test_execute_calls_services_and_returns_result(self):
        # Setup mocks
        mock_period_close = AsyncMock()
        mock_period_close.close_period = AsyncMock(return_value={"period_id": "P001"})
        
        mock_post_closing = AsyncMock()
        mock_post_closing.post_closing_journal = AsyncMock(return_value={"journal_id": "JRN-001"})
        
        mock_tax = AsyncMock()
        mock_tax.adjust_tax = AsyncMock(return_value={"adjustment_id": "TAX-001"})
        
        mock_asset = AsyncMock()
        mock_asset.perform_impairment_test = AsyncMock(return_value={"impairment_id": "IMP-001"})
        mock_asset.revalue_assets = AsyncMock(return_value={"revaluation_id": "REV-001"})
        
        mock_fiscal = AsyncMock()
        mock_fiscal.create_closing_period = AsyncMock(return_value={"period": "2026-01"})
        
        mock_journal = AsyncMock()
        mock_journal.post_journal = AsyncMock(return_value={"journal_id": "JRN-002"})
        
        mock_gate = MagicMock()
        mock_gate.check = AsyncMock(return_value=True)
        
        use_case = YearEndClosingUseCase(
            period_close_uc=mock_period_close,
            post_closing_uc=mock_post_closing,
            fiscal_period_service=mock_fiscal,
            tax_service=mock_tax,
            fixed_asset_service=mock_asset,
            journal_service=mock_journal,
            sealed_gate=mock_gate
        )
        
        command = MagicMock()
        command.to_dict.return_value = {
            "legal_entity_id": str(uuid4()),
            "closing_year": 2026,
            "closing_date": date.today().isoformat(),
            "reverse_opening_balances": True,
            "adjust_tax": True,
            "impairment_test": True,
            "revaluation_assets": True,
            "generate_financial_statements": True,
            "dry_run": False
        }
        
        result = await use_case.execute(command)
        assert isinstance(result, YearEndClosingResult)
        # Verify mocks were called
        mock_fiscal.create_closing_period.assert_called_once()
        mock_period_close.close_period.assert_called_once()
        mock_tax.adjust_tax.assert_called_once()
        mock_asset.perform_impairment_test.assert_called_once()
        mock_asset.revalue_assets.assert_called_once()
        mock_gate.check.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_dry_run_does_not_call_services(self):
        mock_period_close = AsyncMock()
        mock_tax = AsyncMock()
        mock_asset = AsyncMock()
        mock_fiscal = AsyncMock()
        mock_journal = AsyncMock()
        mock_gate = MagicMock()
        
        use_case = YearEndClosingUseCase(
            period_close_uc=mock_period_close,
            post_closing_uc=AsyncMock(),
            fiscal_period_service=mock_fiscal,
            tax_service=mock_tax,
            fixed_asset_service=mock_asset,
            journal_service=mock_journal,
            sealed_gate=mock_gate
        )
        
        command = MagicMock()
        command.to_dict.return_value = {
            "legal_entity_id": str(uuid4()),
            "closing_year": 2026,
            "closing_date": date.today().isoformat(),
            "dry_run": True
        }
        
        result = await use_case.execute(command)
        assert isinstance(result, YearEndClosingResult)
        # In dry_run mode, services should NOT be called (or minimal)
        mock_fiscal.create_closing_period.assert_not_called()
        mock_period_close.close_period.assert_not_called()
        mock_tax.adjust_tax.assert_not_called()
        mock_asset.perform_impairment_test.assert_not_called()
        mock_asset.revalue_assets.assert_not_called()

    def test_get_stats_returns_dict(self):
        use_case = YearEndClosingUseCase(
            period_close_uc=MagicMock(),
            post_closing_uc=MagicMock(),
            fiscal_period_service=MagicMock(),
            tax_service=MagicMock(),
            fixed_asset_service=MagicMock(),
            journal_service=MagicMock(),
            sealed_gate=MagicMock()
        )
        stats = use_case.get_stats()
        assert isinstance(stats, dict)
        # At minimum, should have some keys
        assert "total_executions" in stats or "executed_count" in stats

    def test_get_audit_trail_returns_list(self):
        use_case = YearEndClosingUseCase(
            period_close_uc=MagicMock(),
            post_closing_uc=MagicMock(),
            fiscal_period_service=MagicMock(),
            tax_service=MagicMock(),
            fixed_asset_service=MagicMock(),
            journal_service=MagicMock(),
            sealed_gate=MagicMock()
        )
        trail = use_case.get_audit_trail()
        assert isinstance(trail, list)


# ============================================================================
# Test Module-Level Functions
# ============================================================================

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


@pytest.mark.asyncio
async def test_year_end_closing_handler_calls_use_case_and_returns_result():
    mock_use_case = AsyncMock()
    mock_use_case.execute = AsyncMock(return_value=YearEndClosingResult(
        periods_closed=["2026-01"],
        closing_journal_ids=[],
        tax_adjustment_journal_id=None,
        reversal_journal_ids=[],
        impairment_journal_ids=[],
        financial_statement_paths=[],
        message="Success"
    ))
    command = MagicMock()
    result = await year_end_closing_handler(command=command, use_case=mock_use_case)
    assert isinstance(result, YearEndClosingResult)
    assert result.message == "Success"
    mock_use_case.execute.assert_called_once_with(command)