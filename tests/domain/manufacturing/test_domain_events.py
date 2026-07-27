# test_domain_events.py
# ======================
# Comprehensive tests for domain/manufacturing/domain_events.py.
# Covers DomainEventType enum methods, base DomainEvent class,
# all concrete event classes, serialization, helpers, and publisher protocol.

import json
from datetime import UTC, datetime, date
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from domain.manufacturing.bill_of_materials_entity import BillOfMaterialsEntity, BOMStatus, BOMItem
from domain.manufacturing.domain_events import (
    BOMActivatedEvent,
    BOMCreatedEvent,
    BOMItemAddedEvent,
    BOMObsoletedEvent,
    BOMUpdatedEvent,
    CostCardUpdatedEvent,
    DomainEvent,
    DomainEventPublisher,
    DomainEventType,
    HPPCalculatedEvent,
    LaborPostedEvent,
    MaterialIssuedEvent,
    OverheadAppliedEvent,
    ProductionCompletedEvent,
    StandardCostActivatedEvent,
    StandardCostCreatedEvent,
    VarianceAnalyzedEvent,
    WorkOrderApprovedEvent,
    WorkOrderCancelledEvent,
    WorkOrderCompletedEvent,
    WorkOrderCreatedEvent,
    WorkOrderStartedEvent,
    deserialize_domain_event,
    event_to_audit_log,
    serialize_domain_event,
)
from domain.manufacturing.work_order_entity import WorkOrderEntity, WorkOrderStatus, WorkOrderPriority
from domain.manufacturing.cost_element_enum import CostElement


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def sample_work_order() -> WorkOrderEntity:
    """Create a sample WorkOrderEntity for testing."""
    now = datetime(2025, 1, 1, 8, 0, tzinfo=UTC)
    later = datetime(2025, 1, 10, 17, 0, tzinfo=UTC)
    return WorkOrderEntity(
        work_order_id=uuid4(),
        work_order_number="WO-001",
        product_id=uuid4(),
        product_code="PROD-001",
        product_name="Test Product",
        bom_id=uuid4(),
        bom_version=1,
        planned_quantity=Decimal("100"),
        completed_quantity=Decimal("0"),
        status=WorkOrderStatus.DRAFT,
        priority=WorkOrderPriority.NORMAL,
        planned_start_date=now,
        planned_end_date=later,
        actual_start_date=None,
        actual_end_date=None,
        created_by="tester",
        version=1,
    )


@pytest.fixture
def sample_bom() -> BillOfMaterialsEntity:
    """Create a sample BillOfMaterialsEntity for testing."""
    items = [
        BOMItem(
            item_id=uuid4(),
            item_code="MAT-001",
            item_name="Raw Material A",
            quantity=Decimal("2"),
            unit_cost=Decimal("50"),
            cost_element=CostElement.MATERIAL,
        ),
        BOMItem(
            item_id=uuid4(),
            item_code="LAB-001",
            item_name="Labor",
            quantity=Decimal("1"),
            unit_cost=Decimal("30"),
            cost_element=CostElement.LABOR,
        ),
    ]
    return BillOfMaterialsEntity(
        bom_id=uuid4(),
        bom_code="BOM-001",
        product_id=uuid4(),
        product_code="PROD-001",
        product_name="Test Product",
        version=1,
        quantity_per_assembly=Decimal("1"),
        unit_of_measure="PCS",
        items=items,
        status=BOMStatus.DRAFT,
        effective_date=date(2025, 1, 1),
        created_by="tester",
    )


# ----------------------------------------------------------------------
# DomainEventType Enum Tests
# ----------------------------------------------------------------------
class TestDomainEventType:
    def test_members_exist(self):
        assert hasattr(DomainEventType, "BOM_CREATED")
        assert hasattr(DomainEventType, "BOM_UPDATED")
        assert hasattr(DomainEventType, "BOM_ACTIVATED")
        assert hasattr(DomainEventType, "BOM_OBSOLETED")
        assert hasattr(DomainEventType, "BOM_ITEM_ADDED")
        assert hasattr(DomainEventType, "BOM_ITEM_REMOVED")
        assert hasattr(DomainEventType, "BOM_ITEM_UPDATED")
        assert hasattr(DomainEventType, "BOM_VERSION_INCREMENTED")
        assert hasattr(DomainEventType, "WORK_ORDER_CREATED")
        assert hasattr(DomainEventType, "WORK_ORDER_APPROVED")
        assert hasattr(DomainEventType, "WORK_ORDER_STARTED")
        assert hasattr(DomainEventType, "WORK_ORDER_COMPLETED")
        assert hasattr(DomainEventType, "WORK_ORDER_CANCELLED")
        assert hasattr(DomainEventType, "WORK_ORDER_UPDATED")
        assert hasattr(DomainEventType, "MATERIAL_ISSUED")
        assert hasattr(DomainEventType, "LABOR_POSTED")
        assert hasattr(DomainEventType, "OVERHEAD_APPLIED")
        assert hasattr(DomainEventType, "PRODUCTION_COMPLETED")
        assert hasattr(DomainEventType, "WIP_CREATED")
        assert hasattr(DomainEventType, "WIP_UPDATED")
        assert hasattr(DomainEventType, "WIP_COMPLETED")
        assert hasattr(DomainEventType, "WIP_ADJUSTED")
        assert hasattr(DomainEventType, "STANDARD_COST_CREATED")
        assert hasattr(DomainEventType, "STANDARD_COST_UPDATED")
        assert hasattr(DomainEventType, "STANDARD_COST_ACTIVATED")
        assert hasattr(DomainEventType, "STANDARD_COST_OBSOLETED")
        assert hasattr(DomainEventType, "COST_CARD_CREATED")
        assert hasattr(DomainEventType, "COST_CARD_UPDATED")
        assert hasattr(DomainEventType, "COST_CARD_CLOSED")
        assert hasattr(DomainEventType, "HPP_CALCULATED")
        assert hasattr(DomainEventType, "VARIANCE_ANALYZED")
        assert hasattr(DomainEventType, "ROUTING_CREATED")
        assert hasattr(DomainEventType, "ROUTING_ACTIVATED")
        assert hasattr(DomainEventType, "ROUTING_OBSOLETED")

    def test_member_is_instance(self):
        assert isinstance(DomainEventType.BOM_CREATED, DomainEventType)

    def test_is_work_order_event(self):
        # Work order events should return True
        work_order_events = [
            DomainEventType.WORK_ORDER_CREATED,
            DomainEventType.WORK_ORDER_APPROVED,
            DomainEventType.WORK_ORDER_STARTED,
            DomainEventType.WORK_ORDER_COMPLETED,
            DomainEventType.WORK_ORDER_CANCELLED,
            DomainEventType.WORK_ORDER_UPDATED,
        ]
        for ev in work_order_events:
            assert ev.is_work_order_event() is True

        # Non-work-order events should return False
        non_work_order = [
            DomainEventType.BOM_CREATED,
            DomainEventType.MATERIAL_ISSUED,
            DomainEventType.HPP_CALCULATED,
        ]
        for ev in non_work_order:
            assert ev.is_work_order_event() is False

    def test_is_production_event(self):
        # Production events should return True
        production_events = [
            DomainEventType.MATERIAL_ISSUED,
            DomainEventType.LABOR_POSTED,
            DomainEventType.OVERHEAD_APPLIED,
            DomainEventType.PRODUCTION_COMPLETED,
        ]
        for ev in production_events:
            assert ev.is_production_event() is True

        # Non-production events should return False
        non_production = [
            DomainEventType.WORK_ORDER_CREATED,
            DomainEventType.BOM_CREATED,
            DomainEventType.HPP_CALCULATED,
        ]
        for ev in non_production:
            assert ev.is_production_event() is False

    def test_is_cost_event(self):
        # Cost events should return True
        cost_events = [
            DomainEventType.STANDARD_COST_CREATED,
            DomainEventType.STANDARD_COST_UPDATED,
            DomainEventType.STANDARD_COST_ACTIVATED,
            DomainEventType.STANDARD_COST_OBSOLETED,
            DomainEventType.COST_CARD_CREATED,
            DomainEventType.COST_CARD_UPDATED,
            DomainEventType.COST_CARD_CLOSED,
            DomainEventType.HPP_CALCULATED,
            DomainEventType.VARIANCE_ANALYZED,
        ]
        for ev in cost_events:
            assert ev.is_cost_event() is True

        # Non-cost events should return False
        non_cost = [
            DomainEventType.WORK_ORDER_CREATED,
            DomainEventType.BOM_CREATED,
            DomainEventType.MATERIAL_ISSUED,
        ]
        for ev in non_cost:
            assert ev.is_cost_event() is False


# ----------------------------------------------------------------------
# DomainEvent Base Class
# ----------------------------------------------------------------------
class TestDomainEvent:
    def test_construction_valid(self):
        event_id = uuid4()
        agg_id = uuid4()
        now = datetime(2025, 1, 1, 10, 0, tzinfo=UTC)
        event = DomainEvent(
            event_id=event_id,
            event_type=DomainEventType.WORK_ORDER_CREATED,
            aggregate_id=agg_id,
            aggregate_version=1,
            occurred_at=now,
            event_data={"key": "value"},
            user_id="alice",
            correlation_id="corr-123",
            causation_id="cause-456",
        )
        assert event.event_id == event_id
        assert event.event_type == DomainEventType.WORK_ORDER_CREATED
        assert event.aggregate_id == agg_id
        assert event.aggregate_version == 1
        assert event.occurred_at == now
        assert event.event_data == {"key": "value"}
        assert event.user_id == "alice"
        assert event.correlation_id == "corr-123"
        assert event.causation_id == "cause-456"

    def test_validation_aggregate_version_zero_raises(self):
        with pytest.raises(ValueError, match="aggregate_version must be >= 1"):
            DomainEvent(
                event_id=uuid4(),
                event_type=DomainEventType.WORK_ORDER_CREATED,
                aggregate_id=uuid4(),
                aggregate_version=0,
                occurred_at=datetime.now(UTC),
                event_data={},
            )

    def test_validation_naive_datetime_raises(self):
        naive = datetime(2025, 1, 1, 10, 0)
        with pytest.raises(ValueError, match="occurred_at must be timezone-aware"):
            DomainEvent(
                event_id=uuid4(),
                event_type=DomainEventType.WORK_ORDER_CREATED,
                aggregate_id=uuid4(),
                aggregate_version=1,
                occurred_at=naive,
                event_data={},
            )

    def test_to_dict(self):
        event_id = uuid4()
        agg_id = uuid4()
        now = datetime(2025, 1, 1, 10, 0, tzinfo=UTC)
        event = DomainEvent(
            event_id=event_id,
            event_type=DomainEventType.WORK_ORDER_CREATED,
            aggregate_id=agg_id,
            aggregate_version=1,
            occurred_at=now,
            event_data={"key": "value"},
            user_id="alice",
            correlation_id="corr-123",
            causation_id="cause-456",
        )
        d = event.to_dict()
        assert d["event_id"] == str(event_id)
        assert d["event_type"] == "work_order_created"
        assert d["aggregate_id"] == str(agg_id)
        assert d["aggregate_version"] == 1
        assert d["occurred_at"] == now.isoformat()
        assert d["event_data"] == {"key": "value"}
        assert d["user_id"] == "alice"
        assert d["correlation_id"] == "corr-123"
        assert d["causation_id"] == "cause-456"

    def test_from_dict(self):
        data = {
            "event_id": str(uuid4()),
            "event_type": "work_order_created",
            "aggregate_id": str(uuid4()),
            "aggregate_version": 1,
            "occurred_at": "2025-01-01T10:00:00+00:00",
            "event_data": {"key": "value"},
            "user_id": "alice",
            "correlation_id": "corr-123",
            "causation_id": "cause-456",
        }
        event = DomainEvent.from_dict(data)
        assert event.event_id == UUID(data["event_id"])
        assert event.event_type == DomainEventType.WORK_ORDER_CREATED
        assert event.aggregate_id == UUID(data["aggregate_id"])
        assert event.aggregate_version == 1
        assert event.occurred_at == datetime(2025, 1, 1, 10, 0, tzinfo=UTC)
        assert event.event_data == {"key": "value"}
        assert event.user_id == "alice"
        assert event.correlation_id == "corr-123"
        assert event.causation_id == "cause-456"

    def test_to_json_roundtrip(self):
        event = DomainEvent(
            event_id=uuid4(),
            event_type=DomainEventType.WORK_ORDER_CREATED,
            aggregate_id=uuid4(),
            aggregate_version=1,
            occurred_at=datetime.now(UTC),
            event_data={"key": "value"},
        )
        json_str = event.to_json()
        reconstructed = DomainEvent.from_json(json_str)
        assert reconstructed.event_id == event.event_id
        assert reconstructed.event_type == event.event_type
        assert reconstructed.aggregate_id == event.aggregate_id
        assert reconstructed.aggregate_version == event.aggregate_version
        assert reconstructed.occurred_at == event.occurred_at
        assert reconstructed.event_data == event.event_data


# ----------------------------------------------------------------------
# Concrete Event Classes - Tests
# ----------------------------------------------------------------------
class TestWorkOrderCreatedEvent:
    def test_construction(self, sample_work_order):
        agg_id = uuid4()
        event = WorkOrderCreatedEvent(
            aggregate_id=agg_id,
            aggregate_version=2,
            work_order=sample_work_order,
            created_by="alice",
            user_id="user1",
            correlation_id="corr1",
            causation_id="cause1",
        )
        assert event.event_type == DomainEventType.WORK_ORDER_CREATED
        assert event.aggregate_id == agg_id
        assert event.aggregate_version == 2
        assert event.user_id == "user1"
        assert event.event_data["work_order_id"] == str(sample_work_order.work_order_id)
        assert event.event_data["work_order_number"] == "WO-001"
        assert event.event_data["product_code"] == "PROD-001"
        assert event.event_data["created_by"] == "alice"


class TestWorkOrderApprovedEvent:
    def test_construction(self, sample_work_order):
        agg_id = uuid4()
        event = WorkOrderApprovedEvent(
            aggregate_id=agg_id,
            aggregate_version=3,
            work_order=sample_work_order,
            approved_by="bob",
            user_id="user2",
        )
        assert event.event_type == DomainEventType.WORK_ORDER_APPROVED
        assert event.event_data["work_order_number"] == "WO-001"
        assert event.event_data["approved_by"] == "bob"
        assert event.event_data["previous_status"] == "draft"
        assert event.event_data["new_status"] == "approved"


class TestWorkOrderStartedEvent:
    def test_construction(self, sample_work_order):
        agg_id = uuid4()
        event = WorkOrderStartedEvent(
            aggregate_id=agg_id,
            aggregate_version=4,
            work_order=sample_work_order,
            started_by="carol",
        )
        assert event.event_type == DomainEventType.WORK_ORDER_STARTED
        assert event.event_data["work_order_number"] == "WO-001"
        assert event.event_data["started_by"] == "carol"


class TestWorkOrderCompletedEvent:
    def test_construction(self, sample_work_order):
        agg_id = uuid4()
        event = WorkOrderCompletedEvent(
            aggregate_id=agg_id,
            aggregate_version=5,
            work_order=sample_work_order,
            completed_quantity=Decimal("100"),
            completed_by="dave",
            is_fully_completed=True,
        )
        assert event.event_type == DomainEventType.WORK_ORDER_COMPLETED
        assert event.event_data["completed_quantity"] == "100"
        assert event.event_data["is_fully_completed"] is True


class TestWorkOrderCancelledEvent:
    def test_construction(self, sample_work_order):
        agg_id = uuid4()
        event = WorkOrderCancelledEvent(
            aggregate_id=agg_id,
            aggregate_version=6,
            work_order=sample_work_order,
            reason="Cancelled due to material shortage",
            cancelled_by="eve",
        )
        assert event.event_type == DomainEventType.WORK_ORDER_CANCELLED
        assert event.event_data["reason"] == "Cancelled due to material shortage"
        assert event.event_data["cancelled_by"] == "eve"


class TestBOMCreatedEvent:
    def test_construction(self, sample_bom):
        agg_id = uuid4()
        event = BOMCreatedEvent(
            aggregate_id=agg_id,
            aggregate_version=1,
            bom=sample_bom,
            created_by="alice",
        )
        assert event.event_type == DomainEventType.BOM_CREATED
        assert event.event_data["bom_code"] == "BOM-001"
        assert event.event_data["product_code"] == "PROD-001"
        assert event.event_data["item_count"] == 2
        assert event.event_data["total_cost"] == str(sample_bom.get_total_cost())


class TestBOMUpdatedEvent:
    def test_construction(self):
        agg_id = uuid4()
        bom_id = uuid4()
        changes = {"name": "Updated BOM"}
        event = BOMUpdatedEvent(
            aggregate_id=agg_id,
            aggregate_version=2,
            bom_id=bom_id,
            bom_code="BOM-001",
            changes=changes,
            updated_by="bob",
        )
        assert event.event_type == DomainEventType.BOM_UPDATED
        assert event.event_data["bom_id"] == str(bom_id)
        assert event.event_data["changes"] == changes
        assert event.event_data["updated_by"] == "bob"


class TestBOMActivatedEvent:
    def test_construction(self, sample_bom):
        agg_id = uuid4()
        event = BOMActivatedEvent(
            aggregate_id=agg_id,
            aggregate_version=3,
            bom=sample_bom,
            activated_by="carol",
        )
        assert event.event_type == DomainEventType.BOM_ACTIVATED
        assert event.event_data["bom_code"] == "BOM-001"
        assert event.event_data["activated_by"] == "carol"
        assert event.event_data["previous_status"] == "draft"
        assert event.event_data["new_status"] == "active"


class TestBOMObsoletedEvent:
    def test_construction(self, sample_bom):
        agg_id = uuid4()
        event = BOMObsoletedEvent(
            aggregate_id=agg_id,
            aggregate_version=4,
            bom=sample_bom,
            reason="Replaced by new BOM",
            obsoleted_by="dave",
        )
        assert event.event_type == DomainEventType.BOM_OBSOLETED
        assert event.event_data["reason"] == "Replaced by new BOM"
        assert event.event_data["obsoleted_by"] == "dave"


class TestBOMItemAddedEvent:
    def test_construction(self):
        agg_id = uuid4()
        bom_id = uuid4()
        item = BOMItem(
            item_id=uuid4(),
            item_code="MAT-002",
            item_name="Raw Material B",
            quantity=Decimal("3"),
            unit_cost=Decimal("75"),
            cost_element=CostElement.MATERIAL,
        )
        event = BOMItemAddedEvent(
            aggregate_id=agg_id,
            aggregate_version=5,
            bom_id=bom_id,
            bom_code="BOM-001",
            item=item,
            added_by="eve",
        )
        assert event.event_type == DomainEventType.BOM_ITEM_ADDED
        assert event.event_data["item_code"] == "MAT-002"
        assert event.event_data["quantity"] == "3"
        assert event.event_data["added_by"] == "eve"


class TestMaterialIssuedEvent:
    def test_construction(self):
        agg_id = uuid4()
        event = MaterialIssuedEvent(
            aggregate_id=agg_id,
            aggregate_version=1,
            work_order_id=uuid4(),
            work_order_number="WO-001",
            material_id=uuid4(),
            material_code="MAT-001",
            material_name="Raw Material A",
            quantity=Decimal("10"),
            cost=Decimal("500"),
            issued_by="alice",
        )
        assert event.event_type == DomainEventType.MATERIAL_ISSUED
        assert event.event_data["work_order_number"] == "WO-001"
        assert event.event_data["quantity"] == "10"
        assert event.event_data["cost"] == "500"


class TestLaborPostedEvent:
    def test_construction(self):
        agg_id = uuid4()
        event = LaborPostedEvent(
            aggregate_id=agg_id,
            aggregate_version=1,
            work_order_id=uuid4(),
            work_order_number="WO-001",
            employee_id=uuid4(),
            employee_name="John Doe",
            hours=Decimal("8"),
            rate=Decimal("50"),
            cost=Decimal("400"),
            posted_by="bob",
        )
        assert event.event_type == DomainEventType.LABOR_POSTED
        assert event.event_data["employee_name"] == "John Doe"
        assert event.event_data["hours"] == "8"
        assert event.event_data["cost"] == "400"


class TestOverheadAppliedEvent:
    def test_construction(self):
        agg_id = uuid4()
        event = OverheadAppliedEvent(
            aggregate_id=agg_id,
            aggregate_version=1,
            work_order_id=uuid4(),
            work_order_number="WO-001",
            overhead_pool="Factory Overhead",
            amount=Decimal("200"),
            allocation_basis="Machine Hours",
            applied_by="carol",
        )
        assert event.event_type == DomainEventType.OVERHEAD_APPLIED
        assert event.event_data["overhead_pool"] == "Factory Overhead"
        assert event.event_data["amount"] == "200"


class TestProductionCompletedEvent:
    def test_construction(self):
        agg_id = uuid4()
        event = ProductionCompletedEvent(
            aggregate_id=agg_id,
            aggregate_version=1,
            work_order_id=uuid4(),
            work_order_number="WO-001",
            product_id=uuid4(),
            product_code="PROD-001",
            product_name="Product A",
            quantity=Decimal("50"),
            unit_cost=Decimal("20"),
            total_cost=Decimal("1000"),
            completed_by="dave",
        )
        assert event.event_type == DomainEventType.PRODUCTION_COMPLETED
        assert event.event_data["product_code"] == "PROD-001"
        assert event.event_data["quantity"] == "50"
        assert event.event_data["total_cost"] == "1000"


class TestCostCardUpdatedEvent:
    def test_construction(self):
        agg_id = uuid4()
        event = CostCardUpdatedEvent(
            aggregate_id=agg_id,
            aggregate_version=1,
            product_id=uuid4(),
            period="2025-01",
            total_cost=Decimal("5000"),
            unit_cost=Decimal("50"),
            user_id="eve",
        )
        assert event.event_type == DomainEventType.COST_CARD_UPDATED
        assert event.event_data["period"] == "2025-01"
        assert event.event_data["total_cost"] == "5000"
        assert event.event_data["unit_cost"] == "50"


class TestHPPCalculatedEvent:
    def test_construction(self):
        agg_id = uuid4()
        start = datetime(2025, 1, 1, tzinfo=UTC)
        end = datetime(2025, 1, 31, tzinfo=UTC)
        event = HPPCalculatedEvent(
            aggregate_id=agg_id,
            aggregate_version=1,
            product_id=uuid4(),
            period_start=start,
            period_end=end,
            units_produced=Decimal("100"),
            total_cost=Decimal("5000"),
            unit_hpp=Decimal("50"),
            calculated_by="frank",
        )
        assert event.event_type == DomainEventType.HPP_CALCULATED
        assert event.event_data["units_produced"] == "100"
        assert event.event_data["unit_hpp"] == "50"


class TestStandardCostCreatedEvent:
    def test_construction(self):
        agg_id = uuid4()
        event = StandardCostCreatedEvent(
            aggregate_id=agg_id,
            aggregate_version=1,
            standard_cost_id=uuid4(),
            product_id=uuid4(),
            product_code="PROD-001",
            product_name="Product A",
            material_cost=Decimal("10"),
            labor_cost=Decimal("5"),
            overhead_cost=Decimal("3"),
            total_cost=Decimal("18"),
            effective_date=datetime(2025, 1, 1, tzinfo=UTC),
            created_by="grace",
        )
        assert event.event_type == DomainEventType.STANDARD_COST_CREATED
        assert event.event_data["product_code"] == "PROD-001"
        assert event.event_data["total_cost"] == "18"


class TestStandardCostActivatedEvent:
    def test_construction(self):
        agg_id = uuid4()
        event = StandardCostActivatedEvent(
            aggregate_id=agg_id,
            aggregate_version=2,
            standard_cost_id=uuid4(),
            product_id=uuid4(),
            product_code="PROD-001",
            product_name="Product A",
            activated_by="hank",
        )
        assert event.event_type == DomainEventType.STANDARD_COST_ACTIVATED
        assert event.event_data["product_code"] == "PROD-001"
        assert event.event_data["activated_by"] == "hank"


class TestVarianceAnalyzedEvent:
    def test_construction(self):
        agg_id = uuid4()
        event = VarianceAnalyzedEvent(
            aggregate_id=agg_id,
            aggregate_version=1,
            work_order_id=uuid4(),
            work_order_number="WO-001",
            total_variance=Decimal("200"),
            variance_type="unfavorable",
            material_variance=Decimal("100"),
            labor_variance=Decimal("50"),
            overhead_variance=Decimal("50"),
            analyzed_by="ivy",
        )
        assert event.event_type == DomainEventType.VARIANCE_ANALYZED
        assert event.event_data["work_order_number"] == "WO-001"
        assert event.event_data["total_variance"] == "200"
        assert event.event_data["variance_type"] == "unfavorable"


# ----------------------------------------------------------------------
# DomainEventPublisher (Protocol)
# ----------------------------------------------------------------------
class TestDomainEventPublisher:
    def test_class_defined(self):
        assert DomainEventPublisher is not None

    async def test_publish_raises_not_implemented(self):
        publisher = DomainEventPublisher()
        with pytest.raises(NotImplementedError):
            await publisher.publish(MagicMock())

    async def test_publish_many_raises_not_implemented(self):
        publisher = DomainEventPublisher()
        with pytest.raises(NotImplementedError):
            await publisher.publish_many([MagicMock()])


# ----------------------------------------------------------------------
# Helper Functions
# ----------------------------------------------------------------------
class TestHelpers:
    def test_serialize_domain_event(self, sample_work_order):
        agg_id = uuid4()
        event = WorkOrderCreatedEvent(
            aggregate_id=agg_id,
            aggregate_version=1,
            work_order=sample_work_order,
            created_by="alice",
        )
        json_str = serialize_domain_event(event)
        data = json.loads(json_str)
        assert data["event_type"] == "work_order_created"
        assert data["aggregate_id"] == str(agg_id)
        assert data["event_data"]["work_order_number"] == "WO-001"

    def test_deserialize_domain_event(self, sample_work_order):
        agg_id = uuid4()
        event = WorkOrderCreatedEvent(
            aggregate_id=agg_id,
            aggregate_version=1,
            work_order=sample_work_order,
            created_by="alice",
        )
        json_str = serialize_domain_event(event)
        reconstructed = deserialize_domain_event(json_str)
        assert reconstructed.event_id == event.event_id
        assert reconstructed.event_type == event.event_type
        assert reconstructed.aggregate_id == event.aggregate_id
        assert reconstructed.aggregate_version == event.aggregate_version
        assert reconstructed.event_data == event.event_data

    def test_deserialize_domain_event_invalid_json(self):
        with pytest.raises(json.JSONDecodeError):
            deserialize_domain_event("invalid json")

    def test_event_to_audit_log(self, sample_work_order):
        agg_id = uuid4()
        event = WorkOrderCreatedEvent(
            aggregate_id=agg_id,
            aggregate_version=1,
            work_order=sample_work_order,
            created_by="alice",
            user_id="user123",
            correlation_id="corr-456",
        )
        log = event_to_audit_log(event)
        assert log["event_id"] == str(event.event_id)
        assert log["event_type"] == "work_order_created"
        assert log["aggregate_id"] == str(agg_id)
        assert log["aggregate_version"] == 1
        assert log["user_id"] == "user123"
        assert log["correlation_id"] == "corr-456"
        assert log["summary"] == "WO-001"

    def test_event_to_audit_log_with_bom_event(self, sample_bom):
        agg_id = uuid4()
        event = BOMCreatedEvent(
            aggregate_id=agg_id,
            aggregate_version=1,
            bom=sample_bom,
            created_by="bob",
        )
        log = event_to_audit_log(event)
        assert log["summary"] == "BOM-001"


# ----------------------------------------------------------------------
# Aliases (ensure they are defined)
# ----------------------------------------------------------------------
def test_aliases_exist():
    from domain.manufacturing.domain_events import (
        BOMCreated,
        BOMUpdated,
        BOMActivated,
        BOMObsoleted,
        BOMItemAdded,
        WorkOrderCreated,
        WorkOrderApproved,
        WorkOrderStarted,
        WorkOrderCompleted,
        WorkOrderCancelled,
        MaterialIssued,
        LaborPosted,
        OverheadApplied,
        ProductionCompleted,
        CostCardUpdated,
        HPPCalculated,
        StandardCostCreated,
        StandardCostActivated,
        VarianceAnalyzed,
    )
    assert BOMCreated is BOMCreatedEvent
    assert BOMUpdated is BOMUpdatedEvent
    assert BOMActivated is BOMActivatedEvent
    assert BOMObsoleted is BOMObsoletedEvent
    assert BOMItemAdded is BOMItemAddedEvent
    assert WorkOrderCreated is WorkOrderCreatedEvent
    assert WorkOrderApproved is WorkOrderApprovedEvent
    assert WorkOrderStarted is WorkOrderStartedEvent
    assert WorkOrderCompleted is WorkOrderCompletedEvent
    assert WorkOrderCancelled is WorkOrderCancelledEvent
    assert MaterialIssued is MaterialIssuedEvent
    assert LaborPosted is LaborPostedEvent
    assert OverheadApplied is OverheadAppliedEvent
    assert ProductionCompleted is ProductionCompletedEvent
    assert CostCardUpdated is CostCardUpdatedEvent
    assert HPPCalculated is HPPCalculatedEvent
    assert StandardCostCreated is StandardCostCreatedEvent
    assert StandardCostActivated is StandardCostActivatedEvent
    assert VarianceAnalyzed is VarianceAnalyzedEvent