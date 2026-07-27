# test_cost_card_projection.py
# =============================
# Comprehensive tests for domain/manufacturing/cost_card_projection.py.
# Covers all public methods, validation, edge cases, and decimal precision.

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from domain.manufacturing.cost_card_entity import CostCardEntity, CostCardStatus
from domain.manufacturing.cost_card_projection import (
    CostCardProjection,
    CostCardProjectionRepository,
    CostCardSummary,
)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def mock_cost_card() -> MagicMock:
    """Create a mock CostCardEntity with realistic data."""
    card = MagicMock(spec=CostCardEntity)
    card.cost_card_id = uuid4()
    card.work_order_id = uuid4()
    card.work_order_number = "WO-001"
    card.product_id = uuid4()
    card.product_code = "PROD-001"
    card.product_name = "Test Product"
    card.planned_quantity = Decimal("100")
    card.completed_quantity = Decimal("75")
    card.material_cost = Decimal("1500")
    card.labor_cost = Decimal("750")
    card.overhead_cost = Decimal("500")
    card.total_cost = Decimal("2750")
    card.unit_cost = Decimal("36.67")  # 2750 / 75
    card.status = CostCardStatus.IN_PROGRESS
    card.entries = [MagicMock() for _ in range(5)]
    card.created_at = datetime(2025, 1, 1, 10, 0, tzinfo=UTC)
    card.updated_at = datetime(2025, 1, 2, 10, 0, tzinfo=UTC)
    return card


@pytest.fixture
def projection(mock_cost_card) -> CostCardProjection:
    """Create a CostCardProjection from mock cost card."""
    return CostCardProjection.from_cost_card(mock_cost_card)


@pytest.fixture
def sample_projections(projection) -> list[CostCardProjection]:
    """Create a list of projections for summary testing."""
    # Create a few projections with varying data
    proj2 = CostCardProjection(
        cost_card_id=uuid4(),
        work_order_id=uuid4(),
        work_order_number="WO-002",
        product_id=projection.product_id,
        product_code=projection.product_code,
        product_name=projection.product_name,
        planned_quantity=Decimal("200"),
        completed_quantity=Decimal("180"),
        completion_rate=90.0,
        material_cost=Decimal("3600"),
        labor_cost=Decimal("1800"),
        overhead_cost=Decimal("1200"),
        total_cost=Decimal("6600"),
        unit_cost=Decimal("36.67"),
        status=CostCardStatus.COMPLETED,
        material_cost_per_unit=Decimal("20.00"),
        labor_cost_per_unit=Decimal("10.00"),
        overhead_cost_per_unit=Decimal("6.67"),
        entry_count=8,
        created_at=datetime(2025, 1, 3, 10, 0, tzinfo=UTC),
        updated_at=datetime(2025, 1, 4, 10, 0, tzinfo=UTC),
    )
    proj3 = CostCardProjection(
        cost_card_id=uuid4(),
        work_order_id=uuid4(),
        work_order_number="WO-003",
        product_id=projection.product_id,
        product_code=projection.product_code,
        product_name=projection.product_name,
        planned_quantity=Decimal("150"),
        completed_quantity=Decimal("120"),
        completion_rate=80.0,
        material_cost=Decimal("2400"),
        labor_cost=Decimal("1200"),
        overhead_cost=Decimal("800"),
        total_cost=Decimal("4400"),
        unit_cost=Decimal("36.67"),
        status=CostCardStatus.IN_PROGRESS,
        material_cost_per_unit=Decimal("20.00"),
        labor_cost_per_unit=Decimal("10.00"),
        overhead_cost_per_unit=Decimal("6.67"),
        entry_count=6,
        created_at=datetime(2025, 1, 2, 10, 0, tzinfo=UTC),
        updated_at=datetime(2025, 1, 3, 10, 0, tzinfo=UTC),
    )
    return [projection, proj2, proj3]


# ----------------------------------------------------------------------
# CostCardProjection - Construction & Validation
# ----------------------------------------------------------------------
class TestCostCardProjectionConstruction:
    def test_construction_valid(self, mock_cost_card):
        proj = CostCardProjection.from_cost_card(mock_cost_card)
        assert proj.cost_card_id == mock_cost_card.cost_card_id
        assert proj.work_order_id == mock_cost_card.work_order_id
        assert proj.planned_quantity == Decimal("100")
        assert proj.completed_quantity == Decimal("75")
        assert proj.completion_rate == 75.0
        assert proj.material_cost == Decimal("1500")
        assert proj.total_cost == Decimal("2750")
        assert proj.unit_cost == Decimal("36.67")
        assert proj.status == CostCardStatus.IN_PROGRESS
        assert proj.entry_count == 5

    def test_construction_from_cost_card_zero_completed(self, mock_cost_card):
        mock_cost_card.completed_quantity = Decimal("0")
        proj = CostCardProjection.from_cost_card(mock_cost_card)
        assert proj.completion_rate == 0.0
        assert proj.unit_cost == Decimal(0)
        assert proj.material_cost_per_unit == Decimal(0)
        assert proj.labor_cost_per_unit == Decimal(0)
        assert proj.overhead_cost_per_unit == Decimal(0)

    def test_validation_planned_quantity_zero_raises(self):
        with pytest.raises(ValueError, match="Planned quantity must be positive"):
            CostCardProjection(
                cost_card_id=uuid4(),
                work_order_id=uuid4(),
                work_order_number="WO-001",
                product_id=uuid4(),
                product_code="P",
                product_name="N",
                planned_quantity=Decimal("0"),
                completed_quantity=Decimal("0"),
                completion_rate=0.0,
                material_cost=Decimal(0),
                labor_cost=Decimal(0),
                overhead_cost=Decimal(0),
                total_cost=Decimal(0),
                unit_cost=Decimal(0),
                status=CostCardStatus.DRAFT,
                material_cost_per_unit=Decimal(0),
                labor_cost_per_unit=Decimal(0),
                overhead_cost_per_unit=Decimal(0),
                entry_count=0,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )

    def test_validation_completed_exceeds_planned_raises(self):
        with pytest.raises(ValueError, match="Completed quantity exceeds planned"):
            CostCardProjection(
                cost_card_id=uuid4(),
                work_order_id=uuid4(),
                work_order_number="WO-001",
                product_id=uuid4(),
                product_code="P",
                product_name="N",
                planned_quantity=Decimal("100"),
                completed_quantity=Decimal("150"),
                completion_rate=150.0,
                material_cost=Decimal(0),
                labor_cost=Decimal(0),
                overhead_cost=Decimal(0),
                total_cost=Decimal(0),
                unit_cost=Decimal(0),
                status=CostCardStatus.DRAFT,
                material_cost_per_unit=Decimal(0),
                labor_cost_per_unit=Decimal(0),
                overhead_cost_per_unit=Decimal(0),
                entry_count=0,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )

    def test_validation_completion_rate_out_of_range_raises(self):
        with pytest.raises(ValueError, match="Completion rate must be between 0 and 100"):
            CostCardProjection(
                cost_card_id=uuid4(),
                work_order_id=uuid4(),
                work_order_number="WO-001",
                product_id=uuid4(),
                product_code="P",
                product_name="N",
                planned_quantity=Decimal("100"),
                completed_quantity=Decimal("50"),
                completion_rate=200.0,  # out of range
                material_cost=Decimal(0),
                labor_cost=Decimal(0),
                overhead_cost=Decimal(0),
                total_cost=Decimal(0),
                unit_cost=Decimal(0),
                status=CostCardStatus.DRAFT,
                material_cost_per_unit=Decimal(0),
                labor_cost_per_unit=Decimal(0),
                overhead_cost_per_unit=Decimal(0),
                entry_count=0,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )

    def test_validation_unit_cost_mismatch_raises(self):
        with pytest.raises(ValueError, match="Unit cost mismatch"):
            CostCardProjection(
                cost_card_id=uuid4(),
                work_order_id=uuid4(),
                work_order_number="WO-001",
                product_id=uuid4(),
                product_code="P",
                product_name="N",
                planned_quantity=Decimal("100"),
                completed_quantity=Decimal("10"),
                completion_rate=10.0,
                material_cost=Decimal("100"),
                labor_cost=Decimal("100"),
                overhead_cost=Decimal("100"),
                total_cost=Decimal("300"),
                unit_cost=Decimal("20"),  # 300/10=30, mismatch
                status=CostCardStatus.DRAFT,
                material_cost_per_unit=Decimal("10"),
                labor_cost_per_unit=Decimal("10"),
                overhead_cost_per_unit=Decimal("10"),
                entry_count=0,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )

    def test_validation_material_cost_per_unit_mismatch_raises(self):
        with pytest.raises(ValueError, match="Material cost per unit mismatch"):
            CostCardProjection(
                cost_card_id=uuid4(),
                work_order_id=uuid4(),
                work_order_number="WO-001",
                product_id=uuid4(),
                product_code="P",
                product_name="N",
                planned_quantity=Decimal("100"),
                completed_quantity=Decimal("10"),
                completion_rate=10.0,
                material_cost=Decimal("200"),
                labor_cost=Decimal("0"),
                overhead_cost=Decimal("0"),
                total_cost=Decimal("200"),
                unit_cost=Decimal("20"),
                status=CostCardStatus.DRAFT,
                material_cost_per_unit=Decimal("15"),  # should be 20
                labor_cost_per_unit=Decimal("0"),
                overhead_cost_per_unit=Decimal("0"),
                entry_count=0,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )

    def test_validation_naive_timestamps_raises(self):
        naive = datetime(2025, 1, 1, 10, 0)
        with pytest.raises(ValueError, match="Timestamps must be timezone-aware"):
            CostCardProjection(
                cost_card_id=uuid4(),
                work_order_id=uuid4(),
                work_order_number="WO-001",
                product_id=uuid4(),
                product_code="P",
                product_name="N",
                planned_quantity=Decimal("100"),
                completed_quantity=Decimal("50"),
                completion_rate=50.0,
                material_cost=Decimal(0),
                labor_cost=Decimal(0),
                overhead_cost=Decimal(0),
                total_cost=Decimal(0),
                unit_cost=Decimal(0),
                status=CostCardStatus.DRAFT,
                material_cost_per_unit=Decimal(0),
                labor_cost_per_unit=Decimal(0),
                overhead_cost_per_unit=Decimal(0),
                entry_count=0,
                created_at=naive,
                updated_at=naive,
            )

    def test_validation_negative_total_cost_raises(self):
        with pytest.raises(ValueError, match="Total cost cannot be negative"):
            CostCardProjection(
                cost_card_id=uuid4(),
                work_order_id=uuid4(),
                work_order_number="WO-001",
                product_id=uuid4(),
                product_code="P",
                product_name="N",
                planned_quantity=Decimal("100"),
                completed_quantity=Decimal("50"),
                completion_rate=50.0,
                material_cost=Decimal(0),
                labor_cost=Decimal(0),
                overhead_cost=Decimal(0),
                total_cost=Decimal("-10"),
                unit_cost=Decimal(0),
                status=CostCardStatus.DRAFT,
                material_cost_per_unit=Decimal(0),
                labor_cost_per_unit=Decimal(0),
                overhead_cost_per_unit=Decimal(0),
                entry_count=0,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )


# ----------------------------------------------------------------------
# CostCardProjection - Factory Method from_cost_card
# ----------------------------------------------------------------------
class TestCostCardProjectionFromCostCard:
    def test_from_cost_card_success(self, mock_cost_card):
        proj = CostCardProjection.from_cost_card(mock_cost_card)
        assert proj.cost_card_id == mock_cost_card.cost_card_id
        assert proj.work_order_id == mock_cost_card.work_order_id
        assert proj.work_order_number == "WO-001"
        assert proj.product_id == mock_cost_card.product_id
        assert proj.planned_quantity == Decimal("100")
        assert proj.completed_quantity == Decimal("75")
        assert proj.completion_rate == 75.0
        # Check unit cost precision
        expected_unit = (mock_cost_card.total_cost / Decimal("75")).quantize(Decimal("0.01"))
        assert proj.unit_cost == expected_unit
        assert proj.material_cost_per_unit == (mock_cost_card.material_cost / Decimal("75")).quantize(Decimal("0.01"))
        assert proj.entry_count == len(mock_cost_card.entries)

    def test_from_cost_card_zero_completed(self, mock_cost_card):
        mock_cost_card.completed_quantity = Decimal("0")
        proj = CostCardProjection.from_cost_card(mock_cost_card)
        assert proj.completion_rate == 0.0
        assert proj.unit_cost == Decimal(0)
        assert proj.material_cost_per_unit == Decimal(0)
        assert proj.labor_cost_per_unit == Decimal(0)
        assert proj.overhead_cost_per_unit == Decimal(0)

    def test_from_cost_card_planned_zero(self, mock_cost_card):
        mock_cost_card.planned_quantity = Decimal("0")
        proj = CostCardProjection.from_cost_card(mock_cost_card)
        assert proj.completion_rate == 0.0

    def test_from_cost_card_handles_large_numbers(self):
        # Test decimal precision with large numbers
        card = MagicMock(spec=CostCardEntity)
        card.cost_card_id = uuid4()
        card.work_order_id = uuid4()
        card.work_order_number = "WO-001"
        card.product_id = uuid4()
        card.product_code = "P"
        card.product_name = "N"
        card.planned_quantity = Decimal("1000")
        card.completed_quantity = Decimal("333")
        card.material_cost = Decimal("1234567.89")
        card.labor_cost = Decimal("987654.32")
        card.overhead_cost = Decimal("456789.01")
        card.total_cost = card.material_cost + card.labor_cost + card.overhead_cost
        card.unit_cost = (card.total_cost / card.completed_quantity).quantize(Decimal("0.01"))
        card.status = CostCardStatus.IN_PROGRESS
        card.entries = []
        card.created_at = datetime.now(UTC)
        card.updated_at = datetime.now(UTC)
        proj = CostCardProjection.from_cost_card(card)
        expected_unit = (card.total_cost / card.completed_quantity).quantize(Decimal("0.01"))
        assert proj.unit_cost == expected_unit
        assert proj.material_cost_per_unit == (card.material_cost / card.completed_quantity).quantize(Decimal("0.01"))


# ----------------------------------------------------------------------
# CostCardProjection - Query Methods
# ----------------------------------------------------------------------
class TestCostCardProjectionQueries:
    def test_get_remaining_quantity(self, projection):
        remaining = projection.get_remaining_quantity()
        assert remaining == Decimal("25")  # 100 - 75

    def test_get_remaining_quantity_completed(self, mock_cost_card):
        mock_cost_card.completed_quantity = Decimal("100")
        proj = CostCardProjection.from_cost_card(mock_cost_card)
        assert proj.get_remaining_quantity() == Decimal("0")

    def test_is_completed_true(self):
        proj = CostCardProjection(
            cost_card_id=uuid4(),
            work_order_id=uuid4(),
            work_order_number="WO-001",
            product_id=uuid4(),
            product_code="P",
            product_name="N",
            planned_quantity=Decimal("100"),
            completed_quantity=Decimal("100"),
            completion_rate=100.0,
            material_cost=Decimal(0),
            labor_cost=Decimal(0),
            overhead_cost=Decimal(0),
            total_cost=Decimal(0),
            unit_cost=Decimal(0),
            status=CostCardStatus.COMPLETED,
            material_cost_per_unit=Decimal(0),
            labor_cost_per_unit=Decimal(0),
            overhead_cost_per_unit=Decimal(0),
            entry_count=0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        assert proj.is_completed() is True

    def test_is_completed_false(self, projection):
        assert projection.is_completed() is False

    def test_is_over_budget(self, projection):
        # unit_cost = 36.67, standard_cost = 35.00 -> true
        assert projection.is_over_budget(Decimal("35.00")) is True
        # standard_cost = 40.00 -> false
        assert projection.is_over_budget(Decimal("40.00")) is False

    def test_is_over_budget_equal(self, projection):
        assert projection.is_over_budget(Decimal("36.67")) is False  # equal, not over


# ----------------------------------------------------------------------
# CostCardProjection - Serialization
# ----------------------------------------------------------------------
class TestCostCardProjectionSerialization:
    def test_to_dict(self, projection):
        d = projection.to_dict()
        assert d["cost_card_id"] == str(projection.cost_card_id)
        assert d["work_order_id"] == str(projection.work_order_id)
        assert d["work_order_number"] == "WO-001"
        assert d["planned_quantity"] == "100"
        assert d["completed_quantity"] == "75"
        assert d["remaining_quantity"] == "25"
        assert d["completion_rate"] == 75.0
        assert d["material_cost"] == "1500"
        assert d["total_cost"] == "2750"
        assert d["unit_cost"] == "36.67"
        assert d["status"] == "in_progress"
        assert d["entry_count"] == 5
        assert d["created_at"] == projection.created_at.isoformat()
        assert d["updated_at"] == projection.updated_at.isoformat()


# ----------------------------------------------------------------------
# CostCardProjectionRepository (Interface)
# ----------------------------------------------------------------------
class TestCostCardProjectionRepository:
    @pytest.mark.asyncio
    async def test_get_by_id_not_implemented(self):
        repo = CostCardProjectionRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_id(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_get_by_work_order_not_implemented(self):
        repo = CostCardProjectionRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_work_order(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_get_by_product_not_implemented(self):
        repo = CostCardProjectionRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_product(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_get_by_date_range_not_implemented(self):
        repo = CostCardProjectionRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_date_range(uuid4(), datetime.now(UTC), datetime.now(UTC))

    @pytest.mark.asyncio
    async def test_get_open_cost_cards_not_implemented(self):
        repo = CostCardProjectionRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_open_cost_cards(uuid4())

    @pytest.mark.asyncio
    async def test_save_not_implemented(self):
        repo = CostCardProjectionRepository()
        with pytest.raises(NotImplementedError):
            await repo.save(MagicMock(), uuid4())

    @pytest.mark.asyncio
    async def test_delete_not_implemented(self):
        repo = CostCardProjectionRepository()
        with pytest.raises(NotImplementedError):
            await repo.delete(uuid4(), uuid4())


# ----------------------------------------------------------------------
# CostCardSummary - Construction & Validation
# ----------------------------------------------------------------------
class TestCostCardSummaryConstruction:
    def test_construction_valid(self, sample_projections):
        start = datetime(2025, 1, 1, tzinfo=UTC)
        end = datetime(2025, 1, 31, tzinfo=UTC)
        summary = CostCardSummary.from_projections(
            sample_projections,
            product_id=sample_projections[0].product_id,
            product_code="PROD-001",
            product_name="Test Product",
            period_start=start,
            period_end=end,
        )
        assert summary.product_id == sample_projections[0].product_id
        assert summary.total_work_orders == 3
        assert summary.total_planned_quantity == Decimal("450")
        assert summary.total_completed_quantity == Decimal("375")
        assert summary.total_cost == Decimal("13750")
        assert summary.average_unit_cost == (Decimal("13750") / Decimal("375")).quantize(Decimal("0.01"))

    def test_validation_negative_planned_raises(self):
        with pytest.raises(ValueError, match="Total planned quantity cannot be negative"):
            CostCardSummary(
                product_id=uuid4(),
                product_code="P",
                product_name="N",
                period_start=datetime.now(UTC),
                period_end=datetime.now(UTC) + timedelta(days=1),
                total_work_orders=0,
                total_planned_quantity=Decimal("-1"),
                total_completed_quantity=Decimal(0),
                total_material_cost=Decimal(0),
                total_labor_cost=Decimal(0),
                total_overhead_cost=Decimal(0),
                total_cost=Decimal(0),
                average_unit_cost=Decimal(0),
                average_material_cost_per_unit=Decimal(0),
                average_labor_cost_per_unit=Decimal(0),
                average_overhead_cost_per_unit=Decimal(0),
            )

    def test_validation_period_end_before_start_raises(self):
        with pytest.raises(ValueError, match="Period end must be after period start"):
            CostCardSummary(
                product_id=uuid4(),
                product_code="P",
                product_name="N",
                period_start=datetime.now(UTC),
                period_end=datetime.now(UTC) - timedelta(days=1),
                total_work_orders=0,
                total_planned_quantity=Decimal(0),
                total_completed_quantity=Decimal(0),
                total_material_cost=Decimal(0),
                total_labor_cost=Decimal(0),
                total_overhead_cost=Decimal(0),
                total_cost=Decimal(0),
                average_unit_cost=Decimal(0),
                average_material_cost_per_unit=Decimal(0),
                average_labor_cost_per_unit=Decimal(0),
                average_overhead_cost_per_unit=Decimal(0),
            )

    def test_validation_naive_dates_raises(self):
        naive_start = datetime(2025, 1, 1, 10, 0)
        naive_end = datetime(2025, 1, 2, 10, 0)
        with pytest.raises(ValueError, match="Period dates must be timezone-aware"):
            CostCardSummary(
                product_id=uuid4(),
                product_code="P",
                product_name="N",
                period_start=naive_start,
                period_end=naive_end,
                total_work_orders=0,
                total_planned_quantity=Decimal(0),
                total_completed_quantity=Decimal(0),
                total_material_cost=Decimal(0),
                total_labor_cost=Decimal(0),
                total_overhead_cost=Decimal(0),
                total_cost=Decimal(0),
                average_unit_cost=Decimal(0),
                average_material_cost_per_unit=Decimal(0),
                average_labor_cost_per_unit=Decimal(0),
                average_overhead_cost_per_unit=Decimal(0),
            )


# ----------------------------------------------------------------------
# CostCardSummary - from_projections
# ----------------------------------------------------------------------
class TestCostCardSummaryFromProjections:
    def test_from_projections_with_data(self, sample_projections):
        start = datetime(2025, 1, 1, tzinfo=UTC)
        end = datetime(2025, 1, 31, tzinfo=UTC)
        summary = CostCardSummary.from_projections(
            sample_projections,
            product_id=sample_projections[0].product_id,
            product_code="PROD-001",
            product_name="Test Product",
            period_start=start,
            period_end=end,
        )
        assert summary.total_work_orders == 3
        assert summary.total_planned_quantity == Decimal("100+200+150")  # 450
        assert summary.total_completed_quantity == Decimal("75+180+120")  # 375
        assert summary.total_material_cost == Decimal("1500+3600+2400")  # 7500
        assert summary.total_labor_cost == Decimal("750+1800+1200")  # 3750
        assert summary.total_overhead_cost == Decimal("500+1200+800")  # 2500
        assert summary.total_cost == Decimal("2750+6600+4400")  # 13750
        expected_avg_unit = (Decimal("13750") / Decimal("375")).quantize(Decimal("0.01"))
        assert summary.average_unit_cost == expected_avg_unit

    def test_from_projections_empty_list(self):
        start = datetime(2025, 1, 1, tzinfo=UTC)
        end = datetime(2025, 1, 31, tzinfo=UTC)
        summary = CostCardSummary.from_projections(
            [],
            product_id=uuid4(),
            product_code="P",
            product_name="N",
            period_start=start,
            period_end=end,
        )
        assert summary.total_work_orders == 0
        assert summary.total_planned_quantity == Decimal(0)
        assert summary.total_completed_quantity == Decimal(0)
        assert summary.total_cost == Decimal(0)
        assert summary.average_unit_cost == Decimal(0)

    def test_from_projections_zero_completed(self):
        # Create projection with zero completed
        proj = CostCardProjection(
            cost_card_id=uuid4(),
            work_order_id=uuid4(),
            work_order_number="WO-001",
            product_id=uuid4(),
            product_code="P",
            product_name="N",
            planned_quantity=Decimal("100"),
            completed_quantity=Decimal("0"),
            completion_rate=0.0,
            material_cost=Decimal(0),
            labor_cost=Decimal(0),
            overhead_cost=Decimal(0),
            total_cost=Decimal(0),
            unit_cost=Decimal(0),
            status=CostCardStatus.IN_PROGRESS,
            material_cost_per_unit=Decimal(0),
            labor_cost_per_unit=Decimal(0),
            overhead_cost_per_unit=Decimal(0),
            entry_count=0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        start = datetime(2025, 1, 1, tzinfo=UTC)
        end = datetime(2025, 1, 31, tzinfo=UTC)
        summary = CostCardSummary.from_projections(
            [proj],
            product_id=proj.product_id,
            product_code="P",
            product_name="N",
            period_start=start,
            period_end=end,
        )
        assert summary.total_completed_quantity == Decimal(0)
        assert summary.average_unit_cost == Decimal(0)
        assert summary.average_material_cost_per_unit == Decimal(0)
        assert summary.average_labor_cost_per_unit == Decimal(0)
        assert summary.average_overhead_cost_per_unit == Decimal(0)

    def test_from_projections_handles_decimal_precision(self):
        # Test with values that produce repeating decimals
        proj1 = CostCardProjection(
            cost_card_id=uuid4(),
            work_order_id=uuid4(),
            work_order_number="WO-001",
            product_id=uuid4(),
            product_code="P",
            product_name="N",
            planned_quantity=Decimal("100"),
            completed_quantity=Decimal("30"),
            completion_rate=30.0,
            material_cost=Decimal("1000"),
            labor_cost=Decimal("500"),
            overhead_cost=Decimal("300"),
            total_cost=Decimal("1800"),
            unit_cost=Decimal("60.00"),
            status=CostCardStatus.IN_PROGRESS,
            material_cost_per_unit=Decimal("33.33"),
            labor_cost_per_unit=Decimal("16.67"),
            overhead_cost_per_unit=Decimal("10.00"),
            entry_count=0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        proj2 = CostCardProjection(
            cost_card_id=uuid4(),
            work_order_id=uuid4(),
            work_order_number="WO-002",
            product_id=proj1.product_id,
            product_code="P",
            product_name="N",
            planned_quantity=Decimal("200"),
            completed_quantity=Decimal("60"),
            completion_rate=30.0,
            material_cost=Decimal("2000"),
            labor_cost=Decimal("1000"),
            overhead_cost=Decimal("600"),
            total_cost=Decimal("3600"),
            unit_cost=Decimal("60.00"),
            status=CostCardStatus.IN_PROGRESS,
            material_cost_per_unit=Decimal("33.33"),
            labor_cost_per_unit=Decimal("16.67"),
            overhead_cost_per_unit=Decimal("10.00"),
            entry_count=0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        start = datetime(2025, 1, 1, tzinfo=UTC)
        end = datetime(2025, 1, 31, tzinfo=UTC)
        summary = CostCardSummary.from_projections(
            [proj1, proj2],
            product_id=proj1.product_id,
            product_code="P",
            product_name="N",
            period_start=start,
            period_end=end,
        )
        # Total completed = 90, total cost = 5400, avg = 60.00
        assert summary.average_unit_cost == Decimal("60.00")
        assert summary.average_material_cost_per_unit == Decimal("33.33")
        assert summary.average_labor_cost_per_unit == Decimal("16.67")
        assert summary.average_overhead_cost_per_unit == Decimal("10.00")


# ----------------------------------------------------------------------
# CostCardSummary - Query Methods
# ----------------------------------------------------------------------
class TestCostCardSummaryQueries:
    def test_get_completion_rate(self, sample_projections):
        start = datetime(2025, 1, 1, tzinfo=UTC)
        end = datetime(2025, 1, 31, tzinfo=UTC)
        summary = CostCardSummary.from_projections(
            sample_projections,
            product_id=sample_projections[0].product_id,
            product_code="PROD-001",
            product_name="Test Product",
            period_start=start,
            period_end=end,
        )
        # total_planned = 450, total_completed = 375 => 83.333...
        assert summary.get_completion_rate() == pytest.approx(83.3333, rel=1e-4)

    def test_get_completion_rate_zero_planned(self):
        summary = CostCardSummary(
            product_id=uuid4(),
            product_code="P",
            product_name="N",
            period_start=datetime.now(UTC),
            period_end=datetime.now(UTC) + timedelta(days=1),
            total_work_orders=0,
            total_planned_quantity=Decimal("0"),
            total_completed_quantity=Decimal("0"),
            total_material_cost=Decimal(0),
            total_labor_cost=Decimal(0),
            total_overhead_cost=Decimal(0),
            total_cost=Decimal(0),
            average_unit_cost=Decimal(0),
            average_material_cost_per_unit=Decimal(0),
            average_labor_cost_per_unit=Decimal(0),
            average_overhead_cost_per_unit=Decimal(0),
        )
        assert summary.get_completion_rate() == 0.0


# ----------------------------------------------------------------------
# CostCardSummary - Serialization
# ----------------------------------------------------------------------
class TestCostCardSummarySerialization:
    def test_to_dict(self, sample_projections):
        start = datetime(2025, 1, 1, tzinfo=UTC)
        end = datetime(2025, 1, 31, tzinfo=UTC)
        summary = CostCardSummary.from_projections(
            sample_projections,
            product_id=sample_projections[0].product_id,
            product_code="PROD-001",
            product_name="Test Product",
            period_start=start,
            period_end=end,
        )
        d = summary.to_dict()
        assert d["product_id"] == str(summary.product_id)
        assert d["product_code"] == "PROD-001"
        assert d["period_start"] == start.isoformat()
        assert d["period_end"] == end.isoformat()
        assert d["total_work_orders"] == 3
        assert d["total_planned_quantity"] == "450"
        assert d["total_completed_quantity"] == "375"
        assert d["completion_rate"] == pytest.approx(83.3333, rel=1e-4)
        assert d["total_cost"] == "13750"
        assert d["average_unit_cost"] == (Decimal("13750") / Decimal("375")).quantize(Decimal("0.01")).to_eng_string()