#!/usr/bin/env python3
"""
tests/application/use_cases/test_fiscal_reconciliation.py
Test untuk application/use_cases/fiscal_reconciliation.py
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from application.use_cases.fiscal_reconciliation import (
    FiscalCorrection,
    FiscalReconciliationCommand,
    FiscalReconciliationResult,
    FiscalReconciliationUseCase,
    audit,
    fiscal_reconciliation_handler,
)

# ============================================================================
# Test FiscalReconciliationCommand
# ============================================================================

class TestFiscalReconciliationCommand:
    def test_construction(self):
        command = FiscalReconciliationCommand(
            legal_entity_id=uuid4(),
            tahun_pajak=2026,
            include_corrections=True,
            post_adjustment_journal=True,
            dry_run=False,
            user_id=uuid4(),
            correlation_id="corr-123"
        )
        assert isinstance(command, FiscalReconciliationCommand)

    def test_to_dict_returns_dict_with_expected_fields(self):
        legal_entity_id = uuid4()
        tahun_pajak = 2026
        command = FiscalReconciliationCommand(
            legal_entity_id=legal_entity_id,
            tahun_pajak=tahun_pajak,
            include_corrections=True,
            post_adjustment_journal=True,
            dry_run=False,
            user_id=uuid4(),
            correlation_id="corr-123"
        )
        result = command.to_dict()
        assert isinstance(result, dict)
        assert result["legal_entity_id"] == str(legal_entity_id)
        assert result["tahun_pajak"] == tahun_pajak
        assert result["include_corrections"] is True
        assert result["post_adjustment_journal"] is True
        assert result["dry_run"] is False
        assert result["correlation_id"] == "corr-123"


# ============================================================================
# Test FiscalCorrection
# ============================================================================

class TestFiscalCorrection:
    def test_construction(self):
        correction = FiscalCorrection(
            description="Depreciation adjustment",
            amount=Decimal("5000000"),
            is_permanent=True
        )
        assert isinstance(correction, FiscalCorrection)
        assert correction.description == "Depreciation adjustment"
        assert correction.amount == Decimal("5000000")
        assert correction.is_permanent is True

    def test_construction_with_temporary_correction(self):
        correction = FiscalCorrection(
            description="Timing difference",
            amount=Decimal("2000000"),
            is_permanent=False
        )
        assert correction.is_permanent is False


# ============================================================================
# Test FiscalReconciliationResult
# ============================================================================

class TestFiscalReconciliationResult:
    def test_construction(self):
        result = FiscalReconciliationResult(
            commercial_net_income=Decimal("100000000"),
            fiscal_corrections_positive=[MagicMock(description="Koreksi positif")],
            fiscal_corrections_negative=[MagicMock(description="Koreksi negatif")],
            fiscal_net_income=Decimal("105000000"),
            fiscal_loss_compensation=Decimal("5000000"),
            taxable_income=Decimal("100000000"),
            corporate_tax_rate=Decimal("0.22"),
            corporate_tax_due=Decimal("22000000"),
            tax_credits=Decimal("5000000"),
            tax_payable=Decimal("17000000"),
            adjustment_journal_id=uuid4(),
            report_path="/reports/fiscal_2026.pdf"
        )
        assert isinstance(result, FiscalReconciliationResult)
        assert result.commercial_net_income == Decimal("100000000")
        assert result.taxable_income == Decimal("100000000")
        assert result.tax_payable == Decimal("17000000")
        assert len(result.fiscal_corrections_positive) == 1


# ============================================================================
# Test FiscalReconciliationUseCase
# ============================================================================

class TestFiscalReconciliationUseCase:
    def test_construction(self):
        use_case = FiscalReconciliationUseCase(
            tax_service=MagicMock(),
            ledger_service=MagicMock(),
            report_service=MagicMock(),
            journal_service=MagicMock(),
            fiscal_period_service=MagicMock(),
            sealed_gate=MagicMock()
        )
        assert isinstance(use_case, FiscalReconciliationUseCase)

    @pytest.mark.asyncio
    async def test_execute_calls_services_and_returns_result(self):
        mock_tax = AsyncMock()
        mock_tax.reconcile_fiscal = AsyncMock(return_value=FiscalReconciliationResult(
            commercial_net_income=Decimal("100000000"),
            fiscal_corrections_positive=[],
            fiscal_corrections_negative=[],
            fiscal_net_income=Decimal("100000000"),
            fiscal_loss_compensation=Decimal("0"),
            taxable_income=Decimal("100000000"),
            corporate_tax_rate=Decimal("0.22"),
            corporate_tax_due=Decimal("22000000"),
            tax_credits=Decimal("0"),
            tax_payable=Decimal("22000000"),
            adjustment_journal_id=uuid4(),
            report_path="/reports/fiscal_2026.pdf"
        ))
        use_case = FiscalReconciliationUseCase(
            tax_service=mock_tax,
            ledger_service=AsyncMock(),
            report_service=AsyncMock(),
            journal_service=AsyncMock(),
            fiscal_period_service=MagicMock(),
            sealed_gate=MagicMock()
        )
        command = MagicMock()
        command.to_dict.return_value = {"tahun_pajak": 2026}
        result = await use_case.execute(command)
        assert isinstance(result, FiscalReconciliationResult)
        assert result.tax_payable == Decimal("22000000")
        mock_tax.reconcile_fiscal.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_passes_through_exceptions(self):
        mock_tax = AsyncMock()
        mock_tax.reconcile_fiscal = AsyncMock(side_effect=ValueError("Reconciliation failed"))
        use_case = FiscalReconciliationUseCase(
            tax_service=mock_tax,
            ledger_service=AsyncMock(),
            report_service=AsyncMock(),
            journal_service=AsyncMock(),
            fiscal_period_service=MagicMock(),
            sealed_gate=MagicMock()
        )
        command = MagicMock()
        with pytest.raises(ValueError, match="Reconciliation failed"):
            await use_case.execute(command)

    def test_get_stats_returns_dict(self):
        use_case = FiscalReconciliationUseCase(
            tax_service=MagicMock(),
            ledger_service=MagicMock(),
            report_service=MagicMock(),
            journal_service=MagicMock(),
            fiscal_period_service=MagicMock(),
            sealed_gate=MagicMock()
        )
        stats = use_case.get_stats()
        assert isinstance(stats, dict)
        # Check that it contains the expected keys from the actual implementation
        assert "executed" in stats
        assert "succeeded" in stats
        assert "failed" in stats

    def test_get_audit_trail_returns_list(self):
        use_case = FiscalReconciliationUseCase(
            tax_service=MagicMock(),
            ledger_service=MagicMock(),
            report_service=MagicMock(),
            journal_service=MagicMock(),
            fiscal_period_service=MagicMock(),
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
async def test_fiscal_reconciliation_handler_calls_use_case_and_returns_result():
    mock_use_case = AsyncMock()
    mock_use_case.execute = AsyncMock(return_value={"status": "success", "tax_payable": 22000000})
    command = MagicMock()
    result = await fiscal_reconciliation_handler(command=command, use_case=mock_use_case)
    assert result == {"status": "success", "tax_payable": 22000000}
    mock_use_case.execute.assert_called_once_with(command)
