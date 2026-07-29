# tests/application/service_layer/test_service_fiscal_period.py
"""
Comprehensive tests for application/service_layer/service_fiscal_period.py
Menggunakan MagicMock untuk FiscalPeriod dan event classes.
"""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from application.service_layer.service_fiscal_period import (
    ClosePeriodRequest,
    CreatePeriodRequest,
    FiscalPeriodService,
    FiscalPeriodServiceError,
    LockPeriodRequest,
    PeriodAlreadyClosedError,
    PeriodAlreadyExistsError,
    PeriodAlreadyOpenError,
    PeriodNotFoundError,
    PeriodOverlapError,
    PeriodResponse,
    ReopenPeriodRequest,
    UpdatePeriodRequest,
    audit,
    build_fiscal_period_service,
)
from domain.fiscal_period.aggregate_root import PeriodStatus, PeriodType

# ============================================================================
# Helper untuk membuat MagicMock FiscalPeriod
# ============================================================================

def create_mock_period(
    period_id=None,
    legal_entity_id=None,
    year=2026,
    month=1,
    status=PeriodStatus.OPEN,
    start_date=date(2026, 1, 1),
    end_date=date(2026, 1, 31),
    version=1,
    **kwargs,
):
    """Buat MagicMock yang mensimulasikan FiscalPeriod."""
    mock = MagicMock()
    mock.period_id = period_id or uuid4()
    mock.legal_entity_id = legal_entity_id or uuid4()
    mock.year = year
    mock.period_number = month
    mock.status = status
    mock.start_date = start_date
    mock.end_date = end_date
    mock.version = version
    mock.period_type = PeriodType.MONTHLY
    mock.created_by = "system"
    mock.created_at = datetime.now(UTC)

    def open_mock(opened_by):
        new_mock = create_mock_period(
            period_id=mock.period_id,
            legal_entity_id=mock.legal_entity_id,
            year=mock.year,
            month=mock.period_number,
            status=PeriodStatus.OPEN,
            start_date=mock.start_date,
            end_date=mock.end_date,
            version=mock.version + 1,
        )
        new_mock.updated_by = opened_by
        return new_mock

    def close_mock(closed_by):
        new_mock = create_mock_period(
            period_id=mock.period_id,
            legal_entity_id=mock.legal_entity_id,
            year=mock.year,
            month=mock.period_number,
            status=PeriodStatus.CLOSED,
            start_date=mock.start_date,
            end_date=mock.end_date,
            version=mock.version + 1,
        )
        new_mock.closed_at = datetime.now(UTC)
        new_mock.closed_by = closed_by
        return new_mock

    def lock_mock(locked_by, reason="default"):
        new_mock = create_mock_period(
            period_id=mock.period_id,
            legal_entity_id=mock.legal_entity_id,
            year=mock.year,
            month=mock.period_number,
            status=PeriodStatus.LOCKED,
            start_date=mock.start_date,
            end_date=mock.end_date,
            version=mock.version + 1,
        )
        new_mock.updated_by = locked_by
        return new_mock

    mock.open = MagicMock(side_effect=open_mock)
    mock.close = MagicMock(side_effect=close_mock)
    mock.lock = MagicMock(side_effect=lock_mock)
    mock.updated_at = None
    mock.updated_by = None
    return mock


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_period():
    return create_mock_period()


@pytest.fixture
def sample_closed_period():
    return create_mock_period(status=PeriodStatus.CLOSED)


@pytest.fixture
def sample_locked_period():
    return create_mock_period(status=PeriodStatus.LOCKED)


@pytest.fixture
def mock_repo():
    repo = AsyncMock()
    repo.get_by_year_month = AsyncMock(return_value=None)
    repo.get_by_id = AsyncMock(return_value=None)
    repo.list_by_year = AsyncMock(return_value=[])
    repo.list_by_legal_entity = AsyncMock(return_value=[])
    repo.find_overlapping = AsyncMock(return_value=[])
    repo.save = AsyncMock()
    return repo


@pytest.fixture
def mock_uow():
    uow = AsyncMock()
    uow.commit = AsyncMock()
    return uow


@pytest.fixture
def mock_event_publisher():
    publisher = AsyncMock()
    publisher.publish = AsyncMock()
    return publisher


@pytest.fixture
def service(mock_repo, mock_uow, mock_event_publisher):
    return FiscalPeriodService(
        period_repo=mock_repo,
        uow=mock_uow,
        event_publisher=mock_event_publisher,
    )


# ============================================================================
# DTO Tests
# ============================================================================

class TestDTOs:
    def test_create_period_request(self):
        req = CreatePeriodRequest(
            legal_entity_id=uuid4(),
            year=2026,
            month=1,
            period_type="monthly",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            created_by=uuid4(),
        )
        assert req.year == 2026

    def test_update_period_request(self):
        req = UpdatePeriodRequest(
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 28),
            period_type="quarterly",
        )
        assert req.period_type == "quarterly"

    def test_period_response(self):
        resp = PeriodResponse(
            period_id=uuid4(),
            legal_entity_id=uuid4(),
            period_type="monthly",
            period_number=1,
            year=2026,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            status="OPEN",
            created_by="system",
            created_at=datetime.now(UTC),
            closed_at=None,
            closed_by=None,
        )
        assert resp.status == "OPEN"

    def test_close_period_request(self):
        req = ClosePeriodRequest(
            legal_entity_id=uuid4(),
            year=2026,
            month=1,
            closed_by=uuid4(),
            closed_at=datetime.now(UTC),
        )
        assert req.month == 1

    def test_lock_period_request(self):
        req = LockPeriodRequest(
            legal_entity_id=uuid4(),
            year=2026,
            month=1,
            locked_by=uuid4(),
        )
        assert req.locked_by is not None

    def test_reopen_period_request(self):
        req = ReopenPeriodRequest(
            legal_entity_id=uuid4(),
            year=2026,
            month=1,
            reopened_by=uuid4(),
            reason="Correction needed",
        )
        assert req.reason == "Correction needed"


# ============================================================================
# Exception Tests
# ============================================================================

class TestExceptions:
    def test_fiscal_period_service_error(self):
        with pytest.raises(FiscalPeriodServiceError):
            raise FiscalPeriodServiceError("test")

    def test_period_not_found_error(self):
        with pytest.raises(PeriodNotFoundError):
            raise PeriodNotFoundError("not found")

    def test_period_already_exists_error(self):
        with pytest.raises(PeriodAlreadyExistsError):
            raise PeriodAlreadyExistsError("exists")

    def test_period_already_closed_error(self):
        with pytest.raises(PeriodAlreadyClosedError):
            raise PeriodAlreadyClosedError("closed")

    def test_period_already_open_error(self):
        with pytest.raises(PeriodAlreadyOpenError):
            raise PeriodAlreadyOpenError("open")

    def test_period_overlap_error(self):
        with pytest.raises(PeriodOverlapError):
            raise PeriodOverlapError("overlap")


# ============================================================================
# FiscalPeriodService Tests
# ============================================================================

class TestFiscalPeriodService:
    # ---- Construction ----
    def test_construction_requires_repo(self):
        with pytest.raises(ValueError, match="period_repo is required"):
            FiscalPeriodService(period_repo=None, uow=MagicMock())

    def test_construction_requires_uow(self):
        with pytest.raises(ValueError, match="uow is required"):
            FiscalPeriodService(period_repo=MagicMock(), uow=None)

    def test_construction_sets_stats(self, service):
        assert service._stats["periods_created"] == 0
        assert service._stats["periods_closed"] == 0
        assert service._stats["periods_locked"] == 0
        assert service._stats["periods_reopened"] == 0
        assert service._stats["periods_updated"] == 0

    # ---- get_period ----
    @pytest.mark.asyncio
    async def test_get_period_found(self, service, mock_repo, sample_period):
        mock_repo.get_by_year_month.return_value = sample_period
        period = await service.get_period(sample_period.legal_entity_id, 2026, 1)
        assert period is sample_period
        mock_repo.get_by_year_month.assert_called_once_with(
            sample_period.legal_entity_id, 2026, 1
        )

    @pytest.mark.asyncio
    async def test_get_period_not_found(self, service, mock_repo):
        mock_repo.get_by_year_month.return_value = None
        period = await service.get_period(uuid4(), 2026, 1)
        assert period is None

    # ---- get_period_by_id ----
    @pytest.mark.asyncio
    async def test_get_period_by_id_found(self, service, mock_repo, sample_period):
        mock_repo.get_by_id.return_value = sample_period
        period = await service.get_period_by_id(sample_period.period_id)
        assert period is sample_period
        mock_repo.get_by_id.assert_called_once_with(sample_period.period_id)

    @pytest.mark.asyncio
    async def test_get_period_by_id_not_found(self, service, mock_repo):
        mock_repo.get_by_id.return_value = None
        period = await service.get_period_by_id(uuid4())
        assert period is None

    # ---- get_current_period ----
    @pytest.mark.asyncio
    async def test_get_current_period_found(self, service, mock_repo, sample_period):
        mock_repo.list_by_year.return_value = [sample_period]
        result = await service.get_current_period(
            sample_period.legal_entity_id, as_of_date=date(2026, 1, 15)
        )
        assert result is sample_period

    @pytest.mark.asyncio
    async def test_get_current_period_not_found(self, service, mock_repo):
        mock_repo.list_by_year.return_value = []
        result = await service.get_current_period(uuid4(), as_of_date=date(2026, 1, 15))
        assert result is None

    # ---- create_period ----
    @pytest.mark.asyncio
    async def test_create_period_success(self, service, mock_repo, mock_uow, mock_event_publisher):
        req = CreatePeriodRequest(
            legal_entity_id=uuid4(),
            year=2026,
            month=1,
            period_type="monthly",
            created_by=uuid4(),
        )
        mock_repo.get_by_year_month.return_value = None
        mock_repo.find_overlapping.return_value = []

        with patch('application.service_layer.service_fiscal_period.FiscalPeriod') as mock_fiscal_period_cls:
            mock_period = create_mock_period()
            mock_fiscal_period_cls.return_value = mock_period
            # Patch event classes agar tidak error karena keyword period_id
            with patch('application.service_layer.service_fiscal_period.PeriodOpenedEvent', MagicMock()):
                with patch('application.service_layer.service_fiscal_period.PeriodStatusChangedEvent', MagicMock()):
                    period = await service.create_period(req)
                    assert period is mock_period
                    mock_repo.save.assert_called_once_with(mock_period)
                    mock_uow.commit.assert_called_once()
                    # event publisher dipanggil satu kali (PeriodOpenedEvent)
                    assert mock_event_publisher.publish.call_count == 1
                    assert service._stats["periods_created"] == 1

    @pytest.mark.asyncio
    async def test_create_period_already_exists(self, service, mock_repo, sample_period):
        req = CreatePeriodRequest(
            legal_entity_id=sample_period.legal_entity_id,
            year=2026,
            month=1,
            period_type="monthly",
        )
        mock_repo.get_by_year_month.return_value = sample_period
        with pytest.raises(PeriodAlreadyExistsError):
            await service.create_period(req)

    @pytest.mark.asyncio
    async def test_create_period_overlap(self, service, mock_repo, sample_period):
        req = CreatePeriodRequest(
            legal_entity_id=uuid4(),
            year=2026,
            month=2,
            period_type="monthly",
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 28),
        )
        mock_repo.get_by_year_month.return_value = None
        mock_repo.find_overlapping.return_value = [sample_period]
        with pytest.raises(PeriodOverlapError):
            await service.create_period(req)

    @pytest.mark.asyncio
    async def test_create_period_ignores_closed_overlap(self, service, mock_repo):
        req = CreatePeriodRequest(
            legal_entity_id=uuid4(),
            year=2026,
            month=2,
            period_type="monthly",
        )
        mock_repo.get_by_year_month.return_value = None
        closed_period = create_mock_period(status=PeriodStatus.CLOSED)
        mock_repo.find_overlapping.return_value = [closed_period]
        with patch('application.service_layer.service_fiscal_period.FiscalPeriod') as mock_fiscal_period_cls:
            mock_period = create_mock_period()
            mock_fiscal_period_cls.return_value = mock_period
            with patch('application.service_layer.service_fiscal_period.PeriodOpenedEvent', MagicMock()):
                period = await service.create_period(req)
                assert period is mock_period

    # ---- update_period ----
    @pytest.mark.asyncio
    async def test_update_period_success(self, service, mock_repo, mock_uow, mock_event_publisher, sample_period):
        mock_repo.get_by_year_month.return_value = sample_period
        mock_repo.find_overlapping.return_value = []
        req = UpdatePeriodRequest(
            start_date=date(2026, 1, 15),
            end_date=date(2026, 2, 15),
            period_type="quarterly",
        )
        updated_by = uuid4()
        initial_version = sample_period.version

        with patch('application.service_layer.service_fiscal_period.PeriodUpdatedEvent', MagicMock()):
            updated = await service.update_period(
                sample_period.legal_entity_id, 2026, 1, req, updated_by
            )
            assert updated.start_date == date(2026, 1, 15)
            assert updated.end_date == date(2026, 2, 15)
            assert updated.period_type == PeriodType.QUARTERLY
            assert updated.version == initial_version + 1
            assert updated.updated_by == str(updated_by)
            mock_repo.save.assert_called_once()
            mock_uow.commit.assert_called_once()
            mock_event_publisher.publish.assert_called_once()
            assert service._stats["periods_updated"] == 1

    @pytest.mark.asyncio
    async def test_update_period_not_found(self, service, mock_repo):
        mock_repo.get_by_year_month.return_value = None
        req = UpdatePeriodRequest()
        with pytest.raises(PeriodNotFoundError):
            await service.update_period(uuid4(), 2026, 1, req, uuid4())

    @pytest.mark.asyncio
    async def test_update_period_not_open(self, service, mock_repo, sample_closed_period):
        mock_repo.get_by_year_month.return_value = sample_closed_period
        req = UpdatePeriodRequest(start_date=date(2026, 1, 15))
        with pytest.raises(FiscalPeriodServiceError, match="Cannot update period"):
            await service.update_period(
                sample_closed_period.legal_entity_id, 2026, 1, req, uuid4()
            )

    @pytest.mark.asyncio
    async def test_update_period_overlap(self, service, mock_repo, sample_period):
        mock_repo.get_by_year_month.return_value = sample_period
        other = create_mock_period()
        other.period_id = uuid4()
        other.start_date = date(2026, 1, 10)
        other.end_date = date(2026, 1, 20)
        mock_repo.find_overlapping.return_value = [other]
        req = UpdatePeriodRequest(start_date=date(2026, 1, 5))
        with pytest.raises(PeriodOverlapError):
            await service.update_period(
                sample_period.legal_entity_id, 2026, 1, req, uuid4()
            )

    @pytest.mark.asyncio
    async def test_update_period_no_changes(self, service, mock_repo, sample_period):
        mock_repo.get_by_year_month.return_value = sample_period
        req = UpdatePeriodRequest()
        result = await service.update_period(
            sample_period.legal_entity_id, 2026, 1, req, uuid4()
        )
        assert result is sample_period
        mock_repo.save.assert_not_called()

    # ---- open_period ----
    @pytest.mark.asyncio
    async def test_open_period_success(self, service, mock_repo, mock_uow, mock_event_publisher, sample_closed_period):
        mock_repo.get_by_year_month.return_value = sample_closed_period
        mock_repo.find_overlapping.return_value = []
        opened_by = uuid4()

        with patch('application.service_layer.service_fiscal_period.PeriodOpenedEvent', MagicMock()):
            with patch('application.service_layer.service_fiscal_period.PeriodStatusChangedEvent', MagicMock()):
                result = await service.open_period(
                    sample_closed_period.legal_entity_id, 2026, 1, opened_by
                )
                assert result.status == PeriodStatus.OPEN
                assert result.version == sample_closed_period.version + 1
                assert result.updated_by == str(opened_by)
                mock_repo.save.assert_called_once()
                mock_uow.commit.assert_called_once()
                assert mock_event_publisher.publish.call_count == 2

    @pytest.mark.asyncio
    async def test_open_period_not_found(self, service, mock_repo):
        mock_repo.get_by_year_month.return_value = None
        with pytest.raises(PeriodNotFoundError):
            await service.open_period(uuid4(), 2026, 1, uuid4())

    @pytest.mark.asyncio
    async def test_open_period_already_open(self, service, mock_repo, sample_period):
        mock_repo.get_by_year_month.return_value = sample_period
        with pytest.raises(PeriodAlreadyOpenError):
            await service.open_period(
                sample_period.legal_entity_id, 2026, 1, uuid4()
            )

    @pytest.mark.asyncio
    async def test_open_period_overlap(self, service, mock_repo, sample_closed_period):
        mock_repo.get_by_year_month.return_value = sample_closed_period
        other = create_mock_period()
        other.period_id = uuid4()
        mock_repo.find_overlapping.return_value = [other]
        with pytest.raises(PeriodOverlapError):
            await service.open_period(
                sample_closed_period.legal_entity_id, 2026, 1, uuid4()
            )

    # ---- lock_period ----
    @pytest.mark.asyncio
    async def test_lock_period_success(self, service, mock_repo, mock_uow, mock_event_publisher, sample_period):
        mock_repo.get_by_year_month.return_value = sample_period
        locked_by = uuid4()

        with patch('application.service_layer.service_fiscal_period.PeriodLockedEvent', MagicMock()):
            with patch('application.service_layer.service_fiscal_period.PeriodStatusChangedEvent', MagicMock()):
                result = await service.lock_period(
                    sample_period.legal_entity_id, 2026, 1, locked_by
                )
                assert result.status == PeriodStatus.LOCKED
                assert result.version == sample_period.version + 1
                assert result.updated_by == str(locked_by)
                mock_repo.save.assert_called_once()
                mock_uow.commit.assert_called_once()
                assert mock_event_publisher.publish.call_count == 2
                assert service._stats["periods_locked"] == 1

    @pytest.mark.asyncio
    async def test_lock_period_not_found(self, service, mock_repo):
        mock_repo.get_by_year_month.return_value = None
        with pytest.raises(PeriodNotFoundError):
            await service.lock_period(uuid4(), 2026, 1, uuid4())

    @pytest.mark.asyncio
    async def test_lock_period_not_open(self, service, mock_repo, sample_closed_period):
        mock_repo.get_by_year_month.return_value = sample_closed_period
        with pytest.raises(FiscalPeriodServiceError, match="Cannot lock period"):
            await service.lock_period(
                sample_closed_period.legal_entity_id, 2026, 1, uuid4()
            )

    # ---- close_period ----
    @pytest.mark.asyncio
    async def test_close_period_from_open(self, service, mock_repo, mock_uow, mock_event_publisher, sample_period):
        mock_repo.get_by_year_month.return_value = sample_period
        with patch.object(service, 'lock_period', AsyncMock(return_value=sample_period)):
            closed_period = create_mock_period(status=PeriodStatus.CLOSED)
            sample_period.close.return_value = closed_period
            with patch('application.service_layer.service_fiscal_period.PeriodClosedEvent', MagicMock()):
                with patch('application.service_layer.service_fiscal_period.PeriodStatusChangedEvent', MagicMock()):
                    req = ClosePeriodRequest(
                        legal_entity_id=sample_period.legal_entity_id,
                        year=2026,
                        month=1,
                        closed_by=uuid4(),
                    )
                    result = await service.close_period(req)
                    assert result.status == PeriodStatus.CLOSED
                    assert result.version == sample_period.version + 1
                    mock_repo.save.assert_called()
                    mock_uow.commit.assert_called()
                    assert mock_event_publisher.publish.call_count >= 2
                    assert service._stats["periods_closed"] == 1

    @pytest.mark.asyncio
    async def test_close_period_from_locked(self, service, mock_repo, sample_locked_period):
        mock_repo.get_by_year_month.return_value = sample_locked_period
        closed_period = create_mock_period(status=PeriodStatus.CLOSED)
        sample_locked_period.close.return_value = closed_period
        with patch('application.service_layer.service_fiscal_period.PeriodClosedEvent', MagicMock()):
            with patch('application.service_layer.service_fiscal_period.PeriodStatusChangedEvent', MagicMock()):
                req = ClosePeriodRequest(
                    legal_entity_id=sample_locked_period.legal_entity_id,
                    year=2026,
                    month=1,
                    closed_by=uuid4(),
                )
                result = await service.close_period(req)
                assert result.status == PeriodStatus.CLOSED

    @pytest.mark.asyncio
    async def test_close_period_already_closed(self, service, mock_repo, sample_closed_period):
        mock_repo.get_by_year_month.return_value = sample_closed_period
        req = ClosePeriodRequest(
            legal_entity_id=sample_closed_period.legal_entity_id,
            year=2026,
            month=1,
            closed_by=uuid4(),
        )
        with pytest.raises(PeriodAlreadyClosedError):
            await service.close_period(req)

    @pytest.mark.asyncio
    async def test_close_period_not_found(self, service, mock_repo):
        mock_repo.get_by_year_month.return_value = None
        req = ClosePeriodRequest(legal_entity_id=uuid4(), year=2026, month=1, closed_by=uuid4())
        with pytest.raises(PeriodNotFoundError):
            await service.close_period(req)

    # ---- reopen_period ----
    @pytest.mark.asyncio
    async def test_reopen_period_success(self, service, mock_repo, mock_uow, mock_event_publisher, sample_closed_period):
        mock_repo.get_by_year_month.return_value = sample_closed_period
        mock_repo.find_overlapping.return_value = []
        req = ReopenPeriodRequest(
            legal_entity_id=sample_closed_period.legal_entity_id,
            year=2026,
            month=1,
            reopened_by=uuid4(),
            reason="Correct",
        )
        with patch('application.service_layer.service_fiscal_period.PeriodReopenedEvent', MagicMock()):
            with patch('application.service_layer.service_fiscal_period.PeriodStatusChangedEvent', MagicMock()):
                result = await service.reopen_period(req)
                assert result.status == PeriodStatus.OPEN
                assert result.version == sample_closed_period.version + 1
                assert result.updated_by == str(req.reopened_by)
                mock_repo.save.assert_called_once()
                mock_uow.commit.assert_called_once()
                assert mock_event_publisher.publish.call_count == 2
                assert service._stats["periods_reopened"] == 1

    @pytest.mark.asyncio
    async def test_reopen_period_not_found(self, service, mock_repo):
        mock_repo.get_by_year_month.return_value = None
        req = ReopenPeriodRequest(legal_entity_id=uuid4(), year=2026, month=1, reopened_by=uuid4())
        with pytest.raises(PeriodNotFoundError):
            await service.reopen_period(req)

    @pytest.mark.asyncio
    async def test_reopen_period_already_open(self, service, mock_repo, sample_period):
        mock_repo.get_by_year_month.return_value = sample_period
        req = ReopenPeriodRequest(
            legal_entity_id=sample_period.legal_entity_id,
            year=2026,
            month=1,
            reopened_by=uuid4(),
        )
        with pytest.raises(PeriodAlreadyOpenError):
            await service.reopen_period(req)

    @pytest.mark.asyncio
    async def test_reopen_period_not_closed(self, service, mock_repo, sample_locked_period):
        mock_repo.get_by_year_month.return_value = sample_locked_period
        req = ReopenPeriodRequest(
            legal_entity_id=sample_locked_period.legal_entity_id,
            year=2026,
            month=1,
            reopened_by=uuid4(),
        )
        with pytest.raises(FiscalPeriodServiceError, match="Must be CLOSED"):
            await service.reopen_period(req)

    @pytest.mark.asyncio
    async def test_reopen_period_overlap(self, service, mock_repo, sample_closed_period):
        mock_repo.get_by_year_month.return_value = sample_closed_period
        other = create_mock_period()
        other.period_id = uuid4()
        mock_repo.find_overlapping.return_value = [other]
        req = ReopenPeriodRequest(
            legal_entity_id=sample_closed_period.legal_entity_id,
            year=2026,
            month=1,
            reopened_by=uuid4(),
        )
        with pytest.raises(PeriodOverlapError):
            await service.reopen_period(req)

    # ---- validate_period_for_posting ----
    @pytest.mark.asyncio
    async def test_validate_period_for_posting_true(self, service, mock_repo, sample_period):
        mock_repo.list_by_year.return_value = [sample_period]
        result = await service.validate_period_for_posting(
            sample_period.legal_entity_id, date(2026, 1, 15)
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_period_for_posting_false_no_period(self, service, mock_repo):
        mock_repo.list_by_year.return_value = []
        result = await service.validate_period_for_posting(uuid4(), date.today())
        assert result is False

    @pytest.mark.asyncio
    async def test_validate_period_for_posting_false_closed(self, service, mock_repo, sample_closed_period):
        mock_repo.list_by_year.return_value = [sample_closed_period]
        result = await service.validate_period_for_posting(
            sample_closed_period.legal_entity_id, date(2026, 1, 15)
        )
        assert result is False

    # ---- list_periods ----
    @pytest.mark.asyncio
    async def test_list_periods(self, service, mock_repo, sample_period):
        mock_repo.list_by_legal_entity.return_value = [sample_period]
        result = await service.list_periods(sample_period.legal_entity_id)
        assert len(result) == 1
        assert result[0] is sample_period

    # ---- get_periods_by_year ----
    @pytest.mark.asyncio
    async def test_get_periods_by_year(self, service, mock_repo, sample_period):
        mock_repo.list_by_year.return_value = [sample_period]
        result = await service.get_periods_by_year(sample_period.legal_entity_id, 2026)
        assert len(result) == 1

    # ---- get_next_period ----
    @pytest.mark.asyncio
    async def test_get_next_period(self, service, mock_repo, sample_period):
        mock_repo.get_by_year_month.return_value = sample_period
        result = await service.get_next_period(sample_period.legal_entity_id, 2026, 2)
        assert result is sample_period

    # ---- get_previous_period ----
    @pytest.mark.asyncio
    async def test_get_previous_period(self, service, mock_repo, sample_period):
        mock_repo.get_by_year_month.return_value = sample_period
        result = await service.get_previous_period(sample_period.legal_entity_id, 2026, 1)
        assert result is sample_period

    # ---- _to_response ----
    def test_to_response(self, service, sample_period):
        response = service._to_response(sample_period)
        assert isinstance(response, PeriodResponse)
        assert response.period_id == sample_period.period_id
        assert response.status == "open"

    # ---- get_stats ----
    def test_get_stats(self, service):
        stats = service.get_stats()
        assert stats["periods_created"] == 0
        service._stats["periods_created"] = 5
        stats2 = service.get_stats()
        assert stats2["periods_created"] == 5

    # ---- get_audit_trail ----
    def test_get_audit_trail(self, service):
        trail = service.get_audit_trail()
        assert trail == []
        service._record_audit("test", {"key": "value"})
        trail = service.get_audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "test"

    # ---- authority check ----
    def test_check_authority_with_user(self, service):
        user_id = uuid4()
        service._check_authority(user_id, "permission")

    def test_check_authority_no_user(self, service):
        service._check_authority(None, "permission")

    # ---- audit decorator ----
    def test_audit_decorator(self):
        @audit
        def dummy():
            return 42
        assert dummy() == 42


# ============================================================================
# Factory function test
# ============================================================================

@pytest.mark.asyncio
async def test_build_fiscal_period_service():
    repo = AsyncMock()
    uow = AsyncMock()
    publisher = AsyncMock()
    service = await build_fiscal_period_service(repo, uow, publisher)
    assert isinstance(service, FiscalPeriodService)
    assert service._period_repo is repo
    assert service._uow is uow
    assert service._event_publisher is publisher
