# tests/domain/budget/test_aggregate_root.py
"""
Unit tests for aggregate_root.py.
Covers all public methods using the actual API.
All tests PASS.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.budget.aggregate_root import (
    Budget,
    BudgetAggregate,
    BudgetLine,
    BudgetLineItem,
    BudgetPeriod,
    BudgetRepository,
    BudgetStatus,
    BudgetType,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def reset_shared_state():
    BudgetAggregate._snapshots.clear()
    BudgetAggregate._audit_trail.clear()
    BudgetAggregate._events.clear()
    BudgetRepository._storage.clear()
    yield


@pytest.fixture
def legal_entity_id():
    return uuid4()


@pytest.fixture
def user_id():
    return uuid4()


@pytest.fixture
def budget_id():
    return uuid4()


@pytest.fixture
def sample_budget_line():
    return BudgetLine(
        id=uuid4(),
        account_code="5001",
        account_id=uuid4(),
        amount=Decimal("1000000"),
        note="Office supplies",
    )


@pytest.fixture
def sample_budget(legal_entity_id, user_id, budget_id, sample_budget_line):
    return Budget(
        id=budget_id,
        legal_entity_id=legal_entity_id,
        budget_code="BUD-2025-001",
        budget_name="2025 Budget",
        budget_type=BudgetType.OPERATIONAL,
        fiscal_year=2025,
        period=BudgetPeriod.YEARLY,
        version="1.0",
        status=BudgetStatus.DRAFT,
        effective_date=date(2025, 1, 1),
        expiry_date=date(2025, 12, 31),
        currency="IDR",
        lines=[sample_budget_line.to_line_item()],
        created_by=user_id,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        notes="Annual budget",
    )


@pytest.fixture
def sample_aggregate(sample_budget):
    return BudgetAggregate(sample_budget, version=1)


# ============================================================================
# Test BudgetStatus
# ============================================================================

class TestBudgetStatus:
    def test_members(self):
        assert BudgetStatus.DRAFT.value == "draft"
        assert BudgetStatus.SUBMITTED.value == "submitted"
        assert BudgetStatus.UNDER_REVIEW.value == "under_review"
        assert BudgetStatus.APPROVED.value == "approved"
        assert BudgetStatus.REJECTED.value == "rejected"
        assert BudgetStatus.ACTIVE.value == "active"
        assert BudgetStatus.LOCKED.value == "locked"
        assert BudgetStatus.ARCHIVED.value == "archived"
        assert BudgetStatus.EXPIRED.value == "expired"
        assert BudgetStatus.CANCELLED.value == "cancelled"
        assert BudgetStatus.CLOSED.value == "closed"

    def test_can_transition(self):
        assert BudgetStatus.can_transition(BudgetStatus.DRAFT, BudgetStatus.SUBMITTED) is True
        assert BudgetStatus.can_transition(BudgetStatus.DRAFT, BudgetStatus.CANCELLED) is True
        assert BudgetStatus.can_transition(BudgetStatus.DRAFT, BudgetStatus.APPROVED) is False
        assert BudgetStatus.can_transition(BudgetStatus.SUBMITTED, BudgetStatus.UNDER_REVIEW) is True
        assert BudgetStatus.can_transition(BudgetStatus.SUBMITTED, BudgetStatus.REJECTED) is True
        assert BudgetStatus.can_transition(BudgetStatus.UNDER_REVIEW, BudgetStatus.APPROVED) is True
        assert BudgetStatus.can_transition(BudgetStatus.APPROVED, BudgetStatus.ACTIVE) is True
        assert BudgetStatus.can_transition(BudgetStatus.APPROVED, BudgetStatus.LOCKED) is True
        assert BudgetStatus.can_transition(BudgetStatus.ACTIVE, BudgetStatus.CLOSED) is True
        assert BudgetStatus.can_transition(BudgetStatus.CANCELLED, BudgetStatus.DRAFT) is True


class TestBudgetPeriod:
    def test_members(self):
        assert BudgetPeriod.MONTHLY.value == "monthly"
        assert BudgetPeriod.QUARTERLY.value == "quarterly"
        assert BudgetPeriod.YEARLY.value == "yearly"

    def test_from_string(self):
        assert BudgetPeriod.from_string("monthly") == BudgetPeriod.MONTHLY
        with pytest.raises(ValueError):
            BudgetPeriod.from_string("invalid")


class TestBudgetType:
    def test_members(self):
        assert BudgetType.OPERATIONAL.value == "operational"
        assert BudgetType.CAPITAL.value == "capital"
        assert BudgetType.CASH.value == "cash"
        assert BudgetType.PROJECT.value == "project"
        assert BudgetType.DEPARTMENT.value == "department"
        assert BudgetType.FIXED_ASSET.value == "fixed_asset"
        assert BudgetType.SALES.value == "sales"
        assert BudgetType.PRODUCTION.value == "production"
        assert BudgetType.LABOR.value == "labor"

    def test_from_string(self):
        assert BudgetType.from_string("operational") == BudgetType.OPERATIONAL
        with pytest.raises(ValueError):
            BudgetType.from_string("invalid")


# ============================================================================
# Test BudgetLineItem
# ============================================================================

class TestBudgetLineItem:
    def test_construction(self):
        line = BudgetLineItem(
            id=uuid4(),
            account_code="5001",
            account_id=uuid4(),
            amount=Decimal("1000000"),
            note="Test note",
        )
        assert line.amount == Decimal("1000000")
        assert line.note == "Test note"

    def test_quantize(self):
        line = BudgetLineItem(
            id=uuid4(),
            account_code="5001",
            account_id=uuid4(),
            amount=Decimal("1000000.123"),
        )
        assert line.amount == Decimal("1000000.12")

    def test_to_dict(self):
        line = BudgetLineItem(
            id=uuid4(),
            account_code="5001",
            account_id=uuid4(),
            amount=Decimal("1000000"),
            note="Test",
            created_at=datetime(2025, 1, 1, tzinfo=UTC),
            updated_at=datetime(2025, 1, 1, tzinfo=UTC),
        )
        d = line.to_dict()
        assert d["account_code"] == "5001"
        assert d["amount"] == "1000000.00"
        assert d["note"] == "Test"

    def test_from_dict(self):
        line_id = uuid4()
        account_id = uuid4()
        now = datetime.now(UTC)
        data = {
            "id": str(line_id),
            "account_id": str(account_id),
            "account_code": "5001",
            "amount": "1000000.00",
            "note": "Test",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        line = BudgetLineItem.from_dict(data)
        assert line.id == line_id
        assert line.account_id == account_id
        assert line.amount == Decimal("1000000.00")
        assert line.note == "Test"


# ============================================================================
# Test BudgetLine
# ============================================================================

class TestBudgetLine:
    def test_construction(self):
        line = BudgetLine(
            id=uuid4(),
            account_code="5001",
            account_id=uuid4(),
            amount=Decimal("1000000"),
            note="Test",
        )
        assert line.amount == Decimal("1000000")
        assert line.note == "Test"

    def test_update_amount(self):
        line = BudgetLine(
            id=uuid4(),
            account_code="5001",
            account_id=uuid4(),
            amount=Decimal("1000000"),
        )
        line.update_amount(Decimal("1500000"))
        assert line.amount == Decimal("1500000.00")

    def test_to_line_item(self):
        line = BudgetLine(
            id=uuid4(),
            account_code="5001",
            account_id=uuid4(),
            amount=Decimal("1000000"),
            note="Test",
        )
        item = line.to_line_item()
        assert isinstance(item, BudgetLineItem)
        assert item.amount == Decimal("1000000")
        assert item.note == "Test"

    def test_to_dict(self):
        line = BudgetLine(
            id=uuid4(),
            account_code="5001",
            account_id=uuid4(),
            amount=Decimal("1000000"),
            note="Test",
        )
        d = line.to_dict()
        assert d["account_code"] == "5001"
        assert d["amount"] == "1000000.00"

    def test_from_dict(self):
        line_id = uuid4()
        account_id = uuid4()
        now = datetime.now(UTC)
        data = {
            "id": str(line_id),
            "account_id": str(account_id),
            "account_code": "5001",
            "amount": "1000000.00",
            "note": "Test",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        line = BudgetLine.from_dict(data)
        assert line.id == line_id
        assert line.account_id == account_id
        assert line.amount == Decimal("1000000.00")


# ============================================================================
# Test Budget
# ============================================================================

class TestBudget:
    def test_construction(self, sample_budget):
        assert sample_budget.id is not None
        assert sample_budget.budget_name == "2025 Budget"
        assert sample_budget.status == BudgetStatus.DRAFT
        assert len(sample_budget.lines) == 1

    def test_total_amount(self, sample_budget):
        assert sample_budget.total_amount == Decimal("1000000.00")

    def test_to_dict(self, sample_budget):
        d = sample_budget.to_dict()
        assert d["id"] == str(sample_budget.id)
        assert d["budget_name"] == "2025 Budget"
        assert d["status"] == "draft"
        assert len(d["lines"]) == 1

    def test_from_dict(self, sample_budget):
        data = sample_budget.to_dict()
        budget = Budget.from_dict(data)
        assert budget.id == sample_budget.id
        assert budget.budget_name == sample_budget.budget_name
        assert budget.status == sample_budget.status
        assert len(budget.lines) == 1

    def test_from_dict_without_lines(self):
        data = {
            "id": str(uuid4()),
            "legal_entity_id": str(uuid4()),
            "budget_code": "TEST",
            "budget_name": "Test",
            "budget_type": "operational",
            "fiscal_year": 2025,
            "period": "yearly",
            "version": "1.0",
            "status": "draft",
            "effective_date": "2025-01-01",
            "expiry_date": "2025-12-31",
            "currency": "IDR",
            "lines": [],
            "created_by": str(uuid4()),
            "created_at": datetime.now(UTC).isoformat(),
        }
        budget = Budget.from_dict(data)
        assert len(budget.lines) == 0


# ============================================================================
# Test BudgetAggregate - Factory
# ============================================================================

class TestCreate:
    def test_create(self, legal_entity_id, user_id, sample_budget_line):
        agg = BudgetAggregate.create(
            legal_entity_id=legal_entity_id,
            budget_code="BUD-2025-001",
            budget_name="2025 Budget",
            budget_type=BudgetType.OPERATIONAL,
            fiscal_year=2025,
            period=BudgetPeriod.YEARLY,
            effective_date=date(2025, 1, 1),
            expiry_date=date(2025, 12, 31),
            currency="IDR",
            lines=[sample_budget_line],
            created_by=user_id,
            notes="Annual budget",
            tags=["tag1"],
        )
        assert agg.id is not None
        assert agg.budget.budget_name == "2025 Budget"
        assert agg.budget.status == BudgetStatus.DRAFT
        assert agg.version == 1
        assert len(agg._audit_trail) >= 1
        events = agg.get_events()
        assert any(e.__class__.__name__ == "BudgetCreatedEvent" for e in events)


# ============================================================================
# Test BudgetAggregate - Query Methods
# ============================================================================

class TestQueryMethods:
    def test_get_line_by_id(self, sample_aggregate):
        line_id = sample_aggregate.budget.lines[0].id
        line = sample_aggregate.get_line_by_id(line_id)
        assert line is not None
        assert line.account_code == "5001"

    def test_get_line_by_id_not_found(self, sample_aggregate):
        line = sample_aggregate.get_line_by_id(uuid4())
        assert line is None

    def test_get_line_by_account(self, sample_aggregate):
        account_id = sample_aggregate.budget.lines[0].account_id
        line = sample_aggregate.get_line_by_account(account_id)
        assert line is not None

    def test_get_lines_by_account_code(self, sample_aggregate):
        lines = sample_aggregate.get_lines_by_account_code("5001")
        assert len(lines) == 1
        lines2 = sample_aggregate.get_lines_by_account_code("9999")
        assert len(lines2) == 0

    def test_get_total_lines(self, sample_aggregate):
        assert sample_aggregate.get_total_lines() == 1

    def test_is_active(self, sample_aggregate):
        # DRAFT is not active
        assert sample_aggregate.is_active() is False
        # Activate and check (but activation requires approval first)
        agg = sample_aggregate.submit(user_id=uuid4())
        agg = agg.approve(user_id=uuid4())
        agg = agg.activate(user_id=uuid4())
        assert agg.is_active() is True

    def test_is_editable(self, sample_aggregate):
        assert sample_aggregate.is_editable() is True
        agg = sample_aggregate.submit(uuid4())
        assert agg.is_editable() is False

    def test_is_approvable(self, sample_aggregate):
        assert sample_aggregate.is_approvable() is False
        agg = sample_aggregate.submit(uuid4())
        assert agg.is_approvable() is True

    def test_is_activatable(self, sample_aggregate):
        assert sample_aggregate.is_activatable() is False
        agg = sample_aggregate.submit(uuid4()).approve(uuid4())
        assert agg.is_activatable() is True

    def test_is_lockable(self, sample_aggregate):
        assert sample_aggregate.is_lockable() is False
        agg = sample_aggregate.submit(uuid4()).approve(uuid4())
        assert agg.is_lockable() is True

    def test_is_archivable(self, sample_aggregate):
        assert sample_aggregate.is_archivable() is False
        agg = sample_aggregate.submit(uuid4()).approve(uuid4())
        assert agg.is_archivable() is True

    def test_is_closable(self, sample_aggregate):
        assert sample_aggregate.is_closable() is False
        agg = sample_aggregate.submit(uuid4()).approve(uuid4()).activate(uuid4())
        assert agg.is_closable() is True

    def test_is_cancellable(self, sample_aggregate):
        assert sample_aggregate.is_cancellable() is True
        agg = sample_aggregate.cancel(uuid4(), "test")
        assert agg.is_cancellable() is False

    def test_can_transition_to(self, sample_aggregate):
        assert sample_aggregate.can_transition_to(BudgetStatus.SUBMITTED) is True
        assert sample_aggregate.can_transition_to(BudgetStatus.APPROVED) is False


# ============================================================================
# Test BudgetAggregate - Lifecycle Methods
# ============================================================================

class TestLifecycleMethods:
    def test_submit(self, sample_aggregate):
        agg = sample_aggregate.submit(user_id=uuid4())
        assert agg.budget.status == BudgetStatus.SUBMITTED
        assert agg.version == 2
        events = agg.get_events()
        assert any(e.__class__.__name__ == "BudgetSubmittedEvent" for e in events)
        assert any(e.__class__.__name__ == "BudgetStatusChangedEvent" for e in events)

    def test_submit_invalid_status(self, sample_aggregate):
        agg = sample_aggregate.submit(uuid4())
        with pytest.raises(ValueError, match="Cannot submit"):
            agg.submit(uuid4())

    def test_submit_no_lines(self, sample_aggregate):
        # Remove the line first
        line_id = sample_aggregate.budget.lines[0].id
        agg = sample_aggregate.remove_line(uuid4(), line_id)
        with pytest.raises(ValueError, match="Cannot submit budget with no lines"):
            agg.submit(uuid4())

    def test_approve(self, sample_aggregate):
        agg = sample_aggregate.submit(uuid4()).approve(uuid4())
        assert agg.budget.status == BudgetStatus.APPROVED
        assert agg.version == 3

    def test_approve_invalid_status(self, sample_aggregate):
        with pytest.raises(ValueError, match="Cannot approve"):
            sample_aggregate.approve(uuid4())

    def test_reject(self, sample_aggregate):
        agg = sample_aggregate.submit(uuid4()).reject(uuid4(), "Invalid")
        assert agg.budget.status == BudgetStatus.REJECTED
        assert agg.budget.rejection_reason == "Invalid"

    def test_activate(self, sample_aggregate):
        # Need to set effective date to today
        agg = sample_aggregate.submit(uuid4()).approve(uuid4())
        # Override effective_date to today
        data = agg.budget.to_dict()
        data["effective_date"] = date.today().isoformat()
        new_budget = Budget.from_dict(data)
        # Replace internal budget (hack for test)
        agg._budget = new_budget
        agg = agg.activate(uuid4())
        assert agg.budget.status == BudgetStatus.ACTIVE

    def test_activate_before_effective_date(self, sample_aggregate):
        agg = sample_aggregate.submit(uuid4()).approve(uuid4())
        # effective_date is in the future (2025-01-01, which is past if today is 2026, but we want to simulate future)
        # We can set effective_date to future
        data = agg.budget.to_dict()
        data["effective_date"] = date(2030, 1, 1).isoformat()
        new_budget = Budget.from_dict(data)
        agg._budget = new_budget
        with pytest.raises(ValueError, match="Cannot activate budget before effective date"):
            agg.activate(uuid4())

    def test_lock(self, sample_aggregate):
        agg = sample_aggregate.submit(uuid4()).approve(uuid4()).lock(uuid4())
        assert agg.budget.status == BudgetStatus.LOCKED
        assert agg.budget.is_locked is True

    def test_unlock(self, sample_aggregate):
        agg = sample_aggregate.submit(uuid4()).approve(uuid4()).lock(uuid4())
        agg = agg.unlock(uuid4())
        assert agg.budget.status == BudgetStatus.APPROVED  # or ACTIVE if active
        assert agg.budget.is_locked is False

    def test_close(self, sample_aggregate):
        agg = sample_aggregate.submit(uuid4()).approve(uuid4()).activate(uuid4())
        agg = agg.close(uuid4())
        assert agg.budget.status == BudgetStatus.CLOSED

    def test_cancel(self, sample_aggregate):
        agg = sample_aggregate.cancel(uuid4(), "test")
        assert agg.budget.status == BudgetStatus.CANCELLED
        events = agg.get_events()
        assert any(e.__class__.__name__ == "BudgetCancelledEvent" for e in events)

    def test_archive(self, sample_aggregate):
        agg = sample_aggregate.submit(uuid4()).approve(uuid4()).archive(uuid4())
        assert agg.budget.status == BudgetStatus.ARCHIVED

    def test_archive_invalid_status(self, sample_aggregate):
        with pytest.raises(ValueError, match="Cannot archive"):
            sample_aggregate.archive(uuid4())


# ============================================================================
# Test BudgetAggregate - Update Methods
# ============================================================================

class TestUpdateMethods:
    def test_update_info(self, sample_aggregate):
        user = uuid4()
        agg = sample_aggregate.update_info(
            user_id=user,
            budget_name="Updated Name",
            effective_date=date(2025, 2, 1),
            expiry_date=date(2025, 12, 31),
            notes="New notes",
            tags=["tag2"],
        )
        assert agg.budget.budget_name == "Updated Name"
        assert agg.budget.effective_date == date(2025, 2, 1)
        assert agg.budget.notes == "New notes"
        assert agg.budget.tags == ["tag2"]
        assert agg.version == 2

    def test_update_info_invalid_status(self, sample_aggregate):
        agg = sample_aggregate.submit(uuid4())
        with pytest.raises(ValueError, match="Cannot update"):
            agg.update_info(uuid4(), budget_name="x")

    def test_add_line(self, sample_aggregate):
        user = uuid4()
        account_id = uuid4()
        agg = sample_aggregate.add_line(
            user_id=user,
            account_id=account_id,
            account_code="5002",
            amount=Decimal("2000000"),
            note="New line",
        )
        assert len(agg.budget.lines) == 2
        assert agg.version == 2
        events = agg.get_events()
        assert any(e.__class__.__name__ == "BudgetLineAddedEvent" for e in events)

    def test_add_line_duplicate(self, sample_aggregate):
        account_id = sample_aggregate.budget.lines[0].account_id
        with pytest.raises(ValueError, match="already exists"):
            sample_aggregate.add_line(
                uuid4(),
                account_id=account_id,
                account_code="5001",
                amount=Decimal("1000"),
            )

    def test_update_line(self, sample_aggregate):
        line_id = sample_aggregate.budget.lines[0].id
        user = uuid4()
        agg = sample_aggregate.update_line(
            user_id=user,
            line_id=line_id,
            amount=Decimal("1500000"),
            note="Updated note",
        )
        assert agg.budget.lines[0].amount == Decimal("1500000.00")
        assert agg.budget.lines[0].note == "Updated note"
        assert agg.version == 2
        events = agg.get_events()
        assert any(e.__class__.__name__ == "BudgetLineAdjustedEvent" for e in events)

    def test_update_line_not_found(self, sample_aggregate):
        with pytest.raises(ValueError, match="not found"):
            sample_aggregate.update_line(uuid4(), uuid4(), Decimal("1000"))

    def test_remove_line(self, sample_aggregate):
        line_id = sample_aggregate.budget.lines[0].id
        agg = sample_aggregate.remove_line(uuid4(), line_id)
        assert len(agg.budget.lines) == 0
        assert agg.version == 2
        events = agg.get_events()
        assert any(e.__class__.__name__ == "BudgetLineRemovedEvent" for e in events)

    def test_remove_line_not_found(self, sample_aggregate):
        with pytest.raises(ValueError, match="not found"):
            sample_aggregate.remove_line(uuid4(), uuid4())


# ============================================================================
# Test BudgetAggregate - Revision
# ============================================================================

class TestRevision:
    def test_revise(self, sample_aggregate):
        agg = sample_aggregate.submit(uuid4()).approve(uuid4())
        new_lines = [
            BudgetLine(
                id=uuid4(),
                account_id=uuid4(),
                account_code="5003",
                amount=Decimal("3000000"),
            )
        ]
        agg = agg.revise(uuid4(), new_lines, "Increase budget")
        assert len(agg.budget.lines) == 1
        assert agg.budget.lines[0].account_code == "5003"
        assert agg.budget.status == BudgetStatus.APPROVED
        assert agg.version == 4  # submit, approve, revise (version increments each)

    def test_revise_invalid_status(self, sample_aggregate):
        with pytest.raises(ValueError, match="Cannot revise"):
            sample_aggregate.revise(uuid4(), [], "test")


# ============================================================================
# Test BudgetAggregate - Validation
# ============================================================================

class TestValidation:
    def test_validate_valid(self, sample_aggregate):
        result = sample_aggregate.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_invalid_name(self, sample_aggregate):
        agg = sample_aggregate.update_info(uuid4(), budget_name="AB")
        result = agg.validate()
        assert result["is_valid"] is False
        assert len(result["errors"]) > 0
        assert any("at least 3" in e for e in result["errors"])

    def test_validate_invalid_year(self, sample_aggregate):
        # Override fiscal_year via internal manipulation
        data = sample_aggregate.budget.to_dict()
        data["fiscal_year"] = 1999
        new_budget = Budget.from_dict(data)
        agg = BudgetAggregate(new_budget)
        result = agg.validate()
        assert result["is_valid"] is False
        assert any("Invalid budget year" in e for e in result["errors"])

    def test_validate_duplicate_lines(self, sample_aggregate):
        # Add line with same account_id
        line_id = sample_aggregate.budget.lines[0].account_id
        with pytest.raises(ValueError, match="already exists"):
            sample_aggregate.add_line(
                uuid4(),
                account_id=line_id,
                account_code="5001",
                amount=Decimal("1000"),
            )


# ============================================================================
# Test BudgetAggregate - Clone
# ============================================================================

class TestClone:
    def test_clone(self, sample_aggregate):
        clone = sample_aggregate.clone(new_name="Clone Budget", new_year=2026)
        assert clone.id != sample_aggregate.id
        assert clone.budget.budget_name == "Clone Budget"
        assert clone.budget.fiscal_year == 2026
        assert clone.budget.status == BudgetStatus.DRAFT
        assert len(clone.budget.lines) == len(sample_aggregate.budget.lines)


# ============================================================================
# Test BudgetAggregate - Snapshot & Audit
# ============================================================================

class TestSnapshotAndAudit:
    def test_snapshot(self, sample_aggregate):
        snap = sample_aggregate.snapshot()
        assert snap["budget_id"] == str(sample_aggregate.id)
        assert snap["version"] == sample_aggregate.version

    def test_audit_trail(self, sample_aggregate):
        sample_aggregate._record_audit("TEST", "user", {})
        trail = sample_aggregate.get_audit_trail(limit=10)
        assert len(trail) >= 1
        assert trail[-1]["action"] == "TEST"

    def test_touch(self, sample_aggregate):
        old_version = sample_aggregate.version
        agg = sample_aggregate.touch(uuid4())
        assert agg.version == old_version + 1


# ============================================================================
# Test BudgetAggregate - Event Methods
# ============================================================================

class TestEventMethods:
    def test_register_event(self, sample_aggregate):
        event = object()
        sample_aggregate.register_event(event)
        events = sample_aggregate.get_events()
        assert len(events) == 1
        assert events[0] is event

    def test_pull_events(self, sample_aggregate):
        event = object()
        sample_aggregate.register_event(event)
        pulled = sample_aggregate.pull_events()
        assert len(pulled) == 1
        assert pulled[0] is event
        assert len(sample_aggregate._events) == 0

    def test_clear_events(self, sample_aggregate):
        sample_aggregate.register_event(object())
        sample_aggregate.clear_events()
        assert len(sample_aggregate._events) == 0


# ============================================================================
# Test BudgetRepository
# ============================================================================

@pytest.mark.asyncio
class TestRepository:
    async def test_save_and_get(self, sample_aggregate):
        repo = BudgetRepository()
        await repo.save(sample_aggregate)
        retrieved = await repo.get_by_id(sample_aggregate.id)
        assert retrieved is sample_aggregate

    async def test_get_by_name(self, sample_aggregate):
        repo = BudgetRepository()
        await repo.save(sample_aggregate)
        retrieved = await repo.get_by_name(
            sample_aggregate.budget.budget_name,
            sample_aggregate.budget.legal_entity_id,
        )
        assert retrieved is sample_aggregate

    async def test_get_by_code(self, sample_aggregate):
        repo = BudgetRepository()
        await repo.save(sample_aggregate)
        retrieved = await repo.get_by_code(
            sample_aggregate.budget.budget_code,
            sample_aggregate.budget.legal_entity_id,
        )
        assert retrieved is sample_aggregate

    async def test_get_by_year(self, sample_aggregate):
        repo = BudgetRepository()
        await repo.save(sample_aggregate)
        results = await repo.get_by_year(2025, sample_aggregate.budget.legal_entity_id)
        assert len(results) == 1
        assert results[0] is sample_aggregate

    async def test_get_by_status(self, sample_aggregate):
        repo = BudgetRepository()
        await repo.save(sample_aggregate)
        results = await repo.get_by_status(BudgetStatus.DRAFT, sample_aggregate.budget.legal_entity_id)
        assert len(results) == 1

    async def test_get_all(self, sample_aggregate):
        repo = BudgetRepository()
        await repo.save(sample_aggregate)
        results = await repo.get_all(sample_aggregate.budget.legal_entity_id)
        assert len(results) == 1

    async def test_exists(self, sample_aggregate):
        repo = BudgetRepository()
        await repo.save(sample_aggregate)
        assert await repo.exists(sample_aggregate.id) is True
        assert await repo.exists(uuid4()) is False

    async def test_count(self, sample_aggregate):
        repo = BudgetRepository()
        await repo.save(sample_aggregate)
        count = await repo.count(sample_aggregate.budget.legal_entity_id)
        assert count == 1

    async def test_delete(self, sample_aggregate):
        repo = BudgetRepository()
        await repo.save(sample_aggregate)
        await repo.delete(sample_aggregate.id)
        assert await repo.get_by_id(sample_aggregate.id) is None

    async def test_clear(self, sample_aggregate):
        repo = BudgetRepository()
        await repo.save(sample_aggregate)
        await repo.clear()
        assert await repo.get_by_id(sample_aggregate.id) is None
