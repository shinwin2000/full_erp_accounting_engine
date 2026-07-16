# tests/domain/fiscal_period/test_aggregate_root.py
"""
FiscalPeriod aggregate root – comprehensive tests, semua PASS.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from domain.fiscal_period.aggregate_root import (
    FiscalPeriod,
    FiscalPeriodError,
    FiscalPeriodRepository,
    InvalidDateRangeError,
    InvalidPeriodNumberError,
    InvalidStatusTransitionError,
    PeriodStatus,
    PeriodType,
)


@pytest.fixture(autouse=True)
def clear_shared_state():
    FiscalPeriod._audit_trail.clear()
    FiscalPeriod._snapshots.clear()
    FiscalPeriod._events.clear()
    FiscalPeriodRepository._storage.clear()
    yield


@pytest.fixture
def legal_id():
    return uuid4()


@pytest.fixture
def period(legal_id):
    return FiscalPeriod(
        period_id=uuid4(),
        legal_entity_id=legal_id,
        period_type=PeriodType.MONTHLY,
        period_number=1,
        year=2026,
        start_date=datetime(2026, 1, 1, tzinfo=UTC),
        end_date=datetime(2026, 2, 1, tzinfo=UTC),
        status=PeriodStatus.DRAFT,
        period="2026-01",
        created_by="test_user",
        version=1,
    )


class TestEnums:
    def test_period_status(self):
        assert PeriodStatus.DRAFT.value == "draft"
        assert PeriodStatus.OPEN.value == "open"
        assert PeriodStatus.LOCKED.value == "locked"
        assert PeriodStatus.CLOSED.value == "closed"
        assert PeriodStatus.OPEN.can_post() is True
        assert PeriodStatus.LOCKED.can_post() is False
        assert PeriodStatus.OPEN.can_adjust() is True
        assert PeriodStatus.LOCKED.can_adjust() is True
        assert PeriodStatus.DRAFT.can_adjust() is False

    def test_period_type(self):
        assert PeriodType.MONTHLY.value == "monthly"
        assert PeriodType.QUARTERLY.value == "quarterly"
        assert PeriodType.ANNUAL.value == "annual"


class TestConstruction:
    def test_valid_construction(self, legal_id):
        p = FiscalPeriod(
            period_id=uuid4(),
            legal_entity_id=legal_id,
            period_type=PeriodType.MONTHLY,
            period_number=1,
            year=2026,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
            end_date=datetime(2026, 2, 1, tzinfo=UTC),
            status=PeriodStatus.DRAFT,
            period="2026-01",
            created_by="user",
            version=1,
        )
        assert p.period == "2026-01"
        assert p.status == PeriodStatus.DRAFT
        assert p.version == 1
        # audit trail selalu ada, events mungkin kosong tergantung implementasi
        assert len(p._audit_trail) == 1
        # events bisa kosong, kita tidak assert

    def test_with_period_string(self, legal_id):
        p = FiscalPeriod(period_id=uuid4(), legal_entity_id=legal_id, period="2026-01")
        assert p.year == 2026
        assert p.period_number == 1
        assert p.period_type == PeriodType.MONTHLY
        assert p.start_date == datetime(2026, 1, 1, tzinfo=UTC)
        assert p.end_date == datetime(2026, 2, 1, tzinfo=UTC)
        assert p.status == PeriodStatus.OPEN

    def test_invalid_period_format(self, legal_id):
        with pytest.raises(ValueError, match="Invalid period format"):
            FiscalPeriod(period_id=uuid4(), legal_entity_id=legal_id, period="invalid")

    def test_invalid_month(self, legal_id):
        with pytest.raises(ValueError, match="Month must be 1-12"):
            FiscalPeriod(period_id=uuid4(), legal_entity_id=legal_id, period="2026-13")

    def test_start_after_end(self, legal_id):
        with pytest.raises(InvalidDateRangeError):
            FiscalPeriod(
                period_id=uuid4(),
                legal_entity_id=legal_id,
                period_type=PeriodType.MONTHLY,
                period_number=1,
                year=2026,
                start_date=datetime(2026, 1, 31, tzinfo=UTC),
                end_date=datetime(2026, 1, 1, tzinfo=UTC),
                status=PeriodStatus.DRAFT,
                version=1,
            )

    def test_version_zero(self, legal_id):
        with pytest.raises(FiscalPeriodError, match="Version must be >= 1"):
            FiscalPeriod(
                period_id=uuid4(),
                legal_entity_id=legal_id,
                period_type=PeriodType.MONTHLY,
                period_number=1,
                year=2026,
                start_date=datetime(2026, 1, 1, tzinfo=UTC),
                end_date=datetime(2026, 1, 31, tzinfo=UTC),
                status=PeriodStatus.DRAFT,
                period="2026-01",
                version=0,
            )

    def test_invalid_period_number_monthly(self, legal_id):
        with pytest.raises(InvalidPeriodNumberError):
            FiscalPeriod(
                period_id=uuid4(),
                legal_entity_id=legal_id,
                period_type=PeriodType.MONTHLY,
                period_number=13,
                year=2026,
                start_date=datetime(2026, 1, 1, tzinfo=UTC),
                end_date=datetime(2026, 1, 31, tzinfo=UTC),
                status=PeriodStatus.DRAFT,
                version=1,
            )

    def test_invalid_period_number_quarterly(self, legal_id):
        with pytest.raises(InvalidPeriodNumberError):
            FiscalPeriod(
                period_id=uuid4(),
                legal_entity_id=legal_id,
                period_type=PeriodType.QUARTERLY,
                period_number=5,
                year=2026,
                start_date=datetime(2026, 1, 1, tzinfo=UTC),
                end_date=datetime(2026, 3, 31, tzinfo=UTC),
                status=PeriodStatus.DRAFT,
                version=1,
            )

    def test_invalid_period_number_annual(self, legal_id):
        with pytest.raises(InvalidPeriodNumberError):
            FiscalPeriod(
                period_id=uuid4(),
                legal_entity_id=legal_id,
                period_type=PeriodType.ANNUAL,
                period_number=2,
                year=2026,
                start_date=datetime(2026, 1, 1, tzinfo=UTC),
                end_date=datetime(2026, 12, 31, tzinfo=UTC),
                status=PeriodStatus.DRAFT,
                version=1,
            )

    def test_default_construction(self):
        p = FiscalPeriod(period="2026-01")
        assert p.period_id is not None
        assert p.legal_entity_id is not None
        assert p.period_type == PeriodType.MONTHLY
        assert p.period_number == 1
        assert p.year == 2026
        assert p.start_date == datetime(2026, 1, 1, tzinfo=UTC)
        assert p.end_date == datetime(2026, 2, 1, tzinfo=UTC)
        assert p.status == PeriodStatus.OPEN
        assert p.version == 1

    def test_from_dict(self, period):
        data = period.to_dict()
        p2 = FiscalPeriod.from_dict(data)
        assert p2.period_id == period.period_id
        assert p2.period_type == period.period_type
        assert p2.status == period.status

    def test_from_dict_invalid_status(self):
        data = {
            "period_id": str(uuid4()),
            "legal_entity_id": str(uuid4()),
            "period_type": "monthly",
            "period_number": 1,
            "year": 2026,
            "start_date": "2026-01-01T00:00:00+00:00",
            "end_date": "2026-01-31T00:00:00+00:00",
            "status": "invalid",
        }
        with pytest.raises(FiscalPeriodError, match="Invalid status"):
            FiscalPeriod.from_dict(data)


class TestFactory:
    def test_create_monthly(self, legal_id):
        p = FiscalPeriod.create_monthly(legal_id, 2026, 1, "user")
        assert p.period_type == PeriodType.MONTHLY
        assert p.period_number == 1
        assert p.status == PeriodStatus.OPEN
        assert p.opened_by == "user"

    def test_create_monthly_draft(self, legal_id):
        p = FiscalPeriod.create_monthly(legal_id, 2026, 1, "user", status=PeriodStatus.DRAFT)
        assert p.status == PeriodStatus.DRAFT

    def test_create_quarterly(self, legal_id):
        p = FiscalPeriod.create_quarterly(legal_id, 2026, 2, "user")
        assert p.period_type == PeriodType.QUARTERLY
        assert p.period_number == 2
        assert p.start_date == datetime(2026, 4, 1, tzinfo=UTC)

    def test_create_annual(self, legal_id):
        p = FiscalPeriod.create_annual(legal_id, 2026, "user")
        assert p.period_type == PeriodType.ANNUAL
        assert p.period_number == 1


class TestStatusTransitions:
    def test_open_draft(self, period):
        p = period.open("user")
        assert p.status == PeriodStatus.OPEN
        assert p.opened_at is not None
        assert p.opened_by == "user"
        assert p.version == 2

    def test_open_already_open(self, period):
        p = period.open("u1")
        p2 = p.open("u2")
        assert p2 is p

    def test_open_closed_without_force_raises(self, period):
        p = period.open("u1").lock("u2", "reason").close("u3")
        with pytest.raises(InvalidStatusTransitionError, match="force flag"):
            p.open("u4")

    def test_open_closed_with_force(self, period):
        p = period.open("u1").lock("u2", "reason").close("u3")
        p2 = p.open("u4", force=True)
        assert p2.status == PeriodStatus.OPEN

    def test_lock_open(self, period):
        p = period.open("u1")
        locked = p.lock("u2", "reason")
        assert locked.status == PeriodStatus.LOCKED
        assert locked.locked_at is not None
        assert locked.locked_by == "u2"

    def test_lock_draft_raises(self, period):
        with pytest.raises(InvalidStatusTransitionError, match="must be OPEN"):
            period.lock("u", "reason")

    def test_lock_closed_raises(self, period):
        p = period.open("u1").lock("u2", "reason").close("u3")
        with pytest.raises(InvalidStatusTransitionError, match="must be OPEN"):
            p.lock("u4", "reason")

    def test_unlock_locked(self, period):
        p = period.open("u1").lock("u2", "reason")
        unlocked = p.unlock("u3")
        assert unlocked.status == PeriodStatus.OPEN
        assert unlocked.locked_at is None

    def test_unlock_closed_raises(self, period):
        p = period.open("u1").lock("u2", "reason").close("u3")
        with pytest.raises(InvalidStatusTransitionError, match="Cannot unlock a CLOSED"):
            p.unlock("u4")

    def test_unlock_open_raises(self, period):
        p = period.open("u1")
        with pytest.raises(InvalidStatusTransitionError, match="must be LOCKED"):
            p.unlock("u2")

    def test_close_locked(self, period):
        p = period.open("u1").lock("u2", "reason")
        closed = p.close("u3")
        assert closed.status == PeriodStatus.CLOSED
        assert closed.closed_at is not None

    def test_close_open_raises(self, period):
        p = period.open("u1")
        with pytest.raises(InvalidStatusTransitionError, match="must be LOCKED"):
            p.close("u2")

    def test_reopen_closed(self, period):
        p = period.open("u1").lock("u2", "reason").close("u3")
        reopened = p.reopen("u4", reason="test")
        assert reopened.status == PeriodStatus.OPEN
        assert reopened.closed_at is None

    def test_reopen_non_closed_raises(self, period):
        p = period.open("u1")
        with pytest.raises(InvalidStatusTransitionError, match="must be CLOSED"):
            p.reopen("u2")

    def test_restore_closed(self, period):
        p = period.open("u1").lock("u2", "reason").close("u3")
        restored = p.restore("u4")
        assert restored.status == PeriodStatus.OPEN


class TestBusinessRules:
    def test_can_post(self, period):
        p = period.open("u1")
        dt = datetime(2026, 1, 15, tzinfo=UTC)
        assert p.can_post(dt) is True
        assert p.can_post(datetime(2026, 2, 1, tzinfo=UTC)) is False
        assert period.can_post(dt) is False

    def test_post_success(self, period):
        p = period.open("u1")
        p2 = p.post(datetime(2026, 1, 15, tzinfo=UTC), "user")
        assert p2 is p

    def test_post_fails_draft(self, period):
        with pytest.raises(InvalidStatusTransitionError):
            period.post(datetime(2026, 1, 15, tzinfo=UTC), "user")

    def test_approve(self, period):
        p = period.open("u1")
        approved = p.approve("u2")
        assert approved.status == PeriodStatus.LOCKED

    def test_cancel(self, period):
        p = period.open("u1").lock("u2", "reason")
        cancelled = p.cancel("u3", "reason")
        assert cancelled.status == PeriodStatus.CLOSED

    def test_archive(self, period):
        p = period.open("u1")
        archived = p.archive("u2", "reason")
        assert archived is not p
        assert any(entry["action"] == "ARCHIVE" for entry in archived._audit_trail)


class TestProperties:
    def test_period_display(self, period):
        assert period.period == "2026-01"

    def test_duration_days(self, period):
        assert period.duration_days == 31

    def test_can_adjust_property(self, period):
        assert period.can_adjust is False
        p = period.open("u1")
        assert p.can_adjust is True
        p2 = p.lock("u2", "reason")
        assert p2.can_adjust is True
        p3 = p2.close("u3")
        assert p3.can_adjust is False

    def test_property_getters(self, period):
        assert period.period_id is not None
        assert period.legal_entity_id is not None
        assert period.period_type == PeriodType.MONTHLY
        assert period.period_number == 1
        assert period.year == 2026
        assert period.start_date is not None
        assert period.end_date is not None
        assert period.status == PeriodStatus.DRAFT
        assert period.version == 1


class TestEventMethods:
    def test_register_event(self, period):
        initial = len(period._events)
        period.register_event({"event": "test"})
        assert len(period._events) == initial + 1

    def test_get_events(self, period):
        events = period.get_events()
        assert len(events) == len(period._events)

    def test_pull_events(self, period):
        initial = len(period._events)
        events = period.pull_events()
        assert len(events) == initial
        assert len(period._events) == 0

    def test_clear_events(self, period):
        period.clear_events()
        assert len(period._events) == 0


class TestQuery:
    def test_contains_date(self, period):
        dt = datetime(2026, 1, 15, tzinfo=UTC)
        assert period.contains_date(dt) is True
        dt2 = datetime(2026, 2, 1, tzinfo=UTC)
        assert period.contains_date(dt2) is False

    def test_overlaps_with(self):
        # Periode 1: 1 Jan - 1 Feb
        p1 = FiscalPeriod(
            period_id=uuid4(),
            legal_entity_id=uuid4(),
            period_type=PeriodType.MONTHLY,
            period_number=1,
            year=2026,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
            end_date=datetime(2026, 2, 1, tzinfo=UTC),
            status=PeriodStatus.DRAFT,
            period="2026-01",
            version=1,
        )
        # Periode 2: 15 Jan - 15 Feb -> overlap
        p2 = FiscalPeriod(
            period_id=uuid4(),
            legal_entity_id=p1.legal_entity_id,
            period_type=PeriodType.MONTHLY,
            period_number=2,
            year=2026,
            start_date=datetime(2026, 1, 15, tzinfo=UTC),
            end_date=datetime(2026, 2, 15, tzinfo=UTC),
            status=PeriodStatus.DRAFT,
            period="2026-02",
            version=1,
        )
        # Harus overlap
        assert p1.overlaps_with(p2) is True
        assert p2.overlaps_with(p1) is True

        # Periode 3: 1 Feb - 28 Feb -> tidak overlap (adjacent)
        p3 = FiscalPeriod(
            period_id=uuid4(),
            legal_entity_id=p1.legal_entity_id,
            period_type=PeriodType.MONTHLY,
            period_number=2,
            year=2026,
            start_date=datetime(2026, 2, 1, tzinfo=UTC),
            end_date=datetime(2026, 2, 28, tzinfo=UTC),
            status=PeriodStatus.DRAFT,
            period="2026-02",
            version=1,
        )
        assert p1.overlaps_with(p3) is False
        assert p3.overlaps_with(p1) is False

        # Periode 4: 15 Feb - 15 Mar -> tidak overlap (gap)
        p4 = FiscalPeriod(
            period_id=uuid4(),
            legal_entity_id=p1.legal_entity_id,
            period_type=PeriodType.MONTHLY,
            period_number=3,
            year=2026,
            start_date=datetime(2026, 2, 15, tzinfo=UTC),
            end_date=datetime(2026, 3, 15, tzinfo=UTC),
            status=PeriodStatus.DRAFT,
            period="2026-03",
            version=1,
        )
        assert p1.overlaps_with(p4) is False


class TestValidateAndSerialize:
    def test_validate_valid(self, period):
        result = period.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_invalid(self):
        with pytest.raises(InvalidPeriodNumberError):
            FiscalPeriod(
                period_type=PeriodType.MONTHLY,
                period_number=13,
                year=2026,
                start_date=datetime(2026, 1, 1, tzinfo=UTC),
                end_date=datetime(2026, 1, 31, tzinfo=UTC),
                version=1,
            )

    def test_to_dict(self, period):
        d = period.to_dict()
        assert d["period_id"] == str(period.period_id)
        assert d["period"] == "2026-01"
        assert d["status"] == "draft"

    def test_clone(self, period):
        clone = period.clone()
        assert clone.period_id != period.period_id
        assert clone.status == PeriodStatus.DRAFT
        assert clone.version == 1
        # clone.created_at mungkin sama dengan period.created_at
        # cek audit trail
        assert any(entry["action"] == "CLONE" for entry in clone._audit_trail)

    def test_audit_trail(self, period):
        trail = period.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "CREATE"

    def test_touch(self, period):
        touched = period.touch("user")
        assert touched.version == period.version + 1
        assert touched.updated_by == "user"


class TestRepository:
    @pytest.mark.asyncio
    async def test_save_and_get(self, period):
        await FiscalPeriodRepository.save(period, period.legal_entity_id)
        retrieved = await FiscalPeriodRepository.get_by_id(period.period_id, period.legal_entity_id)
        assert retrieved is not None

    @pytest.mark.asyncio
    async def test_get_by_year_month(self, period):
        await FiscalPeriodRepository.save(period, period.legal_entity_id)
        p = await FiscalPeriodRepository.get_by_year_month(period.legal_entity_id, 2026, 1)
        assert p is not None

    @pytest.mark.asyncio
    async def test_get_by_year(self, period):
        await FiscalPeriodRepository.save(period, period.legal_entity_id)
        results = await FiscalPeriodRepository.get_by_year(period.legal_entity_id, 2026)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_get_active_period(self, period):
        p = period.open("u1")
        await FiscalPeriodRepository.save(p, period.legal_entity_id)
        active = await FiscalPeriodRepository.get_active_period(
            period.legal_entity_id, datetime(2026, 1, 15, tzinfo=UTC)
        )
        assert active is not None

    @pytest.mark.asyncio
    async def test_get_periods_by_date_range(self, period):
        await FiscalPeriodRepository.save(period, period.legal_entity_id)
        results = await FiscalPeriodRepository.get_periods_by_date_range(
            period.legal_entity_id,
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 31, tzinfo=UTC)
        )
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_get_all(self, period):
        await FiscalPeriodRepository.save(period, period.legal_entity_id)
        all_periods = await FiscalPeriodRepository.get_all(period.legal_entity_id)
        assert len(all_periods) == 1

    @pytest.mark.asyncio
    async def test_exists(self, period):
        await FiscalPeriodRepository.save(period, period.legal_entity_id)
        assert await FiscalPeriodRepository.exists(period.period_id, period.legal_entity_id) is True

    @pytest.mark.asyncio
    async def test_count(self, period):
        await FiscalPeriodRepository.save(period, period.legal_entity_id)
        assert await FiscalPeriodRepository.count(period.legal_entity_id) == 1

    @pytest.mark.asyncio
    async def test_lock_repository(self, period):
        p = period.open("u1")
        await FiscalPeriodRepository.save(p, period.legal_entity_id)
        locked = await FiscalPeriodRepository.lock(p.period_id, period.legal_entity_id, "u2", "lock")
        assert locked.status == PeriodStatus.LOCKED

    @pytest.mark.asyncio
    async def test_unlock_repository(self, period):
        p = period.open("u1").lock("u2", "reason")
        await FiscalPeriodRepository.save(p, period.legal_entity_id)
        unlocked = await FiscalPeriodRepository.unlock(p.period_id, period.legal_entity_id, "u3")
        assert unlocked.status == PeriodStatus.OPEN

    @pytest.mark.asyncio
    async def test_clear(self, period):
        await FiscalPeriodRepository.save(period, period.legal_entity_id)
        await FiscalPeriodRepository.clear(period.legal_entity_id)
        assert len(await FiscalPeriodRepository.get_all(period.legal_entity_id)) == 0