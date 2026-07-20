# adapters/primary_api/v1/test_fastapi_project_router.py
"""
Comprehensive unit tests for FastAPI Project Router.

Covers:
- IdempotencyManager
- All enum classes
- All request/response schemas (valid & invalid cases)
- All endpoint functions (with mocked service layer)
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from adapters.primary_api.v1.fastapi_project_router import (
    ContractType,
    IdempotencyManager,
    MilestoneCreateSchema,
    ProjectCostResponseSchema,
    ProjectCreateSchema,
    ProjectDashboardResponseSchema,
    ProjectResponseSchema,
    ProjectRevenueResponseSchema,
    ProjectStatus,
    ProjectUpdateSchema,
    RetainerContractCreateSchema,
    RetainerContractResponseSchema,
    RetainerStatus,
    RevenueRecognitionMethod,
    RevenueRecognitionRequestSchema,
    RevenueRecognitionResponseSchema,
    TimeEntryCreateSchema,
    TimeEntryResponseSchema,
    TimeEntryStatus,
    TimeEntryUpdateSchema,
    UtilizationReportSchema,
    activate_project,
    approve_time_entry,
    close_project,
    create_project,
    create_retainer_contract,
    create_time_entry,
    export_projects,
    get_project,
    get_project_by_code,
    get_project_cost,
    get_project_dashboard,
    get_project_history,
    get_project_revenue,
    get_project_status,
    get_utilization_report,
    list_projects,
    list_time_entries,
    recognize_revenue,
    reject_time_entry,
    suspend_project,
    update_project,
    update_time_entry,
)

# =============================================================================
# Helper fixtures
# =============================================================================

@pytest.fixture
def mock_token_payload():
    return MagicMock(user_id=uuid4())


@pytest.fixture
def mock_legal_entity_id():
    return uuid4()


@pytest.fixture
def mock_project_service():
    svc = AsyncMock()

    # Project responses
    svc.create_project.return_value = MagicMock(
        id=uuid4(),
        project_code="PROJ-001",
        project_name="Test Project",
        customer_id=uuid4(),
        customer_name="Customer A",
        customer_code="CUST-001",
        start_date=date.today(),
        end_date=None,
        status="draft",
        contract_type="fixed_price",
        contract_value=Decimal("100000"),
        currency_code="IDR",
        budget_total=Decimal("80000"),
        cost_to_date=Decimal("0"),
        revenue_to_date=Decimal("0"),
        recognized_revenue_to_date=Decimal("0"),
        unbilled_revenue=Decimal("0"),
        profit_to_date=Decimal("0"),
        profit_margin_percent=0.0,
        completion_percent=0.0,
        revenue_recognition_method="percentage_completion",
        billing_cycle_days=30,
        manager_employee_id=uuid4(),
        manager_name="Manager A",
        notes="Test notes",
        tags=["tag1", "tag2"],
        is_locked=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        created_by=uuid4(),
        created_by_name="Admin",
        version=1,
    )
    svc.get_project_by_id.return_value = svc.create_project.return_value
    svc.get_project_by_code.return_value = svc.create_project.return_value
    svc.update_project.return_value = svc.create_project.return_value
    svc.close_project.return_value = MagicMock(
        project_code="PROJ-001",
        status="closed",
    )
    svc.delete_project.return_value = MagicMock(
        project_code="PROJ-001",
        status="deleted",
    )
    svc.activate_project.return_value = svc.create_project.return_value
    svc.suspend_project.return_value = svc.create_project.return_value
    svc.list_projects.return_value = MagicMock(
        items=[svc.create_project.return_value],
        total=1,
        page=1,
        page_size=20,
    )

    # Cost & revenue
    svc.get_project_cost.return_value = MagicMock(
        project_id=uuid4(),
        project_code="PROJ-001",
        project_name="Test Project",
        labor_cost=Decimal("10000"),
        material_cost=Decimal("5000"),
        equipment_cost=Decimal("2000"),
        subcontractor_cost=Decimal("3000"),
        overhead_cost=Decimal("1000"),
        other_cost=Decimal("500"),
        total_cost=Decimal("21500"),
        budget_variance=Decimal("58500"),
        cost_by_category={"labor": 10000, "material": 5000},
        cost_by_period={"2025-01": 10000, "2025-02": 11500},
    )
    svc.get_project_revenue.return_value = MagicMock(
        project_id=uuid4(),
        project_code="PROJ-001",
        project_name="Test Project",
        contract_value=Decimal("100000"),
        revenue_recognized=Decimal("50000"),
        revenue_to_date=Decimal("50000"),
        unbilled_revenue=Decimal("20000"),
        invoiced_amount=Decimal("30000"),
        paid_amount=Decimal("25000"),
        outstanding_amount=Decimal("5000"),
        recognition_method="percentage_completion",
        recognition_percentage=50.0,
        notes="Test",
    )

    # Time entries
    svc.create_time_entry.return_value = MagicMock(
        id=uuid4(),
        time_entry_number="TE-001",
        employee_id=uuid4(),
        employee_name="Employee A",
        project_id=uuid4(),
        project_code="PROJ-001",
        project_name="Test Project",
        work_date=date.today(),
        hours=Decimal("8"),
        hourly_rate=Decimal("100000"),
        total_amount=Decimal("800000"),
        description="Development work",
        is_billable=True,
        task_code="TASK-001",
        status="draft",
        is_billed=False,
        billed_invoice_id=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        created_by=uuid4(),
        created_by_name="Admin",
        approved_at=None,
        approved_by=None,
        approved_by_name=None,
        rejected_at=None,
        rejection_reason=None,
        version=1,
    )
    svc.list_time_entries.return_value = MagicMock(
        items=[svc.create_time_entry.return_value],
        total=1,
        page=1,
        page_size=50,
    )
    svc.update_time_entry.return_value = svc.create_time_entry.return_value
    svc.approve_time_entry.return_value = svc.create_time_entry.return_value
    svc.reject_time_entry.return_value = svc.create_time_entry.return_value

    # Retainer
    svc.create_retainer_contract.return_value = MagicMock(
        id=uuid4(),
        customer_id=uuid4(),
        customer_name="Customer A",
        customer_code="CUST-001",
        contract_number="RET-001",
        monthly_fee=Decimal("10000000"),
        start_date=date.today(),
        end_date=None,
        status="active",
        max_hours_per_month=Decimal("160"),
        hourly_rate_overtime=Decimal("150000"),
        total_invoiced=Decimal("20000000"),
        total_hours_used=Decimal("120"),
        remaining_hours=Decimal("40"),
        notes="Test",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        created_by=uuid4(),
        created_by_name="Admin",
        version=1,
    )

    # Revenue recognition
    svc.recognize_revenue.return_value = [
        MagicMock(
            id=uuid4(),
            project_id=uuid4(),
            project_name="Test Project",
            previous_recognized=Decimal("40000"),
            current_recognized=Decimal("10000"),
            total_recognized=Decimal("50000"),
            remaining_revenue=Decimal("50000"),
            journal_id=uuid4(),
            status="posted",
            created_at=datetime.now(UTC),
        )
    ]

    # Dashboard
    svc.get_project_dashboard.return_value = MagicMock(
        total_projects=10,
        active_projects=5,
        on_hold_projects=2,
        completed_projects=3,
        total_budget=Decimal("1000000"),
        total_cost_to_date=Decimal("400000"),
        total_revenue_recognized=Decimal("600000"),
        total_profit=Decimal("200000"),
        overall_profit_margin=20.0,
        average_completion_percent=45.0,
        projects_by_status={"active": 5, "on_hold": 2, "completed": 3},
        projects_by_customer=[{"customer": "A", "count": 3, "revenue": 300000}],
        top_projects_by_revenue=[{"project": "P1", "revenue": 100000}],
        top_projects_by_cost=[{"project": "P1", "cost": 80000}],
    )

    # Utilization
    svc.get_utilization_report.return_value = MagicMock(
        total_employees=10,
        total_available_hours=Decimal("1600"),
        total_billed_hours=Decimal("1200"),
        total_non_billed_hours=Decimal("400"),
        total_utilization_rate=75.0,
        by_employee=[{"employee": "E1", "billed": 120, "available": 160}],
        by_project=[{"project": "P1", "hours": 200}],
    )

    # History & status
    svc.get_project_history.return_value = []
    svc.get_project_status.return_value = MagicMock(
        project_code="PROJ-001",
        status="active",
        status_description="Project is active",
        can_activate=False,
        can_suspend=True,
        can_close=True,
        can_cancel=True,
        is_locked=False,
        is_archived=False,
        completion_percent=50.0,
        on_track=True,
        days_remaining=30,
        budget_remaining=Decimal("40000"),
    )

    # Export
    svc.export_projects.return_value = b"csv data"

    return svc


# =============================================================================
# Tests for IdempotencyManager
# =============================================================================

class TestIdempotencyManager:
    def test_initialization(self):
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

    def test_cache_serializes_complex_types(self):
        manager = IdempotencyManager()
        data = {"date": date.today(), "decimal": Decimal("10.50")}
        manager.cache_result("key2", "method2", data)
        cached = manager.get_cached_result("key2", "method2")
        assert cached is not None
        assert "date" in cached

    def test_cache_expiration(self):
        manager = IdempotencyManager()
        manager._ttl_seconds = 0
        manager.cache_result("key3", "method3", {"foo": "bar"})
        cached = manager.get_cached_result("key3", "method3")
        assert cached is None

    def test_key_generation_deterministic(self):
        manager = IdempotencyManager()
        key1 = manager._get_key("abc", "create_project")
        key2 = manager._get_key("abc", "create_project")
        key3 = manager._get_key("abc", "update_project")
        assert key1 == key2
        assert key1 != key3


# =============================================================================
# Tests for Enums
# =============================================================================

class TestEnums:
    def test_project_status_values(self):
        assert ProjectStatus.DRAFT.value == "draft"
        assert ProjectStatus.ACTIVE.value == "active"
        assert ProjectStatus.ON_HOLD.value == "on_hold"
        assert ProjectStatus.IN_PROGRESS.value == "in_progress"
        assert ProjectStatus.COMPLETED.value == "completed"
        assert ProjectStatus.CANCELLED.value == "cancelled"
        assert ProjectStatus.CLOSED.value == "closed"
        assert ProjectStatus.ARCHIVED.value == "archived"
        assert ProjectStatus.LOCKED.value == "locked"

    def test_contract_type_values(self):
        assert ContractType.FIXED_PRICE.value == "fixed_price"
        assert ContractType.TIME_MATERIAL.value == "time_material"
        assert ContractType.RETAINER.value == "retainer"
        assert ContractType.COST_PLUS.value == "cost_plus"
        assert ContractType.MILESTONE.value == "milestone"

    def test_revenue_recognition_method_values(self):
        assert RevenueRecognitionMethod.PERCENTAGE_COMPLETION.value == "percentage_completion"
        assert RevenueRecognitionMethod.COMPLETED_CONTRACT.value == "completed_contract"
        assert RevenueRecognitionMethod.STRAIGHT_LINE.value == "straight_line"
        assert RevenueRecognitionMethod.MILESTONE.value == "milestone"
        assert RevenueRecognitionMethod.INPUT_METHOD.value == "input_method"
        assert RevenueRecognitionMethod.OUTPUT_METHOD.value == "output_method"

    def test_time_entry_status_values(self):
        assert TimeEntryStatus.DRAFT.value == "draft"
        assert TimeEntryStatus.SUBMITTED.value == "submitted"
        assert TimeEntryStatus.APPROVED.value == "approved"
        assert TimeEntryStatus.REJECTED.value == "rejected"
        assert TimeEntryStatus.BILLED.value == "billed"
        assert TimeEntryStatus.CANCELLED.value == "cancelled"

    def test_retainer_status_values(self):
        assert RetainerStatus.ACTIVE.value == "active"
        assert RetainerStatus.SUSPENDED.value == "suspended"
        assert RetainerStatus.TERMINATED.value == "terminated"
        assert RetainerStatus.EXPIRED.value == "expired"
        assert RetainerStatus.DRAFT.value == "draft"


# =============================================================================
# Tests for Schemas (validation)
# =============================================================================

class TestProjectCreateSchema:
    def test_valid_schema(self):
        data = {
            "project_code": "PROJ-001",
            "project_name": "Test Project",
            "customer_id": uuid4(),
            "start_date": date.today(),
            "end_date": None,
            "contract_type": ContractType.FIXED_PRICE,
            "contract_value": Decimal("100000"),
            "currency_code": "IDR",
            "budget_total": Decimal("80000"),
            "manager_employee_id": uuid4(),
            "revenue_recognition_method": RevenueRecognitionMethod.PERCENTAGE_COMPLETION,
            "billing_cycle_days": 30,
            "notes": "Test",
            "tags": ["tag1"],
        }
        schema = ProjectCreateSchema(**data)
        assert schema.project_code == "PROJ-001"
        assert schema.contract_value == Decimal("100000")

    def test_project_code_uppercase(self):
        schema = ProjectCreateSchema(
            project_code="proj-001",
            project_name="Test",
            customer_id=uuid4(),
            start_date=date.today(),
            contract_type=ContractType.FIXED_PRICE,
            contract_value=Decimal("1000"),
        )
        assert schema.project_code == "PROJ-001"

    def test_end_date_after_start(self):
        with pytest.raises(ValueError, match="End date must be after start date"):
            ProjectCreateSchema(
                project_code="PROJ-001",
                project_name="Test",
                customer_id=uuid4(),
                start_date=date(2025, 1, 10),
                end_date=date(2025, 1, 5),
                contract_type=ContractType.FIXED_PRICE,
                contract_value=Decimal("1000"),
            )

    def test_contract_value_positive(self):
        with pytest.raises(ValueError):
            ProjectCreateSchema(
                project_code="PROJ-001",
                project_name="Test",
                customer_id=uuid4(),
                start_date=date.today(),
                contract_type=ContractType.FIXED_PRICE,
                contract_value=Decimal("-1000"),
            )


class TestTimeEntryCreateSchema:
    def test_valid_schema(self):
        data = {
            "project_id": uuid4(),
            "work_date": date.today(),
            "hours": Decimal("8"),
            "hourly_rate": Decimal("100000"),
            "description": "Development",
            "is_billable": True,
            "task_code": "TASK-001",
        }
        schema = TimeEntryCreateSchema(**data)
        assert schema.hours == Decimal("8")
        assert schema.total_amount == Decimal("800000")

    def test_hours_positive(self):
        with pytest.raises(ValueError):
            TimeEntryCreateSchema(
                project_id=uuid4(),
                hours=Decimal("0"),
                hourly_rate=Decimal("100000"),
            )


class TestRetainerContractCreateSchema:
    def test_valid_schema(self):
        data = {
            "customer_id": uuid4(),
            "contract_number": "RET-001",
            "monthly_fee": Decimal("10000000"),
            "start_date": date.today(),
            "end_date": None,
            "max_hours_per_month": Decimal("160"),
            "hourly_rate_overtime": Decimal("150000"),
            "notes": "Test",
        }
        schema = RetainerContractCreateSchema(**data)
        assert schema.contract_number == "RET-001"
        assert schema.monthly_fee == Decimal("10000000")

    def test_end_date_after_start(self):
        with pytest.raises(ValueError, match="End date must be after start date"):
            RetainerContractCreateSchema(
                customer_id=uuid4(),
                contract_number="RET-001",
                monthly_fee=Decimal("10000"),
                start_date=date(2025, 1, 10),
                end_date=date(2025, 1, 5),
            )


class TestMilestoneCreateSchema:
    def test_valid_schema(self):
        data = {
            "milestone_name": "Phase 1",
            "milestone_order": 1,
            "percentage": Decimal("25.00"),
            "amount": Decimal("25000"),
            "due_date": date.today(),
            "description": "First phase",
        }
        schema = MilestoneCreateSchema(**data)
        assert schema.percentage == Decimal("25.00")
        assert schema.milestone_order == 1


# =============================================================================
# Tests for Endpoint Functions (with mocks)
# =============================================================================

@pytest.mark.asyncio
class TestProjectCRUD:
    async def test_create_project_success(self, mock_project_service, mock_token_payload, mock_legal_entity_id):
        request = ProjectCreateSchema(
            project_code="PROJ-001",
            project_name="Test Project",
            customer_id=uuid4(),
            start_date=date.today(),
            contract_type=ContractType.FIXED_PRICE,
            contract_value=Decimal("100000"),
        )
        result = await create_project(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_project_service,
        )
        assert isinstance(result, ProjectResponseSchema)
        assert result.project_code == "PROJ-001"
        mock_project_service.create_project.assert_called_once()

    async def test_create_project_idempotency(self, mock_project_service, mock_token_payload, mock_legal_entity_id):
        request = ProjectCreateSchema(
            project_code="PROJ-001",
            project_name="Test",
            customer_id=uuid4(),
            start_date=date.today(),
            contract_type=ContractType.FIXED_PRICE,
            contract_value=Decimal("1000"),
        )
        with patch("adapters.primary_api.v1.fastapi_project_router._idempotency_manager") as mock_im:
            mock_im.get_cached_result.return_value = {
                "id": str(uuid4()),
                "project_code": "PROJ-001",
                "project_name": "Test",
                "customer_id": str(uuid4()),
                "customer_name": None,
                "customer_code": None,
                "start_date": date.today().isoformat(),
                "end_date": None,
                "status": "draft",
                "contract_type": "fixed_price",
                "contract_value": "1000.00",
                "currency_code": "IDR",
                "budget_total": "0.00",
                "cost_to_date": "0.00",
                "revenue_to_date": "0.00",
                "recognized_revenue_to_date": "0.00",
                "unbilled_revenue": "0.00",
                "profit_to_date": "0.00",
                "profit_margin_percent": 0.0,
                "completion_percent": 0.0,
                "revenue_recognition_method": "percentage_completion",
                "billing_cycle_days": 30,
                "manager_employee_id": None,
                "manager_name": None,
                "notes": None,
                "tags": None,
                "is_locked": False,
                "created_at": datetime.now(UTC).isoformat(),
                "updated_at": datetime.now(UTC).isoformat(),
                "created_by": str(uuid4()),
                "created_by_name": None,
                "version": 1,
            }
            result = await create_project(
                request=request,
                idempotency_key="abc123",
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                service=mock_project_service,
            )
            assert isinstance(result, ProjectResponseSchema)
            mock_project_service.create_project.assert_not_called()

    async def test_get_project_success(self, mock_project_service, mock_legal_entity_id):
        project_id = uuid4()
        result = await get_project(
            project_id=project_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_project_service,
        )
        assert isinstance(result, ProjectResponseSchema)
        mock_project_service.get_project_by_id.assert_called_once_with(project_id, mock_legal_entity_id)

    async def test_get_project_not_found(self, mock_project_service, mock_legal_entity_id):
        mock_project_service.get_project_by_id.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_project(
                project_id=uuid4(),
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                service=mock_project_service,
            )
        assert exc.value.status_code == 404

    async def test_get_project_by_code_success(self, mock_project_service, mock_legal_entity_id):
        result = await get_project_by_code(
            project_code="PROJ-001",
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_project_service,
        )
        assert isinstance(result, ProjectResponseSchema)
        mock_project_service.get_project_by_code.assert_called_once_with("PROJ-001", mock_legal_entity_id)

    async def test_get_project_by_code_not_found(self, mock_project_service, mock_legal_entity_id):
        mock_project_service.get_project_by_code.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_project_by_code(
                project_code="UNKNOWN",
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                service=mock_project_service,
            )
        assert exc.value.status_code == 404

    async def test_update_project_success(self, mock_project_service, mock_token_payload, mock_legal_entity_id):
        project_id = uuid4()
        request = ProjectUpdateSchema(project_name="Updated Name")
        result = await update_project(
            project_id=project_id,
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_project_service,
        )
        assert isinstance(result, ProjectResponseSchema)
        mock_project_service.update_project.assert_called_once()

    async def test_update_project_not_found(self, mock_project_service, mock_token_payload, mock_legal_entity_id):
        mock_project_service.update_project.return_value = None
        with pytest.raises(HTTPException) as exc:
            await update_project(
                project_id=uuid4(),
                request=ProjectUpdateSchema(),
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                service=mock_project_service,
            )
        assert exc.value.status_code == 404

    async def test_close_project(self, mock_project_service, mock_token_payload, mock_legal_entity_id):
        project_id = uuid4()
        result = await close_project(
            project_id=project_id,
            permanent=False,
            reason="Done",
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_project_service,
        )
        assert result["action"] == "closed"
        mock_project_service.close_project.assert_called_once_with(
            project_id, mock_token_payload.user_id, mock_legal_entity_id, "Done"
        )

    async def test_delete_project(self, mock_project_service, mock_token_payload, mock_legal_entity_id):
        project_id = uuid4()
        result = await close_project(
            project_id=project_id,
            permanent=True,
            reason="Delete",
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_project_service,
        )
        assert result["action"] == "deleted"
        mock_project_service.delete_project.assert_called_once_with(
            project_id, mock_token_payload.user_id, mock_legal_entity_id, "Delete"
        )

    async def test_activate_project(self, mock_project_service, mock_token_payload, mock_legal_entity_id):
        project_id = uuid4()
        result = await activate_project(
            project_id=project_id,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_project_service,
        )
        assert isinstance(result, ProjectResponseSchema)
        mock_project_service.activate_project.assert_called_once_with(
            project_id, mock_token_payload.user_id, mock_legal_entity_id
        )

    async def test_suspend_project(self, mock_project_service, mock_token_payload, mock_legal_entity_id):
        project_id = uuid4()
        result = await suspend_project(
            project_id=project_id,
            reason="Budget issue",
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_project_service,
        )
        assert isinstance(result, ProjectResponseSchema)
        mock_project_service.suspend_project.assert_called_once_with(
            project_id, mock_token_payload.user_id, mock_legal_entity_id, "Budget issue"
        )

    async def test_list_projects(self, mock_project_service, mock_legal_entity_id):
        result = await list_projects(
            customer_id=None,
            status=ProjectStatus.ACTIVE,
            manager_id=None,
            start_date_from=None,
            start_date_to=None,
            search="test",
            page=1,
            page_size=20,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_project_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], ProjectResponseSchema)
        mock_project_service.list_projects.assert_called_once()


@pytest.mark.asyncio
class TestProjectCostAndRevenue:
    async def test_get_project_cost_success(self, mock_project_service, mock_legal_entity_id):
        project_id = uuid4()
        as_of = date.today()
        result = await get_project_cost(
            project_id=project_id,
            as_of_date=as_of,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_project_service,
        )
        assert isinstance(result, ProjectCostResponseSchema)
        assert result.total_cost == Decimal("21500")
        mock_project_service.get_project_cost.assert_called_once_with(
            project_id, mock_legal_entity_id, as_of
        )

    async def test_get_project_cost_not_found(self, mock_project_service, mock_legal_entity_id):
        mock_project_service.get_project_cost.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_project_cost(
                project_id=uuid4(),
                as_of_date=date.today(),
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                service=mock_project_service,
            )
        assert exc.value.status_code == 404

    async def test_get_project_revenue_success(self, mock_project_service, mock_legal_entity_id):
        project_id = uuid4()
        start = date(2025, 1, 1)
        end = date(2025, 1, 31)
        result = await get_project_revenue(
            project_id=project_id,
            period_start=start,
            period_end=end,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_project_service,
        )
        assert isinstance(result, ProjectRevenueResponseSchema)
        assert result.contract_value == Decimal("100000")
        mock_project_service.get_project_revenue.assert_called_once_with(
            project_id=project_id,
            legal_entity_id=mock_legal_entity_id,
            period_start=start,
            period_end=end,
        )


@pytest.mark.asyncio
class TestTimeEntries:
    async def test_create_time_entry_success(self, mock_project_service, mock_token_payload, mock_legal_entity_id):
        request = TimeEntryCreateSchema(
            project_id=uuid4(),
            hours=Decimal("8"),
            hourly_rate=Decimal("100000"),
            is_billable=True,
        )
        result = await create_time_entry(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_project_service,
        )
        assert isinstance(result, TimeEntryResponseSchema)
        assert result.total_amount == Decimal("800000")
        mock_project_service.create_time_entry.assert_called_once()

    async def test_list_time_entries(self, mock_project_service, mock_legal_entity_id):
        result = await list_time_entries(
            project_id=None,
            employee_id=None,
            start_date=None,
            end_date=None,
            status=TimeEntryStatus.DRAFT,
            is_billed=None,
            page=1,
            page_size=50,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_project_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], TimeEntryResponseSchema)
        mock_project_service.list_time_entries.assert_called_once()

    async def test_update_time_entry_success(self, mock_project_service, mock_token_payload, mock_legal_entity_id):
        te_id = uuid4()
        request = TimeEntryUpdateSchema(hours=Decimal("10"))
        result = await update_time_entry(
            time_entry_id=te_id,
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_project_service,
        )
        assert isinstance(result, TimeEntryResponseSchema)
        mock_project_service.update_time_entry.assert_called_once()

    async def test_approve_time_entry_success(self, mock_project_service, mock_token_payload, mock_legal_entity_id):
        te_id = uuid4()
        result = await approve_time_entry(
            time_entry_id=te_id,
            notes="Approved",
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_project_service,
        )
        assert isinstance(result, TimeEntryResponseSchema)
        mock_project_service.approve_time_entry.assert_called_once_with(
            te_id, mock_token_payload.user_id, mock_legal_entity_id, "Approved"
        )

    async def test_reject_time_entry_success(self, mock_project_service, mock_token_payload, mock_legal_entity_id):
        te_id = uuid4()
        result = await reject_time_entry(
            time_entry_id=te_id,
            reason="Invalid",
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_project_service,
        )
        assert isinstance(result, TimeEntryResponseSchema)
        mock_project_service.reject_time_entry.assert_called_once_with(
            te_id, mock_token_payload.user_id, mock_legal_entity_id, "Invalid"
        )


@pytest.mark.asyncio
class TestRetainerContracts:
    async def test_create_retainer_success(self, mock_project_service, mock_token_payload, mock_legal_entity_id):
        request = RetainerContractCreateSchema(
            customer_id=uuid4(),
            contract_number="RET-001",
            monthly_fee=Decimal("10000000"),
            start_date=date.today(),
        )
        result = await create_retainer_contract(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_project_service,
        )
        assert isinstance(result, RetainerContractResponseSchema)
        assert result.contract_number == "RET-001"
        mock_project_service.create_retainer_contract.assert_called_once()


@pytest.mark.asyncio
class TestRevenueRecognition:
    async def test_recognize_revenue_success(self, mock_project_service, mock_token_payload, mock_legal_entity_id):
        request = RevenueRecognitionRequestSchema(
            period_end_date=date.today(),
            calculate_only=False,
        )
        result = await recognize_revenue(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_project_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], RevenueRecognitionResponseSchema)
        mock_project_service.recognize_revenue.assert_called_once()


@pytest.mark.asyncio
class TestDashboardAndReports:
    async def test_get_dashboard(self, mock_project_service, mock_legal_entity_id):
        as_of = date.today()
        result = await get_project_dashboard(
            as_of_date=as_of,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_project_service,
        )
        assert isinstance(result, ProjectDashboardResponseSchema)
        assert result.total_projects == 10
        assert result.overall_profit_margin == 20.0
        mock_project_service.get_project_dashboard.assert_called_once_with(mock_legal_entity_id, as_of)

    async def test_get_utilization_report(self, mock_project_service, mock_legal_entity_id):
        start = date(2025, 1, 1)
        end = date(2025, 1, 31)
        result = await get_utilization_report(
            period_start=start,
            period_end=end,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_project_service,
        )
        assert isinstance(result, UtilizationReportSchema)
        assert result.total_utilization_rate == 75.0
        mock_project_service.get_utilization_report.assert_called_once_with(
            mock_legal_entity_id, start, end
        )


@pytest.mark.asyncio
class TestHistoryAndStatus:
    async def test_get_project_history(self, mock_project_service, mock_legal_entity_id):
        project_id = uuid4()
        result = await get_project_history(
            project_id=project_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_project_service,
        )
        assert isinstance(result, list)
        mock_project_service.get_project_history.assert_called_once_with(project_id, mock_legal_entity_id)

    async def test_get_project_status_success(self, mock_project_service, mock_legal_entity_id):
        project_id = uuid4()
        result = await get_project_status(
            project_id=project_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_project_service,
        )
        assert result["status"] == "active"
        assert result["can_suspend"] is True
        mock_project_service.get_project_status.assert_called_once_with(project_id, mock_legal_entity_id)

    async def test_get_project_status_not_found(self, mock_project_service, mock_legal_entity_id):
        mock_project_service.get_project_status.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_project_status(
                project_id=uuid4(),
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                service=mock_project_service,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestExport:
    async def test_export_projects(self, mock_project_service, mock_legal_entity_id):
        response = await export_projects(
            format="csv",
            status=ProjectStatus.ACTIVE,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_project_service,
        )
        assert response.body == b"csv data"
        assert response.media_type == "text/csv"
        assert "attachment" in response.headers["Content-Disposition"]
        mock_project_service.export_projects.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            format="csv",
            status="active",
        )
