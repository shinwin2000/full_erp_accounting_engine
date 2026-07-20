# test_optimistic_lock.py
# =========================================
# Lengkap: Semua test asli dipertahankan + tambahan test coverage untuk metode yang hilang.

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from domain.journal.optimistic_lock import (
    OptimisticLockException,
    OptimisticLockManager,
    VersionedJournalMixin,
)


class TestOptimisticLockException:
    def test_construction(self):
        entity_id = uuid4()
        exc = OptimisticLockException(
            entity_id=entity_id,
            entity_type="Journal",
            expected_version=1,
            actual_version=2,
        )
        assert exc.entity_id == entity_id
        assert exc.entity_type == "Journal"
        assert exc.expected_version == 1
        assert exc.actual_version == 2
        assert "Optimistic lock conflict" in str(exc)


class TestOptimisticLockManager:
    def test_check_version_success(self):
        class Dummy:
            version = 5

        entity = Dummy()
        # Should not raise
        OptimisticLockManager.check_version(entity, 5)

    def test_check_version_failure(self):
        class Dummy:
            id = uuid4()
            version = 3

        entity = Dummy()
        with pytest.raises(OptimisticLockException) as excinfo:
            OptimisticLockManager.check_version(entity, 5)
        assert excinfo.value.expected_version == 5
        assert excinfo.value.actual_version == 3

    def test_check_version_fallback_to_private(self):
        class Dummy:
            id = uuid4()
            _version = 7

        entity = Dummy()
        OptimisticLockManager.check_version(entity, 7)  # should not raise

    def test_check_posted_immutability_allowed(self):
        class Dummy:
            status = "POSTED"

        entity = Dummy()
        # These operations should not raise
        for op in ["reverse", "archive", "read", "view"]:
            OptimisticLockManager.check_posted_immutability(entity, op)

    def test_check_posted_immutability_raises(self):
        class Dummy:
            status = "POSTED"

        entity = Dummy()
        with pytest.raises(ValueError, match="Cannot perform 'update' on posted journal"):
            OptimisticLockManager.check_posted_immutability(entity, "update")

    def test_check_posted_immutability_not_posted(self):
        class Dummy:
            status = "DRAFT"

        entity = Dummy()
        # Should not raise for any operation
        OptimisticLockManager.check_posted_immutability(entity, "delete")

    def test_with_version_check_success(self):
        class Dummy:
            id = uuid4()
            version = 1

            def __init__(self):
                self.updated = False

        entity = Dummy()

        def update_func(e):
            e.updated = True
            return e

        updated = OptimisticLockManager.with_version_check(entity, 1, update_func)
        assert updated.updated is True
        assert updated.version == 2

    def test_with_version_check_failure(self):
        class Dummy:
            id = uuid4()
            version = 2

        entity = Dummy()

        def update_func(e):
            return e

        with pytest.raises(OptimisticLockException):
            OptimisticLockManager.with_version_check(entity, 1, update_func)

    def test_increment_version_with_version_attr(self):
        class Dummy:
            version = 1

        entity = Dummy()
        OptimisticLockManager.increment_version(entity)
        assert entity.version == 2

    def test_increment_version_with_private_version_attr(self):
        class Dummy:
            _version = 1

        entity = Dummy()
        OptimisticLockManager.increment_version(entity)
        assert entity._version == 2

    # --- Test retry_on_conflict (async decorator) ---
    @pytest.mark.asyncio
    async def test_retry_on_conflict_success_first_try(self):
        mock_func = AsyncMock(return_value="success")
        decorated = OptimisticLockManager.retry_on_conflict(max_retries=3)(mock_func)
        result = await decorated()
        assert result == "success"
        mock_func.assert_called_once()

    @pytest.mark.asyncio
    async def test_retry_on_conflict_retries_then_succeeds(self):
        call_count = 0

        async def func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise OptimisticLockException(uuid4(), "Test", 1, 2)
            return "success"

        decorated = OptimisticLockManager.retry_on_conflict(
            max_retries=3,
            retry_delay_ms=10,
            backoff_multiplier=1.0,
        )(func)

        import time
        start = time.monotonic()
        result = await decorated()
        elapsed = time.monotonic() - start
        assert result == "success"
        assert call_count == 3
        # With 2 retries, delay should be 10ms + 10ms (since backoff=1.0)
        assert elapsed >= 0.02

    @pytest.mark.asyncio
    async def test_retry_on_conflict_all_fail(self):
        async def func():
            raise OptimisticLockException(uuid4(), "Test", 1, 2)

        decorated = OptimisticLockManager.retry_on_conflict(
            max_retries=3,
            retry_delay_ms=10,
            backoff_multiplier=1.0,
        )(func)

        with pytest.raises(OptimisticLockException):
            await decorated()

    @pytest.mark.asyncio
    async def test_retry_on_conflict_other_exception_not_retried(self):
        async def func():
            raise ValueError("Other error")

        decorated = OptimisticLockManager.retry_on_conflict(max_retries=3)(func)

        with pytest.raises(ValueError, match="Other error"):
            await decorated()

    # --- Test retry_on_conflict_sync (sync decorator) ---
    def test_retry_on_conflict_sync_success_first_try(self):
        mock_func = MagicMock(return_value="success")
        decorated = OptimisticLockManager.retry_on_conflict_sync(max_retries=3)(mock_func)
        result = decorated()
        assert result == "success"
        mock_func.assert_called_once()

    def test_retry_on_conflict_sync_retries_then_succeeds(self):
        call_count = 0

        def func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise OptimisticLockException(uuid4(), "Test", 1, 2)
            return "success"

        decorated = OptimisticLockManager.retry_on_conflict_sync(
            max_retries=3,
            retry_delay_ms=10,
            backoff_multiplier=1.0,
        )(func)

        import time
        start = time.monotonic()
        result = decorated()
        elapsed = time.monotonic() - start
        assert result == "success"
        assert call_count == 3
        assert elapsed >= 0.02

    def test_retry_on_conflict_sync_all_fail(self):
        def func():
            raise OptimisticLockException(uuid4(), "Test", 1, 2)

        decorated = OptimisticLockManager.retry_on_conflict_sync(
            max_retries=3,
            retry_delay_ms=10,
            backoff_multiplier=1.0,
        )(func)

        with pytest.raises(OptimisticLockException):
            decorated()

    def test_retry_on_conflict_sync_other_exception(self):
        def func():
            raise ValueError("Other error")

        decorated = OptimisticLockManager.retry_on_conflict_sync(max_retries=3)(func)

        with pytest.raises(ValueError, match="Other error"):
            decorated()


class TestVersionedJournalMixin:
    def test_initial_version(self):
        mixin = VersionedJournalMixin(version=5)
        assert mixin.version == 5

    def test_initial_version_default(self):
        mixin = VersionedJournalMixin()
        assert mixin.version == 1

    def test_increment_version(self):
        mixin = VersionedJournalMixin(version=3)
        old_version = mixin.version
        mixin.increment_version()
        assert mixin.version == old_version + 1
        history = mixin.get_version_history()
        assert len(history) == 1
        assert history[0]["old_version"] == old_version
        assert "timestamp" in history[0]

    def test_check_version_true(self):
        mixin = VersionedJournalMixin(version=7)
        assert mixin.check_version(7) is True

    def test_check_version_false(self):
        mixin = VersionedJournalMixin(version=7)
        assert mixin.check_version(8) is False

    def test_get_version_history(self):
        mixin = VersionedJournalMixin()
        mixin.increment_version()
        mixin.increment_version()
        history = mixin.get_version_history()
        assert len(history) == 2
        # Ensure copy is returned
        history.append({"extra": "should not affect"})
        assert len(mixin.get_version_history()) == 2

    # --- create_version_hash ---
    def test_create_version_hash(self):
        mixin = VersionedJournalMixin(version=3)
        journal_id = uuid4()
        now = datetime.now(UTC)
        hash_val = mixin.create_version_hash(journal_id, now)
        assert isinstance(hash_val, str)
        assert len(hash_val) == 64  # SHA256 hex length
        # Same inputs should produce same hash
        hash_val2 = mixin.create_version_hash(journal_id, now)
        assert hash_val == hash_val2

    def test_create_version_hash_changes_with_version(self):
        mixin = VersionedJournalMixin(version=3)
        journal_id = uuid4()
        now = datetime.now(UTC)
        h1 = mixin.create_version_hash(journal_id, now)
        mixin.increment_version()
        h2 = mixin.create_version_hash(journal_id, now)
        assert h1 != h2

    # --- to_version_dict ---
    def test_to_version_dict(self):
        mixin = VersionedJournalMixin(version=2)
        mixin.increment_version()
        d = mixin.to_version_dict()
        assert d["version"] == 3
        assert len(d["version_history"]) == 1
        assert d["version_history"][0]["old_version"] == 2

    def test_to_version_dict_no_history(self):
        mixin = VersionedJournalMixin(version=1)
        d = mixin.to_version_dict()
        assert d["version"] == 1
        assert d["version_history"] == []
