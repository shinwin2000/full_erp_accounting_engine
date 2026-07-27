# tests/domain/forex/test_aggregate_root.py
"""
Comprehensive unit tests for Forex revaluation aggregate root.

Covers:
- Value objects: JournalLine, RevaluationJournal, RevaluationResult
- Aggregate: creation, updates, status transitions (approve, reject, post, cancel, reverse, close, reopen, archive)
- Business methods: calculate_revaluation, create_adjustment_journal, get_result
- Utilities: audit trail, snapshot, clone, touch, validate
- Repository: in-memory storage with CRUD operations
- Helper function: add_audit
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from domain.forex.aggregate_root import (
    ForexRevaluationAggregate,
    ForexRevaluationError,
    ForexRevaluationRepository,
    GainLossType,
    InvalidRevaluationStatusError,
    JournalLine,
    RevaluationAlreadyPostedError,
    RevaluationJournal,
    RevaluationResult,
    RevaluationStatus,
    add_audit,
)
from domain.forex.exchange_rate_vo import ExchangeRate


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def old_rate() -> ExchangeRate:
    """Old exchange rate (e.g., 1 USD = 14,000 IDR)."""
    return ExchangeRate(
        currency="USD",
        rate=Decimal("14000.00"),
        effective_date=datetime.now(UTC) - timedelta(days=30),
    )


@pytest.fixture
def new_rate() -> ExchangeRate:
    """New exchange rate (e.g., 1 USD = 15,000 IDR) – gain scenario."""
    return ExchangeRate(
        currency="USD",
        rate=Decimal("15000.00"),
        effective_date=datetime.now(UTC),
    )


@pytest.fixture
def losing_new_rate() -> ExchangeRate:
    """New rate that causes a loss (1 USD = 13,000 IDR)."""
    return ExchangeRate(
        currency="USD",
        rate=Decimal("13000.00"),
        effective_date=datetime.now(UTC),
    )


@pytest.fixture
def legal_entity_id() -> UUID:
    return uuid4()


@pytest.fixture
def aggregate_kwargs(legal_entity_id, old_rate, new_rate) -> dict[str, Any]:
    """Base kwargs for a valid aggregate (gain scenario)."""
    return {
        "aggregate_id": uuid4(),
        "legal_entity_id": legal_entity_id,
        "currency": "USD",
        "revaluation_date": new_rate.effective_date,
        "balance_fcy": Decimal("1000.00"),
        "old_rate": old_rate,
        "new_rate": new_rate,
        "gain_loss": Decimal("1000000.00"),  # 1000 * (15000-14000)
        "gain_loss_type": GainLossType.GAIN,
        "status": RevaluationStatus.DRAFT,
        "created_by": "tester",
        "version": 1,
    }


@pytest.fixture
def aggregate(aggregate_kwargs) -> ForexRevaluationAggregate:
    """A fully initialized aggregate in DRAFT state (gain)."""
    return ForexRevaluationAggregate(**aggregate_kwargs)


@pytest.fixture
def loss_aggregate(legal_entity_id, old_rate, losing_new_rate) -> ForexRevaluationAggregate:
    """Aggregate with a loss scenario."""
    return ForexRevaluationAggregate(
        aggregate_id=uuid4(),
        legal_entity_id=legal_entity_id,
        currency="USD",
        revaluation_date=losing_new_rate.effective_date,
        balance_fcy=Decimal("1000.00"),
        old_rate=old_rate,
        new_rate=losing_new_rate,
        gain_loss=Decimal("1000000.00"),  # 1000 * (14000-13000)
        gain_loss_type=GainLossType.LOSS,
        status=RevaluationStatus.DRAFT,
        created_by="tester",
    )


@pytest.fixture
def approved_aggregate(aggregate) -> ForexRevaluationAggregate:
    """Aggregate in APPROVED state."""
    return aggregate.approve("finance_manager")


@pytest.fixture
def posted_aggregate(approved_aggregate) -> ForexRevaluationAggregate:
    """Aggregate in POSTED state (with journal)."""
    return approved_aggregate.post("tester")


# -----------------------------------------------------------------------------
# Tests for Value Objects
# -----------------------------------------------------------------------------

class TestJournalLine:
    """Test the JournalLine immutable value object."""

    def test_construction_success(self):
        """Valid debit line."""
        line = JournalLine(
            account_code="1100",
            account_name="Cash",
            debit=Decimal("100"),
            credit=Decimal("0"),
            description="Test",
        )
        assert line.account_code == "1100"
        assert line.debit == Decimal("100")
        assert line.credit == Decimal("0")
        assert line.is_debit is True
        assert line.is_credit is False
        assert line.amount == Decimal("100")

    def test_credit_line(self):
        line = JournalLine(
            account_code="4210",
            account_name="Gain",
            debit=Decimal("0"),
            credit=Decimal("50"),
        )
        assert line.is_debit is False
        assert line.is_credit is True
        assert line.amount == Decimal("50")

    def test_negative_amount_raises(self):
        with pytest.raises(ValueError, match="Debit and credit cannot be negative"):
            JournalLine("1100", "Cash", debit=Decimal("-10"), credit=Decimal("0"))

    def test_both_debit_and_credit_raises(self):
        with pytest.raises(ValueError, match="cannot have both debit and credit"):
            JournalLine("1100", "Cash", debit=Decimal("10"), credit=Decimal("5"))

    def test_zero_amount_raises(self):
        with pytest.raises(ValueError, match="must have non-zero amount"):
            JournalLine("1100", "Cash", debit=Decimal("0"), credit=Decimal("0"))

    def test_to_dict_and_from_dict(self):
        line = JournalLine("1100", "Cash", Decimal("100"), Decimal("0"), "Test")
        d = line.to_dict()
        assert d["account_code"] == "1100"
        assert d["debit"] == "100"
        assert d["credit"] == "0"
        restored = JournalLine.from_dict(d)
        assert restored == line


class TestRevaluationJournal:
    """Test the RevaluationJournal value object."""

    def test_construction_success(self, aggregate):
        lines = [
            JournalLine("1100", "Cash", Decimal("100"), Decimal("0")),
            JournalLine("4210", "Gain", Decimal("0"), Decimal("100")),
        ]
        journal = RevaluationJournal(
            journal_id=uuid4(),
            revaluation_id=aggregate.aggregate_id,
            journal_date=datetime.now(UTC),
            description="Test journal",
            lines=lines,
            created_by="tester",
        )
        assert journal.total_debit == Decimal("100")
        assert journal.total_credit == Decimal("100")
        assert journal.is_balanced is True

    def test_unbalanced_journal(self):
        lines = [
            JournalLine("1100", "Cash", Decimal("100"), Decimal("0")),
            JournalLine("4210", "Gain", Decimal("0"), Decimal("50")),
        ]
        journal = RevaluationJournal(
            journal_id=uuid4(),
            revaluation_id=uuid4(),
            journal_date=datetime.now(UTC),
            description="Unbalanced",
            lines=lines,
        )
        assert journal.is_balanced is False

    def test_to_dict_and_from_dict(self, aggregate):
        lines = [
            JournalLine("1100", "Cash", Decimal("100"), Decimal("0")),
            JournalLine("4210", "Gain", Decimal("0"), Decimal("100")),
        ]
        original = RevaluationJournal(
            journal_id=uuid4(),
            revaluation_id=aggregate.aggregate_id,
            journal_date=datetime.now(UTC),
            description="Test",
            lines=lines,
            created_by="tester",
            version=1,
        )
        d = original.to_dict()
        restored = RevaluationJournal.from_dict(d)
        assert restored.journal_id == original.journal_id
        assert restored.total_debit == original.total_debit
        assert restored.total_credit == original.total_credit
        assert len(restored.lines) == len(original.lines)


class TestRevaluationResult:
    """Test the RevaluationResult value object."""

    def test_construction(self, old_rate, new_rate):
        result = RevaluationResult(
            gain_loss=Decimal("1000000"),
            gain_loss_type=GainLossType.GAIN,
            old_rate=old_rate,
            new_rate=new_rate,
            balance_fcy=Decimal("1000"),
            balance_lcy_before=Decimal("14000000"),
            balance_lcy_after=Decimal("15000000"),
        )
        assert result.gain_loss_type == GainLossType.GAIN
        assert result.old_rate == old_rate
        assert result.new_rate == new_rate

    def test_to_dict_and_from_dict(self, old_rate, new_rate):
        original = RevaluationResult(
            gain_loss=Decimal("1000000"),
            gain_loss_type=GainLossType.GAIN,
            old_rate=old_rate,
            new_rate=new_rate,
            balance_fcy=Decimal("1000"),
            balance_lcy_before=Decimal("14000000"),
            balance_lcy_after=Decimal("15000000"),
        )
        d = original.to_dict()
        restored = RevaluationResult.from_dict(d)
        assert restored.gain_loss == original.gain_loss
        assert restored.gain_loss_type == original.gain_loss_type
        assert restored.old_rate.rate == original.old_rate.rate


# -----------------------------------------------------------------------------
# Tests for ForexRevaluationAggregate
# -----------------------------------------------------------------------------

class TestForexRevaluationAggregate:
    """Test the aggregate root."""

    def test_construction_success(self, aggregate):
        assert aggregate.aggregate_id is not None
        assert aggregate.legal_entity_id is not None
        assert aggregate.currency == "USD"
        assert aggregate.status == RevaluationStatus.DRAFT
        assert aggregate.version == 1
        assert aggregate.gain_loss_type == GainLossType.GAIN

    def test_validation_raises_for_negative_balance(self, aggregate_kwargs):
        aggregate_kwargs["balance_fcy"] = Decimal("-100")
        with pytest.raises(ForexRevaluationError, match="Balance cannot be negative"):
            ForexRevaluationAggregate(**aggregate_kwargs)

    def test_validation_raises_for_currency_mismatch(self, aggregate_kwargs):
        aggregate_kwargs["old_rate"] = ExchangeRate("EUR", Decimal("1"), datetime.now(UTC))
        with pytest.raises(ForexRevaluationError, match="Currency mismatch"):
            ForexRevaluationAggregate(**aggregate_kwargs)

    def test_validation_raises_for_version_less_than_one(self, aggregate_kwargs):
        aggregate_kwargs["version"] = 0
        with pytest.raises(ForexRevaluationError, match="Version must be >= 1"):
            ForexRevaluationAggregate(**aggregate_kwargs)

    def test_validation_raises_for_naive_datetime(self, aggregate_kwargs):
        aggregate_kwargs["revaluation_date"] = datetime.now()  # naive
        with pytest.raises(ForexRevaluationError):
            ForexRevaluationAggregate(**aggregate_kwargs)

    # ---- Entity basic methods ----

    def test_create(self, aggregate):
        # create() just records audit and returns self (already created via __init__)
        agg = aggregate.create("tester")
        assert agg is aggregate  # returns self (no mutation)
        # Check audit trail
        assert len(agg.audit_trail()) >= 1
        assert agg.audit_trail()[-1]["action"] == "CREATE"

    def test_update(self, aggregate):
        agg2 = aggregate.update("updater", balance_fcy=Decimal("2000"))
        assert agg2 is not aggregate
        assert agg2.balance_fcy == Decimal("2000")
        assert agg2.version == aggregate.version + 1
        assert agg2.updated_at > aggregate.updated_at
        # Check audit
        assert agg2.audit_trail()[-1]["action"] == "UPDATE"

    def test_update_raises_if_not_draft(self, approved_aggregate):
        with pytest.raises(InvalidRevaluationStatusError, match="Cannot update revaluation in status approved"):
            approved_aggregate.update("tester", balance_fcy=Decimal("500"))

    def test_delete(self, aggregate):
        agg2 = aggregate.delete("tester", reason="Testing deletion")
        assert agg2.status == RevaluationStatus.CANCELLED
        assert agg2.cancelled_by == "tester"
        assert agg2.cancel_reason == "Testing deletion"
        assert agg2.version == aggregate.version + 1

    def test_delete_raises_if_posted(self, posted_aggregate):
        with pytest.raises(RevaluationAlreadyPostedError, match="Cannot delete posted revaluation"):
            posted_aggregate.delete("tester")

    def test_restore(self, aggregate):
        cancelled = aggregate.cancel("tester", "test")
        restored = cancelled.restore("admin")
        assert restored.status == RevaluationStatus.DRAFT
        assert restored.cancelled_by is None
        assert restored.cancel_reason is None
        assert restored.version == cancelled.version + 1

    def test_restore_raises_if_not_cancelled(self, aggregate):
        with pytest.raises(InvalidRevaluationStatusError, match="Cannot restore revaluation in status draft"):
            aggregate.restore("admin")

    def test_activate(self, aggregate):
        # activate() delegates to approve()
        agg2 = aggregate.activate("admin")
        assert agg2.status == RevaluationStatus.APPROVED
        assert agg2.approved_by == "admin"

    def test_activate_raises_if_not_draft(self, approved_aggregate):
        with pytest.raises(InvalidRevaluationStatusError, match="Cannot activate revaluation in status approved"):
            approved_aggregate.activate("admin")

    def test_deactivate(self, aggregate):
        agg2 = aggregate.deactivate("admin", "Deactivating")
        assert agg2.status == RevaluationStatus.CANCELLED
        assert agg2.cancel_reason == "Deactivating"

    def test_lock_unlock(self, aggregate):
        locked = aggregate.lock("admin", "Audit")
        assert locked.metadata["locked_by"] == "admin"
        assert "locked_at" in locked.metadata
        assert locked.metadata["lock_reason"] == "Audit"
        unlocked = locked.unlock("admin")
        assert "locked_by" not in unlocked.metadata

    def test_validate(self, aggregate):
        result = aggregate.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

        # Invalid: old rate date > revaluation date
        invalid = ForexRevaluationAggregate(
            aggregate_id=uuid4(),
            legal_entity_id=aggregate.legal_entity_id,
            currency="USD",
            revaluation_date=datetime.now(UTC),
            balance_fcy=Decimal("100"),
            old_rate=ExchangeRate("USD", Decimal("1"), datetime.now(UTC) + timedelta(days=1)),
            new_rate=ExchangeRate("USD", Decimal("1.1"), datetime.now(UTC)),
            gain_loss=Decimal("10"),
            gain_loss_type=GainLossType.GAIN,
        )
        result2 = invalid.validate()
        assert result2["is_valid"] is False
        assert "Old rate date" in result2["errors"][0]

    def test_to_dict_and_from_dict(self, aggregate):
        d = aggregate.to_dict()
        restored = ForexRevaluationAggregate.from_dict(d)
        assert restored.aggregate_id == aggregate.aggregate_id
        assert restored.currency == aggregate.currency
        assert restored.gain_loss == aggregate.gain_loss
        assert restored.status == aggregate.status
        # Check timestamps
        assert restored.created_at == aggregate.created_at

    def test_clone(self, aggregate):
        cloned = aggregate.clone()
        assert cloned.aggregate_id != aggregate.aggregate_id
        assert cloned.legal_entity_id == aggregate.legal_entity_id
        assert cloned.currency == aggregate.currency
        assert cloned.status == RevaluationStatus.DRAFT
        assert cloned.version == 1
        assert cloned.gain_loss == aggregate.gain_loss
        # Audit should record CLONE
        assert cloned.audit_trail()[-1]["action"] == "CLONE"

    def test_snapshot(self, aggregate):
        snap = aggregate.snapshot()
        assert snap["aggregate_id"] == str(aggregate.aggregate_id)
        assert snap["currency"] == "USD"
        assert snap["version"] == aggregate.version
        assert "timestamp" in snap

    def test_get_version(self, aggregate):
        assert aggregate.get_version() == aggregate.version

    def test_audit_trail(self, aggregate):
        # Create multiple actions
        aggregate.create("tester")
        aggregate.update("updater", balance_fcy=Decimal("2000"))
        trail = aggregate.audit_trail(limit=2)
        assert len(trail) == 2
        assert trail[0]["action"] == "UPDATE"
        assert trail[1]["action"] == "CREATE"

    def test_touch(self, aggregate):
        agg2 = aggregate.touch("tester")
        assert agg2.version == aggregate.version + 1
        assert agg2.updated_at > aggregate.updated_at
        assert agg2.audit_trail()[-1]["action"] == "TOUCH"

    # ---- Status transitions ----

    def test_approve(self, aggregate):
        agg2 = aggregate.approve("finance_manager")
        assert agg2.status == RevaluationStatus.APPROVED
        assert agg2.approved_by == "finance_manager"
        assert agg2.approved_at is not None
        assert agg2.version == aggregate.version + 1

    def test_approve_raises_if_not_draft(self, approved_aggregate):
        with pytest.raises(InvalidRevaluationStatusError, match="Cannot approve revaluation in status approved"):
            approved_aggregate.approve("finance_manager")

    def test_can_approve(self, aggregate):
        assert aggregate.can_approve("finance_manager") is True
        assert aggregate.can_approve("user") is False  # only finance_manager/admin

    def test_reject(self, aggregate):
        agg2 = aggregate.reject("admin", "Wrong data")
        assert agg2.status == RevaluationStatus.REJECTED
        assert agg2.rejected_by == "admin"
        assert agg2.rejection_reason == "Wrong data"

    def test_reject_raises_if_not_draft(self, approved_aggregate):
        with pytest.raises(InvalidRevaluationStatusError, match="Cannot reject revaluation in status approved"):
            approved_aggregate.reject("admin", "reason")

    def test_cancel(self, aggregate):
        agg2 = aggregate.cancel("tester", "Cancel test")
        assert agg2.status == RevaluationStatus.CANCELLED
        assert agg2.cancelled_by == "tester"
        assert agg2.cancel_reason == "Cancel test"

    def test_cancel_raises_if_posted(self, posted_aggregate):
        with pytest.raises(InvalidRevaluationStatusError, match="Cannot cancel revaluation in status posted"):
            posted_aggregate.cancel("tester", "reason")

    def test_post(self, approved_aggregate):
        agg2 = approved_aggregate.post("tester")
        assert agg2.status == RevaluationStatus.POSTED
        assert agg2.posted_by == "tester"
        assert agg2.posted_at is not None
        assert agg2.journal_id is not None
        assert agg2.journal is None  # Not stored in aggregate by default, only journal_id
        assert agg2.version == approved_aggregate.version + 1

    def test_post_raises_if_not_approved(self, aggregate):
        with pytest.raises(InvalidRevaluationStatusError, match="Cannot post revaluation in status draft"):
            aggregate.post("tester")

    def test_reverse(self, posted_aggregate):
        reversed_agg = posted_aggregate.reverse("admin", "Reversal due to error")
        assert reversed_agg.aggregate_id != posted_aggregate.aggregate_id
        assert reversed_agg.status == RevaluationStatus.DRAFT
        assert reversed_agg.gain_loss == posted_aggregate.gain_loss  # same amount
        # GainLossType should be opposite
        expected_type = GainLossType.LOSS if posted_aggregate.gain_loss_type == GainLossType.GAIN else GainLossType.GAIN
        assert reversed_agg.gain_loss_type == expected_type
        assert reversed_agg.old_rate == posted_aggregate.new_rate
        assert reversed_agg.new_rate == posted_aggregate.old_rate
        # Audit
        assert reversed_agg.audit_trail()[-1]["action"] == "REVERSE"

    def test_reverse_raises_if_not_posted(self, aggregate):
        with pytest.raises(InvalidRevaluationStatusError, match="Cannot reverse revaluation in status draft"):
            aggregate.reverse("admin", "reason")

    def test_close(self, posted_aggregate):
        # close() returns a copy with same version
        closed = posted_aggregate.close("tester", "Closing")
        assert closed.aggregate_id == posted_aggregate.aggregate_id
        assert closed.status == posted_aggregate.status
        assert closed.version == posted_aggregate.version  # no change

    def test_reopen(self, aggregate):
        cancelled = aggregate.cancel("tester", "test")
        reopened = cancelled.reopen("admin", "Reopen")
        assert reopened.status == RevaluationStatus.DRAFT
        assert reopened.version == cancelled.version + 1

    def test_reopen_raises_if_not_cancelled(self, approved_aggregate):
        with pytest.raises(InvalidRevaluationStatusError, match="Cannot reopen revaluation in status approved"):
            approved_aggregate.reopen("admin", "reason")

    def test_archive(self, posted_aggregate):
        archived = posted_aggregate.archive("admin", "Archiving old")
        assert archived.aggregate_id == posted_aggregate.aggregate_id
        assert archived.version == posted_aggregate.version + 1
        assert archived.audit_trail()[-1]["action"] == "ARCHIVE"

    def test_archive_raises_if_not_posted(self, aggregate):
        with pytest.raises(InvalidRevaluationStatusError, match="Cannot archive revaluation in status draft"):
            aggregate.archive("admin", "reason")

    def test_unarchive(self, aggregate):
        unarchived = aggregate.unarchive("admin")
        assert unarchived.version == aggregate.version + 1
        assert unarchived.audit_trail()[-1]["action"] == "UNARCHIVE"

    # ---- Business methods ----

    def test_calculate_revaluation_factory(self, legal_entity_id, old_rate, new_rate):
        agg = ForexRevaluationAggregate.calculate_revaluation(
            legal_entity_id=legal_entity_id,
            currency="USD",
            balance_fcy=Decimal("1000"),
            old_rate=old_rate,
            new_rate=new_rate,
            created_by="tester",
        )
        assert agg.legal_entity_id == legal_entity_id
        assert agg.currency == "USD"
        assert agg.balance_fcy == Decimal("1000")
        assert agg.gain_loss == Decimal("1000000")  # 1000 * 1000
        assert agg.gain_loss_type == GainLossType.GAIN
        assert agg.status == RevaluationStatus.DRAFT

    def test_create_adjustment_journal_gain(self, aggregate):
        journal = aggregate.create_adjustment_journal()
        assert isinstance(journal, RevaluationJournal)
        assert journal.revaluation_id == aggregate.aggregate_id
        assert len(journal.lines) == 2
        # Check line types
        line1, line2 = journal.lines[0], journal.lines[1]
        # For gain: credit gain, debit cash
        assert line1.account_code == "4210"  # Gain
        assert line1.credit == aggregate.gain_loss
        assert line2.account_code == "1100"  # Cash
        assert line2.debit == aggregate.gain_loss
        assert journal.is_balanced is True

    def test_create_adjustment_journal_loss(self, loss_aggregate):
        journal = loss_aggregate.create_adjustment_journal()
        line1, line2 = journal.lines[0], journal.lines[1]
        # For loss: debit loss, credit cash
        assert line1.account_code == "5210"  # Loss
        assert line1.debit == loss_aggregate.gain_loss
        assert line2.account_code == "1100"  # Cash
        assert line2.credit == loss_aggregate.gain_loss
        assert journal.is_balanced is True

    def test_create_adjustment_journal_raises_if_zero_gain_loss(self, aggregate):
        # Create aggregate with zero gain/loss
        zero_agg = ForexRevaluationAggregate(
            aggregate_id=uuid4(),
            legal_entity_id=aggregate.legal_entity_id,
            currency="USD",
            revaluation_date=datetime.now(UTC),
            balance_fcy=Decimal("1000"),
            old_rate=ExchangeRate("USD", Decimal("1"), datetime.now(UTC)),
            new_rate=ExchangeRate("USD", Decimal("1"), datetime.now(UTC)),
            gain_loss=Decimal("0"),
            gain_loss_type=GainLossType.NEUTRAL,
        )
        with pytest.raises(ForexRevaluationError, match="No gain/loss to journalize"):
            zero_agg.create_adjustment_journal()

    def test_get_result(self, aggregate):
        result = aggregate.get_result()
        assert isinstance(result, RevaluationResult)
        assert result.gain_loss == aggregate.gain_loss
        assert result.gain_loss_type == aggregate.gain_loss_type
        assert result.old_rate == aggregate.old_rate
        assert result.new_rate == aggregate.new_rate
        assert result.balance_fcy == aggregate.balance_fcy
        # Check LCY amounts
        expected_before = aggregate.old_rate.convert(aggregate.balance_fcy)
        expected_after = aggregate.new_rate.convert(aggregate.balance_fcy)
        assert result.balance_lcy_before == expected_before
        assert result.balance_lcy_after == expected_after

    # ---- Event methods ----

    def test_event_methods(self, aggregate):
        event = MagicMock()
        aggregate.register_event(event)
        assert len(aggregate.get_events()) == 1
        pulled = aggregate.pull_events()
        assert len(pulled) == 1
        assert pulled[0] == event
        assert len(aggregate.get_events()) == 0

        # apply
        aggregate.apply(MagicMock())
        assert len(aggregate.get_events()) == 1

    # ---- add_child / remove_child (not implemented) ----

    def test_add_child_not_implemented(self, aggregate):
        with pytest.raises(NotImplementedError, match="has no child entities"):
            aggregate.add_child(MagicMock(), "tester")

    def test_remove_child_not_implemented(self, aggregate):
        with pytest.raises(NotImplementedError, match="has no child entities"):
            aggregate.remove_child(uuid4(), "tester")

    # ---- Additional coverage: GainLossType.is_neutral ----

    def test_gain_loss_type_is_neutral(self):
        assert GainLossType.GAIN.is_neutral() is False
        assert GainLossType.LOSS.is_neutral() is False
        assert GainLossType.NEUTRAL.is_neutral() is True


# -----------------------------------------------------------------------------
# Tests for ForexRevaluationRepository (in-memory)
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
class TestForexRevaluationRepository:
    """Test the in-memory repository."""

    @pytest.fixture(autouse=True)
    def clear_storage(self):
        ForexRevaluationRepository._storage.clear()
        yield
        ForexRevaluationRepository._storage.clear()

    async def test_save_and_get_by_id(self, aggregate):
        await ForexRevaluationRepository.save(aggregate)
        retrieved = await ForexRevaluationRepository.get_by_id(aggregate.aggregate_id)
        assert retrieved is not None
        assert retrieved.aggregate_id == aggregate.aggregate_id

    async def test_get_by_legal_entity(self, aggregate, legal_entity_id):
        await ForexRevaluationRepository.save(aggregate)
        results = await ForexRevaluationRepository.get_by_legal_entity(legal_entity_id)
        assert len(results) == 1
        assert results[0].legal_entity_id == legal_entity_id

    async def test_get_by_currency(self, aggregate):
        await ForexRevaluationRepository.save(aggregate)
        results = await ForexRevaluationRepository.get_by_currency(aggregate.legal_entity_id, "USD")
        assert len(results) == 1
        assert results[0].currency == "USD"

    async def test_get_by_status(self, aggregate):
        await ForexRevaluationRepository.save(aggregate)
        results = await ForexRevaluationRepository.get_by_status(aggregate.legal_entity_id, RevaluationStatus.DRAFT)
        assert len(results) == 1
        assert results[0].status == RevaluationStatus.DRAFT

    async def test_get_all(self, aggregate):
        await ForexRevaluationRepository.save(aggregate)
        all_agg = await ForexRevaluationRepository.get_all()
        assert len(all_agg) == 1

    async def test_delete(self, aggregate):
        await ForexRevaluationRepository.save(aggregate)
        await ForexRevaluationRepository.delete(aggregate.aggregate_id)
        retrieved = await ForexRevaluationRepository.get_by_id(aggregate.aggregate_id)
        assert retrieved is None

    async def test_exists(self, aggregate):
        await ForexRevaluationRepository.save(aggregate)
        assert await ForexRevaluationRepository.exists(aggregate.aggregate_id) is True
        assert await ForexRevaluationRepository.exists(uuid4()) is False

    async def test_count(self, aggregate):
        await ForexRevaluationRepository.save(aggregate)
        assert await ForexRevaluationRepository.count() == 1

    async def test_list(self, aggregate):
        await ForexRevaluationRepository.save(aggregate)
        results = await ForexRevaluationRepository.list(limit=10, offset=0)
        assert len(results) == 1

    async def test_clear(self, aggregate):
        await ForexRevaluationRepository.save(aggregate)
        await ForexRevaluationRepository.clear()
        assert len(await ForexRevaluationRepository.get_all()) == 0


# -----------------------------------------------------------------------------
# Tests for helper function add_audit
# -----------------------------------------------------------------------------

def test_add_audit(caplog):
    """add_audit logs an INFO message with AUDIT prefix."""
    with caplog.at_level(logging.INFO):
        add_audit("TEST_ACTION", {"key": "value"})
        assert "AUDIT: TEST_ACTION - {'key': 'value'}" in caplog.text