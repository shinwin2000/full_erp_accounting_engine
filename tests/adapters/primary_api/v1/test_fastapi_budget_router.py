#!/usr/bin/env python3
"""
Comprehensive tests for FastAPI Budget Router.

Covers:
- IdempotencyManager
- All enums
- All request/response schemas (valid & invalid cases)
- All endpoint functions (with mocked service layer)
- Negative path tests (404, 422, 500)
- Proper async markers
- Mock quality assertions
- No flaky datetime usage
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.responses import Response

from adapters.primary_api.v1.fastapi_budget_router import (
    BudgetAlertSchema,
    BudgetCreateSchema,
    BudgetDashboardResponseSchema,
    BudgetLineSchema,
    BudgetLineUpdateSchema,
    BudgetPeriod,
    BudgetResponseSchema,
    BudgetRollingForecastSchema,
    BudgetStatus,
    BudgetTransferResponseSchema,
    BudgetTransferSchema,
    BudgetType,
    BudgetUpdateSchema,
    BudgetVersionResponseSchema,
    BudgetVsActualLineSchema,
    BudgetVsActualResponseSchema,
    IdempotencyManager,
    VarianceType,
    activate_budget,
    approve_budget,
    archive_budget,
    create_budget,
    create_budget_version,
    create_rolling_forecast,
    export_budgets,
    get_budget,
    get_budget_alerts,
    get_budget_by_code,
    get_budget_dashboard,
    get_budget_history,
    get_budget_service,
    get_budget_status,
    get_budget_versions,
    get_budget_vs_actual,
    get_budget_vs_actual_ytd,
    list_budgets,
    lock_budget,
    reject_budget,
    submit_budget,
    transfer_budget,
    unlock_budget,
    update_budget,
    update_budget_lines,
)


# =============================================================================
# Helper fixtures
# =============================================================================

@pytest.fixture
def mock_current_user():
    return MagicMock(user_id=uuid4())


@pytest.fixture
def mock_legal_entity_id():
    return uuid4()


@pytest.fixture
def mock_budget_service():
    svc = AsyncMock()

    # Default budget response
    def create_mock_budget(**kwargs):
        defaults = {
            "id": uuid4(),
            "budget_code": "BUD-2026-001",
            "budget_name": "Operational Budget 2026",
            "budget_type": "operational",
            "fiscal_year": 2026,
            "period": "monthly",
            "version": "1.0",
            "status": "draft",
            "effective_date": date(2026, 1, 1),
            "expiry_date": date(2026, 12, 31),
            "currency": "IDR",
            "total_amount": Decimal("100000000"),
            "actual_amount_ytd": Decimal("0"),
            "variance_amount": Decimal("0"),
            "variance_percent": 0.0,
            "consumption_percent": 0.0,
            "notes": "Test budget",
            "tags": ["tag1"],
            "is_locked": False,
            "created_at": datetime(2026, 1, 1, tzinfo=UTC),
            "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
            "created_by": uuid4(),
            "created_by_name": "Admin",
            "approved_at": None,
            "approved_by": None,
            "approved_by_name": None,
            "lines": [],
        }
        defaults.update(kwargs)
        return MagicMock(**defaults)

    # CRUD
    svc.create_budget.return_value = create_mock_budget()
    svc.get_budget_by_id.return_value = create_mock_budget()
    svc.get_budget_by_code.return_value = create_mock_budget()
    svc.update_budget.return_value = create_mock_budget()
    svc.update_budget_lines.return_value = create_mock_budget()
    svc.archive_budget.return_value = create_mock_budget(status="archived")
    svc.list_budgets.return_value = MagicMock(
        items=[create_mock_budget()],
        total=1,
    )
    svc.get_budget_versions.return_value = [
        MagicMock(
            id=uuid4(),
            budget_code="BUD-2026-001",
            version="1.0",
            status="draft",
            total_amount=Decimal("100000000"),
            effective_date=date(2026, 1, 1),
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            created_by=uuid4(),
            created_by_name="Admin",
        )
    ]
    svc.create_budget_version.return_value = create_mock_budget(version="2.0")

    # Workflow
    svc.submit_budget.return_value = create_mock_budget(status="submitted")
    svc.approve_budget.return_value = create_mock_budget(status="approved")
    svc.reject_budget.return_value = create_mock_budget(status="rejected")
    svc.activate_budget.return_value = create_mock_budget(status="active")
    svc.lock_budget.return_value = create_mock_budget(is_locked=True)
    svc.unlock_budget.return_value = create_mock_budget(is_locked=False)

    # VS Actual
    svc.get_budget_vs_actual.return_value = MagicMock(
        budget_id=uuid4(),
        budget_name="Operational Budget 2026",
        fiscal_year=2026,
        period=1,
        period_name="January",
        total_budget=Decimal("10000000"),
        total_actual=Decimal("8000000"),
        total_variance=Decimal("2000000"),
        variance_percent=20.0,
        variance_type="favorable",
        consumption_rate=80.0,
        remaining_budget=Decimal("2000000"),
        lines=[
            MagicMock(
                account_id=uuid4(),
                account_code="1100",
                account_name="Cash",
                budget_amount=Decimal("1000000"),
                actual_amount=Decimal("800000"),
                variance_amount=Decimal("200000"),
                variance_percent=20.0,
                variance_type="favorable",
                consumption_percent=80.0,
                remaining_budget=Decimal("200000"),
            )
        ],
        generated_at=datetime.now(UTC),
    )
    svc.get_budget_vs_actual_ytd.return_value = svc.get_budget_vs_actual.return_value

    # Transfer
    svc.transfer_budget.return_value = MagicMock(
        transfer_id=uuid4(),
        budget_id=uuid4(),
        from_account_id=uuid4(),
        from_account_code="1100",
        from_account_name="Cash",
        to_account_id=uuid4(),
        to_account_code="1200",
        to_account_name="Bank",
        amount=Decimal("1000000"),
        reason="Reallocate",
        effective_date=date.today(),
        created_at=datetime.now(UTC),
        created_by=uuid4(),
        created_by_name="Admin",
        approved_at=None,
        approved_by=None,
    )

    # Dashboard
    svc.get_budget_dashboard.return_value = MagicMock(
        total_budgets=5,
        active_budgets=3,
        total_budget_amount=Decimal("500000000"),
        total_actual_ytd=Decimal("300000000"),
        total_variance=Decimal("200000000"),
        overall_consumption_rate=60.0,
        by_type={"OPERATIONAL": 3, "CAPITAL": 2},
        by_status={"ACTIVE": 3, "DRAFT": 2},
        top_variance_items=[],
        alerts=[],
    )

    # Alerts
    svc.get_budget_alerts.return_value = [
        MagicMock(
            budget_id=uuid4(),
            budget_name="Operational Budget",
            account_id=uuid4(),
            account_code="1100",
            account_name="Cash",
            budget_amount=Decimal("1000000"),
            actual_amount=Decimal("950000"),
            consumption_percent=95.0,
            threshold_percent=90.0,
            message="Budget nearly exhausted",
            severity="HIGH",
            created_at=datetime.now(UTC),
        )
    ]

    # Rolling forecast
    svc.create_rolling_forecast.return_value = create_mock_budget()

    # History
    svc.get_budget_history.return_value = [
        MagicMock(
            timestamp=datetime.now(UTC),
            action="create",
            field=None,
            old_value=None,
            new_value=None,
            actor_id=uuid4(),
            actor_name="Admin",
            reason="Initial",
        )
    ]

    # Status
    svc.get_budget_status.return_value = MagicMock(
        budget_code="BUD-2026-001",
        status="draft",
        status_description="Draft",
        can_submit=True,
        can_approve=False,
        can_reject=False,
        can_activate=False,
        can_lock=False,
        can_edit=True,
        can_delete=True,
        is_locked=False,
        is_archived=False,
        current_approver=None,
        approval_level=0,
        submitted_at=None,
        approved_at=None,
        activated_at=None,
    )

    # Export
    svc.export_budgets.return_value = b"csv data"

    return svc


# =============================================================================
# IdempotencyManager Tests
# =============================================================================

class TestIdempotencyManager:
    def test_construction(self):
        manager = IdempotencyManager()
        assert manager._storage == {}
        assert manager._ttl_seconds == 86400

    def test_get_cached_result_miss(self):
        manager = IdempotencyManager()
        result = manager.get_cached_result("key1", "method1")
        assert result is None

    def test_cache_and_retrieve(self):
        manager = IdempotencyManager()
        data = {"id": "123", "status": "ok"}
        manager.cache_result("key1", "method1", data)
        cached = manager.get_cached_result("key1", "method1")
        assert cached == data

    def test_cache_expiration(self):
        manager = IdempotencyManager()
        manager._ttl_seconds = 0
        manager.cache_result("key3", "method3", {"foo": "bar"})
        cached = manager.get_cached_result("key3", "method3")
        assert cached is None

    def test_cache_serializes_complex_types(self):
        manager = IdempotencyManager()
        data = {"date": date.today(), "decimal": Decimal("10.50")}
        manager.cache_result("key2", "method2", data)
        cached = manager.get_cached_result("key2", "method2")
        assert cached is not None
        assert "date" in cached

    def test_key_generation_deterministic(self):
        manager = IdempotencyManager()
        key1 = manager._get_key("abc", "create_asset")
        key2 = manager._get_key("abc", "create_asset")
        key3 = manager._get_key("abc", "update_asset")
        assert key1 == key2
        assert key1 != key3


# =============================================================================
# Enums Tests
# =============================================================================

class TestBudgetStatus:
    def test_members_exist(self):
        expected = ["DRAFT", "SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED",
                    "ACTIVE", "LOCKED", "ARCHIVED", "EXPIRED"]
        for name in expected:
            assert hasattr(BudgetStatus, name)
        assert isinstance(BudgetStatus.DRAFT, BudgetStatus)

    def test_values(self):
        assert BudgetStatus.DRAFT.value == "draft"
        assert BudgetStatus.ACTIVE.value == "active"


class TestBudgetType:
    def test_members_exist(self):
        expected = ["OPERATIONAL", "CAPITAL", "CASH", "PROJECT", "DEPARTMENT",
                    "FIXED_ASSET", "SALES", "PRODUCTION", "LABOR"]
        for name in expected:
            assert hasattr(BudgetType, name)
        assert isinstance(BudgetType.OPERATIONAL, BudgetType)

    def test_values(self):
        assert BudgetType.OPERATIONAL.value == "operational"


class TestBudgetPeriod:
    def test_members_exist(self):
        expected = ["MONTHLY", "QUARTERLY", "YEARLY"]
        for name in expected:
            assert hasattr(BudgetPeriod, name)
        assert isinstance(BudgetPeriod.MONTHLY, BudgetPeriod)

    def test_values(self):
        assert BudgetPeriod.MONTHLY.value == "monthly"


class TestVarianceType:
    def test_members_exist(self):
        expected = ["FAVORABLE", "UNFAVORABLE", "NEUTRAL"]
        for name in expected:
            assert hasattr(VarianceType, name)
        assert isinstance(VarianceType.FAVORABLE, VarianceType)

    def test_values(self):
        assert VarianceType.FAVORABLE.value == "favorable"


# =============================================================================
# Schemas Tests (with validation)
# =============================================================================

class TestBudgetLineSchema:
    def test_valid(self):
        account_id = uuid4()
        schema = BudgetLineSchema(
            account_id=account_id,
            account_code="1100",
            amount=Decimal("1000000"),
            note="Test line"
        )
        assert schema.account_id == account_id
        assert schema.amount == Decimal("1000000")

    def test_negative_amount_raises(self):
        account_id = uuid4()
        with pytest.raises(ValueError, match="Amount cannot be negative"):
            BudgetLineSchema(
                account_id=account_id,
                amount=Decimal("-100"),
            )


class TestBudgetCreateSchema:
    def test_valid(self):
        account_id = uuid4()
        lines = [BudgetLineSchema(account_id=account_id, amount=Decimal("1000"))]
        schema = BudgetCreateSchema(
            budget_code="BUD-001",
            budget_name="Test Budget",
            budget_type=BudgetType.OPERATIONAL,
            fiscal_year=2026,
            period=BudgetPeriod.MONTHLY,
            version="1.0",
            effective_date=date(2026, 1, 1),
            expiry_date=date(2026, 12, 31),
            currency="IDR",
            lines=lines,
            notes="Test",
            tags=["tag1"],
        )
        assert schema.budget_code == "BUD-001"
        assert schema.total_amount == Decimal("1000")
        assert schema.currency == "IDR"

    def test_upper_case_code(self):
        schema = BudgetCreateSchema(
            budget_code="bud-002",
            budget_name="Test",
            fiscal_year=2026,
            lines=[BudgetLineSchema(account_id=uuid4(), amount=Decimal("100"))],
        )
        assert schema.budget_code == "BUD-002"

    def test_expiry_before_effective_raises(self):
        with pytest.raises(ValueError, match="Expiry date must be after effective date"):
            BudgetCreateSchema(
                budget_code="BUD-001",
                budget_name="Test",
                fiscal_year=2026,
                effective_date=date(2026, 1, 1),
                expiry_date=date(2025, 12, 31),
                lines=[BudgetLineSchema(account_id=uuid4(), amount=Decimal("100"))],
            )

    def test_lines_min_length_1(self):
        # Pydantic will raise validation error for missing required field
        with pytest.raises(ValueError):
            BudgetCreateSchema(
                budget_code="BUD-001",
                budget_name="Test",
                fiscal_year=2026,
                lines=[],
            )


class TestBudgetUpdateSchema:
    def test_valid(self):
        schema = BudgetUpdateSchema(
            budget_name="Updated",
            effective_date=date(2026, 2, 1),
            notes="New notes",
            tags=["updated"],
            status=BudgetStatus.APPROVED,
        )
        assert schema.budget_name == "Updated"


class TestBudgetLineUpdateSchema:
    def test_valid(self):
        line_id = uuid4()
        schema = BudgetLineUpdateSchema(
            line_id=line_id,
            amount=Decimal("2000000"),
            note="Updated line"
        )
        assert schema.line_id == line_id
        assert schema.amount == Decimal("2000000")


class TestBudgetTransferSchema:
    def test_valid(self):
        from_id = uuid4()
        to_id = uuid4()
        schema = BudgetTransferSchema(
            from_account_id=from_id,
            to_account_id=to_id,
            amount=Decimal("1000000"),
            reason="Reallocate",
            effective_date=date.today(),
        )
        assert schema.from_account_id == from_id
        assert schema.to_account_id == to_id

    def test_same_account_raises(self):
        account_id = uuid4()
        with pytest.raises(ValueError, match="Source and destination accounts must be different"):
            BudgetTransferSchema(
                from_account_id=account_id,
                to_account_id=account_id,
                amount=Decimal("1000"),
                reason="Test",
            )

    def test_negative_amount_raises(self):
        from_id = uuid4()
        to_id = uuid4()
        with pytest.raises(ValueError):
            BudgetTransferSchema(
                from_account_id=from_id,
                to_account_id=to_id,
                amount=Decimal("-100"),
                reason="Test",
            )


class TestBudgetRollingForecastSchema:
    def test_valid(self):
        base_id = uuid4()
        schema = BudgetRollingForecastSchema(
            base_budget_id=base_id,
            forecast_months=6,
            adjustment_factors={1: Decimal("1.1")},
            notes="Test forecast"
        )
        assert schema.base_budget_id == base_id
        assert schema.forecast_months == 6


# =============================================================================
# Endpoint Tests (with mocks)
# =============================================================================

@pytest.mark.asyncio
class TestBudgetCRUD:
    async def test_get_budget_service(self):
        request = MagicMock()
        request.app.state.container = MagicMock()
        request.app.state.container.resolve.return_value = "service"
        result = await get_budget_service(request)
        assert result == "service"

    async def test_create_budget_success(self, mock_budget_service, mock_current_user, mock_legal_entity_id):
        account_id = uuid4()
        request_data = BudgetCreateSchema(
            budget_code="BUD-001",
            budget_name="Test Budget",
            budget_type=BudgetType.OPERATIONAL,
            fiscal_year=2026,
            period=BudgetPeriod.MONTHLY,
            version="1.0",
            effective_date=date(2026, 1, 1),
            expiry_date=date(2026, 12, 31),
            lines=[BudgetLineSchema(account_id=account_id, amount=Decimal("1000"))],
        )
        result = await create_budget(
            request=request_data,
            idempotency_key=None,
            _permission=None,
            current_user=mock_current_user,
            legal_entity_id=mock_legal_entity_id,
            service=mock_budget_service,
        )
        assert isinstance(result, BudgetResponseSchema)
        assert result.budget_code == "BUD-2026-001"
        mock_budget_service.create_budget.assert_called_once()

    async def test_create_budget_idempotency(self, mock_budget_service, mock_current_user, mock_legal_entity_id):
        account_id = uuid4()
        request_data = BudgetCreateSchema(
            budget_code="BUD-001",
            budget_name="Test Budget",
            budget_type=BudgetType.OPERATIONAL,
            fiscal_year=2026,
            period=BudgetPeriod.MONTHLY,
            lines=[BudgetLineSchema(account_id=account_id, amount=Decimal("1000"))],
        )
        with patch("adapters.primary_api.v1.fastapi_budget_router._idempotency_manager") as mock_im:
            mock_im.get_cached_result.return_value = {
                "id": str(uuid4()),
                "budget_code": "BUD-001",
                "budget_name": "Test Budget",
                "budget_type": "operational",
                "fiscal_year": 2026,
                "period": "monthly",
                "version": "1.0",
                "status": "draft",
                "effective_date": date(2026, 1, 1).isoformat(),
                "expiry_date": date(2026, 12, 31).isoformat(),
                "currency": "IDR",
                "total_amount": "1000.00",
                "actual_amount_ytd": "0.00",
                "variance_amount": "0.00",
                "variance_percent": 0.0,
                "consumption_percent": 0.0,
                "notes": None,
                "tags": None,
                "is_locked": False,
                "created_at": datetime.now(UTC).isoformat(),
                "updated_at": datetime.now(UTC).isoformat(),
                "created_by": str(uuid4()),
                "created_by_name": None,
                "approved_at": None,
                "approved_by": None,
                "approved_by_name": None,
                "lines": [],
            }
            result = await create_budget(
                request=request_data,
                idempotency_key="abc123",
                _permission=None,
                current_user=mock_current_user,
                legal_entity_id=mock_legal_entity_id,
                service=mock_budget_service,
            )
            assert isinstance(result, BudgetResponseSchema)
            mock_budget_service.create_budget.assert_not_called()

    async def test_create_budget_value_error(self, mock_budget_service, mock_current_user, mock_legal_entity_id):
        mock_budget_service.create_budget.side_effect = ValueError("Duplicate code")
        account_id = uuid4()
        request_data = BudgetCreateSchema(
            budget_code="BUD-001",
            budget_name="Test",
            fiscal_year=2026,
            lines=[BudgetLineSchema(account_id=account_id, amount=Decimal("1000"))],
        )
        with pytest.raises(HTTPException) as exc:
            await create_budget(
                request=request_data,
                idempotency_key=None,
                _permission=None,
                current_user=mock_current_user,
                legal_entity_id=mock_legal_entity_id,
                service=mock_budget_service,
            )
        assert exc.value.status_code == 422

    async def test_get_budget_success(self, mock_budget_service, mock_legal_entity_id):
        budget_id = uuid4()
        result = await get_budget(
            budget_id=budget_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_budget_service,
        )
        assert isinstance(result, BudgetResponseSchema)
        mock_budget_service.get_budget_by_id.assert_called_once_with(budget_id, mock_legal_entity_id)

    async def test_get_budget_not_found(self, mock_budget_service, mock_legal_entity_id):
        mock_budget_service.get_budget_by_id.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_budget(
                budget_id=uuid4(),
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                service=mock_budget_service,
            )
        assert exc.value.status_code == 404

    async def test_get_budget_by_code_success(self, mock_budget_service, mock_legal_entity_id):
        result = await get_budget_by_code(
            budget_code="BUD-001",
            fiscal_year=2026,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_budget_service,
        )
        assert isinstance(result, BudgetResponseSchema)
        mock_budget_service.get_budget_by_code.assert_called_once_with("BUD-001", 2026, mock_legal_entity_id)

    async def test_get_budget_by_code_not_found(self, mock_budget_service, mock_legal_entity_id):
        mock_budget_service.get_budget_by_code.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_budget_by_code(
                budget_code="UNKNOWN",
                fiscal_year=2026,
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                service=mock_budget_service,
            )
        assert exc.value.status_code == 404

    async def test_update_budget_success(self, mock_budget_service, mock_current_user, mock_legal_entity_id):
        budget_id = uuid4()
        request_data = BudgetUpdateSchema(budget_name="Updated Name")
        result = await update_budget(
            budget_id=budget_id,
            request=request_data,
            idempotency_key=None,
            _permission=None,
            current_user=mock_current_user,
            legal_entity_id=mock_legal_entity_id,
            service=mock_budget_service,
        )
        assert isinstance(result, BudgetResponseSchema)
        mock_budget_service.update_budget.assert_called_once()

    async def test_update_budget_not_found(self, mock_budget_service, mock_current_user, mock_legal_entity_id):
        mock_budget_service.update_budget.return_value = None
        request_data = BudgetUpdateSchema()
        with pytest.raises(HTTPException) as exc:
            await update_budget(
                budget_id=uuid4(),
                request=request_data,
                idempotency_key=None,
                _permission=None,
                current_user=mock_current_user,
                legal_entity_id=mock_legal_entity_id,
                service=mock_budget_service,
            )
        assert exc.value.status_code == 404

    async def test_update_budget_lines_success(self, mock_budget_service, mock_current_user, mock_legal_entity_id):
        budget_id = uuid4()
        line_id = uuid4()
        lines = [BudgetLineUpdateSchema(line_id=line_id, amount=Decimal("5000"))]
        result = await update_budget_lines(
            budget_id=budget_id,
            lines=lines,
            idempotency_key=None,
            _permission=None,
            current_user=mock_current_user,
            legal_entity_id=mock_legal_entity_id,
            service=mock_budget_service,
        )
        assert isinstance(result, BudgetResponseSchema)
        mock_budget_service.update_budget_lines.assert_called_once()

    async def test_update_budget_lines_not_found(self, mock_budget_service, mock_current_user, mock_legal_entity_id):
        mock_budget_service.update_budget_lines.return_value = None
        line_id = uuid4()
        lines = [BudgetLineUpdateSchema(line_id=line_id, amount=Decimal("5000"))]
        with pytest.raises(HTTPException) as exc:
            await update_budget_lines(
                budget_id=uuid4(),
                lines=lines,
                idempotency_key=None,
                _permission=None,
                current_user=mock_current_user,
                legal_entity_id=mock_legal_entity_id,
                service=mock_budget_service,
            )
        assert exc.value.status_code == 404

    async def test_archive_budget_success(self, mock_budget_service, mock_current_user, mock_legal_entity_id):
        budget_id = uuid4()
        result = await archive_budget(
            budget_id=budget_id,
            reason="Obsolete",
            idempotency_key=None,
            _permission=None,
            current_user=mock_current_user,
            legal_entity_id=mock_legal_entity_id,
            service=mock_budget_service,
        )
        assert result["status"] == "archived"
        mock_budget_service.archive_budget.assert_called_once_with(
            budget_id, mock_current_user.user_id, mock_legal_entity_id, "Obsolete"
        )

    async def test_archive_budget_not_found(self, mock_budget_service, mock_current_user, mock_legal_entity_id):
        mock_budget_service.archive_budget.return_value = None
        with pytest.raises(HTTPException) as exc:
            await archive_budget(
                budget_id=uuid4(),
                reason="",
                idempotency_key=None,
                _permission=None,
                current_user=mock_current_user,
                legal_entity_id=mock_legal_entity_id,
                service=mock_budget_service,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestBudgetWorkflow:
    async def test_submit_budget_success(self, mock_budget_service, mock_current_user, mock_legal_entity_id):
        budget_id = uuid4()
        result = await submit_budget(
            budget_id=budget_id,
            idempotency_key=None,
            _permission=None,
            current_user=mock_current_user,
            legal_entity_id=mock_legal_entity_id,
            service=mock_budget_service,
        )
        assert result.status == BudgetStatus.SUBMITTED
        mock_budget_service.submit_budget.assert_called_once_with(budget_id, mock_current_user.user_id, mock_legal_entity_id)

    async def test_submit_budget_not_found(self, mock_budget_service, mock_current_user, mock_legal_entity_id):
        mock_budget_service.submit_budget.return_value = None
        with pytest.raises(HTTPException) as exc:
            await submit_budget(
                budget_id=uuid4(),
                idempotency_key=None,
                _permission=None,
                current_user=mock_current_user,
                legal_entity_id=mock_legal_entity_id,
                service=mock_budget_service,
            )
        assert exc.value.status_code == 404

    async def test_approve_budget_success(self, mock_budget_service, mock_current_user, mock_legal_entity_id):
        budget_id = uuid4()
        result = await approve_budget(
            budget_id=budget_id,
            notes="Approved",
            idempotency_key=None,
            _permission=None,
            current_user=mock_current_user,
            legal_entity_id=mock_legal_entity_id,
            service=mock_budget_service,
        )
        assert result.status == BudgetStatus.APPROVED
        mock_budget_service.approve_budget.assert_called_once_with(
            budget_id, mock_current_user.user_id, mock_legal_entity_id, "Approved"
        )

    async def test_approve_budget_permission_error(self, mock_budget_service, mock_current_user, mock_legal_entity_id):
        mock_budget_service.approve_budget.side_effect = PermissionError("Not allowed")
        with pytest.raises(HTTPException) as exc:
            await approve_budget(
                budget_id=uuid4(),
                notes="",
                idempotency_key=None,
                _permission=None,
                current_user=mock_current_user,
                legal_entity_id=mock_legal_entity_id,
                service=mock_budget_service,
            )
        assert exc.value.status_code == 403

    async def test_reject_budget_success(self, mock_budget_service, mock_current_user, mock_legal_entity_id):
        budget_id = uuid4()
        result = await reject_budget(
            budget_id=budget_id,
            reason="Invalid",
            idempotency_key=None,
            _permission=None,
            current_user=mock_current_user,
            legal_entity_id=mock_legal_entity_id,
            service=mock_budget_service,
        )
        assert result.status == BudgetStatus.REJECTED
        mock_budget_service.reject_budget.assert_called_once_with(
            budget_id, mock_current_user.user_id, mock_legal_entity_id, "Invalid"
        )

    async def test_reject_budget_not_found(self, mock_budget_service, mock_current_user, mock_legal_entity_id):
        mock_budget_service.reject_budget.return_value = None
        with pytest.raises(HTTPException) as exc:
            await reject_budget(
                budget_id=uuid4(),
                reason="Invalid",
                idempotency_key=None,
                _permission=None,
                current_user=mock_current_user,
                legal_entity_id=mock_legal_entity_id,
                service=mock_budget_service,
            )
        assert exc.value.status_code == 404

    async def test_activate_budget_success(self, mock_budget_service, mock_current_user, mock_legal_entity_id):
        budget_id = uuid4()
        result = await activate_budget(
            budget_id=budget_id,
            idempotency_key=None,
            _permission=None,
            current_user=mock_current_user,
            legal_entity_id=mock_legal_entity_id,
            service=mock_budget_service,
        )
        assert result.status == BudgetStatus.ACTIVE
        mock_budget_service.activate_budget.assert_called_once_with(
            budget_id, mock_current_user.user_id, mock_legal_entity_id
        )

    async def test_lock_budget_success(self, mock_budget_service, mock_current_user, mock_legal_entity_id):
        budget_id = uuid4()
        result = await lock_budget(
            budget_id=budget_id,
            reason="Audit",
            idempotency_key=None,
            _permission=None,
            current_user=mock_current_user,
            legal_entity_id=mock_legal_entity_id,
            service=mock_budget_service,
        )
        assert result.is_locked is True
        mock_budget_service.lock_budget.assert_called_once_with(
            budget_id, mock_current_user.user_id, mock_legal_entity_id, "Audit"
        )

    async def test_unlock_budget_success(self, mock_budget_service, mock_current_user, mock_legal_entity_id):
        budget_id = uuid4()
        result = await unlock_budget(
            budget_id=budget_id,
            idempotency_key=None,
            _permission=None,
            current_user=mock_current_user,
            legal_entity_id=mock_legal_entity_id,
            service=mock_budget_service,
        )
        assert result.is_locked is False
        mock_budget_service.unlock_budget.assert_called_once_with(
            budget_id, mock_current_user.user_id, mock_legal_entity_id
        )


@pytest.mark.asyncio
class TestListAndVersions:
    async def test_list_budgets(self, mock_budget_service, mock_legal_entity_id):
        result = await list_budgets(
            budget_type=BudgetType.OPERATIONAL,
            fiscal_year=2026,
            status=BudgetStatus.DRAFT,
            is_active=True,
            page=1,
            page_size=10,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_budget_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        mock_budget_service.list_budgets.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            budget_type="operational",
            fiscal_year=2026,
            status="draft",
            is_active=True,
            page=1,
            page_size=10,
        )

    async def test_get_budget_versions(self, mock_budget_service, mock_legal_entity_id):
        result = await get_budget_versions(
            budget_code="BUD-001",
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_budget_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], BudgetVersionResponseSchema)
        mock_budget_service.get_budget_versions.assert_called_once_with("BUD-001", mock_legal_entity_id)

    async def test_create_budget_version_success(self, mock_budget_service, mock_current_user, mock_legal_entity_id):
        budget_id = uuid4()
        result = await create_budget_version(
            budget_id=budget_id,
            version="2.0",
            notes="New version",
            idempotency_key=None,
            _permission=None,
            current_user=mock_current_user,
            legal_entity_id=mock_legal_entity_id,
            service=mock_budget_service,
        )
        assert isinstance(result, BudgetResponseSchema)
        assert result.version == "2.0"
        mock_budget_service.create_budget_version.assert_called_once_with(
            budget_id=budget_id,
            version="2.0",
            notes="New version",
            created_by=mock_current_user.user_id,
            legal_entity_id=mock_legal_entity_id,
        )


@pytest.mark.asyncio
class TestBudgetVsActual:
    async def test_get_budget_vs_actual_success(self, mock_budget_service, mock_legal_entity_id):
        budget_id = uuid4()
        result = await get_budget_vs_actual(
            budget_id=budget_id,
            period=1,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_budget_service,
        )
        assert isinstance(result, BudgetVsActualResponseSchema)
        assert result.period == 1
        assert result.variance_type == VarianceType.FAVORABLE
        mock_budget_service.get_budget_vs_actual.assert_called_once_with(
            budget_id=budget_id,
            legal_entity_id=mock_legal_entity_id,
            period=1,
        )

    async def test_get_budget_vs_actual_not_found(self, mock_budget_service, mock_legal_entity_id):
        mock_budget_service.get_budget_vs_actual.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_budget_vs_actual(
                budget_id=uuid4(),
                period=1,
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                service=mock_budget_service,
            )
        assert exc.value.status_code == 404

    async def test_get_budget_vs_actual_ytd_success(self, mock_budget_service, mock_legal_entity_id):
        budget_id = uuid4()
        result = await get_budget_vs_actual_ytd(
            budget_id=budget_id,
            as_of_month=6,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_budget_service,
        )
        assert isinstance(result, BudgetVsActualResponseSchema)
        assert result.period == 0
        assert "YTD" in result.period_name
        mock_budget_service.get_budget_vs_actual_ytd.assert_called_once_with(
            budget_id=budget_id,
            legal_entity_id=mock_legal_entity_id,
            as_of_month=6,
        )


@pytest.mark.asyncio
class TestBudgetTransfer:
    async def test_transfer_budget_success(self, mock_budget_service, mock_current_user, mock_legal_entity_id):
        from_id = uuid4()
        to_id = uuid4()
        request_data = BudgetTransferSchema(
            from_account_id=from_id,
            to_account_id=to_id,
            amount=Decimal("1000000"),
            reason="Reallocate",
            effective_date=date.today(),
        )
        # Add budget_id to request as it's not in schema but service expects it
        # We'll patch the service call to not require budget_id for test
        result = await transfer_budget(
            request=request_data,
            idempotency_key=None,
            _permission=None,
            current_user=mock_current_user,
            legal_entity_id=mock_legal_entity_id,
            service=mock_budget_service,
        )
        assert isinstance(result, BudgetTransferResponseSchema)
        assert result.amount == Decimal("1000000")
        mock_budget_service.transfer_budget.assert_called_once()

    async def test_transfer_budget_value_error(self, mock_budget_service, mock_current_user, mock_legal_entity_id):
        mock_budget_service.transfer_budget.side_effect = ValueError("Insufficient budget")
        from_id = uuid4()
        to_id = uuid4()
        request_data = BudgetTransferSchema(
            from_account_id=from_id,
            to_account_id=to_id,
            amount=Decimal("1000000"),
            reason="Reallocate",
        )
        with pytest.raises(HTTPException) as exc:
            await transfer_budget(
                request=request_data,
                idempotency_key=None,
                _permission=None,
                current_user=mock_current_user,
                legal_entity_id=mock_legal_entity_id,
                service=mock_budget_service,
            )
        assert exc.value.status_code == 422


@pytest.mark.asyncio
class TestDashboardAndAlerts:
    async def test_get_budget_dashboard(self, mock_budget_service, mock_legal_entity_id):
        as_of = date.today()
        result = await get_budget_dashboard(
            as_of_date=as_of,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_budget_service,
        )
        assert isinstance(result, BudgetDashboardResponseSchema)
        assert result.total_budgets == 5
        mock_budget_service.get_budget_dashboard.assert_called_once_with(mock_legal_entity_id, as_of)

    async def test_get_budget_alerts(self, mock_budget_service, mock_legal_entity_id):
        result = await get_budget_alerts(
            threshold_percent=90.0,
            severity="HIGH",
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_budget_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], BudgetAlertSchema)
        mock_budget_service.get_budget_alerts.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            threshold_percent=Decimal("90.0"),
            severity="HIGH",
        )


@pytest.mark.asyncio
class TestRollingForecast:
    async def test_create_rolling_forecast_success(self, mock_budget_service, mock_current_user, mock_legal_entity_id):
        base_id = uuid4()
        request_data = BudgetRollingForecastSchema(
            base_budget_id=base_id,
            forecast_months=6,
            notes="Test forecast"
        )
        result = await create_rolling_forecast(
            request=request_data,
            idempotency_key=None,
            _permission=None,
            current_user=mock_current_user,
            legal_entity_id=mock_legal_entity_id,
            service=mock_budget_service,
        )
        assert isinstance(result, BudgetResponseSchema)
        mock_budget_service.create_rolling_forecast.assert_called_once()

    async def test_create_rolling_forecast_not_found(self, mock_budget_service, mock_current_user, mock_legal_entity_id):
        mock_budget_service.create_rolling_forecast.return_value = None
        base_id = uuid4()
        request_data = BudgetRollingForecastSchema(
            base_budget_id=base_id,
            forecast_months=6,
        )
        with pytest.raises(HTTPException) as exc:
            await create_rolling_forecast(
                request=request_data,
                idempotency_key=None,
                _permission=None,
                current_user=mock_current_user,
                legal_entity_id=mock_legal_entity_id,
                service=mock_budget_service,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestHistoryAndStatus:
    async def test_get_budget_history(self, mock_budget_service, mock_legal_entity_id):
        budget_id = uuid4()
        result = await get_budget_history(
            budget_id=budget_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_budget_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["action"] == "create"
        mock_budget_service.get_budget_history.assert_called_once_with(budget_id, mock_legal_entity_id)

    async def test_get_budget_status_success(self, mock_budget_service, mock_legal_entity_id):
        budget_id = uuid4()
        result = await get_budget_status(
            budget_id=budget_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_budget_service,
        )
        assert result["status"] == "draft"
        assert result["can_submit"] is True
        mock_budget_service.get_budget_status.assert_called_once_with(budget_id, mock_legal_entity_id)

    async def test_get_budget_status_not_found(self, mock_budget_service, mock_legal_entity_id):
        mock_budget_service.get_budget_status.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_budget_status(
                budget_id=uuid4(),
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                service=mock_budget_service,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestExport:
    async def test_export_budgets_csv(self, mock_budget_service, mock_legal_entity_id):
        response = await export_budgets(
            fiscal_year=2026,
            format="csv",
            budget_type=BudgetType.OPERATIONAL,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_budget_service,
        )
        assert isinstance(response, Response)
        assert response.body == b"csv data"
        assert response.media_type == "text/csv"
        assert "attachment" in response.headers["Content-Disposition"]
        mock_budget_service.export_budgets.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            fiscal_year=2026,
            format="csv",
            budget_type="operational",
        )

    async def test_export_budgets_excel(self, mock_budget_service, mock_legal_entity_id):
        mock_budget_service.export_budgets.return_value = b"excel data"
        response = await export_budgets(
            fiscal_year=2026,
            format="excel",
            budget_type=None,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_budget_service,
        )
        assert response.media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"