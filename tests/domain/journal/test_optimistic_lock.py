"""
Tests for domain/journal/optimistic_lock.py

Covers:
- OptimisticLockException: attributes and message
- OptimisticLockManager: check_version, check_posted_immutability,
  with_version_check, increment_version, retry_on_conflict (async),
  retry_on_conflict_sync
- VersionedJournalMixin: version tracking, history, hashing, serialization
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from domain.journal.journal_entity import JournalStatus
from domain.journal.optimistic_lock import (
    OptimisticLockException,
    OptimisticLockManager,
    VersionedJournalMixin,
)


# ============================================================================
# OptimisticLockException
# ============================================================================


class TestOptimisticLockException:
    def test_attributes_are_stored(self):
        entity_id = uuid4()
        exc = OptimisticLockException(entity_id, "Journal", expected_version=1, actual_version=2)
        assert exc.entity_id == entity_id
        assert exc.entity_type == "Journal"
        assert exc.expected_version == 1
        assert exc.actual_version == 2

    def test_message_contains_versions(self):
        exc = OptimisticLockException(uuid4(), "Journal", expected_version=1, actual_version=5)
        assert "expected version 1" in str(exc)
        assert "actual version is 5" in str(exc)

    def test_is_an_exception(self):
        assert issubclass(OptimisticLockException, Exception)


# ============================================================================
# OptimisticLockManager.check_version
# ============================================================================


class TestCheckVersion:
    def test_matching_version_does_not_raise(self):
        entity = SimpleNamespace(id=uuid4(), version=3)
        OptimisticLockManager.check_version(entity, expected_version=3)  # no raise

    def test_mismatched_version_raises(self):
        entity = SimpleNamespace(id=uuid4(), version=3)
        with pytest.raises(OptimisticLockException) as exc_info:
            OptimisticLockManager.check_version(entity, expected_version=2)
        assert exc_info.value.expected_version == 2
        assert exc_info.value.actual_version == 3

    def test_falls_back_to_underscore_version_attr(self):
        entity = SimpleNamespace(_version=7)
        OptimisticLockManager.check_version(entity, expected_version=7)  # no raise

    def test_falls_back_to_default_version_1(self):
        entity = SimpleNamespace()  # no version, no _version
        OptimisticLockManager.check_version(entity, expected_version=1)  # no raise

    def test_falls_back_to_journal_id_when_no_id(self):
        journal_id = uuid4()
        entity = SimpleNamespace(journal_id=journal_id, version=1)
        with pytest.raises(OptimisticLockException) as exc_info:
            OptimisticLockManager.check_version(entity, expected_version=99)
        assert exc_info.value.entity_id == journal_id


# ============================================================================
# OptimisticLockManager.check_posted_immutability
# ============================================================================


class TestCheckPostedImmutability:
    @pytest.mark.parametrize("operation", ["reverse", "archive", "read", "view"])
    def test_allowed_operations_on_posted_do_not_raise(self, operation):
        entity = SimpleNamespace(status=JournalStatus.POSTED)
        OptimisticLockManager.check_posted_immutability(entity, operation)  # no raise

    def test_disallowed_operation_on_posted_raises(self):
        entity = SimpleNamespace(status=JournalStatus.POSTED)
        with pytest.raises(ValueError, match="Cannot perform 'edit' on posted journal"):
            OptimisticLockManager.check_posted_immutability(entity, "edit")

    def test_non_posted_status_never_raises(self):
        entity = SimpleNamespace(status=JournalStatus.DRAFT)
        OptimisticLockManager.check_posted_immutability(entity, "edit")  # no raise

    def test_entity_without_status_never_raises(self):
        entity = SimpleNamespace()
        OptimisticLockManager.check_posted_immutability(entity, "edit")  # no raise


# ============================================================================
# OptimisticLockManager.with_version_check / increment_version
# ============================================================================


class TestWithVersionCheckAndIncrement:
    def test_with_version_check_applies_update_and_increments(self):
        entity = SimpleNamespace(version=1)

        def update_func(e):
            e.updated = True
            return e

        result = OptimisticLockManager.with_version_check(entity, expected_version=1, update_func=update_func)
        assert result.updated is True
        assert result.version == 2

    def test_with_version_check_raises_on_mismatch(self):
        entity = SimpleNamespace(version=5)
        with pytest.raises(OptimisticLockException):
            OptimisticLockManager.with_version_check(entity, expected_version=1, update_func=lambda e: e)

    def test_increment_version_prefers_underscore_version(self):
        entity = SimpleNamespace(_version=1, version=1)
        OptimisticLockManager.increment_version(entity)
        assert entity._version == 2

    def test_increment_version_falls_back_to_version_attr(self):
        entity = SimpleNamespace(version=1)
        OptimisticLockManager.increment_version(entity)
        assert entity.version == 2


# ============================================================================
# OptimisticLockManager.retry_on_conflict (async)
# ============================================================================


class TestRetryOnConflictAsync:
    async def test_succeeds_on_first_attempt(self):
        calls = {"count": 0}

        @OptimisticLockManager.retry_on_conflict(max_retries=3, retry_delay_ms=1)
        async def operation():
            calls["count"] += 1
            return "ok"

        result = await operation()
        assert result == "ok"
        assert calls["count"] == 1

    async def test_retries_then_succeeds(self):
        calls = {"count": 0}

        @OptimisticLockManager.retry_on_conflict(max_retries=3, retry_delay_ms=1)
        async def operation():
            calls["count"] += 1
            if calls["count"] < 2:
                raise OptimisticLockException(uuid4(), "Journal", 1, 2)
            return "recovered"

        result = await operation()
        assert result == "recovered"
        assert calls["count"] == 2

    async def test_exhausts_retries_and_raises(self):
        calls = {"count": 0}

        @OptimisticLockManager.retry_on_conflict(max_retries=2, retry_delay_ms=1)
        async def operation():
            calls["count"] += 1
            raise OptimisticLockException(uuid4(), "Journal", 1, 2)

        with pytest.raises(OptimisticLockException):
            await operation()
        assert calls["count"] == 2

    async def test_non_lock_exceptions_propagate_immediately(self):
        @OptimisticLockManager.retry_on_conflict(max_retries=3, retry_delay_ms=1)
        async def operation():
            raise ValueError("unrelated error")

        with pytest.raises(ValueError, match="unrelated error"):
            await operation()


# ============================================================================
# OptimisticLockManager.retry_on_conflict_sync
# ============================================================================


class TestRetryOnConflictSync:
    def test_succeeds_on_first_attempt(self):
        calls = {"count": 0}

        @OptimisticLockManager.retry_on_conflict_sync(max_retries=3, retry_delay_ms=1)
        def operation():
            calls["count"] += 1
            return "ok"

        assert operation() == "ok"
        assert calls["count"] == 1

    def test_retries_then_succeeds(self):
        calls = {"count": 0}

        @OptimisticLockManager.retry_on_conflict_sync(max_retries=3, retry_delay_ms=1)
        def operation():
            calls["count"] += 1
            if calls["count"] < 3:
                raise OptimisticLockException(uuid4(), "Journal", 1, 2)
            return "recovered"

        assert operation() == "recovered"
        assert calls["count"] == 3

    def test_exhausts_retries_and_raises(self):
        @OptimisticLockManager.retry_on_conflict_sync(max_retries=2, retry_delay_ms=1)
        def operation():
            raise OptimisticLockException(uuid4(), "Journal", 1, 2)

        with pytest.raises(OptimisticLockException):
            operation()


# ============================================================================
# VersionedJournalMixin
# ============================================================================


class TestVersionedJournalMixin:
    def test_default_version_is_1(self):
        mixin = VersionedJournalMixin()
        assert mixin.version == 1

    def test_custom_initial_version(self):
        mixin = VersionedJournalMixin(version=5)
        assert mixin.version == 5

    def test_increment_version_bumps_version(self):
        mixin = VersionedJournalMixin()
        mixin.increment_version()
        assert mixin.version == 2

    def test_increment_version_records_history(self):
        mixin = VersionedJournalMixin()
        mixin.increment_version()
        history = mixin.get_version_history()
        assert len(history) == 1
        assert history[0]["old_version"] == 1
        assert "timestamp" in history[0]

    def test_get_version_history_returns_copy(self):
        mixin = VersionedJournalMixin()
        mixin.increment_version()
        history = mixin.get_version_history()
        history.append({"fake": "entry"})
        assert len(mixin.get_version_history()) == 1  # original unaffected

    def test_check_version_true_when_matching(self):
        mixin = VersionedJournalMixin()
        assert mixin.check_version(1) is True

    def test_check_version_false_when_mismatched(self):
        mixin = VersionedJournalMixin()
        assert mixin.check_version(99) is False

    def test_create_version_hash_is_deterministic(self):
        mixin = VersionedJournalMixin()
        journal_id = uuid4()
        ts = datetime.now(UTC)
        h1 = mixin.create_version_hash(journal_id, ts)
        h2 = mixin.create_version_hash(journal_id, ts)
        assert h1 == h2
        assert len(h1) == 64  # sha256 hex digest length

    def test_create_version_hash_differs_with_different_version(self):
        mixin = VersionedJournalMixin()
        journal_id = uuid4()
        ts = datetime.now(UTC)
        h1 = mixin.create_version_hash(journal_id, ts)
        mixin.increment_version()
        h2 = mixin.create_version_hash(journal_id, ts)
        assert h1 != h2

    def test_to_version_dict(self):
        mixin = VersionedJournalMixin()
        mixin.increment_version()
        d = mixin.to_version_dict()
        assert d["version"] == 2
        assert len(d["version_history"]) == 1
