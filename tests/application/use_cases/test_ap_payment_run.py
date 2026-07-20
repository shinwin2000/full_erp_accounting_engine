#!/usr/bin/env python3
"""
tests/application/use_cases/test_ap_payment_run.py
Test untuk application/use_cases/ap_payment_run.py
"""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from application.use_cases.ap_payment_run import (
    ApPaymentRun,
    APPaymentRunCommand,
    APPaymentRunResult,
    APPaymentRunUseCase,
    ap_payment_run_handler,
    audit,
    transactional,
)

# ============================================================================
# Test APPaymentRunCommand
# ============================================================================

class TestAPPaymentRunCommand:
    def test_construction(self):
        command = APPaymentRunCommand(
            legal_entity_id=uuid4(),
            payment_date=date.today(),
            vendor_id=uuid4(),
            invoice_ids=[uuid4(), uuid4()],
            bank_account_id=uuid4(),
            payment_method="BANK_TRANSFER",
            auto_approve=True,
            dry_run=False,
            user_id=uuid4(),
            correlation_id="corr-123"
        )
        assert isinstance(command, APPaymentRunCommand)

    def test_to_dict_returns_dict_with_expected_fields(self):
        legal_entity_id = uuid4()
        vendor_id = uuid4()
        payment_date = date.today()
        command = APPaymentRunCommand(
            legal_entity_id=legal_entity_id,
            payment_date=payment_date,
            vendor_id=vendor_id,
            invoice_ids=[uuid4()],
            bank_account_id=uuid4(),
            payment_method="BANK_TRANSFER",
            auto_approve=True,
            dry_run=False,
            user_id=uuid4(),
            correlation_id="corr-123"
        )
        result = command.to_dict()
        assert isinstance(result, dict)
        assert result["legal_entity_id"] == str(legal_entity_id)
        assert result["payment_date"] == payment_date.isoformat()
        assert result["vendor_id"] == str(vendor_id)
        assert result["payment_method"] == "BANK_TRANSFER"
        assert result["auto_approve"] is True
        assert result["dry_run"] is False


# ============================================================================
# Test APPaymentRunResult
# ============================================================================

class TestAPPaymentRunResult:
    def test_construction(self):
        result = APPaymentRunResult(
            invoice_count=5,
            total_amount=Decimal("1000000.00"),
            discount_applied=Decimal("50000.00"),
            net_payment=Decimal("950000.00"),
            payment_ids=[uuid4(), uuid4()],
            journal_id=uuid4(),
            bank_file_path="/payments/2026-01-15.txt",
            errors=[]
        )
        assert isinstance(result, APPaymentRunResult)
        assert result.invoice_count == 5
        assert result.total_amount == Decimal("1000000.00")
        assert result.net_payment == Decimal("950000.00")
        assert len(result.payment_ids) == 2

    def test_construction_with_errors(self):
        result = APPaymentRunResult(
            invoice_count=2,
            total_amount=Decimal("500000.00"),
            discount_applied=Decimal("0"),
            net_payment=Decimal("500000.00"),
            payment_ids=[],
            journal_id=uuid4(),
            bank_file_path=None,
            errors=["Invoice INV-001 not found", "Insufficient balance"]
        )
        assert len(result.errors) == 2
        assert result.errors[0] == "Invoice INV-001 not found"


# ============================================================================
# Test APPaymentRunUseCase
# ============================================================================

class TestAPPaymentRunUseCase:
    def test_construction(self):
        use_case = APPaymentRunUseCase(
            ap_service=MagicMock(),
            bank_cash_service=MagicMock(),
            journal_service=MagicMock(),
            uow=MagicMock(),
            sealed_gate=MagicMock()
        )
        assert isinstance(use_case, APPaymentRunUseCase)

    @pytest.mark.asyncio
    async def test_execute_calls_services_and_returns_result(self):
        mock_ap = AsyncMock()
        mock_ap.process_payment_run = AsyncMock(return_value=APPaymentRunResult(
            invoice_count=3,
            total_amount=Decimal("750000.00"),
            discount_applied=Decimal("25000.00"),
            net_payment=Decimal("725000.00"),
            payment_ids=[uuid4()],
            journal_id=uuid4(),
            bank_file_path="/payments/run.txt",
            errors=[]
        ))
        use_case = APPaymentRunUseCase(
            ap_service=mock_ap,
            bank_cash_service=AsyncMock(),
            journal_service=AsyncMock(),
            uow=MagicMock(),
            sealed_gate=MagicMock()
        )
        command = MagicMock()
        command.to_dict.return_value = {"vendor_id": str(uuid4())}
        result = await use_case.execute(command)
        assert isinstance(result, APPaymentRunResult)
        assert result.invoice_count == 3
        assert result.net_payment == Decimal("725000.00")
        mock_ap.process_payment_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_passes_through_exceptions(self):
        mock_ap = AsyncMock()
        mock_ap.process_payment_run = AsyncMock(side_effect=ValueError("Payment run failed"))
        use_case = APPaymentRunUseCase(
            ap_service=mock_ap,
            bank_cash_service=AsyncMock(),
            journal_service=AsyncMock(),
            uow=MagicMock(),
            sealed_gate=MagicMock()
        )
        command = MagicMock()
        with pytest.raises(ValueError, match="Payment run failed"):
            await use_case.execute(command)

    def test_get_stats_returns_dict(self):
        use_case = APPaymentRunUseCase(
            ap_service=MagicMock(),
            bank_cash_service=MagicMock(),
            journal_service=MagicMock(),
            uow=MagicMock(),
            sealed_gate=MagicMock()
        )
        stats = use_case.get_stats()
        assert isinstance(stats, dict)
        # At minimum should have some keys
        assert "total_executions" in stats or "executed_count" in stats

    def test_get_audit_trail_returns_list(self):
        use_case = APPaymentRunUseCase(
            ap_service=MagicMock(),
            bank_cash_service=MagicMock(),
            journal_service=MagicMock(),
            uow=MagicMock(),
            sealed_gate=MagicMock()
        )
        trail = use_case.get_audit_trail()
        assert isinstance(trail, list)


# ============================================================================
# Test ApPaymentRun (legacy)
# ============================================================================

class TestApPaymentRun:
    def test_construction(self):
        instance = ApPaymentRun(
            ap_service=MagicMock(),
            bank_service=MagicMock(),
            journal_service=MagicMock()
        )
        assert isinstance(instance, ApPaymentRun)

    def test_execute_returns_result(self):
        mock_ap = MagicMock()
        mock_ap.process_payments = MagicMock(return_value={"payment_ids": ["PAY-001"], "total": 1000})
        instance = ApPaymentRun(
            ap_service=mock_ap,
            bank_service=MagicMock(),
            journal_service=MagicMock()
        )
        invoices = [MagicMock(), MagicMock()]
        result = instance.execute(
            invoices=invoices,
            bank_account="BCA-001",
            user_id="admin"
        )
        assert result is not None
        mock_ap.process_payments.assert_called_once_with(invoices, "BCA-001", "admin")

    def test_get_audit_trail_returns_list(self):
        instance = ApPaymentRun(
            ap_service=MagicMock(),
            bank_service=MagicMock(),
            journal_service=MagicMock()
        )
        # Simulate some audit entries
        instance._audit_trail = [{"event": "created"}, {"event": "processed"}]
        trail = instance.get_audit_trail()
        assert isinstance(trail, list)
        assert len(trail) == 2


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


def test_transactional_returns_callable_decorator():
    async def dummy_method(self):
        return "ok"
    decorated = transactional(dummy_method)
    assert callable(decorated)


@pytest.mark.asyncio
async def test_ap_payment_run_handler_calls_use_case_and_returns_result():
    mock_use_case = AsyncMock()
    mock_use_case.execute = AsyncMock(return_value={"status": "success", "payment_count": 5})
    command = MagicMock()
    result = await ap_payment_run_handler(command=command, use_case=mock_use_case)
    assert result == {"status": "success", "payment_count": 5}
    mock_use_case.execute.assert_called_once_with(command)
