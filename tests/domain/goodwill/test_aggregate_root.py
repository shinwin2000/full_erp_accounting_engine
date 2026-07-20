# test_aggregate_root.py
# Comprehensive tests for aggregate_root.py (Goodwill domain)

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from domain.goodwill.aggregate_root import (
    DuplicateGoodwillNumberError,
    Goodwill,
    GoodwillAggregate,
    GoodwillAllocation,
    GoodwillAlreadyDisposedError,
    GoodwillError,
    GoodwillImpairmentHistory,
    GoodwillRepository,
    GoodwillStatus,
    InvalidGoodwillAmountError,
    InvalidImpairmentAmountError,
    InvalidReversalAmountError,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def reset_audit_trail():
    """Reset class variables before each test."""
    GoodwillAggregate._audit_trail = []
    GoodwillAggregate._snapshots = []
    GoodwillRepository._storage = {}
    yield
    GoodwillAggregate._audit_trail = []
    GoodwillAggregate._snapshots = []
    GoodwillRepository._storage = {}


@pytest.fixture
def legal_entity_id():
    return uuid4()


@pytest.fixture
def valid_goodwill(legal_entity_id):
    """Create a valid Goodwill entity."""
    return Goodwill.acquire(
        legal_entity_id=legal_entity_id,
        goodwill_number="GW-001",
        amount=Decimal("1000000"),
        acquisition_date=date(2024, 1, 1),
        cgu_code="CGU-01",
        cgu_name="Cash Generating Unit A",
        description="Goodwill from acquisition of Company X",
        created_by=uuid4(),
    )


@pytest.fixture
def goodwill_aggregate(valid_goodwill):
    """Create a GoodwillAggregate from a valid Goodwill."""
    agg = GoodwillAggregate(valid_goodwill)
    # Ensure we have a clean state
    agg._events = []
    return agg


@pytest.fixture
def allocation_data():
    return {
        "cgu_code": "CGU-02",
        "cgu_name": "Cash Generating Unit B",
        "allocated_amount": Decimal("300000"),
        "percentage": Decimal("30"),
    }


@pytest.fixture
def allocation(allocation_data):
    return GoodwillAllocation(**allocation_data)


# ============================================================================
# Tests for GoodwillStatus Enum
# ============================================================================

class TestGoodwillStatus:
    def test_display_name(self):
        assert GoodwillStatus.ACTIVE.display_name() == "Aktif"
        assert GoodwillStatus.IMPAIRED.display_name() == "Mengalami Penurunan Nilai"
        assert GoodwillStatus.PARTIALLY_IMPAIRED.display_name() == "Penurunan Nilai Sebagian"
        assert GoodwillStatus.FULLY_AMORTIZED.display_name() == "Tersusut Penuh"
        assert GoodwillStatus.DISPOSED.display_name() == "Dihapuskan"
        assert GoodwillStatus.REVERSED.display_name() == "Pemulihan Penurunan Nilai"

    def test_can_impair(self):
        assert GoodwillStatus.ACTIVE.can_impair() is True
        assert GoodwillStatus.PARTIALLY_IMPAIRED.can_impair() is True
        assert GoodwillStatus.IMPAIRED.can_impair() is False
        assert GoodwillStatus.FULLY_AMORTIZED.can_impair() is False
        assert GoodwillStatus.DISPOSED.can_impair() is False
        assert GoodwillStatus.REVERSED.can_impair() is False

    def test_can_reverse(self):
        assert GoodwillStatus.PARTIALLY_IMPAIRED.can_reverse() is True
        assert GoodwillStatus.IMPAIRED.can_reverse() is True
        assert GoodwillStatus.ACTIVE.can_reverse() is False
        assert GoodwillStatus.FULLY_AMORTIZED.can_reverse() is False
        assert GoodwillStatus.DISPOSED.can_reverse() is False
        assert GoodwillStatus.REVERSED.can_reverse() is False

    def test_from_string(self):
        assert GoodwillStatus.from_string("active") == GoodwillStatus.ACTIVE
        assert GoodwillStatus.from_string("impaired") == GoodwillStatus.IMPAIRED
        assert GoodwillStatus.from_string("partially_impaired") == GoodwillStatus.PARTIALLY_IMPAIRED
        assert GoodwillStatus.from_string("fully_amortized") == GoodwillStatus.FULLY_AMORTIZED
        assert GoodwillStatus.from_string("disposed") == GoodwillStatus.DISPOSED
        assert GoodwillStatus.from_string("reversed") == GoodwillStatus.REVERSED
        assert GoodwillStatus.from_string("unknown") is None


# ============================================================================
# Tests for GoodwillAllocation VO
# ============================================================================

class TestGoodwillAllocation:
    def test_construction_valid(self, allocation):
        assert allocation.cgu_code == "CGU-02"
        assert allocation.allocated_amount == Decimal("300000")
        assert allocation.percentage == Decimal("30")
        assert allocation.allocated_at.tzinfo is not None

    def test_validation_cgu_code_empty(self):
        with pytest.raises(GoodwillError, match="CGU code must be non-empty"):
            GoodwillAllocation(
                cgu_code="",
                cgu_name="Test",
                allocated_amount=Decimal("100"),
                percentage=Decimal("10"),
            )

    def test_validation_cgu_name_empty(self):
        with pytest.raises(GoodwillError, match="CGU name must be non-empty"):
            GoodwillAllocation(
                cgu_code="CGU",
                cgu_name="",
                allocated_amount=Decimal("100"),
                percentage=Decimal("10"),
            )

    def test_validation_allocated_amount_non_positive(self):
        with pytest.raises(GoodwillError, match="Allocated amount must be positive"):
            GoodwillAllocation(
                cgu_code="CGU",
                cgu_name="Test",
                allocated_amount=Decimal("-100"),
                percentage=Decimal("10"),
            )
        with pytest.raises(GoodwillError, match="Allocated amount must be positive"):
            GoodwillAllocation(
                cgu_code="CGU",
                cgu_name="Test",
                allocated_amount=Decimal("0"),
                percentage=Decimal("10"),
            )

    def test_validation_percentage_out_of_range(self):
        with pytest.raises(GoodwillError, match="Percentage must be 0-100"):
            GoodwillAllocation(
                cgu_code="CGU",
                cgu_name="Test",
                allocated_amount=Decimal("100"),
                percentage=Decimal("-1"),
            )
        with pytest.raises(GoodwillError, match="Percentage must be 0-100"):
            GoodwillAllocation(
                cgu_code="CGU",
                cgu_name="Test",
                allocated_amount=Decimal("100"),
                percentage=Decimal("101"),
            )

    def test_to_dict(self, allocation):
        d = allocation.to_dict()
        assert d["cgu_code"] == "CGU-02"
        assert d["cgu_name"] == "Cash Generating Unit B"
        assert d["allocated_amount"] == "300000"
        assert d["percentage"] == "30"
        assert "allocated_at" in d

    def test_from_dict(self):
        now = datetime.now(UTC)
        data = {
            "cgu_code": "CGU-03",
            "cgu_name": "Unit C",
            "allocated_amount": "500000",
            "percentage": "50",
            "allocated_at": now.isoformat(),
        }
        alloc = GoodwillAllocation.from_dict(data)
        assert alloc.cgu_code == "CGU-03"
        assert alloc.allocated_amount == Decimal("500000")
        assert alloc.percentage == Decimal("50")
        assert alloc.allocated_at == now


# ============================================================================
# Tests for GoodwillImpairmentHistory VO
# ============================================================================

class TestGoodwillImpairmentHistory:
    def test_construction(self):
        now = datetime.now(UTC)
        hid = uuid4()
        gid = uuid4()
        history = GoodwillImpairmentHistory(
            impairment_id=hid,
            goodwill_id=gid,
            impairment_date=date(2024, 6, 1),
            impairment_amount=Decimal("200000"),
            carrying_before=Decimal("1000000"),
            carrying_after=Decimal("800000"),
            recoverable_amount=Decimal("850000"),
            impairment_loss_total_before=Decimal("0"),
            impairment_loss_total_after=Decimal("200000"),
            tested_by="auditor1",
            notes="Test impairment",
            created_at=now,
        )
        assert history.impairment_id == hid
        assert history.goodwill_id == gid
        assert history.impairment_amount == Decimal("200000")
        assert history.notes == "Test impairment"

    def test_to_dict(self):
        hid = uuid4()
        gid = uuid4()
        now = datetime.now(UTC)
        history = GoodwillImpairmentHistory(
            impairment_id=hid,
            goodwill_id=gid,
            impairment_date=date(2024, 6, 1),
            impairment_amount=Decimal("200000"),
            carrying_before=Decimal("1000000"),
            carrying_after=Decimal("800000"),
            recoverable_amount=Decimal("850000"),
            impairment_loss_total_before=Decimal("0"),
            impairment_loss_total_after=Decimal("200000"),
            tested_by="auditor1",
            notes="Test",
            created_at=now,
        )
        d = history.to_dict()
        assert d["impairment_id"] == str(hid)
        assert d["goodwill_id"] == str(gid)
        assert d["impairment_amount"] == "200000"
        assert d["tested_by"] == "auditor1"

    def test_from_dict(self):
        hid = uuid4()
        gid = uuid4()
        now = datetime.now(UTC)
        data = {
            "impairment_id": str(hid),
            "goodwill_id": str(gid),
            "impairment_date": "2024-06-01",
            "impairment_amount": "200000",
            "carrying_before": "1000000",
            "carrying_after": "800000",
            "recoverable_amount": "850000",
            "impairment_loss_total_before": "0",
            "impairment_loss_total_after": "200000",
            "tested_by": "auditor1",
            "notes": "Test",
            "created_at": now.isoformat(),
        }
        history = GoodwillImpairmentHistory.from_dict(data)
        assert history.impairment_id == hid
        assert history.impairment_amount == Decimal("200000")
        assert history.tested_by == "auditor1"


# ============================================================================
# Tests for Goodwill Entity
# ============================================================================

class TestGoodwillEntity:
    def test_acquire_valid(self, legal_entity_id):
        goodwill = Goodwill.acquire(
            legal_entity_id=legal_entity_id,
            goodwill_number="GW-002",
            amount=Decimal("2000000"),
            acquisition_date=date(2024, 1, 1),
            cgu_code="CGU-10",
            cgu_name="Unit X",
            description="Acquisition of Subsidiary",
            created_by=uuid4(),
        )
        assert goodwill.id is not None
        assert goodwill.goodwill_number == "GW-002"
        assert goodwill.amount == Decimal("2000000")
        assert goodwill.carrying_amount == Decimal("2000000")
        assert goodwill.status == GoodwillStatus.ACTIVE
        assert goodwill.impairment_loss_total == Decimal("0")
        assert goodwill.accumulated_amortization == Decimal("0")

    def test_acquire_invalid_amount(self, legal_entity_id):
        with pytest.raises(InvalidGoodwillAmountError, match="positive"):
            Goodwill.acquire(
                legal_entity_id=legal_entity_id,
                goodwill_number="GW-003",
                amount=Decimal("-100"),
                acquisition_date=date(2024, 1, 1),
                cgu_code="CGU",
                cgu_name="Unit",
            )

    def test_validation_goodwill_number_too_short(self, legal_entity_id):
        with pytest.raises(GoodwillError, match="at least 3 characters"):
            Goodwill(
                id=uuid4(),
                goodwill_number="GW",
                legal_entity_id=legal_entity_id,
                amount=Decimal("1000"),
                carrying_amount=Decimal("1000"),
                acquisition_date=date(2024, 1, 1),
                description="Test",
                cgu_code="CGU",
                cgu_name="Unit",
            )

    def test_validation_amount_positive(self, legal_entity_id):
        with pytest.raises(InvalidGoodwillAmountError, match="positive"):
            Goodwill(
                id=uuid4(),
                goodwill_number="GW-001",
                legal_entity_id=legal_entity_id,
                amount=Decimal("0"),
                carrying_amount=Decimal("0"),
                acquisition_date=date(2024, 1, 1),
                description="Test",
                cgu_code="CGU",
                cgu_name="Unit",
            )

    def test_validation_carrying_negative(self, legal_entity_id):
        with pytest.raises(GoodwillError, match="cannot be negative"):
            Goodwill(
                id=uuid4(),
                goodwill_number="GW-001",
                legal_entity_id=legal_entity_id,
                amount=Decimal("1000"),
                carrying_amount=Decimal("-100"),
                acquisition_date=date(2024, 1, 1),
                description="Test",
                cgu_code="CGU",
                cgu_name="Unit",
            )

    def test_validation_carrying_exceeds_amount(self, legal_entity_id):
        with pytest.raises(GoodwillError, match="exceeds original amount"):
            Goodwill(
                id=uuid4(),
                goodwill_number="GW-001",
                legal_entity_id=legal_entity_id,
                amount=Decimal("1000"),
                carrying_amount=Decimal("1500"),
                acquisition_date=date(2024, 1, 1),
                description="Test",
                cgu_code="CGU",
                cgu_name="Unit",
            )

    def test_validation_impairment_total_negative(self, legal_entity_id):
        with pytest.raises(GoodwillError, match="cannot be negative"):
            Goodwill(
                id=uuid4(),
                goodwill_number="GW-001",
                legal_entity_id=legal_entity_id,
                amount=Decimal("1000"),
                carrying_amount=Decimal("1000"),
                acquisition_date=date(2024, 1, 1),
                description="Test",
                cgu_code="CGU",
                cgu_name="Unit",
                impairment_loss_total=Decimal("-100"),
            )

    def test_validation_impairment_total_exceeds_amount(self, legal_entity_id):
        with pytest.raises(GoodwillError, match="exceeds amount"):
            Goodwill(
                id=uuid4(),
                goodwill_number="GW-001",
                legal_entity_id=legal_entity_id,
                amount=Decimal("1000"),
                carrying_amount=Decimal("1000"),
                acquisition_date=date(2024, 1, 1),
                description="Test",
                cgu_code="CGU",
                cgu_name="Unit",
                impairment_loss_total=Decimal("2000"),
            )

    def test_validation_acquisition_date_future(self, legal_entity_id):
        future = date.today() + timedelta(days=10)
        with pytest.raises(GoodwillError, match="cannot be in the future"):
            Goodwill(
                id=uuid4(),
                goodwill_number="GW-001",
                legal_entity_id=legal_entity_id,
                amount=Decimal("1000"),
                carrying_amount=Decimal("1000"),
                acquisition_date=future,
                description="Test",
                cgu_code="CGU",
                cgu_name="Unit",
            )

    def test_validation_allocations_exceed(self, legal_entity_id):
        alloc1 = GoodwillAllocation(
            cgu_code="CGU1",
            cgu_name="Unit 1",
            allocated_amount=Decimal("600"),
            percentage=Decimal("60"),
        )
        alloc2 = GoodwillAllocation(
            cgu_code="CGU2",
            cgu_name="Unit 2",
            allocated_amount=Decimal("500"),
            percentage=Decimal("50"),
        )
        with pytest.raises(GoodwillError, match="Total allocated .* exceeds"):
            Goodwill(
                id=uuid4(),
                goodwill_number="GW-001",
                legal_entity_id=legal_entity_id,
                amount=Decimal("1000"),
                carrying_amount=Decimal("1000"),
                acquisition_date=date(2024, 1, 1),
                description="Test",
                cgu_code="CGU",
                cgu_name="Unit",
                allocations=[alloc1, alloc2],
            )

    def test_validation_version(self, legal_entity_id):
        with pytest.raises(GoodwillError, match="Version must be >= 1"):
            Goodwill(
                id=uuid4(),
                goodwill_number="GW-001",
                legal_entity_id=legal_entity_id,
                amount=Decimal("1000"),
                carrying_amount=Decimal("1000"),
                acquisition_date=date(2024, 1, 1),
                description="Test",
                cgu_code="CGU",
                cgu_name="Unit",
                version=0,
            )

    def test_properties(self, valid_goodwill):
        # is_fully_impaired
        assert valid_goodwill.is_fully_impaired is False
        # impairment_percentage
        assert valid_goodwill.impairment_percentage == 0.0
        # carrying_value
        assert valid_goodwill.carrying_value == valid_goodwill.carrying_amount
        # accumulated_impairment
        assert valid_goodwill.accumulated_impairment == Decimal("0")
        # is_amortizable
        assert valid_goodwill.is_amortizable is True
        # remaining_to_amortize
        assert valid_goodwill.remaining_to_amortize == valid_goodwill.carrying_amount
        # remaining_impairment_capacity
        assert valid_goodwill.remaining_impairment_capacity == valid_goodwill.carrying_amount

        # After full impairment
        impaired = Goodwill(
            **{**valid_goodwill.__dict__, "carrying_amount": Decimal("0"), "impairment_loss_total": valid_goodwill.amount}
        )
        assert impaired.is_fully_impaired is True
        assert impaired.impairment_percentage == 100.0
        assert impaired.is_amortizable is False
        assert impaired.remaining_to_amortize == Decimal("0")

    def test_to_dict(self, valid_goodwill):
        d = valid_goodwill.to_dict(include_history=False)
        assert d["id"] == str(valid_goodwill.id)
        assert d["goodwill_number"] == "GW-001"
        assert d["amount"] == "1000000"
        assert d["carrying_amount"] == "1000000"
        assert d["status"] == "active"
        assert d["is_fully_impaired"] is False
        assert d["impairment_percentage"] == 0.0
        assert "allocations" in d
        assert "impairment_history" not in d

    def test_to_dict_with_history(self, valid_goodwill):
        # Add some history
        agg = GoodwillAggregate(valid_goodwill)
        agg.record_impairment(
            impairment_amount=Decimal("200000"),
            recoverable_amount=Decimal("800000"),
            tested_by="auditor",
        )
        d = agg.goodwill.to_dict(include_history=True)
        assert "impairment_history" in d
        assert len(d["impairment_history"]) == 1
        assert d["impairment_history"][0]["impairment_amount"] == "200000"

    def test_from_dict(self, valid_goodwill):
        data = valid_goodwill.to_dict()
        restored = Goodwill.from_dict(data)
        assert restored.id == valid_goodwill.id
        assert restored.goodwill_number == valid_goodwill.goodwill_number
        assert restored.amount == valid_goodwill.amount
        assert restored.carrying_amount == valid_goodwill.carrying_amount
        assert restored.status == valid_goodwill.status

    def test_from_dict_with_invalid_status(self, valid_goodwill):
        data = valid_goodwill.to_dict()
        data["status"] = "invalid_status"
        # from_dict should fallback to ACTIVE
        restored = Goodwill.from_dict(data)
        assert restored.status == GoodwillStatus.ACTIVE


# ============================================================================
# Tests for GoodwillAggregate
# ============================================================================

class TestGoodwillAggregateEventMethods:
    def test_register_event(self, goodwill_aggregate):
        event = {"event_type": "TestEvent"}
        goodwill_aggregate.register_event(event)
        assert len(goodwill_aggregate._events) == 1
        assert goodwill_aggregate._events[0] == event

    def test_get_events(self, goodwill_aggregate):
        event = {"event_type": "Test"}
        goodwill_aggregate.register_event(event)
        events = goodwill_aggregate.get_events()
        assert len(events) == 1
        assert events[0] == event
        # Ensure it's a copy
        assert events is not goodwill_aggregate._events

    def test_pull_events(self, goodwill_aggregate):
        event = {"event_type": "Test"}
        goodwill_aggregate.register_event(event)
        events = goodwill_aggregate.pull_events()
        assert len(events) == 1
        assert len(goodwill_aggregate._events) == 0

    def test_clear_events(self, goodwill_aggregate):
        goodwill_aggregate.register_event({"event_type": "Test"})
        assert len(goodwill_aggregate._events) == 1
        goodwill_aggregate.clear_events()
        assert len(goodwill_aggregate._events) == 0

    def test_apply(self, goodwill_aggregate):
        event = {"event_type": "ApplyEvent"}
        goodwill_aggregate.apply(event)
        assert len(goodwill_aggregate._events) == 1

    def test_replay(self, goodwill_aggregate):
        events = [{"event_type": "E1"}, {"event_type": "E2"}]
        goodwill_aggregate.replay(events)
        assert len(goodwill_aggregate._events) == 2
        assert goodwill_aggregate.version == 1 + 2  # initial version 1 + len(events)

    def test_reconstruct(self, goodwill_aggregate):
        events = [{"event_type": "E1"}]
        goodwill_aggregate.reconstruct(events)
        assert len(goodwill_aggregate._events) == 1
        assert goodwill_aggregate.version == 2

    def test_snapshot(self, goodwill_aggregate):
        snap = goodwill_aggregate.snapshot()
        assert snap["version"] == goodwill_aggregate.version
        assert snap["goodwill_id"] == str(goodwill_aggregate.goodwill.id)
        assert snap["goodwill_number"] == "GW-001"
        assert snap["carrying_amount"] == "1000000"
        assert snap["status"] == "active"


class TestGoodwillAggregateAuditTrail:
    def test_record_audit(self, goodwill_aggregate):
        goodwill_aggregate._record_audit("TEST", "user1", {"key": "value"})
        trail = goodwill_aggregate.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TEST"
        assert trail[0]["performed_by"] == "user1"
        assert trail[0]["details"] == {"key": "value"}

    def test_audit_trail_limit(self, goodwill_aggregate):
        for i in range(150):
            goodwill_aggregate._record_audit(f"ACTION_{i}", "user", {})
        trail = goodwill_aggregate.audit_trail(limit=100)
        assert len(trail) == 100


class TestGoodwillAggregateEntityBasicMethods:
    def test_create(self, goodwill_aggregate):
        result = goodwill_aggregate.create(created_by="admin")
        assert result is goodwill_aggregate
        trail = result.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "CREATE"
        assert trail[0]["performed_by"] == "admin"

    def test_update(self, goodwill_aggregate):
        # Update description and amount
        agg = goodwill_aggregate.update(
            updated_by="admin",
            description="Updated description",
            amount="1500000",
        )
        assert agg.goodwill.description == "Updated description"
        assert agg.goodwill.amount == Decimal("1500000")
        assert agg.goodwill.version == 2
        trail = agg.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "UPDATE"
        assert trail[0]["details"]["changes"] == {"description": "Updated description", "amount": "1500000"}

    def test_update_ignores_id_created(self, goodwill_aggregate):
        original_id = goodwill_aggregate.goodwill.id
        original_created = goodwill_aggregate.goodwill.created_at
        agg = goodwill_aggregate.update(
            updated_by="admin",
            id=str(uuid4()),
            created_at=datetime.now(UTC).isoformat(),
            description="New desc",
        )
        assert agg.goodwill.id == original_id
        assert agg.goodwill.created_at == original_created
        assert agg.goodwill.description == "New desc"

    def test_delete(self, goodwill_aggregate):
        agg = goodwill_aggregate.delete(deleted_by="admin", reason="Disposed")
        assert agg.goodwill.status == GoodwillStatus.DISPOSED
        assert agg.goodwill.carrying_amount == Decimal("0")
        assert agg.goodwill.impairment_loss_total == agg.goodwill.amount
        assert agg.goodwill.disposed_at == date.today()
        assert agg.goodwill.disposed_reason == "Disposed"
        assert agg.goodwill.version == 2
        trail = agg.audit_trail()
        assert trail[0]["action"] == "DELETE"

    def test_delete_already_disposed(self, goodwill_aggregate):
        agg = goodwill_aggregate.delete("admin")
        agg2 = agg.delete("admin2")
        assert agg2.goodwill.status == GoodwillStatus.DISPOSED  # unchanged

    def test_restore(self, goodwill_aggregate):
        agg = goodwill_aggregate.delete("admin")
        restored = agg.restore("admin")
        assert restored.goodwill.status == GoodwillStatus.ACTIVE
        assert restored.goodwill.carrying_amount == agg.goodwill.impairment_loss_total
        assert restored.goodwill.disposed_at is None
        assert restored.goodwill.disposed_reason is None

    def test_restore_non_disposed_raises(self, goodwill_aggregate):
        with pytest.raises(GoodwillError, match="Cannot restore non-disposed"):
            goodwill_aggregate.restore("admin")

    def test_activate(self, goodwill_aggregate):
        # Already active, should return self
        agg = goodwill_aggregate.activate("admin")
        assert agg is goodwill_aggregate
        # Now impair it, then activate should set to ACTIVE
        agg.record_impairment(Decimal("100000"), Decimal("900000"), "auditor")
        activated = agg.activate("admin")
        assert activated.goodwill.status == GoodwillStatus.ACTIVE

    def test_deactivate(self, goodwill_aggregate):
        agg = goodwill_aggregate.deactivate("admin", "Reason")
        assert agg.goodwill.status == GoodwillStatus.DISPOSED
        # If already disposed, deactivate does nothing
        agg2 = agg.deactivate("admin2")
        assert agg2.goodwill.status == GoodwillStatus.DISPOSED

    def test_lock(self, goodwill_aggregate):
        agg = goodwill_aggregate.lock("admin", "Lock reason")
        metadata = getattr(agg.goodwill, "metadata", {})
        assert metadata.get("locked_by") == "admin"
        assert metadata.get("lock_reason") == "Lock reason"
        assert agg.goodwill.version == 2
        trail = agg.audit_trail()
        assert trail[0]["action"] == "LOCK"

    def test_unlock(self, goodwill_aggregate):
        agg = goodwill_aggregate.lock("admin", "Lock")
        unlocked = agg.unlock("admin")
        metadata = getattr(unlocked.goodwill, "metadata", {})
        assert "locked_by" not in metadata
        assert "locked_at" not in metadata
        assert "lock_reason" not in metadata
        assert unlocked.goodwill.version == 3

    def test_validate(self, goodwill_aggregate):
        result = goodwill_aggregate.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_invalid(self, goodwill_aggregate):
        # Corrupt the state by setting carrying amount negative
        # We can't directly mutate frozen dataclass, but we can create a new Goodwill
        bad_goodwill = Goodwill(
            **{**goodwill_aggregate.goodwill.__dict__, "carrying_amount": Decimal("-100")}
        )
        agg = GoodwillAggregate(bad_goodwill)
        result = agg.validate()
        assert result["is_valid"] is False
        assert len(result["errors"]) > 0

    def test_touch(self, goodwill_aggregate):
        old_version = goodwill_aggregate.goodwill.version
        agg = goodwill_aggregate.touch("toucher")
        assert agg.goodwill.version == old_version + 1
        trail = agg.audit_trail()
        assert trail[0]["action"] == "TOUCH"
        assert trail[0]["performed_by"] == "toucher"


class TestGoodwillAggregateRootMethods:
    def test_add_child_allocation(self, goodwill_aggregate, allocation):
        old_count = len(goodwill_aggregate.goodwill.allocations)
        agg = goodwill_aggregate.add_child(allocation, "admin")
        assert len(agg.goodwill.allocations) == old_count + 1
        assert agg.goodwill.allocations[-1] == allocation
        assert agg.goodwill.version == 2
        trail = agg.audit_trail()
        assert trail[0]["action"] == "ADD_ALLOCATION"
        assert trail[0]["details"]["cgu_code"] == "CGU-02"

    def test_add_child_exceeds_amount(self, goodwill_aggregate, allocation):
        # Total allocated = 300k, goodwill amount 1M, okay
        # Add another 800k, total 1.1M > 1M -> error
        alloc2 = GoodwillAllocation(
            cgu_code="CGU-03",
            cgu_name="Unit C",
            allocated_amount=Decimal("800000"),
            percentage=Decimal("80"),
        )
        agg = goodwill_aggregate.add_child(allocation, "admin")
        with pytest.raises(GoodwillError, match="Total allocated .* exceeds"):
            agg.add_child(alloc2, "admin")

    def test_remove_child(self, goodwill_aggregate, allocation):
        agg = goodwill_aggregate.add_child(allocation, "admin")
        assert len(agg.goodwill.allocations) == 1
        agg2 = agg.remove_child("CGU-02", "admin")
        assert len(agg2.goodwill.allocations) == 0
        assert agg2.goodwill.version == 3
        trail = agg2.audit_trail()
        assert trail[0]["action"] == "REMOVE_ALLOCATION"
        assert trail[0]["details"]["cgu_code"] == "CGU-02"

    def test_can_post(self, goodwill_aggregate):
        assert goodwill_aggregate.can_post() is True
        agg = goodwill_aggregate.delete("admin")
        assert agg.can_post() is False

    def test_post(self, goodwill_aggregate):
        agg = goodwill_aggregate.post("admin")
        trail = agg.audit_trail()
        assert trail[0]["action"] == "POST"

    def test_can_approve(self, goodwill_aggregate):
        assert goodwill_aggregate.can_approve("finance_manager") is True
        assert goodwill_aggregate.can_approve("user") is False

    def test_approve(self, goodwill_aggregate):
        agg = goodwill_aggregate.approve("admin")
        trail = agg.audit_trail()
        assert trail[0]["action"] == "APPROVE"

    def test_can_reject(self, goodwill_aggregate):
        assert goodwill_aggregate.can_reject("user") is True

    def test_reject(self, goodwill_aggregate):
        agg = goodwill_aggregate.reject("admin", "Reason")
        trail = agg.audit_trail()
        assert trail[0]["action"] == "REJECT"
        assert trail[0]["details"]["reason"] == "Reason"

    def test_can_cancel(self, goodwill_aggregate):
        assert goodwill_aggregate.can_cancel() is True
        agg = goodwill_aggregate.delete("admin")
        assert agg.can_cancel() is False

    def test_cancel(self, goodwill_aggregate):
        agg = goodwill_aggregate.cancel("admin", "Cancelled")
        assert agg.goodwill.status == GoodwillStatus.DISPOSED
        trail = agg.audit_trail()
        assert trail[0]["action"] == "DELETE"

    def test_can_reverse(self, goodwill_aggregate):
        assert goodwill_aggregate.can_reverse() is False
        agg = goodwill_aggregate.record_impairment(Decimal("200000"), Decimal("800000"), "auditor")
        assert agg.can_reverse() is True
        agg2 = agg.record_impairment(Decimal("800000"), Decimal("0"), "auditor")
        assert agg2.can_reverse() is True  # IMPAIRED status

    def test_reverse(self, goodwill_aggregate):
        agg = goodwill_aggregate.record_impairment(Decimal("200000"), Decimal("800000"), "auditor")
        agg2 = agg.reverse("admin", "Reversal reason")
        assert agg2.goodwill.status == GoodwillStatus.ACTIVE
        assert agg2.goodwill.carrying_amount == agg2.goodwill.amount
        assert agg2.goodwill.impairment_loss_total == Decimal("0")
        assert agg2.goodwill.last_reversal_date == date.today()
        assert agg2.goodwill.last_reversal_amount == Decimal("200000")
        trail = agg2.audit_trail()
        assert trail[0]["action"] == "REVERSE_IMPAIRMENT"

    def test_reverse_when_not_reversible(self, goodwill_aggregate):
        with pytest.raises(GoodwillError, match="Cannot reverse impairment for goodwill in status active"):
            goodwill_aggregate.reverse("admin", "Reason")

    def test_can_close(self, goodwill_aggregate):
        assert goodwill_aggregate.can_close() is False
        agg = goodwill_aggregate.delete("admin")
        assert agg.can_close() is True

    def test_close(self, goodwill_aggregate):
        agg = goodwill_aggregate.delete("admin")
        agg2 = agg.close("admin", "Closing")
        trail = agg2.audit_trail()
        assert trail[0]["action"] == "CLOSE"
        assert trail[0]["details"]["reason"] == "Closing"

    def test_can_reopen(self, goodwill_aggregate):
        assert goodwill_aggregate.can_reopen() is False
        agg = goodwill_aggregate.delete("admin")
        assert agg.can_reopen() is True

    def test_reopen(self, goodwill_aggregate):
        agg = goodwill_aggregate.delete("admin")
        agg2 = agg.reopen("admin", "Reopen")
        assert agg2.goodwill.status == GoodwillStatus.ACTIVE
        assert agg2.goodwill.disposed_at is None
        assert agg2.goodwill.disposed_reason is None
        trail = agg2.audit_trail()
        assert trail[0]["action"] == "REOPEN"

    def test_can_archive(self, goodwill_aggregate):
        assert goodwill_aggregate.can_archive() is False
        agg = goodwill_aggregate.delete("admin")
        assert agg.can_archive() is True

    def test_archive(self, goodwill_aggregate):
        agg = goodwill_aggregate.delete("admin")
        agg2 = agg.archive("admin", "Archiving")
        trail = agg2.audit_trail()
        assert trail[0]["action"] == "ARCHIVE"

    def test_can_unarchive(self, goodwill_aggregate):
        assert goodwill_aggregate.can_unarchive() is True

    def test_unarchive(self, goodwill_aggregate):
        agg = goodwill_aggregate.unarchive("admin")
        trail = agg.audit_trail()
        assert trail[0]["action"] == "UNARCHIVE"


class TestGoodwillAggregateBusinessMethods:
    def test_create_goodwill(self, legal_entity_id):
        agg = GoodwillAggregate.create_goodwill(
            legal_entity_id=legal_entity_id,
            goodwill_number="GW-NEW",
            amount=Decimal("1500000"),
            acquisition_date=date(2024, 1, 1),
            cgu_code="CGU-99",
            cgu_name="Unit 99",
            description="New goodwill",
            created_by="admin",
        )
        assert agg.goodwill.goodwill_number == "GW-NEW"
        assert agg.goodwill.amount == Decimal("1500000")
        assert agg.goodwill.status == GoodwillStatus.ACTIVE
        events = agg.get_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "GoodwillRecognized"

    def test_allocate_to_cgu(self, goodwill_aggregate):
        agg = goodwill_aggregate.allocate_to_cgu(
            cgu_code="CGU-05",
            cgu_name="Unit 5",
            amount=Decimal("200000"),
            percentage=Decimal("20"),
        )
        assert len(agg.goodwill.allocations) == 1
        assert agg.goodwill.allocations[0].cgu_code == "CGU-05"
        assert agg.goodwill.allocations[0].allocated_amount == Decimal("200000")
        trail = agg.audit_trail()
        assert trail[0]["action"] == "ADD_ALLOCATION"

    def test_record_impairment(self, goodwill_aggregate):
        agg = goodwill_aggregate.record_impairment(
            impairment_amount=Decimal("200000"),
            recoverable_amount=Decimal("800000"),
            tested_by="auditor",
            notes="Testing impairment",
        )
        assert agg.goodwill.carrying_amount == Decimal("800000")
        assert agg.goodwill.impairment_loss_total == Decimal("200000")
        assert agg.goodwill.status == GoodwillStatus.PARTIALLY_IMPAIRED
        assert agg.goodwill.last_impairment_date == date.today()
        assert agg.goodwill.last_impairment_amount == Decimal("200000")
        assert len(agg.goodwill.impairment_history) == 1
        events = agg.get_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "GoodwillImpaired"
        trail = agg.audit_trail()
        assert trail[0]["action"] == "RECORD_IMPAIRMENT"

    def test_record_impairment_invalid_amount(self, goodwill_aggregate):
        with pytest.raises(InvalidImpairmentAmountError, match="positive"):
            goodwill_aggregate.record_impairment(
                impairment_amount=Decimal("-100"),
                recoverable_amount=Decimal("900000"),
                tested_by="auditor",
            )
        with pytest.raises(InvalidImpairmentAmountError, match="exceeds carrying amount"):
            goodwill_aggregate.record_impairment(
                impairment_amount=Decimal("2000000"),
                recoverable_amount=Decimal("0"),
                tested_by="auditor",
            )

    def test_record_impairment_full(self, goodwill_aggregate):
        agg = goodwill_aggregate.record_impairment(
            impairment_amount=Decimal("1000000"),
            recoverable_amount=Decimal("0"),
            tested_by="auditor",
        )
        assert agg.goodwill.carrying_amount == Decimal("0")
        assert agg.goodwill.impairment_loss_total == Decimal("1000000")
        assert agg.goodwill.status == GoodwillStatus.FULLY_AMORTIZED

    def test_reverse_impairment(self, goodwill_aggregate):
        agg = goodwill_aggregate.record_impairment(
            impairment_amount=Decimal("300000"),
            recoverable_amount=Decimal("700000"),
            tested_by="auditor",
        )
        agg2 = agg.reverse_impairment(reversed_by="admin", reason="Recovery")
        assert agg2.goodwill.status == GoodwillStatus.ACTIVE
        assert agg2.goodwill.carrying_amount == agg2.goodwill.amount
        assert agg2.goodwill.impairment_loss_total == Decimal("0")
        assert agg2.goodwill.last_reversal_date == date.today()
        assert agg2.goodwill.last_reversal_amount == Decimal("300000")
        events = agg2.get_events()
        assert len(events) == 2  # impairment + reversal
        assert events[1]["event_type"] == "GoodwillImpairmentReversed"

    def test_amortize(self, goodwill_aggregate):
        agg = goodwill_aggregate.amortize(
            amortization_amount=Decimal("100000"),
            period="2024-Q1",
            amortized_by="accountant",
        )
        assert agg.goodwill.carrying_amount == Decimal("900000")
        assert agg.goodwill.accumulated_amortization == Decimal("100000")
        assert agg.goodwill.last_amortization_date == date.today()
        events = agg.get_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "GoodwillAmortized"
        trail = agg.audit_trail()
        assert trail[0]["action"] == "AMORTIZE"

    def test_amortize_invalid(self, goodwill_aggregate):
        with pytest.raises(GoodwillError, match="positive"):
            goodwill_aggregate.amortize(Decimal("-100"), "period", "user")
        with pytest.raises(GoodwillError, match="exceeds carrying amount"):
            goodwill_aggregate.amortize(Decimal("2000000"), "period", "user")

    def test_amortize_full(self, goodwill_aggregate):
        agg = goodwill_aggregate.amortize(
            amortization_amount=Decimal("1000000"),
            period="2024",
            amortized_by="accountant",
        )
        assert agg.goodwill.carrying_amount == Decimal("0")
        assert agg.goodwill.status == GoodwillStatus.FULLY_AMORTIZED

    def test_get_impairment_history(self, goodwill_aggregate):
        agg = goodwill_aggregate.record_impairment(
            impairment_amount=Decimal("200000"),
            recoverable_amount=Decimal("800000"),
            tested_by="auditor",
        )
        history = agg.get_impairment_history()
        assert len(history) == 1
        assert history[0].impairment_amount == Decimal("200000")

    def test_get_summary(self, goodwill_aggregate):
        summary = goodwill_aggregate.get_summary()
        assert summary["goodwill_id"] == str(goodwill_aggregate.goodwill.id)
        assert summary["goodwill_number"] == "GW-001"
        assert summary["original_amount"] == "1000000"
        assert summary["carrying_amount"] == "1000000"
        assert summary["status"] == "active"
        assert summary["impairment_percentage"] == 0.0
        assert summary["is_fully_impaired"] is False


# ============================================================================
# Tests for GoodwillRepository
# ============================================================================

class TestGoodwillRepository:
    async def test_save_and_get_by_id(self, goodwill_aggregate):
        await GoodwillRepository.save(goodwill_aggregate)
        retrieved = await GoodwillRepository.get_by_id(goodwill_aggregate.goodwill.id)
        assert retrieved is not None
        assert retrieved.goodwill.id == goodwill_aggregate.goodwill.id

    async def test_get_by_number(self, goodwill_aggregate):
        await GoodwillRepository.save(goodwill_aggregate)
        retrieved = await GoodwillRepository.get_by_number("GW-001")
        assert retrieved is not None
        assert retrieved.goodwill.id == goodwill_aggregate.goodwill.id

    async def test_get_by_legal_entity(self, goodwill_aggregate, legal_entity_id):
        await GoodwillRepository.save(goodwill_aggregate)
        items = await GoodwillRepository.get_by_legal_entity(legal_entity_id)
        assert len(items) == 1
        assert items[0].goodwill.id == goodwill_aggregate.goodwill.id

        # Another legal entity
        other = GoodwillAggregate.create_goodwill(
            legal_entity_id=uuid4(),
            goodwill_number="GW-002",
            amount=Decimal("500000"),
            acquisition_date=date(2024, 1, 1),
            cgu_code="CGU",
            cgu_name="Unit",
        )
        await GoodwillRepository.save(other)
        items2 = await GoodwillRepository.get_by_legal_entity(legal_entity_id)
        assert len(items2) == 1

    async def test_get_by_status(self, goodwill_aggregate):
        await GoodwillRepository.save(goodwill_aggregate)
        active = await GoodwillRepository.get_by_status(GoodwillStatus.ACTIVE)
        assert len(active) == 1

        # Impair it
        agg = goodwill_aggregate.record_impairment(
            impairment_amount=Decimal("200000"),
            recoverable_amount=Decimal("800000"),
            tested_by="auditor",
        )
        await GoodwillRepository.save(agg)
        active2 = await GoodwillRepository.get_by_status(GoodwillStatus.ACTIVE)
        assert len(active2) == 0
        impaired = await GoodwillRepository.get_by_status(GoodwillStatus.PARTIALLY_IMPAIRED)
        assert len(impaired) == 1

    async def test_get_all(self, goodwill_aggregate):
        await GoodwillRepository.save(goodwill_aggregate)
        all_items = await GoodwillRepository.get_all()
        assert len(all_items) == 1

    async def test_delete(self, goodwill_aggregate):
        await GoodwillRepository.save(goodwill_aggregate)
        await GoodwillRepository.delete(goodwill_aggregate.goodwill.id)
        retrieved = await GoodwillRepository.get_by_id(goodwill_aggregate.goodwill.id)
        assert retrieved is None

    async def test_exists(self, goodwill_aggregate):
        await GoodwillRepository.save(goodwill_aggregate)
        assert await GoodwillRepository.exists(goodwill_aggregate.goodwill.id) is True
        assert await GoodwillRepository.exists(uuid4()) is False

    async def test_count(self, goodwill_aggregate):
        assert await GoodwillRepository.count() == 0
        await GoodwillRepository.save(goodwill_aggregate)
        assert await GoodwillRepository.count() == 1

    async def test_list(self, goodwill_aggregate):
        await GoodwillRepository.save(goodwill_aggregate)
        # Add another
        agg2 = GoodwillAggregate.create_goodwill(
            legal_entity_id=uuid4(),
            goodwill_number="GW-002",
            amount=Decimal("500000"),
            acquisition_date=date(2024, 1, 1),
            cgu_code="CGU",
            cgu_name="Unit",
        )
        await GoodwillRepository.save(agg2)
        items = await GoodwillRepository.list(limit=1, offset=1)
        assert len(items) == 1
        # Order is not guaranteed, but we can check count
        items_all = await GoodwillRepository.list(limit=10, offset=0)
        assert len(items_all) == 2

    async def test_clear(self, goodwill_aggregate):
        await GoodwillRepository.save(goodwill_aggregate)
        assert await GoodwillRepository.count() == 1
        await GoodwillRepository.clear()
        assert await GoodwillRepository.count() == 0


# ============================================================================
# Additional property tests for GoodwillAggregate
# ============================================================================

def test_goodwill_property(goodwill_aggregate):
    assert goodwill_aggregate.goodwill == goodwill_aggregate._goodwill


def test_domain_events_property(goodwill_aggregate):
    goodwill_aggregate.register_event({"test": "event"})
    assert len(goodwill_aggregate.domain_events) == 1


def test_pop_events_alias(goodwill_aggregate):
    goodwill_aggregate.register_event({"event": "1"})
    events = goodwill_aggregate.pop_events()
    assert len(events) == 1
    assert len(goodwill_aggregate._events) == 0


# ============================================================================
# Edge cases: duplicate goodwill number (repository level)
# ============================================================================

async def test_duplicate_goodwill_number_handling(goodwill_aggregate):
    await GoodwillRepository.save(goodwill_aggregate)
    # Try to save another with same number - repository doesn't enforce, but domain might.
    # The repository save doesn't check duplicates. We'll rely on the domain's validation for uniqueness elsewhere.
    # This test just verifies that saving doesn't raise from repository side.
    dup = GoodwillAggregate.create_goodwill(
        legal_entity_id=uuid4(),
        goodwill_number="GW-001",  # duplicate
        amount=Decimal("100000"),
        acquisition_date=date(2024, 1, 1),
        cgu_code="CGU",
        cgu_name="Unit",
    )
    await GoodwillRepository.save(dup)  # Should not raise
    # Repository allows duplicates; validation should be done at service/application layer.
    assert await GoodwillRepository.count() == 2