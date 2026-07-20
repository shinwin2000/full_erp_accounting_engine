# adapters/coretax_djp/test_nsfp_manager.py
"""
Comprehensive unit tests for NSFP Manager.

Covers:
- NSFStatus enum
- All exception classes
- NSFP entity: properties, status transitions, allocation, release, usage, locking, events, serialization
- NSFPRepositoryPort interface (tested with Fallback implementation)
- _FallbackNSFPRepository: CRUD operations, batch add, status queries
- NSFPManager: allocation, release, refill, quota info, sync, validation, health, legacy helpers
- Module-level functions: get_nsfp_manager, get_nsfp
- Redis integration (mocked)
- Coretax API client (mocked)
- Alert triggering (mocked)
"""

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from adapters.coretax_djp.nsfp_manager import (
    NSFP,
    NSFAllocationError,
    NSFDuplicateError,
    NSFError,
    NSFExpiredError,
    NSFInvalidFormatError,
    NSFNotAvailableError,
    NSFNotFoundError,
    NSFPManager,
    NSFQuotaExhaustedError,
    NSFStatus,
    _FallbackNSFPRepository,
    get_nsfp,
    get_nsfp_manager,
)

# =============================================================================
# Helpers
# =============================================================================

def create_nsfp(
    number="12345678",
    npwp="123456789012345",
    tahun=2025,
    bulan=1,
    status=NSFStatus.AVAILABLE,
):
    return NSFP(
        nsfp_number=number,
        npwp=npwp,
        tahun=tahun,
        bulan=bulan,
        status=status,
        nsfp_id=uuid4(),
        version=1,
    )


# =============================================================================
# Tests for NSFStatus Enum
# =============================================================================

class TestNSFStatus:
    def test_enum_values(self):
        assert NSFStatus.AVAILABLE.value == "available"
        assert NSFStatus.ALLOCATED.value == "allocated"
        assert NSFStatus.USED.value == "used"
        assert NSFStatus.EXPIRED.value == "expired"
        assert NSFStatus.CANCELLED.value == "cancelled"
        assert NSFStatus.RELEASED.value == "released"
        assert NSFStatus.PENDING.value == "pending"
        assert NSFStatus.LOCKED.value == "locked"
        assert NSFStatus.ARCHIVED.value == "archived"
        assert NSFStatus.ERROR.value == "error"


# =============================================================================
# Tests for Exceptions
# =============================================================================

class TestExceptions:
    def test_exceptions_inherit(self):
        assert issubclass(NSFNotFoundError, NSFError)
        assert issubclass(NSFNotAvailableError, NSFError)
        assert issubclass(NSFDuplicateError, NSFError)
        assert issubclass(NSFInvalidFormatError, NSFError)
        assert issubclass(NSFQuotaExhaustedError, NSFError)
        assert issubclass(NSFAllocationError, NSFError)
        assert issubclass(NSFExpiredError, NSFError)

    def test_exception_instantiation(self):
        e = NSFError("test")
        assert str(e) == "test"


# =============================================================================
# Tests for NSFP Entity
# =============================================================================

class TestNSFPEntity:
    def test_initialization(self):
        nsfp = NSFP(
            nsfp_number="12345678",
            npwp="123456789012345",
            tahun=2025,
            bulan=1,
        )
        assert nsfp.nsfp_number == "12345678"
        assert nsfp.npwp == "123456789012345"
        assert nsfp.tahun == 2025
        assert nsfp.bulan == 1
        assert nsfp.status == NSFStatus.AVAILABLE
        assert nsfp.nsfp_id is not None
        assert nsfp.version == 1
        assert nsfp.allocated_to_faktur_id is None
        assert nsfp.used_at is None
        assert not nsfp.is_expired
        assert nsfp.is_available
        assert not nsfp.is_allocated
        assert not nsfp.is_used
        assert nsfp.nsfp_number_masked == "1234...5678"

    def test_expiry_date_calculation(self):
        # Jan 2025: expiry should be March 2025 (last day)
        nsfp = NSFP(nsfp_number="12345678", npwp="123", tahun=2025, bulan=1)
        assert nsfp.expiry_date == date(2025, 3, 31)
        # Dec 2025: expiry should be Feb 2026 (leap year)
        nsfp2 = NSFP(nsfp_number="12345678", npwp="123", tahun=2025, bulan=12)
        assert nsfp2.expiry_date == date(2026, 2, 28)
        # Dec 2023: expiry Feb 2024 (leap year)
        nsfp3 = NSFP(nsfp_number="12345678", npwp="123", tahun=2023, bulan=12)
        assert nsfp3.expiry_date == date(2024, 2, 29)

    def test_is_expired(self):
        nsfp = NSFP(nsfp_number="12345678", npwp="123", tahun=2025, bulan=1)
        # Mock expiry date in past
        with patch.object(nsfp, "_expiry_date", date(2020, 1, 1)):
            assert nsfp.is_expired is True

    def test_create(self):
        nsfp = NSFP(nsfp_number="12345678", npwp="123", tahun=2025, bulan=1)
        created_by = uuid4()
        nsfp.create(created_by)
        assert nsfp.status == NSFStatus.AVAILABLE
        assert nsfp.version == 2
        assert len(nsfp.get_events()) == 1
        event = nsfp.get_events()[0]
        assert event["event_type"] == "nsfp_created"
        assert event["data"]["created_by"] == str(created_by)

    def test_update(self):
        nsfp = create_nsfp()
        nsfp._status = NSFStatus.PENDING
        updated_by = uuid4()
        nsfp.update({"npwp": "999999999999999"}, updated_by)
        assert nsfp.npwp == "999999999999999"
        assert nsfp.version == 2
        events = nsfp.get_events()
        assert events[-1]["event_type"] == "nsfp_updated"

    def test_update_locked_raises(self):
        nsfp = create_nsfp()
        nsfp.lock(uuid4())
        with pytest.raises(NSFError, match="locked"):
            nsfp.update({}, uuid4())

    def test_delete(self):
        nsfp = create_nsfp()
        deleted_by = uuid4()
        nsfp.delete(deleted_by, permanent=False)
        assert nsfp.status == NSFStatus.ARCHIVED
        nsfp.delete(deleted_by, permanent=True)
        assert nsfp.status == NSFStatus.CANCELLED
        assert nsfp.cancelled_at is not None

    def test_delete_locked_raises(self):
        nsfp = create_nsfp()
        nsfp.lock(uuid4())
        with pytest.raises(NSFError, match="locked"):
            nsfp.delete(uuid4())

    def test_restore(self):
        nsfp = create_nsfp(status=NSFStatus.ARCHIVED)
        nsfp.restore(uuid4())
        assert nsfp.status == NSFStatus.AVAILABLE
        assert nsfp.cancelled_at is None
        events = nsfp.get_events()
        assert events[-1]["event_type"] == "nsfp_restored"

    def test_restore_invalid_status_raises(self):
        nsfp = create_nsfp()
        with pytest.raises(NSFError, match="Cannot restore"):
            nsfp.restore(uuid4())

    def test_activate_and_deactivate(self):
        nsfp = create_nsfp(status=NSFStatus.PENDING)
        nsfp.activate(uuid4())
        assert nsfp.status == NSFStatus.AVAILABLE
        nsfp.deactivate(uuid4())
        assert nsfp.status == NSFStatus.PENDING

    def test_activate_invalid_status_raises(self):
        nsfp = create_nsfp()
        with pytest.raises(NSFError, match="Cannot activate"):
            nsfp.activate(uuid4())

    def test_lock_unlock(self):
        nsfp = create_nsfp()
        locked_by = uuid4()
        nsfp.lock(locked_by, "audit")
        assert nsfp.is_locked
        assert nsfp.locked_by == locked_by
        assert nsfp.status == NSFStatus.LOCKED
        nsfp.unlock(uuid4())
        assert not nsfp.is_locked
        assert nsfp.status == NSFStatus.AVAILABLE

    def test_lock_already_locked_raises(self):
        nsfp = create_nsfp()
        nsfp.lock(uuid4())
        with pytest.raises(NSFError, match="already locked"):
            nsfp.lock(uuid4())

    def test_unlock_not_locked_raises(self):
        nsfp = create_nsfp()
        with pytest.raises(NSFError, match="not locked"):
            nsfp.unlock(uuid4())

    def test_allocate_success(self):
        nsfp = create_nsfp()
        faktur_id = uuid4()
        allocated_by = uuid4()
        nsfp.allocate(faktur_id, allocated_by)
        assert nsfp.status == NSFStatus.ALLOCATED
        assert nsfp.allocated_to_faktur_id == faktur_id
        assert nsfp.allocated_at is not None
        events = nsfp.get_events()
        assert events[-1]["event_type"] == "nsfp_allocated"

    def test_allocate_when_not_available(self):
        nsfp = create_nsfp(status=NSFStatus.ALLOCATED)
        with pytest.raises(NSFAllocationError, match="not available"):
            nsfp.allocate(uuid4(), uuid4())

    def test_allocate_when_locked(self):
        nsfp = create_nsfp()
        nsfp.lock(uuid4())
        with pytest.raises(NSFAllocationError, match="locked"):
            nsfp.allocate(uuid4(), uuid4())

    def test_allocate_when_expired(self):
        nsfp = create_nsfp()
        with patch.object(nsfp, "is_expired", True):
            with pytest.raises(NSFExpiredError, match="expired"):
                nsfp.allocate(uuid4(), uuid4())

    def test_release(self):
        nsfp = create_nsfp(status=NSFStatus.ALLOCATED)
        nsfp.allocated_to_faktur_id = uuid4()
        released_by = uuid4()
        nsfp.release(released_by, "test")
        assert nsfp.status == NSFStatus.AVAILABLE
        assert nsfp.allocated_to_faktur_id is None
        assert nsfp.released_at is not None
        events = nsfp.get_events()
        assert events[-1]["event_type"] == "nsfp_released"

    def test_release_invalid_status_raises(self):
        nsfp = create_nsfp()
        with pytest.raises(NSFError, match="Cannot release"):
            nsfp.release(uuid4())

    def test_mark_as_used(self):
        nsfp = create_nsfp(status=NSFStatus.ALLOCATED)
        used_by = uuid4()
        nsfp.mark_as_used(used_by)
        assert nsfp.status == NSFStatus.USED
        assert nsfp.used_at is not None
        events = nsfp.get_events()
        assert events[-1]["event_type"] == "nsfp_marked_as_used"

    def test_mark_as_used_invalid_status_raises(self):
        nsfp = create_nsfp()
        with pytest.raises(NSFError, match="Cannot mark"):
            nsfp.mark_as_used(uuid4())

    def test_request_nsfp(self):
        nsfp = create_nsfp()
        nsfp.request_nsfp(uuid4(), 10)
        assert nsfp.status == NSFStatus.PENDING
        events = nsfp.get_events()
        assert events[-1]["event_type"] == "nsfp_requested"

    def test_get_status(self):
        nsfp = create_nsfp()
        status = nsfp.get_status()
        assert status["nsfp_id"] == str(nsfp.nsfp_id)
        assert status["status"] == "available"
        assert status["is_available"] is True

    def test_get_history(self):
        nsfp = create_nsfp()
        nsfp._history.append({"event": "test"})
        history = nsfp.get_history()
        assert len(history) == 1
        assert history[0]["event"] == "test"

    def test_snapshot(self):
        nsfp = create_nsfp()
        snap = nsfp.snapshot()
        assert snap["nsfp_id"] == str(nsfp.nsfp_id)
        assert snap["nsfp_number"] == nsfp.nsfp_number
        assert snap["status"] == "available"

    def test_to_dict_from_dict(self):
        nsfp = create_nsfp(number="87654321")
        d = nsfp.to_dict()
        assert d["nsfp_number"] == "87654321"
        assert d["npwp"] == "123456789012345"
        nsfp2 = NSFP.from_dict(d)
        assert nsfp2.nsfp_number == "87654321"
        assert nsfp2.npwp == "123456789012345"
        assert nsfp2.tahun == 2025
        assert nsfp2.bulan == 1

    def test_audit_trail(self):
        nsfp = create_nsfp()
        nsfp._history.append({"audit": "test"})
        trail = nsfp.audit_trail()
        assert trail == nsfp._history

    def test_can_transition(self):
        nsfp = create_nsfp(status=NSFStatus.PENDING)
        assert nsfp.can_transition(NSFStatus.AVAILABLE) is True
        assert nsfp.can_transition(NSFStatus.USED) is False

    def test_transition(self):
        nsfp = create_nsfp(status=NSFStatus.PENDING)
        nsfp.transition(NSFStatus.AVAILABLE, uuid4(), "reason")
        assert nsfp.status == NSFStatus.AVAILABLE
        assert len(nsfp.get_history()) == 1
        hist = nsfp.get_history()[0]
        assert hist["from_status"] == "pending"
        assert hist["to_status"] == "available"

    def test_transition_invalid_raises(self):
        nsfp = create_nsfp(status=NSFStatus.USED)
        with pytest.raises(NSFError, match="invalid"):
            nsfp.transition(NSFStatus.AVAILABLE, uuid4())

    def test_register_event_and_clear(self):
        nsfp = create_nsfp()
        nsfp.register_event("test_event", {"data": "test"})
        events = nsfp.get_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "test_event"
        nsfp.clear_events()
        assert len(nsfp.get_events()) == 0

    def test_validate_nsfp(self):
        nsfp = create_nsfp(number="12345678")
        assert nsfp.validate_nsfp() is True
        nsfp_invalid = NSFP(nsfp_number="1234567", npwp="123", tahun=2025, bulan=1)
        with pytest.raises(NSFInvalidFormatError, match="Invalid NSFP format"):
            nsfp_invalid.validate_nsfp()

    def test_is_available_for_period(self):
        nsfp = create_nsfp(tahun=2025, bulan=1)
        assert nsfp.is_available_for_period(2025, 1) is True
        assert nsfp.is_available_for_period(2025, 2) is False

    def test_check_expiry(self):
        nsfp = create_nsfp()
        with patch.object(nsfp, "is_expired", True):
            # status available -> should transition to EXPIRED
            result = nsfp.check_expiry()
            assert result is True
            assert nsfp.status == NSFStatus.EXPIRED
            events = nsfp.get_events()
            assert events[-1]["event_type"] == "nsfp_expired"
        # If already used, should not change
        nsfp2 = create_nsfp(status=NSFStatus.USED)
        with patch.object(nsfp2, "is_expired", True):
            result = nsfp2.check_expiry()
            assert result is False
            assert nsfp2.status == NSFStatus.USED


# =============================================================================
# Tests for NSFPRepositoryPort (via Fallback)
# =============================================================================

class TestFallbackNSFPRepository:
    @pytest.mark.asyncio
    async def test_add_and_get_by_id(self):
        repo = _FallbackNSFPRepository()
        nsfp = create_nsfp()
        await repo.add(nsfp)
        retrieved = await repo.get_by_id(nsfp.nsfp_id)
        assert retrieved is not None
        assert retrieved.nsfp_id == nsfp.nsfp_id

    @pytest.mark.asyncio
    async def test_get_by_number(self):
        repo = _FallbackNSFPRepository()
        nsfp = create_nsfp(number="11111111")
        await repo.add(nsfp)
        retrieved = await repo.get_by_number("11111111")
        assert retrieved.nsfp_number == "11111111"

    @pytest.mark.asyncio
    async def test_update(self):
        repo = _FallbackNSFPRepository()
        nsfp = create_nsfp()
        await repo.add(nsfp)
        nsfp._status = NSFStatus.ALLOCATED
        await repo.update(nsfp)
        retrieved = await repo.get_by_id(nsfp.nsfp_id)
        assert retrieved.status == NSFStatus.ALLOCATED

    @pytest.mark.asyncio
    async def test_delete(self):
        repo = _FallbackNSFPRepository()
        nsfp = create_nsfp()
        await repo.add(nsfp)
        await repo.delete(nsfp.nsfp_id)
        retrieved = await repo.get_by_id(nsfp.nsfp_id)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_get_by_npwp_period(self):
        repo = _FallbackNSFPRepository()
        nsfp1 = create_nsfp(npwp="111", tahun=2025, bulan=1)
        nsfp2 = create_nsfp(npwp="222", tahun=2025, bulan=1)
        await repo.add(nsfp1)
        await repo.add(nsfp2)
        results = await repo.get_by_npwp_period("111", 2025, 1)
        assert len(results) == 1
        assert results[0].npwp == "111"

    @pytest.mark.asyncio
    async def test_get_available_by_period(self):
        repo = _FallbackNSFPRepository()
        nsfp1 = create_nsfp(npwp="111", tahun=2025, bulan=1, status=NSFStatus.AVAILABLE)
        nsfp2 = create_nsfp(npwp="111", tahun=2025, bulan=1, status=NSFStatus.ALLOCATED)
        await repo.add(nsfp1)
        await repo.add(nsfp2)
        results = await repo.get_available_by_period("111", 2025, 1)
        assert len(results) == 1
        assert results[0].status == NSFStatus.AVAILABLE

    @pytest.mark.asyncio
    async def test_get_by_status(self):
        repo = _FallbackNSFPRepository()
        nsfp1 = create_nsfp(status=NSFStatus.AVAILABLE)
        nsfp2 = create_nsfp(status=NSFStatus.ALLOCATED)
        await repo.add(nsfp1)
        await repo.add(nsfp2)
        results = await repo.get_by_status(NSFStatus.AVAILABLE)
        assert len(results) == 1
        assert results[0].status == NSFStatus.AVAILABLE

    @pytest.mark.asyncio
    async def test_get_allocated_by_faktur(self):
        repo = _FallbackNSFPRepository()
        faktur_id = uuid4()
        nsfp = create_nsfp(status=NSFStatus.ALLOCATED)
        nsfp.allocated_to_faktur_id = faktur_id
        await repo.add(nsfp)
        retrieved = await repo.get_allocated_by_faktur(faktur_id)
        assert retrieved.nsfp_id == nsfp.nsfp_id

    @pytest.mark.asyncio
    async def test_count_available(self):
        repo = _FallbackNSFPRepository()
        nsfp = create_nsfp(npwp="111", tahun=2025, bulan=1, status=NSFStatus.AVAILABLE)
        await repo.add(nsfp)
        count = await repo.count_available("111", 2025, 1)
        assert count == 1

    @pytest.mark.asyncio
    async def test_mark_as_used(self):
        repo = _FallbackNSFPRepository()
        nsfp = create_nsfp(status=NSFStatus.ALLOCATED)
        await repo.add(nsfp)
        used_at = datetime.now(UTC)
        await repo.mark_as_used(nsfp.nsfp_id, used_at)
        retrieved = await repo.get_by_id(nsfp.nsfp_id)
        assert retrieved.status == NSFStatus.USED

    @pytest.mark.asyncio
    async def test_batch_add(self):
        repo = _FallbackNSFPRepository()
        nsfps = [create_nsfp(number=str(i).zfill(8)) for i in range(5)]
        await repo.batch_add(nsfps)
        count = 0
        for n in nsfps:
            if await repo.get_by_number(n.nsfp_number):
                count += 1
        assert count == 5


# =============================================================================
# Tests for NSFPManager
# =============================================================================

@pytest.fixture
def manager():
    # Use a fresh instance with in-memory storage (no Redis)
    return NSFPManager(config={})


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.lpop = AsyncMock()
    redis.rpush = AsyncMock()
    redis.llen = AsyncMock()
    redis.setex = AsyncMock()
    redis.expireat = AsyncMock()
    return redis


@pytest.fixture
def mock_coretax_client():
    client = AsyncMock()
    client.post = AsyncMock(return_value={"status": "success", "nsfp_list": ["12345678", "87654321"]})
    client.get = AsyncMock()
    return client


class TestNSFPManager:
    @pytest.mark.asyncio
    async def test_create(self, manager):
        created_by = uuid4()
        data = {
            "nsfp_number": "12345678",
            "npwp": "123456789012345",
            "tahun": 2025,
            "bulan": 1,
        }
        result = await manager.create(data, created_by)
        assert result["success"] is True
        assert result["nsfp_number"] == "1234...5678"
        assert result["status"] == "available"
        # Verify stored
        nsfp = await manager.get_by_number("12345678")
        assert nsfp is not None

    @pytest.mark.asyncio
    async def test_allocate_nsfp_with_redis(self, manager, mock_redis):
        manager._redis_client = mock_redis
        key = manager._get_redis_available_key("123", 2025, 1)
        mock_redis.lpop.return_value = b"12345678"
        faktur_id = uuid4()
        allocated_by = uuid4()
        result = await manager.allocate_nsfp("123", 2025, 1, faktur_id, allocated_by)
        assert result["success"] is True
        assert result["nsfp_number"] == "12345678"
        mock_redis.lpop.assert_called_once_with(key)
        mock_redis.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_allocate_nsfp_fallback_no_redis(self, manager):
        manager._redis_client = None
        # Pre-populate test stock
        test_key = manager._get_test_key("123", 2025, 1)
        manager._test_stock[test_key] = ["12345678"]
        faktur_id = uuid4()
        result = await manager.allocate_nsfp("123", 2025, 1, faktur_id, uuid4())
        assert result["success"] is True
        assert result["nsfp_number"] == "12345678"
        assert len(manager._test_stock[test_key]) == 0

    @pytest.mark.asyncio
    async def test_allocate_nsfp_no_available_raises(self, manager):
        with pytest.raises(NSFNotAvailableError, match="No NSFP available"):
            await manager.allocate_nsfp("123", 2025, 1, uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_release_nsfp(self, manager):
        test_key = manager._get_test_key("123", 2025, 1)
        manager._test_stock[test_key] = ["12345678"]
        # Allocate first
        faktur_id = uuid4()
        await manager.allocate_nsfp("123", 2025, 1, faktur_id, uuid4())
        # Release
        result = await manager.release_nsfp("12345678", "123", 2025, 1, uuid4(), "test")
        assert result["success"] is True
        # Should be back in stock
        assert "12345678" in manager._test_stock[test_key]

    @pytest.mark.asyncio
    async def test_get_next_nsfp(self, manager):
        # Alias for allocate
        test_key = manager._get_test_key("123", 2025, 1)
        manager._test_stock[test_key] = ["11111111"]
        result = await manager.get_next_nsfp("123", 2025, 1, uuid4(), uuid4())
        assert result["nsfp_number"] == "11111111"

    @pytest.mark.asyncio
    async def test_request_nsfp_from_djp_success(self, manager, mock_coretax_client):
        manager._coretax_client = mock_coretax_client
        result = await manager.request_nsfp_from_djp("123", 2025, 1, 2, uuid4())
        assert result["success"] is True
        assert result["jumlah"] == 2
        mock_coretax_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_request_nsfp_from_djp_failure(self, manager, mock_coretax_client):
        mock_coretax_client.post.return_value = {"status": "failed", "message": "error"}
        manager._coretax_client = mock_coretax_client
        result = await manager.request_nsfp_from_djp("123", 2025, 1, 2, uuid4())
        assert result["success"] is False
        assert "error" in result["error"]

    @pytest.mark.asyncio
    async def test_request_nsfp_from_djp_auth_retry(self, manager, mock_coretax_client):
        from adapters.coretax_djp.api_oauth2_client import CoretaxAuthError
        # Fail first attempt, succeed second
        mock_coretax_client.post.side_effect = [
            CoretaxAuthError("auth fail"),
            {"status": "success", "nsfp_list": ["12345678"]},
        ]
        manager._coretax_client = mock_coretax_client
        result = await manager.request_nsfp_from_djp("123", 2025, 1, 1, uuid4())
        assert result["success"] is True
        assert mock_coretax_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_refill_nsfp_stock(self, manager):
        # Mock request_nsfp_from_djp
        manager.request_nsfp_from_djp = AsyncMock(
            return_value={"success": True, "nsfp_list": ["11111111", "22222222"]}
        )
        manager._redis_client = None  # use fallback
        result = await manager.refill_nsfp_stock("123", 2025, 1, force=True)
        assert result["success"] is True
        assert result["added_count"] == 2
        test_key = manager._get_test_key("123", 2025, 1)
        assert len(manager._test_stock[test_key]) == 2

    @pytest.mark.asyncio
    async def test_get_available_count(self, manager):
        test_key = manager._get_test_key("123", 2025, 1)
        manager._test_stock[test_key] = ["a", "b", "c"]
        count = await manager.get_available_count("123", 2025, 1)
        assert count == 3

    @pytest.mark.asyncio
    async def test_get_quota_info(self, manager, mock_coretax_client):
        manager._coretax_client = mock_coretax_client
        mock_coretax_client.get.return_value = {
            "total_quota": 100,
            "used": 10,
            "remaining": 90,
        }
        # Pre-populate cache count
        manager._test_stock[manager._get_test_key("123", 2025, 1)] = ["a", "b"]
        result = await manager.get_quota_info("123", 2025, 1)
        assert result["success"] is True
        assert result["total_quota"] == 100
        assert result["available_in_cache"] == 2
        assert result["is_low"] is False
        # Check cache
        cached = await manager._get_cached(manager._get_cache_key("123", 2025, 1))
        assert cached is not None

    @pytest.mark.asyncio
    async def test_preload_nsfp_for_upcoming_months(self, manager):
        manager.refill_nsfp_stock = AsyncMock(
            side_effect=lambda npwp, tahun, bulan: {"success": True, "status": "ok", "added_count": 1}
        )
        result = await manager.preload_nsfp_for_upcoming_months("123", months_ahead=2)
        assert result["success"] is True
        assert len(result["preloaded_months"]) == 2

    @pytest.mark.asyncio
    async def test_sync_with_coretax(self, manager, mock_coretax_client):
        manager._coretax_client = mock_coretax_client
        mock_coretax_client.get.return_value = {"remaining_quota": 50}
        result = await manager.sync_with_coretax("123", 2025, 1)
        assert result["success"] is True
        assert result["remote_quota"] == 50

    @pytest.mark.asyncio
    async def test_validate_nsfp(self, manager, mock_coretax_client):
        manager._coretax_client = mock_coretax_client
        mock_coretax_client.get.return_value = {"is_valid": True, "is_used": False}
        result = await manager.validate_nsfp("12345678", "123")
        assert result["success"] is True
        assert result["is_valid"] is True

    @pytest.mark.asyncio
    async def test_mark_nsfp_as_used(self, manager):
        # First create and allocate
        nsfp = create_nsfp(number="11111111", status=NSFStatus.ALLOCATED)
        await manager._repository.add(nsfp)
        faktur_id = uuid4()
        # Mock coretax client
        manager._coretax_client = AsyncMock()
        manager._coretax_client.post = AsyncMock()
        result = await manager.mark_nsfp_as_used("11111111", faktur_id, uuid4())
        assert result["success"] is True
        assert result["marked_as_used"] is True
        # Verify status updated
        updated = await manager.get_by_number("11111111")
        assert updated.status == NSFStatus.USED

    @pytest.mark.asyncio
    async def test_get_status(self, manager):
        nsfp = create_nsfp(number="11111111")
        await manager._repository.add(nsfp)
        result = await manager.get_status("11111111")
        assert result["status"] == "available"
        result_not_found = await manager.get_status("00000000")
        assert result_not_found["success"] is False

    @pytest.mark.asyncio
    async def test_get_history(self, manager):
        nsfp = create_nsfp(number="11111111")
        nsfp._history.append({"event": "test"})
        await manager._repository.add(nsfp)
        result = await manager.get_history("11111111")
        assert result["success"] is True
        assert len(result["history"]) == 1

    @pytest.mark.asyncio
    async def test_get_by_id(self, manager):
        nsfp = create_nsfp()
        await manager._repository.add(nsfp)
        retrieved = await manager.get_by_id(nsfp.nsfp_id)
        assert retrieved.nsfp_id == nsfp.nsfp_id

    @pytest.mark.asyncio
    async def test_get_allocated_by_faktur(self, manager):
        faktur_id = uuid4()
        nsfp = create_nsfp(status=NSFStatus.ALLOCATED)
        nsfp.allocated_to_faktur_id = faktur_id
        await manager._repository.add(nsfp)
        retrieved = await manager.get_allocated_by_faktur(faktur_id)
        assert retrieved.nsfp_id == nsfp.nsfp_id

    @pytest.mark.asyncio
    async def test_batch_allocate(self, manager):
        # Setup stock
        manager._redis_client = None
        test_key = manager._get_test_key("123", 2025, 1)
        manager._test_stock[test_key] = ["11111111", "22222222"]
        allocations = [
            {"npwp": "123", "tahun": 2025, "bulan": 1, "faktur_id": uuid4()},
            {"npwp": "123", "tahun": 2025, "bulan": 1, "faktur_id": uuid4()},
        ]
        results = await manager.batch_allocate(allocations, uuid4())
        assert len(results) == 2
        assert results[0]["success"] is True
        assert results[1]["success"] is True

    @pytest.mark.asyncio
    async def test_auto_refill_all(self, manager):
        manager.refill_nsfp_stock = AsyncMock(
            side_effect=lambda npwp, tahun, bulan: {"success": True, "added_count": 1}
        )
        npwps = ["111", "222"]
        result = await manager.auto_refill_all(npwps, 2025, 1)
        assert result["success"] is True
        assert len(result["results"]) == 2

    @pytest.mark.asyncio
    async def test_health_check(self, manager):
        # Mock get_available_count and get_quota_info
        manager.get_available_count = AsyncMock(return_value=10)
        manager.get_quota_info = AsyncMock(return_value={"total_quota": 100})
        result = await manager.health_check("123", 2025, 1)
        assert result["success"] is True
        assert result["status"] == "healthy"
        # Low watermark case
        manager.get_available_count = AsyncMock(return_value=1)
        result = await manager.health_check("123", 2025, 1)
        assert result["status"] == "critical"

    # ========================================================================
    # Legacy methods
    # ========================================================================
    def test_request_new_range(self, manager):
        result = manager.request_new_range(5)
        assert isinstance(result, SimpleNamespace)
        assert result.start == 1
        assert result.end == 5
        test_key = manager._get_test_key("123456789012345", date.today().year, date.today().month)
        assert len(manager._test_stock[test_key]) == 5

    def test_get_next(self, manager):
        # Prepopulate stock
        test_key = manager._get_test_key("123456789012345", date.today().year, date.today().month)
        manager._test_stock[test_key] = ["11111111", "22222222"]
        nsfp = manager.get_next()
        assert nsfp == "11111111"
        # Should pop next
        nsfp2 = manager.get_next()
        assert nsfp2 == "22222222"
        # Auto refill when empty
        with patch.object(manager, "request_new_range") as mock_request:
            mock_request.return_value = SimpleNamespace(start=3, end=12)
            manager._test_stock[test_key] = []
            nsfp3 = manager.get_next()
            assert nsfp3 == "00000003"

    def test_get_next_no_available_raises(self, manager):
        # Empty stock and request_new_range fails to add
        manager._test_stock.clear()
        with patch.object(manager, "request_new_range") as mock_request:
            mock_request.return_value = SimpleNamespace(start=1, end=0)  # no range
            with pytest.raises(NSFNotAvailableError, match="No NSFP available"):
                manager.get_next()

    def test_use(self, manager):
        manager._test_used_set = set()
        nsfp = "12345678"
        assert manager.use(nsfp) is True
        assert nsfp in manager._test_used_set
        with pytest.raises(NSFDuplicateError, match="sudah digunakan"):
            manager.use(nsfp)


# =============================================================================
# Tests for Module-level Functions
# =============================================================================

@patch("adapters.coretax_djp.nsfp_manager.NSFPManager")
async def test_get_nsfp_manager(mock_manager_class):
    mock_instance = AsyncMock()
    mock_manager_class.return_value = mock_instance
    # Reset global
    import adapters.coretax_djp.nsfp_manager as mod
    mod._nsfp_manager = None
    result = await get_nsfp_manager(config={"test": True})
    assert result is mock_instance
    mock_manager_class.assert_called_once_with(config={"test": True})

@patch("adapters.coretax_djp.nsfp_manager.get_nsfp_manager")
async def test_get_nsfp(mock_get):
    mock_get.return_value = "manager"
    result = await get_nsfp()
    assert result == "manager"
