#!/usr/bin/env python3
"""
tests/unit/test_version_lock.py
Test untuk constitution/version_lock.py
Mencakup: VersionMetadata, VersionLockRecord, VersionChangeAttempt,
IntegrityReport, VersionLock, VersionLockService
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from constitution.version_lock import (
    IntegrityCheckResult,
    IntegrityReport,
    VersionChangeAttempt,
    VersionChangeType,
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


class TestVersionMetadata:
    def test_create_valid_metadata(self):
        """Test creation of valid VersionMetadata."""
        now = datetime.now(UTC)
        metadata = VersionMetadata(
            version="1.2.3",
            release_date=now,
            created_by="test_user",
            approved_by=["approver1", "approver2"],
            change_type=VersionChangeType.MINOR,
            changelog_entry="Test changelog",
            version_number=1,
        )
        assert metadata.version == "1.2.3"
        assert metadata.release_date == now
        assert metadata.created_by == "test_user"
        assert len(metadata.approved_by) == 2
        assert metadata.change_type == VersionChangeType.MINOR
        assert metadata.version_number == 1
        assert metadata.cryptographic_hash != ""
        assert len(metadata._audit_trail) == 1

    def test_validate_invalid_semantic_version(self):
        """Test validation rejects invalid semantic version."""
        now = datetime.now(UTC)
        with pytest.raises(ValueError, match="Invalid semantic version"):
            VersionMetadata(
                version="1.2",
                release_date=now,
                created_by="test_user",
                approved_by=["approver"],
                change_type=VersionChangeType.MINOR,
                changelog_entry="test",
            )
        with pytest.raises(ValueError, match="Invalid semantic version"):
            VersionMetadata(
                version="a.b.c",
                release_date=now,
                created_by="test_user",
                approved_by=["approver"],
                change_type=VersionChangeType.MINOR,
                changelog_entry="test",
            )

    def test_validate_negative_version_components(self):
        """Test validation rejects negative version numbers."""
        now = datetime.now(UTC)
        with pytest.raises(ValueError, match="non-negative"):
            VersionMetadata(
                version="1.-2.3",
                release_date=now,
                created_by="test_user",
                approved_by=["approver"],
                change_type=VersionChangeType.MINOR,
                changelog_entry="test",
            )

    def test_compute_hash_consistent(self):
        """Test hash computation is deterministic."""
        now = datetime.now(UTC)
        metadata1 = VersionMetadata(
            version="1.2.3",
            release_date=now,
            created_by="test_user",
            approved_by=["approver1"],
            change_type=VersionChangeType.MINOR,
            changelog_entry="test",
        )
        metadata2 = VersionMetadata(
            version="1.2.3",
            release_date=now,
            created_by="test_user",
            approved_by=["approver1"],
            change_type=VersionChangeType.MINOR,
            changelog_entry="test",
        )
        assert metadata1.compute_hash() == metadata2.compute_hash()

    def test_to_dict_contains_expected_fields(self):
        """Test to_dict returns expected structure."""
        now = datetime.now(UTC)
        metadata = VersionMetadata(
            version="1.2.3",
            release_date=now,
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

    def test_clone_increments_version(self):
        """Test clone creates new version with incremented version number."""
        now = datetime.now(UTC)
        metadata = VersionMetadata(
            version="1.2.3",
            release_date=now,
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

    def test_validate_returns_errors_for_invalid(self):
        """Test validate method returns errors for invalid state."""
        now = datetime.now(UTC)
        metadata = VersionMetadata(
            version="1.2.3",
            release_date=now,
            created_by="test_user",
            approved_by=["approver1"],
            change_type=VersionChangeType.MINOR,
            changelog_entry="test",
        )
        # Force hash mismatch by modifying internal state
        object.__setattr__(metadata, "cryptographic_hash", "fakehash")
        result = metadata.validate()
        assert result["is_valid"] is False
        assert "Hash mismatch" in result["errors"]

    def test_audit_trail_records_actions(self):
        """Test audit trail records actions correctly."""
        now = datetime.now(UTC)
        metadata = VersionMetadata(
            version="1.0.0",
            release_date=now,
            created_by="test_user",
            approved_by=["approver1"],
            change_type=VersionChangeType.MAJOR,
            changelog_entry="Initial",
        )
        # CREATE already recorded
        assert len(metadata.audit_trail()) >= 1
        metadata.touch("toucher")
        trail = metadata.audit_trail()
        assert len(trail) >= 2
        assert trail[-1]["action"] == "TOUCH"
        assert trail[-1]["performed_by"] == "toucher"


class TestVersionLockRecord:
    def test_create_valid_record(self):
        """Test creation of valid VersionLockRecord."""
        record_id = uuid.uuid4()
        now = datetime.now(UTC)
        record = VersionLockRecord(
            record_id=record_id,
            previous_state=VersionLockState.UNLOCKED,
            new_state=VersionLockState.LOCKED,
            reason="Test lock",
            initiated_by="admin",
            initiated_at=now,
            approved_by=["approver1", "approver2"],
            event_type=VersionLockEventType.STATE_CHANGE,
        )
        assert record.record_id == record_id
        assert record.previous_state == VersionLockState.UNLOCKED
        assert record.new_state == VersionLockState.LOCKED
        assert record.reason == "Test lock"
        assert record.initiated_by == "admin"
        assert record.event_type == VersionLockEventType.STATE_CHANGE

    def test_is_active_with_expiry(self):
        """Test is_active returns correct based on expiry."""
        record = VersionLockRecord(
            record_id=uuid.uuid4(),
            previous_state=VersionLockState.UNLOCKED,
            new_state=VersionLockState.LOCKED,
            reason="test",
            initiated_by="admin",
            initiated_at=datetime.now(UTC),
            approved_by=["approver"],
            event_type=VersionLockEventType.STATE_CHANGE,
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )
        assert record.is_active() is False

        record.expires_at = datetime.now(UTC) + timedelta(hours=1)
        assert record.is_active() is True

    def test_compute_signature_content_returns_string(self):
        """Test compute_signature_content returns deterministic string."""
        record = VersionLockRecord(
            record_id=uuid.uuid4(),
            previous_state=VersionLockState.UNLOCKED,
            new_state=VersionLockState.LOCKED,
            reason="test",
            initiated_by="admin",
            initiated_at=datetime.now(UTC),
            approved_by=["approver"],
            event_type=VersionLockEventType.STATE_CHANGE,
        )
        sig = record.compute_signature_content()
        assert "|" in sig
        assert str(record.record_id) in sig


class TestVersionChangeAttempt:
    def test_create_valid_attempt(self):
        """Test creation of valid VersionChangeAttempt."""
        attempt_id = uuid.uuid4()
        now = datetime.now(UTC)
        attempt = VersionChangeAttempt(
            attempt_id=attempt_id,
            target_version="2.0.0",
            change_type=VersionChangeType.MAJOR,
            attempted_by="dev",
            attempted_at=now,
            success=True,
            requires_approval=True,
            approvals_received=["approver1"],
        )
        assert attempt.attempt_id == attempt_id
        assert attempt.target_version == "2.0.0"
        assert attempt.success is True
        assert attempt.cryptographic_hash != ""

    def test_compute_hash_consistent(self):
        """Test hash computation for attempt."""
        now = datetime.now(UTC)
        attempt1 = VersionChangeAttempt(
            attempt_id=uuid.uuid4(),
            target_version="2.0.0",
            change_type=VersionChangeType.MAJOR,
            attempted_by="dev",
            attempted_at=now,
            success=True,
            requires_approval=True,
            approvals_received=["a"],
        )
        attempt2 = VersionChangeAttempt(
            attempt_id=uuid.uuid4(),
            target_version="2.0.0",
            change_type=VersionChangeType.MAJOR,
            attempted_by="dev",
            attempted_at=now,
            success=True,
            requires_approval=True,
            approvals_received=["a"],
        )
        # Different attempt_id -> different hash
        assert attempt1.compute_hash() != attempt2.compute_hash()


class TestIntegrityReport:
    def test_create_valid_report(self):
        """Test creation of valid IntegrityReport."""
        report_id = uuid.uuid4()
        now = datetime.now(UTC)
        report = IntegrityReport(
            report_id=report_id,
            checked_at=now,
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

    def test_compute_hash_includes_fields(self):
        """Test hash includes all fields."""
        now = datetime.now(UTC)
        report = IntegrityReport(
            report_id=uuid.uuid4(),
            checked_at=now,
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
            checked_at=now,
            checked_by="auditor",
            expected_version="1.0.1",  # different
            actual_version="1.0.0",
            expected_hash="abc",
            actual_hash="abc",
            result=IntegrityCheckResult.INTACT,
            discrepancies=[],
            recommended_action="NONE",
        )
        assert h1 != report2.compute_hash()


class TestVersionLock:
    def test_initialization_creates_initial_version(self):
        """Test VersionLock initializes with version 1.0.0."""
        lock = VersionLock(current_version="1.0.0", current_state=VersionLockState.UNLOCKED)
        assert lock.current_version == "1.0.0"
        assert lock.current_state == VersionLockState.UNLOCKED
        assert len(lock.version_history) == 1
        assert lock.version_history[0].version == "1.0.0"

    def test_save_version_metadata_appends_and_updates_current(self):
        """Test save_version_metadata updates current version."""
        lock = VersionLock(current_version="1.0.0", current_state=VersionLockState.UNLOCKED)
        now = datetime.now(UTC)
        new_meta = VersionMetadata(
            version="2.0.0",
            release_date=now,
            created_by="dev",
            approved_by=["approver"],
            change_type=VersionChangeType.MAJOR,
            changelog_entry="Major upgrade",
        )
        lock.save_version_metadata(new_meta)
        assert lock.current_version == "2.0.0"
        assert len(lock.version_history) == 2

    def test_get_version_history_returns_recent_limit(self):
        """Test get_version_history respects limit."""
        lock = VersionLock(current_version="1.0.0", current_state=VersionLockState.UNLOCKED)
        now = datetime.now(UTC)
        for i in range(5):
            meta = VersionMetadata(
                version=f"1.{i}.0",
                release_date=now,
                created_by="dev",
                approved_by=["approver"],
                change_type=VersionChangeType.MINOR,
                changelog_entry=f"v1.{i}.0",
            )
            lock.save_version_metadata(meta)
        history = lock.get_version_history(limit=3)
        assert len(history) == 3
        assert history[-1].version == "1.4.0"

    def test_change_lock_state_requires_approvers_for_lock(self):
        """Test locking requires at least 2 approvers."""
        lock = VersionLock(current_version="1.0.0", current_state=VersionLockState.UNLOCKED)
        with pytest.raises(VersionLockViolationError, match="requires at least 2 approvers"):
            lock.change_lock_state(
                VersionLockState.LOCKED,
                "Lock without enough approvers",
                "admin",
                ["single_approver"],  # only 1
            )

    def test_change_lock_state_success_with_approvers(self):
        """Test lock state change succeeds with proper approvers."""
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
        assert len(lock.lock_records) == 2  # initial + new

    def test_change_lock_state_rejects_from_frozen(self):
        """Test cannot change from FROZEN except to CORRUPTED."""
        lock = VersionLock(current_version="1.0.0", current_state=VersionLockState.FROZEN)
        with pytest.raises(VersionLockViolationError, match="Cannot change from FROZEN"):
            lock.change_lock_state(
                VersionLockState.UNLOCKED,
                "Try to unfreeze",
                "admin",
                ["approver1", "approver2"],
            )

    def test_attempt_version_change_frozen_fails(self):
        """Test attempt_version_change fails when FROZEN."""
        lock = VersionLock(current_version="1.0.0", current_state=VersionLockState.FROZEN)
        attempt = lock.attempt_version_change(
            "2.0.0", VersionChangeType.MAJOR, "dev", True, ["approver1", "approver2"]
        )
        assert attempt.success is False
        assert "frozen" in attempt.failure_reason.lower()

    def test_attempt_version_change_requires_approval(self):
        """Test requires_approval check."""
        lock = VersionLock(current_version="1.0.0", current_state=VersionLockState.LOCKED)
        attempt = lock.attempt_version_change(
            "2.0.0", VersionChangeType.MAJOR, "dev", True, ["only_one"]
        )
        assert attempt.success is False
        assert "at least 2 approvals" in attempt.failure_reason

    def test_commit_version_change_success(self):
        """Test commit_version_change creates new version."""
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
        """Test commit_version_change fails when FROZEN."""
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
        """Test MAJOR version must increment."""
        lock = VersionLock(current_version="1.0.0", current_state=VersionLockState.UNLOCKED)
        with pytest.raises(VersionLockError, match="MAJOR version must increment"):
            lock.commit_version_change(
                "1.0.0",  # same
                VersionChangeType.MAJOR,
                "Invalid",
                "dev",
                ["approver1", "approver2"],
            )

    def test_check_integrity_intact(self):
        """Test integrity check returns INTACT for valid state."""
        lock = VersionLock(current_version="1.0.0", current_state=VersionLockState.UNLOCKED)
        report = lock.check_integrity(checker_id="tester")
        assert report.result == IntegrityCheckResult.INTACT
        assert len(lock.integrity_reports) == 1

    def test_check_integrity_detects_modification(self):
        """Test integrity check detects version mismatch."""
        lock = VersionLock(current_version="1.0.0", current_state=VersionLockState.UNLOCKED)
        report = lock.check_integrity(expected_version="2.0.0", checker_id="tester")
        assert report.result in (
            IntegrityCheckResult.MODIFIED,
            IntegrityCheckResult.TAMPERED,
        )
        assert len(report.discrepancies) > 0

    def test_is_modification_allowed(self):
        """Test is_modification_allowed returns correct based on state."""
        lock = VersionLock(current_version="1.0.0", current_state=VersionLockState.UNLOCKED)
        assert lock.is_modification_allowed() is True

        lock.current_state = VersionLockState.LOCKED
        assert lock.is_modification_allowed(is_amendment=True) is False
        assert lock.is_modification_allowed(is_amendment=False) is False

        lock.current_state = VersionLockState.FROZEN
        assert lock.is_modification_allowed() is False

    def test_get_statistics_returns_summary(self):
        """Test get_statistics returns aggregated data."""
        lock = VersionLock(current_version="1.0.0", current_state=VersionLockState.UNLOCKED)
        stats = lock.get_statistics()
        assert stats["current_version"] == "1.0.0"
        assert "total_version_changes" in stats
        assert "total_state_changes" in stats

    def test_reset_reinitializes(self):
        """Test reset clears history and reinitializes."""
        lock = VersionLock(current_version="1.0.0", current_state=VersionLockState.LOCKED)
        # Add some data
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


class TestVersionLockService:
    @patch("constitution.version_lock.get_supreme_law")
    def test_lock_calls_supreme_law_enforce(self, mock_get_supreme_law):
        """Test lock method enforces constitutional principle."""
        mock_law = MagicMock()
        mock_get_supreme_law.return_value = mock_law

        service = VersionLockService()
        record = service.lock(
            "Test lock",
            "admin",
            ["approver1", "approver2"],
        )
        assert record.new_state == VersionLockState.LOCKED
        mock_law.enforce.assert_called_once()

    @patch("constitution.version_lock.get_supreme_law")
    def test_freeze_requires_audit_committee_chair(self, mock_get_supreme_law):
        """Test freeze requires Audit Committee Chair approval."""
        service = VersionLockService()
        with pytest.raises(Exception, match="requires Audit Committee Chair approval"):
            service.freeze(
                "Freeze without chair",
                "admin",
                ["approver1", "approver2"],  # no chair
            )

    @patch("constitution.version_lock.get_supreme_law")
    def test_unfreeze_requires_chair_and_frozen_state(self, mock_get_supreme_law):
        """Test unfreeze requires frozen state and chair approval."""
        service = VersionLockService()
        # Not frozen
        with pytest.raises(Exception, match="current state is UNLOCKED"):
            service.unfreeze(
                "Unfreeze when not frozen",
                "admin",
                ["audit_committee_chair", "approver2"],
            )

    @patch("constitution.version_lock.get_supreme_law")
    def test_propose_version_upgrade_success(self, mock_get_supreme_law):
        """Test propose_version_upgrade creates attempt."""
        service = VersionLockService()
        # Unlock first
        service.unlock("Unlock for test", "admin", ["approver1", "approver2"])

        attempt = service.propose_version_upgrade(
            "2.0.0",
            VersionChangeType.MAJOR,
            "Major upgrade",
            "dev",
            requires_approval=True,
        )
        assert attempt.target_version == "2.0.0"
        assert attempt.success is True

    @patch("constitution.version_lock.get_supreme_law")
    def test_commit_version_upgrade_success(self, mock_get_supreme_law):
        """Test commit_version_upgrade creates new version."""
        service = VersionLockService()
        service.unlock("Unlock for test", "admin", ["approver1", "approver2"])

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
        """Test run_integrity_check creates report."""
        service = VersionLockService()
        report = service.run_integrity_check(checker_id="tester")
        assert report.result is not None
        assert report.checked_by == "tester"

    @patch("constitution.version_lock.get_supreme_law")
    def test_get_status_returns_summary(self, mock_get_supreme_law):
        """Test get_status returns status dictionary."""
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
        """Test emergency restore requires emergency lockdown."""
        mock_guardian = MagicMock()
        mock_guardian.get_current_status.return_value = "NORMAL"  # not emergency
        mock_get_guardian.return_value = mock_guardian

        service = VersionLockService()
        with pytest.raises(VersionLockViolationError, match="Emergency restore only allowed"):
            service.emergency_version_restore(
                "1.0.0",
                "Emergency restore",
                "admin",
                ["approver1", "approver2", "approver3"],
            )

    def test_get_version_lock_service_singleton(self):
        """Test get_version_lock_service returns singleton."""
        svc1 = get_version_lock_service()
        svc2 = get_version_lock_service()
        assert svc1 is svc2


class TestVersionLockIntegration:
    def test_full_workflow(self):
        """Test complete workflow from unlock to lock to version upgrade."""
        service = VersionLockService()

        # 1. Unlock
        service.unlock("Start workflow", "admin", ["approver1", "approver2"])
        assert service.get_status()["current_state"] == "UNLOCKED"

        # 2. Propose version upgrade
        attempt = service.propose_version_upgrade(
            "2.0.0",
            VersionChangeType.MAJOR,
            "Major release",
            "dev",
            requires_approval=True,
        )
        assert attempt.success is True

        # 3. Commit version upgrade
        meta = service.commit_version_upgrade(
            "2.0.0",
            VersionChangeType.MAJOR,
            "Major release",
            "dev",
            ["approver1", "approver2", "approver3"],
        )
        assert meta.version == "2.0.0"

        # 4. Lock
        service.lock("Lock after upgrade", "admin", ["approver1", "approver2"])
        assert service.get_status()["current_state"] == "LOCKED"

        # 5. Integrity check
        report = service.run_integrity_check()
        assert report.result == IntegrityCheckResult.INTACT