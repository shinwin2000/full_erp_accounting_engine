# adapters/primary_api/v1/test_fastapi_maintenance_router.py
"""
Comprehensive unit tests for FastAPI Maintenance Router.

Covers:
- IdempotencyManager
- All enum classes
- All request/response schemas (valid & invalid cases)
- Health endpoints (ping, health, info)
- All endpoint functions (with mocked service layer)
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from adapters.primary_api.v1.fastapi_maintenance_router import (
    IdempotencyManager,
    MaintenanceAssetCreateSchema,
    MaintenanceAssetResponseSchema,
    MaintenanceAssetStatus,
    MaintenanceAssetUpdateSchema,
    MaintenanceCostSummarySchema,
    MaintenancePriority,
    MaintenanceScheduleCreateSchema,
    MaintenanceScheduleResponseSchema,
    MaintenanceScheduleUpdateSchema,
    MaintenanceType,
    ScheduleFrequency,
    SparePartUsageResponseSchema,
    SparePartUsageSchema,
    SparePartUsageStatus,
    WorkOrderMaintenanceCreateSchema,
    WorkOrderMaintenanceResponseSchema,
    WorkOrderMaintenanceUpdateSchema,
    WorkOrderStatus,
    cancel_maintenance_work_order,
    complete_maintenance_work_order,
    create_maintenance_asset,
    create_maintenance_schedule,
    create_maintenance_work_order,
    deactivate_maintenance_asset,
    deactivate_maintenance_schedule,
    export_maintenance_work_orders,
    get_maintenance_asset,
    get_maintenance_cost_summary,
    get_maintenance_schedule,
    get_maintenance_work_order,
    health,
    info,
    list_maintenance_assets,
    list_maintenance_schedules,
    list_maintenance_work_orders,
    ping,
    record_spare_parts_usage,
    update_maintenance_asset,
    update_maintenance_schedule,
    update_maintenance_work_order,
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
def mock_maintenance_service():
    svc = AsyncMock()

    # Asset responses
    svc.create_maintenance_asset.return_value = MagicMock(
        id=uuid4(),
        asset_code="MA-001",
        asset_name="Test Asset",
        asset_category="Equipment",
        location="Warehouse A",
        serial_number="SN123",
        manufacturer="Test Manufacturer",
        model="TM-100",
        purchase_date=date.today(),
        warranty_expiry_date=None,
        maintenance_interval_days=30,
        status="active",
        is_active=True,
        is_locked=False,
        notes="Test notes",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        created_by=uuid4(),
        created_by_name="Admin",
        version=1,
    )
    svc.get_maintenance_asset_by_id.return_value = svc.create_maintenance_asset.return_value
    svc.list_maintenance_assets.return_value = [svc.create_maintenance_asset.return_value]
    svc.update_maintenance_asset.return_value = svc.create_maintenance_asset.return_value
    svc.deactivate_maintenance_asset.return_value = MagicMock(
        asset_code="MA-001",
        status="inactive",
    )

    # Schedule responses
    svc.create_maintenance_schedule.return_value = MagicMock(
        id=uuid4(),
        asset_id=uuid4(),
        asset_code="MA-001",
        asset_name="Test Asset",
        schedule_code="SCH-001",
        schedule_name="Monthly Check",
        maintenance_type="preventive",
        frequency="monthly",
        custom_interval_days=None,
        start_date=date.today(),
        end_date=None,
        estimated_duration_hours=Decimal("2.0"),
        assigned_team="Team Alpha",
        status="active",
        is_active=True,
        next_due_date=date.today(),
        notes="Test",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        created_by=uuid4(),
        created_by_name="Admin",
        version=1,
    )
    svc.get_maintenance_schedule_by_id.return_value = svc.create_maintenance_schedule.return_value
    svc.list_maintenance_schedules.return_value = [svc.create_maintenance_schedule.return_value]
    svc.update_maintenance_schedule.return_value = svc.create_maintenance_schedule.return_value
    svc.deactivate_maintenance_schedule.return_value = MagicMock(
        schedule_code="SCH-001",
        status="inactive",
    )

    # Work Order responses
    svc.create_maintenance_work_order.return_value = MagicMock(
        id=uuid4(),
        wo_number="WO-001",
        asset_id=uuid4(),
        asset_code="MA-001",
        asset_name="Test Asset",
        schedule_id=uuid4(),
        maintenance_type="preventive",
        priority="medium",
        description="Routine check",
        requested_by=uuid4(),
        requested_by_name="Requester A",
        assigned_technician_id=None,
        assigned_technician_name=None,
        planned_start_date=date.today(),
        planned_end_date=date.today(),
        actual_start_date=None,
        actual_end_date=None,
        estimated_cost=Decimal("500.00"),
        actual_cost=Decimal("0"),
        status="draft",
        is_locked=False,
        notes="Test",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        created_by=uuid4(),
        created_by_name="Admin",
        completed_at=None,
        completed_by=None,
        version=1,
    )
    svc.get_maintenance_work_order_by_id.return_value = svc.create_maintenance_work_order.return_value
    svc.list_maintenance_work_orders.return_value = MagicMock(
        items=[svc.create_maintenance_work_order.return_value],
        total=1,
        page=1,
        page_size=20,
    )
    svc.update_maintenance_work_order.return_value = svc.create_maintenance_work_order.return_value
    svc.complete_maintenance_work_order.return_value = svc.create_maintenance_work_order.return_value
    svc.cancel_maintenance_work_order.return_value = MagicMock(
        wo_number="WO-001",
        status="cancelled",
    )

    # Spare parts
    svc.record_spare_parts_usage.return_value = MagicMock(
        id=uuid4(),
        item_id=uuid4(),
        item_code="SP-001",
        item_name="Bearing",
        quantity=Decimal("2"),
        unit_cost=Decimal("150.00"),
        total_cost=Decimal("300.00"),
        work_order_id=uuid4(),
        work_order_number="WO-001",
        issued_date=date.today(),
        status="issued",
        notes="Test",
        created_at=datetime.now(UTC),
        created_by=uuid4(),
        created_by_name="Admin",
    )

    # Cost summary
    svc.get_maintenance_cost_summary.return_value = MagicMock(
        total_maintenance_cost=Decimal("5000"),
        preventive_cost=Decimal("2000"),
        corrective_cost=Decimal("1500"),
        emergency_cost=Decimal("1000"),
        labor_cost=Decimal("2500"),
        spare_parts_cost=Decimal("2000"),
        other_cost=Decimal("500"),
        by_asset=[{"asset": "MA-001", "cost": 3000}],
        by_work_order=[{"wo": "WO-001", "cost": 500}],
    )

    # Export
    svc.export_maintenance_work_orders.return_value = b"csv data"

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
        key1 = manager._get_key("abc", "create_asset")
        key2 = manager._get_key("abc", "create_asset")
        key3 = manager._get_key("abc", "update_asset")
        assert key1 == key2
        assert key1 != key3


# =============================================================================
# Tests for Enums
# =============================================================================

class TestEnums:
    def test_maintenance_asset_status_values(self):
        assert MaintenanceAssetStatus.ACTIVE.value == "active"
        assert MaintenanceAssetStatus.INACTIVE.value == "inactive"
        assert MaintenanceAssetStatus.UNDER_MAINTENANCE.value == "under_maintenance"
        assert MaintenanceAssetStatus.OUT_OF_SERVICE.value == "out_of_service"
        assert MaintenanceAssetStatus.OBSOLETE.value == "obsolete"
        assert MaintenanceAssetStatus.ARCHIVED.value == "archived"

    def test_maintenance_type_values(self):
        assert MaintenanceType.PREVENTIVE.value == "preventive"
        assert MaintenanceType.CORRECTIVE.value == "corrective"
        assert MaintenanceType.PREDICTIVE.value == "predictive"
        assert MaintenanceType.EMERGENCY.value == "emergency"
        assert MaintenanceType.ROUTINE.value == "routine"

    def test_maintenance_priority_values(self):
        assert MaintenancePriority.CRITICAL.value == "critical"
        assert MaintenancePriority.HIGH.value == "high"
        assert MaintenancePriority.MEDIUM.value == "medium"
        assert MaintenancePriority.LOW.value == "low"

    def test_work_order_status_values(self):
        assert WorkOrderStatus.DRAFT.value == "draft"
        assert WorkOrderStatus.PLANNED.value == "planned"
        assert WorkOrderStatus.ASSIGNED.value == "assigned"
        assert WorkOrderStatus.IN_PROGRESS.value == "in_progress"
        assert WorkOrderStatus.ON_HOLD.value == "on_hold"
        assert WorkOrderStatus.COMPLETED.value == "completed"
        assert WorkOrderStatus.CANCELLED.value == "cancelled"
        assert WorkOrderStatus.CLOSED.value == "closed"
        assert WorkOrderStatus.LOCKED.value == "locked"
        assert WorkOrderStatus.ARCHIVED.value == "archived"

    def test_schedule_frequency_values(self):
        assert ScheduleFrequency.DAILY.value == "daily"
        assert ScheduleFrequency.WEEKLY.value == "weekly"
        assert ScheduleFrequency.BIWEEKLY.value == "biweekly"
        assert ScheduleFrequency.MONTHLY.value == "monthly"
        assert ScheduleFrequency.QUARTERLY.value == "quarterly"
        assert ScheduleFrequency.SEMI_ANNUAL.value == "semi_annual"
        assert ScheduleFrequency.ANNUAL.value == "annual"
        assert ScheduleFrequency.CUSTOM.value == "custom"

    def test_spare_part_usage_status_values(self):
        assert SparePartUsageStatus.REQUESTED.value == "requested"
        assert SparePartUsageStatus.ISSUED.value == "issued"
        assert SparePartUsageStatus.USED.value == "used"
        assert SparePartUsageStatus.RETURNED.value == "returned"


# =============================================================================
# Tests for Schemas (validation)
# =============================================================================

class TestMaintenanceAssetCreateSchema:
    def test_valid_schema(self):
        data = {
            "asset_code": "MA-001",
            "asset_name": "Test Asset",
            "asset_category": "Equipment",
            "location": "Warehouse A",
            "serial_number": "SN123",
            "manufacturer": "Test Corp",
            "model": "TM-100",
            "purchase_date": date.today(),
            "warranty_expiry_date": None,
            "maintenance_interval_days": 30,
            "notes": "Test",
            "is_active": True,
        }
        schema = MaintenanceAssetCreateSchema(**data)
        assert schema.asset_code == "MA-001"
        assert schema.asset_name == "Test Asset"

    def test_asset_code_uppercase(self):
        schema = MaintenanceAssetCreateSchema(
            asset_code="ma-001",
            asset_name="Test",
            asset_category="Equipment",
        )
        assert schema.asset_code == "MA-001"

    def test_asset_code_required(self):
        with pytest.raises(ValueError, match="Asset code is required"):
            MaintenanceAssetCreateSchema(
                asset_code="",
                asset_name="Test",
                asset_category="Equipment",
            )


class TestMaintenanceScheduleCreateSchema:
    def test_valid_schema(self):
        data = {
            "asset_id": uuid4(),
            "schedule_code": "SCH-001",
            "schedule_name": "Monthly Check",
            "maintenance_type": MaintenanceType.PREVENTIVE,
            "frequency": ScheduleFrequency.MONTHLY,
            "custom_interval_days": None,
            "start_date": date.today(),
            "end_date": None,
            "estimated_duration_hours": Decimal("2.0"),
            "assigned_team": "Team Alpha",
            "notes": "Test",
            "is_active": True,
        }
        schema = MaintenanceScheduleCreateSchema(**data)
        assert schema.schedule_code == "SCH-001"
        assert schema.frequency == ScheduleFrequency.MONTHLY

    def test_custom_frequency_requires_interval(self):
        with pytest.raises(ValueError, match="Custom interval days required for CUSTOM frequency"):
            MaintenanceScheduleCreateSchema(
                asset_id=uuid4(),
                schedule_code="SCH-001",
                schedule_name="Test",
                maintenance_type=MaintenanceType.PREVENTIVE,
                frequency=ScheduleFrequency.CUSTOM,
                custom_interval_days=None,
                start_date=date.today(),
            )

    def test_end_date_after_start(self):
        with pytest.raises(ValueError, match="End date must be after start date"):
            MaintenanceScheduleCreateSchema(
                asset_id=uuid4(),
                schedule_code="SCH-001",
                schedule_name="Test",
                maintenance_type=MaintenanceType.PREVENTIVE,
                frequency=ScheduleFrequency.DAILY,
                start_date=date(2025, 1, 10),
                end_date=date(2025, 1, 5),
            )


class TestWorkOrderMaintenanceCreateSchema:
    def test_valid_schema(self):
        data = {
            "wo_number": "WO-001",
            "asset_id": uuid4(),
            "schedule_id": uuid4(),
            "maintenance_type": MaintenanceType.PREVENTIVE,
            "priority": MaintenancePriority.MEDIUM,
            "description": "Routine maintenance",
            "requested_by": uuid4(),
            "planned_start_date": date.today(),
            "planned_end_date": date.today(),
            "estimated_cost": Decimal("500.00"),
            "notes": "Test",
        }
        schema = WorkOrderMaintenanceCreateSchema(**data)
        assert schema.wo_number == "WO-001"
        assert schema.priority == MaintenancePriority.MEDIUM

    def test_end_date_after_start(self):
        with pytest.raises(ValueError, match="Planned end date must be after planned start date"):
            WorkOrderMaintenanceCreateSchema(
                wo_number="WO-001",
                asset_id=uuid4(),
                maintenance_type=MaintenanceType.CORRECTIVE,
                description="Fix issue",
                requested_by=uuid4(),
                planned_start_date=date(2025, 1, 10),
                planned_end_date=date(2025, 1, 5),
            )


class TestSparePartUsageSchema:
    def test_valid_schema(self):
        data = {
            "item_id": uuid4(),
            "quantity": Decimal("2"),
            "unit_cost": Decimal("150.00"),
            "work_order_id": uuid4(),
            "issued_date": date.today(),
            "notes": "Test",
        }
        schema = SparePartUsageSchema(**data)
        assert schema.quantity == Decimal("2")
        assert schema.total_cost == Decimal("300.00")

    def test_quantity_positive(self):
        with pytest.raises(ValueError):
            SparePartUsageSchema(
                item_id=uuid4(),
                quantity=Decimal("0"),
                unit_cost=Decimal("100"),
                work_order_id=uuid4(),
            )


# =============================================================================
# Tests for Health Endpoints
# =============================================================================

class TestHealthEndpoints:
    def test_ping(self):
        result = ping()
        assert result["status"] == "ok"
        assert result["service"] == "maintenance-router"

    def test_health(self):
        result = health()
        assert result["status"] == "healthy"

    def test_info(self):
        result = info()
        assert result["version"] == "1.0"
        assert result["name"] == "Maintenance Router"


# =============================================================================
# Tests for Maintenance Asset Endpoints
# =============================================================================

@pytest.mark.asyncio
class TestMaintenanceAssetEndpoints:
    async def test_create_asset_success(self, mock_maintenance_service, mock_token_payload, mock_legal_entity_id):
        request = MaintenanceAssetCreateSchema(
            asset_code="MA-001",
            asset_name="Test Asset",
            asset_category="Equipment",
        )
        result = await create_maintenance_asset(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            maintenance_svc=mock_maintenance_service,
        )
        assert isinstance(result, MaintenanceAssetResponseSchema)
        assert result.asset_code == "MA-001"
        mock_maintenance_service.create_maintenance_asset.assert_called_once()

    async def test_create_asset_idempotency(self, mock_maintenance_service, mock_token_payload, mock_legal_entity_id):
        request = MaintenanceAssetCreateSchema(
            asset_code="MA-001",
            asset_name="Test",
            asset_category="Equipment",
        )
        with patch("adapters.primary_api.v1.fastapi_maintenance_router._idempotency_manager") as mock_im:
            mock_im.get_cached_result.return_value = {
                "id": str(uuid4()),
                "asset_code": "MA-001",
                "asset_name": "Test",
                "asset_category": "Equipment",
                "location": None,
                "serial_number": None,
                "manufacturer": None,
                "model": None,
                "purchase_date": None,
                "warranty_expiry_date": None,
                "maintenance_interval_days": None,
                "status": "active",
                "is_active": True,
                "is_locked": False,
                "notes": None,
                "created_at": datetime.now(UTC).isoformat(),
                "updated_at": datetime.now(UTC).isoformat(),
                "created_by": str(uuid4()),
                "created_by_name": None,
                "version": 1,
            }
            result = await create_maintenance_asset(
                request=request,
                idempotency_key="abc123",
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                maintenance_svc=mock_maintenance_service,
            )
            assert isinstance(result, MaintenanceAssetResponseSchema)
            mock_maintenance_service.create_maintenance_asset.assert_not_called()

    async def test_list_assets(self, mock_maintenance_service, mock_legal_entity_id):
        result = await list_maintenance_assets(
            category="Equipment",
            status=MaintenanceAssetStatus.ACTIVE,
            is_active=True,
            search="test",
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            maintenance_svc=mock_maintenance_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], MaintenanceAssetResponseSchema)
        mock_maintenance_service.list_maintenance_assets.assert_called_once()

    async def test_get_asset_success(self, mock_maintenance_service, mock_legal_entity_id):
        asset_id = uuid4()
        result = await get_maintenance_asset(
            asset_id=asset_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            maintenance_svc=mock_maintenance_service,
        )
        assert isinstance(result, MaintenanceAssetResponseSchema)
        mock_maintenance_service.get_maintenance_asset_by_id.assert_called_once_with(asset_id, mock_legal_entity_id)

    async def test_get_asset_not_found(self, mock_maintenance_service, mock_legal_entity_id):
        mock_maintenance_service.get_maintenance_asset_by_id.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_maintenance_asset(
                asset_id=uuid4(),
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                maintenance_svc=mock_maintenance_service,
            )
        assert exc.value.status_code == 404

    async def test_update_asset_success(self, mock_maintenance_service, mock_token_payload, mock_legal_entity_id):
        asset_id = uuid4()
        request = MaintenanceAssetUpdateSchema(asset_name="Updated Name")
        result = await update_maintenance_asset(
            asset_id=asset_id,
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            maintenance_svc=mock_maintenance_service,
        )
        assert isinstance(result, MaintenanceAssetResponseSchema)
        mock_maintenance_service.update_maintenance_asset.assert_called_once()

    async def test_update_asset_not_found(self, mock_maintenance_service, mock_token_payload, mock_legal_entity_id):
        mock_maintenance_service.update_maintenance_asset.return_value = None
        with pytest.raises(HTTPException) as exc:
            await update_maintenance_asset(
                asset_id=uuid4(),
                request=MaintenanceAssetUpdateSchema(),
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                maintenance_svc=mock_maintenance_service,
            )
        assert exc.value.status_code == 404

    async def test_deactivate_asset_success(self, mock_maintenance_service, mock_token_payload, mock_legal_entity_id):
        asset_id = uuid4()
        result = await deactivate_maintenance_asset(
            asset_id=asset_id,
            reason="Obsolete",
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            maintenance_svc=mock_maintenance_service,
        )
        assert result["status"] == "inactive"
        mock_maintenance_service.deactivate_maintenance_asset.assert_called_once_with(
            asset_id, mock_legal_entity_id, mock_token_payload.user_id, "Obsolete"
        )


# =============================================================================
# Tests for Maintenance Schedule Endpoints
# =============================================================================

@pytest.mark.asyncio
class TestMaintenanceScheduleEndpoints:
    async def test_create_schedule_success(self, mock_maintenance_service, mock_token_payload, mock_legal_entity_id):
        request = MaintenanceScheduleCreateSchema(
            asset_id=uuid4(),
            schedule_code="SCH-001",
            schedule_name="Monthly Check",
            maintenance_type=MaintenanceType.PREVENTIVE,
            frequency=ScheduleFrequency.MONTHLY,
            start_date=date.today(),
        )
        result = await create_maintenance_schedule(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            maintenance_svc=mock_maintenance_service,
        )
        assert isinstance(result, MaintenanceScheduleResponseSchema)
        assert result.schedule_code == "SCH-001"
        mock_maintenance_service.create_maintenance_schedule.assert_called_once()

    async def test_list_schedules(self, mock_maintenance_service, mock_legal_entity_id):
        result = await list_maintenance_schedules(
            asset_id=None,
            maintenance_type=MaintenanceType.PREVENTIVE,
            is_active=True,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            maintenance_svc=mock_maintenance_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], MaintenanceScheduleResponseSchema)

    async def test_get_schedule_success(self, mock_maintenance_service, mock_legal_entity_id):
        schedule_id = uuid4()
        result = await get_maintenance_schedule(
            schedule_id=schedule_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            maintenance_svc=mock_maintenance_service,
        )
        assert isinstance(result, MaintenanceScheduleResponseSchema)
        mock_maintenance_service.get_maintenance_schedule_by_id.assert_called_once_with(schedule_id, mock_legal_entity_id)

    async def test_update_schedule_success(self, mock_maintenance_service, mock_token_payload, mock_legal_entity_id):
        schedule_id = uuid4()
        request = MaintenanceScheduleUpdateSchema(schedule_name="Updated Schedule")
        result = await update_maintenance_schedule(
            schedule_id=schedule_id,
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            maintenance_svc=mock_maintenance_service,
        )
        assert isinstance(result, MaintenanceScheduleResponseSchema)
        mock_maintenance_service.update_maintenance_schedule.assert_called_once()

    async def test_deactivate_schedule_success(self, mock_maintenance_service, mock_token_payload, mock_legal_entity_id):
        schedule_id = uuid4()
        result = await deactivate_maintenance_schedule(
            schedule_id=schedule_id,
            reason="Completed",
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            maintenance_svc=mock_maintenance_service,
        )
        assert result["status"] == "inactive"
        mock_maintenance_service.deactivate_maintenance_schedule.assert_called_once_with(
            schedule_id, mock_legal_entity_id, mock_token_payload.user_id, "Completed"
        )


# =============================================================================
# Tests for Work Order Endpoints
# =============================================================================

@pytest.mark.asyncio
class TestWorkOrderEndpoints:
    async def test_create_work_order_success(self, mock_maintenance_service, mock_token_payload, mock_legal_entity_id):
        request = WorkOrderMaintenanceCreateSchema(
            wo_number="WO-001",
            asset_id=uuid4(),
            maintenance_type=MaintenanceType.PREVENTIVE,
            description="Routine check",
            requested_by=uuid4(),
            planned_start_date=date.today(),
            planned_end_date=date.today(),
        )
        result = await create_maintenance_work_order(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            maintenance_svc=mock_maintenance_service,
        )
        assert isinstance(result, WorkOrderMaintenanceResponseSchema)
        assert result.wo_number == "WO-001"
        mock_maintenance_service.create_maintenance_work_order.assert_called_once()

    async def test_list_work_orders(self, mock_maintenance_service, mock_legal_entity_id):
        result = await list_maintenance_work_orders(
            asset_id=None,
            status=WorkOrderStatus.DRAFT,
            priority=MaintenancePriority.MEDIUM,
            start_date=None,
            end_date=None,
            page=1,
            page_size=20,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            maintenance_svc=mock_maintenance_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], WorkOrderMaintenanceResponseSchema)
        mock_maintenance_service.list_maintenance_work_orders.assert_called_once()

    async def test_get_work_order_success(self, mock_maintenance_service, mock_legal_entity_id):
        wo_id = uuid4()
        result = await get_maintenance_work_order(
            wo_id=wo_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            maintenance_svc=mock_maintenance_service,
        )
        assert isinstance(result, WorkOrderMaintenanceResponseSchema)
        mock_maintenance_service.get_maintenance_work_order_by_id.assert_called_once_with(wo_id, mock_legal_entity_id)

    async def test_update_work_order_success(self, mock_maintenance_service, mock_token_payload, mock_legal_entity_id):
        wo_id = uuid4()
        request = WorkOrderMaintenanceUpdateSchema(priority=MaintenancePriority.HIGH)
        result = await update_maintenance_work_order(
            wo_id=wo_id,
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            maintenance_svc=mock_maintenance_service,
        )
        assert isinstance(result, WorkOrderMaintenanceResponseSchema)
        mock_maintenance_service.update_maintenance_work_order.assert_called_once()

    async def test_complete_work_order_success(self, mock_maintenance_service, mock_token_payload, mock_legal_entity_id):
        wo_id = uuid4()
        result = await complete_maintenance_work_order(
            wo_id=wo_id,
            actual_end_date=date.today(),
            actual_cost=Decimal("500"),
            notes="Completed",
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            maintenance_svc=mock_maintenance_service,
        )
        assert isinstance(result, WorkOrderMaintenanceResponseSchema)
        mock_maintenance_service.complete_maintenance_work_order.assert_called_once()

    async def test_cancel_work_order_success(self, mock_maintenance_service, mock_token_payload, mock_legal_entity_id):
        wo_id = uuid4()
        result = await cancel_maintenance_work_order(
            wo_id=wo_id,
            reason="No longer needed",
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            maintenance_svc=mock_maintenance_service,
        )
        assert result["status"] == "cancelled"
        mock_maintenance_service.cancel_maintenance_work_order.assert_called_once()


# =============================================================================
# Tests for Spare Parts Usage
# =============================================================================

@pytest.mark.asyncio
class TestSparePartsEndpoints:
    async def test_record_spare_parts_usage_success(self, mock_maintenance_service, mock_token_payload, mock_legal_entity_id):
        request = SparePartUsageSchema(
            item_id=uuid4(),
            quantity=Decimal("2"),
            unit_cost=Decimal("150.00"),
            work_order_id=uuid4(),
            issued_date=date.today(),
        )
        result = await record_spare_parts_usage(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            maintenance_svc=mock_maintenance_service,
        )
        assert isinstance(result, SparePartUsageResponseSchema)
        assert result.total_cost == Decimal("300.00")
        mock_maintenance_service.record_spare_parts_usage.assert_called_once()


# =============================================================================
# Tests for Cost Summary
# =============================================================================

@pytest.mark.asyncio
class TestCostSummaryEndpoint:
    async def test_get_cost_summary(self, mock_maintenance_service, mock_legal_entity_id):
        start = date(2025, 1, 1)
        end = date(2025, 1, 31)
        result = await get_maintenance_cost_summary(
            start_date=start,
            end_date=end,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            maintenance_svc=mock_maintenance_service,
        )
        assert isinstance(result, MaintenanceCostSummarySchema)
        assert result.period_start == start
        assert result.period_end == end
        assert result.total_maintenance_cost == Decimal("5000")
        mock_maintenance_service.get_maintenance_cost_summary.assert_called_once()


# =============================================================================
# Tests for Export
# =============================================================================

@pytest.mark.asyncio
class TestExportEndpoint:
    async def test_export_work_orders(self, mock_maintenance_service, mock_legal_entity_id):
        start = date(2025, 1, 1)
        end = date(2025, 1, 31)
        response = await export_maintenance_work_orders(
            start_date=start,
            end_date=end,
            format="csv",
            status=WorkOrderStatus.COMPLETED,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            maintenance_svc=mock_maintenance_service,
        )
        assert response.body == b"csv data"
        assert response.media_type == "text/csv"
        assert "attachment" in response.headers["Content-Disposition"]
        mock_maintenance_service.export_maintenance_work_orders.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            start_date=start,
            end_date=end,
            format="csv",
            status="completed",
        )

    async def test_export_excel(self, mock_maintenance_service, mock_legal_entity_id):
        start = date(2025, 1, 1)
        end = date(2025, 1, 31)
        mock_maintenance_service.export_maintenance_work_orders.return_value = b"excel data"
        response = await export_maintenance_work_orders(
            start_date=start,
            end_date=end,
            format="excel",
            status=None,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            maintenance_svc=mock_maintenance_service,
        )
        assert response.media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
