#!/usr/bin/env python3
"""
tests/application/use_cases/test_period_close.py
Test untuk application/use_cases/period_close.py
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from application.use_cases.period_close import (
    PeriodCloseCommand,
    PeriodCloseResult,
    PeriodCloseUseCase,
    audit,
    period_close_handler,
)


# ============================================================================
# Test PeriodCloseCommand
# ============================================================================

class TestPeriodCloseCommand:
    def test_construction(self):
        command = PeriodCloseCommand(
            legal_entity_id=uuid4(),
            period_year=2026,
            period_month=5,
            close_date=datetime.now(UTC),
            run_closing_journals=True,
            skip_validation_checks=False,
            force_close=False,
            user_id=uuid4(),
            correlation_id="corr-123"
        )
        assert isinstance(command, PeriodCloseCommand)

    def test_to_dict_returns_dict_with_expected_fields(self):
        legal_entity_id = uuid4()
        period_year = 2026
        period_month = 5
        command = PeriodCloseCommand(
            legal_entity_id=legal_entity_id,
            period_year=period_year,
            period_month=period_month,
            close_date=datetime.now(UTC),
            run_closing_journals=True,
            skip_validation_checks=False,
            force_close=False,
            user_id=uuid4(),
            correlation_id="corr-123"
        )
        result = command.to_dict()
        assert isinstance(result, dict)
        assert result["legal_entity_id"] == str(legal_entity_id)
        assert result["period_year"] == period_year
        assert result["period_month"] == period_month
        assert result["run_closing_journals"] is True
        assert result["skip_validation_checks"] is False
        assert result["force_close"] is False
        assert result["correlation_id"] == "corr-123"


# ============================================================================
# Test PeriodCloseResult
# ============================================================================

class TestPeriodCloseResult:
    def test_construction(self):
        result = PeriodCloseResult()
        assert isinstance(result, PeriodCloseResult)
        # Default attributes should be empty
        assert result.steps == []
        assert result.warnings == []
        assert result.errors == []
        assert result.is_success is False

    def test_add_step_appends_step_and_returns_self(self):
        result = PeriodCloseResult()
        returned = result.add_step("Validated balances")
        assert returned is result
        assert result.steps == ["Validated balances"]

    def test_add_warning_appends_warning_and_returns_self(self):
        result = PeriodCloseResult()
        returned = result.add_warning("Depreciation not run")
        assert returned is result
        assert result.warnings == ["Depreciation not run"]

    def test_add_error_appends_error_and_returns_self(self):
        result = PeriodCloseResult()
        returned = result.add_error("Missing journal entries")
        assert returned is result
        assert result.errors == ["Missing journal entries"]

    def test_to_dict_returns_dict_with_all_fields(self):
        result = PeriodCloseResult()
        result.add_step("Step 1")
        result.add_warning("Warning 1")
        result.add_error("Error 1")
        result.is_success = True
        d = result.to_dict()
        assert isinstance(d, dict)
        assert d["steps"] == ["Step 1"]
        assert d["warnings"] == ["Warning 1"]
        assert d["errors"] == ["Error 1"]
        assert d["is_success"] is True


# ============================================================================
# Test PeriodCloseUseCase
# ============================================================================

class TestPeriodCloseUseCase:
    def test_construction(self):
        use_case = PeriodCloseUseCase(
            fiscal_period_service=MagicMock(),
            journal_service=MagicMock(),
            bank_cash_service=MagicMock(),
            inventory_service=MagicMock(),
            sealed_gate=MagicMock()
        )
        assert isinstance(use_case, PeriodCloseUseCase)

    @pytest.mark.asyncio
    async def test_execute_calls_services_and_returns_result(self):
        mock_fiscal = AsyncMock()
        mock_fiscal.close_period = AsyncMock(return_value={"period_id": "P-2026-05"})
        use_case = PeriodCloseUseCase(
            fiscal_period_service=mock_fiscal,
            journal_service=AsyncMock(),
            bank_cash_service=AsyncMock(),
            inventory_service=AsyncMock(),
            sealed_gate=MagicMock()
        )
        command = MagicMock()
        command.to_dict.return_value = {"period_year": 2026, "period_month": 5}
        result = await use_case.execute(command)
        # Assuming execute returns a PeriodCloseResult
        assert isinstance(result, PeriodCloseResult)
        mock_fiscal.close_period.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_passes_through_exceptions(self):
        mock_fiscal = AsyncMock()
        mock_fiscal.close_period = AsyncMock(side_effect=ValueError("Period close failed"))
        use_case = PeriodCloseUseCase(
            fiscal_period_service=mock_fiscal,
            journal_service=AsyncMock(),
            bank_cash_service=AsyncMock(),
            inventory_service=AsyncMock(),
            sealed_gate=MagicMock()
        )
        command = MagicMock()
        with pytest.raises(ValueError, match="Period close failed"):
            await use_case.execute(command)

    def test_execute_simple_returns_result(self):
        # execute_simple is synchronous, returns PeriodCloseResult
        mock_fiscal = MagicMock()
        mock_fiscal.close_period = MagicMock(return_value={"period_id": "P-2026-05"})
        use_case = PeriodCloseUseCase(
            fiscal_period_service=mock_fiscal,
            journal_service=MagicMock(),
            bank_cash_service=MagicMock(),
            inventory_service=MagicMock(),
            sealed_gate=MagicMock()
        )
        period = MagicMock()
        period.id = uuid4()
        result = use_case.execute_simple(period=period, closed_by="admin")
        assert isinstance(result, PeriodCloseResult)
        mock_fiscal.close_period.assert_called_once_with(period.id, "admin")

    def test_get_stats_returns_dict(self):
        use_case = PeriodCloseUseCase(
            fiscal_period_service=MagicMock(),
            journal_service=MagicMock(),
            bank_cash_service=MagicMock(),
            inventory_service=MagicMock(),
            sealed_gate=MagicMock()
        )
        stats = use_case.get_stats()
        assert isinstance(stats, dict)
        # At minimum, should have some keys (even zero counts)
        assert "total_executions" in stats or "executed_count" in stats

    def test_get_audit_trail_returns_list(self):
        use_case = PeriodCloseUseCase(
            fiscal_period_service=MagicMock(),
            journal_service=MagicMock(),
            bank_cash_service=MagicMock(),
            inventory_service=MagicMock(),
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
async def test_period_close_handler_calls_use_case_and_returns_result():
    mock_use_case = AsyncMock()
    mock_use_case.execute = AsyncMock(return_value={"status": "success"})
    command = MagicMock()
    result = await period_close_handler(command=command, use_case=mock_use_case)
    assert result == {"status": "success"}
    mock_use_case.execute.assert_called_once_with(command)