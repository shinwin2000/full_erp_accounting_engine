# tests/kernel/guards/test_period_lock.py
"""
Comprehensive tests for kernel/guards/period_lock.py
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from kernel.guards.guard_exceptions import PeriodLockError
from kernel.guards.period_lock import (
    BasePeriodLockGuard,
    FiscalPeriod,
    PeriodLock,
    PeriodLockCheckResult,
    PeriodLockGuard,
    PeriodLockSeverity,
    PeriodStatus,
    _FallbackFiscalPeriodRepository,
    get_period_lock_guard,
    lock_period,
    unlock_period,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def fixed_now():
    return datetime(2026, 7, 27, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mock_datetime(fixed_now):
    with patch("kernel.guards.period_lock.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.utcnow.return_value = fixed_now
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        yield mock_dt


@pytest.fixture
def legal_entity_id():
    return uuid4()


@pytest.fixture
def period_id():
    return uuid4()


@pytest.fixture
def sample_period(legal_entity_id, period_id):
    return FiscalPeriod(
        period_id=period_id,
        legal_entity_id=legal_entity_id,
        fiscal_year=2026,
        period_number=1,
        period_name="Jan 2026",
        start_date=datetime(2026, 1, 1, tzinfo=UTC),
        end_date=datetime(2026, 1, 31, tzinfo=UTC),
        status=PeriodStatus.OPEN,
    )


@pytest.fixture
def closed_period(legal_entity_id):
    return FiscalPeriod(
        period_id=uuid4(),
        legal_entity_id=legal_entity_id,
        fiscal_year=2026,
        period_number=2,
        period_name="Feb 2026",
        start_date=datetime(2026, 2, 1, tzinfo=UTC),
        end_date=datetime(2026, 2, 28, tzinfo=UTC),
        status=PeriodStatus.CLOSED,
    )


@pytest.fixture
def locked_period(legal_entity_id):
    return FiscalPeriod(
        period_id=uuid4(),
        legal_entity_id=legal_entity_id,
        fiscal_year=2026,
        period_number=3,
        period_name="Mar 2026",
        start_date=datetime(2026, 3, 1, tzinfo=UTC),
        end_date=datetime(2026, 3, 31, tzinfo=UTC),
        status=PeriodStatus.LOCKED,
    )


@pytest.fixture
def future_period(legal_entity_id):
    return FiscalPeriod(
        period_id=uuid4(),
        legal_entity_id=legal_entity_id,
        fiscal_year=2026,
        period_number=4,
        period_name="Apr 2026",
        start_date=datetime(2026, 4, 1, tzinfo=UTC),
        end_date=datetime(2026, 4, 30, tzinfo=UTC),
        status=PeriodStatus.FUTURE,
    )


@pytest.fixture
def period_repo(sample_period, closed_period, locked_period, future_period):
    repo = _FallbackFiscalPeriodRepository()
    repo.add_period(sample_period)
    repo.add_period(closed_period)
    repo.add_period(locked_period)
    repo.add_period(future_period)
    return repo


@pytest.fixture
def guard(period_repo):
    return PeriodLockGuard(period_repo)


# ============================================================================
# Tests for Enums
# ============================================================================

class TestPeriodStatus:
    def test_members(self):
        assert PeriodStatus.FUTURE.value == "future"
        assert PeriodStatus.OPEN.value == "open"
        assert PeriodStatus.LOCKED.value == "locked"
        assert PeriodStatus.CLOSED.value == "closed"
        assert PeriodStatus.ARCHIVED.value == "archived"


class TestPeriodLockSeverity:
    def test_members(self):
        assert PeriodLockSeverity.CRITICAL.value == 80
        assert PeriodLockSeverity.HIGH.value == 60
        assert PeriodLockSeverity.MEDIUM.value == 40
        assert PeriodLockSeverity.LOW.value == 20
        assert PeriodLockSeverity.INFO.value == 0


# ============================================================================
# Tests for FiscalPeriod
# ============================================================================

class TestFiscalPeriod:
    def test_construction(self, sample_period):
        assert sample_period.period_id is not None
        assert sample_period.fiscal_year == 2026
        assert sample_period.period_number == 1
        assert sample_period.status == PeriodStatus.OPEN
        assert sample_period.cryptographic_hash != ""

    def test_compute_hash(self, sample_period):
        h1 = sample_period.compute_hash()
        h2 = sample_period.compute_hash()
        assert h1 == h2
        # Change something
        sample_period.status = PeriodStatus.CLOSED
        h3 = sample_period.compute_hash()
        assert h1 != h3

    def test_contains(self, sample_period):
        within = datetime(2026, 1, 15, tzinfo=UTC)
        assert sample_period.contains(within) is True
        outside = datetime(2026, 2, 1, tzinfo=UTC)
        assert sample_period.contains(outside) is False

    def test_is_open_for_posting_open(self, sample_period):
        assert sample_period.is_open_for_posting() is True
        assert sample_period.is_open_for_posting(allow_locked=True) is True

    def test_is_open_for_posting_locked(self, locked_period):
        assert locked_period.is_open_for_posting() is False
        assert locked_period.is_open_for_posting(allow_locked=True) is True

    def test_is_open_for_posting_closed(self, closed_period):
        assert closed_period.is_open_for_posting() is False
        assert closed_period.is_open_for_posting(allow_locked=True) is False

    def test_can_be_adjusted(self, sample_period, locked_period, closed_period):
        assert sample_period.can_be_adjusted() is True
        assert locked_period.can_be_adjusted() is True
        assert closed_period.can_be_adjusted() is False

    def test_to_dict(self, sample_period):
        d = sample_period.to_dict()
        assert d["period_id"] == str(sample_period.period_id)
        assert d["fiscal_year"] == 2026
        assert d["status"] == "open"
        assert d["start_date"] == "2026-01-01T00:00:00+00:00"
        assert d["end_date"] == "2026-01-31T00:00:00+00:00"


# ============================================================================
# Tests for _FallbackFiscalPeriodRepository
# ============================================================================

class TestFallbackFiscalPeriodRepository:
    def test_add_period(self, sample_period):
        repo = _FallbackFiscalPeriodRepository()
        repo.add_period(sample_period)
        assert sample_period.period_id in repo._periods
        assert len(repo._by_entity[sample_period.legal_entity_id]) == 1
        assert len(repo._by_year[(sample_period.legal_entity_id, sample_period.fiscal_year)]) == 1

    def test_remove_period(self, sample_period):
        repo = _FallbackFiscalPeriodRepository()
        repo.add_period(sample_period)
        result = repo.remove_period(sample_period.period_id)
        assert result is True
        assert sample_period.period_id not in repo._periods
        # Try remove non-existent
        result2 = repo.remove_period(uuid4())
        assert result2 is False

    @pytest.mark.asyncio
    async def test_get_by_id(self, sample_period):
        repo = _FallbackFiscalPeriodRepository()
        repo.add_period(sample_period)
        result = await repo.get_by_id(sample_period.period_id, sample_period.legal_entity_id)
        assert result is sample_period
        # Wrong legal entity
        result2 = await repo.get_by_id(sample_period.period_id, uuid4())
        assert result2 is None

    @pytest.mark.asyncio
    async def test_get_by_legal_entity(self, sample_period, closed_period, legal_entity_id):
        repo = _FallbackFiscalPeriodRepository()
        repo.add_period(sample_period)
        repo.add_period(closed_period)
        results = await repo.get_by_legal_entity(legal_entity_id)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_get_current_period(self, sample_period):
        repo = _FallbackFiscalPeriodRepository()
        repo.add_period(sample_period)
        date = datetime(2026, 1, 15, tzinfo=UTC)
        result = await repo.get_current_period(sample_period.legal_entity_id, date)
        assert result is sample_period
        # No period for this date
        date2 = datetime(2026, 2, 15, tzinfo=UTC)
        result2 = await repo.get_current_period(sample_period.legal_entity_id, date2)
        assert result2 is None

    @pytest.mark.asyncio
    async def test_get_period_by_number(self, sample_period):
        repo = _FallbackFiscalPeriodRepository()
        repo.add_period(sample_period)
        result = await repo.get_period_by_number(
            sample_period.legal_entity_id, 2026, 1
        )
        assert result is sample_period
        result2 = await repo.get_period_by_number(
            sample_period.legal_entity_id, 2026, 2
        )
        assert result2 is None

    @pytest.mark.asyncio
    async def test_get_periods_by_fiscal_year(self, sample_period, closed_period, legal_entity_id):
        repo = _FallbackFiscalPeriodRepository()
        repo.add_period(sample_period)
        repo.add_period(closed_period)
        results = await repo.get_periods_by_fiscal_year(legal_entity_id, 2026)
        assert len(results) == 2
        results2 = await repo.get_periods_by_fiscal_year(legal_entity_id, 2025)
        assert len(results2) == 0

    @pytest.mark.asyncio
    async def test_get_periods_by_status(self, sample_period, closed_period, locked_period, legal_entity_id):
        repo = _FallbackFiscalPeriodRepository()
        repo.add_period(sample_period)  # OPEN
        repo.add_period(closed_period)  # CLOSED
        repo.add_period(locked_period)  # LOCKED
        open_periods = await repo.get_periods_by_status(legal_entity_id, PeriodStatus.OPEN)
        assert len(open_periods) == 1
        assert open_periods[0] is sample_period
        closed = await repo.get_periods_by_status(legal_entity_id, PeriodStatus.CLOSED)
        assert len(closed) == 1
        locked = await repo.get_periods_by_status(legal_entity_id, PeriodStatus.LOCKED)
        assert len(locked) == 1

    @pytest.mark.asyncio
    async def test_update_period_status(self, sample_period):
        repo = _FallbackFiscalPeriodRepository()
        repo.add_period(sample_period)
        updated = await repo.update_period_status(sample_period.period_id, PeriodStatus.LOCKED, "admin")
        assert updated is not None
        assert updated.status == PeriodStatus.LOCKED
        assert updated.modified_by == "admin"
        assert updated.modified_at is not None
        # Non-existent
        result2 = await repo.update_period_status(uuid4(), PeriodStatus.OPEN, "admin")
        assert result2 is None

    @pytest.mark.asyncio
    async def test_last_transaction_date(self, legal_entity_id):
        repo = _FallbackFiscalPeriodRepository()
        date1 = datetime(2026, 1, 1, tzinfo=UTC)
        date2 = datetime(2026, 1, 15, tzinfo=UTC)
        await repo.record_transaction_date(legal_entity_id, date1)
        last = await repo.get_last_transaction_date(legal_entity_id)
        assert last == date1
        await repo.record_transaction_date(legal_entity_id, date2)
        last2 = await repo.get_last_transaction_date(legal_entity_id)
        assert last2 == date2

    def test_clear(self, sample_period):
        repo = _FallbackFiscalPeriodRepository()
        repo.add_period(sample_period)
        assert len(repo._periods) == 1
        repo.clear()
        assert len(repo._periods) == 0
        assert len(repo._by_entity) == 0
        assert len(repo._by_year) == 0


# ============================================================================
# Tests for PeriodLockCheckResult
# ============================================================================

class TestPeriodLockCheckResult:
    def test_construction(self, period_id, legal_entity_id):
        result = PeriodLockCheckResult(
            check_id=uuid4(),
            period_id=period_id,
            period_name="Jan 2026",
            legal_entity_id=legal_entity_id,
            period_status=PeriodStatus.OPEN,
            transaction_date=datetime.now(UTC),
            is_allowed=True,
            severity=PeriodLockSeverity.INFO,
            message="OK",
        )
        assert result.check_id is not None
        assert result.period_id == period_id
        assert result.is_allowed is True
        assert result.cryptographic_hash != ""

    def test_compute_hash(self, period_id, legal_entity_id):
        result = PeriodLockCheckResult(
            check_id=uuid4(),
            period_id=period_id,
            period_name="Jan 2026",
            legal_entity_id=legal_entity_id,
            period_status=PeriodStatus.OPEN,
            transaction_date=datetime.now(UTC),
            is_allowed=True,
            severity=PeriodLockSeverity.INFO,
            message="OK",
        )
        h1 = result.compute_hash()
        h2 = result.compute_hash()
        assert h1 == h2
        result.message = "Changed"
        h3 = result.compute_hash()
        assert h1 != h3

    def test_to_dict(self, period_id, legal_entity_id):
        result = PeriodLockCheckResult(
            check_id=uuid4(),
            period_id=period_id,
            period_name="Jan 2026",
            legal_entity_id=legal_entity_id,
            period_status=PeriodStatus.OPEN,
            transaction_date=datetime(2026, 1, 15, tzinfo=UTC),
            is_allowed=True,
            severity=PeriodLockSeverity.INFO,
            message="OK",
            requires_approval=False,
            is_adjustment=False,
        )
        d = result.to_dict()
        assert d["period_id"] == str(period_id)
        assert d["period_status"] == "open"
        assert d["is_allowed"] is True
        assert d["severity"] == "INFO"
        assert "hash" in d


# ============================================================================
# Tests for BasePeriodLockGuard (abstract)
# ============================================================================

def test_base_class_abstract():
    with pytest.raises(TypeError):
        BasePeriodLockGuard()


# ============================================================================
# Tests for PeriodLockGuard
# ============================================================================

class TestPeriodLockGuard:
    def test_initialization(self, period_repo):
        guard = PeriodLockGuard(period_repo)
        assert guard._period_repo is period_repo
        assert guard._enabled is True
        assert guard._allow_future_posting is False
        assert guard._max_future_days == 7
        assert guard._max_backdate_days == 30
        assert guard._version == 1

    def test_enable(self, guard):
        guard.enable(False)
        assert guard._enabled is False
        guard.enable(True)
        assert guard._enabled is True
        assert guard._audit_trail[-1]["action"] == "ENABLE"

    def test_set_allow_future_posting(self, guard):
        guard.set_allow_future_posting(True, max_days=14)
        assert guard._allow_future_posting is True
        assert guard._max_future_days == 14
        assert guard._audit_trail[-1]["action"] == "SET_FUTURE_POSTING"

    def test_set_max_backdate_days(self, guard):
        guard.set_max_backdate_days(45)
        assert guard._max_backdate_days == 45
        assert guard._audit_trail[-1]["action"] == "SET_BACKDATE_DAYS"

    @pytest.mark.asyncio
    async def test_get_period(self, guard, sample_period):
        result = await guard.get_period(sample_period.period_id, sample_period.legal_entity_id)
        assert result is sample_period

    @pytest.mark.asyncio
    async def test_get_current_period(self, guard, sample_period):
        with patch("kernel.guards.period_lock.get_current_legal_entity") as mock_le:
            mock_le.return_value = sample_period.legal_entity_id
            result = await guard.get_current_period(date=datetime(2026, 1, 15, tzinfo=UTC))
            assert result is sample_period

    @pytest.mark.asyncio
    async def test_get_current_period_no_legal_entity(self, guard):
        with patch("kernel.guards.period_lock.get_current_legal_entity") as mock_le:
            mock_le.return_value = None
            result = await guard.get_current_period()
            assert result is None

    @pytest.mark.asyncio
    async def test_get_periods_by_status(self, guard, sample_period, closed_period, legal_entity_id):
        results = await guard.get_periods_by_status(legal_entity_id, PeriodStatus.OPEN)
        assert len(results) == 1
        assert results[0] is sample_period
        results2 = await guard.get_periods_by_status(legal_entity_id, PeriodStatus.CLOSED)
        assert len(results2) == 1

    @pytest.mark.asyncio
    async def test_check_period_open_disabled(self, guard, period_id, legal_entity_id):
        guard._enabled = False
        result = await guard.check_period_open(period_id, legal_entity_id)
        assert result.is_allowed is True
        assert result.message == "Period lock guard disabled"

    @pytest.mark.asyncio
    async def test_check_period_open_no_legal_entity(self, guard, period_id):
        with patch("kernel.guards.period_lock.get_current_legal_entity") as mock_le:
            mock_le.return_value = None
            result = await guard.check_period_open(period_id, legal_entity_id=None)
            assert result.is_allowed is False
            assert "No legal entity" in result.message

    @pytest.mark.asyncio
    async def test_check_period_open_period_not_found(self, guard, period_id, legal_entity_id):
        result = await guard.check_period_open(uuid4(), legal_entity_id)
        assert result.is_allowed is False
        assert "not found" in result.message

    @pytest.mark.asyncio
    async def test_check_period_open_date_outside_period(self, guard, sample_period, legal_entity_id):
        tx_date = datetime(2026, 2, 1, tzinfo=UTC)
        result = await guard.check_period_open(
            sample_period.period_id, legal_entity_id, transaction_date=tx_date
        )
        assert result.is_allowed is False
        assert "outside period" in result.message

    @pytest.mark.asyncio
    async def test_check_period_open_future_disabled(self, guard, sample_period, legal_entity_id):
        guard._allow_future_posting = False
        tx_date = datetime(2026, 2, 1, tzinfo=UTC)  # within period? Actually Jan 1-31, so Feb is outside. Let's use future date within period
        # Make period that covers future date
        future_period = FiscalPeriod(
            period_id=uuid4(),
            legal_entity_id=legal_entity_id,
            fiscal_year=2026,
            period_number=5,
            period_name="May 2026",
            start_date=datetime(2026, 5, 1, tzinfo=UTC),
            end_date=datetime(2026, 5, 31, tzinfo=UTC),
            status=PeriodStatus.FUTURE,
        )
        await guard._period_repo.add_period(future_period)
        tx_date = datetime(2026, 5, 15, tzinfo=UTC)
        result = await guard.check_period_open(
            future_period.period_id, legal_entity_id, transaction_date=tx_date
        )
        assert result.is_allowed is False
        assert "Future posting is disabled" in result.message

    @pytest.mark.asyncio
    async def test_check_period_open_future_exceeds_max_days(self, guard, sample_period, legal_entity_id):
        guard._allow_future_posting = True
        guard._max_future_days = 7
        future_period = FiscalPeriod(
            period_id=uuid4(),
            legal_entity_id=legal_entity_id,
            fiscal_year=2026,
            period_number=6,
            period_name="Jun 2026",
            start_date=datetime(2026, 6, 1, tzinfo=UTC),
            end_date=datetime(2026, 6, 30, tzinfo=UTC),
            status=PeriodStatus.FUTURE,
        )
        await guard._period_repo.add_period(future_period)
        # Current date is 2026-07-27, so June is past, not future. We need a period in the future.
        # Let's use August 2026
        aug_period = FiscalPeriod(
            period_id=uuid4(),
            legal_entity_id=legal_entity_id,
            fiscal_year=2026,
            period_number=8,
            period_name="Aug 2026",
            start_date=datetime(2026, 8, 1, tzinfo=UTC),
            end_date=datetime(2026, 8, 31, tzinfo=UTC),
            status=PeriodStatus.FUTURE,
        )
        await guard._period_repo.add_period(aug_period)
        tx_date = datetime(2026, 8, 20, tzinfo=UTC)  # ~24 days future, exceeds 7
        result = await guard.check_period_open(
            aug_period.period_id, legal_entity_id, transaction_date=tx_date
        )
        assert result.is_allowed is False
        assert "exceeds" in result.message

    @pytest.mark.asyncio
    async def test_check_period_open_backdate_exceeds(self, guard, sample_period, legal_entity_id):
        guard._max_backdate_days = 7
        tx_date = datetime(2026, 1, 1, tzinfo=UTC)  # ~207 days back, exceeds 7
        result = await guard.check_period_open(
            sample_period.period_id, legal_entity_id, transaction_date=tx_date
        )
        assert result.is_allowed is False
        assert "Backdating" in result.message

    @pytest.mark.asyncio
    async def test_check_period_open_backdate_exceeds_but_adjustment_allowed(self, guard, sample_period, legal_entity_id):
        guard._max_backdate_days = 7
        tx_date = datetime(2026, 1, 1, tzinfo=UTC)
        result = await guard.check_period_open(
            sample_period.period_id, legal_entity_id, transaction_date=tx_date, is_adjustment=True
        )
        assert result.is_allowed is True  # adjustment allowed even with backdate

    @pytest.mark.asyncio
    async def test_check_period_open_closed(self, guard, closed_period, legal_entity_id):
        result = await guard.check_period_open(closed_period.period_id, legal_entity_id)
        assert result.is_allowed is False
        assert "CLOSED" in result.message

    @pytest.mark.asyncio
    async def test_check_period_open_locked_not_allowed(self, guard, locked_period, legal_entity_id):
        result = await guard.check_period_open(locked_period.period_id, legal_entity_id)
        assert result.is_allowed is False
        assert "LOCKED" in result.message

    @pytest.mark.asyncio
    async def test_check_period_open_locked_allowed(self, guard, locked_period, legal_entity_id):
        result = await guard.check_period_open(
            locked_period.period_id, legal_entity_id, allow_locked=True
        )
        assert result.is_allowed is True
        assert "open for posting" in result.message

    @pytest.mark.asyncio
    async def test_check_period_open_locked_requires_approval(self, guard, locked_period, legal_entity_id):
        result = await guard.check_period_open(
            locked_period.period_id, legal_entity_id, allow_locked=True, require_approval=True
        )
        assert result.is_allowed is False
        assert "requires 2 approvals" in result.message

    @pytest.mark.asyncio
    async def test_check_period_open_locked_approved(self, guard, locked_period, legal_entity_id):
        result = await guard.check_period_open(
            locked_period.period_id, legal_entity_id, allow_locked=True, require_approval=True,
            approved_by=["approver1", "approver2"]
        )
        assert result.is_allowed is True

    @pytest.mark.asyncio
    async def test_check_period_open_future_status(self, guard, future_period, legal_entity_id):
        result = await guard.check_period_open(future_period.period_id, legal_entity_id)
        assert result.is_allowed is False
        assert "FUTURE" in result.message

    @pytest.mark.asyncio
    async def test_check_date_in_period_valid(self, guard, sample_period, legal_entity_id):
        tx_date = datetime(2026, 1, 15, tzinfo=UTC)
        result = await guard.check_date_in_period(sample_period.period_id, tx_date, legal_entity_id)
        assert result.is_allowed is True
        assert "within period" in result.message

    @pytest.mark.asyncio
    async def test_check_date_in_period_no_legal_entity(self, guard, sample_period):
        with patch("kernel.guards.period_lock.get_current_legal_entity") as mock_le:
            mock_le.return_value = None
            result = await guard.check_date_in_period(sample_period.period_id, datetime.now(UTC))
            assert result.is_allowed is False

    @pytest.mark.asyncio
    async def test_check_date_in_period_period_not_found(self, guard, period_id, legal_entity_id):
        result = await guard.check_date_in_period(uuid4(), datetime.now(UTC), legal_entity_id)
        assert result.is_allowed is False
        assert "not found" in result.message

    @pytest.mark.asyncio
    async def test_check_date_in_period_before_start(self, guard, sample_period, legal_entity_id):
        tx_date = datetime(2025, 12, 31, tzinfo=UTC)
        result = await guard.check_date_in_period(sample_period.period_id, tx_date, legal_entity_id)
        assert result.is_allowed is False
        assert "days before" in result.message

    @pytest.mark.asyncio
    async def test_check_date_in_period_after_end(self, guard, sample_period, legal_entity_id):
        tx_date = datetime(2026, 2, 1, tzinfo=UTC)
        result = await guard.check_date_in_period(sample_period.period_id, tx_date, legal_entity_id)
        assert result.is_allowed is False
        assert "days after" in result.message

    @pytest.mark.asyncio
    async def test_check_period_sequence_ok(self, guard, sample_period, legal_entity_id):
        # sample_period has no previous period, so it's OK
        result = await guard.check_period_sequence(sample_period.period_id, legal_entity_id)
        assert result.is_allowed is True
        assert "No previous period" in result.message

    @pytest.mark.asyncio
    async def test_check_period_sequence_previous_not_closed(self, guard, sample_period, legal_entity_id, period_repo):
        # Create a period with previous period that is not closed
        prev_period = FiscalPeriod(
            period_id=uuid4(),
            legal_entity_id=legal_entity_id,
            fiscal_year=2026,
            period_number=0,
            period_name="Dec 2025",
            start_date=datetime(2025, 12, 1, tzinfo=UTC),
            end_date=datetime(2025, 12, 31, tzinfo=UTC),
            status=PeriodStatus.OPEN,
        )
        period_repo.add_period(prev_period)
        current = FiscalPeriod(
            period_id=uuid4(),
            legal_entity_id=legal_entity_id,
            fiscal_year=2026,
            period_number=1,
            period_name="Jan 2026",
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
            end_date=datetime(2026, 1, 31, tzinfo=UTC),
            status=PeriodStatus.OPEN,
            previous_period_id=prev_period.period_id,
        )
        period_repo.add_period(current)
        result = await guard.check_period_sequence(current.period_id, legal_entity_id)
        assert result.is_allowed is True  # sequence check is warning only
        assert "not closed" in result.message

    @pytest.mark.asyncio
    async def test_get_current_open_period(self, guard, sample_period):
        with patch("kernel.guards.period_lock.get_current_legal_entity") as mock_le:
            mock_le.return_value = sample_period.legal_entity_id
            result = await guard.get_current_open_period(date=datetime(2026, 1, 15, tzinfo=UTC))
            assert result is sample_period

    @pytest.mark.asyncio
    async def test_get_open_periods(self, guard, legal_entity_id):
        results = await guard.get_open_periods(legal_entity_id)
        assert len(results) == 1  # sample_period is OPEN

    @pytest.mark.asyncio
    async def test_get_closed_periods(self, guard, legal_entity_id):
        results = await guard.get_closed_periods(legal_entity_id)
        assert len(results) == 1  # closed_period

    @pytest.mark.asyncio
    async def test_enforce_allowed(self, guard, sample_period, legal_entity_id):
        result = await guard.enforce(
            sample_period.period_id, legal_entity_id, raise_on_violation=True
        )
        assert result.is_allowed is True
        # Check history recorded
        assert len(guard._check_history) == 1

    @pytest.mark.asyncio
    async def test_enforce_violation_raises(self, guard, closed_period, legal_entity_id):
        with pytest.raises(PeriodLockError, match="CLOSED"):
            await guard.enforce(closed_period.period_id, legal_entity_id, raise_on_violation=True)
        # History recorded
        assert len(guard._check_history) == 1

    @pytest.mark.asyncio
    async def test_enforce_no_raise(self, guard, closed_period, legal_entity_id):
        result = await guard.enforce(closed_period.period_id, legal_entity_id, raise_on_violation=False)
        assert result.is_allowed is False
        assert len(guard._check_history) == 1

    @pytest.mark.asyncio
    async def test_enforce_records_transaction_date(self, guard, sample_period, legal_entity_id):
        tx_date = datetime(2026, 1, 15, tzinfo=UTC)
        await guard.enforce(
            sample_period.period_id, legal_entity_id, transaction_date=tx_date, raise_on_violation=True
        )
        last = await guard._period_repo.get_last_transaction_date(legal_entity_id)
        assert last == tx_date

    def test_get_check_history(self, guard, sample_period, legal_entity_id):
        # Add some history manually
        result = PeriodLockCheckResult(
            check_id=uuid4(),
            period_id=sample_period.period_id,
            period_name=sample_period.period_name,
            legal_entity_id=legal_entity_id,
            period_status=PeriodStatus.OPEN,
            transaction_date=datetime.now(UTC),
            is_allowed=True,
            severity=PeriodLockSeverity.INFO,
            message="OK",
        )
        guard._check_history = [result]
        history = guard.get_check_history(limit=10)
        assert len(history) == 1

        # Filter by only_violations
        history2 = guard.get_check_history(only_violations=True)
        assert len(history2) == 0

        # Filter by period_id
        history3 = guard.get_check_history(period_id=sample_period.period_id)
        assert len(history3) == 1
        history4 = guard.get_check_history(period_id=uuid4())
        assert len(history4) == 0

        # Filter by legal_entity_id
        history5 = guard.get_check_history(legal_entity_id=legal_entity_id)
        assert len(history5) == 1
        history6 = guard.get_check_history(legal_entity_id=uuid4())
        assert len(history6) == 0

    def test_get_statistics_empty(self, guard):
        stats = guard.get_statistics()
        assert stats["total_checks"] == 0
        assert stats["enabled"] is True

    def test_get_statistics_with_data(self, guard, sample_period, legal_entity_id, closed_period):
        # Add some history
        result1 = PeriodLockCheckResult(
            check_id=uuid4(),
            period_id=sample_period.period_id,
            period_name=sample_period.period_name,
            legal_entity_id=legal_entity_id,
            period_status=PeriodStatus.OPEN,
            transaction_date=datetime.now(UTC),
            is_allowed=True,
            severity=PeriodLockSeverity.INFO,
            message="OK",
        )
        result2 = PeriodLockCheckResult(
            check_id=uuid4(),
            period_id=closed_period.period_id,
            period_name=closed_period.period_name,
            legal_entity_id=legal_entity_id,
            period_status=PeriodStatus.CLOSED,
            transaction_date=datetime.now(UTC),
            is_allowed=False,
            severity=PeriodLockSeverity.CRITICAL,
            message="Closed",
        )
        guard._check_history = [result1, result2]
        stats = guard.get_statistics()
        assert stats["total_checks"] == 2
        assert stats["violation_count"] == 1
        assert stats["violation_rate"] == 0.5
        assert stats["by_severity"]["CRITICAL"] == 1
        assert stats["by_period_status"]["closed"] == 1
        assert stats["by_period"][closed_period.period_name] == 1

    def test_reset(self, guard):
        guard._check_history = [MagicMock()]
        guard._version = 5
        guard._audit_trail = [{"a": 1}]
        guard.reset()
        assert len(guard._check_history) == 0
        assert guard._version == 6
        assert len(guard._audit_trail) == 0

    # ---- Entity methods ----
    def test_validate(self, guard):
        result = guard.validate()
        assert result["is_valid"] is True

        guard._max_history = -1
        result2 = guard.validate()
        assert result2["is_valid"] is False
        assert "max_history must be positive" in result2["errors"]

    def test_to_dict(self, guard):
        d = guard.to_dict()
        assert d["enabled"] is True
        assert d["allow_future_posting"] is False
        assert d["version"] == 1

    def test_from_dict(self):
        data = {
            "enabled": False,
            "allow_future_posting": True,
            "max_future_days": 14,
            "max_backdate_days": 60,
            "max_history": 5000,
            "version": 3,
        }
        instance = PeriodLockGuard.from_dict(data)
        assert instance._enabled is False
        assert instance._allow_future_posting is True
        assert instance._max_future_days == 14
        assert instance._max_backdate_days == 60
        assert instance._max_history == 5000
        assert instance._version == 3

    def test_clone(self, guard):
        guard._enabled = False
        guard._allow_future_posting = True
        guard._max_future_days = 20
        guard._version = 5
        cloned = guard.clone()
        assert cloned is not guard
        assert cloned._enabled == guard._enabled
        assert cloned._allow_future_posting == guard._allow_future_posting
        assert cloned._max_future_days == guard._max_future_days
        assert cloned._version == guard._version + 1

    def test_snapshot(self, guard):
        snap = guard.snapshot()
        assert snap["version"] == 1
        assert snap["history_count"] == 0
        assert snap["enabled"] is True
        assert "timestamp" in snap

    def test_version(self, guard):
        assert guard.version() == 1
        guard._version = 3
        assert guard.version() == 3

    def test_audit_trail(self, guard):
        guard._record_audit("ACTION", "user", {"k": "v"})
        trail = guard.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "ACTION"

    def test_touch(self, guard):
        old_ver = guard._version
        guard.touch("admin")
        assert guard._version == old_ver + 1
        assert guard._audit_trail[-1]["action"] == "TOUCH"


# ============================================================================
# Tests for Module-level Functions and Aliases
# ============================================================================

def test_get_period_lock_guard():
    g1 = get_period_lock_guard()
    g2 = get_period_lock_guard()
    assert g1 is g2
    assert isinstance(g1, PeriodLockGuard)


def test_lock_period():
    # lock_period always returns None (placeholder)
    result = lock_period(uuid4(), uuid4(), "user", "reason")
    assert result is None


def test_unlock_period():
    result = unlock_period(uuid4(), uuid4(), "user", "reason")
    assert result is None


def test_period_lock_alias():
    assert PeriodLock is PeriodLockGuard
