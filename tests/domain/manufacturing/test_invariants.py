# tests/domain/manufacturing/test_invariants.py
"""
Comprehensive unit tests for domain/manufacturing/invariants.py.
Covers all public methods, including static invariants and enforcer.
All datetime is mocked to avoid flakiness.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from domain.manufacturing.bill_of_materials_entity import BillOfMaterialsEntity, BOMStatus
from domain.manufacturing.invariants import (
    InvariantResult,
    ManufacturingInvariantEnforcer,
    ManufacturingInvariants,
)
from domain.manufacturing.work_in_process_entity import WorkInProcessEntity
from domain.manufacturing.work_order_entity import WorkOrderEntity, WorkOrderStatus

# ============================================================================
# Fixed datetime for deterministic tests
# ============================================================================

FIXED_NOW = datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    with patch("domain.manufacturing.invariants.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.UTC = UTC
        yield mock_dt


# ============================================================================
# Dummy entities for testing (using MagicMock with attributes)
# ============================================================================

def create_mock_work_order(
    work_order_number="WO-001",
    planned_quantity=Decimal(100),
    completed_quantity=Decimal(0),
    planned_start_date=FIXED_NOW,
    planned_end_date=FIXED_NOW + timedelta(days=7),
    actual_start_date=None,
    actual_end_date=None,
    status=WorkOrderStatus.DRAFT,
    product_id="PROD-001",
    bom_id="BOM-001",
    bom_version=1,
):
    mock = MagicMock(spec=WorkOrderEntity)
    mock.work_order_number = work_order_number
    mock.planned_quantity = planned_quantity
    mock.completed_quantity = completed_quantity
    mock.planned_start_date = planned_start_date
    mock.planned_end_date = planned_end_date
    mock.actual_start_date = actual_start_date
    mock.actual_end_date = actual_end_date
    mock.status = status
    mock.product_id = product_id
    mock.bom_id = bom_id
    mock.bom_version = bom_version
    return mock


def create_mock_bom(
    bom_id="BOM-001",
    bom_code="BOM-001",
    product_id="PROD-001",
    version=1,
    status=BOMStatus.ACTIVE,
    items=None,
    effective_date=FIXED_NOW - timedelta(days=1),
    expiry_date=FIXED_NOW + timedelta(days=365),
):
    if items is None:
        items = []
    mock = MagicMock(spec=BillOfMaterialsEntity)
    mock.bom_id = bom_id
    mock.bom_code = bom_code
    mock.product_id = product_id
    mock.version = version
    mock.status = status
    mock.items = items
    mock.effective_date = effective_date
    mock.expiry_date = expiry_date
    return mock


def create_mock_wip(
    work_order_number="WO-001",
    quantity_started=Decimal(100),
    quantity_remaining=Decimal(50),
    quantity_completed=Decimal(50),
    total_cost=Decimal(1000),
    material_cost=Decimal(600),
    labor_cost=Decimal(300),
    overhead_cost=Decimal(100),
):
    mock = MagicMock(spec=WorkInProcessEntity)
    mock.work_order_number = work_order_number
    mock.quantity_started = quantity_started
    mock.quantity_remaining = quantity_remaining
    mock.quantity_completed = quantity_completed
    mock.total_cost = total_cost
    mock.material_cost = material_cost
    mock.labor_cost = labor_cost
    mock.overhead_cost = overhead_cost
    return mock


# ============================================================================
# Tests for InvariantResult
# ============================================================================

class TestInvariantResult:
    def test_construction_valid(self):
        result = InvariantResult(True, ["error1"])
        assert result.is_valid is True
        assert result.errors == ["error1"]

    def test_construction_default(self):
        result = InvariantResult()
        assert result.is_valid is True
        assert result.errors == []

    def test_add_error(self):
        result = InvariantResult()
        result.add_error("test error")
        assert result.is_valid is False
        assert result.errors == ["test error"]

    def test_merge_valid(self):
        r1 = InvariantResult(True)
        r2 = InvariantResult(True)
        r1.merge(r2)
        assert r1.is_valid is True
        assert r1.errors == []

    def test_merge_invalid(self):
        r1 = InvariantResult(True)
        r2 = InvariantResult(False, ["err1", "err2"])
        r1.merge(r2)
        assert r1.is_valid is False
        assert r1.errors == ["err1", "err2"]

    def test_to_dict(self):
        result = InvariantResult(False, ["err"])
        d = result.to_dict()
        assert d["is_valid"] is False
        assert d["errors"] == ["err"]
        assert d["error_count"] == 1

    def test_bool(self):
        assert bool(InvariantResult(True)) is True
        assert bool(InvariantResult(False)) is False

    def test_repr(self):
        result = InvariantResult(False, ["err"])
        assert repr(result) == "InvariantResult(is_valid=False, errors=['err'])"


# ============================================================================
# Tests for ManufacturingInvariants (static methods)
# ============================================================================

class TestManufacturingInvariants:
    # ---- Work Order invariants ----
    def test_validate_work_order_quantity_valid(self):
        wo = create_mock_work_order(planned_quantity=Decimal(10))
        result = ManufacturingInvariants.validate_work_order_quantity(wo)
        assert result.is_valid is True

    def test_validate_work_order_quantity_invalid_zero(self):
        wo = create_mock_work_order(planned_quantity=Decimal(0))
        result = ManufacturingInvariants.validate_work_order_quantity(wo)
        assert result.is_valid is False
        assert "planned quantity must be positive" in result.errors[0]

    def test_validate_work_order_quantity_invalid_negative(self):
        wo = create_mock_work_order(planned_quantity=Decimal(-5))
        result = ManufacturingInvariants.validate_work_order_quantity(wo)
        assert result.is_valid is False
        assert "planned quantity must be positive" in result.errors[0]

    def test_validate_completed_quantity_valid(self):
        wo = create_mock_work_order(planned_quantity=Decimal(100), completed_quantity=Decimal(50))
        result = ManufacturingInvariants.validate_completed_quantity(wo)
        assert result.is_valid is True

    def test_validate_completed_quantity_exceeds(self):
        wo = create_mock_work_order(planned_quantity=Decimal(100), completed_quantity=Decimal(150))
        result = ManufacturingInvariants.validate_completed_quantity(wo)
        assert result.is_valid is False
        assert "exceeds planned quantity" in result.errors[0]

    def test_validate_work_order_status_transition_valid(self):
        # DRAFT -> APPROVED
        result = ManufacturingInvariants.validate_work_order_status_transition(
            WorkOrderStatus.DRAFT, WorkOrderStatus.APPROVED
        )
        assert result.is_valid is True
        # APPROVED -> IN_PROGRESS
        result2 = ManufacturingInvariants.validate_work_order_status_transition(
            WorkOrderStatus.APPROVED, WorkOrderStatus.IN_PROGRESS
        )
        assert result2.is_valid is True
        # IN_PROGRESS -> COMPLETED
        result3 = ManufacturingInvariants.validate_work_order_status_transition(
            WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.COMPLETED
        )
        assert result3.is_valid is True

    def test_validate_work_order_status_transition_invalid(self):
        result = ManufacturingInvariants.validate_work_order_status_transition(
            WorkOrderStatus.DRAFT, WorkOrderStatus.IN_PROGRESS
        )
        assert result.is_valid is False
        assert "Invalid status transition" in result.errors[0]

    def test_validate_work_order_dates_valid(self):
        wo = create_mock_work_order(
            planned_start_date=FIXED_NOW,
            planned_end_date=FIXED_NOW + timedelta(days=1),
        )
        result = ManufacturingInvariants.validate_work_order_dates(wo)
        assert result.is_valid is True

    def test_validate_work_order_dates_invalid_end_before_start(self):
        wo = create_mock_work_order(
            planned_start_date=FIXED_NOW + timedelta(days=1),
            planned_end_date=FIXED_NOW,
        )
        result = ManufacturingInvariants.validate_work_order_dates(wo)
        assert result.is_valid is False
        assert "planned end date must be after planned start date" in result.errors[0]

    def test_validate_work_order_dates_actual_invalid(self):
        wo = create_mock_work_order(
            planned_start_date=FIXED_NOW,
            planned_end_date=FIXED_NOW + timedelta(days=1),
            actual_start_date=FIXED_NOW + timedelta(days=2),
            actual_end_date=FIXED_NOW + timedelta(days=1),
        )
        result = ManufacturingInvariants.validate_work_order_dates(wo)
        assert result.is_valid is False
        assert "actual end date cannot be before actual start date" in result.errors[0]

    # ---- BOM invariants ----
    def test_validate_bom_structure_valid(self):
        bom = create_mock_bom(items=[{"item_code": "A"}, {"item_code": "B"}])
        result = ManufacturingInvariants.validate_bom_structure(bom)
        assert result.is_valid is True

    def test_validate_bom_structure_empty_items(self):
        bom = create_mock_bom(items=[])
        result = ManufacturingInvariants.validate_bom_structure(bom)
        assert result.is_valid is False
        assert "must have at least one component" in result.errors[0]

    def test_validate_bom_structure_self_reference(self):
        bom_id = "BOM-001"
        bom = create_mock_bom(
            bom_id=bom_id,
            items=[
                {"item_code": "A", "sub_bom_id": bom_id},
            ],
        )
        # We need to set sub_bom_id on the mock items.
        # Since items are dicts, we need to create a list of objects with sub_bom_id.
        # Let's create proper mock items.
        item1 = MagicMock()
        item1.sub_bom_id = bom_id
        item1.item_code = "A"
        bom.items = [item1]
        result = ManufacturingInvariants.validate_bom_structure(bom)
        assert result.is_valid is False
        assert "circular reference" in result.errors[0]

    def test_validate_bom_structure_duplicate_codes(self):
        item1 = MagicMock()
        item1.item_code = "A"
        item2 = MagicMock()
        item2.item_code = "A"
        bom = create_mock_bom(items=[item1, item2])
        result = ManufacturingInvariants.validate_bom_structure(bom)
        assert result.is_valid is False
        assert "duplicate item codes" in result.errors[0]

    def test_validate_bom_structure_non_positive_quantity(self):
        item = MagicMock()
        item.item_code = "A"
        item.quantity = Decimal(0)
        bom = create_mock_bom(items=[item])
        result = ManufacturingInvariants.validate_bom_structure(bom)
        assert result.is_valid is False
        assert "non-positive quantity" in result.errors[0]

    def test_validate_bom_effective_date_valid(self):
        bom = create_mock_bom(status=BOMStatus.ACTIVE, effective_date=FIXED_NOW - timedelta(days=1))
        result = ManufacturingInvariants.validate_bom_effective_date(bom, FIXED_NOW)
        assert result.is_valid is True

    def test_validate_bom_effective_date_inactive(self):
        bom = create_mock_bom(status=BOMStatus.DRAFT)
        result = ManufacturingInvariants.validate_bom_effective_date(bom, FIXED_NOW)
        assert result.is_valid is False
        assert "not active" in result.errors[0]

    def test_validate_bom_effective_date_before_effective(self):
        bom = create_mock_bom(effective_date=FIXED_NOW + timedelta(days=1))
        result = ManufacturingInvariants.validate_bom_effective_date(bom, FIXED_NOW)
        assert result.is_valid is False
        assert "effective date is after" in result.errors[0]

    def test_validate_bom_effective_date_expired(self):
        bom = create_mock_bom(expiry_date=FIXED_NOW - timedelta(days=1))
        result = ManufacturingInvariants.validate_bom_effective_date(bom, FIXED_NOW)
        assert result.is_valid is False
        assert "expired on" in result.errors[0]

    def test_validate_bom_version_continuity_valid(self):
        prev = create_mock_bom(version=1, product_id="PROD-001")
        new = create_mock_bom(version=2, product_id="PROD-001")
        result = ManufacturingInvariants.validate_bom_version_continuity(prev, new)
        assert result.is_valid is True

    def test_validate_bom_version_continuity_no_prev(self):
        new = create_mock_bom(version=1)
        result = ManufacturingInvariants.validate_bom_version_continuity(None, new)
        assert result.is_valid is True

    def test_validate_bom_version_continuity_product_mismatch(self):
        prev = create_mock_bom(product_id="PROD-001")
        new = create_mock_bom(product_id="PROD-002")
        result = ManufacturingInvariants.validate_bom_version_continuity(prev, new)
        assert result.is_valid is False
        assert "does not match" in result.errors[0]

    def test_validate_bom_version_continuity_version_not_increased(self):
        prev = create_mock_bom(version=2)
        new = create_mock_bom(version=1)
        result = ManufacturingInvariants.validate_bom_version_continuity(prev, new)
        assert result.is_valid is False
        assert "must be greater" in result.errors[0]

    # ---- WIP invariants ----
    def test_validate_wip_consistency_valid(self):
        wip = create_mock_wip()
        result = ManufacturingInvariants.validate_wip_consistency(wip)
        assert result.is_valid is True

    def test_validate_wip_consistency_quantity_started_non_positive(self):
        wip = create_mock_wip(quantity_started=Decimal(0))
        result = ManufacturingInvariants.validate_wip_consistency(wip)
        assert result.is_valid is False
        assert "non-positive quantity started" in result.errors[0]

    def test_validate_wip_consistency_quantity_remaining_negative(self):
        wip = create_mock_wip(quantity_remaining=Decimal(-1))
        result = ManufacturingInvariants.validate_wip_consistency(wip)
        assert result.is_valid is False
        assert "negative quantity remaining" in result.errors[0]

    def test_validate_wip_consistency_quantity_completed_negative(self):
        wip = create_mock_wip(quantity_completed=Decimal(-1))
        result = ManufacturingInvariants.validate_wip_consistency(wip)
        assert result.is_valid is False
        assert "negative quantity completed" in result.errors[0]

    def test_validate_wip_consistency_quantity_mismatch(self):
        wip = create_mock_wip(quantity_started=100, quantity_remaining=30, quantity_completed=50)
        result = ManufacturingInvariants.validate_wip_consistency(wip)
        assert result.is_valid is False
        assert "quantity mismatch" in result.errors[0]

    def test_validate_wip_consistency_total_cost_negative(self):
        wip = create_mock_wip(total_cost=Decimal(-100))
        result = ManufacturingInvariants.validate_wip_consistency(wip)
        assert result.is_valid is False
        assert "total cost cannot be negative" in result.errors[0]

    def test_validate_wip_consistency_cost_mismatch(self):
        wip = create_mock_wip(
            total_cost=Decimal(2000),
            material_cost=Decimal(600),
            labor_cost=Decimal(300),
            overhead_cost=Decimal(100)
        )
        result = ManufacturingInvariants.validate_wip_consistency(wip)
        assert result.is_valid is False
        assert "total cost mismatch" in result.errors[0]

    def test_validate_wip_completion_valid(self):
        wip = create_mock_wip(quantity_remaining=Decimal(50))
        result = ManufacturingInvariants.validate_wip_completion(wip, Decimal(30))
        assert result.is_valid is True

    def test_validate_wip_completion_non_positive_units(self):
        wip = create_mock_wip()
        result = ManufacturingInvariants.validate_wip_completion(wip, Decimal(0))
        assert result.is_valid is False
        assert "Cannot complete non-positive units" in result.errors[0]

    def test_validate_wip_completion_exceeds_remaining(self):
        wip = create_mock_wip(quantity_remaining=Decimal(10))
        result = ManufacturingInvariants.validate_wip_completion(wip, Decimal(20))
        assert result.is_valid is False
        assert "only 10 remaining" in result.errors[0]

    # ---- Material availability ----
    def test_validate_material_availability_valid(self):
        result = ManufacturingInvariants.validate_material_availability(
            required_quantity=Decimal(10),
            available_quantity=Decimal(20),
            material_code="MAT-001"
        )
        assert result.is_valid is True

    def test_validate_material_availability_insufficient(self):
        result = ManufacturingInvariants.validate_material_availability(
            required_quantity=Decimal(10),
            available_quantity=Decimal(5),
            material_code="MAT-001"
        )
        assert result.is_valid is False
        assert "Insufficient material" in result.errors[0]

    def test_validate_material_availability_required_negative(self):
        result = ManufacturingInvariants.validate_material_availability(
            required_quantity=Decimal(-1),
            available_quantity=Decimal(10),
            material_code="MAT-001"
        )
        assert result.is_valid is False
        assert "Required quantity must be positive" in result.errors[0]

    # ---- Cost invariants ----
    def test_validate_non_negative_cost_valid(self):
        result = ManufacturingInvariants.validate_non_negative_cost(Decimal(100), "Material")
        assert result.is_valid is True

    def test_validate_non_negative_cost_negative(self):
        result = ManufacturingInvariants.validate_non_negative_cost(Decimal(-10), "Material")
        assert result.is_valid is False
        assert "cannot be negative" in result.errors[0]

    def test_validate_standard_cost_consistency_valid(self):
        mock_cost = MagicMock()
        mock_cost.material_cost = Decimal(100)
        mock_cost.labor_cost = Decimal(50)
        mock_cost.overhead_cost = Decimal(20)
        mock_cost.total_cost = Decimal(170)
        result = ManufacturingInvariants.validate_standard_cost_consistency(mock_cost)
        assert result.is_valid is True

    def test_validate_standard_cost_consistency_mismatch(self):
        mock_cost = MagicMock()
        mock_cost.material_cost = Decimal(100)
        mock_cost.labor_cost = Decimal(50)
        mock_cost.overhead_cost = Decimal(20)
        mock_cost.total_cost = Decimal(200)
        result = ManufacturingInvariants.validate_standard_cost_consistency(mock_cost)
        assert result.is_valid is False
        assert "total mismatch" in result.errors[0]

    # ---- Cross-entity invariants ----
    def test_validate_work_order_bom_consistency_valid(self):
        wo = create_mock_work_order(product_id="PROD-001", bom_version=1)
        bom = create_mock_bom(product_id="PROD-001", version=1)
        result = ManufacturingInvariants.validate_work_order_bom_consistency(wo, bom)
        assert result.is_valid is True

    def test_validate_work_order_bom_consistency_bom_none(self):
        wo = create_mock_work_order()
        result = ManufacturingInvariants.validate_work_order_bom_consistency(wo, None)
        assert result.is_valid is False
        assert "references non-existent BOM" in result.errors[0]

    def test_validate_work_order_bom_consistency_product_mismatch(self):
        wo = create_mock_work_order(product_id="PROD-001")
        bom = create_mock_bom(product_id="PROD-002")
        result = ManufacturingInvariants.validate_work_order_bom_consistency(wo, bom)
        assert result.is_valid is False
        assert "does not match BOM product" in result.errors[0]

    def test_validate_work_order_bom_consistency_version_mismatch(self):
        wo = create_mock_work_order(bom_version=2)
        bom = create_mock_bom(version=1)
        result = ManufacturingInvariants.validate_work_order_bom_consistency(wo, bom)
        assert result.is_valid is False
        assert "does not match BOM current version" in result.errors[0]


# ============================================================================
# Tests for ManufacturingInvariantEnforcer
# ============================================================================

@pytest.mark.asyncio
class TestManufacturingInvariantEnforcer:
    @pytest.fixture
    def enforcer(self):
        return ManufacturingInvariantEnforcer()

    @pytest.fixture
    def enforcer_with_checker(self):
        checker = AsyncMock()
        checker.return_value = (Decimal(100), InvariantResult(True))
        bom_validator = AsyncMock()
        bom_validator.return_value = create_mock_bom()
        return ManufacturingInvariantEnforcer(
            material_availability_checker=checker,
            bom_validator=bom_validator
        )

    async def test_enforce_work_order_create_valid(self, enforcer_with_checker):
        wo = create_mock_work_order()
        bom = create_mock_bom()
        result = await enforcer_with_checker.enforce_work_order_create(wo, bom)
        assert result.is_valid is True

    async def test_enforce_work_order_create_invalid_quantity(self, enforcer):
        wo = create_mock_work_order(planned_quantity=Decimal(0))
        result = await enforcer.enforce_work_order_create(wo)
        assert result.is_valid is False
        assert "planned quantity must be positive" in result.errors[0]

    async def test_enforce_work_order_create_bom_not_found(self, enforcer):
        wo = create_mock_work_order(bom_id="missing")
        # No bom_validator, and bom=None => will try to use bom_validator, but it's None.
        # It will skip BOM validation because bom is None and _bom_validator is None.
        # Actually the code: if bom: ... elif self._bom_validator: ... so if no validator, it just passes.
        # To test BOM not found, we need to pass a bom_validator that returns None.
        enforcer_with_validator = ManufacturingInvariantEnforcer(
            bom_validator=AsyncMock(return_value=None)
        )
        result = await enforcer_with_validator.enforce_work_order_create(wo)
        assert result.is_valid is False
        assert "not found" in result.errors[0]

    async def test_enforce_work_order_create_bom_validator_exception(self, enforcer):
        enforcer._bom_validator = AsyncMock(side_effect=Exception("DB error"))
        wo = create_mock_work_order()
        result = await enforcer.enforce_work_order_create(wo)
        assert result.is_valid is False
        assert "Failed to validate BOM" in result.errors[0]

    async def test_enforce_work_order_update_valid(self, enforcer):
        wo = create_mock_work_order(completed_quantity=Decimal(50))
        result = await enforcer.enforce_work_order_update(wo)
        assert result.is_valid is True

    async def test_enforce_work_order_update_invalid(self, enforcer):
        wo = create_mock_work_order(completed_quantity=Decimal(150), planned_quantity=Decimal(100))
        result = await enforcer.enforce_work_order_update(wo)
        assert result.is_valid is False
        assert "exceeds planned quantity" in result.errors[0]

    async def test_enforce_status_transition_valid(self, enforcer):
        result = await enforcer.enforce_status_transition(
            WorkOrderStatus.DRAFT, WorkOrderStatus.APPROVED, "WO-001"
        )
        assert result.is_valid is True

    async def test_enforce_status_transition_invalid(self, enforcer):
        result = await enforcer.enforce_status_transition(
            WorkOrderStatus.DRAFT, WorkOrderStatus.IN_PROGRESS, "WO-001"
        )
        assert result.is_valid is False
        assert "Invalid status transition" in result.errors[0]

    async def test_enforce_material_issue_valid(self, enforcer_with_checker):
        result = await enforcer_with_checker.enforce_material_issue("MAT-001", Decimal(10), "WO-001")
        assert result.is_valid is True

    async def test_enforce_material_issue_no_checker(self, enforcer):
        # Without checker, it should return valid (with warning)
        result = await enforcer.enforce_material_issue("MAT-001", Decimal(10), "WO-001")
        assert result.is_valid is True
        # No error, just warning

    async def test_enforce_material_issue_insufficient(self, enforcer):
        # Provide a checker that returns insufficient availability
        checker = AsyncMock()
        checker.return_value = (Decimal(5), InvariantResult(True))
        enforcer._material_checker = checker
        result = await enforcer.enforce_material_issue("MAT-001", Decimal(10), "WO-001")
        assert result.is_valid is False
        assert "Insufficient material" in result.errors[0]

    async def test_enforce_material_issue_checker_returns_invariant_result(self, enforcer):
        # Checker returns an InvariantResult with error
        checker = AsyncMock()
        checker.return_value = (Decimal(100), InvariantResult(False, ["checker error"]))
        enforcer._material_checker = checker
        result = await enforcer.enforce_material_issue("MAT-001", Decimal(10), "WO-001")
        assert result.is_valid is False
        assert "checker error" in result.errors[0]

    async def test_enforce_material_issue_checker_exception(self, enforcer):
        checker = AsyncMock(side_effect=Exception("checker boom"))
        enforcer._material_checker = checker
        result = await enforcer.enforce_material_issue("MAT-001", Decimal(10), "WO-001")
        assert result.is_valid is False
        assert "Material availability check failed" in result.errors[0]

    async def test_enforce_bom_structure_valid(self, enforcer):
        bom = create_mock_bom(items=[{"item_code": "A"}])
        # Need to ensure items are valid objects with attributes.
        item = MagicMock()
        item.item_code = "A"
        item.quantity = Decimal(1)
        bom.items = [item]
        result = await enforcer.enforce_bom_structure(bom)
        assert result.is_valid is True

    async def test_enforce_bom_structure_invalid(self, enforcer):
        bom = create_mock_bom(items=[])
        result = await enforcer.enforce_bom_structure(bom)
        assert result.is_valid is False
        assert "must have at least one component" in result.errors[0]

    async def test_enforce_bom_activation_valid(self, enforcer):
        bom = create_mock_bom(status=BOMStatus.DRAFT, effective_date=FIXED_NOW - timedelta(days=1))
        # Need a valid BOM with at least one item
        item = MagicMock()
        item.item_code = "A"
        item.quantity = Decimal(1)
        bom.items = [item]
        result = await enforcer.enforce_bom_activation(bom, FIXED_NOW)
        assert result.is_valid is True

    async def test_enforce_bom_activation_invalid_status(self, enforcer):
        bom = create_mock_bom(status=BOMStatus.ACTIVE)
        item = MagicMock()
        item.item_code = "A"
        item.quantity = Decimal(1)
        bom.items = [item]
        result = await enforcer.enforce_bom_activation(bom, FIXED_NOW)
        assert result.is_valid is False
        assert "Only DRAFT BOMs can be activated" in result.errors[0]

    async def test_enforce_bom_activation_effective_date_future(self, enforcer):
        bom = create_mock_bom(status=BOMStatus.DRAFT, effective_date=FIXED_NOW + timedelta(days=1))
        item = MagicMock()
        item.item_code = "A"
        item.quantity = Decimal(1)
        bom.items = [item]
        result = await enforcer.enforce_bom_activation(bom, FIXED_NOW)
        assert result.is_valid is False
        assert "Cannot activate BOM before its effective date" in result.errors[0]

    async def test_enforce_wip_consistency_valid(self, enforcer):
        wip = create_mock_wip()
        result = await enforcer.enforce_wip_consistency(wip)
        assert result.is_valid is True

    async def test_enforce_wip_consistency_invalid(self, enforcer):
        wip = create_mock_wip(quantity_started=Decimal(0))
        result = await enforcer.enforce_wip_consistency(wip)
        assert result.is_valid is False
        assert "non-positive quantity started" in result.errors[0]

    async def test_enforce_wip_completion_valid(self, enforcer):
        wip = create_mock_wip(quantity_remaining=Decimal(50))
        result = await enforcer.enforce_wip_completion(wip, Decimal(30))
        assert result.is_valid is True

    async def test_enforce_wip_completion_invalid_exceeds(self, enforcer):
        wip = create_mock_wip(quantity_remaining=Decimal(10))
        result = await enforcer.enforce_wip_completion(wip, Decimal(20))
        assert result.is_valid is False
        assert "only 10 remaining" in result.errors[0]

    async def test_enforce_wip_completion_non_positive(self, enforcer):
        wip = create_mock_wip()
        result = await enforcer.enforce_wip_completion(wip, Decimal(0))
        assert result.is_valid is False
        assert "Cannot complete non-positive units" in result.errors[0]

    def test_violation_log(self, enforcer):
        # Simulate a violation
        enforcer._log_violation("test", InvariantResult(False, ["err"]), {"key": "val"})
        log = enforcer.get_violation_log()
        assert len(log) == 1
        assert log[0]["rule"] == "test"
        assert log[0]["errors"] == ["err"]
        assert log[0]["context"] == {"key": "val"}

    def test_clear_violation_log(self, enforcer):
        enforcer._log_violation("test", InvariantResult(False, ["err"]), {})
        assert len(enforcer.get_violation_log()) == 1
        enforcer.clear_violation_log()
        assert len(enforcer.get_violation_log()) == 0
