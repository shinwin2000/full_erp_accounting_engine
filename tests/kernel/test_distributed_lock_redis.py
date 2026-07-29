"""
Tests for kernel.distributed_lock_redis module.
Comprehensive unit tests for distributed lock functionality with Redis fallback.
"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from kernel.distributed_lock_redis import (
    BaseDistributedLock,
    DistributedLock,
    LockInfo,
    LockStatus,
    _FallbackRedisClient,
    acquire_lock,
    distributed_lock_context,
    get_distributed_lock,
    release_lock,
)

# ============================================================================
# TESTS FOR _FallbackRedisClient
# ============================================================================

class Test_FallbackRedisClient:
    """Tests for the in-memory fallback Redis client."""

    @pytest.fixture
    def client(self):
        """Create a fresh fallback client instance."""
        return _FallbackRedisClient()

    def test_construction(self, client):
        """_FallbackRedisClient can be instantiated."""
        assert isinstance(client, _FallbackRedisClient)
        assert hasattr(client, '_store')
        assert hasattr(client, '_lock')

    @pytest.mark.asyncio
    async def test_set_basic(self, client):
        """Test basic set operation."""
        result = await client.set("test_key", "test_value")
        assert result is True

        stored = await client.get("test_key")
        assert stored == "test_value"

    @pytest.mark.asyncio
    async def test_set_nx_true_existing_key(self, client):
        """Test set with nx=True on existing key returns False."""
        await client.set("existing_key", "value1")
        result = await client.set("existing_key", "value2", nx=True)
        assert result is False

        stored = await client.get("existing_key")
        assert stored == "value1"

    @pytest.mark.asyncio
    async def test_set_nx_false_overwrites(self, client):
        """Test set with nx=False overwrites existing key."""
        await client.set("key", "value1")
        result = await client.set("key", "value2", nx=False)
        assert result is True

        stored = await client.get("key")
        assert stored == "value2"

    @pytest.mark.asyncio
    async def test_set_with_expiration(self, client):
        """Test set with expiration time."""
        result = await client.set("expiring_key", "value", ex=1)
        assert result is True

        stored = await client.get("expiring_key")
        assert stored == "value"

    @pytest.mark.asyncio
    async def test_get_nonexistent_key(self, client):
        """Test get returns None for nonexistent key."""
        result = await client.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_existing_key(self, client):
        """Test delete returns 1 for existing key."""
        await client.set("to_delete", "value")
        result = await client.delete("to_delete")
        assert result == 1

        stored = await client.get("to_delete")
        assert stored is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_key(self, client):
        """Test delete returns 0 for nonexistent key."""
        result = await client.delete("nonexistent")
        assert result == 0

    @pytest.mark.asyncio
    async def test_eval_delete_script_success(self, client):
        """Test eval with delete script when value matches."""
        await client.set("lock_key", "lock_value")
        script = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
        result = await client.eval(script, 1, "lock_key", "lock_value")
        assert result == 1

    @pytest.mark.asyncio
    async def test_eval_delete_script_mismatch(self, client):
        """Test eval with delete script when value doesn't match."""
        await client.set("lock_key", "lock_value")
        script = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
        result = await client.eval(script, 1, "lock_key", "wrong_value")
        assert result == 0

    @pytest.mark.asyncio
    async def test_eval_expire_script(self, client):
        """Test eval with expire script."""
        await client.set("key", "value")
        script = "redis.call('expire', KEYS[1], ARGV[2])"
        result = await client.eval(script, 1, "key", "ignored", 30)
        assert result == 1


# ============================================================================
# TESTS FOR LockStatus ENUM
# ============================================================================

class TestLockStatus:
    """Tests for the LockStatus enum."""

    def test_all_members_exist(self):
        """All expected enum members are defined."""
        assert hasattr(LockStatus, 'ACQUIRED')
        assert hasattr(LockStatus, 'RELEASED')
        assert hasattr(LockStatus, 'EXPIRED')
        assert hasattr(LockStatus, 'NOT_ACQUIRED')
        assert hasattr(LockStatus, 'FAILED')

    def test_members_are_instances(self):
        """Enum members are instances of LockStatus."""
        assert isinstance(LockStatus.ACQUIRED, LockStatus)
        assert isinstance(LockStatus.RELEASED, LockStatus)
        assert isinstance(LockStatus.EXPIRED, LockStatus)
        assert isinstance(LockStatus.NOT_ACQUIRED, LockStatus)
        assert isinstance(LockStatus.FAILED, LockStatus)

    def test_unique_values(self):
        """All enum members have unique values."""
        values = [member.value for member in LockStatus]
        assert len(values) == len(set(values))

    def test_iteration(self):
        """Can iterate over all enum members."""
        members = list(LockStatus)
        assert len(members) == 5


# ============================================================================
# TESTS FOR LockInfo DATACLASS
# ============================================================================

class TestLockInfo:
    """Tests for the LockInfo dataclass."""

    def test_construction_required_fields(self):
        """LockInfo can be constructed with required fields."""
        now = datetime.now(UTC)
        info = LockInfo(
            lock_key="test_key",
            lock_value="test_value",
            acquired_at=now,
            expires_at=now,
            ttl_seconds=30,
            auto_renew=True,
        )
        assert info.lock_key == "test_key"
        assert info.lock_value == "test_value"
        assert info.ttl_seconds == 30
        assert info.auto_renew is True
        assert info.renewal_task is None

    def test_construction_with_renewal_task(self):
        """LockInfo can be constructed with renewal task."""
        now = datetime.now(UTC)
        mock_task = MagicMock(spec=asyncio.Task)
        info = LockInfo(
            lock_key="test_key",
            lock_value="test_value",
            acquired_at=now,
            expires_at=now,
            ttl_seconds=30,
            auto_renew=True,
            renewal_task=mock_task,
        )
        assert info.renewal_task is mock_task

    def test_dataclass_fields(self):
        """LockInfo has all expected fields."""
        now = datetime.now(UTC)
        info = LockInfo(
            lock_key="key",
            lock_value="value",
            acquired_at=now,
            expires_at=now,
            ttl_seconds=30,
            auto_renew=False,
        )
        assert hasattr(info, 'lock_key')
        assert hasattr(info, 'lock_value')
        assert hasattr(info, 'acquired_at')
        assert hasattr(info, 'expires_at')
        assert hasattr(info, 'ttl_seconds')
        assert hasattr(info, 'auto_renew')
        assert hasattr(info, 'renewal_task')


# ============================================================================
# TESTS FOR BaseDistributedLock
# ============================================================================

class TestBaseDistributedLock:
    """Tests for the BaseDistributedLock abstract class."""

    def test_class_is_abstract(self):
        """BaseDistributedLock is an abstract class."""
        assert hasattr(BaseDistributedLock, '__abstractmethods__')

    def test_cannot_instantiate_directly(self):
        """Cannot instantiate BaseDistributedLock directly."""
        with pytest.raises(TypeError):
            BaseDistributedLock()

    def test_has_required_abstract_methods(self):
        """BaseDistributedLock defines all required abstract methods."""
        abstract_methods = BaseDistributedLock.__abstractmethods__
        required_methods = {
            'acquire', 'release', 'is_locked', 'get_lock_holder',
            'is_held_by_current', 'force_release', 'get_held_locks',
            'get_lock_info', 'get_all_locks', 'get_statistics'
        }
        assert required_methods.issubset(abstract_methods)


# ============================================================================
# TESTS FOR DistributedLock
# ============================================================================

class TestDistributedLock:
    """Tests for the DistributedLock class."""

    @pytest.fixture
    def lock_manager(self):
        """Create a fresh DistributedLock instance and clean up safely."""
        manager = DistributedLock()
        yield manager
        # Safely reset to cancel renewal tasks, ignore RuntimeError if loop closed
        try:
            manager.reset()
        except RuntimeError:
            pass

    def test_construction(self, lock_manager):
        """DistributedLock can be instantiated."""
        assert isinstance(lock_manager, DistributedLock)
        assert isinstance(lock_manager, BaseDistributedLock)

    def test_construction_with_redis_urls(self):
        """DistributedLock can be instantiated with redis URLs."""
        manager = DistributedLock(redis_urls=["redis://localhost:6379"])
        assert isinstance(manager, DistributedLock)
        assert len(manager._redis_clients) >= 1

    def test_initial_state(self, lock_manager):
        """DistributedLock starts with empty state."""
        assert len(lock_manager._locks_held) == 0
        assert len(lock_manager._renewal_tasks) == 0
        assert lock_manager._version == 1

    @pytest.mark.asyncio
    async def test_acquire_success(self, lock_manager):
        """Successfully acquire a lock."""
        result = await lock_manager.acquire("test_lock", ttl_seconds=30)
        assert result is True
        assert "test_lock" in lock_manager._locks_held

    @pytest.mark.asyncio
    async def test_acquire_with_custom_ttl(self, lock_manager):
        """Acquire lock with custom TTL."""
        result = await lock_manager.acquire("test_lock", ttl_seconds=60)
        assert result is True
        lock_info = lock_manager._locks_held.get("test_lock")
        assert lock_info is not None
        assert lock_info.ttl_seconds == 60

    @pytest.mark.asyncio
    async def test_acquire_without_auto_renew(self, lock_manager):
        """Acquire lock without auto-renewal."""
        result = await lock_manager.acquire("test_lock", auto_renew=False)
        assert result is True
        lock_info = lock_manager._locks_held.get("test_lock")
        assert lock_info is not None
        assert lock_info.auto_renew is False

    @pytest.mark.asyncio
    async def test_acquire_blocking_false_immediate_fail(self, lock_manager):
        """Acquire with blocking=False fails immediately if lock exists."""
        await lock_manager.acquire("test_lock", auto_renew=False)
        result = await lock_manager.acquire("test_lock", blocking=False)
        assert result is False

    @pytest.mark.asyncio
    async def test_release_success(self, lock_manager):
        """Successfully release a lock."""
        await lock_manager.acquire("test_lock")
        result = await lock_manager.release("test_lock")
        assert result is True
        assert "test_lock" not in lock_manager._locks_held

    @pytest.mark.asyncio
    async def test_release_nonexistent_lock(self, lock_manager):
        """Release nonexistent lock returns False."""
        result = await lock_manager.release("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_is_locked_true(self, lock_manager):
        """is_locked returns True for held lock."""
        await lock_manager.acquire("test_lock")
        result = await lock_manager.is_locked("test_lock")
        assert result is True

    @pytest.mark.asyncio
    async def test_is_locked_false(self, lock_manager):
        """is_locked returns False for released lock."""
        await lock_manager.acquire("test_lock")
        await lock_manager.release("test_lock")
        result = await lock_manager.is_locked("test_lock")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_lock_holder(self, lock_manager):
        """get_lock_holder returns the lock value."""
        await lock_manager.acquire("test_lock")
        holder = await lock_manager.get_lock_holder("test_lock")
        assert holder is not None
        assert isinstance(holder, str)

    @pytest.mark.asyncio
    async def test_get_lock_holder_none(self, lock_manager):
        """get_lock_holder returns None for nonexistent lock."""
        holder = await lock_manager.get_lock_holder("nonexistent")
        assert holder is None

    @pytest.mark.asyncio
    async def test_is_held_by_current_true(self, lock_manager):
        """is_held_by_current returns True for own lock."""
        await lock_manager.acquire("test_lock")
        result = await lock_manager.is_held_by_current("test_lock")
        assert result is True

    @pytest.mark.asyncio
    async def test_is_held_by_current_false(self, lock_manager):
        """is_held_by_current returns False for nonexistent lock."""
        result = await lock_manager.is_held_by_current("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_force_release(self, lock_manager):
        """force_release removes lock."""
        await lock_manager.acquire("test_lock")
        result = await lock_manager.force_release("test_lock")
        assert result is True
        assert "test_lock" not in lock_manager._locks_held

    def test_get_held_locks_empty(self, lock_manager):
        """get_held_locks returns empty list when no locks held."""
        locks = lock_manager.get_held_locks()
        assert locks == []

    @pytest.mark.asyncio
    async def test_get_held_locks_with_locks(self, lock_manager):
        """get_held_locks returns list of held locks."""
        await lock_manager.acquire("lock1")
        await lock_manager.acquire("lock2")

        locks = lock_manager.get_held_locks()
        assert len(locks) == 2
        lock_keys = [lock['lock_key'] for lock in locks]
        assert "lock1" in lock_keys
        assert "lock2" in lock_keys

    @pytest.mark.asyncio
    async def test_release_all(self, lock_manager):
        """release_all releases all held locks."""
        await lock_manager.acquire("lock1")
        await lock_manager.acquire("lock2")

        await lock_manager.release_all()

        assert len(lock_manager._locks_held) == 0

    @pytest.mark.asyncio
    async def test_get_lock_info(self, lock_manager):
        """get_lock_info returns lock details."""
        await lock_manager.acquire("test_lock")
        info = await lock_manager.get_lock_info("test_lock")

        assert info is not None
        assert info['lock_key'] == "test_lock"
        assert 'holder' in info
        assert 'is_held_by_current' in info

    @pytest.mark.asyncio
    async def test_get_lock_info_none(self, lock_manager):
        """get_lock_info returns None for nonexistent lock."""
        info = await lock_manager.get_lock_info("nonexistent")
        assert info is None

    @pytest.mark.asyncio
    async def test_get_all_locks(self, lock_manager):
        """get_all_locks returns all locks."""
        await lock_manager.acquire("lock1")
        await lock_manager.acquire("lock2")

        all_locks = await lock_manager.get_all_locks()
        assert len(all_locks) == 2

    def test_get_statistics(self, lock_manager):
        """get_statistics returns lock manager stats."""
        stats = lock_manager.get_statistics()

        assert 'held_locks' in stats
        assert 'renewal_tasks' in stats
        assert 'redis_clients' in stats
        assert 'version' in stats
        assert stats['held_locks'] == 0
        assert stats['version'] == 1

    # Entity methods tests
    def test_validate_valid(self, lock_manager):
        """validate returns valid for proper configuration."""
        result = lock_manager.validate()
        assert result['is_valid'] is True
        assert result['errors'] == []

    def test_to_dict(self, lock_manager):
        """to_dict returns serializable representation."""
        result = lock_manager.to_dict()

        assert isinstance(result, dict)
        assert 'held_locks' in result
        assert 'version' in result
        assert result['version'] == 1

    def test_from_dict(self, lock_manager):
        """from_dict creates instance from dict."""
        data = {'version': 2, 'held_locks': ['lock1']}
        new_instance = DistributedLock.from_dict(data)

        assert isinstance(new_instance, DistributedLock)
        assert new_instance._version == 2

    def test_clone(self, lock_manager):
        """clone creates new instance with incremented version."""
        lock_manager._version = 5
        cloned = lock_manager.clone()

        assert isinstance(cloned, DistributedLock)
        assert cloned is not lock_manager
        assert cloned._version == 6

    def test_snapshot(self, lock_manager):
        """snapshot returns current state snapshot."""
        snapshot = lock_manager.snapshot()

        assert isinstance(snapshot, dict)
        assert 'version' in snapshot
        assert 'held_locks' in snapshot
        assert 'timestamp' in snapshot

    def test_version(self, lock_manager):
        """version returns current version number."""
        assert lock_manager.version() == 1

        lock_manager._version = 10
        assert lock_manager.version() == 10

    def test_audit_trail(self, lock_manager):
        """audit_trail returns audit log."""
        trail = lock_manager.audit_trail()
        assert isinstance(trail, list)

        lock_manager.touch("user1")
        lock_manager.touch("user2")

        trail = lock_manager.audit_trail()
        assert len(trail) >= 2

    def test_audit_trail_with_limit(self, lock_manager):
        """audit_trail respects limit parameter."""
        for i in range(10):
            lock_manager.touch(f"user{i}")

        trail = lock_manager.audit_trail(limit=5)
        assert len(trail) <= 5

    def test_touch(self, lock_manager):
        """touch increments version and adds audit entry."""
        initial_version = lock_manager._version
        result = lock_manager.touch("test_user")

        assert result is lock_manager
        assert lock_manager._version == initial_version + 1

        trail = lock_manager.audit_trail()
        assert len(trail) >= 1
        assert trail[-1]['performed_by'] == "test_user"

    @pytest.mark.asyncio
    async def test_reset(self, lock_manager):
        """reset clears all state."""
        await lock_manager.acquire("lock1")
        lock_manager.touch("user")

        lock_manager.reset()

        assert len(lock_manager._locks_held) == 0
        assert len(lock_manager._renewal_tasks) == 0
        assert lock_manager._version == 1
        assert len(lock_manager._audit_trail) == 0


# ============================================================================
# TESTS FOR CONTEXT MANAGER
# ============================================================================

class TestLockContextManager:
    """Tests for the lock context manager."""

    @pytest.fixture
    def lock_manager(self):
        """Create a fresh DistributedLock instance and clean up safely."""
        manager = DistributedLock()
        yield manager
        try:
            manager.reset()
        except RuntimeError:
            pass

    @pytest.mark.asyncio
    async def test_lock_context_success(self, lock_manager):
        """lock context manager acquires and releases lock."""
        async with lock_manager.lock("test_lock"):
            assert await lock_manager.is_locked("test_lock")

        assert not await lock_manager.is_locked("test_lock")

    @pytest.mark.asyncio
    async def test_lock_context_with_custom_params(self, lock_manager):
        """lock context manager accepts custom parameters."""
        async with lock_manager.lock("test_lock", ttl_seconds=60, timeout_seconds=5.0):
            assert await lock_manager.is_locked("test_lock")

    @pytest.mark.asyncio
    async def test_lock_context_exception_releases(self, lock_manager):
        """lock context manager releases lock even on exception."""
        try:
            async with lock_manager.lock("test_lock"):
                raise ValueError("Test error")
        except ValueError:
            pass

        assert not await lock_manager.is_locked("test_lock")


# ============================================================================
# TESTS FOR MODULE-LEVEL FUNCTIONS
# ============================================================================

class TestModuleFunctions:
    """Tests for module-level convenience functions."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton before each test."""
        import kernel.distributed_lock_redis as module
        module._distributed_lock_instance = None
        yield
        module._distributed_lock_instance = None

    def test_get_distributed_lock_singleton(self):
        """get_distributed_lock returns singleton instance."""
        lock1 = get_distributed_lock()
        lock2 = get_distributed_lock()

        assert lock1 is lock2
        assert isinstance(lock1, DistributedLock)

    def test_get_distributed_lock_creates_instance(self):
        """get_distributed_lock creates instance if none exists."""
        import kernel.distributed_lock_redis as module
        module._distributed_lock_instance = None

        lock = get_distributed_lock()
        assert lock is not None
        assert isinstance(lock, DistributedLock)

    @pytest.mark.asyncio
    async def test_acquire_lock(self):
        """acquire_lock acquires lock using singleton."""
        result = await acquire_lock("test_lock", ttl_seconds=30)
        assert result is True

        await release_lock("test_lock")

    @pytest.mark.asyncio
    async def test_release_lock(self):
        """release_lock releases lock using singleton."""
        await acquire_lock("test_lock")
        result = await release_lock("test_lock")
        assert result is True

    @pytest.mark.asyncio
    async def test_distributed_lock_context(self):
        """distributed_lock_context provides context manager."""
        async with distributed_lock_context("test_lock"):
            lock = get_distributed_lock()
            assert await lock.is_locked("test_lock")


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestIntegration:
    """Integration tests for distributed lock system."""

    @pytest.fixture
    def lock_manager(self):
        """Create a fresh DistributedLock instance and clean up safely."""
        manager = DistributedLock()
        yield manager
        try:
            manager.reset()
        except RuntimeError:
            pass

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, lock_manager):
        """Test complete lock lifecycle."""
        assert await lock_manager.acquire("resource")
        assert await lock_manager.is_locked("resource")
        assert await lock_manager.is_held_by_current("resource")

        info = await lock_manager.get_lock_info("resource")
        assert info is not None
        assert info['lock_key'] == "resource"

        assert await lock_manager.release("resource")
        assert not await lock_manager.is_locked("resource")
        assert not await lock_manager.is_held_by_current("resource")

    @pytest.mark.asyncio
    async def test_multiple_locks(self, lock_manager):
        """Test managing multiple locks simultaneously."""
        locks = ["lock_a", "lock_b", "lock_c"]

        for lock_key in locks:
            result = await lock_manager.acquire(lock_key)
            assert result is True

        for lock_key in locks:
            assert await lock_manager.is_locked(lock_key)

        await lock_manager.release_all()

        for lock_key in locks:
            assert not await lock_manager.is_locked(lock_key)

    @pytest.mark.asyncio
    async def test_statistics_accuracy(self, lock_manager):
        """Test statistics reflect actual state."""
        stats = lock_manager.get_statistics()
        assert stats['held_locks'] == 0

        await lock_manager.acquire("lock1")
        await lock_manager.acquire("lock2")

        stats = lock_manager.get_statistics()
        assert stats['held_locks'] == 2

        await lock_manager.release("lock1")

        stats = lock_manager.get_statistics()
        assert stats['held_locks'] == 1

    @pytest.mark.asyncio
    async def test_audit_trail_completeness(self, lock_manager):
        """Test audit trail captures all operations."""
        await lock_manager.acquire("test_lock")
        await lock_manager.release("test_lock")
        lock_manager.touch("system")

        trail = lock_manager.audit_trail()

        actions = [entry['action'] for entry in trail]
        assert 'ACQUIRE' in actions
        assert 'RELEASE' in actions
        assert 'TOUCH' in actions
