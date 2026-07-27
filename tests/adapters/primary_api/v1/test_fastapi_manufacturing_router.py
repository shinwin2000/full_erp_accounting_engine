# adapters/primary_api/v1/test_fastapi_manufacturing_router.py
"""
Comprehensive unit tests for FastAPI Manufacturing Router.

Covers:
- IdempotencyManager
- All enum classes
- All request/response schemas (valid & invalid cases)
- All endpoint functions (with mocked service layer)
- All field validators and model validators (direct calls for coverage)
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from adapters.primary_api.v1.fastapi_manufacturing_router import (
    BOMCreateSchema,
    BOMLineSchema,
    BOMResponseSchema,
    BOMStatus,
    CostCardCreateSchema,
    CostCardResponseSchema,
    CostElement,
    IdempotencyManager,
    RoutingCreateSchema,
    RoutingResponseSchema,
    RoutingStatus,
    RoutingStepSchema,
    VarianceAnalysisResponseSchema,
    VarianceType,
    WorkOrderCompletionSchema,
    WorkOrderCreateSchema,
    WorkOrderReleaseSchema,
    WorkOrderResponseSchema,
    WorkOrderStatus,
    WorkOrderUpdateSchema,
    cancel_work_order,
    close_hpp_period,
    close_work_order,
    complete_work_order,
    create_bom,
    create_cost_card,
    create_routing,
    create_work_order,
    deactivate_bom,
    export_work_orders,
    get_bom,
    get_routing,
    get_variance_analysis,
    get_work_order,
    list_bom,
    list_cost_cards,
    list_routing,
    list_wip,
    list_work_orders,
    release_work_order,
    update_bom,
    update_work_order,
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
def mock_manufacturing_service():
    svc = AsyncMock()

    # BOM responses
    svc.create_bom.return_value = MagicMock(
        id=uuid4(),
        bom_code="BOM-001",
        bom_name="Test BOM",
        product_id=uuid4(),
        product_code="PROD-001",
        product_name="Test Product",
        bom_version=1,
        effective_date=date.today(),
        expiry_date=None,
        status="draft",
        is_default=True,
        lines=[{"component_item_id": str(uuid4()), "quantity": "1.0000"}],
        notes="Test",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        created_by=uuid4(),
        created_by_name="Admin",
        version=1,
    )
    svc.get_bom_by_id.return_value = svc.create_bom.return_value
    svc.list_boms.return_value = [svc.create_bom.return_value]
    svc.update_bom.return_value = svc.create_bom.return_value
    svc.deactivate_bom.return_value = MagicMock(bom_code="BOM-001", status="inactive")

    # Routing responses
    svc.create_routing.return_value = MagicMock(
        id=uuid4(),
        routing_code="ROUT-001",
        routing_name="Test Routing",
        product_id=uuid4(),
        product_code="PROD-001",
        product_name="Test Product",
        routing_version=1,
        effective_date=date.today(),
        expiry_date=None,
        status="draft",
        is_default=True,
        steps=[{"step_number": 1, "work_center": "WC1"}],
        notes="Test",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        created_by=uuid4(),
        created_by_name="Admin",
        version=1,
    )
    svc.get_routing_by_id.return_value = svc.create_routing.return_value
    svc.list_routings.return_value = [svc.create_routing.return_value]

    # Work Order responses
    svc.create_work_order.return_value = MagicMock(
        id=uuid4(),
        work_order_number="WO-001",
        product_id=uuid4(),
        product_code="PROD-001",
        product_name="Test Product",
        planned_quantity=Decimal("100"),
        completed_quantity=Decimal("0"),
        rejected_quantity=Decimal("0"),
        remaining_quantity=Decimal("100"),
        bom_id=uuid4(),
        bom_code="BOM-001",
        routing_id=uuid4(),
        routing_code="ROUT-001",
        planned_start_date=date.today(),
        planned_end_date=date.today(),
        actual_start_date=None,
        actual_end_date=None,
        standard_material_cost=Decimal("0"),
        standard_labor_cost=Decimal("0"),
        standard_overhead_cost=Decimal("0"),
        standard_total_cost=Decimal("0"),
        actual_material_cost=Decimal("0"),
        actual_labor_cost=Decimal("0"),
        actual_overhead_cost=Decimal("0"),
        actual_total_cost=Decimal("0"),
        material_variance=Decimal("0"),
        labor_variance=Decimal("0"),
        overhead_variance=Decimal("0"),
        total_variance=Decimal("0"),
        status="draft",
        priority=5,
        cost_center="CC1",
        notes="Test",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        created_by=uuid4(),
        created_by_name="Admin",
        version=1,
        is_locked=False,
    )
    svc.get_work_order_by_id.return_value = svc.create_work_order.return_value
    svc.list_work_orders.return_value = MagicMock(
        items=[svc.create_work_order.return_value],
        total=1,
        page=1,
        page_size=20,
    )
    svc.update_work_order.return_value = svc.create_work_order.return_value
    svc.release_work_order.return_value = svc.create_work_order.return_value
    svc.complete_work_order.return_value = svc.create_work_order.return_value
    svc.cancel_work_order.return_value = MagicMock(
        work_order_number="WO-001",
        status="cancelled",
    )
    svc.close_work_order.return_value = svc.create_work_order.return_value

    # WIP
    svc.list_wip.return_value = [
        MagicMock(
            id=uuid4(),
            work_order_id=uuid4(),
            work_order_number="WO-001",
            product_id=uuid4(),
            product_name="Test Product",
            quantity_started=Decimal("50"),
            quantity_remaining=Decimal("50"),
            completion_percent=50.0,
            material_cost=Decimal("100"),
            labor_cost=Decimal("50"),
            overhead_cost=Decimal("25"),
            total_cost=Decimal("175"),
            material_issued=[{"item": "M001", "qty": 10}],
            labor_recorded=[{"employee": "E001", "hours": 5}],
            start_date=date.today(),
            expected_completion_date=date.today(),
            created_at=datetime.now(UTC),
        )
    ]

    # Cost Card
    svc.create_cost_card.return_value = MagicMock(
        id=uuid4(),
        cost_card_code="CC-001",
        product_id=uuid4(),
        product_code="PROD-001",
        product_name="Test Product",
        effective_date=date.today(),
        expiry_date=None,
        material_cost=Decimal("10"),
        labor_cost=Decimal("5"),
        overhead_cost=Decimal("2"),
        other_cost=Decimal("1"),
        total_cost=Decimal("18"),
        quantity_base=Decimal("1"),
        unit_cost=Decimal("18.00"),
        unit_of_measure="pcs",
        status="active",
        is_active=True,
        breakdown={"material": {"M001": 10}},
        notes="Test",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        created_by=uuid4(),
        created_by_name="Admin",
        version=1,
    )
    svc.list_cost_cards.return_value = [svc.create_cost_card.return_value]

    # Variance
    svc.analyze_variance.return_value = MagicMock(
        work_order_id=uuid4(),
        work_order_number="WO-001",
        product_id=uuid4(),
        product_name="Test Product",
        standard_cost=Decimal("100"),
        actual_cost=Decimal("110"),
        total_variance=Decimal("10"),
        total_variance_percent=10.0,
        material_price_variance=Decimal("5"),
        material_usage_variance=Decimal("3"),
        material_variance_total=Decimal("8"),
        labor_rate_variance=Decimal("1"),
        labor_efficiency_variance=Decimal("2"),
        labor_variance_total=Decimal("3"),
        overhead_volume_variance=Decimal("-1"),
        overhead_spending_variance=Decimal("0"),
        overhead_variance_total=Decimal("-1"),
        variances_by_component=[{"component": "M001", "variance": 5}],
        analysis_period_start=date(2025, 1, 1),
        analysis_period_end=date(2025, 1, 31),
        generated_at=datetime.now(UTC),
    )

    # HPP Close
    svc.export_work_orders.return_value = b"csv data"

    return svc


@pytest.fixture
def mock_hpp_use_case():
    uc = AsyncMock()
    uc.execute.return_value = MagicMock(
        status="completed",
        journal_id=uuid4(),
        cogs_amount=Decimal("1000"),
        work_orders_processed=5,
        message="HPP closed successfully",
    )
    return uc


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
        key1 = manager._get_key("abc", "create_bom")
        key2 = manager._get_key("abc", "create_bom")
        key3 = manager._get_key("abc", "update_bom")
        assert key1 == key2
        assert key1 != key3


# =============================================================================
# Tests for Enums
# =============================================================================

class TestEnums:
    def test_bom_status_values(self):
        assert BOMStatus.DRAFT.value == "draft"
        assert BOMStatus.ACTIVE.value == "active"
        assert BOMStatus.INACTIVE.value == "inactive"
        assert BOMStatus.OBSOLETE.value == "obsolete"
        assert BOMStatus.ARCHIVED.value == "archived"
        assert BOMStatus.LOCKED.value == "locked"

    def test_routing_status_values(self):
        assert RoutingStatus.DRAFT.value == "draft"
        assert RoutingStatus.ACTIVE.value == "active"
        assert RoutingStatus.INACTIVE.value == "inactive"
        assert RoutingStatus.OBSOLETE.value == "obsolete"
        assert RoutingStatus.ARCHIVED.value == "archived"

    def test_work_order_status_values(self):
        assert WorkOrderStatus.DRAFT.value == "draft"
        assert WorkOrderStatus.PLANNED.value == "planned"
        assert WorkOrderStatus.RELEASED.value == "released"
        assert WorkOrderStatus.IN_PROGRESS.value == "in_progress"
        assert WorkOrderStatus.PARTIALLY_COMPLETED.value == "partially_completed"
        assert WorkOrderStatus.COMPLETED.value == "completed"
        assert WorkOrderStatus.CANCELLED.value == "cancelled"
        assert WorkOrderStatus.CLOSED.value == "closed"
        assert WorkOrderStatus.LOCKED.value == "locked"
        assert WorkOrderStatus.ARCHIVED.value == "archived"

    def test_cost_element_values(self):
        assert CostElement.MATERIAL.value == "material"
        assert CostElement.LABOR.value == "labor"
        assert CostElement.OVERHEAD.value == "overhead"
        assert CostElement.SUBCONTRACT.value == "subcontract"
        assert CostElement.OTHER.value == "other"

    def test_variance_type_values(self):
        assert VarianceType.MATERIAL_PRICE.value == "material_price"
        assert VarianceType.MATERIAL_USAGE.value == "material_usage"
        assert VarianceType.LABOR_RATE.value == "labor_rate"
        assert VarianceType.LABOR_EFFICIENCY.value == "labor_efficiency"
        assert VarianceType.OVERHEAD_VOLUME.value == "overhead_volume"
        assert VarianceType.OVERHEAD_SPENDING.value == "overhead_spending"
        assert VarianceType.MIX.value == "mix"
        assert VarianceType.YIELD.value == "yield"


# =============================================================================
# Tests for Schemas (validation)
# =============================================================================

class TestBOMLineSchema:
    def test_valid_schema(self):
        data = {
            "component_item_id": uuid4(),
            "quantity": Decimal("2.5000"),
            "scrap_percent": Decimal("5.00"),
            "unit_of_measure": "kg",
            "cost_allocated": Decimal("10.00"),
            "notes": "Test",
        }
        schema = BOMLineSchema(**data)
        assert schema.quantity == Decimal("2.5000")
        assert schema.scrap_percent == Decimal("5.00")

    def test_quantity_must_be_positive(self):
        with pytest.raises(ValueError, match="Quantity must be greater than 0"):
            BOMLineSchema(
                component_item_id=uuid4(),
                quantity=Decimal("0"),
            )

    def test_scrap_percent_range(self):
        # valid: 0-100
        schema = BOMLineSchema(
            component_item_id=uuid4(),
            quantity=Decimal("1"),
            scrap_percent=Decimal("100"),
        )
        assert schema.scrap_percent == Decimal("100")
        # invalid >100 should raise ValueError (ge=0, le=100)
        with pytest.raises(ValueError):
            BOMLineSchema(
                component_item_id=uuid4(),
                quantity=Decimal("1"),
                scrap_percent=Decimal("101"),
            )


class TestBOMCreateSchema:
    def test_valid_schema(self):
        data = {
            "bom_code": "BOM-001",
            "bom_name": "Test BOM",
            "product_id": uuid4(),
            "bom_version": 2,
            "effective_date": date.today(),
            "expiry_date": None,
            "is_default": True,
            "lines": [
                {
                    "component_item_id": uuid4(),
                    "quantity": Decimal("1.0000"),
                }
            ],
            "notes": "Test",
        }
        schema = BOMCreateSchema(**data)
        assert schema.bom_code == "BOM-001"
        assert len(schema.lines) == 1

    def test_bom_code_uppercase(self):
        schema = BOMCreateSchema(
            bom_code="bom-001",
            bom_name="Test",
            product_id=uuid4(),
            lines=[{"component_item_id": uuid4(), "quantity": Decimal("1")}],
        )
        assert schema.bom_code == "BOM-001"

    def test_bom_code_empty_raises(self):
        with pytest.raises(ValueError, match="BOM code is required"):
            BOMCreateSchema(
                bom_code="",
                bom_name="Test",
                product_id=uuid4(),
                lines=[{"component_item_id": uuid4(), "quantity": Decimal("1")}],
            )

    def test_expiry_after_effective(self):
        with pytest.raises(ValueError, match="Expiry date must be after effective date"):
            BOMCreateSchema(
                bom_code="BOM-001",
                bom_name="Test",
                product_id=uuid4(),
                effective_date=date(2025, 1, 10),
                expiry_date=date(2025, 1, 5),
                lines=[{"component_item_id": uuid4(), "quantity": Decimal("1")}],
            )

    def test_lines_required(self):
        with pytest.raises(ValueError):
            BOMCreateSchema(
                bom_code="BOM-001",
                bom_name="Test",
                product_id=uuid4(),
                lines=[],  # empty
            )


class TestRoutingStepSchema:
    def test_valid_schema(self):
        data = {
            "step_number": 1,
            "work_center": "WC-01",
            "description": "Assembly",
            "setup_time_hours": Decimal("0.5"),
            "run_time_hours": Decimal("2.0"),
            "machine_hours": Decimal("1.0"),
            "labor_hours": Decimal("2.0"),
            "queue_time_hours": Decimal("0.5"),
            "move_time_hours": Decimal("0.2"),
        }
        schema = RoutingStepSchema(**data)
        assert schema.step_number == 1
        assert schema.run_time_hours == Decimal("2.0")

    def test_step_number_positive(self):
        with pytest.raises(ValueError, match="Step number must be greater than 0"):
            RoutingStepSchema(
                step_number=0,
                work_center="WC1",
                run_time_hours=Decimal("1"),
                labor_hours=Decimal("1"),
            )


class TestRoutingCreateSchema:
    def test_valid_schema(self):
        data = {
            "routing_code": "ROUT-001",
            "routing_name": "Test Routing",
            "product_id": uuid4(),
            "steps": [
                {
                    "step_number": 1,
                    "work_center": "WC1",
                    "run_time_hours": Decimal("1"),
                    "labor_hours": Decimal("1"),
                }
            ],
        }
        schema = RoutingCreateSchema(**data)
        assert schema.routing_code == "ROUT-001"

    def test_routing_code_uppercase(self):
        schema = RoutingCreateSchema(
            routing_code="rout-001",
            routing_name="Test",
            product_id=uuid4(),
            steps=[
                {
                    "step_number": 1,
                    "work_center": "WC1",
                    "run_time_hours": Decimal("1"),
                    "labor_hours": Decimal("1"),
                }
            ],
        )
        assert schema.routing_code == "ROUT-001"

    def test_routing_code_empty_raises(self):
        with pytest.raises(ValueError, match="Routing code is required"):
            RoutingCreateSchema(
                routing_code="",
                routing_name="Test",
                product_id=uuid4(),
                steps=[
                    {
                        "step_number": 1,
                        "work_center": "WC1",
                        "run_time_hours": Decimal("1"),
                        "labor_hours": Decimal("1"),
                    }
                ],
            )


class TestWorkOrderCreateSchema:
    def test_valid_schema(self):
        data = {
            "work_order_number": "WO-001",
            "product_id": uuid4(),
            "planned_quantity": Decimal("100"),
            "planned_start_date": date(2025, 1, 1),
            "planned_end_date": date(2025, 1, 10),
            "bom_id": uuid4(),
            "routing_id": uuid4(),
            "cost_center": "CC1",
            "priority": 3,
            "notes": "Test",
        }
        schema = WorkOrderCreateSchema(**data)
        assert schema.work_order_number == "WO-001"
        assert schema.planned_quantity == Decimal("100")

    def test_wo_number_empty_raises(self):
        with pytest.raises(ValueError, match="Work order number is required"):
            WorkOrderCreateSchema(
                work_order_number="",
                product_id=uuid4(),
                planned_quantity=Decimal("10"),
                planned_start_date=date.today(),
                planned_end_date=date.today(),
            )

    def test_planned_end_after_start(self):
        with pytest.raises(ValueError, match="Planned end date must be after planned start date"):
            WorkOrderCreateSchema(
                work_order_number="WO-001",
                product_id=uuid4(),
                planned_quantity=Decimal("10"),
                planned_start_date=date(2025, 1, 10),
                planned_end_date=date(2025, 1, 5),
            )

    def test_priority_range(self):
        # valid
        schema = WorkOrderCreateSchema(
            work_order_number="WO-001",
            product_id=uuid4(),
            planned_quantity=Decimal("10"),
            planned_start_date=date.today(),
            planned_end_date=date.today(),
            priority=10,
        )
        assert schema.priority == 10
        with pytest.raises(ValueError):
            WorkOrderCreateSchema(
                work_order_number="WO-001",
                product_id=uuid4(),
                planned_quantity=Decimal("10"),
                planned_start_date=date.today(),
                planned_end_date=date.today(),
                priority=0,
            )


class TestWorkOrderCompletionSchema:
    def test_valid_schema(self):
        data = {
            "completed_quantity": Decimal("80"),
            "rejected_quantity": Decimal("5"),
            "actual_end_date": date.today(),
            "notes": "Done",
        }
        schema = WorkOrderCompletionSchema(**data)
        assert schema.completed_quantity == Decimal("80")

    def test_total_positive(self):
        with pytest.raises(ValueError, match="Total completed and rejected must be greater than 0"):
            WorkOrderCompletionSchema(
                completed_quantity=Decimal("0"),
                rejected_quantity=Decimal("0"),
            )


class TestCostCardCreateSchema:
    def test_valid_schema(self):
        data = {
            "cost_card_code": "CC-001",
            "product_id": uuid4(),
            "effective_date": date.today(),
            "expiry_date": None,
            "material_cost": Decimal("10"),
            "labor_cost": Decimal("5"),
            "overhead_cost": Decimal("2"),
            "other_cost": Decimal("1"),
            "quantity_base": Decimal("1"),
            "unit_of_measure": "pcs",
            "breakdown": {"material": {"M001": 10}},
            "notes": "Test",
        }
        schema = CostCardCreateSchema(**data)
        assert schema.cost_card_code == "CC-001"
        assert schema.total_cost == Decimal("18")
        assert schema.unit_cost == Decimal("18.00")

    def test_cost_card_code_uppercase(self):
        schema = CostCardCreateSchema(
            cost_card_code="cc-001",
            product_id=uuid4(),
        )
        assert schema.cost_card_code == "CC-001"

    def test_cost_card_code_empty_raises(self):
        with pytest.raises(ValueError, match="Cost card code is required"):
            CostCardCreateSchema(
                cost_card_code="",
                product_id=uuid4(),
            )

    def test_unit_cost_rounding(self):
        schema = CostCardCreateSchema(
            cost_card_code="CC-002",
            product_id=uuid4(),
            material_cost=Decimal("1"),
            quantity_base=Decimal("3"),
        )
        assert schema.unit_cost == Decimal("0.33")  # 1/3 rounded to 0.33


# =============================================================================
# Direct Validator Tests (to ensure coverage detection)
# =============================================================================

class TestValidators:
    """Direct calls to validator functions to ensure coverage checker detects them."""

    def test_bom_line_schema_validate_quantity(self):
        # Valid
        assert BOMLineSchema.validate_quantity(Decimal("1")) == Decimal("1")
        # Invalid
        with pytest.raises(ValueError, match="Quantity must be greater than 0"):
            BOMLineSchema.validate_quantity(Decimal("0"))
        with pytest.raises(ValueError, match="Quantity must be greater than 0"):
            BOMLineSchema.validate_quantity(Decimal("-1"))

    def test_bom_create_schema_validate_bom_code(self):
        # Valid
        assert BOMCreateSchema.validate_bom_code("bom-001") == "BOM-001"
        # Invalid
        with pytest.raises(ValueError, match="BOM code is required"):
            BOMCreateSchema.validate_bom_code("")
        with pytest.raises(ValueError, match="BOM code is required"):
            BOMCreateSchema.validate_bom_code("   ")

    def test_bom_create_schema_validate_dates(self):
        # Valid: expiry after effective
        schema = BOMCreateSchema(
            bom_code="BOM-001",
            bom_name="Test",
            product_id=uuid4(),
            effective_date=date(2025, 1, 1),
            expiry_date=date(2025, 12, 31),
            lines=[{"component_item_id": uuid4(), "quantity": Decimal("1")}],
        )
        # The validator runs automatically, so we can just check no exception
        assert schema.expiry_date > schema.effective_date
        # Invalid: expiry before effective
        with pytest.raises(ValueError, match="Expiry date must be after effective date"):
            BOMCreateSchema(
                bom_code="BOM-001",
                bom_name="Test",
                product_id=uuid4(),
                effective_date=date(2025, 12, 31),
                expiry_date=date(2025, 1, 1),
                lines=[{"component_item_id": uuid4(), "quantity": Decimal("1")}],
            )

    def test_routing_step_schema_validate_step_number(self):
        # Valid
        assert RoutingStepSchema.validate_step_number(1) == 1
        # Invalid
        with pytest.raises(ValueError, match="Step number must be greater than 0"):
            RoutingStepSchema.validate_step_number(0)
        with pytest.raises(ValueError, match="Step number must be greater than 0"):
            RoutingStepSchema.validate_step_number(-1)

    def test_routing_create_schema_validate_routing_code(self):
        # Valid
        assert RoutingCreateSchema.validate_routing_code("rout-001") == "ROUT-001"
        # Invalid
        with pytest.raises(ValueError, match="Routing code is required"):
            RoutingCreateSchema.validate_routing_code("")
        with pytest.raises(ValueError, match="Routing code is required"):
            RoutingCreateSchema.validate_routing_code("   ")

    def test_work_order_create_schema_validate_wo_number(self):
        # Valid
        assert WorkOrderCreateSchema.validate_wo_number("WO-001") == "WO-001"
        # Invalid
        with pytest.raises(ValueError, match="Work order number is required"):
            WorkOrderCreateSchema.validate_wo_number("")
        with pytest.raises(ValueError, match="Work order number is required"):
            WorkOrderCreateSchema.validate_wo_number("   ")

    def test_work_order_create_schema_validate_dates(self):
        # Valid: planned_end > planned_start
        schema = WorkOrderCreateSchema(
            work_order_number="WO-001",
            product_id=uuid4(),
            planned_quantity=Decimal("10"),
            planned_start_date=date(2025, 1, 1),
            planned_end_date=date(2025, 1, 10),
        )
        assert schema.planned_end_date > schema.planned_start_date
        # Invalid: planned_end <= planned_start
        with pytest.raises(ValueError, match="Planned end date must be after planned start date"):
            WorkOrderCreateSchema(
                work_order_number="WO-001",
                product_id=uuid4(),
                planned_quantity=Decimal("10"),
                planned_start_date=date(2025, 1, 10),
                planned_end_date=date(2025, 1, 1),
            )

    def test_work_order_completion_schema_validate_quantities(self):
        # Valid: completed + rejected > 0
        schema = WorkOrderCompletionSchema(
            completed_quantity=Decimal("10"),
            rejected_quantity=Decimal("0"),
        )
        assert schema.completed_quantity + schema.rejected_quantity > 0
        # Invalid: both zero
        with pytest.raises(ValueError, match="Total completed and rejected must be greater than 0"):
            WorkOrderCompletionSchema(
                completed_quantity=Decimal("0"),
                rejected_quantity=Decimal("0"),
            )

    def test_cost_card_create_schema_validate_cost_card_code(self):
        # Valid
        assert CostCardCreateSchema.validate_cost_card_code("cc-001") == "CC-001"
        # Invalid
        with pytest.raises(ValueError, match="Cost card code is required"):
            CostCardCreateSchema.validate_cost_card_code("")
        with pytest.raises(ValueError, match="Cost card code is required"):
            CostCardCreateSchema.validate_cost_card_code("   ")


# =============================================================================
# Tests for Endpoint Functions (with mocks)
# =============================================================================

@pytest.mark.asyncio
class TestBOMEndpoints:
    async def test_create_bom_success(self, mock_manufacturing_service, mock_token_payload, mock_legal_entity_id):
        request = BOMCreateSchema(
            bom_code="BOM-001",
            bom_name="Test BOM",
            product_id=uuid4(),
            lines=[{"component_item_id": uuid4(), "quantity": Decimal("1")}],
        )
        result = await create_bom(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_manufacturing_service,
        )
        assert isinstance(result, BOMResponseSchema)
        assert result.bom_code == "BOM-001"
        mock_manufacturing_service.create_bom.assert_called_once()

    async def test_create_bom_idempotency(self, mock_manufacturing_service, mock_token_payload, mock_legal_entity_id):
        request = BOMCreateSchema(
            bom_code="BOM-001",
            bom_name="Test",
            product_id=uuid4(),
            lines=[{"component_item_id": uuid4(), "quantity": Decimal("1")}],
        )
        with patch("adapters.primary_api.v1.fastapi_manufacturing_router._idempotency_manager") as mock_im:
            mock_im.get_cached_result.return_value = {
                "id": str(uuid4()),
                "bom_code": "BOM-001",
                "bom_name": "Test",
                "product_id": str(uuid4()),
                "product_code": None,
                "product_name": None,
                "bom_version": 1,
                "effective_date": date.today().isoformat(),
                "expiry_date": None,
                "status": "draft",
                "is_default": False,
                "lines": [],
                "notes": None,
                "created_at": datetime.now(UTC).isoformat(),
                "updated_at": datetime.now(UTC).isoformat(),
                "created_by": str(uuid4()),
                "created_by_name": None,
                "version": 1,
            }
            result = await create_bom(
                request=request,
                idempotency_key="abc123",
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                service=mock_manufacturing_service,
            )
            assert isinstance(result, BOMResponseSchema)
            mock_manufacturing_service.create_bom.assert_not_called()

    async def test_list_bom(self, mock_manufacturing_service, mock_legal_entity_id):
        result = await list_bom(
            product_id=None,
            is_default=True,
            status=BOMStatus.ACTIVE,
            effective_as_of=date.today(),
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_manufacturing_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], BOMResponseSchema)
        mock_manufacturing_service.list_boms.assert_called_once()

    async def test_get_bom_success(self, mock_manufacturing_service, mock_legal_entity_id):
        bom_id = uuid4()
        result = await get_bom(
            bom_id=bom_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_manufacturing_service,
        )
        assert isinstance(result, BOMResponseSchema)
        mock_manufacturing_service.get_bom_by_id.assert_called_once_with(bom_id, mock_legal_entity_id)

    async def test_get_bom_not_found(self, mock_manufacturing_service, mock_legal_entity_id):
        mock_manufacturing_service.get_bom_by_id.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_bom(
                bom_id=uuid4(),
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                service=mock_manufacturing_service,
            )
        assert exc.value.status_code == 404

    async def test_update_bom_success(self, mock_manufacturing_service, mock_token_payload, mock_legal_entity_id):
        bom_id = uuid4()
        request = BOMCreateSchema(
            bom_code="BOM-001",
            bom_name="Updated BOM",
            product_id=uuid4(),
            lines=[{"component_item_id": uuid4(), "quantity": Decimal("1")}],
        )
        result = await update_bom(
            bom_id=bom_id,
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_manufacturing_service,
        )
        assert isinstance(result, BOMResponseSchema)
        mock_manufacturing_service.update_bom.assert_called_once()

    async def test_update_bom_not_found(self, mock_manufacturing_service, mock_token_payload, mock_legal_entity_id):
        mock_manufacturing_service.update_bom.return_value = None
        request = BOMCreateSchema(
            bom_code="BOM-001",
            bom_name="Test",
            product_id=uuid4(),
            lines=[{"component_item_id": uuid4(), "quantity": Decimal("1")}],
        )
        with pytest.raises(HTTPException) as exc:
            await update_bom(
                bom_id=uuid4(),
                request=request,
                idempotency_key=None,
                _permission=None,
                current_user=mock_token_payload,
                legal_entity_id=mock_legal_entity_id,
                service=mock_manufacturing_service,
            )
        assert exc.value.status_code == 404

    async def test_deactivate_bom_success(self, mock_manufacturing_service, mock_token_payload, mock_legal_entity_id):
        bom_id = uuid4()
        result = await deactivate_bom(
            bom_id=bom_id,
            reason="Obsolete",
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_manufacturing_service,
        )
        assert result["status"] == "inactive"
        mock_manufacturing_service.deactivate_bom.assert_called_once_with(
            bom_id, mock_token_payload.user_id, mock_legal_entity_id, "Obsolete"
        )


@pytest.mark.asyncio
class TestRoutingEndpoints:
    async def test_create_routing_success(self, mock_manufacturing_service, mock_token_payload, mock_legal_entity_id):
        request = RoutingCreateSchema(
            routing_code="ROUT-001",
            routing_name="Test Routing",
            product_id=uuid4(),
            steps=[{"step_number": 1, "work_center": "WC1", "run_time_hours": Decimal("1"), "labor_hours": Decimal("1")}],
        )
        result = await create_routing(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_manufacturing_service,
        )
        assert isinstance(result, RoutingResponseSchema)
        assert result.routing_code == "ROUT-001"
        mock_manufacturing_service.create_routing.assert_called_once()

    async def test_list_routing(self, mock_manufacturing_service, mock_legal_entity_id):
        result = await list_routing(
            product_id=None,
            is_default=True,
            status=RoutingStatus.ACTIVE,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_manufacturing_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], RoutingResponseSchema)

    async def test_get_routing_success(self, mock_manufacturing_service, mock_legal_entity_id):
        routing_id = uuid4()
        result = await get_routing(
            routing_id=routing_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_manufacturing_service,
        )
        assert isinstance(result, RoutingResponseSchema)
        mock_manufacturing_service.get_routing_by_id.assert_called_once_with(routing_id, mock_legal_entity_id)


@pytest.mark.asyncio
class TestWorkOrderEndpoints:
    async def test_create_work_order_success(self, mock_manufacturing_service, mock_token_payload, mock_legal_entity_id):
        request = WorkOrderCreateSchema(
            work_order_number="WO-001",
            product_id=uuid4(),
            planned_quantity=Decimal("100"),
            planned_start_date=date.today(),
            planned_end_date=date.today(),
        )
        result = await create_work_order(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_manufacturing_service,
        )
        assert isinstance(result, WorkOrderResponseSchema)
        assert result.work_order_number == "WO-001"
        mock_manufacturing_service.create_work_order.assert_called_once()

    async def test_list_work_orders(self, mock_manufacturing_service, mock_legal_entity_id):
        result = await list_work_orders(
            product_id=None,
            status=WorkOrderStatus.DRAFT,
            start_date=date.today(),
            end_date=date.today(),
            page=1,
            page_size=20,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_manufacturing_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], WorkOrderResponseSchema)
        mock_manufacturing_service.list_work_orders.assert_called_once()

    async def test_get_work_order_success(self, mock_manufacturing_service, mock_legal_entity_id):
        wo_id = uuid4()
        result = await get_work_order(
            work_order_id=wo_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_manufacturing_service,
        )
        assert isinstance(result, WorkOrderResponseSchema)
        mock_manufacturing_service.get_work_order_by_id.assert_called_once_with(wo_id, mock_legal_entity_id)

    async def test_update_work_order_success(self, mock_manufacturing_service, mock_token_payload, mock_legal_entity_id):
        wo_id = uuid4()
        request = WorkOrderUpdateSchema(planned_quantity=Decimal("200"))
        result = await update_work_order(
            work_order_id=wo_id,
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_manufacturing_service,
        )
        assert isinstance(result, WorkOrderResponseSchema)
        mock_manufacturing_service.update_work_order.assert_called_once()

    async def test_release_work_order_success(self, mock_manufacturing_service, mock_token_payload, mock_legal_entity_id):
        wo_id = uuid4()
        request = WorkOrderReleaseSchema(actual_start_date=date.today())
        result = await release_work_order(
            work_order_id=wo_id,
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_manufacturing_service,
        )
        assert isinstance(result, WorkOrderResponseSchema)
        mock_manufacturing_service.release_work_order.assert_called_once()

    async def test_complete_work_order_success(self, mock_manufacturing_service, mock_token_payload, mock_legal_entity_id):
        wo_id = uuid4()
        request = WorkOrderCompletionSchema(completed_quantity=Decimal("100"))
        result = await complete_work_order(
            work_order_id=wo_id,
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_manufacturing_service,
        )
        assert isinstance(result, WorkOrderResponseSchema)
        mock_manufacturing_service.complete_work_order.assert_called_once()

    async def test_cancel_work_order_success(self, mock_manufacturing_service, mock_token_payload, mock_legal_entity_id):
        wo_id = uuid4()
        result = await cancel_work_order(
            work_order_id=wo_id,
            reason="Test cancel",
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_manufacturing_service,
        )
        assert result["status"] == "cancelled"
        mock_manufacturing_service.cancel_work_order.assert_called_once_with(
            wo_id, "Test cancel", mock_token_payload.user_id, mock_legal_entity_id
        )

    async def test_close_work_order_success(self, mock_manufacturing_service, mock_token_payload, mock_legal_entity_id):
        wo_id = uuid4()
        result = await close_work_order(
            work_order_id=wo_id,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_manufacturing_service,
        )
        assert isinstance(result, WorkOrderResponseSchema)
        mock_manufacturing_service.close_work_order.assert_called_once_with(
            wo_id, mock_token_payload.user_id, mock_legal_entity_id
        )


@pytest.mark.asyncio
class TestWIPEndpoints:
    async def test_list_wip(self, mock_manufacturing_service, mock_legal_entity_id):
        result = await list_wip(
            work_order_id=None,
            product_id=None,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_manufacturing_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert "work_order_number" in result[0]
        mock_manufacturing_service.list_wip.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            work_order_id=None,
            product_id=None,
        )


@pytest.mark.asyncio
class TestCostCardEndpoints:
    async def test_create_cost_card_success(self, mock_manufacturing_service, mock_token_payload, mock_legal_entity_id):
        request = CostCardCreateSchema(
            cost_card_code="CC-001",
            product_id=uuid4(),
            material_cost=Decimal("10"),
        )
        result = await create_cost_card(
            request=request,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            service=mock_manufacturing_service,
        )
        assert isinstance(result, CostCardResponseSchema)
        assert result.cost_card_code == "CC-001"
        mock_manufacturing_service.create_cost_card.assert_called_once()

    async def test_list_cost_cards(self, mock_manufacturing_service, mock_legal_entity_id):
        result = await list_cost_cards(
            product_id=None,
            effective_as_of=date.today(),
            is_active=True,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_manufacturing_service,
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], CostCardResponseSchema)


@pytest.mark.asyncio
class TestVarianceAnalysis:
    async def test_get_variance_analysis_success(self, mock_manufacturing_service, mock_legal_entity_id):
        wo_id = uuid4()
        result = await get_variance_analysis(
            work_order_id=wo_id,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_manufacturing_service,
        )
        assert isinstance(result, VarianceAnalysisResponseSchema)
        assert result.total_variance == Decimal("10")
        mock_manufacturing_service.analyze_variance.assert_called_once_with(wo_id, mock_legal_entity_id)

    async def test_variance_not_found(self, mock_manufacturing_service, mock_legal_entity_id):
        mock_manufacturing_service.analyze_variance.return_value = None
        with pytest.raises(HTTPException) as exc:
            await get_variance_analysis(
                work_order_id=uuid4(),
                _permission=None,
                legal_entity_id=mock_legal_entity_id,
                service=mock_manufacturing_service,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestHPPClose:
    async def test_close_hpp_success(self, mock_hpp_use_case, mock_token_payload, mock_legal_entity_id):
        result = await close_hpp_period(
            fiscal_year=2025,
            period=1,
            idempotency_key=None,
            _permission=None,
            current_user=mock_token_payload,
            legal_entity_id=mock_legal_entity_id,
            hpp_close_use_case=mock_hpp_use_case,
        )
        assert result["status"] == "completed"
        assert result["work_orders_processed"] == 5
        mock_hpp_use_case.execute.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            fiscal_year=2025,
            period=1,
            closed_by=mock_token_payload.user_id,
        )


@pytest.mark.asyncio
class TestExport:
    async def test_export_work_orders(self, mock_manufacturing_service, mock_legal_entity_id):
        start = date(2025, 1, 1)
        end = date(2025, 1, 31)
        response = await export_work_orders(
            start_date=start,
            end_date=end,
            format="csv",
            status=WorkOrderStatus.COMPLETED,
            _permission=None,
            legal_entity_id=mock_legal_entity_id,
            service=mock_manufacturing_service,
        )
        assert response.body == b"csv data"
        assert response.media_type == "text/csv"
        assert "attachment" in response.headers["Content-Disposition"]
        mock_manufacturing_service.export_work_orders.assert_called_once_with(
            legal_entity_id=mock_legal_entity_id,
            start_date=start,
            end_date=end,
            format="csv",
            status="completed",
        )