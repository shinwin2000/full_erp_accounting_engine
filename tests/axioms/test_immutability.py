#!/usr/bin/env python3
"""
tests/unit/test_immutability.py
Test untuk axioms/immutability.py
Mencakup: ImmutableRecord, CorrectionRecord, ImmutabilityViolation,
ImmutabilityValidator, ImmutabilityAxiom, helper functions
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from axioms.immutability import (
    CorrectionMethod,
    CorrectionRecord,
    DataState,
    ImmutabilityAxiom,
    ImmutabilityHashChainError,
    ImmutabilityValidator,
    ImmutabilityViolation,
    ImmutabilityViolationError,
    ImmutabilityViolationSeverity,
    ImmutableRecord,
    ImmutableRecordType,
    create_immutable_record,
    get_immutability_axiom,
    record_type_from_string,
    state_from_string,
)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_test_record(
    record_type: ImmutableRecordType = ImmutableRecordType.JOURNAL,
    aggregate_id: UUID | None = None,
    version: int = 1,
    is_active: bool = True,
) -> ImmutableRecord:
    if aggregate_id is None:
        aggregate_id = uuid.uuid4()
    data = {"amount": 1000, "description": "Test"}
    data_hash = hashlib.sha3_256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    return ImmutableRecord(
        record_id=uuid.uuid4(),
        record_type=record_type,
        aggregate_id=aggregate_id,
        version=version,
        data_hash=data_hash,
        previous_hash=None,
        timestamp=datetime.now(UTC),
        created_by="tester",
        signature="test_signature",
        is_active=is_active,
    )


def create_test_correction() -> CorrectionRecord:
    return CorrectionRecord(
        correction_id=uuid.uuid4(),
        original_record_id=uuid.uuid4(),
        correction_method=CorrectionMethod.REVERSAL_JOURNAL,
        correction_record_id=uuid.uuid4(),
        reason="Test correction",
        authorized_by="admin",
        authorized_at=datetime.now(UTC),
        approved_by=["approver1", "approver2"],
        audit_reference="AUDIT-001",
    )


def create_test_violation() -> ImmutabilityViolation:
    return ImmutabilityViolation(
        violation_id=uuid.uuid4(),
        target_record_id=uuid.uuid4(),
        target_aggregate_id=uuid.uuid4(),
        attempted_operation="UPDATE",
        attempted_by="user123",
        attempted_at=datetime.now(UTC),
        source_module="test_module",
        severity=ImmutabilityViolationSeverity.HIGH,
        message="Test violation",
        was_blocked=True,
        bypass_attempted=False,
        forensic_evidence_hash="",
    )


# ============================================================================
# TESTS FOR ImmutableRecord
# ============================================================================

class TestImmutableRecord:
    def test_create_valid_record(self):
        record = create_test_record()
        assert record.record_id is not None
        assert record.record_type == ImmutableRecordType.JOURNAL
        assert record.aggregate_id is not None
        assert record.version == 1
        assert record.is_active is True
        assert record.data_hash != ""
        assert record.cryptographic_hash != ""
        assert record._version == 1

    def test_validate_version_positive(self):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            ImmutableRecord(
                record_id=uuid.uuid4(),
                record_type=ImmutableRecordType.JOURNAL,
                aggregate_id=uuid.uuid4(),
                version=0,
                data_hash="abc",
                previous_hash=None,
                timestamp=datetime.now(UTC),
                created_by="tester",
                signature="sig",
                _version=1,
            )

    def test_validate__version_positive(self):
        with pytest.raises(ValueError, match="_version must be >= 1"):
            ImmutableRecord(
                record_id=uuid.uuid4(),
                record_type=ImmutableRecordType.JOURNAL,
                aggregate_id=uuid.uuid4(),
                version=1,
                data_hash="abc",
                previous_hash=None,
                timestamp=datetime.now(UTC),
                created_by="tester",
                signature="sig",
                _version=0,
            )

    def test_compute_data_hash_consistent(self):
        record = create_test_record()
        data = {"amount": 1000, "description": "Test"}
        h1 = record.compute_data_hash(data)
        h2 = record.compute_data_hash(data)
        assert h1 == h2
        data2 = {"amount": 2000, "description": "Test"}
        assert h1 != record.compute_data_hash(data2)

    def test_compute_chain_hash_consistent(self):
        record = create_test_record()
        h1 = record.compute_chain_hash()
        h2 = record.compute_chain_hash()
        assert h1 == h2

    def test_compute_hash_consistent(self):
        record = create_test_record()
        h1 = record.compute_hash()
        h2 = record.compute_hash()
        assert h1 == h2

    def test_update_raises(self):
        record = create_test_record()
        with pytest.raises(AttributeError):
            record.update("admin", data_hash="new")

    def test_delete_marks_deleted(self):
        record = create_test_record()
        deleted = record.delete("admin", "test")
        assert deleted.deleted_at is not None
        assert deleted.deleted_by == "admin"
        assert deleted._version == record._version + 1

    def test_restore_recovers_deleted(self):
        record = create_test_record()
        deleted = record.delete("admin", "test")
        restored = deleted.restore("admin")
        assert restored.deleted_at is None
        assert restored.deleted_by is None
        assert restored._version == deleted._version + 1

    def test_restore_not_deleted_raises(self):
        record = create_test_record()
        with pytest.raises(ValueError, match="Record not deleted"):
            record.restore("admin")

    def test_activate_does_nothing_if_active(self):
        record = create_test_record()
        activated = record.activate("admin")
        assert activated is record

    def test_activate_activates_inactive(self):
        record = create_test_record(is_active=False)
        activated = record.activate("admin")
        assert activated.is_active is True
        assert activated._version == record._version + 1

    def test_deactivate_does_nothing_if_inactive(self):
        record = create_test_record(is_active=False)
        deactivated = record.deactivate("admin", "test")
        assert deactivated is record

    def test_deactivate_deactivates_active(self):
        record = create_test_record()
        deactivated = record.deactivate("admin", "test")
        assert deactivated.is_active is False
        assert deactivated._version == record._version + 1

    def test_deactivate_default_alias(self):
        record = create_test_record()
        deactivated = record.deactivate_default()
        assert deactivated.is_active is False
        assert deactivated._version == record._version + 1

    def test_lock_returns_self(self):
        record = create_test_record()
        locked = record.lock("admin", "test")
        assert locked is record

    def test_unlock_returns_self(self):
        record = create_test_record()
        unlocked = record.unlock("admin")
        assert unlocked is record

    def test_validate_returns_valid(self):
        record = create_test_record()
        result = record.validate()
        assert result["is_valid"] is True
        assert result["record_id"] == str(record.record_id)

    def test_validate_returns_errors_on_hash_mismatch(self):
        record = create_test_record()
        object.__setattr__(record, "cryptographic_hash", "fake")
        result = record.validate()
        assert result["is_valid"] is False
        assert "Hash mismatch" in result["errors"]

    def test_to_dict_contains_fields(self):
        record = create_test_record()
        d = record.to_dict()
        assert d["record_type"] == "JOURNAL"
        assert d["aggregate_id"] == str(record.aggregate_id)
        assert d["is_active"] is True
        assert "record_id" in d

    def test_from_dict_reconstructs(self):
        record = create_test_record()
        d = record.to_dict()
        # Need to add full data_hash for reconstruction
        d["data_hash"] = record.data_hash
        d["signature"] = record.signature
        reconstructed = ImmutableRecord.from_dict(d)
        assert reconstructed.record_id == record.record_id
        assert reconstructed.record_type == record.record_type
        assert reconstructed.aggregate_id == record.aggregate_id
        assert reconstructed.version == record.version

    def test_clone_creates_new_instance(self):
        record = create_test_record()
        cloned = record.clone()
        assert cloned.record_id != record.record_id
        assert cloned.aggregate_id == record.aggregate_id
        assert cloned.record_type == record.record_type
        assert cloned.version == record.version
        assert cloned._version == 1
        assert cloned.is_active is True

    def test_snapshot_returns_summary(self):
        record = create_test_record()
        snap = record.snapshot()
        assert snap["record_id"] == str(record.record_id)
        assert snap["is_active"] == record.is_active
        assert "timestamp" in snap

    def test_version_method(self):
        record = create_test_record()
        assert record.version() == 1

    def test_audit_trail_records_actions(self):
        record = create_test_record()
        assert len(record.audit_trail()) >= 1
        record.touch("toucher")
        trail = record.audit_trail()
        assert len(trail) >= 2
        assert trail[-1]["action"] == "TOUCH"

    def test_touch_increments_version(self):
        record = create_test_record()
        touched = record.touch("toucher")
        assert touched._version == record._version + 1


# ============================================================================
# TESTS FOR CorrectionRecord
# ============================================================================

class TestCorrectionRecord:
    def test_create_valid_correction(self):
        correction = create_test_correction()
        assert correction.correction_id is not None
        assert correction.original_record_id is not None
        assert correction.correction_method == CorrectionMethod.REVERSAL_JOURNAL
        assert correction.reason == "Test correction"
        assert len(correction.approved_by) == 2
        assert correction.version == 1
        assert correction.cryptographic_hash != ""

    def test_validate_requires_approvers(self):
        with pytest.raises(ValueError, match="At least one approver required"):
            CorrectionRecord(
                correction_id=uuid.uuid4(),
                original_record_id=uuid.uuid4(),
                correction_method=CorrectionMethod.REVERSAL_JOURNAL,
                correction_record_id=uuid.uuid4(),
                reason="test",
                authorized_by="admin",
                authorized_at=datetime.now(UTC),
                approved_by=[],
                audit_reference="AUDIT-001",
            )

    def test_update_raises(self):
        correction = create_test_correction()
        with pytest.raises(AttributeError):
            correction.update("admin", reason="new")

    def test_delete_marks_deleted(self):
        correction = create_test_correction()
        deleted = correction.delete("admin", "test")
        assert deleted.deleted_at is not None
        assert deleted.deleted_by == "admin"
        assert deleted.version == correction.version + 1

    def test_restore_recovers_deleted(self):
        correction = create_test_correction()
        deleted = correction.delete("admin", "test")
        restored = deleted.restore("admin")
        assert restored.deleted_at is None
        assert restored.deleted_by is None
        assert restored.version == deleted.version + 1

    def test_restore_not_deleted_raises(self):
        correction = create_test_correction()
        with pytest.raises(ValueError, match="Not deleted"):
            correction.restore("admin")

    def test_activate_returns_self(self):
        correction = create_test_correction()
        activated = correction.activate("admin")
        assert activated is correction

    def test_deactivate_returns_self(self):
        correction = create_test_correction()
        deactivated = correction.deactivate("admin")
        assert deactivated is correction

    def test_lock_returns_self(self):
        correction = create_test_correction()
        locked = correction.lock("admin", "test")
        assert locked is correction

    def test_unlock_returns_self(self):
        correction = create_test_correction()
        unlocked = correction.unlock("admin")
        assert unlocked is correction

    def test_validate_returns_valid(self):
        correction = create_test_correction()
        result = correction.validate()
        assert result["is_valid"] is True
        assert result["correction_id"] == str(correction.correction_id)

    def test_validate_returns_errors_on_hash_mismatch(self):
        correction = create_test_correction()
        object.__setattr__(correction, "cryptographic_hash", "fake")
        result = correction.validate()
        assert result["is_valid"] is False
        assert "Hash mismatch" in result["errors"]

    def test_to_dict_contains_fields(self):
        correction = create_test_correction()
        d = correction.to_dict()
        assert d["correction_method"] == "REVERSAL_JOURNAL"
        assert d["reason"] == "Test correction"
        assert d["audit_reference"] == "AUDIT-001"
        assert "correction_id" in d

    def test_from_dict_reconstructs(self):
        correction = create_test_correction()
        d = correction.to_dict()
        reconstructed = CorrectionRecord.from_dict(d)
        assert reconstructed.correction_id == correction.correction_id
        assert reconstructed.original_record_id == correction.original_record_id
        assert reconstructed.correction_method == correction.correction_method
        assert reconstructed.reason == correction.reason
        assert reconstructed.approved_by == correction.approved_by

    def test_clone_creates_new_instance(self):
        correction = create_test_correction()
        cloned = correction.clone()
        assert cloned.correction_id != correction.correction_id
        assert cloned.original_record_id == correction.original_record_id
        assert cloned.correction_method == correction.correction_method
        assert cloned.version == 1

    def test_snapshot_returns_summary(self):
        correction = create_test_correction()
        snap = correction.snapshot()
        assert snap["correction_id"] == str(correction.correction_id)
        assert snap["method"] == correction.correction_method.name

    def test_get_version(self):
        correction = create_test_correction()
        assert correction.get_version() == 1

    def test_audit_trail_records(self):
        correction = create_test_correction()
        assert len(correction.audit_trail()) >= 1
        correction.touch("toucher")
        trail = correction.audit_trail()
        assert trail[-1]["action"] == "TOUCH"

    def test_touch_increments_version(self):
        correction = create_test_correction()
        touched = correction.touch("toucher")
        assert touched.version == correction.version + 1


# ============================================================================
# TESTS FOR ImmutabilityViolation
# ============================================================================

class TestImmutabilityViolation:
    def test_create_valid_violation(self):
        violation = create_test_violation()
        assert violation.violation_id is not None
        assert violation.target_record_id is not None
        assert violation.target_aggregate_id is not None
        assert violation.severity == ImmutabilityViolationSeverity.HIGH
        assert violation.was_blocked is True
        assert violation.forensic_evidence_hash != ""
        assert violation.cryptographic_hash != ""
        assert violation.version == 1

    def test_validate_returns_valid(self):
        violation = create_test_violation()
        result = violation.validate()
        assert result["is_valid"] is True
        assert result["violation_id"] == str(violation.violation_id)

    def test_validate_returns_errors_on_hash_mismatch(self):
        violation = create_test_violation()
        object.__setattr__(violation, "cryptographic_hash", "fake")
        result = violation.validate()
        assert result["is_valid"] is False
        assert "Hash mismatch" in result["errors"]

    def test_validate_returns_errors_on_forensic_hash_mismatch(self):
        violation = create_test_violation()
        object.__setattr__(violation, "forensic_evidence_hash", "fake")
        result = violation.validate()
        assert result["is_valid"] is False
        assert "Forensic hash mismatch" in result["errors"]

    def test_update_raises(self):
        violation = create_test_violation()
        with pytest.raises(AttributeError):
            violation.update("admin", message="new")

    def test_delete_raises(self):
        violation = create_test_violation()
        with pytest.raises(AttributeError):
            violation.delete("admin")

    def test_restore_raises(self):
        violation = create_test_violation()
        with pytest.raises(AttributeError):
            violation.restore("admin")

    def test_activate_returns_self(self):
        violation = create_test_violation()
        activated = violation.activate("admin")
        assert activated is violation

    def test_deactivate_returns_self(self):
        violation = create_test_violation()
        deactivated = violation.deactivate("admin")
        assert deactivated is violation

    def test_lock_returns_self(self):
        violation = create_test_violation()
        locked = violation.lock("admin", "test")
        assert locked is violation

    def test_unlock_returns_self(self):
        violation = create_test_violation()
        unlocked = violation.unlock("admin")
        assert unlocked is violation

    def test_to_dict_contains_fields(self):
        violation = create_test_violation()
        d = violation.to_dict()
        assert d["severity"] == "HIGH"
        assert d["message"] == "Test violation"
        assert d["was_blocked"] is True
        assert "violation_id" in d

    def test_from_dict_reconstructs(self):
        violation = create_test_violation()
        d = violation.to_dict()
        reconstructed = ImmutabilityViolation.from_dict(d)
        assert reconstructed.violation_id == violation.violation_id
        assert reconstructed.target_record_id == violation.target_record_id
        assert reconstructed.severity == violation.severity
        assert reconstructed.was_blocked == violation.was_blocked

    def test_clone_creates_new_instance(self):
        violation = create_test_violation()
        cloned = violation.clone()
        assert cloned.violation_id != violation.violation_id
        assert cloned.target_record_id == violation.target_record_id
        assert cloned.target_aggregate_id == violation.target_aggregate_id
        assert cloned.version == 1
        assert cloned.forensic_evidence_hash == ""

    def test_snapshot_returns_summary(self):
        violation = create_test_violation()
        snap = violation.snapshot()
        assert snap["violation_id"] == str(violation.violation_id)
        assert snap["severity"] == violation.severity.name

    def test_get_version(self):
        violation = create_test_violation()
        assert violation.get_version() == 1

    def test_audit_trail_records(self):
        violation = create_test_violation()
        assert len(violation.audit_trail()) >= 1
        violation.touch("toucher")
        trail = violation.audit_trail()
        assert trail[-1]["action"] == "TOUCH"


# ============================================================================
# TESTS FOR ImmutabilityValidator
# ============================================================================

class TestImmutabilityValidator:
    def test_validate_operation_on_draft_allows(self):
        is_allowed, violation = ImmutabilityValidator.validate_operation(
            current_state=DataState.DRAFT,
            operation="UPDATE",
            aggregate_id=uuid.uuid4(),
            record_id=uuid.uuid4(),
            user_id="user",
            module="test",
        )
        assert is_allowed is True
        assert violation is None

    def test_validate_operation_on_draft_delete_allows(self):
        is_allowed, violation = ImmutabilityValidator.validate_operation(
            current_state=DataState.DRAFT,
            operation="DELETE",
            aggregate_id=uuid.uuid4(),
            record_id=uuid.uuid4(),
            user_id="user",
            module="test",
        )
        assert is_allowed is True
        assert violation is None

    def test_validate_operation_on_posted_allows_read(self):
        is_allowed, violation = ImmutabilityValidator.validate_operation(
            current_state=DataState.POSTED,
            operation="READ",
            aggregate_id=uuid.uuid4(),
            record_id=uuid.uuid4(),
            user_id="user",
            module="test",
        )
        assert is_allowed is True
        assert violation is None

    def test_validate_operation_on_posted_blocks_update(self):
        with patch("axioms.immutability.ImmutabilityValidator._notify_constitution"):
            is_allowed, violation = ImmutabilityValidator.validate_operation(
                current_state=DataState.POSTED,
                operation="UPDATE",
                aggregate_id=uuid.uuid4(),
                record_id=uuid.uuid4(),
                user_id="user",
                module="test",
            )
        assert is_allowed is False
        assert violation is not None
        assert violation.severity == ImmutabilityViolationSeverity.CRITICAL

    def test_validate_operation_on_posted_allows_correction_with_bypass(self):
        is_allowed, violation = ImmutabilityValidator.validate_operation(
            current_state=DataState.POSTED,
            operation="REVERSE",
            aggregate_id=uuid.uuid4(),
            record_id=uuid.uuid4(),
            user_id="user",
            module="test",
            is_correction=True,
            correction_method=CorrectionMethod.REVERSAL_JOURNAL,
            bypass_authorization=["approver"],
        )
        assert is_allowed is True
        assert violation is None

    def test_validate_operation_on_posted_blocks_correction_without_bypass(self):
        with patch("axioms.immutability.ImmutabilityValidator._notify_constitution"):
            is_allowed, violation = ImmutabilityValidator.validate_operation(
                current_state=DataState.POSTED,
                operation="REVERSE",
                aggregate_id=uuid.uuid4(),
                record_id=uuid.uuid4(),
                user_id="user",
                module="test",
                is_correction=True,
                correction_method=CorrectionMethod.REVERSAL_JOURNAL,
                bypass_authorization=None,
            )
        assert is_allowed is False
        assert violation is not None

    def test_validate_operation_on_submitted_modify_without_bypass_blocks(self):
        with patch("axioms.immutability.ImmutabilityValidator._notify_constitution"):
            is_allowed, violation = ImmutabilityValidator.validate_operation(
                current_state=DataState.SUBMITTED,
                operation="UPDATE",
                aggregate_id=uuid.uuid4(),
                record_id=uuid.uuid4(),
                user_id="user",
                module="test",
                bypass_authorization=None,
            )
        assert is_allowed is False
        assert violation is not None
        assert violation.severity == ImmutabilityViolationSeverity.MEDIUM

    def test_validate_operation_on_submitted_modify_with_bypass_allows(self):
        is_allowed, violation = ImmutabilityValidator.validate_operation(
            current_state=DataState.SUBMITTED,
            operation="UPDATE",
            aggregate_id=uuid.uuid4(),
            record_id=uuid.uuid4(),
            user_id="user",
            module="test",
            bypass_authorization=["approver"],
        )
        assert is_allowed is True
        assert violation is None

    def test_validate_operation_on_deleted_blocks(self):
        with patch("axioms.immutability.ImmutabilityValidator._notify_constitution"):
            is_allowed, violation = ImmutabilityValidator.validate_operation(
                current_state=DataState.DELETED,
                operation="UPDATE",
                aggregate_id=uuid.uuid4(),
                record_id=uuid.uuid4(),
                user_id="user",
                module="test",
            )
        assert is_allowed is False
        assert violation is not None

    def test_validate_state_transition_valid_posting(self):
        is_valid, violation = ImmutabilityValidator.validate_state_transition(
            from_state=DataState.APPROVED,
            to_state=DataState.POSTED,
            aggregate_id=uuid.uuid4(),
            record_id=uuid.uuid4(),
            user_id="user",
            module="test",
        )
        assert is_valid is True
        assert violation is None

    def test_validate_state_transition_invalid_posting_from_draft(self):
        with patch("axioms.immutability.ImmutabilityValidator._notify_constitution"):
            is_valid, violation = ImmutabilityValidator.validate_state_transition(
                from_state=DataState.DRAFT,
                to_state=DataState.POSTED,
                aggregate_id=uuid.uuid4(),
                record_id=uuid.uuid4(),
                user_id="user",
                module="test",
            )
        assert is_valid is False
        assert violation is not None
        assert violation.severity == ImmutabilityViolationSeverity.CRITICAL

    def test_validate_state_transition_from_posted_to_archived_allows(self):
        is_valid, violation = ImmutabilityValidator.validate_state_transition(
            from_state=DataState.POSTED,
            to_state=DataState.ARCHIVED,
            aggregate_id=uuid.uuid4(),
            record_id=uuid.uuid4(),
            user_id="user",
            module="test",
        )
        assert is_valid is True
        assert violation is None

    def test_validate_state_transition_from_posted_to_draft_blocks(self):
        with patch("axioms.immutability.ImmutabilityValidator._notify_constitution"):
            is_valid, violation = ImmutabilityValidator.validate_state_transition(
                from_state=DataState.POSTED,
                to_state=DataState.DRAFT,
                aggregate_id=uuid.uuid4(),
                record_id=uuid.uuid4(),
                user_id="user",
                module="test",
            )
        assert is_valid is False
        assert violation is not None
        assert violation.severity == ImmutabilityViolationSeverity.CATASTROPHIC

    def test_validate_state_transition_reversal_requires_approval(self):
        is_valid, violation = ImmutabilityValidator.validate_state_transition(
            from_state=DataState.POSTED,
            to_state=DataState.REVERSED,
            aggregate_id=uuid.uuid4(),
            record_id=uuid.uuid4(),
            user_id=None,  # No user, so require_approval triggers
            module="test",
            require_approval=True,
        )
        assert is_valid is False
        assert violation is not None
        assert violation.severity == ImmutabilityViolationSeverity.HIGH


# ============================================================================
# TESTS FOR ImmutabilityAxiom
# ============================================================================

class TestImmutabilityAxiom:
    def test_singleton(self):
        axiom1 = ImmutabilityAxiom()
        axiom2 = ImmutabilityAxiom()
        assert axiom1 is axiom2

    def test_save_and_get_immutable_record(self):
        axiom = ImmutabilityAxiom()
        record = create_test_record()
        axiom.save_immutable_record(record)
        retrieved = axiom.get_immutable_record(record.record_id)
        assert retrieved is not None
        assert retrieved.record_id == record.record_id

    def test_get_immutable_records_for_aggregate(self):
        axiom = ImmutabilityAxiom()
        agg_id = uuid.uuid4()
        record1 = create_test_record(aggregate_id=agg_id)
        record2 = create_test_record(aggregate_id=agg_id)
        record3 = create_test_record()
        axiom.save_immutable_record(record1)
        axiom.save_immutable_record(record2)
        axiom.save_immutable_record(record3)
        results = axiom.get_immutable_records_for_aggregate(agg_id)
        assert len(results) == 2
        assert all(r.aggregate_id == agg_id for r in results)

    def test_delete_immutable_record(self):
        axiom = ImmutabilityAxiom()
        record = create_test_record()
        axiom.save_immutable_record(record)
        result = axiom.delete_immutable_record(record.record_id)
        assert result is True
        assert axiom.get_immutable_record(record.record_id) is None

    def test_save_and_get_corrections(self):
        axiom = ImmutabilityAxiom()
        correction = create_test_correction()
        axiom.save_correction(correction)
        corrections = axiom.get_corrections()
        assert len(corrections) >= 1
        found = next((c for c in corrections if c.correction_id == correction.correction_id), None)
        assert found is not None

    def test_get_corrections_filter_by_original_record(self):
        axiom = ImmutabilityAxiom()
        original_id = uuid.uuid4()
        c1 = create_test_correction()
        c1.original_record_id = original_id
        c2 = create_test_correction()
        c2.original_record_id = original_id
        c3 = create_test_correction()
        axiom.save_correction(c1)
        axiom.save_correction(c2)
        axiom.save_correction(c3)
        results = axiom.get_corrections(original_record_id=original_id)
        assert len(results) == 2

    def test_delete_correction(self):
        axiom = ImmutabilityAxiom()
        correction = create_test_correction()
        axiom.save_correction(correction)
        result = axiom.delete_correction(correction.correction_id)
        assert result is True
        corrections = axiom.get_corrections()
        assert all(c.correction_id != correction.correction_id for c in corrections)

    def test_save_and_get_violations(self):
        axiom = ImmutabilityAxiom()
        violation = create_test_violation()
        axiom.save_violation(violation)
        violations = axiom.get_violations()
        assert len(violations) >= 1
        found = next((v for v in violations if v.violation_id == violation.violation_id), None)
        assert found is not None

    def test_get_violations_filter_by_severity(self):
        axiom = ImmutabilityAxiom()
        v1 = create_test_violation()
        v1.severity = ImmutabilityViolationSeverity.LOW
        v2 = create_test_violation()
        v2.severity = ImmutabilityViolationSeverity.CRITICAL
        axiom.save_violation(v1)
        axiom.save_violation(v2)
        result = axiom.get_violations(min_severity=ImmutabilityViolationSeverity.HIGH)
        assert all(v.severity.value >= ImmutabilityViolationSeverity.HIGH.value for v in result)

    def test_get_violations_filter_by_aggregate(self):
        axiom = ImmutabilityAxiom()
        agg_id = uuid.uuid4()
        v1 = create_test_violation()
        v1.target_aggregate_id = agg_id
        v2 = create_test_violation()
        v2.target_aggregate_id = agg_id
        v3 = create_test_violation()
        axiom.save_violation(v1)
        axiom.save_violation(v2)
        axiom.save_violation(v3)
        result = axiom.get_violations(aggregate_id=agg_id)
        assert len(result) == 2

    def test_register_immutable_record(self):
        axiom = ImmutabilityAxiom()
        record = create_test_record()
        axiom.register_immutable_record(record, verify_hash_chain=False)
        assert axiom.get_immutable_record(record.record_id) is not None

    def test_register_immutable_record_chain_verification(self):
        axiom = ImmutabilityAxiom()
        record = create_test_record()
        record.previous_hash = "some_hash"
        with pytest.raises(ImmutabilityHashChainError, match="Previous record not found"):
            axiom.register_immutable_record(record, verify_hash_chain=True)

    def test_get_and_set_aggregate_state(self):
        axiom = ImmutabilityAxiom()
        agg_id = uuid.uuid4()
        assert axiom.get_aggregate_state(agg_id) == DataState.DRAFT
        axiom.set_aggregate_state(agg_id, DataState.POSTED)
        assert axiom.get_aggregate_state(agg_id) == DataState.POSTED

    def test_enforce_operation_allows_draft_update(self):
        axiom = ImmutabilityAxiom()
        agg_id = uuid.uuid4()
        record_id = uuid.uuid4()
        is_allowed, violation = axiom.enforce_operation(
            aggregate_id=agg_id,
            operation="UPDATE",
            record_id=record_id,
            user_id="user",
            raise_on_violation=False,
        )
        assert is_allowed is True
        assert violation is None

    def test_enforce_operation_blocks_posted_update(self):
        axiom = ImmutabilityAxiom()
        agg_id = uuid.uuid4()
        record_id = uuid.uuid4()
        axiom.set_aggregate_state(agg_id, DataState.POSTED)
        is_allowed, violation = axiom.enforce_operation(
            aggregate_id=agg_id,
            operation="UPDATE",
            record_id=record_id,
            user_id="user",
            raise_on_violation=False,
        )
        assert is_allowed is False
        assert violation is not None

    def test_enforce_operation_raises_on_critical(self):
        axiom = ImmutabilityAxiom()
        agg_id = uuid.uuid4()
        record_id = uuid.uuid4()
        axiom.set_aggregate_state(agg_id, DataState.POSTED)
        with pytest.raises(ImmutabilityViolationError):
            axiom.enforce_operation(
                aggregate_id=agg_id,
                operation="UPDATE",
                record_id=record_id,
                user_id="user",
                raise_on_violation=True,
            )

    def test_enforce_state_transition_valid(self):
        axiom = ImmutabilityAxiom()
        agg_id = uuid.uuid4()
        record_id = uuid.uuid4()
        is_valid, violation = axiom.enforce_state_transition(
            aggregate_id=agg_id,
            from_state=DataState.APPROVED,
            to_state=DataState.POSTED,
            record_id=record_id,
            user_id="user",
            raise_on_violation=False,
        )
        assert is_valid is True
        assert violation is None
        assert axiom.get_aggregate_state(agg_id) == DataState.POSTED

    def test_enforce_state_transition_invalid(self):
        axiom = ImmutabilityAxiom()
        agg_id = uuid.uuid4()
        record_id = uuid.uuid4()
        is_valid, violation = axiom.enforce_state_transition(
            aggregate_id=agg_id,
            from_state=DataState.DRAFT,
            to_state=DataState.POSTED,
            record_id=record_id,
            user_id="user",
            raise_on_violation=False,
        )
        assert is_valid is False
        assert violation is not None

    def test_enforce_state_transition_raises(self):
        axiom = ImmutabilityAxiom()
        agg_id = uuid.uuid4()
        record_id = uuid.uuid4()
        with pytest.raises(ImmutabilityViolationError):
            axiom.enforce_state_transition(
                aggregate_id=agg_id,
                from_state=DataState.DRAFT,
                to_state=DataState.POSTED,
                record_id=record_id,
                user_id="user",
                raise_on_violation=True,
            )

    def test_record_correction(self):
        axiom = ImmutabilityAxiom()
        original_id = uuid.uuid4()
        correction_record_id = uuid.uuid4()
        correction = axiom.record_correction(
            original_record_id=original_id,
            correction_method=CorrectionMethod.REVERSAL_JOURNAL,
            correction_record_id=correction_record_id,
            reason="Test",
            authorized_by="admin",
            approved_by=["a", "b"],
            audit_reference="AUDIT-001",
        )
        assert correction is not None
        assert correction.original_record_id == original_id
        assert correction.correction_method == CorrectionMethod.REVERSAL_JOURNAL

    def test_record_correction_requires_two_approvers_for_amendment(self):
        axiom = ImmutabilityAxiom()
        with pytest.raises(ValueError, match="requires at least 2 approvers"):
            axiom.record_correction(
                original_record_id=uuid.uuid4(),
                correction_method=CorrectionMethod.AMENDMENT_ENTRY,
                correction_record_id=uuid.uuid4(),
                reason="Test",
                authorized_by="admin",
                approved_by=["only_one"],
                audit_reference="AUDIT-001",
            )

    def test_record_correction_deactivates_original(self):
        axiom = ImmutabilityAxiom()
        original = create_test_record()
        axiom.save_immutable_record(original)
        correction = axiom.record_correction(
            original_record_id=original.record_id,
            correction_method=CorrectionMethod.REVERSAL_JOURNAL,
            correction_record_id=uuid.uuid4(),
            reason="Test",
            authorized_by="admin",
            approved_by=["a", "b"],
            audit_reference="AUDIT-001",
        )
        assert correction is not None
        updated_original = axiom.get_immutable_record(original.record_id)
        assert updated_original is not None
        assert updated_original.is_active is False

    def test_is_immutable(self):
        axiom = ImmutabilityAxiom()
        assert axiom.is_immutable(DataState.POSTED) is True
        assert axiom.is_immutable(DataState.REVERSED) is True
        assert axiom.is_immutable(DataState.ARCHIVED) is True
        assert axiom.is_immutable(DataState.DELETED) is True
        assert axiom.is_immutable(DataState.DRAFT) is False
        assert axiom.is_immutable(DataState.SUBMITTED) is False
        assert axiom.is_immutable(DataState.APPROVED) is False

    def test_get_allowed_states_for_operation(self):
        axiom = ImmutabilityAxiom()
        # READ allows all states
        assert len(axiom.get_allowed_states_for_operation("READ")) == 7
        # UPDATE allows DRAFT, SUBMITTED, APPROVED
        update_states = axiom.get_allowed_states_for_operation("UPDATE")
        assert DataState.DRAFT in update_states
        assert DataState.SUBMITTED in update_states
        assert DataState.APPROVED in update_states
        assert DataState.POSTED not in update_states
        # DELETE only DRAFT
        delete_states = axiom.get_allowed_states_for_operation("DELETE")
        assert DataState.DRAFT in delete_states
        assert len(delete_states) == 1
        # REVERSE allows POSTED, REVERSED, ARCHIVED
        reverse_states = axiom.get_allowed_states_for_operation("REVERSE")
        assert DataState.POSTED in reverse_states
        assert DataState.REVERSED in reverse_states
        assert DataState.ARCHIVED in reverse_states

    def test_get_statistics(self):
        axiom = ImmutabilityAxiom()
        record = create_test_record()
        axiom.save_immutable_record(record)
        correction = create_test_correction()
        axiom.save_correction(correction)
        stats = axiom.get_statistics()
        assert stats["total_immutable_records"] >= 1
        assert stats["active_records"] >= 1
        assert stats["total_corrections"] >= 1
        assert "state_distribution" in stats

    def test_reset(self):
        axiom = ImmutabilityAxiom()
        record = create_test_record()
        axiom.save_immutable_record(record)
        correction = create_test_correction()
        axiom.save_correction(correction)
        axiom.reset()
        assert len(axiom._immutable_records) == 0
        assert len(axiom._correction_history) == 0
        assert len(axiom._violation_history) == 0
        assert len(axiom._state_registry) == 0


# ============================================================================
# TESTS FOR HELPER FUNCTIONS
# ============================================================================

class TestHelperFunctions:
    def test_create_immutable_record(self):
        record_id = uuid.uuid4()
        aggregate_id = uuid.uuid4()
        data = {"amount": 100, "description": "Test"}
        record = create_immutable_record(
            record_id=record_id,
            record_type=ImmutableRecordType.JOURNAL,
            aggregate_id=aggregate_id,
            version=1,
            data=data,
            previous_hash=None,
            created_by="tester",
            signature="sig",
        )
        assert record.record_id == record_id
        assert record.aggregate_id == aggregate_id
        assert record.version == 1
        assert record.data_hash != ""
        assert record.is_active is True

    def test_state_from_string(self):
        assert state_from_string("DRAFT") == DataState.DRAFT
        assert state_from_string("SUBMITTED") == DataState.SUBMITTED
        assert state_from_string("APPROVED") == DataState.APPROVED
        assert state_from_string("POSTED") == DataState.POSTED
        assert state_from_string("REVERSED") == DataState.REVERSED
        assert state_from_string("ARCHIVED") == DataState.ARCHIVED
        assert state_from_string("DELETED") == DataState.DELETED
        assert state_from_string("unknown") == DataState.DRAFT

    def test_record_type_from_string(self):
        assert record_type_from_string("JOURNAL") == ImmutableRecordType.JOURNAL
        assert record_type_from_string("INVOICE") == ImmutableRecordType.INVOICE
        assert record_type_from_string("PAYMENT") == ImmutableRecordType.PAYMENT
        assert record_type_from_string("ACCOUNT_BALANCE") == ImmutableRecordType.ACCOUNT_BALANCE
        assert record_type_from_string("PERIOD_CLOSE") == ImmutableRecordType.PERIOD_CLOSE
        assert record_type_from_string("AUDIT_EVENT") == ImmutableRecordType.AUDIT_EVENT
        assert record_type_from_string("unknown") == ImmutableRecordType.JOURNAL

    def test_get_immutability_axiom_singleton(self):
        axiom1 = get_immutability_axiom()
        axiom2 = get_immutability_axiom()
        assert axiom1 is axiom2