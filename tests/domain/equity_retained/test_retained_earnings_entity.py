# tests/domain/equity_retained/test_retained_earnings_entity.py
"""
Comprehensive unit tests for retained_earnings_entity.py.

Covers:
- Enums: RetainedEarningsEntryType, RetainedEarningsPeriod (members, display_name, is_increase, is_decrease)
- Value Object: RetainedEarningsEntry (construction, validation, to_dict, from_dict)
- Entity: RetainedEarningsEntity (construction, validation, entity dasar methods,
  properties, business logic, query methods, serialization, repository)
- Exceptions: RetainedEarningsError, InsufficientRetainedEarningsError, DuplicatePeriodError
- Helper functions: calculate_retained_earnings_after_period, format_retained_earnings
- Repository: all methods (get_by_legal_entity, get_by_id, get_all, save, update,
  delete, exists, count, list, paginate, search, lock, unlock, clear)
- Negative path: all exception scenarios with pytest.raises
- Mock datetime to avoid flaky tests
"""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest

from domain.equity_retained.retained_earnings_entity import (
    DuplicatePeriodError,
    InsufficientRetainedEarningsError,
    RetainedEarningsEntity,
    RetainedEarningsEntry,
    RetainedEarningsEntryType,
    RetainedEarningsError,
    RetainedEarningsPeriod,
    RetainedEarningsRepository,
    calculate_retained_earnings_after_period,
    format_retained_earnings,
)

# =============================================================================
# FIXED DATETIME (untuk menghindari flaky)
# =============================================================================

FIXED_DATETIME = datetime(2026, 1, 15, 10, 30, 0, tzinfo=UTC)
FIXED_PERIOD = "2026-01"
FIXED_CURRENCY = "IDR"
FIXED_OPENING_BALANCE = Decimal("1000000")


@pytest.fixture(autouse=True)
def mock_datetime_now():
    """Mock datetime.now(UTC) to return fixed datetime."""
    with patch("domain.equity_retained.retained_earnings_entity.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_DATETIME
        mock_dt.UTC = UTC
        yield mock_dt


# =============================================================================
# Helper to create valid RetainedEarningsEntry
# =============================================================================

def create_valid_entry(
    entry_id=None,
    period=FIXED_PERIOD,
    entry_type=RetainedEarningsEntryType.NET_INCOME,
    net_income=Decimal("500000"),
    dividends=Decimal("0"),
    adjustment=Decimal("0"),
    amount=Decimal("500000"),
    balance_after=Decimal("1500000"),
    description="Net income for Jan 2026",
    reference_id="REF-001",
    created_by="system",
    created_at=FIXED_DATETIME,
):
    if entry_id is None:
        entry_id = uuid4()
    return RetainedEarningsEntry(
        entry_id=entry_id,
        period=period,
        entry_type=entry_type,
        net_income=net_income,
        dividends=dividends,
        adjustment=adjustment,
        amount=amount,
        balance_after=balance_after,
        description=description,
        reference_id=reference_id,
        created_by=created_by,
        created_at=created_at,
    )


def create_valid_entity(
    retained_earnings_id=None,
    legal_entity_id=None,
    opening_balance=FIXED_OPENING_BALANCE,
    current_balance=FIXED_OPENING_BALANCE,
    entries=None,
    currency=FIXED_CURRENCY,
    created_at=FIXED_DATETIME,
    updated_at=FIXED_DATETIME,
    version=1,
    metadata=None,
):
    if retained_earnings_id is None:
        retained_earnings_id = uuid4()
    if legal_entity_id is None:
        legal_entity_id = uuid4()
    if entries is None:
        entries = []
    if metadata is None:
        metadata = {}
    return RetainedEarningsEntity(
        retained_earnings_id=retained_earnings_id,
        legal_entity_id=legal_entity_id,
        opening_balance=opening_balance,
        current_balance=current_balance,
        entries=entries,
        currency=currency,
        created_at=created_at,
        updated_at=updated_at,
        version=version,
        metadata=metadata,
    )


# =============================================================================
# Tests for Enums
# =============================================================================

class TestRetainedEarningsEntryType:
    def test_members(self):
        assert RetainedEarningsEntryType.OPENING_BALANCE.value == "opening_balance"
        assert RetainedEarningsEntryType.NET_INCOME.value == "net_income"
        assert RetainedEarningsEntryType.NET_LOSS.value == "net_loss"
        assert RetainedEarningsEntryType.DIVIDEND.value == "dividend"
        assert RetainedEarningsEntryType.PRIOR_PERIOD_ADJUSTMENT.value == "adjustment"
        assert RetainedEarningsEntryType.TRANSFER_TO_RESERVE.value == "transfer_to_reserve"
        assert RetainedEarningsEntryType.TRANSFER_FROM_RESERVE.value == "transfer_from_reserve"

    def test_display_name(self):
        assert RetainedEarningsEntryType.OPENING_BALANCE.display_name() == "Saldo Awal"
        assert RetainedEarningsEntryType.NET_INCOME.display_name() == "Laba Bersih"
        assert RetainedEarningsEntryType.NET_LOSS.display_name() == "Rugi Bersih"
        assert RetainedEarningsEntryType.DIVIDEND.display_name() == "Dividen"
        assert RetainedEarningsEntryType.PRIOR_PERIOD_ADJUSTMENT.display_name() == "Penyesuaian"
        assert RetainedEarningsEntryType.TRANSFER_TO_RESERVE.display_name() == "Transfer ke Cadangan"
        assert RetainedEarningsEntryType.TRANSFER_FROM_RESERVE.display_name() == "Transfer dari Cadangan"

    def test_is_increase(self):
        assert RetainedEarningsEntryType.NET_INCOME.is_increase() is True
        assert RetainedEarningsEntryType.OPENING_BALANCE.is_increase() is True
        assert RetainedEarningsEntryType.TRANSFER_FROM_RESERVE.is_increase() is True
        assert RetainedEarningsEntryType.NET_LOSS.is_increase() is False
        assert RetainedEarningsEntryType.DIVIDEND.is_increase() is False
        assert RetainedEarningsEntryType.TRANSFER_TO_RESERVE.is_increase() is False

    def test_is_decrease(self):
        assert RetainedEarningsEntryType.NET_LOSS.is_decrease() is True
        assert RetainedEarningsEntryType.DIVIDEND.is_decrease() is True
        assert RetainedEarningsEntryType.TRANSFER_TO_RESERVE.is_decrease() is True
        assert RetainedEarningsEntryType.NET_INCOME.is_decrease() is False
        assert RetainedEarningsEntryType.OPENING_BALANCE.is_decrease() is False
        assert RetainedEarningsEntryType.TRANSFER_FROM_RESERVE.is_decrease() is False


class TestRetainedEarningsPeriod:
    def test_members(self):
        assert RetainedEarningsPeriod.MONTHLY.value == "monthly"
        assert RetainedEarningsPeriod.QUARTERLY.value == "quarterly"
        assert RetainedEarningsPeriod.YEARLY.value == "yearly"
        assert RetainedEarningsPeriod.CUSTOM.value == "custom"


# =============================================================================
# Tests for Exceptions
# =============================================================================

def test_retained_earnings_error():
    with pytest.raises(RetainedEarningsError):
        raise RetainedEarningsError("test")


def test_insufficient_retained_earnings_error():
    with pytest.raises(InsufficientRetainedEarningsError):
        raise InsufficientRetainedEarningsError("test")


def test_duplicate_period_error():
    with pytest.raises(DuplicatePeriodError):
        raise DuplicatePeriodError("test")


# =============================================================================
# Tests for RetainedEarningsEntry
# =============================================================================

class TestRetainedEarningsEntry:
    def test_construction_valid(self):
        entry = create_valid_entry()
        assert entry.entry_id is not None
        assert entry.period == FIXED_PERIOD
        assert entry.entry_type == RetainedEarningsEntryType.NET_INCOME
        assert entry.net_income == Decimal("500000")
        assert entry.amount == Decimal("500000")
        assert entry.balance_after == Decimal("1500000")
        assert entry.created_at == FIXED_DATETIME

    def test_validation_invalid_period(self):
        with pytest.raises(RetainedEarningsError, match="Period must be a non-empty string"):
            RetainedEarningsEntry(
                entry_id=uuid4(),
                period="",
                entry_type=RetainedEarningsEntryType.NET_INCOME,
                net_income=Decimal("0"),
                dividends=Decimal("0"),
                adjustment=Decimal("0"),
                amount=Decimal("0"),
                balance_after=Decimal("0"),
                description="",
                created_by="system",
            )

    def test_validation_invalid_entry_type(self):
        with pytest.raises(RetainedEarningsError, match="Invalid entry_type"):
            RetainedEarningsEntry(
                entry_id=uuid4(),
                period="2026-01",
                entry_type="INVALID",  # type: ignore
                net_income=Decimal("0"),
                dividends=Decimal("0"),
                adjustment=Decimal("0"),
                amount=Decimal("0"),
                balance_after=Decimal("0"),
                description="",
                created_by="system",
            )

    def test_to_dict(self):
        entry = create_valid_entry()
        d = entry.to_dict()
        assert d["entry_id"] == str(entry.entry_id)
        assert d["period"] == FIXED_PERIOD
        assert d["entry_type"] == "net_income"
        assert d["entry_type_display"] == "Laba Bersih"
        assert d["net_income"] == "500000"
        assert d["amount"] == "500000"
        assert d["balance_after"] == "1500000"
        assert d["created_by"] == "system"

    def test_from_dict(self):
        entry = create_valid_entry()
        data = entry.to_dict()
        restored = RetainedEarningsEntry.from_dict(data)
        assert restored.entry_id == entry.entry_id
        assert restored.period == entry.period
        assert restored.entry_type == entry.entry_type
        assert restored.net_income == entry.net_income
        assert restored.amount == entry.amount
        assert restored.balance_after == entry.balance_after
        assert restored.created_by == entry.created_by


# =============================================================================
# Tests for RetainedEarningsEntity
# =============================================================================

class TestRetainedEarningsEntity:
    def test_construction_valid(self):
        entity = create_valid_entity()
        assert entity.retained_earnings_id is not None
        assert entity.legal_entity_id is not None
        assert entity.opening_balance == FIXED_OPENING_BALANCE
        assert entity.current_balance == FIXED_OPENING_BALANCE
        assert entity.version == 1
        assert entity.created_at == FIXED_DATETIME
        assert entity.updated_at == FIXED_DATETIME

    def test_construction_invalid_currency(self):
        with pytest.raises(RetainedEarningsError, match="Invalid currency"):
            create_valid_entity(currency="ID")

    def test_validation_balance_mismatch_warning(self, caplog):
        # Create entity with one entry but current_balance doesn't match sum
        entry = create_valid_entry(amount=Decimal("500000"), balance_after=Decimal("1500000"))
        create_valid_entity(
            opening_balance=Decimal("1000000"),
            current_balance=Decimal("2000000"),
            entries=[entry],
        )
        # Validation should log a warning
        assert "Entries sum 1500000 does not match current_balance 2000000" in caplog.text

    # ---- Entity Dasar Methods ----

    def test_create(self):
        entity = create_valid_entity()
        result = entity.create("admin")
        assert result is entity
        trail = result._audit_trail
        assert len(trail) == 1
        assert trail[0]["action"] == "CREATE"

    def test_update(self):
        entity = create_valid_entity()
        updated = entity.update("admin", opening_balance=Decimal("2000000"))
        assert updated.opening_balance == Decimal("2000000")
        assert updated.version == entity.version + 1
        trail = updated._audit_trail
        assert trail[-1]["action"] == "UPDATE"

    def test_update_ignores_protected_fields(self):
        entity = create_valid_entity()
        updated = entity.update("admin", retained_earnings_id=uuid4(), created_at=datetime.now(UTC), version=99)
        assert updated.retained_earnings_id == entity.retained_earnings_id
        assert updated.created_at == entity.created_at
        assert updated.version == entity.version + 1  # not 99

    def test_delete(self):
        entity = create_valid_entity()
        deleted = entity.delete("admin", "closing")
        assert deleted.entries == []
        assert deleted.opening_balance == Decimal("0")
        assert deleted.current_balance == Decimal("0")
        assert deleted.version == entity.version + 1
        trail = deleted._audit_trail
        assert trail[-1]["action"] == "DELETE"

    def test_restore(self):
        entity = create_valid_entity(opening_balance=Decimal("1000000"), current_balance=Decimal("1500000"))
        restored = entity.restore("admin")
        assert restored.current_balance == restored.opening_balance == Decimal("1000000")
        assert restored.entries == []
        assert restored.version == entity.version + 1
        trail = restored._audit_trail
        assert trail[-1]["action"] == "RESTORE"

    def test_activate(self):
        entity = create_valid_entity()
        activated = entity.activate("admin")
        assert activated.version == entity.version + 1
        trail = activated._audit_trail
        assert trail[-1]["action"] == "ACTIVATE"

    def test_deactivate(self):
        entity = create_valid_entity()
        deactivated = entity.deactivate("admin", "reason")
        assert deactivated.version == entity.version + 1
        trail = deactivated._audit_trail
        assert trail[-1]["action"] == "DEACTIVATE"

    def test_lock(self):
        entity = create_valid_entity()
        locked = entity.lock("admin", "audit")
        assert locked.metadata["locked_by"] == "admin"
        assert locked.metadata["lock_reason"] == "audit"
        assert locked.version == entity.version + 1
        trail = locked._audit_trail
        assert trail[-1]["action"] == "LOCK"

    def test_unlock(self):
        entity = create_valid_entity()
        entity.metadata["locked_by"] = "admin"
        unlocked = entity.unlock("admin")
        assert "locked_by" not in unlocked.metadata
        assert unlocked.version == entity.version + 1
        trail = unlocked._audit_trail
        assert trail[-1]["action"] == "UNLOCK"

    def test_validate_success(self):
        entity = create_valid_entity()
        result = entity.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_negative_balance(self):
        entity = create_valid_entity(current_balance=Decimal("-1000"))
        result = entity.validate()
        assert result["is_valid"] is False
        assert "Negative retained earnings balance" in result["errors"][0]

    def test_to_dict_without_entries(self):
        entity = create_valid_entity()
        d = entity.to_dict(include_entries=False)
        assert "entries" not in d
        assert d["entries_count"] == 0
        assert d["retained_earnings_id"] == str(entity.retained_earnings_id)

    def test_to_dict_with_entries(self):
        entry = create_valid_entry()
        entity = create_valid_entity(entries=[entry])
        d = entity.to_dict(include_entries=True)
        assert "entries" in d
        assert len(d["entries"]) == 1
        assert d["entries"][0]["entry_id"] == str(entry.entry_id)

    def test_from_dict(self):
        entity = create_valid_entity()
        data = entity.to_dict()
        restored = RetainedEarningsEntity.from_dict(data)
        assert restored.retained_earnings_id == entity.retained_earnings_id
        assert restored.legal_entity_id == entity.legal_entity_id
        assert restored.opening_balance == entity.opening_balance
        assert restored.current_balance == entity.current_balance
        assert restored.version == entity.version

    def test_clone(self):
        entity = create_valid_entity()
        clone = entity.clone()
        assert clone.retained_earnings_id != entity.retained_earnings_id
        assert clone.legal_entity_id == entity.legal_entity_id
        assert clone.opening_balance == entity.opening_balance
        assert clone.current_balance == entity.opening_balance  # reset to opening
        assert clone.entries == []
        assert clone.version == 1
        trail = clone._audit_trail
        assert trail[-1]["action"] == "CLONE"

    def test_snapshot(self):
        entity = create_valid_entity()
        snap = entity.snapshot()
        assert snap["retained_earnings_id"] == str(entity.retained_earnings_id)
        assert snap["balance"] == str(entity.current_balance)
        assert "timestamp" in snap

    def test_get_version(self):
        entity = create_valid_entity(version=5)
        assert entity.get_version() == 5

    def test_audit_trail(self):
        entity = create_valid_entity()
        entity._record_audit("TEST", "user", {"key": "val"})
        trail = entity.audit_trail(limit=10)
        assert len(trail) == 1
        assert trail[0]["action"] == "TEST"

    def test_touch(self):
        entity = create_valid_entity(version=3)
        touched = entity.touch("admin")
        assert touched.version == 4
        trail = touched._audit_trail
        assert trail[-1]["action"] == "TOUCH"

    # ---- Properties ----

    def test_total_net_income(self):
        entries = [
            create_valid_entry(net_income=Decimal("500000"), amount=Decimal("500000")),
            create_valid_entry(net_income=Decimal("-200000"), amount=Decimal("-200000")),
        ]
        entity = create_valid_entity(entries=entries)
        assert entity.total_net_income == Decimal("500000")

    def test_total_net_loss(self):
        entries = [
            create_valid_entry(net_income=Decimal("500000"), amount=Decimal("500000")),
            create_valid_entry(net_income=Decimal("-200000"), amount=Decimal("-200000")),
        ]
        entity = create_valid_entity(entries=entries)
        assert entity.total_net_loss == Decimal("200000")

    def test_total_dividends(self):
        entries = [
            create_valid_entry(dividends=Decimal("100000"), amount=Decimal("-100000")),
            create_valid_entry(dividends=Decimal("50000"), amount=Decimal("-50000")),
        ]
        entity = create_valid_entity(entries=entries)
        assert entity.total_dividends == Decimal("150000")

    def test_total_adjustments(self):
        entries = [
            create_valid_entry(adjustment=Decimal("10000"), amount=Decimal("10000")),
            create_valid_entry(adjustment=Decimal("-5000"), amount=Decimal("-5000")),
        ]
        entity = create_valid_entity(entries=entries)
        assert entity.total_adjustments == Decimal("5000")

    def test_net_change_period(self):
        entity = create_valid_entity(opening_balance=Decimal("1000000"), current_balance=Decimal("1500000"))
        assert entity.net_change_period == Decimal("500000")

    def test_is_accumulated_loss_true(self):
        entity = create_valid_entity(current_balance=Decimal("-1000"))
        assert entity.is_accumulated_loss is True

    def test_is_accumulated_loss_false(self):
        entity = create_valid_entity(current_balance=Decimal("1000"))
        assert entity.is_accumulated_loss is False

    # ---- Business Logic ----

    def test_add_net_income_positive(self):
        entity = create_valid_entity(opening_balance=Decimal("1000000"), current_balance=Decimal("1000000"))
        new_entity = entity.add_net_income(
            net_income=Decimal("500000"),
            period="2026-01",
            created_by="admin",
            description="Profit",
            reference_id="REF-001",
        )
        assert new_entity.current_balance == Decimal("1500000")
        assert len(new_entity.entries) == 1
        entry = new_entity.entries[0]
        assert entry.entry_type == RetainedEarningsEntryType.NET_INCOME
        assert entry.net_income == Decimal("500000")
        assert entry.amount == Decimal("500000")
        assert entry.balance_after == Decimal("1500000")
        assert entry.period == "2026-01"
        assert entry.reference_id == "REF-001"
        trail = new_entity._audit_trail
        assert trail[-1]["action"] == "ADD_NET_INCOME"

    def test_add_net_income_negative(self):
        entity = create_valid_entity(opening_balance=Decimal("1000000"), current_balance=Decimal("1000000"))
        new_entity = entity.add_net_income(
            net_income=Decimal("-200000"),
            period="2026-01",
            created_by="admin",
            description="Loss",
            reference_id=None,
        )
        assert new_entity.current_balance == Decimal("800000")
        entry = new_entity.entries[0]
        assert entry.entry_type == RetainedEarningsEntryType.NET_LOSS
        assert entry.net_income == Decimal("-200000")
        assert entry.amount == Decimal("-200000")

    def test_add_net_income_zero_returns_same(self):
        entity = create_valid_entity()
        new_entity = entity.add_net_income(Decimal("0"), "2026-01", "admin")
        assert new_entity is entity

    def test_record_dividend_success(self):
        entity = create_valid_entity(opening_balance=Decimal("1000000"), current_balance=Decimal("1000000"))
        new_entity = entity.record_dividend(
            dividend_amount=Decimal("300000"),
            period="2026-01",
            created_by="admin",
            description="Dividend",
            reference_id="REF-DIV",
        )
        assert new_entity.current_balance == Decimal("700000")
        entry = new_entity.entries[0]
        assert entry.entry_type == RetainedEarningsEntryType.DIVIDEND
        assert entry.dividends == Decimal("300000")
        assert entry.amount == Decimal("-300000")
        assert entry.balance_after == Decimal("700000")
        assert entry.reference_id == "REF-DIV"
        trail = new_entity._audit_trail
        assert trail[-1]["action"] == "RECORD_DIVIDEND"

    def test_record_dividend_zero_raises(self):
        entity = create_valid_entity()
        with pytest.raises(RetainedEarningsError, match="positive"):
            entity.record_dividend(Decimal("0"), "2026-01", "admin")

    def test_record_dividend_insufficient_raises(self):
        entity = create_valid_entity(current_balance=Decimal("100000"))
        with pytest.raises(InsufficientRetainedEarningsError, match="Cannot record dividend"):
            entity.record_dividend(Decimal("200000"), "2026-01", "admin")

    def test_add_prior_period_adjustment_positive(self):
        entity = create_valid_entity(opening_balance=Decimal("1000000"), current_balance=Decimal("1000000"))
        new_entity = entity.add_prior_period_adjustment(
            adjustment=Decimal("50000"),
            period="2025-12",
            created_by="admin",
            description="Adjustment",
            reference_id="REF-ADJ",
        )
        assert new_entity.current_balance == Decimal("1050000")
        entry = new_entity.entries[0]
        assert entry.entry_type == RetainedEarningsEntryType.PRIOR_PERIOD_ADJUSTMENT
        assert entry.adjustment == Decimal("50000")
        assert entry.amount == Decimal("50000")
        assert entry.period == "2025-12"
        trail = new_entity._audit_trail
        assert trail[-1]["action"] == "ADD_ADJUSTMENT"

    def test_add_prior_period_adjustment_zero_returns_same(self):
        entity = create_valid_entity()
        new_entity = entity.add_prior_period_adjustment(Decimal("0"), "2025-12", "admin")
        assert new_entity is entity

    def test_transfer_to_reserve_success(self):
        entity = create_valid_entity(opening_balance=Decimal("1000000"), current_balance=Decimal("1000000"))
        new_entity = entity.transfer_to_reserve(
            amount=Decimal("200000"),
            period="2026-01",
            created_by="admin",
            description="Transfer to reserve",
        )
        assert new_entity.current_balance == Decimal("800000")
        entry = new_entity.entries[0]
        assert entry.entry_type == RetainedEarningsEntryType.TRANSFER_TO_RESERVE
        assert entry.amount == Decimal("-200000")
        trail = new_entity._audit_trail
        assert trail[-1]["action"] == "TRANSFER_TO_RESERVE"

    def test_transfer_to_reserve_zero_raises(self):
        entity = create_valid_entity()
        with pytest.raises(RetainedEarningsError, match="positive"):
            entity.transfer_to_reserve(Decimal("0"), "2026-01", "admin")

    def test_transfer_to_reserve_insufficient_raises(self):
        entity = create_valid_entity(current_balance=Decimal("100000"))
        with pytest.raises(InsufficientRetainedEarningsError, match="Cannot transfer"):
            entity.transfer_to_reserve(Decimal("200000"), "2026-01", "admin")

    def test_transfer_from_reserve_success(self):
        entity = create_valid_entity(opening_balance=Decimal("1000000"), current_balance=Decimal("1000000"))
        new_entity = entity.transfer_from_reserve(
            amount=Decimal("150000"),
            period="2026-01",
            created_by="admin",
            description="Transfer from reserve",
        )
        assert new_entity.current_balance == Decimal("1150000")
        entry = new_entity.entries[0]
        assert entry.entry_type == RetainedEarningsEntryType.TRANSFER_FROM_RESERVE
        assert entry.amount == Decimal("150000")
        trail = new_entity._audit_trail
        assert trail[-1]["action"] == "TRANSFER_FROM_RESERVE"

    def test_transfer_from_reserve_zero_raises(self):
        entity = create_valid_entity()
        with pytest.raises(RetainedEarningsError, match="positive"):
            entity.transfer_from_reserve(Decimal("0"), "2026-01", "admin")

    # ---- Query Methods ----

    def test_get_entry_by_period_found(self):
        entry1 = create_valid_entry(period="2026-01", amount=Decimal("500000"))
        entry2 = create_valid_entry(period="2026-02", amount=Decimal("300000"))
        entity = create_valid_entity(entries=[entry1, entry2])
        result = entity.get_entry_by_period("2026-01")
        assert result is entry1

    def test_get_entry_by_period_not_found(self):
        entity = create_valid_entity(entries=[create_valid_entry(period="2026-01")])
        result = entity.get_entry_by_period("2026-02")
        assert result is None

    def test_get_entries_by_type(self):
        entry1 = create_valid_entry(entry_type=RetainedEarningsEntryType.NET_INCOME)
        entry2 = create_valid_entry(entry_type=RetainedEarningsEntryType.DIVIDEND)
        entity = create_valid_entity(entries=[entry1, entry2])
        results = entity.get_entries_by_type(RetainedEarningsEntryType.NET_INCOME)
        assert len(results) == 1
        assert results[0] is entry1

    def test_get_balance_at_period_before_first(self):
        # Opening balance + entries before period
        entity = create_valid_entity(opening_balance=Decimal("1000000"), current_balance=Decimal("1500000"))
        # No entries yet
        balance = entity.get_balance_at_period("2026-01")
        assert balance == Decimal("1000000")

    def test_get_balance_at_period_after_entries(self):
        entry1 = create_valid_entry(period="2026-01", amount=Decimal("500000"), balance_after=Decimal("1500000"))
        entry2 = create_valid_entry(period="2026-02", amount=Decimal("300000"), balance_after=Decimal("1800000"))
        entity = create_valid_entity(opening_balance=Decimal("1000000"), entries=[entry1, entry2])
        balance = entity.get_balance_at_period("2026-01")
        assert balance == Decimal("1500000")

    # ---- Private methods (indirectly tested) ----

    def test__take_snapshot_limits(self):
        entity = create_valid_entity()
        for _ in range(15):
            entity._take_snapshot()
        assert len(entity._snapshots) <= 10

    def test__record_audit(self):
        entity = create_valid_entity()
        entity._record_audit("TEST", "user", {"data": "val"})
        trail = entity._audit_trail
        assert len(trail) == 1
        assert trail[0]["action"] == "TEST"

    def test__add_entry(self):
        entity = create_valid_entity(opening_balance=Decimal("1000000"), current_balance=Decimal("1000000"))
        entry = create_valid_entry(amount=Decimal("500000"), balance_after=Decimal("1500000"))
        new_entity = entity._add_entry(entry)
        assert new_entity.current_balance == Decimal("1500000")
        assert len(new_entity.entries) == 1
        assert new_entity.version == entity.version + 1

    def test__copy(self):
        entity = create_valid_entity()
        copy = entity._copy()
        assert copy.retained_earnings_id == entity.retained_earnings_id
        assert copy.opening_balance == entity.opening_balance
        assert copy.current_balance == entity.current_balance
        assert copy.entries is not entity.entries  # shallow copy
        assert copy.version == entity.version


# =============================================================================
# Tests for Helper Functions
# =============================================================================

def test_calculate_retained_earnings_after_period():
    result = calculate_retained_earnings_after_period(
        opening_balance=Decimal("1000000"),
        net_income=Decimal("500000"),
        dividends=Decimal("200000"),
    )
    assert result == Decimal("1300000")


def test_format_retained_earnings():
    assert format_retained_earnings(Decimal("1234567.89"), "IDR") == "IDR 1,234,567.89"
    assert format_retained_earnings(Decimal("0"), "USD") == "USD 0.00"


# =============================================================================
# Tests for RetainedEarningsRepository
# =============================================================================

@pytest.mark.asyncio
class TestRetainedEarningsRepository:
    @pytest.fixture(autouse=True)
    def clear_storage(self):
        RetainedEarningsRepository._storage.clear()
        yield

    @pytest.fixture
    def entity(self):
        return create_valid_entity()

    @pytest.fixture
    def repo(self):
        return RetainedEarningsRepository()

    async def test_save_and_get_by_id(self, repo, entity):
        await repo.save(entity)
        retrieved = await repo.get_by_id(entity.retained_earnings_id)
        assert retrieved is entity

    async def test_get_by_legal_entity(self, repo, entity):
        await repo.save(entity)
        retrieved = await repo.get_by_legal_entity(entity.legal_entity_id)
        assert retrieved is entity

    async def test_get_all(self, repo, entity):
        await repo.save(entity)
        all_entities = await repo.get_all()
        assert len(all_entities) == 1
        assert all_entities[0] is entity

    async def test_update(self, repo, entity):
        await repo.save(entity)
        entity.currency = "USD"
        await repo.update(entity)
        retrieved = await repo.get_by_id(entity.retained_earnings_id)
        assert retrieved.currency == "USD"

    async def test_delete(self, repo, entity):
        await repo.save(entity)
        await repo.delete(entity.retained_earnings_id)
        retrieved = await repo.get_by_id(entity.retained_earnings_id)
        assert retrieved is None

    async def test_exists(self, repo, entity):
        await repo.save(entity)
        assert await repo.exists(entity.retained_earnings_id) is True
        assert await repo.exists(uuid4()) is False

    async def test_count(self, repo, entity):
        await repo.save(entity)
        assert await repo.count() == 1

    async def test_list(self, repo, entity):
        await repo.save(entity)
        entities = await repo.list(limit=10, offset=0)
        assert len(entities) == 1

    async def test_paginate(self, repo, entity):
        await repo.save(entity)
        entities, total = await repo.paginate(page=1, per_page=10)
        assert len(entities) == 1
        assert total == 1

    async def test_search(self, repo, entity):
        await repo.save(entity)
        results = await repo.search(str(entity.legal_entity_id), fields=["legal_entity_id"])
        assert len(results) == 1
        assert results[0] is entity

    async def test_lock(self, repo, entity):
        await repo.save(entity)
        locked = await repo.lock(entity.retained_earnings_id, "admin", "audit")
        assert locked.metadata["locked_by"] == "admin"
        assert locked.version == entity.version + 1

    async def test_lock_not_found(self, repo):
        with pytest.raises(ValueError, match="not found"):
            await repo.lock(uuid4(), "admin", "audit")

    async def test_unlock(self, repo, entity):
        await repo.save(entity)
        await repo.lock(entity.retained_earnings_id, "admin", "audit")
        unlocked = await repo.unlock(entity.retained_earnings_id, "admin")
        assert "locked_by" not in unlocked.metadata
        assert unlocked.version == entity.version + 2

    async def test_unlock_not_found(self, repo):
        with pytest.raises(ValueError, match="not found"):
            await repo.unlock(uuid4(), "admin")

    async def test_clear(self, repo, entity):
        await repo.save(entity)
        await repo.clear()
        all_entities = await repo.get_all()
        assert all_entities == []

    async def test_search_no_fields(self, repo, entity):
        await repo.save(entity)
        results = await repo.search(str(entity.retained_earnings_id))
        assert len(results) == 1
        # default fields include retained_earnings_id and legal_entity_id

    async def test_search_multiple_entities(self, repo):
        e1 = create_valid_entity(legal_entity_id=UUID("11111111-1111-1111-1111-111111111111"))
        e2 = create_valid_entity(legal_entity_id=UUID("22222222-2222-2222-2222-222222222222"))
        await repo.save(e1)
        await repo.save(e2)
        results = await repo.search("11111111", fields=["legal_entity_id"])
        assert len(results) == 1
        assert results[0] is e1
