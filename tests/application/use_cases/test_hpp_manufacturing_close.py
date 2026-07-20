#!/usr/bin/env python3
"""
tests/application/use_cases/test_hpp_manufacturing_close.py
Test untuk application/use_cases/hpp_manufacturing_close.py
"""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from application.use_cases.hpp_manufacturing_close import (
    HPPManufacturingCloseCommand,
    HPPManufacturingCloseUseCase,
    HPPResult,
    audit,
    hpp_manufacturing_close_handler,
    transactional,
)

# ============================================================================
# Test HPPManufacturingCloseCommand
# ============================================================================

class TestHPPManufacturingCloseCommand:
    def test_construction(self):
        command = HPPManufacturingCloseCommand(
            legal_entity_id=uuid4(),
            period_start=date.today(),
            period_end=date.today(),
            post_to_gl=True,
            dry_run=False,
            user_id=uuid4(),
            correlation_id="corr-123"
        )
        assert isinstance(command, HPPManufacturingCloseCommand)

    def test_to_dict_returns_dict_with_expected_fields(self):
        legal_entity_id = uuid4()
        period_start = date(2026, 1, 1)
        period_end = date(2026, 1, 31)
        command = HPPManufacturingCloseCommand(
            legal_entity_id=legal_entity_id,
            period_start=period_start,
            period_end=period_end,
            post_to_gl=True,
            dry_run=False,
            user_id=uuid4(),
            correlation_id="corr-123"
        )
        result = command.to_dict()
        assert isinstance(result, dict)
        assert result["legal_entity_id"] == str(legal_entity_id)
        assert result["period_start"] == period_start.isoformat()
        assert result["period_end"] == period_end.isoformat()
        assert result["post_to_gl"] is True
        assert result["dry_run"] is False
        assert result["correlation_id"] == "corr-123"


# ============================================================================
# Test HPPResult
# ============================================================================

class TestHPPResult:
    def test_construction(self):
        result = HPPResult(
            total_material_cost=Decimal("1000.00"),
            total_labor_cost=Decimal("500.00"),
            total_overhead_cost=Decimal("300.00"),
            total_manufacturing_cost=Decimal("1800.00"),
            beginning_wip=Decimal("200.00"),
            ending_wip=Decimal("150.00"),
            cogm=Decimal("1850.00"),
            journal_id=uuid4(),
            product_costs=[{"product_id": "P001", "cost": 100}]
        )
        assert isinstance(result, HPPResult)
        assert result.total_material_cost == Decimal("1000.00")
        assert result.total_labor_cost == Decimal("500.00")
        assert result.total_manufacturing_cost == Decimal("1800.00")
        assert result.cogm == Decimal("1850.00")
        assert len(result.product_costs) == 1


# ============================================================================
# Test HPPManufacturingCloseUseCase
# ============================================================================

class TestHPPManufacturingCloseUseCase:
    def test_construction(self):
        use_case = HPPManufacturingCloseUseCase(
            manufacturing_service=MagicMock(),
            inventory_service=MagicMock(),
            journal_service=MagicMock(),
            fiscal_period_service=MagicMock(),
            uow=MagicMock(),
            sealed_gate=MagicMock()
        )
        assert isinstance(use_case, HPPManufacturingCloseUseCase)

    @pytest.mark.asyncio
    async def test_execute_calls_services_and_returns_result(self):
        mock_manufacturing = AsyncMock()
        mock_manufacturing.calculate_hpp = AsyncMock(return_value=HPPResult(
            total_material_cost=Decimal("1000"),
            total_labor_cost=Decimal("500"),
            total_overhead_cost=Decimal("300"),
            total_manufacturing_cost=Decimal("1800"),
            beginning_wip=Decimal("200"),
            ending_wip=Decimal("150"),
            cogm=Decimal("1850"),
            journal_id=uuid4(),
            product_costs=[]
        ))
        use_case = HPPManufacturingCloseUseCase(
            manufacturing_service=mock_manufacturing,
            inventory_service=AsyncMock(),
            journal_service=AsyncMock(),
            fiscal_period_service=MagicMock(),
            uow=MagicMock(),
            sealed_gate=MagicMock()
        )
        command = MagicMock()
        command.to_dict.return_value = {"period_start": date(2026, 1, 1), "period_end": date(2026, 1, 31)}
        result = await use_case.execute(command)
        assert isinstance(result, HPPResult)
        assert result.cogm == Decimal("1850.00")
        mock_manufacturing.calculate_hpp.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_passes_through_exceptions(self):
        mock_manufacturing = AsyncMock()
        mock_manufacturing.calculate_hpp = AsyncMock(side_effect=ValueError("HPP calculation failed"))
        use_case = HPPManufacturingCloseUseCase(
            manufacturing_service=mock_manufacturing,
            inventory_service=AsyncMock(),
            journal_service=AsyncMock(),
            fiscal_period_service=MagicMock(),
            uow=MagicMock(),
            sealed_gate=MagicMock()
        )
        command = MagicMock()
        with pytest.raises(ValueError, match="HPP calculation failed"):
            await use_case.execute(command)

    def test_get_stats_returns_dict(self):
        use_case = HPPManufacturingCloseUseCase(
            manufacturing_service=MagicMock(),
            inventory_service=MagicMock(),
            journal_service=MagicMock(),
            fiscal_period_service=MagicMock(),
            uow=MagicMock(),
            sealed_gate=MagicMock()
        )
        stats = use_case.get_stats()
        assert isinstance(stats, dict)
        # At minimum, should have some keys
        assert "total_executions" in stats or "executed_count" in stats

    def test_get_audit_trail_returns_list(self):
        use_case = HPPManufacturingCloseUseCase(
            manufacturing_service=MagicMock(),
            inventory_service=MagicMock(),
            journal_service=MagicMock(),
            fiscal_period_service=MagicMock(),
            uow=MagicMock(),
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


def test_transactional_returns_callable_decorator():
    async def dummy_method(self):
        return "ok"
    decorated = transactional(dummy_method)
    assert callable(decorated)


@pytest.mark.asyncio
async def test_hpp_manufacturing_close_handler_calls_use_case_and_returns_result():
    mock_use_case = AsyncMock()
    mock_use_case.execute = AsyncMock(return_value={"status": "success", "cogm": 1850.0})
    command = MagicMock()
    result = await hpp_manufacturing_close_handler(command=command, use_case=mock_use_case)
    assert result == {"status": "success", "cogm": 1850.0}
    mock_use_case.execute.assert_called_once_with(command)
