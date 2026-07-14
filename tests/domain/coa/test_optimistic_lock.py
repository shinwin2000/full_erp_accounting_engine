"""
Tests for domain/coa/optimistic_lock.py

Covers OptimisticLockException, RetryConfig (validation + get_delay per
strategy), OptimisticLockManager (check_version/increment_version/
with_version_check[_async]), retry_on_conflict decorator (sync + async),
VersionedEntity mixin, OptimisticLockUtils, DeadlockDetector, and the
module-level with_retry/with_retry_async helpers.

======================================================================
KNOWN BUGS IN THE SOURCE (verified by direct execution):

BUG-LOCK-001 — `with_retry(operation, config)` is a synchronous function
that builds a `retry_on_conflict` decorator and calls
`decorator(operation)()`. If `operation` happens to be an async function
(a coroutine function), `retry_on_conflict`'s internal dispatch picks its
`async_wrapper`, so `decorator(operation)()` returns an *un-awaited
coroutine object* instead of the actual result -- with_retry has no
built-in way to detect or reject this, and no exception is raised (Python
only emits a "coroutine was never awaited" RuntimeWarning). Confirmed:
`with_retry(async_op, ...)` returns `<coroutine object ...>`, not the
operation's actual return value.

BUG-LOCK-002 — `with_retry_async(operation, config)` unconditionally does
`await decorator(operation)()`. If `operation` is a plain synchronous
callable (which the type hint `Callable[[], T]` does not rule out --
nothing about the hint requires an async function), `retry_on_conflict`
picks `sync_wrapper`, whose call already returns a plain value (not a
coroutine). Awaiting that plain value raises
`TypeError: object <type> can't be used in 'await' expression`. Confirmed
with a plain `def sync_op(): return 42`.

In short: `with_retry` only works correctly for sync operations, and
`with_retry_async` only works correctly for async operations -- despite
neither function's signature enforcing that distinction.
======================================================================
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import pytest

from domain.coa.optimistic_lock import (
    DeadlockDetectedError,
    DeadlockDetector,
    OptimisticLockException,
    OptimisticLockManager,
    OptimisticLockRetryExhausted,
    OptimisticLockUtils,
    RetryConfig,
    RetryStrategy,
    VersionedEntity,
    retry_on_conflict,
    with_retry,
    with_retry_async,
)

# ============================================================================
# OptimisticLockException
# ============================================================================


class TestOptimisticLockException:
    def test_basic_message(self):
        exc = OptimisticLockException(entity_id="acc-1", expected_version=1, actual_version=2)
        assert "expected version 1" in str(exc)
        assert "actual version 2" in str(exc)

    def test_message_includes_entity_type_and_operation_when_given(self):
        exc = OptimisticLockException(
            entity_id="acc-1", expected_version=1, actual_version=2,
            entity_type="Account", operation="update",
        )
        assert "Account acc-1" in str(exc)
        assert "during update" in str(exc)

    def test_attributes_stored(self):
        exc = OptimisticLockException(entity_id="acc-1", expected_version=1, actual_version=2)
        assert exc.entity_id == "acc-1"
        assert exc.expected_version == 1
        assert exc.actual_version == 2
        assert exc.entity_type is None
        assert exc.operation is None

    def test_deadlock_detected_error_is_subclass(self):
        assert issubclass(DeadlockDetectedError, OptimisticLockException)


# ============================================================================
# RetryConfig
# ============================================================================


class TestRetryConfig:
    def test_defaults(self):
        config = RetryConfig()
        assert config.max_retries == 3
        assert config.strategy == RetryStrategy.EXPONENTIAL_BACKOFF

    def test_negative_max_retries_raises(self):
        with pytest.raises(ValueError, match="max_retries must be >= 0"):
            RetryConfig(max_retries=-1)

    def test_negative_initial_delay_raises(self):
        with pytest.raises(ValueError, match="initial_delay_ms must be >= 0"):
            RetryConfig(initial_delay_ms=-1)

    def test_max_delay_less_than_initial_raises(self):
        with pytest.raises(ValueError, match="max_delay_ms must be >= initial_delay_ms"):
            RetryConfig(initial_delay_ms=1000, max_delay_ms=100)

    def test_non_positive_backoff_multiplier_raises(self):
        with pytest.raises(ValueError, match="backoff_multiplier must be > 0"):
            RetryConfig(backoff_multiplier=0)

    def test_get_delay_immediate_is_zero(self):
        config = RetryConfig(strategy=RetryStrategy.IMMEDIATE, jitter=False)
        assert config.get_delay(0) == 0.0
        assert config.get_delay(5) == 0.0

    def test_get_delay_fixed(self):
        config = RetryConfig(strategy=RetryStrategy.FIXED_DELAY, initial_delay_ms=100, jitter=False)
        assert config.get_delay(0) == pytest.approx(0.1)
        assert config.get_delay(5) == pytest.approx(0.1)

    def test_get_delay_linear_backoff_increases_per_attempt(self):
        config = RetryConfig(strategy=RetryStrategy.LINEAR_BACKOFF, initial_delay_ms=100, jitter=False)
        assert config.get_delay(0) == pytest.approx(0.1)
        assert config.get_delay(2) == pytest.approx(0.3)

    def test_get_delay_exponential_backoff(self):
        config = RetryConfig(
            strategy=RetryStrategy.EXPONENTIAL_BACKOFF, initial_delay_ms=100,
            backoff_multiplier=2.0, jitter=False,
        )
        assert config.get_delay(0) == pytest.approx(0.1)
        assert config.get_delay(2) == pytest.approx(0.4)

    def test_get_delay_capped_at_max_delay(self):
        config = RetryConfig(
            strategy=RetryStrategy.EXPONENTIAL_BACKOFF, initial_delay_ms=1000,
            max_delay_ms=2000, backoff_multiplier=10.0, jitter=False,
        )
        assert config.get_delay(5) == pytest.approx(2.0)

    def test_get_delay_random_backoff_within_range(self):
        config = RetryConfig(
            strategy=RetryStrategy.RANDOM_BACKOFF, initial_delay_ms=100,
            max_delay_ms=200, jitter=False,
        )
        delay = config.get_delay(0)
        assert 0.1 <= delay <= 0.2

    def test_get_delay_with_jitter_stays_within_reasonable_bounds(self):
        config = RetryConfig(strategy=RetryStrategy.FIXED_DELAY, initial_delay_ms=100, jitter=True)
        delay = config.get_delay(0)
        assert 0.08 * 0.99 <= delay <= 0.12 * 1.01  # ~ +/-20% jitter band


# ============================================================================
# OptimisticLockManager.check_version
# ============================================================================


class TestCheckVersion:
    def test_matching_version_does_not_raise(self):
        class Entity:
            version = 5
        OptimisticLockManager.check_version(Entity(), 5)

    def test_mismatched_version_raises(self):
        class Entity:
            id = "e1"
            version = 5
        with pytest.raises(OptimisticLockException) as exc_info:
            OptimisticLockManager.check_version(Entity(), 1)
        assert exc_info.value.expected_version == 1
        assert exc_info.value.actual_version == 5

    def test_missing_version_attribute_raises_type_error(self):
        class Entity:
            pass
        with pytest.raises(TypeError, match="has no 'version' attribute"):
            OptimisticLockManager.check_version(Entity(), 1)

    def test_entity_id_prefers_id_over_account_id(self):
        class Entity:
            id = "primary-id"
            account_id = "secondary-id"
            version = 1
        with pytest.raises(OptimisticLockException) as exc_info:
            OptimisticLockManager.check_version(Entity(), 99)
        assert exc_info.value.entity_id == "primary-id"

    def test_entity_id_falls_back_to_account_id(self):
        class Entity:
            account_id = "acc-fallback"
            version = 1
        with pytest.raises(OptimisticLockException) as exc_info:
            OptimisticLockManager.check_version(Entity(), 99)
        assert exc_info.value.entity_id == "acc-fallback"


# ============================================================================
# OptimisticLockManager.increment_version
# ============================================================================


class TestIncrementVersion:
    def test_increment_dataclass_via_replace(self):
        @dataclass(frozen=True)
        class Entity:
            id: str
            version: int

        entity = Entity(id="1", version=1)
        incremented = OptimisticLockManager.increment_version(entity)
        assert incremented.version == 2
        assert incremented is not entity

    def test_increment_plain_object_via_copy_fallback(self):
        class Entity:
            def __init__(self):
                self.version = 1

        entity = Entity()
        incremented = OptimisticLockManager.increment_version(entity)
        assert incremented.version == 2
        assert incremented is not entity
        assert entity.version == 1  # original untouched

    def test_missing_version_attribute_raises(self):
        class Entity:
            pass
        with pytest.raises(TypeError, match="has no 'version' attribute"):
            OptimisticLockManager.increment_version(Entity())


# ============================================================================
# OptimisticLockManager.with_version_check / with_version_check_async
# ============================================================================


class TestWithVersionCheck:
    def test_sync_success(self):
        @dataclass(frozen=True)
        class Entity:
            id: str
            version: int
            name: str

        entity = Entity(id="1", version=1, name="old")

        def update_func(e):
            return dataclass_replace_name(e, "new")

        def dataclass_replace_name(e, new_name):
            from dataclasses import replace
            return replace(e, name=new_name)

        result = OptimisticLockManager.with_version_check(entity, 1, update_func)
        assert result.name == "new"
        assert result.version == 2

    def test_sync_raises_on_mismatch(self):
        @dataclass(frozen=True)
        class Entity:
            id: str
            version: int

        entity = Entity(id="1", version=5)
        with pytest.raises(OptimisticLockException):
            OptimisticLockManager.with_version_check(entity, 1, lambda e: e)

    async def test_async_success(self):
        @dataclass(frozen=True)
        class Entity:
            id: str
            version: int

        entity = Entity(id="1", version=1)

        async def update_func(e):
            return e

        result = await OptimisticLockManager.with_version_check_async(entity, 1, update_func)
        assert result.version == 2

    async def test_async_raises_on_mismatch(self):
        @dataclass(frozen=True)
        class Entity:
            id: str
            version: int

        entity = Entity(id="1", version=5)

        async def update_func(e):
            return e

        with pytest.raises(OptimisticLockException):
            await OptimisticLockManager.with_version_check_async(entity, 1, update_func)


# ============================================================================
# retry_on_conflict decorator
# ============================================================================


class TestRetryOnConflictSync:
    def test_succeeds_first_try(self):
        calls = {"n": 0}

        @retry_on_conflict(max_retries=3, initial_delay_ms=1, jitter=False)
        def op():
            calls["n"] += 1
            return "ok"

        assert op() == "ok"
        assert calls["n"] == 1

    def test_retries_then_succeeds(self):
        calls = {"n": 0}

        @retry_on_conflict(max_retries=3, initial_delay_ms=1, jitter=False)
        def op():
            calls["n"] += 1
            if calls["n"] < 2:
                raise OptimisticLockException("e1", 1, 2)
            return "recovered"

        assert op() == "recovered"
        assert calls["n"] == 2

    def test_exhausts_retries_and_raises_wrapped_exception(self):
        @retry_on_conflict(max_retries=2, initial_delay_ms=1, jitter=False)
        def op():
            raise OptimisticLockException("e1", 1, 2)

        with pytest.raises(OptimisticLockRetryExhausted):
            op()

    def test_non_retryable_exception_propagates_immediately(self):
        calls = {"n": 0}

        @retry_on_conflict(max_retries=3, initial_delay_ms=1, jitter=False)
        def op():
            calls["n"] += 1
            raise ValueError("unrelated")

        with pytest.raises(ValueError, match="unrelated"):
            op()
        assert calls["n"] == 1


class TestRetryOnConflictAsync:
    async def test_succeeds_first_try(self):
        calls = {"n": 0}

        @retry_on_conflict(max_retries=3, initial_delay_ms=1, jitter=False)
        async def op():
            calls["n"] += 1
            return "ok"

        assert await op() == "ok"
        assert calls["n"] == 1

    async def test_retries_then_succeeds(self):
        calls = {"n": 0}

        @retry_on_conflict(max_retries=3, initial_delay_ms=1, jitter=False)
        async def op():
            calls["n"] += 1
            if calls["n"] < 3:
                raise OptimisticLockException("e1", 1, 2)
            return "recovered"

        assert await op() == "recovered"
        assert calls["n"] == 3

    async def test_exhausts_retries_and_raises(self):
        @retry_on_conflict(max_retries=1, initial_delay_ms=1, jitter=False)
        async def op():
            raise OptimisticLockException("e1", 1, 2)

        with pytest.raises(OptimisticLockRetryExhausted):
            await op()


# ============================================================================
# VersionedEntity mixin
# ============================================================================


class TestVersionedEntity:
    def test_default_version_is_1(self):
        entity = VersionedEntity()
        assert entity.version == 1

    def test_custom_initial_version(self):
        entity = VersionedEntity(version=10)
        assert entity.version == 10

    def test_increment_version_in_place(self):
        entity = VersionedEntity()
        entity.increment_version()
        assert entity.version == 2

    def test_check_version(self):
        entity = VersionedEntity(version=3)
        assert entity.check_version(3) is True
        assert entity.check_version(4) is False

    def test_create_snapshot(self):
        entity = VersionedEntity(version=7)
        assert entity.create_snapshot() == {"version": 7}


# ============================================================================
# OptimisticLockUtils
# ============================================================================


class TestOptimisticLockUtils:
    def test_create_version_hash_is_deterministic(self):
        @dataclass
        class Entity:
            id: str
            version: int

        entity = Entity(id="1", version=1)
        h1 = OptimisticLockUtils.create_version_hash(entity)
        h2 = OptimisticLockUtils.create_version_hash(entity)
        assert h1 == h2
        assert len(h1) == 32  # MD5 hex digest length

    def test_create_version_hash_changes_with_version(self):
        @dataclass
        class Entity:
            id: str
            version: int

        e1 = Entity(id="1", version=1)
        e2 = Entity(id="1", version=2)
        assert OptimisticLockUtils.create_version_hash(e1) != OptimisticLockUtils.create_version_hash(e2)

    def test_create_version_hash_missing_version_raises(self):
        class Entity:
            pass
        with pytest.raises(TypeError, match="has no 'version' attribute"):
            OptimisticLockUtils.create_version_hash(Entity())

    def test_create_version_hash_with_include_fields(self):
        class Entity:
            version = 1
            name = "Cash"
            secret = "irrelevant"

        h_with_name = OptimisticLockUtils.create_version_hash(Entity(), include_fields=["name"])
        entity2 = Entity()
        entity2.name = "Different"
        h_with_different_name = OptimisticLockUtils.create_version_hash(entity2, include_fields=["name"])
        assert h_with_name != h_with_different_name

    def test_verify_version_hash_true_when_matching(self):
        @dataclass
        class Entity:
            id: str
            version: int

        entity = Entity(id="1", version=1)
        h = OptimisticLockUtils.create_version_hash(entity)
        assert OptimisticLockUtils.verify_version_hash(entity, h) is True

    def test_verify_version_hash_false_when_mismatched(self):
        @dataclass
        class Entity:
            id: str
            version: int

        entity = Entity(id="1", version=1)
        assert OptimisticLockUtils.verify_version_hash(entity, "not-a-real-hash") is False

    def test_extract_version_from_hash_always_none(self):
        # Documented as best-effort / always None since MD5 is one-way.
        assert OptimisticLockUtils.extract_version_from_hash("anything") is None

    def test_get_version_etag(self):
        class Entity:
            version = 5
        assert OptimisticLockUtils.get_version_etag(Entity()) == 'W/"5"'

    def test_get_version_etag_missing_version_raises(self):
        class Entity:
            pass
        with pytest.raises(TypeError, match="has no 'version' attribute"):
            OptimisticLockUtils.get_version_etag(Entity())

    @pytest.mark.parametrize(
        "etag, expected",
        [('W/"5"', 5), ('"123"', 123), ("v=42", 42), ("no-digits-here", None)],
    )
    def test_parse_version_from_etag(self, etag, expected):
        assert OptimisticLockUtils.parse_version_from_etag(etag) == expected


# ============================================================================
# DeadlockDetector
# ============================================================================


class TestDeadlockDetector:
    def test_acquire_succeeds_when_unlocked(self):
        detector = DeadlockDetector()
        entity_id = uuid4()
        assert detector.acquire(entity_id, "txn-1") is True

    def test_acquire_by_same_transaction_succeeds(self):
        detector = DeadlockDetector()
        entity_id = uuid4()
        detector.acquire(entity_id, "txn-1")
        assert detector.acquire(entity_id, "txn-1") is True

    def test_acquire_by_different_transaction_fails(self):
        detector = DeadlockDetector()
        entity_id = uuid4()
        detector.acquire(entity_id, "txn-1")
        assert detector.acquire(entity_id, "txn-2") is False

    def test_release_frees_lock_for_other_transactions(self):
        detector = DeadlockDetector()
        entity_id = uuid4()
        detector.acquire(entity_id, "txn-1")
        detector.release(entity_id, "txn-1")
        assert detector.acquire(entity_id, "txn-2") is True

    def test_release_by_non_owning_transaction_is_a_no_op(self):
        detector = DeadlockDetector()
        entity_id = uuid4()
        detector.acquire(entity_id, "txn-1")
        detector.release(entity_id, "txn-2")  # does not own the lock
        assert detector.acquire(entity_id, "txn-3") is False  # still locked by txn-1

    def test_is_locked_false_when_unlocked(self):
        detector = DeadlockDetector()
        assert detector.is_locked(uuid4(), "txn-1") is False

    def test_is_locked_false_for_owning_transaction(self):
        detector = DeadlockDetector()
        entity_id = uuid4()
        detector.acquire(entity_id, "txn-1")
        assert detector.is_locked(entity_id, "txn-1") is False

    def test_is_locked_true_for_other_transaction(self):
        detector = DeadlockDetector()
        entity_id = uuid4()
        detector.acquire(entity_id, "txn-1")
        assert detector.is_locked(entity_id, "txn-2") is True


# ============================================================================
# Module-level with_retry / with_retry_async
# ============================================================================


class TestWithRetryHelpers:
    def test_with_retry_sync_operation_succeeds(self):
        calls = {"n": 0}

        def op():
            calls["n"] += 1
            return "done"

        result = with_retry(op, RetryConfig(max_retries=1, initial_delay_ms=1, jitter=False))
        assert result == "done"

    def test_with_retry_uses_default_config_when_none_given(self):
        def op():
            return "done"
        assert with_retry(op) == "done"

    def test_with_retry_on_async_operation_returns_unawaited_coroutine(self):
        """BUG-LOCK-001: with_retry() does not await async operations; it
        silently returns a coroutine object instead of the real result."""
        import inspect

        async def async_op():
            return 99

        result = with_retry(async_op, RetryConfig(max_retries=1, initial_delay_ms=1, jitter=False))
        assert inspect.iscoroutine(result)
        result.close()  # avoid "coroutine was never awaited" warning noise

    async def test_with_retry_async_on_async_operation_succeeds(self):
        async def async_op():
            return "async-done"

        result = await with_retry_async(async_op, RetryConfig(max_retries=1, initial_delay_ms=1, jitter=False))
        assert result == "async-done"

    async def test_with_retry_async_on_sync_operation_raises_type_error(self):
        """BUG-LOCK-002: with_retry_async() always awaits the wrapper's
        result. For a plain sync operation, that result is already a plain
        value (not a coroutine), so awaiting it raises TypeError."""
        def sync_op():
            return 42

        with pytest.raises(TypeError, match="can't be used in 'await' expression"):
            await with_retry_async(sync_op, RetryConfig(max_retries=1, initial_delay_ms=1, jitter=False))
