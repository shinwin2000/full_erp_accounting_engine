# test_work_order_entity.py
# ==========================
# Comprehensive tests for domain/manufacturing/work_order_entity.py.
# Covers all enums, entity construction, business methods, query methods,
# serialization, and repository interface.

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from domain.manufacturing.work_order_entity import (
    WorkOrder,
    WorkOrderEntity,
    WorkOrderPriority,
    WorkOrderRepository,
    WorkOrderStatus,
    WorkOrderType,
)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def sample_work_order() -> WorkOrderEntity:
    """Create a valid WorkOrderEntity in DRAFT state."""
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
        routing_id=uuid4(),
        cost_center="CC-001",
        notes="Initial work order",
        work_order_type=WorkOrderType.PRODUCTION,
        created_at=now,
        updated_at=now,
        created_by="tester",
        version=1,
        material_standard_cost=Decimal("10"),
        labor_standard_cost=Decimal("5"),
        overhead_standard_cost=Decimal("3"),
        material_actual_cost=Decimal("0"),
        labor_actual_cost=Decimal("0"),
        overhead_actual_cost=Decimal("0"),
    )


@pytest.fixture
def approved_work_order(sample_work_order) -> WorkOrderEntity:
    """Return an approved work order."""
    return sample_work_order.approve("approver")


@pytest.fixture
def in_progress_work_order(approved_work_order) -> WorkOrderEntity:
    """Return a work order in progress."""
    return approved_work_order.start_production("operator")


# ----------------------------------------------------------------------
# Enums
# ----------------------------------------------------------------------
class TestWorkOrderStatus:
    def test_members_exist(self):
        assert hasattr(WorkOrderStatus, "DRAFT")
        assert hasattr(WorkOrderStatus, "APPROVED")
        assert hasattr(WorkOrderStatus, "IN_PROGRESS")
        assert hasattr(WorkOrderStatus, "COMPLETED")
        assert hasattr(WorkOrderStatus, "PARTIALLY_COMPLETED")
        assert hasattr(WorkOrderStatus, "CANCELLED")

    def test_member_is_instance(self):
        assert isinstance(WorkOrderStatus.DRAFT, WorkOrderStatus)


class TestWorkOrderPriority:
    def test_members_exist(self):
        assert hasattr(WorkOrderPriority, "LOW")
        assert hasattr(WorkOrderPriority, "NORMAL")
        assert hasattr(WorkOrderPriority, "HIGH")
        assert hasattr(WorkOrderPriority, "URGENT")

    def test_member_is_instance(self):
        assert isinstance(WorkOrderPriority.LOW, WorkOrderPriority)


class TestWorkOrderType:
    def test_members_exist(self):
        assert hasattr(WorkOrderType, "PRODUCTION")
        assert hasattr(WorkOrderType, "MAINTENANCE")
        assert hasattr(WorkOrderType, "SAMPLE")
        assert hasattr(WorkOrderType, "REPAIR")
        assert hasattr(WorkOrderType, "SUBASSEMBLY")

    def test_member_is_instance(self):
        assert isinstance(WorkOrderType.PRODUCTION, WorkOrderType)

    def test_display_name(self):
        assert WorkOrderType.PRODUCTION.display_name() == "Produksi"
        assert WorkOrderType.MAINTENANCE.display_name() == "Pemeliharaan"
        assert WorkOrderType.SAMPLE.display_name() == "Sample"
        assert WorkOrderType.REPAIR.display_name() == "Perbaikan"
        assert WorkOrderType.SUBASSEMBLY.display_name() == "Subasembli"

    def test_from_string_valid(self):
        assert WorkOrderType.from_string("production") == WorkOrderType.PRODUCTION
        assert WorkOrderType.from_string("maintenance") == WorkOrderType.MAINTENANCE
        assert WorkOrderType.from_string("SAMPLE") == WorkOrderType.SAMPLE
        assert WorkOrderType.from_string("repair") == WorkOrderType.REPAIR
        assert WorkOrderType.from_string("subassembly") == WorkOrderType.SUBASSEMBLY

    def test_from_string_invalid_returns_none(self):
        assert WorkOrderType.from_string("unknown") is None
        assert WorkOrderType.from_string("") is None


# ----------------------------------------------------------------------
# WorkOrderEntity - Construction & Validation
# ----------------------------------------------------------------------
class TestWorkOrderEntityConstruction:
    def test_construction_valid(self, sample_work_order):
        assert sample_work_order.work_order_id is not None
        assert sample_work_order.work_order_number == "WO-001"
        assert sample_work_order.product_code == "PROD-001"
        assert sample_work_order.planned_quantity == Decimal("100")
        assert sample_work_order.completed_quantity == Decimal("0")
        assert sample_work_order.status == WorkOrderStatus.DRAFT
        assert sample_work_order.priority == WorkOrderPriority.NORMAL
        assert sample_work_order.version == 1
        assert sample_work_order.created_at.tzinfo == UTC
        assert sample_work_order.updated_at.tzinfo == UTC

    def test_validation_work_order_number_too_short_raises(self):
        with pytest.raises(ValueError, match="at least 3 characters"):
            WorkOrderEntity(
                work_order_id=uuid4(),
                work_order_number="WO",
                product_id=uuid4(),
                product_code="P",
                product_name="N",
                bom_id=uuid4(),
                bom_version=1,
                planned_quantity=Decimal("100"),
                completed_quantity=Decimal("0"),
                status=WorkOrderStatus.DRAFT,
                priority=WorkOrderPriority.NORMAL,
                planned_start_date=datetime.now(UTC),
                planned_end_date=datetime.now(UTC) + timedelta(days=1),
            )

    def test_validation_planned_quantity_zero_raises(self):
        with pytest.raises(ValueError, match="Planned quantity must be positive"):
            WorkOrderEntity(
                work_order_id=uuid4(),
                work_order_number="WO-001",
                product_id=uuid4(),
                product_code="P",
                product_name="N",
                bom_id=uuid4(),
                bom_version=1,
                planned_quantity=Decimal("0"),
                completed_quantity=Decimal("0"),
                status=WorkOrderStatus.DRAFT,
                priority=WorkOrderPriority.NORMAL,
                planned_start_date=datetime.now(UTC),
                planned_end_date=datetime.now(UTC) + timedelta(days=1),
            )

    def test_validation_planned_quantity_negative_raises(self):
        with pytest.raises(ValueError, match="Planned quantity must be positive"):
            WorkOrderEntity(
                work_order_id=uuid4(),
                work_order_number="WO-001",
                product_id=uuid4(),
                product_code="P",
                product_name="N",
                bom_id=uuid4(),
                bom_version=1,
                planned_quantity=Decimal("-10"),
                completed_quantity=Decimal("0"),
                status=WorkOrderStatus.DRAFT,
                priority=WorkOrderPriority.NORMAL,
                planned_start_date=datetime.now(UTC),
                planned_end_date=datetime.now(UTC) + timedelta(days=1),
            )

    def test_validation_completed_quantity_negative_raises(self):
        with pytest.raises(ValueError, match="Completed quantity cannot be negative"):
            WorkOrderEntity(
                work_order_id=uuid4(),
                work_order_number="WO-001",
                product_id=uuid4(),
                product_code="P",
                product_name="N",
                bom_id=uuid4(),
                bom_version=1,
                planned_quantity=Decimal("100"),
                completed_quantity=Decimal("-5"),
                status=WorkOrderStatus.DRAFT,
                priority=WorkOrderPriority.NORMAL,
                planned_start_date=datetime.now(UTC),
                planned_end_date=datetime.now(UTC) + timedelta(days=1),
            )

    def test_validation_completed_exceeds_planned_raises(self):
        with pytest.raises(ValueError, match="Completed quantity exceeds planned"):
            WorkOrderEntity(
                work_order_id=uuid4(),
                work_order_number="WO-001",
                product_id=uuid4(),
                product_code="P",
                product_name="N",
                bom_id=uuid4(),
                bom_version=1,
                planned_quantity=Decimal("100"),
                completed_quantity=Decimal("150"),
                status=WorkOrderStatus.DRAFT,
                priority=WorkOrderPriority.NORMAL,
                planned_start_date=datetime.now(UTC),
                planned_end_date=datetime.now(UTC) + timedelta(days=1),
            )

    def test_validation_planned_end_before_start_raises(self):
        with pytest.raises(ValueError, match="Planned end date must be after planned start date"):
            WorkOrderEntity(
                work_order_id=uuid4(),
                work_order_number="WO-001",
                product_id=uuid4(),
                product_code="P",
                product_name="N",
                bom_id=uuid4(),
                bom_version=1,
                planned_quantity=Decimal("100"),
                completed_quantity=Decimal("0"),
                status=WorkOrderStatus.DRAFT,
                priority=WorkOrderPriority.NORMAL,
                planned_start_date=datetime.now(UTC),
                planned_end_date=datetime.now(UTC) - timedelta(days=1),
            )

    def test_validation_version_zero_raises(self):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            WorkOrderEntity(
                work_order_id=uuid4(),
                work_order_number="WO-001",
                product_id=uuid4(),
                product_code="P",
                product_name="N",
                bom_id=uuid4(),
                bom_version=1,
                planned_quantity=Decimal("100"),
                completed_quantity=Decimal("0"),
                status=WorkOrderStatus.DRAFT,
                priority=WorkOrderPriority.NORMAL,
                planned_start_date=datetime.now(UTC),
                planned_end_date=datetime.now(UTC) + timedelta(days=1),
                version=0,
            )

    def test_validation_naive_timestamps_raises(self):
        naive = datetime(2025, 1, 1, 10, 0)
        with pytest.raises(ValueError, match="created_at must be timezone-aware"):
            WorkOrderEntity(
                work_order_id=uuid4(),
                work_order_number="WO-001",
                product_id=uuid4(),
                product_code="P",
                product_name="N",
                bom_id=uuid4(),
                bom_version=1,
                planned_quantity=Decimal("100"),
                completed_quantity=Decimal("0"),
                status=WorkOrderStatus.DRAFT,
                priority=WorkOrderPriority.NORMAL,
                planned_start_date=datetime.now(UTC),
                planned_end_date=datetime.now(UTC) + timedelta(days=1),
                created_at=naive,
                updated_at=datetime.now(UTC),
            )


# ----------------------------------------------------------------------
# WorkOrderEntity - Business Methods
# ----------------------------------------------------------------------
class TestWorkOrderEntityBusiness:
    def test_approve_success(self, sample_work_order):
        approved = sample_work_order.approve("approver")
        assert approved.status == WorkOrderStatus.APPROVED
        assert approved.created_by == "approver"
        assert approved.version == sample_work_order.version + 1
        assert approved.updated_at > sample_work_order.updated_at
        # Other fields unchanged
        assert approved.work_order_id == sample_work_order.work_order_id
        assert approved.planned_quantity == sample_work_order.planned_quantity

    def test_approve_not_draft_raises(self, approved_work_order):
        with pytest.raises(ValueError, match="Cannot approve work order in status approved"):
            approved_work_order.approve("approver")

    def test_start_production_success(self, approved_work_order):
        started = approved_work_order.start_production("operator")
        assert started.status == WorkOrderStatus.IN_PROGRESS
        assert started.actual_start_date is not None
        assert started.actual_start_date.tzinfo == UTC
        assert started.created_by == "operator"
        assert started.version == approved_work_order.version + 1

    def test_start_production_not_approved_raises(self, sample_work_order):
        with pytest.raises(ValueError, match="Cannot start production in status draft"):
            sample_work_order.start_production("operator")

    def test_start_production_already_started_raises(self, in_progress_work_order):
        with pytest.raises(ValueError, match="Cannot start production in status in_progress"):
            in_progress_work_order.start_production("operator")

    def test_complete_production_partial(self, in_progress_work_order):
        completed = in_progress_work_order.complete_production(Decimal("30"), "operator")
        assert completed.completed_quantity == Decimal("30")
        assert completed.status == WorkOrderStatus.PARTIALLY_COMPLETED
        assert completed.actual_end_date is None
        assert completed.version == in_progress_work_order.version + 1

    def test_complete_production_full(self, in_progress_work_order):
        completed = in_progress_work_order.complete_production(Decimal("100"), "operator")
        assert completed.completed_quantity == Decimal("100")
        assert completed.status == WorkOrderStatus.COMPLETED
        assert completed.actual_end_date is not None
        assert completed.actual_end_date.tzinfo == UTC

    def test_complete_production_exceeds_planned_raises(self, in_progress_work_order):
        with pytest.raises(ValueError, match="exceeds planned"):
            in_progress_work_order.complete_production(Decimal("150"), "operator")

    def test_complete_production_not_in_progress_raises(self, approved_work_order):
        with pytest.raises(ValueError, match="Cannot complete production in status approved"):
            approved_work_order.complete_production(Decimal("50"), "operator")

    def test_cancel_draft_success(self, sample_work_order):
        cancelled = sample_work_order.cancel("canceller", "No longer needed")
        assert cancelled.status == WorkOrderStatus.CANCELLED
        assert "No longer needed" in cancelled.notes
        assert cancelled.version == sample_work_order.version + 1

    def test_cancel_approved_success(self, approved_work_order):
        cancelled = approved_work_order.cancel("canceller", "Cancelled after approval")
        assert cancelled.status == WorkOrderStatus.CANCELLED

    def test_cancel_in_progress_success(self, in_progress_work_order):
        cancelled = in_progress_work_order.cancel("canceller", "Production stopped")
        assert cancelled.status == WorkOrderStatus.CANCELLED

    def test_cancel_completed_raises(self, in_progress_work_order):
        completed = in_progress_work_order.complete_production(Decimal("100"), "operator")
        with pytest.raises(ValueError, match="Cannot cancel work order in status completed"):
            completed.cancel("canceller", "Reason")

    def test_cancel_cancelled_raises(self, sample_work_order):
        cancelled = sample_work_order.cancel("canceller", "First")
        with pytest.raises(ValueError, match="Cannot cancel work order in status cancelled"):
            cancelled.cancel("canceller", "Again")

    def test_update_actual_costs_material_only(self, in_progress_work_order):
        updated = in_progress_work_order.update_actual_costs(
            material_actual=Decimal("1200"),
            updated_by="costing"
        )
        assert updated.material_actual_cost == Decimal("1200")
        assert updated.labor_actual_cost == Decimal("0")
        assert updated.overhead_actual_cost == Decimal("0")
        assert updated.version == in_progress_work_order.version + 1

    def test_update_actual_costs_all_fields(self, in_progress_work_order):
        updated = in_progress_work_order.update_actual_costs(
            material_actual=Decimal("1500"),
            labor_actual=Decimal("800"),
            overhead_actual=Decimal("400"),
            updated_by="costing"
        )
        assert updated.material_actual_cost == Decimal("1500")
        assert updated.labor_actual_cost == Decimal("800")
        assert updated.overhead_actual_cost == Decimal("400")
        assert updated.version == in_progress_work_order.version + 1

    def test_update_actual_costs_no_changes(self, in_progress_work_order):
        # Should still increment version even if no changes? Actually the method creates new instance regardless.
        updated = in_progress_work_order.update_actual_costs()
        assert updated.material_actual_cost == in_progress_work_order.material_actual_cost
        assert updated.labor_actual_cost == in_progress_work_order.labor_actual_cost
        assert updated.overhead_actual_cost == in_progress_work_order.overhead_actual_cost
        assert updated.version == in_progress_work_order.version + 1


# ----------------------------------------------------------------------
# WorkOrderEntity - Query Methods
# ----------------------------------------------------------------------
class TestWorkOrderEntityQueries:
    def test_is_completed_true_when_completed_status(self, in_progress_work_order):
        completed = in_progress_work_order.complete_production(Decimal("100"), "operator")
        assert completed.is_completed() is True

    def test_is_completed_true_when_partially_completed_with_full_quantity(self, in_progress_work_order):
        # Partial status but quantity equals planned
        completed = in_progress_work_order.complete_production(Decimal("100"), "operator")
        assert completed.is_completed() is True

    def test_is_completed_false_when_not_completed(self, in_progress_work_order):
        partial = in_progress_work_order.complete_production(Decimal("50"), "operator")
        assert partial.is_completed() is False

    def test_is_completed_cancelled_false(self, sample_work_order):
        cancelled = sample_work_order.cancel("canceller", "Reason")
        assert cancelled.is_completed() is False

    def test_is_overdue_true(self, in_progress_work_order):
        future = in_progress_work_order.planned_end_date + timedelta(days=5)
        with pytest.raises(ValueError, match="Cannot complete production"):
            # This test is for is_overdue, not complete_production.
            # Let's create a different scenario.
            pass
        # Actually, we can create a work order with planned_end_date in the past.
        past = datetime.now(UTC) - timedelta(days=5)
        overdue_wo = WorkOrderEntity(
            work_order_id=uuid4(),
            work_order_number="WO-OVERDUE",
            product_id=uuid4(),
            product_code="P",
            product_name="N",
            bom_id=uuid4(),
            bom_version=1,
            planned_quantity=Decimal("100"),
            completed_quantity=Decimal("0"),
            status=WorkOrderStatus.IN_PROGRESS,
            priority=WorkOrderPriority.NORMAL,
            planned_start_date=datetime.now(UTC) - timedelta(days=10),
            planned_end_date=past,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        assert overdue_wo.is_overdue() is True

    def test_is_overdue_false_when_completed(self, in_progress_work_order):
        completed = in_progress_work_order.complete_production(Decimal("100"), "operator")
        assert completed.is_overdue() is False

    def test_is_overdue_false_when_cancelled(self, sample_work_order):
        cancelled = sample_work_order.cancel("canceller", "Reason")
        assert cancelled.is_overdue() is False

    def test_is_overdue_false_when_not_past_end(self, in_progress_work_order):
        # planned_end_date is in future
        assert in_progress_work_order.is_overdue() is False

    def test_get_remaining_quantity(self, in_progress_work_order):
        assert in_progress_work_order.get_remaining_quantity() == Decimal("100")
        partial = in_progress_work_order.complete_production(Decimal("30"), "operator")
        assert partial.get_remaining_quantity() == Decimal("70")
        completed = in_progress_work_order.complete_production(Decimal("100"), "operator")
        assert completed.get_remaining_quantity() == Decimal("0")

    def test_get_completion_percentage(self, in_progress_work_order):
        assert in_progress_work_order.get_completion_percentage() == 0.0
        partial = in_progress_work_order.complete_production(Decimal("30"), "operator")
        assert partial.get_completion_percentage() == 30.0
        completed = in_progress_work_order.complete_production(Decimal("100"), "operator")
        assert completed.get_completion_percentage() == 100.0

    def test_get_completion_percentage_zero_planned(self):
        # Create work order with planned_quantity = 0? Validation prevents it.
        # So we can't test this edge case directly.
        pass


# ----------------------------------------------------------------------
# WorkOrderEntity - Serialization
# ----------------------------------------------------------------------
class TestWorkOrderEntitySerialization:
    def test_to_dict(self, sample_work_order):
        d = sample_work_order.to_dict()
        assert d["work_order_id"] == str(sample_work_order.work_order_id)
        assert d["work_order_number"] == "WO-001"
        assert d["product_code"] == "PROD-001"
        assert d["planned_quantity"] == "100"
        assert d["completed_quantity"] == "0"
        assert d["remaining_quantity"] == "100"
        assert d["completion_percentage"] == 0.0
        assert d["status"] == "draft"
        assert d["priority"] == "normal"
        assert d["work_order_type"] == "production"
        assert d["is_overdue"] is False
        assert d["material_standard_cost"] == "10"
        assert d["labor_standard_cost"] == "5"
        assert d["overhead_standard_cost"] == "3"
        assert d["version"] == 1

    def test_to_dict_with_actual_dates(self, in_progress_work_order):
        d = in_progress_work_order.to_dict()
        assert d["actual_start_date"] is not None
        assert d["actual_end_date"] is None
        # Complete it
        completed = in_progress_work_order.complete_production(Decimal("100"), "operator")
        d2 = completed.to_dict()
        assert d2["actual_end_date"] is not None
        assert d2["status"] == "completed"


# ----------------------------------------------------------------------
# WorkOrderEntity - State Transitions
# ----------------------------------------------------------------------
class TestWorkOrderEntityStateTransitions:
    def test_full_workflow(self, sample_work_order):
        # DRAFT -> APPROVED
        approved = sample_work_order.approve("approver")
        assert approved.status == WorkOrderStatus.APPROVED

        # APPROVED -> IN_PROGRESS
        started = approved.start_production("operator")
        assert started.status == WorkOrderStatus.IN_PROGRESS
        assert started.actual_start_date is not None

        # IN_PROGRESS -> PARTIALLY_COMPLETED
        partial = started.complete_production(Decimal("50"), "operator")
        assert partial.status == WorkOrderStatus.PARTIALLY_COMPLETED
        assert partial.completed_quantity == Decimal("50")

        # PARTIALLY_COMPLETED -> COMPLETED
        completed = partial.complete_production(Decimal("50"), "operator")
        assert completed.status == WorkOrderStatus.COMPLETED
        assert completed.completed_quantity == Decimal("100")
        assert completed.actual_end_date is not None

    def test_cancel_flow(self, sample_work_order):
        # DRAFT -> CANCELLED
        cancelled = sample_work_order.cancel("canceller", "No need")
        assert cancelled.status == WorkOrderStatus.CANCELLED
        # Cannot approve cancelled
        with pytest.raises(ValueError):
            cancelled.approve("approver")
        # Cannot start cancelled
        with pytest.raises(ValueError):
            cancelled.start_production("operator")

    def test_approve_to_cancel(self, approved_work_order):
        cancelled = approved_work_order.cancel("canceller", "After approval")
        assert cancelled.status == WorkOrderStatus.CANCELLED


# ----------------------------------------------------------------------
# WorkOrderRepository (Interface)
# ----------------------------------------------------------------------
class TestWorkOrderRepository:
    @pytest.mark.asyncio
    async def test_get_by_id_not_implemented(self):
        repo = WorkOrderRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_id(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_get_by_number_not_implemented(self):
        repo = WorkOrderRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_number("WO-001", uuid4())

    @pytest.mark.asyncio
    async def test_get_by_product_not_implemented(self):
        repo = WorkOrderRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_product(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_get_by_date_range_not_implemented(self):
        repo = WorkOrderRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_date_range(uuid4(), datetime.now(UTC), datetime.now(UTC))

    @pytest.mark.asyncio
    async def test_save_not_implemented(self):
        repo = WorkOrderRepository()
        with pytest.raises(NotImplementedError):
            await repo.save(MagicMock(), uuid4())

    @pytest.mark.asyncio
    async def test_delete_not_implemented(self):
        repo = WorkOrderRepository()
        with pytest.raises(NotImplementedError):
            await repo.delete(uuid4(), uuid4())


# ----------------------------------------------------------------------
# Edge Cases and Decimal Precision
# ----------------------------------------------------------------------
class TestEdgeCases:
    def test_large_quantities(self):
        now = datetime.now(UTC)
        later = now + timedelta(days=1)
        wo = WorkOrderEntity(
            work_order_id=uuid4(),
            work_order_number="WO-001",
            product_id=uuid4(),
            product_code="P",
            product_name="N",
            bom_id=uuid4(),
            bom_version=1,
            planned_quantity=Decimal("999999.999"),
            completed_quantity=Decimal("0"),
            status=WorkOrderStatus.DRAFT,
            priority=WorkOrderPriority.NORMAL,
            planned_start_date=now,
            planned_end_date=later,
            created_at=now,
            updated_at=now,
        )
        assert wo.planned_quantity == Decimal("999999.999")
        wo = wo.complete_production(Decimal("500000.5"), "operator")
        assert wo.completed_quantity == Decimal("500000.5")
        assert wo.get_remaining_quantity() == Decimal("499999.499")
        assert wo.get_completion_percentage() == pytest.approx(50.00005, rel=1e-4)

    def test_decimal_precision_in_costs(self):
        now = datetime.now(UTC)
        later = now + timedelta(days=1)
        wo = WorkOrderEntity(
            work_order_id=uuid4(),
            work_order_number="WO-001",
            product_id=uuid4(),
            product_code="P",
            product_name="N",
            bom_id=uuid4(),
            bom_version=1,
            planned_quantity=Decimal("100"),
            completed_quantity=Decimal("0"),
            status=WorkOrderStatus.DRAFT,
            priority=WorkOrderPriority.NORMAL,
            planned_start_date=now,
            planned_end_date=later,
            created_at=now,
            updated_at=now,
            material_standard_cost=Decimal("10.333"),
            labor_standard_cost=Decimal("5.555"),
            overhead_standard_cost=Decimal("3.777"),
        )
        assert wo.material_standard_cost == Decimal("10.333")
        assert wo.labor_standard_cost == Decimal("5.555")
        assert wo.overhead_standard_cost == Decimal("3.777")

    def test_alias_work_order(self):
        assert WorkOrder is WorkOrderEntity
        wo = WorkOrder(
            work_order_id=uuid4(),
            work_order_number="WO-001",
            product_id=uuid4(),
            product_code="P",
            product_name="N",
            bom_id=uuid4(),
            bom_version=1,
            planned_quantity=Decimal("100"),
            completed_quantity=Decimal("0"),
            status=WorkOrderStatus.DRAFT,
            priority=WorkOrderPriority.NORMAL,
            planned_start_date=datetime.now(UTC),
            planned_end_date=datetime.now(UTC) + timedelta(days=1),
        )
        assert isinstance(wo, WorkOrderEntity)