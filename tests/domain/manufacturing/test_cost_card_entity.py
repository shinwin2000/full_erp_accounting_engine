# test_cost_card_entity.py
# =========================
# Comprehensive tests for domain/manufacturing/cost_card_entity.py.
# Covers all enums, value objects, entity methods, edge cases, and decimal precision.

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from domain.manufacturing.cost_card_entity import (
    CostCard,
    CostCardEntity,
    CostCardRepository,
    CostCardStatus,
    CostEntry,
)
from domain.manufacturing.cost_element_enum import CostElement


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def sample_work_order_id() -> UUID:
    return uuid4()


@pytest.fixture
def sample_product_id() -> UUID:
    return uuid4()


@pytest.fixture
def sample_cost_card(sample_work_order_id, sample_product_id) -> CostCardEntity:
    """Create a valid CostCardEntity in OPEN state with zero costs."""
    return CostCardEntity.create(
        work_order_id=sample_work_order_id,
        work_order_number="WO-001",
        product_id=sample_product_id,
        product_code="PROD-001",
        product_name="Test Product",
        planned_quantity=Decimal("100"),
        created_by="tester",
    )


@pytest.fixture
def sample_cost_entry() -> CostEntry:
    """Create a valid CostEntry."""
    return CostEntry(
        entry_id=uuid4(),
        cost_element=CostElement.MATERIAL,
        amount=Decimal("1000.00"),
        quantity=Decimal("5"),
        unit_cost=Decimal("200.00"),
        transaction_date=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
        reference_type="PO",
        reference_id=uuid4(),
        reference_number="PO-001",
        description="Raw material purchase",
        created_by="tester",
        created_at=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
    )


# ----------------------------------------------------------------------
# CostCardStatus Enum
# ----------------------------------------------------------------------
class TestCostCardStatus:
    def test_members_exist(self):
        assert hasattr(CostCardStatus, "OPEN")
        assert hasattr(CostCardStatus, "CLOSED")
        assert hasattr(CostCardStatus, "ADJUSTED")

    def test_member_is_instance(self):
        assert isinstance(CostCardStatus.OPEN, CostCardStatus)

    def test_from_string_valid(self):
        assert CostCardStatus.from_string("open") == CostCardStatus.OPEN
        assert CostCardStatus.from_string("OPEN") == CostCardStatus.OPEN
        assert CostCardStatus.from_string("closed") == CostCardStatus.CLOSED
        assert CostCardStatus.from_string("adjusted") == CostCardStatus.ADJUSTED

    def test_from_string_invalid_defaults_open(self):
        assert CostCardStatus.from_string("unknown") == CostCardStatus.OPEN
        assert CostCardStatus.from_string("") == CostCardStatus.OPEN


# ----------------------------------------------------------------------
# CostEntry Value Object
# ----------------------------------------------------------------------
class TestCostEntry:
    def test_construction_valid(self, sample_cost_entry):
        assert sample_cost_entry.entry_id is not None
        assert sample_cost_entry.cost_element == CostElement.MATERIAL
        assert sample_cost_entry.amount == Decimal("1000.00")
        assert sample_cost_entry.quantity == Decimal("5")
        assert sample_cost_entry.unit_cost == Decimal("200.00")
        assert sample_cost_entry.reference_type == "PO"
        assert sample_cost_entry.reference_number == "PO-001"
        assert sample_cost_entry.created_at.tzinfo == UTC

    def test_validation_negative_amount_raises(self):
        with pytest.raises(ValueError, match="Amount cannot be negative"):
            CostEntry(
                entry_id=uuid4(),
                cost_element=CostElement.MATERIAL,
                amount=Decimal("-100"),
                quantity=Decimal("1"),
                unit_cost=Decimal("100"),
                transaction_date=datetime.now(UTC),
                reference_type="PO",
                reference_id=uuid4(),
                reference_number="PO-001",
            )

    def test_validation_negative_quantity_raises(self):
        with pytest.raises(ValueError, match="Quantity cannot be negative"):
            CostEntry(
                entry_id=uuid4(),
                cost_element=CostElement.MATERIAL,
                amount=Decimal("100"),
                quantity=Decimal("-1"),
                unit_cost=Decimal("100"),
                transaction_date=datetime.now(UTC),
                reference_type="PO",
                reference_id=uuid4(),
                reference_number="PO-001",
            )

    def test_validation_negative_unit_cost_raises(self):
        with pytest.raises(ValueError, match="Unit cost cannot be negative"):
            CostEntry(
                entry_id=uuid4(),
                cost_element=CostElement.MATERIAL,
                amount=Decimal("100"),
                quantity=Decimal("1"),
                unit_cost=Decimal("-100"),
                transaction_date=datetime.now(UTC),
                reference_type="PO",
                reference_id=uuid4(),
                reference_number="PO-001",
            )

    def test_validation_naive_timestamp_raises(self):
        naive = datetime(2025, 1, 1, 10, 0)
        with pytest.raises(ValueError, match="transaction_date must be timezone-aware"):
            CostEntry(
                entry_id=uuid4(),
                cost_element=CostElement.MATERIAL,
                amount=Decimal("100"),
                quantity=Decimal("1"),
                unit_cost=Decimal("100"),
                transaction_date=naive,
                reference_type="PO",
                reference_id=uuid4(),
                reference_number="PO-001",
            )

    def test_validation_empty_reference_type_raises(self):
        with pytest.raises(ValueError, match="reference_type cannot be empty"):
            CostEntry(
                entry_id=uuid4(),
                cost_element=CostElement.MATERIAL,
                amount=Decimal("100"),
                quantity=Decimal("1"),
                unit_cost=Decimal("100"),
                transaction_date=datetime.now(UTC),
                reference_type="",
                reference_id=uuid4(),
                reference_number="PO-001",
            )

    def test_validation_empty_reference_number_raises(self):
        with pytest.raises(ValueError, match="reference_number cannot be empty"):
            CostEntry(
                entry_id=uuid4(),
                cost_element=CostElement.MATERIAL,
                amount=Decimal("100"),
                quantity=Decimal("1"),
                unit_cost=Decimal("100"),
                transaction_date=datetime.now(UTC),
                reference_type="PO",
                reference_id=uuid4(),
                reference_number="",
            )

    def test_to_dict(self, sample_cost_entry):
        d = sample_cost_entry.to_dict()
        assert d["entry_id"] == str(sample_cost_entry.entry_id)
        assert d["cost_element"] == "material"
        assert d["amount"] == "1000.00"
        assert d["quantity"] == "5"
        assert d["unit_cost"] == "200.00"
        assert d["reference_type"] == "PO"
        assert d["reference_number"] == "PO-001"
        assert d["description"] == "Raw material purchase"

    def test_from_dict(self, sample_cost_entry):
        d = sample_cost_entry.to_dict()
        reconstructed = CostEntry.from_dict(d)
        assert reconstructed.entry_id == sample_cost_entry.entry_id
        assert reconstructed.cost_element == sample_cost_entry.cost_element
        assert reconstructed.amount == sample_cost_entry.amount
        assert reconstructed.quantity == sample_cost_entry.quantity
        assert reconstructed.unit_cost == sample_cost_entry.unit_cost
        assert reconstructed.reference_type == sample_cost_entry.reference_type
        assert reconstructed.reference_number == sample_cost_entry.reference_number
        assert reconstructed.description == sample_cost_entry.description


# ----------------------------------------------------------------------
# CostCardEntity - Construction & Validation
# ----------------------------------------------------------------------
class TestCostCardEntityConstruction:
    def test_create_success(self, sample_work_order_id, sample_product_id):
        card = CostCardEntity.create(
            work_order_id=sample_work_order_id,
            work_order_number="WO-001",
            product_id=sample_product_id,
            product_code="PROD-001",
            product_name="Test Product",
            planned_quantity=Decimal("100"),
            created_by="tester",
        )
        assert card.cost_card_id is not None
        assert card.work_order_id == sample_work_order_id
        assert card.work_order_number == "WO-001"
        assert card.product_id == sample_product_id
        assert card.planned_quantity == Decimal("100")
        assert card.completed_quantity == Decimal("0")
        assert card.material_cost == Decimal("0")
        assert card.labor_cost == Decimal("0")
        assert card.overhead_cost == Decimal("0")
        assert card.total_cost == Decimal("0")
        assert card.unit_cost == Decimal("0")
        assert card.status == CostCardStatus.OPEN
        assert card.version == 1
        assert len(card._audit_trail) == 1
        assert card._audit_trail[0]["action"] == "created"

    def test_create_zero_planned_quantity_raises(self):
        with pytest.raises(ValueError, match="Planned quantity must be positive"):
            CostCardEntity.create(
                work_order_id=uuid4(),
                work_order_number="WO-001",
                product_id=uuid4(),
                product_code="PROD",
                product_name="Test",
                planned_quantity=Decimal("0"),
            )

    def test_create_negative_planned_quantity_raises(self):
        with pytest.raises(ValueError, match="Planned quantity must be positive"):
            CostCardEntity.create(
                work_order_id=uuid4(),
                work_order_number="WO-001",
                product_id=uuid4(),
                product_code="PROD",
                product_name="Test",
                planned_quantity=Decimal("-10"),
            )

    def test_validation_negative_completed_quantity_raises(self):
        with pytest.raises(ValueError, match="Completed quantity cannot be negative"):
            CostCardEntity(
                cost_card_id=uuid4(),
                work_order_id=uuid4(),
                work_order_number="WO-001",
                product_id=uuid4(),
                product_code="PROD",
                product_name="Test",
                planned_quantity=Decimal("100"),
                completed_quantity=Decimal("-5"),
                material_cost=Decimal("0"),
                labor_cost=Decimal("0"),
                overhead_cost=Decimal("0"),
                total_cost=Decimal("0"),
                unit_cost=Decimal("0"),
                status=CostCardStatus.OPEN,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )

    def test_validation_completed_exceeds_planned_raises(self):
        with pytest.raises(ValueError, match="Completed quantity exceeds planned"):
            CostCardEntity(
                cost_card_id=uuid4(),
                work_order_id=uuid4(),
                work_order_number="WO-001",
                product_id=uuid4(),
                product_code="PROD",
                product_name="Test",
                planned_quantity=Decimal("100"),
                completed_quantity=Decimal("150"),
                material_cost=Decimal("0"),
                labor_cost=Decimal("0"),
                overhead_cost=Decimal("0"),
                total_cost=Decimal("0"),
                unit_cost=Decimal("0"),
                status=CostCardStatus.OPEN,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )

    def test_validation_negative_cost_components_raises(self):
        with pytest.raises(ValueError, match="Cost components cannot be negative"):
            CostCardEntity(
                cost_card_id=uuid4(),
                work_order_id=uuid4(),
                work_order_number="WO-001",
                product_id=uuid4(),
                product_code="PROD",
                product_name="Test",
                planned_quantity=Decimal("100"),
                completed_quantity=Decimal("50"),
                material_cost=Decimal("-10"),
                labor_cost=Decimal("0"),
                overhead_cost=Decimal("0"),
                total_cost=Decimal("0"),
                unit_cost=Decimal("0"),
                status=CostCardStatus.OPEN,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )

    def test_validation_total_cost_mismatch_raises(self):
        with pytest.raises(ValueError, match="Total cost mismatch"):
            CostCardEntity(
                cost_card_id=uuid4(),
                work_order_id=uuid4(),
                work_order_number="WO-001",
                product_id=uuid4(),
                product_code="PROD",
                product_name="Test",
                planned_quantity=Decimal("100"),
                completed_quantity=Decimal("50"),
                material_cost=Decimal("100"),
                labor_cost=Decimal("200"),
                overhead_cost=Decimal("300"),
                total_cost=Decimal("700"),  # should be 600
                unit_cost=Decimal("0"),
                status=CostCardStatus.OPEN,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )

    def test_validation_unit_cost_mismatch_raises(self):
        with pytest.raises(ValueError, match="Unit cost mismatch"):
            CostCardEntity(
                cost_card_id=uuid4(),
                work_order_id=uuid4(),
                work_order_number="WO-001",
                product_id=uuid4(),
                product_code="PROD",
                product_name="Test",
                planned_quantity=Decimal("100"),
                completed_quantity=Decimal("10"),
                material_cost=Decimal("100"),
                labor_cost=Decimal("100"),
                overhead_cost=Decimal("100"),
                total_cost=Decimal("300"),
                unit_cost=Decimal("20"),  # should be 30
                status=CostCardStatus.OPEN,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )

    def test_validation_unit_cost_not_zero_when_no_completed_raises(self):
        with pytest.raises(ValueError, match="Unit cost must be zero when no units completed"):
            CostCardEntity(
                cost_card_id=uuid4(),
                work_order_id=uuid4(),
                work_order_number="WO-001",
                product_id=uuid4(),
                product_code="PROD",
                product_name="Test",
                planned_quantity=Decimal("100"),
                completed_quantity=Decimal("0"),
                material_cost=Decimal("100"),
                labor_cost=Decimal("0"),
                overhead_cost=Decimal("0"),
                total_cost=Decimal("100"),
                unit_cost=Decimal("10"),
                status=CostCardStatus.OPEN,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )

    def test_validation_version_zero_raises(self):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            CostCardEntity(
                cost_card_id=uuid4(),
                work_order_id=uuid4(),
                work_order_number="WO-001",
                product_id=uuid4(),
                product_code="PROD",
                product_name="Test",
                planned_quantity=Decimal("100"),
                completed_quantity=Decimal("0"),
                material_cost=Decimal("0"),
                labor_cost=Decimal("0"),
                overhead_cost=Decimal("0"),
                total_cost=Decimal("0"),
                unit_cost=Decimal("0"),
                status=CostCardStatus.OPEN,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                version=0,
            )

    def test_validation_naive_timestamps_raises(self):
        naive = datetime(2025, 1, 1, 10, 0)
        with pytest.raises(ValueError, match="Timestamps must be timezone-aware"):
            CostCardEntity(
                cost_card_id=uuid4(),
                work_order_id=uuid4(),
                work_order_number="WO-001",
                product_id=uuid4(),
                product_code="PROD",
                product_name="Test",
                planned_quantity=Decimal("100"),
                completed_quantity=Decimal("0"),
                material_cost=Decimal("0"),
                labor_cost=Decimal("0"),
                overhead_cost=Decimal("0"),
                total_cost=Decimal("0"),
                unit_cost=Decimal("0"),
                status=CostCardStatus.OPEN,
                created_at=naive,
                updated_at=naive,
            )


# ----------------------------------------------------------------------
# CostCardEntity - Audit Trail
# ----------------------------------------------------------------------
class TestCostCardEntityAudit:
    def test_audit_trail_created_on_creation(self, sample_cost_card):
        trail = sample_cost_card.get_audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "created"
        assert trail[0]["user_id"] == "tester"
        assert trail[0]["version"] == 1

    def test_audit_trail_appends_on_add_cost(self, sample_cost_card):
        card = sample_cost_card.add_material_cost(
            amount=Decimal("500"),
            quantity=Decimal("5"),
            unit_cost=Decimal("100"),
            transaction_date=datetime.now(UTC),
            reference_type="PO",
            reference_id=uuid4(),
            reference_number="PO-002",
            added_by="user1",
        )
        trail = card.get_audit_trail()
        assert len(trail) == 2
        assert trail[1]["action"] == "cost_added"
        assert trail[1]["user_id"] == "user1"
        assert trail[1]["details"]["amount"] == "500"

    def test_audit_trail_appends_on_complete_units(self, sample_cost_card):
        card = sample_cost_card.complete_units(Decimal("50"), "user2")
        trail = card.get_audit_trail()
        assert len(trail) == 2
        assert trail[1]["action"] == "units_completed"
        assert trail[1]["user_id"] == "user2"
        assert trail[1]["details"]["completed_quantity"] == "50"

    def test_audit_trail_appends_on_adjust_cost(self, sample_cost_card):
        card = sample_cost_card.adjust_cost(Decimal("1000"), "Correction", "user3")
        trail = card.get_audit_trail()
        assert len(trail) == 2
        assert trail[1]["action"] == "cost_adjusted"
        assert trail[1]["user_id"] == "user3"
        assert trail[1]["details"]["new_total_cost"] == "1000"

    def test_audit_trail_appends_on_clone(self, sample_cost_card):
        cloned = sample_cost_card.clone()
        cloned.get_audit_trail()
        # Cloning records audit on the original? Actually clone records audit on the new card.
        # The clone method calls _record_audit on itself.
        # The source card's audit trail remains unchanged.
        assert len(sample_cost_card.get_audit_trail()) == 1
        assert len(cloned.get_audit_trail()) == 1
        assert cloned._audit_trail[0]["action"] == "cloned"


# ----------------------------------------------------------------------
# CostCardEntity - Cost Addition Methods
# ----------------------------------------------------------------------
class TestCostCardEntityCostAddition:
    def test_add_material_cost_success(self, sample_cost_card):
        now = datetime.now(UTC)
        ref_id = uuid4()
        card = sample_cost_card.add_material_cost(
            amount=Decimal("1000"),
            quantity=Decimal("10"),
            unit_cost=Decimal("100"),
            transaction_date=now,
            reference_type="PO",
            reference_id=ref_id,
            reference_number="PO-001",
            description="Material purchase",
            added_by="user1",
        )
        assert card.material_cost == Decimal("1000")
        assert card.labor_cost == Decimal("0")
        assert card.overhead_cost == Decimal("0")
        assert card.total_cost == Decimal("1000")
        assert card.unit_cost == Decimal("0")  # no completed units yet
        assert card.version == 2
        assert len(card.entries) == 1
        entry = card.entries[0]
        assert entry.cost_element == CostElement.MATERIAL
        assert entry.amount == Decimal("1000")
        assert entry.reference_number == "PO-001"
        assert entry.description == "Material purchase"
        assert entry.created_by == "user1"

    def test_add_labor_cost_success(self, sample_cost_card):
        now = datetime.now(UTC)
        ref_id = uuid4()
        card = sample_cost_card.add_labor_cost(
            amount=Decimal("500"),
            quantity=Decimal("20"),
            unit_cost=Decimal("25"),
            transaction_date=now,
            reference_type="WORK",
            reference_id=ref_id,
            reference_number="WO-001-LABOR",
            description="Direct labor",
            added_by="user2",
        )
        assert card.material_cost == Decimal("0")
        assert card.labor_cost == Decimal("500")
        assert card.overhead_cost == Decimal("0")
        assert card.total_cost == Decimal("500")
        assert card.version == 2
        assert len(card.entries) == 1
        assert card.entries[0].cost_element == CostElement.LABOR

    def test_add_overhead_cost_success(self, sample_cost_card):
        now = datetime.now(UTC)
        ref_id = uuid4()
        card = sample_cost_card.add_overhead_cost(
            amount=Decimal("300"),
            quantity=Decimal("1"),
            unit_cost=Decimal("300"),
            transaction_date=now,
            reference_type="OVERHEAD",
            reference_id=ref_id,
            reference_number="OV-001",
            description="Factory overhead",
            added_by="user3",
        )
        assert card.material_cost == Decimal("0")
        assert card.labor_cost == Decimal("0")
        assert card.overhead_cost == Decimal("300")
        assert card.total_cost == Decimal("300")
        assert card.version == 2

    def test_add_cost_negative_amount_raises(self, sample_cost_card):
        with pytest.raises(ValueError, match="Amount must be positive"):
            sample_cost_card.add_material_cost(
                amount=Decimal("-100"),
                quantity=Decimal("1"),
                unit_cost=Decimal("100"),
                transaction_date=datetime.now(UTC),
                reference_type="PO",
                reference_id=uuid4(),
                reference_number="PO-001",
            )

    def test_add_cost_zero_amount_raises(self, sample_cost_card):
        with pytest.raises(ValueError, match="Amount must be positive"):
            sample_cost_card.add_material_cost(
                amount=Decimal("0"),
                quantity=Decimal("1"),
                unit_cost=Decimal("100"),
                transaction_date=datetime.now(UTC),
                reference_type="PO",
                reference_id=uuid4(),
                reference_number="PO-001",
            )

    def test_add_cost_negative_quantity_raises(self, sample_cost_card):
        with pytest.raises(ValueError, match="Quantity cannot be negative"):
            sample_cost_card.add_material_cost(
                amount=Decimal("100"),
                quantity=Decimal("-1"),
                unit_cost=Decimal("100"),
                transaction_date=datetime.now(UTC),
                reference_type="PO",
                reference_id=uuid4(),
                reference_number="PO-001",
            )

    def test_add_cost_negative_unit_cost_raises(self, sample_cost_card):
        with pytest.raises(ValueError, match="Unit cost cannot be negative"):
            sample_cost_card.add_material_cost(
                amount=Decimal("100"),
                quantity=Decimal("1"),
                unit_cost=Decimal("-100"),
                transaction_date=datetime.now(UTC),
                reference_type="PO",
                reference_id=uuid4(),
                reference_number="PO-001",
            )

    def test_add_multiple_costs_updates_total(self, sample_cost_card):
        card = sample_cost_card.add_material_cost(
            amount=Decimal("1000"),
            quantity=Decimal("10"),
            unit_cost=Decimal("100"),
            transaction_date=datetime.now(UTC),
            reference_type="PO",
            reference_id=uuid4(),
            reference_number="PO-001",
        )
        card = card.add_labor_cost(
            amount=Decimal("500"),
            quantity=Decimal("20"),
            unit_cost=Decimal("25"),
            transaction_date=datetime.now(UTC),
            reference_type="WORK",
            reference_id=uuid4(),
            reference_number="WO-001",
        )
        assert card.material_cost == Decimal("1000")
        assert card.labor_cost == Decimal("500")
        assert card.overhead_cost == Decimal("0")
        assert card.total_cost == Decimal("1500")
        assert len(card.entries) == 2
        assert card.version == 3


# ----------------------------------------------------------------------
# CostCardEntity - Complete Units
# ----------------------------------------------------------------------
class TestCostCardEntityCompleteUnits:
    def test_complete_units_success(self, sample_cost_card):
        # Add some cost first
        card = sample_cost_card.add_material_cost(
            amount=Decimal("1000"),
            quantity=Decimal("10"),
            unit_cost=Decimal("100"),
            transaction_date=datetime.now(UTC),
            reference_type="PO",
            reference_id=uuid4(),
            reference_number="PO-001",
        )
        card = card.complete_units(Decimal("50"), "user1")
        assert card.completed_quantity == Decimal("50")
        assert card.unit_cost == Decimal("20")  # 1000 / 50
        assert card.status == CostCardStatus.OPEN  # not fully completed
        assert card.version == 3  # started with 1, added cost (2), completed (3)

    def test_complete_units_to_closed_status(self, sample_cost_card):
        card = sample_cost_card.add_material_cost(
            amount=Decimal("1000"),
            quantity=Decimal("10"),
            unit_cost=Decimal("100"),
            transaction_date=datetime.now(UTC),
            reference_type="PO",
            reference_id=uuid4(),
            reference_number="PO-001",
        )
        card = card.complete_units(Decimal("100"), "user1")
        assert card.completed_quantity == Decimal("100")
        assert card.unit_cost == Decimal("10")
        assert card.status == CostCardStatus.CLOSED

    def test_complete_units_zero_quantity_raises(self, sample_cost_card):
        with pytest.raises(ValueError, match="Completed quantity must be positive"):
            sample_cost_card.complete_units(Decimal("0"), "user1")

    def test_complete_units_negative_quantity_raises(self, sample_cost_card):
        with pytest.raises(ValueError, match="Completed quantity must be positive"):
            sample_cost_card.complete_units(Decimal("-10"), "user1")

    def test_complete_units_exceeds_remaining_raises(self, sample_cost_card):
        card = sample_cost_card.complete_units(Decimal("80"), "user1")
        with pytest.raises(ValueError, match="only 20 remaining"):
            card.complete_units(Decimal("30"), "user1")

    def test_complete_units_updates_unit_cost_precisely(self, sample_cost_card):
        # Add cost with amount that doesn't divide evenly
        card = sample_cost_card.add_material_cost(
            amount=Decimal("1000"),
            quantity=Decimal("10"),
            unit_cost=Decimal("100"),
            transaction_date=datetime.now(UTC),
            reference_type="PO",
            reference_id=uuid4(),
            reference_number="PO-001",
        )
        card = card.add_labor_cost(
            amount=Decimal("333"),
            quantity=Decimal("10"),
            unit_cost=Decimal("33.3"),
            transaction_date=datetime.now(UTC),
            reference_type="WORK",
            reference_id=uuid4(),
            reference_number="WO-001",
        )
        # total = 1333, complete 30 units: unit_cost = 1333/30 = 44.4333... -> quantized to 44.43
        card = card.complete_units(Decimal("30"), "user1")
        expected_unit = (Decimal("1333") / Decimal("30")).quantize(Decimal("0.01"))
        assert card.unit_cost == expected_unit


# ----------------------------------------------------------------------
# CostCardEntity - Adjust Cost
# ----------------------------------------------------------------------
class TestCostCardEntityAdjustCost:
    def test_adjust_cost_success(self, sample_cost_card):
        card = sample_cost_card.add_material_cost(
            amount=Decimal("1000"),
            quantity=Decimal("10"),
            unit_cost=Decimal("100"),
            transaction_date=datetime.now(UTC),
            reference_type="PO",
            reference_id=uuid4(),
            reference_number="PO-001",
        )
        card = card.complete_units(Decimal("50"), "user1")
        # unit_cost = 20
        card = card.adjust_cost(Decimal("1200"), "Correction", "user2")
        assert card.total_cost == Decimal("1200")
        assert card.unit_cost == Decimal("24")  # 1200 / 50
        assert card.status == CostCardStatus.ADJUSTED
        assert card.version == 4  # create (1), add cost (2), complete (3), adjust (4)
        assert len(card.entries) == 2  # original cost entry + adjustment entry
        adjustment_entry = card.entries[1]
        assert adjustment_entry.cost_element == CostElement.OTHER
        assert adjustment_entry.amount == Decimal("200")  # 1200 - 1000

    def test_adjust_cost_zero_total(self, sample_cost_card):
        # No cost added, adjust to positive
        card = sample_cost_card.adjust_cost(Decimal("500"), "Initial adjustment", "user1")
        assert card.total_cost == Decimal("500")
        assert card.material_cost == Decimal("0")
        assert card.labor_cost == Decimal("0")
        assert card.overhead_cost == Decimal("0")
        # ratio logic when total_cost=0: all components stay 0
        # The adjustment entry itself is added
        assert len(card.entries) == 1
        adjustment_entry = card.entries[0]
        assert adjustment_entry.amount == Decimal("500")
        assert adjustment_entry.cost_element == CostElement.OTHER

    def test_adjust_cost_negative_total_raises(self, sample_cost_card):
        with pytest.raises(ValueError, match="Total cost cannot be negative"):
            sample_cost_card.adjust_cost(Decimal("-100"), "Invalid", "user1")

    def test_adjust_cost_affects_unit_cost_with_completed_units(self, sample_cost_card):
        card = sample_cost_card.add_material_cost(
            amount=Decimal("1000"),
            quantity=Decimal("10"),
            unit_cost=Decimal("100"),
            transaction_date=datetime.now(UTC),
            reference_type="PO",
            reference_id=uuid4(),
            reference_number="PO-001",
        )
        card = card.complete_units(Decimal("50"), "user1")
        card = card.adjust_cost(Decimal("1500"), "Increase", "user2")
        assert card.unit_cost == Decimal("30")  # 1500/50


# ----------------------------------------------------------------------
# CostCardEntity - Validation and Query Methods
# ----------------------------------------------------------------------
class TestCostCardEntityQueries:
    def test_get_remaining_quantity(self, sample_cost_card):
        card = sample_cost_card.complete_units(Decimal("30"), "user1")
        assert card.get_remaining_quantity() == Decimal("70")

    def test_get_completion_percentage(self, sample_cost_card):
        assert sample_cost_card.get_completion_percentage() == 0.0
        card = sample_cost_card.complete_units(Decimal("50"), "user1")
        assert card.get_completion_percentage() == 50.0

    def test_get_summary(self, sample_cost_card):
        card = sample_cost_card.add_material_cost(
            amount=Decimal("1000"),
            quantity=Decimal("10"),
            unit_cost=Decimal("100"),
            transaction_date=datetime.now(UTC),
            reference_type="PO",
            reference_id=uuid4(),
            reference_number="PO-001",
        )
        card = card.complete_units(Decimal("50"), "user1")
        summary = card.get_summary()
        assert summary["total_entries"] == 1
        assert summary["material_cost"] == "1000"
        assert summary["labor_cost"] == "0"
        assert summary["overhead_cost"] == "0"
        assert summary["total_cost"] == "1000"
        assert summary["unit_cost"] == "20.00"
        assert summary["completion_rate"] == 50.0
        assert summary["remaining_quantity"] == "50"

    def test_validate_valid(self, sample_cost_card):
        errors = sample_cost_card.validate()
        assert errors == []

    def test_validate_with_errors(self, sample_cost_card):
        # Corrupt the card by manually setting mismatched total
        card = CostCardEntity(
            cost_card_id=sample_cost_card.cost_card_id,
            work_order_id=sample_cost_card.work_order_id,
            work_order_number=sample_cost_card.work_order_number,
            product_id=sample_cost_card.product_id,
            product_code=sample_cost_card.product_code,
            product_name=sample_cost_card.product_name,
            planned_quantity=sample_cost_card.planned_quantity,
            completed_quantity=sample_cost_card.completed_quantity,
            material_cost=Decimal("100"),
            labor_cost=Decimal("200"),
            overhead_cost=Decimal("300"),
            total_cost=Decimal("700"),  # mismatch
            unit_cost=Decimal("0"),
            status=CostCardStatus.OPEN,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        errors = card.validate()
        assert len(errors) == 1
        assert "Total cost mismatch" in errors[0]


# ----------------------------------------------------------------------
# CostCardEntity - Clone
# ----------------------------------------------------------------------
class TestCostCardEntityClone:
    def test_clone_creates_new_id(self, sample_cost_card):
        cloned = sample_cost_card.clone()
        assert cloned.cost_card_id != sample_cost_card.cost_card_id
        assert cloned.work_order_id == sample_cost_card.work_order_id
        assert cloned.work_order_number == sample_cost_card.work_order_number
        assert cloned.product_id == sample_cost_card.product_id
        assert cloned.planned_quantity == sample_cost_card.planned_quantity
        assert cloned.completed_quantity == sample_cost_card.completed_quantity
        assert cloned.material_cost == sample_cost_card.material_cost
        assert cloned.total_cost == sample_cost_card.total_cost
        assert cloned.status == sample_cost_card.status
        assert cloned.version == 1  # reset to 1
        assert len(cloned.entries) == len(sample_cost_card.entries)
        assert cloned.entries is not sample_cost_card.entries  # new list

    def test_clone_records_audit(self, sample_cost_card):
        cloned = sample_cost_card.clone()
        trail = cloned.get_audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "cloned"
        assert trail[0]["details"]["source_id"] == str(sample_cost_card.cost_card_id)


# ----------------------------------------------------------------------
# CostCardEntity - Serialization
# ----------------------------------------------------------------------
class TestCostCardEntitySerialization:
    def test_to_dict(self, sample_cost_card):
        d = sample_cost_card.to_dict()
        assert d["cost_card_id"] == str(sample_cost_card.cost_card_id)
        assert d["work_order_id"] == str(sample_cost_card.work_order_id)
        assert d["work_order_number"] == "WO-001"
        assert d["planned_quantity"] == "100"
        assert d["completed_quantity"] == "0"
        assert d["remaining_quantity"] == "100"
        assert d["completion_percentage"] == 0.0
        assert d["material_cost"] == "0"
        assert d["total_cost"] == "0"
        assert d["unit_cost"] == "0"
        assert d["status"] == "open"
        assert d["entries"] == []
        assert d["version"] == 1

    def test_from_dict(self, sample_cost_card):
        sample_cost_card.to_dict()
        # Add some entries to test
        card_with_entries = sample_cost_card.add_material_cost(
            amount=Decimal("1000"),
            quantity=Decimal("10"),
            unit_cost=Decimal("100"),
            transaction_date=datetime.now(UTC),
            reference_type="PO",
            reference_id=uuid4(),
            reference_number="PO-001",
        )
        d2 = card_with_entries.to_dict()
        reconstructed = CostCardEntity.from_dict(d2)
        assert reconstructed.cost_card_id == card_with_entries.cost_card_id
        assert reconstructed.work_order_id == card_with_entries.work_order_id
        assert reconstructed.planned_quantity == card_with_entries.planned_quantity
        assert reconstructed.material_cost == card_with_entries.material_cost
        assert reconstructed.total_cost == card_with_entries.total_cost
        assert reconstructed.status == card_with_entries.status
        assert reconstructed.version == card_with_entries.version
        assert len(reconstructed.entries) == len(card_with_entries.entries)
        assert reconstructed.entries[0].entry_id == card_with_entries.entries[0].entry_id

    def test_from_dict_with_missing_fields_uses_defaults(self):
        # Minimal dict with required fields
        data = {
            "cost_card_id": str(uuid4()),
            "work_order_id": str(uuid4()),
            "work_order_number": "WO-001",
            "product_id": str(uuid4()),
            "product_code": "PROD",
            "product_name": "Test",
            "planned_quantity": "100",
            "completed_quantity": "0",
            "material_cost": "0",
            "labor_cost": "0",
            "overhead_cost": "0",
            "total_cost": "0",
            "unit_cost": "0",
            "status": "open",
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        card = CostCardEntity.from_dict(data)
        assert card.created_by == "system"
        assert card.version == 1
        assert card.entries == []


# ----------------------------------------------------------------------
# CostCardRepository (Interface)
# ----------------------------------------------------------------------
class TestCostCardRepository:
    @pytest.mark.asyncio
    async def test_get_by_id_not_implemented(self):
        repo = CostCardRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_id(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_get_by_work_order_not_implemented(self):
        repo = CostCardRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_work_order(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_get_by_product_not_implemented(self):
        repo = CostCardRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_product(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_get_by_date_range_not_implemented(self):
        repo = CostCardRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_date_range(uuid4(), datetime.now(UTC), datetime.now(UTC))

    @pytest.mark.asyncio
    async def test_get_open_cost_cards_not_implemented(self):
        repo = CostCardRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_open_cost_cards(uuid4())

    @pytest.mark.asyncio
    async def test_save_not_implemented(self):
        repo = CostCardRepository()
        with pytest.raises(NotImplementedError):
            await repo.save(MagicMock(), uuid4())

    @pytest.mark.asyncio
    async def test_delete_not_implemented(self):
        repo = CostCardRepository()
        with pytest.raises(NotImplementedError):
            await repo.delete(uuid4(), uuid4())


# ----------------------------------------------------------------------
# Edge Cases & Decimal Precision
# ----------------------------------------------------------------------
class TestEdgeCases:
    def test_large_numbers(self):
        card = CostCardEntity.create(
            work_order_id=uuid4(),
            work_order_number="WO-001",
            product_id=uuid4(),
            product_code="PROD",
            product_name="Test",
            planned_quantity=Decimal("999999"),
            created_by="system",
        )
        card = card.add_material_cost(
            amount=Decimal("9999999999.99"),
            quantity=Decimal("999999"),
            unit_cost=Decimal("10000.00"),
            transaction_date=datetime.now(UTC),
            reference_type="PO",
            reference_id=uuid4(),
            reference_number="PO-001",
        )
        assert card.material_cost == Decimal("9999999999.99")
        assert card.total_cost == Decimal("9999999999.99")
        card = card.complete_units(Decimal("500000"), "user")
        expected_unit = (Decimal("9999999999.99") / Decimal("500000")).quantize(Decimal("0.01"))
        assert card.unit_cost == expected_unit

    def test_division_by_zero_handled(self, sample_cost_card):
        # Unit cost when no completed units is 0
        assert sample_cost_card.unit_cost == Decimal("0")

    def test_rounding_precision_in_adjust_cost(self, sample_cost_card):
        card = sample_cost_card.add_material_cost(
            amount=Decimal("1000"),
            quantity=Decimal("10"),
            unit_cost=Decimal("100"),
            transaction_date=datetime.now(UTC),
            reference_type="PO",
            reference_id=uuid4(),
            reference_number="PO-001",
        )
        card = card.add_labor_cost(
            amount=Decimal("333.33"),
            quantity=Decimal("10"),
            unit_cost=Decimal("33.333"),
            transaction_date=datetime.now(UTC),
            reference_type="WORK",
            reference_id=uuid4(),
            reference_number="WO-001",
        )
        # total = 1333.33
        card = card.complete_units(Decimal("30"), "user")
        # unit_cost = 1333.33 / 30 = 44.444333... quantized to 44.44
        expected_unit = (Decimal("1333.33") / Decimal("30")).quantize(Decimal("0.01"))
        assert card.unit_cost == expected_unit
        # Adjust to new total
        card = card.adjust_cost(Decimal("1500.00"), "Adjust", "user")
        # new unit = 1500 / 30 = 50.00
        assert card.unit_cost == Decimal("50.00")
        # Check component ratios: material = 1000 * (1500/1333.33) = 1125.00, labor = 333.33 * (1500/1333.33) = 375.00
        # The ratio = 1500/1333.33 = 1.125
        expected_material = (Decimal("1000") * Decimal("1500") / Decimal("1333.33")).quantize(Decimal("0.01"))
        expected_labor = (Decimal("333.33") * Decimal("1500") / Decimal("1333.33")).quantize(Decimal("0.01"))
        assert card.material_cost == expected_material
        assert card.labor_cost == expected_labor
        assert card.total_cost == Decimal("1500.00")

    def test_clone_preserves_entries(self, sample_cost_card):
        card = sample_cost_card.add_material_cost(
            amount=Decimal("1000"),
            quantity=Decimal("10"),
            unit_cost=Decimal("100"),
            transaction_date=datetime.now(UTC),
            reference_type="PO",
            reference_id=uuid4(),
            reference_number="PO-001",
        )
        cloned = card.clone()
        assert len(cloned.entries) == 1
        assert cloned.entries[0].entry_id != card.entries[0].entry_id  # entries are copied, but entry objects are reused? Actually entries are list, and clone copies the list references.
        # But the entries are immutable, so it's fine.
        assert cloned.entries[0].amount == card.entries[0].amount

    def test_alias_cost_card(self):
        assert CostCard is CostCardEntity
