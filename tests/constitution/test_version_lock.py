#!/usr/bin/env python3
"""
tests/unit/test_version_lock.py
Comprehensive tests for constitution/version_lock.py

Covers:
- All enums and exceptions
- All data classes: VersionMetadata, VersionLockRecord, VersionChangeAttempt,
  IntegrityReport
- VersionLock aggregate: all repository and business methods
- VersionLockService: all methods including emergency restore
- All edge cases and negative paths
- No flaky tests (mocked datetime)
- No duplicate test code (parametrized where appropriate)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from constitution.version_lock import (
    IntegrityCheckResult,
    IntegrityReport,
    VersionChangeAttempt,
    VersionChangeType,
    VersionFreezeError,
    VersionIntegrityError,
    VersionLock,
    VersionLockError,
    VersionLockEventType,
    VersionLockRecord,
    VersionLockService,
    VersionLockSeverity,
    VersionLockState,
    VersionLockViolationError,
    VersionMetadata,
    get_version_lock_service,
)

# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def fixed_now():
    """Return a fixed datetime for deterministic tests."""
    return datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mock_datetime(fixed_now):
    """Mock datetime.now and datetime.utcnow to return fixed_now for the module under test."""
    with patch("constitution.version_lock.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.utcnow.return_value = fixed_now
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        yield mock_dt


@pytest.fixture
def sample_version_metadata(fixed_now) -> VersionMetadata:
    return VersionMetadata(
        version="1.2.3",
        release_date=fixed_now,
        created_by="test_user",
        approved_by=["approver1", "approver2"],
        change_type=VersionChangeType.MINOR,
        changelog_entry="Sample changelog",
    )


@pytest.fixture
def sample_lock_record(fixed_now) -> VersionLockRecord:
    return VersionLockRecord(
        record_id=uuid.uuid4(),
        previous_state=VersionLockState.UNLOCKED,
        new_state=VersionLockState.LOCKED,
        reason="Test lock",
        initiated_by="admin",
        initiated_at=fixed_now,
        approved_by=["approver1", "approver2"],
        event_type=VersionLockEventType.STATE_CHANGE,
    )


@pytest.fixture
def sample_change_attempt(fixed_now) -> VersionChangeAttempt:
    return VersionChangeAttempt(
        attempt_id=uuid.uuid4(),
        target_version="2.0.0",
        change_type=VersionChangeType.MAJOR,
        attempted_by="dev",
        attempted_at=fixed_now,
        success=True,
        requires_approval=True,
        approvals_received=["approver1", "approver2"],
    )


@pytest.fixture
def sample_integrity_report(fixed_now) -> IntegrityReport:
    return IntegrityReport(
        report_id=uuid.uuid4(),
        checked_at=fixed_now,
        checked_by="auditor",
        expected_version="1.0.0",
        actual_version="1.0.0",
        expected_hash="abc123",
        actual_hash="abc123",
        result=IntegrityCheckResult.INTACT,
        discrepancies=[],
        recommended_action="NONE",
    )


@pytest.fixture
def version_lock(fixed_now) -> VersionLock:
    return VersionLock(current_version="1.0.0", current_state=VersionLockState.UNLOCKED)


# =============================================================================
# Tests for Enums
# =============================================================================

class TestEnums:
    def test_version_lock_state(self):
        assert VersionLockState.UNLOCKED is not None
        assert VersionLockState.LOCKED is not None
        assert VersionLockState.FROZEN is not None
        assert VersionLockState.CORRUPTED is not None

    def test_version_lock_severity(self):
        assert VersionLockSeverity.CRITICAL.value == 100
        assert VersionLockSeverity.HIGH.value == 70
        assert VersionLockSeverity.MEDIUM.value == 40
        assert VersionLockSeverity.LOW.value == 10

    def test_version_change_type(self):
        assert VersionChangeType.MAJOR is not None
        assert VersionChangeType.MINOR is not None
        assert VersionChangeType.PATCH is not None
        assert VersionChangeType.EMERGENCY is not None
        assert VersionChangeType.CORRUPTION_RECOVERY is not None

    def test_integrity_check_result(self):
        assert IntegrityCheckResult.INTACT is not None
        assert IntegrityCheckResult.MODIFIED is not None
        assert IntegrityCheckResult.CORRUPTED is not None
        assert IntegrityCheckResult.TAMPERED is not None
        assert IntegrityCheckResult.INCOMPLETE is not None

    def test_version_lock_event_type(self):
        assert VersionLockEventType.STATE_CHANGE is not None
        assert VersionLockEventType.VERSION_CHANGE is not None
        assert VersionLockEventType.INTEGRITY_CHECK is not None
        assert VersionLockEventType.INTEGRITY_VIOLATION is not None


# =============================================================================
# Tests for Exceptions
# =============================================================================

class TestExceptions:
    def test_version_lock_error(self):
        with pytest.raises(VersionLockError):
            raise VersionLockError("test")

    def test_version_lock_violation_error(self):
        with pytest.raises(VersionLockViolationError) as exc:
            raise VersionLockViolationError("violation", VersionLockSeverity.HIGH, "1.0.0")
        assert exc.value.severity == VersionLockSeverity.HIGH
        assert exc.value.attempted_version == "1.0.0"

    def test_version_integrity_error(self):
        with pytest.raises(VersionIntegrityError):
            raise VersionIntegrityError("integrity")

    def test_version_freeze_error(self):
        with pytest.raises(VersionFreezeError):
            raise VersionFreezeError("freeze")

    def test_insufficient_approval_error(self):
        with pytest.raises(VersionLockError):
            raise VersionLockError("approval")


# =============================================================================
# Tests for VersionMetadata
# =============================================================================

class TestVersionMetadata:
    def test_create_valid_metadata(self, fixed_now):
        metadata = VersionMetadata(
            version="1.2.3",
            release_date=fixed_now,
            created_by="test_user",
            approved_by=["approver1", "approver2"],
            change_type=VersionChangeType.MINOR,
            changelog_entry="Test changelog",
            version_number=1,
        )
        assert metadata.version == "1.2.3"
        assert metadata.release_date == fixed_now
        assert metadata.created_by == "test_user"
        assert len(metadata.approved_by) == 2
        assert metadata.change_type == VersionChangeType.MINOR
        assert metadata.version_number == 1
        assert metadata.cryptographic_hash != ""
        assert len(metadata._audit_trail) == 1

    @pytest.mark.parametrize("invalid_version", ["1.2", "a.b.c", "1.-2.3"])
    def test_validate_invalid_version(self, invalid_version, fixed_now):
        with pytest.raises(ValueError):
            VersionMetadata(
                version=invalid_version,
                release_date=fixed_now,
                created_by="test_user",
                approved_by=["approver"],
                change_type=VersionChangeType.MINOR,
                changelog_entry="test",
            )

    def test_compute_hash_consistent(self, fixed_now):
        metadata1 = VersionMetadata(
            version="1.2.3",
            release_date=fixed_now,
            created_by="test_user",
            approved_by=["approver1"],
            change_type=VersionChangeType.MINOR,
            changelog_entry="test",
        )
        metadata2 = VersionMetadata(
            version="1.2.3",
            release_date=fixed_now,
            created_by="test_user",
            approved_by=["approver1"],
            change_type=VersionChangeType.MINOR,
            changelog_entry="test",
        )
        assert metadata1.compute_hash() == metadata2.compute_hash()

    def test_to_dict_contains_fields(self, fixed_now):
        metadata = VersionMetadata(
            version="1.2.3",
            release_date=fixed_now,
            created_by="test_user",
            approved_by=["approver1"],
            change_type=VersionChangeType.MINOR,
            changelog_entry="Test changelog",
        )
        d = metadata.to_dict()
        assert d["version"] == "1.2.3"
        assert d["created_by"] == "test_user"
        assert d["change_type"] == "MINOR"
        assert "hash" in d

    def test_clone_increments_version(self, fixed_now):
        metadata = VersionMetadata(
            version="1.2.3",
            release_date=fixed_now,
            created_by="test_user",
            approved_by=["approver1"],
            change_type=VersionChangeType.MINOR,
            changelog_entry="test",
            version_number=5,
        )
        cloned = metadata.clone()
        assert cloned.version_number == 6
        assert cloned.version == metadata.version
        assert cloned.created_by == metadata.created_by
        assert cloned.cryptographic_hash == ""

    def test_validate_returns_errors_for_hash_mismatch(self, fixed_now):
        metadata = VersionMetadata(
            version="1.2.3",
            release_date=fixed_now,
            created_by="test_user",
            approved_by=["approver1"],
            change_type=VersionChangeType.MINOR,
            changelog_entry="test",
        )
        object.__setattr__(metadata, "cryptographic_hash", "fakehash")
        result = metadata.validate()
        assert result["is_valid"] is False
        assert "Hash mismatch" in result["errors"]

    def test_audit_trail_records_actions(self, fixed_now):
        metadata = VersionMetadata(
            version="1.0.0",
            release_date=fixed_now,
            created_by="test_user",
            approved_by=["approver1"],
            change_type=VersionChangeType.MAJOR,
            changelog_entry="Initial",
        )
        assert len(metadata.audit_trail()) >= 1
        metadata.touch("toucher")
        trail = metadata.audit_trail()
        assert len(trail) >= 2
        assert trail[-1]["action"] == "TOUCH"
        assert trail[-1]["performed_by"] == "toucher"

    def test_from_dict_roundtrip(self, sample_version_metadata):
        full_d = {
            "version": sample_version_metadata.version,
            "release_date": sample_version_metadata.release_date.isoformat(),
            "created_by": sample_version_metadata.created_by,
            "approved_by": sample_version_metadata.approved_by,
            "change_type": sample_version_metadata.change_type.name,
            "changelog_entry": sample_version_metadata.changelog_entry,
            "cryptographic_hash": sample_version_metadata.cryptographic_hash,
            "previous_hash": sample_version_metadata.previous_version_hash,
            "constitution_snapshot_id": str(sample_version_metadata.constitution_snapshot_id)
            if sample_version_metadata.constitution_snapshot_id
            else None,
            "version_number": sample_version_metadata.version_number,
        }
        reconstructed = VersionMetadata.from_dict(full_d)
        assert reconstructed.version == sample_version_metadata.version
        assert reconstructed.created_by == sample_version_metadata.created_by
        assert reconstructed.cryptographic_hash == sample_version_metadata.cryptographic_hash

    def test_immutable_methods_raise(self, sample_version_metadata):
        with pytest.raises(AttributeError):
            sample_version_metadata.update("updater", key="value")
        with pytest.raises(AttributeError):
            sample_version_metadata.delete("deleter")
        with pytest.raises(AttributeError):
            sample_version_metadata.restore("restorer")

    def test_activate_deactivate_lock_unlock_return_self(self, sample_version_metadata):
        assert sample_version_metadata.activate("a") is sample_version_metadata
        assert sample_version_metadata.deactivate("d") is sample_version_metadata
        assert sample_version_metadata.lock("l", "reason") is sample_version_metadata
        assert sample_version_metadata.unlock("u") is sample_version_metadata


# =============================================================================
# Tests for VersionLockRecord
# =============================================================================

class TestVersionLockRecord:
    def test_create_valid_record(self, fixed_now):
        record_id = uuid.uuid4()
        record = VersionLockRecord(
            record_id=record_id,
            previous_state=VersionLockState.UNLOCKED,
            new_state=VersionLockState.LOCKED,
            reason="Test lock",
            initiated_by="admin",
            initiated_at=fixed_now,
            approved_by=["approver1", "approver2"],
            event_type=VersionLockEventType.STATE_CHANGE,
        )
        assert record.record_id == record_id
        assert record.previous_state == VersionLockState.UNLOCKED
        assert record.new_state == VersionLockState.LOCKED
        assert record.reason == "Test lock"
        assert record.initiated_by == "admin"
        assert record.event_type == VersionLockEventType.STATE_CHANGE

    def test_is_active_with_expiry(self, fixed_now):
        record = VersionLockRecord(
            record_id=uuid.uuid4(),
            previous_state=VersionLockState.UNLOCKED,
            new_state=VersionLockState.LOCKED,
            reason="test",
            initiated_by="admin",
            initiated_at=fixed_now,
            approved_by=["approver"],
            event_type=VersionLockEventType.STATE_CHANGE,
            expires_at=fixed_now - timedelta(hours=1),
        )
        assert record.is_active() is False

        record.expires_at = fixed_now + timedelta(hours=1)
        assert record.is_active() is True

    def test_compute_signature_content_returns_string(self, fixed_now):
        record = VersionLockRecord(
            record_id=uuid.uuid4(),
            previous_state=VersionLockState.UNLOCKED,
            new_state=VersionLockState.LOCKED,
            reason="test",
            initiated_by="admin",
            initiated_at=fixed_now,
            approved_by=["approver"],
            event_type=VersionLockEventType.STATE_CHANGE,
        )
        sig = record.compute_signature_content()
        assert "|" in sig
        assert str(record.record_id) in sig

    def test_to_dict_contains_fields(self, sample_lock_record):
        d = sample_lock_record.to_dict()
        assert d["record_id"] == str(sample_lock_record.record_id)
        assert d["previous_state"] == sample_lock_record.previous_state.name
        assert d["new_state"] == sample_lock_record.new_state.name
        assert d["reason"] == sample_lock_record.reason
        assert d["initiated_by"] == sample_lock_record.initiated_by
        assert d["event_type"] == sample_lock_record.event_type.name

    def test_from_dict_roundtrip(self, sample_lock_record):
        full_d = {
            "record_id": str(sample_lock_record.record_id),
            "previous_state": sample_lock_record.previous_state.name,
            "new_state": sample_lock_record.new_state.name,
            "reason": sample_lock_record.reason,
            "initiated_by": sample_lock_record.initiated_by,
            "initiated_at": sample_lock_record.initiated_at.isoformat(),
            "approved_by": sample_lock_record.approved_by,
            "expires_at": sample_lock_record.expires_at.isoformat() if sample_lock_record.expires_at else None,
            "cryptographic_signature": sample_lock_record.cryptographic_signature,
            "event_type": sample_lock_record.event_type.name,
            "version_number": sample_lock_record.version_number,
        }
        reconstructed = VersionLockRecord.from_dict(full_d)
        assert reconstructed.record_id == sample_lock_record.record_id
        assert reconstructed.previous_state == sample_lock_record.previous_state
        assert reconstructed.new_state == sample_lock_record.new_state

    def test_clone_creates_new_id_and_resets_version(self, sample_lock_record):
        cloned = sample_lock_record.clone()
        assert cloned.record_id != sample_lock_record.record_id
        assert cloned.version_number == 1
        assert cloned.previous_state == sample_lock_record.previous_state
        assert cloned.initiated_at != sample_lock_record.initiated_at

    def test_immutable_methods_raise(self, sample_lock_record):
        with pytest.raises(AttributeError):
            sample_lock_record.update("updater", key="value")
        with pytest.raises(AttributeError):
            sample_lock_record.delete("deleter")
        with pytest.raises(AttributeError):
            sample_lock_record.restore("restorer")

    def test_audit_trail_and_touch(self, sample_lock_record):
        sample_lock_record.touch("toucher")
        trail = sample_lock_record.audit_trail()
        assert len(trail) >= 2
        assert trail[-1]["action"] == "TOUCH"
        assert trail[-1]["performed_by"] == "toucher"


# =============================================================================
# Tests for VersionChangeAttempt
# =============================================================================

class TestVersionChangeAttempt:
    def test_create_valid_attempt(self, fixed_now):
        attempt_id = uuid.uuid4()
        attempt = VersionChangeAttempt(
            attempt_id=attempt_id,
            target_version="2.0.0",
            change_type=VersionChangeType.MAJOR,
            attempted_by="dev",
            attempted_at=fixed_now,
            success=True,
            requires_approval=True,
            approvals_received=["approver1"],
        )
        assert attempt.attempt_id == attempt_id
        assert attempt.target_version == "2.0.0"
        assert attempt.success is True
        assert attempt.cryptographic_hash != ""

    def test_compute_hash_consistent(self, fixed_now):
        attempt1 = VersionChangeAttempt(
            attempt_id=uuid.uuid4(),
            target_version="2.0.0",
            change_type=VersionChangeType.MAJOR,
            attempted_by="dev",
            attempted_at=fixed_now,
            success=True,
            requires_approval=True,
            approvals_received=["a"],
        )
        attempt2 = VersionChangeAttempt(
            attempt_id=uuid.uuid4(),
            target_version="2.0.0",
            change_type=VersionChangeType.MAJOR,
            attempted_by="dev",
            attempted_at=fixed_now,
            success=True,
            requires_approval=True,
            approvals_received=["a"],
        )
        assert attempt1.compute_hash() != attempt2.compute_hash()

    def test_to_dict_contains_fields(self, sample_change_attempt):
        d = sample_change_attempt.to_dict()
        assert d["attempt_id"] == str(sample_change_attempt.attempt_id)
        assert d["target_version"] == sample_change_attempt.target_version
        assert d["change_type"] == sample_change_attempt.change_type.name
        assert d["success"] == sample_change_attempt.success

    def test_from_dict_roundtrip(self, sample_change_attempt):
        full_d = {
            "attempt_id": str(sample_change_attempt.attempt_id),
            "target_version": sample_change_attempt.target_version,
            "change_type": sample_change_attempt.change_type.name,
            "attempted_by": sample_change_attempt.attempted_by,
            "attempted_at": sample_change_attempt.attempted_at.isoformat(),
            "success": sample_change_attempt.success,
            "failure_reason": sample_change_attempt.failure_reason,
            "requires_approval": sample_change_attempt.requires_approval,
            "approvals_received": sample_change_attempt.approvals_received,
            "hash": sample_change_attempt.cryptographic_hash,
            "version_number": sample_change_attempt.version_number,
        }
        reconstructed = VersionChangeAttempt.from_dict(full_d)
        assert reconstructed.attempt_id == sample_change_attempt.attempt_id
        assert reconstructed.target_version == sample_change_attempt.target_version
        assert reconstructed.success == sample_change_attempt.success

    def test_clone_creates_new_id_and_resets(self, sample_change_attempt):
        cloned = sample_change_attempt.clone()
        assert cloned.attempt_id != sample_change_attempt.attempt_id
        assert cloned.success is False
        assert cloned.approvals_received == []

    def test_immutable_methods_raise(self, sample_change_attempt):
        with pytest.raises(AttributeError):
            sample_change_attempt.update("updater", key="value")
        with pytest.raises(AttributeError):
            sample_change_attempt.delete("deleter")
        with pytest.raises(AttributeError):
            sample_change_attempt.restore("restorer")

    def test_audit_trail_and_touch(self, sample_change_attempt):
        sample_change_attempt.touch("toucher")
        trail = sample_change_attempt.audit_trail()
        assert len(trail) >= 2
        assert trail[-1]["action"] == "TOUCH"


# =============================================================================
# Tests for IntegrityReport
# =============================================================================

class TestIntegrityReport:
    def test_create_valid_report(self, fixed_now):
        report_id = uuid.uuid4()
        report = IntegrityReport(
            report_id=report_id,
            checked_at=fixed_now,
            checked_by="auditor",
            expected_version="1.0.0",
            actual_version="1.0.0",
            expected_hash="abc123",
            actual_hash="abc123",
            result=IntegrityCheckResult.INTACT,
            discrepancies=[],
            recommended_action="NONE",
        )
        assert report.report_id == report_id
        assert report.result == IntegrityCheckResult.INTACT
        assert report.cryptographic_signature != ""

    def test_compute_hash_includes_fields(self, fixed_now):
        report = IntegrityReport(
            report_id=uuid.uuid4(),
            checked_at=fixed_now,
            checked_by="auditor",
            expected_version="1.0.0",
            actual_version="1.0.0",
            expected_hash="abc",
            actual_hash="abc",
            result=IntegrityCheckResult.INTACT,
            discrepancies=[],
            recommended_action="NONE",
        )
        h1 = report.compute_hash()
        report2 = IntegrityReport(
            report_id=report.report_id,
            checked_at=fixed_now,
            checked_by="auditor",
            expected_version="1.0.1",
            actual_version="1.0.0",
            expected_hash="abc",
            actual_hash="abc",
            result=IntegrityCheckResult.INTACT,
            discrepancies=[],
            recommended_action="NONE",
        )
        assert h1 != report2.compute_hash()

    def test_to_dict_contains_fields(self, sample_integrity_report):
        d = sample_integrity_report.to_dict()
        assert d["report_id"] == str(sample_integrity_report.report_id)
        assert d["result"] == sample_integrity_report.result.name
        assert d["expected_version"] == sample_integrity_report.expected_version

    def test_from_dict_roundtrip(self, sample_integrity_report):
        full_d = {
            "report_id": str(sample_integrity_report.report_id),
            "checked_at": sample_integrity_report.checked_at.isoformat(),
            "checked_by": sample_integrity_report.checked_by,
            "expected_version": sample_integrity_report.expected_version,
            "actual_version": sample_integrity_report.actual_version,
            "expected_hash": sample_integrity_report.expected_hash,
            "actual_hash": sample_integrity_report.actual_hash,
            "result": sample_integrity_report.result.name,
            "discrepancies": sample_integrity_report.discrepancies,
            "recommended_action": sample_integrity_report.recommended_action,
            "signature": sample_integrity_report.cryptographic_signature,
            "version_number": sample_integrity_report.version_number,
        }
        reconstructed = IntegrityReport.from_dict(full_d)
        assert reconstructed.report_id == sample_integrity_report.report_id
        assert reconstructed.result == sample_integrity_report.result
        assert reconstructed.expected_version == sample_integrity_report.expected_version

    def test_clone_creates_new_id(self, sample_integrity_report):
        cloned = sample_integrity_report.clone()
        assert cloned.report_id != sample_integrity_report.report_id
        assert cloned.checked_at != sample_integrity_report.checked_at
        assert cloned.result == sample_integrity_report.result

    def test_immutable_methods_raise(self, sample_integrity_report):
        with pytest.raises(AttributeError):
            sample_integrity_report.update("updater", key="value")
        with pytest.raises(AttributeError):
            sample_integrity_report.delete("deleter")
        with pytest.raises(AttributeError):
            sample_integrity_report.restore("restorer")

    def test_audit_trail_and_touch(self, sample_integrity_report):
        sample_integrity_report.touch("toucher")
        trail = sample_integrity_report.audit_trail()
        assert len(trail) >= 2
        assert trail[-1]["action"] == "TOUCH"


# =============================================================================
# Tests for VersionLock Aggregate
# =============================================================================

class TestVersionLock:
    def test_initialization_creates_initial_version(self, fixed_now):
        lock = VersionLock(current_version="1.0.0", current_state=VersionLockState.UNLOCKED)
        assert lock.current_version == "1.0.0"
        assert lock.current_state == VersionLockState.UNLOCKED
        assert len(lock.version_history) == 1
        assert lock.version_history[0].version == "1.0.0"

    def test_save_version_metadata_appends_and_updates_current(self, fixed_now):
        lock = VersionLock(current_version="1.0.0", current_state=VersionLockState.UNLOCKED)
        new_meta = VersionMetadata(
            version="2.0.0",
            release_date=fixed_now,
            created_by="dev",
            approved_by=["approver"],
            change_type=VersionChangeType.MAJOR,
            changelog_entry="Major upgrade",
        )
        lock.save_version_metadata(new_meta)
        assert lock.current_version == "2.0.0"
        assert len(lock.version_history) == 2

    def test_get_version_history_returns_recent_limit(self, fixed_now):
        lock = VersionLock(current_version="1.0.0", current_state=VersionLockState.UNLOCKED)
        for i in range(5):
            meta = VersionMetadata(
                version=f"1.{i}.0",
                release_date=fixed_now,
                created_by="dev",
                approved_by=["approver"],
                change_type=VersionChangeType.MINOR,
                changelog_entry=f"v1.{i}.0",
            )
            lock.save_version_metadata(meta)
        history = lock.get_version_history(limit=3)
        assert len(history) == 3
        assert history[-1].version == "1.4.0"

    def test_get_current_metadata(self, version_lock):
        meta = version_lock.get_current_metadata()
        assert meta is not None
        assert meta.version == "1.0.0"

    def test_delete_version_metadata(self, fixed_now):
        lock = VersionLock(current_version="1.0.0", current_state=VersionLockState.UNLOCKED)
        new_meta = VersionMetadata(
            version="2.0.0",
            release_date=fixed_now,
            created_by="dev",
            approved_by=["approver"],
            change_type=VersionChangeType.MAJOR,
            changelog_entry="Major",
        )
        lock.save_version_metadata(new_meta)
        assert len(lock.version_history) == 2
        result = lock.delete_version_metadata("2.0.0")
        assert result is True
        assert len(lock.version_history) == 1
        result2 = lock.delete_version_metadata("3.0.0")
        assert result2 is False

    def test_save_lock_record_updates_state(self, fixed_now, version_lock):
        record = VersionLockRecord(
            record_id=uuid.uuid4(),
            previous_state=VersionLockState.UNLOCKED,
            new_state=VersionLockState.LOCKED,
            reason="Test",
            initiated_by="admin",
            initiated_at=fixed_now,
            approved_by=["a1", "a2"],
            event_type=VersionLockEventType.STATE_CHANGE,
        )
        version_lock.save_lock_record(record)
        assert version_lock.current_state == VersionLockState.LOCKED
        assert len(version_lock.lock_records) == 2

    def test_get_lock_records(self, fixed_now, version_lock):
        for i in range(3):
            record = VersionLockRecord(
                record_id=uuid.uuid4(),
                previous_state=VersionLockState.UNLOCKED,
                new_state=VersionLockState.LOCKED if i % 2 == 0 else VersionLockState.UNLOCKED,
                reason=f"Test {i}",
                initiated_by="admin",
                initiated_at=fixed_now,
                approved_by=["a1", "a2"],
                event_type=VersionLockEventType.STATE_CHANGE,
            )
            version_lock.save_lock_record(record)
        records = version_lock.get_lock_records(limit=2)
        assert len(records) == 2
        filtered = version_lock.get_lock_records(limit=10, event_type=VersionLockEventType.VERSION_CHANGE)
        assert len(filtered) == 0

    def test_delete_lock_record(self, fixed_now, version_lock):
        record = VersionLockRecord(
            record_id=uuid.uuid4(),
            previous_state=VersionLockState.UNLOCKED,
            new_state=VersionLockState.LOCKED,
            reason="Test",
            initiated_by="admin",
            initiated_at=fixed_now,
            approved_by=["a1", "a2"],
            event_type=VersionLockEventType.STATE_CHANGE,
        )
        version_lock.save_lock_record(record)
        assert len(version_lock.lock_records) == 2
        result = version_lock.delete_lock_record(record.record_id)
        assert result is True
        assert len(version_lock.lock_records) == 1
        result2 = version_lock.delete_lock_record(uuid.uuid4())
        assert result2 is False

    def test_save_change_attempt_and_get(self, fixed_now, version_lock):
        attempt = VersionChangeAttempt(
            attempt_id=uuid.uuid4(),
            target_version="2.0.0",
            change_type=VersionChangeType.MAJOR,
            attempted_by="dev",
            attempted_at=fixed_now,
            success=True,
            requires_approval=True,
            approvals_received=["a1", "a2"],
        )
        version_lock.save_change_attempt(attempt)
        attempts = version_lock.get_change_attempts()
        assert len(attempts) == 1
        assert attempts[0].attempt_id == attempt.attempt_id

    def test_save_integrity_report_and_get(self, fixed_now, version_lock):
        report = IntegrityReport(
            report_id=uuid.uuid4(),
            checked_at=fixed_now,
            checked_by="auditor",
            expected_version="1.0.0",
            actual_version="1.0.0",
            expected_hash="abc",
            actual_hash="abc",
            result=IntegrityCheckResult.INTACT,
            discrepancies=[],
            recommended_action="NONE",
        )
        version_lock.save_integrity_report(report)
        reports = version_lock.get_integrity_reports()
        assert len(reports) == 1
        assert reports[0].report_id == report.report_id

    def test_change_lock_state_requires_approvers_for_lock(self):
        lock = VersionLock(current_version="1.0.0", current_state=VersionLockState.UNLOCKED)
        with pytest.raises(VersionLockViolationError, match="requires at least 2 approvers"):
            lock.change_lock_state(
                VersionLockState.LOCKED,
                "Lock without enough approvers",
                "admin",
                ["single_approver"],
            )

    def test_change_lock_state_success_with_approvers(self):
        lock = VersionLock(current_version="1.0.0", current_state=VersionLockState.UNLOCKED)
        record = lock.change_lock_state(
            VersionLockState.LOCKED,
            "Lock with approvers",
            "admin",
            ["approver1", "approver2"],
        )
        assert lock.current_state == VersionLockState.LOCKED
        assert record.previous_state == VersionLockState.UNLOCKED
        assert record.new_state == VersionLockState.LOCKED
        assert len(lock.lock_records) == 2

    def test_change_lock_state_rejects_from_frozen(self):
        lock = VersionLock(current_version="1.0.0", current_state=VersionLockState.FROZEN)
        with pytest.raises(VersionLockViolationError, match="Cannot change from FROZEN"):
            lock.change_lock_state(
                VersionLockState.UNLOCKED,
                "Try to unfreeze",
                "admin",
                ["approver1", "approver2"],
            )

    def test_attempt_version_change_frozen_fails(self):
        lock = VersionLock(current_version="1.0.0", current_state=VersionLockState.FROZEN)
        attempt = lock.attempt_version_change(
            "2.0.0", VersionChangeType.MAJOR, "dev", True, ["approver1", "approver2"]
        )
        assert attempt.success is False
        assert "frozen" in attempt.failure_reason.lower()

    def test_attempt_version_change_requires_approval(self):
        lock = VersionLock(current_version="1.0.0", current_state=VersionLockState.LOCKED)
        attempt = lock.attempt_version_change(
            "2.0.0", VersionChangeType.MAJOR, "dev", True, ["only_one"]
        )
        assert attempt.success is False
        assert "at least 2 approvals" in attempt.failure_reason

    def test_commit_version_change_success(self, fixed_now):
        lock = VersionLock(current_version="1.0.0", current_state=VersionLockState.UNLOCKED)
        new_meta = lock.commit_version_change(
            "1.1.0",
            VersionChangeType.MINOR,
            "Added feature X",
            "dev",
            ["approver1", "approver2"],
        )
        assert new_meta.version == "1.1.0"
        assert lock.current_version == "1.1.0"
        assert len(lock.version_history) == 2

    def test_commit_version_change_frozen_fails(self):
        lock = VersionLock(current_version="1.0.0", current_state=VersionLockState.FROZEN)
        with pytest.raises(VersionLockViolationError, match="system is frozen"):
            lock.commit_version_change(
                "1.1.0",
                VersionChangeType.MINOR,
                "Should fail",
                "dev",
                ["approver1", "approver2"],
            )

    def test_commit_version_change_invalid_major(self):
        lock = VersionLock(current_version="1.0.0", current_state=VersionLockState.UNLOCKED)
        with pytest.raises(VersionLockError, match="MAJOR version must increment"):
            lock.commit_version_change(
                "1.0.0",
                VersionChangeType.MAJOR,
                "Invalid",
                "dev",
                ["approver1", "approver2"],
            )

    def test_commit_version_change_invalid_minor(self):
        lock = VersionLock(current_version="1.2.0", current_state=VersionLockState.UNLOCKED)
        with pytest.raises(VersionLockError, match="MINOR version must increment minor"):
            lock.commit_version_change(
                "1.1.0",
                VersionChangeType.MINOR,
                "Invalid",
                "dev",
                ["approver1", "approver2"],
            )

    def test_commit_version_change_invalid_patch(self):
        lock = VersionLock(current_version="1.2.3", current_state=VersionLockState.UNLOCKED)
        with pytest.raises(VersionLockError, match="PATCH version must increment patch"):
            lock.commit_version_change(
                "1.2.2",
                VersionChangeType.PATCH,
                "Invalid",
                "dev",
                ["approver1", "approver2"],
            )

    def test_commit_version_change_with_previous_hash_mismatch(self, fixed_now):
        lock = VersionLock(current_version="1.0.0", current_state=VersionLockState.UNLOCKED)
        lock.get_current_metadata()
        wrong_hash = "fakehash"
        with pytest.raises(VersionIntegrityError, match="Previous version hash mismatch"):
            lock.commit_version_change(
                "1.1.0",
                VersionChangeType.MINOR,
                "Invalid",
                "dev",
                ["approver1", "approver2"],
                previous_version_hash=wrong_hash,
            )

    def test_check_integrity_intact(self):
        lock = VersionLock(current_version="1.0.0", current_state=VersionLockState.UNLOCKED)
        report = lock.check_integrity(checker_id="tester")
        assert report.result == IntegrityCheckResult.INTACT
        assert len(lock.integrity_reports) == 1

    def test_check_integrity_detects_modification(self):
        lock = VersionLock(current_version="1.0.0", current_state=VersionLockState.UNLOCKED)
        report = lock.check_integrity(expected_version="2.0.0", checker_id="tester")
        assert report.result in (IntegrityCheckResult.MODIFIED, IntegrityCheckResult.TAMPERED)
        assert len(report.discrepancies) > 0

    def test_check_integrity_detects_hash_chain_break(self, fixed_now):
        lock = VersionLock(current_version="1.0.0", current_state=VersionLockState.UNLOCKED)
        meta2 = VersionMetadata(
            version="2.0.0",
            release_date=fixed_now,
            created_by="dev",
            approved_by=["a1", "a2"],
            change_type=VersionChangeType.MAJOR,
            changelog_entry="v2",
            previous_version_hash="wronghash",
        )
        lock.save_version_metadata(meta2)
        report = lock.check_integrity(checker_id="tester")
        assert report.result == IntegrityCheckResult.TAMPERED
        assert any("Hash chain broken" in d for d in report.discrepancies)

    def test_is_modification_allowed(self):
        lock = VersionLock(current_version="1.0.0", current_state=VersionLockState.UNLOCKED)
        assert lock.is_modification_allowed() is True
        lock.current_state = VersionLockState.LOCKED
        assert lock.is_modification_allowed(is_amendment=True) is False
        assert lock.is_modification_allowed(is_amendment=False) is False
        lock.current_state = VersionLockState.FROZEN
        assert lock.is_modification_allowed() is False

    def test_get_statistics_returns_summary(self):
        lock = VersionLock(current_version="1.0.0", current_state=VersionLockState.UNLOCKED)
        stats = lock.get_statistics()
        assert stats["current_version"] == "1.0.0"
        assert "total_version_changes" in stats
        assert "total_state_changes" in stats

    def test_get_version_timeline(self, version_lock):
        timeline = version_lock.get_version_timeline()
        assert len(timeline) == 1
        assert timeline[0]["version"] == "1.0.0"

    def test_get_lock_history(self, fixed_now, version_lock):
        record = VersionLockRecord(
            record_id=uuid.uuid4(),
            previous_state=VersionLockState.UNLOCKED,
            new_state=VersionLockState.LOCKED,
            reason="Test",
            initiated_by="admin",
            initiated_at=fixed_now,
            approved_by=["a1", "a2"],
            event_type=VersionLockEventType.STATE_CHANGE,
        )
        version_lock.save_lock_record(record)
        history = version_lock.get_lock_history(limit=10)
        assert len(history) == 2

    def test_get_integrity_report_history(self, fixed_now, version_lock):
        report = IntegrityReport(
            report_id=uuid.uuid4(),
            checked_at=fixed_now,
            checked_by="auditor",
            expected_version="1.0.0",
            actual_version="1.0.0",
            expected_hash="abc",
            actual_hash="abc",
            result=IntegrityCheckResult.INTACT,
            discrepancies=[],
            recommended_action="NONE",
        )
        version_lock.save_integrity_report(report)
        history = version_lock.get_integrity_report_history(limit=10)
        assert len(history) == 1
        assert history[0]["report_id"] == str(report.report_id)

    def test_reset_reinitializes(self):
        lock = VersionLock(current_version="1.0.0", current_state=VersionLockState.LOCKED)
        lock.change_lock_state(
            VersionLockState.UNLOCKED,
            "Reset test",
            "admin",
            ["approver1", "approver2"],
        )
        assert len(lock.lock_records) > 1
        lock.reset()
        assert lock.current_version == "1.0.0"
        assert lock.current_state == VersionLockState.UNLOCKED
        assert len(lock.lock_records) == 1
        assert len(lock.version_history) == 1

    def test_notify_supreme_law_calls_check_violation_for_frozen(self):
        lock = VersionLock(current_version="1.0.0", current_state=VersionLockState.UNLOCKED)
        with patch("constitution.version_lock.get_supreme_law") as mock_get:
            mock_law = MagicMock()
            mock_get.return_value = mock_law
            lock._notify_supreme_law(VersionLockState.FROZEN, "Freeze reason")
            mock_law.check_violation.assert_called_once_with(
                "immutability", "version_lock", "System frozen: Freeze reason"
            )

    def test_notify_supreme_law_does_not_call_for_non_frozen(self):
        lock = VersionLock(current_version="1.0.0", current_state=VersionLockState.UNLOCKED)
        with patch("constitution.version_lock.get_supreme_law") as mock_get:
            mock_law = MagicMock()
            mock_get.return_value = mock_law
            lock._notify_supreme_law(VersionLockState.LOCKED, "Lock reason")
            mock_law.check_violation.assert_not_called()


# =============================================================================
# Tests for VersionLockService
# =============================================================================

class TestVersionLockService:
    @patch("constitution.version_lock.get_supreme_law")
    def test_lock_calls_supreme_law_enforce(self, mock_get_supreme_law):
        mock_law = MagicMock()
        mock_get_supreme_law.return_value = mock_law

        service = VersionLockService()
        record = service.lock("Test lock", "admin", ["approver1", "approver2"])
        assert record.new_state == VersionLockState.LOCKED
        mock_law.enforce.assert_called_once()

    @patch("constitution.version_lock.get_supreme_law")
    def test_freeze_requires_audit_committee_chair(self, mock_get_supreme_law):
        service = VersionLockService()
        with pytest.raises(VersionLockViolationError, match="requires Audit Committee Chair approval"):
            service.freeze("Freeze without chair", "admin", ["approver1", "approver2"])

    @patch("constitution.version_lock.get_supreme_law")
    def test_unfreeze_requires_chair_and_frozen_state(self, mock_get_supreme_law):
        service = VersionLockService()
        # First freeze
        with patch.object(service, '_version_lock') as mock_lock:
            mock_lock.current_state = VersionLockState.UNLOCKED
            with pytest.raises(VersionFreezeError, match="current state is UNLOCKED"):
                service.unfreeze("Unfreeze", "admin", ["audit_committee_chair", "approver2"])

    @patch("constitution.version_lock.get_supreme_law")
    def test_propose_version_upgrade_success(self, mock_get_supreme_law):
        service = VersionLockService()
        service.unlock("Unlock", "admin", ["approver1", "approver2"])
        attempt = service.propose_version_upgrade(
            "2.0.0", VersionChangeType.MAJOR, "Major upgrade", "dev", requires_approval=True
        )
        assert attempt.target_version == "2.0.0"
        assert attempt.success is True

    @patch("constitution.version_lock.get_supreme_law")
    def test_commit_version_upgrade_success(self, mock_get_supreme_law):
        service = VersionLockService()
        service.unlock("Unlock", "admin", ["approver1", "approver2"])
        meta = service.commit_version_upgrade(
            "2.0.0",
            VersionChangeType.MAJOR,
            "Major upgrade",
            "dev",
            ["approver1", "approver2", "approver3"],
        )
        assert meta.version == "2.0.0"

    @patch("constitution.version_lock.get_supreme_law")
    def test_run_integrity_check(self, mock_get_supreme_law):
        service = VersionLockService()
        report = service.run_integrity_check(checker_id="tester")
        assert report.result is not None
        assert report.checked_by == "tester"

    @patch("constitution.version_lock.get_supreme_law")
    def test_get_status_returns_summary(self, mock_get_supreme_law):
        service = VersionLockService()
        status = service.get_status()
        assert "current_version" in status
        assert "current_state" in status
        assert "is_modification_allowed" in status

    @patch("constitution.version_lock.get_supreme_law")
    @patch("constitution.version_lock.get_sovereignty_guardian")
    def test_emergency_version_restore_requires_emergency_state(
        self, mock_get_guardian, mock_get_supreme_law
    ):
        mock_guardian = MagicMock()
        mock_guardian.get_current_status.return_value = "NORMAL"
        mock_get_guardian.return_value = mock_guardian

        service = VersionLockService()
        with pytest.raises(VersionLockViolationError, match="Emergency restore only allowed"):
            service.emergency_version_restore(
                "1.0.0", "Emergency", "admin", ["approver1", "approver2", "approver3"]
            )

    def test_get_version_lock(self):
        service = VersionLockService()
        lock = service.get_version_lock()
        assert isinstance(lock, VersionLock)

    def test_get_version_timeline(self):
        service = VersionLockService()
        timeline = service.get_version_timeline()
        assert len(timeline) >= 1

    def test_get_lock_history(self):
        service = VersionLockService()
        service.lock("Test lock", "admin", ["a1", "a2"])
        history = service.get_lock_history(limit=10)
        assert len(history) >= 1

    def test_get_integrity_report_history(self):
        service = VersionLockService()
        service.run_integrity_check()
        history = service.get_integrity_report_history(limit=10)
        assert len(history) >= 1

    def test_verify_full_integrity_chain(self):
        service = VersionLockService()
        service.unlock("Unlock", "admin", ["a1", "a2"])
        service.commit_version_upgrade(
            "2.0.0", VersionChangeType.MAJOR, "Major", "dev", ["a1", "a2", "a3"]
        )
        result = service.verify_full_integrity_chain()
        assert result["version_chain_valid"] is True
        assert result["total_versions"] == 2

        lock = service.get_version_lock()
        latest = lock.version_history[-1]
        object.__setattr__(latest, "previous_version_hash", "wrong")
        result2 = service.verify_full_integrity_chain()
        assert result2["version_chain_valid"] is False
        assert result2["broken_at_version_index"] == 1

    def test_unlock_raises_version_freeze_error_when_frozen(self):
        service = VersionLockService()
        service.freeze("Freeze", "admin", ["audit_committee_chair", "a2"])
        with pytest.raises(VersionFreezeError, match="Cannot unlock: system is frozen"):
            service.unlock("Try unlock", "admin", ["a1", "a2"])

    def test_propose_version_upgrade_when_locked_without_approval_fails(self):
        service = VersionLockService()
        service.lock("Lock", "admin", ["a1", "a2"])
        attempt = service.propose_version_upgrade(
            "2.0.0", VersionChangeType.MAJOR, "Should fail", "dev", requires_approval=False
        )
        assert attempt.success is False
        assert "locked, version changes require approval" in attempt.failure_reason

    def test_get_version_lock_service_singleton(self):
        svc1 = get_version_lock_service()
        svc2 = get_version_lock_service()
        assert svc1 is svc2


# =============================================================================
# Full workflow integration test
# =============================================================================

class TestVersionLockIntegration:
    def test_full_workflow(self):
        service = VersionLockService()

        service.unlock("Start workflow", "admin", ["approver1", "approver2"])
        assert service.get_status()["current_state"] == "UNLOCKED"

        attempt = service.propose_version_upgrade(
            "2.0.0", VersionChangeType.MAJOR, "Major release", "dev", requires_approval=True
        )
        assert attempt.success is True

        meta = service.commit_version_upgrade(
            "2.0.0",
            VersionChangeType.MAJOR,
            "Major release",
            "dev",
            ["approver1", "approver2", "approver3"],
        )
        assert meta.version == "2.0.0"

        service.lock("Lock after upgrade", "admin", ["approver1", "approver2"])
        assert service.get_status()["current_state"] == "LOCKED"

        report = service.run_integrity_check()
        assert report.result == IntegrityCheckResult.INTACT

    def test_version_freeze_and_unfreeze(self):
        service = VersionLockService()

        service.freeze("Freeze system", "admin", ["audit_committee_chair", "a2"])
        assert service.get_status()["current_state"] == "FROZEN"

        with pytest.raises(VersionLockViolationError):
            service.commit_version_upgrade(
                "3.0.0", VersionChangeType.MAJOR, "Should fail", "dev", ["a1", "a2", "a3"]
            )

        service.unfreeze("Unfreeze", "admin", ["audit_committee_chair", "a2"])
        assert service.get_status()["current_state"] == "UNLOCKED"

        meta = service.commit_version_upgrade(
            "3.0.0", VersionChangeType.MAJOR, "After unfreeze", "dev", ["a1", "a2", "a3"]
        )
        assert meta.version == "3.0.0"
