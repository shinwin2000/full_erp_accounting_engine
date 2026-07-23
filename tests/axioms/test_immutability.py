#!/usr/bin/env python3
"""
tests/unit/test_immutability.py
Comprehensive tests for axioms/immutability.py

Covers:
- ImmutableRecord, CorrectionRecord, ImmutabilityViolation
- ImmutabilityValidator and ImmutabilityAxiom
- Helper functions

Design notes on this rewrite:
- Shared "trivial no-op" behaviors across the three record-like dataclasses
  (lock/unlock/create, update-raises, restore-not-deleted-raises, hash
  mismatch validation, version accessors, audit trail) are expressed as
  pytest.mark.parametrize tables instead of copy-pasted per-class tests.
  This keeps the *intent* (verify identical contract across classes) while
  removing structural copy-paste duplication.
- All datetime values used in constructors are fixed (fixed_datetime()),
  never datetime.now(UTC), so nothing here can flake on wall-clock timing.
- Tests that check whether the constitutional notifier fires now capture
  the mock and assert on it (assert_called_once / assert_not_called /
  call_args), rather than only patching it to silence a side effect.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

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

# =============================================================================
# Helper factories
# =============================================================================


def fixed_datetime() -> datetime:
    """Return a fixed datetime for deterministic tests."""
    return datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)


def create_test_record(
    record_type: ImmutableRecordType = ImmutableRecordType.JOURNAL,
    aggregate_id: uuid.UUID | None = None,
    version: int = 1,
    is_active: bool = True,
    record_id: uuid.UUID | None = None,
) -> ImmutableRecord:
    if aggregate_id is None:
        aggregate_id = uuid.uuid4()
    if record_id is None:
        record_id = uuid.uuid4()
    data = {"amount": 1000, "description": "Test"}
    data_hash = hashlib.sha3_256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    return ImmutableRecord(
        record_id=record_id,
        record_type=record_type,
        aggregate_id=aggregate_id,
        version=version,
        data_hash=data_hash,
        previous_hash=None,
        timestamp=fixed_datetime(),
        created_by="tester",
        signature="test_signature",
        is_active=is_active,
    )


def create_test_correction(
    correction_id: uuid.UUID | None = None,
    original_record_id: uuid.UUID | None = None,
    correction_method: CorrectionMethod = CorrectionMethod.REVERSAL_JOURNAL,
    approved_by: list[str] | None = None,
) -> CorrectionRecord:
    if correction_id is None:
        correction_id = uuid.uuid4()
    if original_record_id is None:
        original_record_id = uuid.uuid4()
    if approved_by is None:
        approved_by = ["approver1", "approver2"]
    return CorrectionRecord(
        correction_id=correction_id,
        original_record_id=original_record_id,
        correction_method=correction_method,
        correction_record_id=uuid.uuid4(),
        reason="Test correction",
        authorized_by="admin",
        authorized_at=fixed_datetime(),
        approved_by=approved_by,
        audit_reference="AUDIT-001",
    )


def create_test_violation(
    violation_id: uuid.UUID | None = None,
    target_record_id: uuid.UUID | None = None,
    target_aggregate_id: uuid.UUID | None = None,
    severity: ImmutabilityViolationSeverity = ImmutabilityViolationSeverity.HIGH,
) -> ImmutabilityViolation:
    if violation_id is None:
        violation_id = uuid.uuid4()
    if target_record_id is None:
        target_record_id = uuid.uuid4()
    if target_aggregate_id is None:
        target_aggregate_id = uuid.uuid4()
    return ImmutabilityViolation(
        violation_id=violation_id,
        target_record_id=target_record_id,
        target_aggregate_id=target_aggregate_id,
        attempted_operation="UPDATE",
        attempted_by="user123",
        attempted_at=fixed_datetime(),
        source_module="test_module",
        severity=severity,
        message="Test violation",
        was_blocked=True,
        bypass_attempted=False,
        forensic_evidence_hash="",
    )


# Table of factories shared by the three record-like entities, used to
# express "same contract across classes" as parametrized tests rather than
# copy-pasted test bodies.
ENTITY_FACTORIES = [create_test_record, create_test_correction, create_test_violation]
ENTITY_IDS = ["record", "correction", "violation"]


# =============================================================================
# Tests for ImmutableRecord
# =============================================================================


class TestImmutableRecord:
    def test_create_valid_record(self):
        record = create_test_record()
        assert record.record_id is not None
        assert record.record_type == ImmutableRecordType.JOURNAL
        assert record.aggregate_id is not None
        assert record.version == 1
        assert record.is_active
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
                timestamp=fixed_datetime(),
                created_by="tester",
                signature="sig",
                _version=1,
            )

    def test_validate_internal_version_positive(self):
        with pytest.raises(ValueError, match="_version must be >= 1"):
            ImmutableRecord(
                record_id=uuid.uuid4(),
                record_type=ImmutableRecordType.JOURNAL,
                aggregate_id=uuid.uuid4(),
                version=1,
                data_hash="abc",
                previous_hash=None,
                timestamp=fixed_datetime(),
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
        with pytest.raises(AttributeError, match="ImmutableRecord cannot be updated"):
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
        assert activated.is_active
        assert activated._version == record._version + 1

    def test_deactivate_does_nothing_if_inactive(self):
        record = create_test_record(is_active=False)
        deactivated = record.deactivate("admin", "test")
        assert deactivated is record

    def test_deactivate_deactivates_active(self):
        record = create_test_record()
        deactivated = record.deactivate("admin", "test")
        assert not deactivated.is_active
        assert deactivated._version == record._version + 1

    def test_deactivate_default_alias(self):
        record = create_test_record()
        deactivated = record.deactivate_default()
        assert not deactivated.is_active
        assert deactivated._version == record._version + 1

    def test_validate_returns_valid(self):
        record = create_test_record()
        result = record.validate()
        assert result["is_valid"]
        assert result["record_id"] == str(record.record_id)

    def test_to_dict_contains_fields(self):
        record = create_test_record()
        d = record.to_dict()
        assert d["record_type"] == "JOURNAL"
        assert d["aggregate_id"] == str(record.aggregate_id)
        assert d["is_active"]
        assert "record_id" in d

    def test_from_dict_reconstructs(self):
        record = create_test_record()
        d = record.to_dict()
        # to_dict truncates hashes, so we need full hashes for roundtrip
        d["data_hash"] = record.data_hash
        d["signature"] = record.signature
        reconstructed = ImmutableRecord.from_dict(d)
        assert reconstructed.record_id == record.record_id
        assert reconstructed.record_type == record.record_type
        assert reconstructed.aggregate_id == record.aggregate_id
        assert reconstructed.version == record.version

    def test_from_dict_missing_required_key_raises(self):
        record = create_test_record()
        d = record.to_dict()
        d["data_hash"] = record.data_hash
        d["signature"] = record.signature
        del d["created_by"]
        with pytest.raises(KeyError):
            ImmutableRecord.from_dict(d)

    def test_clone_creates_new_instance(self):
        record = create_test_record()
        cloned = record.clone()
        assert cloned.record_id != record.record_id
        assert cloned.aggregate_id == record.aggregate_id
        assert cloned.record_type == record.record_type
        assert cloned.version == record.version
        assert cloned._version == 1
        assert cloned.is_active

    def test_snapshot_returns_summary(self):
        record = create_test_record()
        snap = record.snapshot()
        assert snap["record_id"] == str(record.record_id)
        assert snap["is_active"] == record.is_active
        assert "timestamp" in snap

    def test_get_version_method(self):
        record = create_test_record()
        assert record.get_version() == 1

    def test_touch_increments_version(self):
        record = create_test_record()
        touched = record.touch("toucher")
        assert touched._version == record._version + 1


# =============================================================================
# Tests for CorrectionRecord
# =============================================================================


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
                authorized_at=fixed_datetime(),
                approved_by=[],
                audit_reference="AUDIT-001",
            )

    def test_validate_version_positive(self):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            CorrectionRecord(
                correction_id=uuid.uuid4(),
                original_record_id=uuid.uuid4(),
                correction_method=CorrectionMethod.REVERSAL_JOURNAL,
                correction_record_id=uuid.uuid4(),
                reason="test",
                authorized_by="admin",
                authorized_at=fixed_datetime(),
                approved_by=["a"],
                audit_reference="AUDIT-001",
                version=0,
            )

    def test_update_raises(self):
        correction = create_test_correction()
        with pytest.raises(AttributeError, match="CorrectionRecord is immutable"):
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

    def test_validate_returns_valid(self):
        correction = create_test_correction()
        result = correction.validate()
        assert result["is_valid"]
        assert result["correction_id"] == str(correction.correction_id)

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

    def test_from_dict_missing_required_key_raises(self):
        correction = create_test_correction()
        d = correction.to_dict()
        del d["reason"]
        with pytest.raises(KeyError):
            CorrectionRecord.from_dict(d)

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

    def test_touch_increments_version(self):
        correction = create_test_correction()
        touched = correction.touch("toucher")
        assert touched.version == correction.version + 1


# =============================================================================
# Tests for ImmutabilityViolation
# =============================================================================


class TestImmutabilityViolation:
    def test_create_valid_violation(self):
        violation = create_test_violation()
        assert violation.violation_id is not None
        assert violation.target_record_id is not None
        assert violation.target_aggregate_id is not None
        assert violation.severity == ImmutabilityViolationSeverity.HIGH
        assert violation.was_blocked
        assert violation.forensic_evidence_hash != ""
        assert violation.cryptographic_hash != ""
        assert violation.version == 1

    def test_validate_version_positive(self):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            ImmutabilityViolation(
                violation_id=uuid.uuid4(),
                target_record_id=uuid.uuid4(),
                target_aggregate_id=uuid.uuid4(),
                attempted_operation="UPDATE",
                attempted_by="user",
                attempted_at=fixed_datetime(),
                source_module="test",
                severity=ImmutabilityViolationSeverity.HIGH,
                message="test",
                was_blocked=True,
                bypass_attempted=False,
                forensic_evidence_hash="",
                version=0,
            )

    def test_validate_returns_valid(self):
        violation = create_test_violation()
        result = violation.validate()
        assert result["is_valid"]
        assert result["violation_id"] == str(violation.violation_id)

    def test_validate_returns_errors_on_forensic_hash_mismatch(self):
        violation = create_test_violation()
        violation.forensic_evidence_hash = "corrupted"
        result = violation.validate()
        assert not result["is_valid"]
        assert "Forensic hash mismatch" in result["errors"]

    def test_update_raises(self):
        violation = create_test_violation()
        with pytest.raises(AttributeError, match="ImmutabilityViolation is immutable"):
            violation.update("admin", message="new")

    def test_delete_raises(self):
        violation = create_test_violation()
        with pytest.raises(AttributeError, match="Cannot delete"):
            violation.delete("admin")

    def test_restore_raises_unconditionally(self):
        # Unlike ImmutableRecord/CorrectionRecord, this is NOT a "not deleted
        # yet" state check -- ImmutabilityViolation.restore always raises,
        # regardless of any deleted-state, because violations are forensic
        # records that can never be restored.
        violation = create_test_violation()
        with pytest.raises(AttributeError, match="Cannot restore"):
            violation.restore("admin")

    def test_to_dict_contains_fields(self):
        violation = create_test_violation()
        d = violation.to_dict()
        assert d["severity"] == "HIGH"
        assert d["message"] == "Test violation"
        assert d["was_blocked"]
        assert "violation_id" in d

    def test_from_dict_reconstructs(self):
        violation = create_test_violation()
        d = violation.to_dict()
        reconstructed = ImmutabilityViolation.from_dict(d)
        assert reconstructed.violation_id == violation.violation_id
        assert reconstructed.target_record_id == violation.target_record_id
        assert reconstructed.severity == violation.severity
        assert reconstructed.was_blocked == violation.was_blocked

    def test_from_dict_missing_required_key_raises(self):
        violation = create_test_violation()
        d = violation.to_dict()
        del d["attempted_by"]
        with pytest.raises(KeyError):
            ImmutabilityViolation.from_dict(d)

    def test_clone_creates_new_instance(self):
        violation = create_test_violation()
        cloned = violation.clone()
        assert cloned.violation_id != violation.violation_id
        assert cloned.target_record_id == violation.target_record_id
        assert cloned.target_aggregate_id == violation.target_aggregate_id
        assert cloned.version == 1
        # clone() passes forensic_evidence_hash="" into the constructor, but
        # __post_init__ always fills in a fresh hash when it's empty -- so
        # the clone ends up with its OWN forensic hash (bound to its new
        # violation_id/attempted_at), not an empty one and not the
        # original's hash.
        assert cloned.forensic_evidence_hash != ""
        assert cloned.forensic_evidence_hash != violation.forensic_evidence_hash
        assert cloned.forensic_evidence_hash == cloned.compute_forensic_hash()

    def test_snapshot_returns_summary(self):
        violation = create_test_violation()
        snap = violation.snapshot()
        assert snap["violation_id"] == str(violation.violation_id)
        assert snap["severity"] == violation.severity.name

    def test_touch_does_not_create_new_instance(self):
        # Unlike ImmutableRecord/CorrectionRecord, touch() here mutates
        # in-place and returns the same object (no versioning concept).
        violation = create_test_violation()
        result = violation.touch("toucher")
        assert result is violation


# =============================================================================
# Shared-contract tests across ImmutableRecord / CorrectionRecord /
# ImmutabilityViolation (parametrized instead of copy-pasted per class)
# =============================================================================


@pytest.mark.parametrize("make_instance", ENTITY_FACTORIES, ids=ENTITY_IDS)
def test_lock_is_a_noop_returning_self(make_instance):
    instance = make_instance()
    assert instance.lock("admin", "test") is instance


@pytest.mark.parametrize("make_instance", ENTITY_FACTORIES, ids=ENTITY_IDS)
def test_unlock_is_a_noop_returning_self(make_instance):
    instance = make_instance()
    assert instance.unlock("admin") is instance


@pytest.mark.parametrize("make_instance", ENTITY_FACTORIES, ids=ENTITY_IDS)
def test_create_is_a_noop_returning_self(make_instance):
    instance = make_instance()
    assert instance.create("creator") is instance


@pytest.mark.parametrize("make_instance", ENTITY_FACTORIES, ids=ENTITY_IDS)
def test_validate_reports_error_on_cryptographic_hash_mismatch(make_instance):
    instance = make_instance()
    instance.cryptographic_hash = "corrupted"
    result = instance.validate()
    assert not result["is_valid"]
    assert "Hash mismatch" in result["errors"]


@pytest.mark.parametrize("make_instance", ENTITY_FACTORIES, ids=ENTITY_IDS)
def test_audit_trail_records_touch_action(make_instance):
    instance = make_instance()
    assert len(instance.audit_trail()) >= 1
    instance.touch("toucher")
    trail = instance.audit_trail()
    assert trail[-1]["action"] == "TOUCH"


# activate()/deactivate() are unconditional no-ops on CorrectionRecord and
# ImmutabilityViolation; ImmutableRecord has real conditional logic and is
# covered separately above (test_activate_activates_inactive, etc.)
@pytest.mark.parametrize(
    "make_instance", [create_test_correction, create_test_violation], ids=["correction", "violation"]
)
def test_activate_is_a_noop_returning_self(make_instance):
    instance = make_instance()
    assert instance.activate("admin") is instance


@pytest.mark.parametrize(
    "make_instance", [create_test_correction, create_test_violation], ids=["correction", "violation"]
)
def test_deactivate_is_a_noop_returning_self(make_instance):
    instance = make_instance()
    assert instance.deactivate("admin") is instance


UPDATE_RAISES_CASES = [
    pytest.param(create_test_record, {"data_hash": "new"}, "ImmutableRecord cannot be updated", id="record"),
    pytest.param(create_test_correction, {"reason": "new"}, "CorrectionRecord is immutable", id="correction"),
    pytest.param(create_test_violation, {"message": "new"}, "ImmutabilityViolation is immutable", id="violation"),
]


@pytest.mark.parametrize("make_instance,kwargs,match", UPDATE_RAISES_CASES)
def test_update_always_raises(make_instance, kwargs, match):
    instance = make_instance()
    with pytest.raises(AttributeError, match=match):
        instance.update("admin", **kwargs)


VERSION_ACCESSOR_CASES = [
    pytest.param(create_test_record, lambda o: o.get_version(), id="record"),
    pytest.param(create_test_correction, lambda o: o.get_version(), id="correction"),
    pytest.param(create_test_violation, lambda o: o.get_version(), id="violation"),
]


@pytest.mark.parametrize("make_instance,accessor", VERSION_ACCESSOR_CASES)
def test_version_accessor_starts_at_one(make_instance, accessor):
    instance = make_instance()
    assert accessor(instance) == 1


# =============================================================================
# Tests for ImmutabilityValidator
# =============================================================================


class TestImmutabilityValidator:
    @pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "UNKNOWN_OP"])
    def test_validate_operation_on_draft_allows_any_operation(self, operation):
        is_allowed, violation = ImmutabilityValidator.validate_operation(
            current_state=DataState.DRAFT,
            operation=operation,
            aggregate_id=uuid.uuid4(),
            record_id=uuid.uuid4(),
            user_id="user",
            module="test",
        )
        assert is_allowed
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
        assert is_allowed
        assert violation is None

    @pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
    def test_validate_operation_on_posted_blocks_and_notifies_constitution(self, operation):
        with patch("axioms.immutability.ImmutabilityValidator._notify_constitution") as mock_notify:
            is_allowed, violation = ImmutabilityValidator.validate_operation(
                current_state=DataState.POSTED,
                operation=operation,
                aggregate_id=uuid.uuid4(),
                record_id=uuid.uuid4(),
                user_id="user",
                module="test",
            )
        assert not is_allowed
        assert violation is not None
        assert violation.severity == ImmutabilityViolationSeverity.CRITICAL
        mock_notify.assert_called_once_with(violation)

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
        assert is_allowed
        assert violation is None

    def test_validate_operation_on_posted_blocks_correction_without_bypass(self):
        with patch("axioms.immutability.ImmutabilityValidator._notify_constitution") as mock_notify:
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
        assert not is_allowed
        assert violation is not None
        mock_notify.assert_called_once()

    def test_validate_operation_on_posted_blocks_correction_with_wrong_method(self):
        """ERROR_CORRECTION / PRIOR_PERIOD_ADJUSTMENT are not eligible for the
        bypass-authorization shortcut even if bypass_authorization is set --
        only REVERSAL_JOURNAL and AMENDMENT_ENTRY are."""
        with patch("axioms.immutability.ImmutabilityValidator._notify_constitution") as mock_notify:
            is_allowed, violation = ImmutabilityValidator.validate_operation(
                current_state=DataState.POSTED,
                operation="REVERSE",
                aggregate_id=uuid.uuid4(),
                record_id=uuid.uuid4(),
                user_id="user",
                module="test",
                is_correction=True,
                correction_method=CorrectionMethod.ERROR_CORRECTION,
                bypass_authorization=["approver"],
            )
        assert not is_allowed
        assert violation is not None
        mock_notify.assert_called_once()

    def test_validate_operation_on_submitted_modify_without_bypass_blocks_but_does_not_notify(self):
        """MEDIUM-severity violations are logged but must NOT escalate to the
        constitutional notifier -- only CRITICAL/CATASTROPHIC paths do."""
        with patch("axioms.immutability.ImmutabilityValidator._notify_constitution") as mock_notify:
            is_allowed, violation = ImmutabilityValidator.validate_operation(
                current_state=DataState.SUBMITTED,
                operation="UPDATE",
                aggregate_id=uuid.uuid4(),
                record_id=uuid.uuid4(),
                user_id="user",
                module="test",
                bypass_authorization=None,
            )
        assert not is_allowed
        assert violation is not None
        assert violation.severity == ImmutabilityViolationSeverity.MEDIUM
        mock_notify.assert_not_called()

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
        assert is_allowed
        assert violation is None

    def test_validate_operation_allows_update_on_approved_with_bypass(self):
        is_allowed, violation = ImmutabilityValidator.validate_operation(
            current_state=DataState.APPROVED,
            operation="UPDATE",
            aggregate_id=uuid.uuid4(),
            record_id=uuid.uuid4(),
            user_id="user",
            module="test",
            bypass_authorization=["approver"],
        )
        assert is_allowed
        assert violation is None

    def test_validate_operation_blocks_update_on_approved_without_bypass(self):
        with patch("axioms.immutability.ImmutabilityValidator._notify_constitution") as mock_notify:
            is_allowed, violation = ImmutabilityValidator.validate_operation(
                current_state=DataState.APPROVED,
                operation="UPDATE",
                aggregate_id=uuid.uuid4(),
                record_id=uuid.uuid4(),
                user_id="user",
                module="test",
                bypass_authorization=None,
            )
        assert not is_allowed
        assert violation is not None
        assert violation.severity == ImmutabilityViolationSeverity.MEDIUM
        mock_notify.assert_not_called()

    def test_validate_operation_on_deleted_blocks(self):
        with patch("axioms.immutability.ImmutabilityValidator._notify_constitution") as mock_notify:
            is_allowed, violation = ImmutabilityValidator.validate_operation(
                current_state=DataState.DELETED,
                operation="UPDATE",
                aggregate_id=uuid.uuid4(),
                record_id=uuid.uuid4(),
                user_id="user",
                module="test",
            )
        assert not is_allowed
        assert violation is not None
        mock_notify.assert_called_once()

    def test_validate_state_transition_valid_posting(self):
        is_valid, violation = ImmutabilityValidator.validate_state_transition(
            from_state=DataState.APPROVED,
            to_state=DataState.POSTED,
            aggregate_id=uuid.uuid4(),
            record_id=uuid.uuid4(),
            user_id="user",
            module="test",
        )
        assert is_valid
        assert violation is None

    def test_validate_state_transition_invalid_posting_from_draft(self):
        with patch("axioms.immutability.ImmutabilityValidator._notify_constitution") as mock_notify:
            is_valid, violation = ImmutabilityValidator.validate_state_transition(
                from_state=DataState.DRAFT,
                to_state=DataState.POSTED,
                aggregate_id=uuid.uuid4(),
                record_id=uuid.uuid4(),
                user_id="user",
                module="test",
            )
        assert not is_valid
        assert violation is not None
        assert violation.severity == ImmutabilityViolationSeverity.CRITICAL
        # Posting-from-invalid-state is CRITICAL but not CATASTROPHIC, and
        # only the POSTED -> non-terminal branch notifies the constitution.
        mock_notify.assert_not_called()

    def test_validate_state_transition_from_posted_to_archived_allows(self):
        is_valid, violation = ImmutabilityValidator.validate_state_transition(
            from_state=DataState.POSTED,
            to_state=DataState.ARCHIVED,
            aggregate_id=uuid.uuid4(),
            record_id=uuid.uuid4(),
            user_id="user",
            module="test",
        )
        assert is_valid
        assert violation is None

    def test_validate_state_transition_from_posted_to_draft_blocks_and_notifies(self):
        with patch("axioms.immutability.ImmutabilityValidator._notify_constitution") as mock_notify:
            is_valid, violation = ImmutabilityValidator.validate_state_transition(
                from_state=DataState.POSTED,
                to_state=DataState.DRAFT,
                aggregate_id=uuid.uuid4(),
                record_id=uuid.uuid4(),
                user_id="user",
                module="test",
            )
        assert not is_valid
        assert violation is not None
        assert violation.severity == ImmutabilityViolationSeverity.CATASTROPHIC
        mock_notify.assert_called_once_with(violation)

    def test_validate_state_transition_reversal_requires_approval(self):
        is_valid, violation = ImmutabilityValidator.validate_state_transition(
            from_state=DataState.POSTED,
            to_state=DataState.REVERSED,
            aggregate_id=uuid.uuid4(),
            record_id=uuid.uuid4(),
            user_id=None,
            module="test",
            require_approval=True,
        )
        assert not is_valid
        assert violation is not None
        assert violation.severity == ImmutabilityViolationSeverity.HIGH

    def test_validate_state_transition_reversal_with_user_and_no_approval_required(self):
        is_valid, violation = ImmutabilityValidator.validate_state_transition(
            from_state=DataState.POSTED,
            to_state=DataState.REVERSED,
            aggregate_id=uuid.uuid4(),
            record_id=uuid.uuid4(),
            user_id="user",
            module="test",
            require_approval=True,
        )
        assert is_valid
        assert violation is None

    def test_validate_state_transition_reversal_approval_not_required(self):
        is_valid, violation = ImmutabilityValidator.validate_state_transition(
            from_state=DataState.POSTED,
            to_state=DataState.REVERSED,
            aggregate_id=uuid.uuid4(),
            record_id=uuid.uuid4(),
            user_id=None,
            module="test",
            require_approval=False,
        )
        assert is_valid
        assert violation is None

    # ---- direct tests of the private notifier, to exercise mock-based
    # verification of the constitution integration itself ----

    def test_notify_constitution_calls_supreme_law_check_violation(self):
        violation = create_test_violation(severity=ImmutabilityViolationSeverity.CRITICAL)
        mock_supreme_law = MagicMock()
        with patch("axioms.immutability.get_supreme_law", return_value=mock_supreme_law):
            ImmutabilityValidator._notify_constitution(violation)
        mock_supreme_law.check_violation.assert_called_once()
        _, kwargs = mock_supreme_law.check_violation.call_args
        assert kwargs["offending_module"] == violation.source_module
        assert kwargs["offending_user"] == violation.attempted_by
        assert kwargs["message"] == violation.message
        assert kwargs["offending_command_id"] == violation.target_record_id

    def test_notify_constitution_swallows_supreme_law_errors(self):
        """If the constitution integration itself is broken, that must never
        propagate out and break the caller's flow -- it's best-effort."""
        violation = create_test_violation()
        with patch("axioms.immutability.get_supreme_law", side_effect=RuntimeError("boom")):
            ImmutabilityValidator._notify_constitution(violation)  # must not raise


# =============================================================================
# Tests for ImmutabilityAxiom
# =============================================================================


class TestImmutabilityAxiom:
    def test_singleton_via_direct_instantiation(self):
        axiom1 = ImmutabilityAxiom()
        axiom2 = ImmutabilityAxiom()
        assert axiom1 is axiom2

    def test_singleton_accessor_matches_direct_instantiation(self):
        axiom1 = get_immutability_axiom()
        axiom2 = ImmutabilityAxiom()
        assert axiom1 is axiom2

    def test_save_and_get_immutable_record(self):
        axiom = ImmutabilityAxiom()
        record = create_test_record()
        axiom.save_immutable_record(record)
        retrieved = axiom.get_immutable_record(record.record_id)
        assert retrieved is not None
        assert retrieved.record_id == record.record_id

    def test_get_immutable_record_not_found_returns_none(self):
        axiom = ImmutabilityAxiom()
        assert axiom.get_immutable_record(uuid.uuid4()) is None

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
        assert result
        assert axiom.get_immutable_record(record.record_id) is None

    def test_delete_immutable_record_not_found(self):
        axiom = ImmutabilityAxiom()
        result = axiom.delete_immutable_record(uuid.uuid4())
        assert not result

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
        c1 = create_test_correction(original_record_id=original_id)
        c2 = create_test_correction(original_record_id=original_id)
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
        assert result
        corrections = axiom.get_corrections()
        assert all(c.correction_id != correction.correction_id for c in corrections)

    def test_delete_correction_not_found(self):
        axiom = ImmutabilityAxiom()
        result = axiom.delete_correction(uuid.uuid4())
        assert not result

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
        v1 = create_test_violation(severity=ImmutabilityViolationSeverity.LOW)
        v2 = create_test_violation(severity=ImmutabilityViolationSeverity.CRITICAL)
        axiom.save_violation(v1)
        axiom.save_violation(v2)
        result = axiom.get_violations(min_severity=ImmutabilityViolationSeverity.HIGH)
        assert all(v.severity.value >= ImmutabilityViolationSeverity.HIGH.value for v in result)
        assert any(v.violation_id == v2.violation_id for v in result)
        assert all(v.violation_id != v1.violation_id for v in result)

    def test_get_violations_filter_by_aggregate(self):
        axiom = ImmutabilityAxiom()
        agg_id = uuid.uuid4()
        v1 = create_test_violation(target_aggregate_id=agg_id)
        v2 = create_test_violation(target_aggregate_id=agg_id)
        v3 = create_test_violation()
        axiom.save_violation(v1)
        axiom.save_violation(v2)
        axiom.save_violation(v3)
        result = axiom.get_violations(aggregate_id=agg_id)
        assert len(result) == 2

    def test_register_immutable_record_without_chain_verification(self):
        axiom = ImmutabilityAxiom()
        record = create_test_record()
        axiom.register_immutable_record(record, verify_hash_chain=False)
        assert axiom.get_immutable_record(record.record_id) is not None

    def test_register_immutable_record_chain_verification_fails_when_previous_missing(self):
        axiom = ImmutabilityAxiom()
        record = create_test_record()
        record.previous_hash = "some_hash_that_does_not_exist"
        with pytest.raises(ImmutabilityHashChainError, match="Previous record not found"):
            axiom.register_immutable_record(record, verify_hash_chain=True)

    def test_register_immutable_record_chain_verification_succeeds(self):
        axiom = ImmutabilityAxiom()
        prev = create_test_record()
        axiom.save_immutable_record(prev)
        chain_hash = prev.compute_chain_hash()
        new_record = create_test_record()
        new_record.previous_hash = chain_hash
        axiom.register_immutable_record(new_record, verify_hash_chain=True)
        assert axiom.get_immutable_record(new_record.record_id) is not None

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
        assert is_allowed
        assert violation is None

    def test_enforce_operation_blocks_posted_update_without_raising(self):
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
        assert not is_allowed
        assert violation is not None

    def test_enforce_operation_raises_on_critical_when_requested(self):
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

    def test_enforce_operation_does_not_raise_below_critical_threshold(self):
        """MEDIUM-severity violations (e.g. modifying a SUBMITTED record
        without bypass) must be reported but never raised, even when
        raise_on_violation=True -- only >= CRITICAL does that."""
        axiom = ImmutabilityAxiom()
        agg_id = uuid.uuid4()
        record_id = uuid.uuid4()
        axiom.set_aggregate_state(agg_id, DataState.SUBMITTED)
        is_allowed, violation = axiom.enforce_operation(
            aggregate_id=agg_id,
            operation="UPDATE",
            record_id=record_id,
            user_id="user",
            raise_on_violation=True,
        )
        assert not is_allowed
        assert violation is not None
        assert violation.severity == ImmutabilityViolationSeverity.MEDIUM

    def test_enforce_operation_persists_violation_to_history(self):
        axiom = ImmutabilityAxiom()
        agg_id = uuid.uuid4()
        record_id = uuid.uuid4()
        axiom.set_aggregate_state(agg_id, DataState.POSTED)
        _, violation = axiom.enforce_operation(
            aggregate_id=agg_id,
            operation="UPDATE",
            record_id=record_id,
            user_id="user",
            raise_on_violation=False,
        )
        stored = axiom.get_violations(aggregate_id=agg_id)
        assert any(v.violation_id == violation.violation_id for v in stored)

    def test_enforce_operation_with_bypass_allows(self):
        axiom = ImmutabilityAxiom()
        agg_id = uuid.uuid4()
        record_id = uuid.uuid4()
        axiom.set_aggregate_state(agg_id, DataState.POSTED)
        is_allowed, violation = axiom.enforce_operation(
            aggregate_id=agg_id,
            operation="REVERSE",
            record_id=record_id,
            user_id="user",
            is_correction=True,
            correction_method=CorrectionMethod.REVERSAL_JOURNAL,
            bypass_authorization=["approver"],
            raise_on_violation=False,
        )
        assert is_allowed
        assert violation is None

    def test_enforce_operation_with_bypass_insufficient(self):
        axiom = ImmutabilityAxiom()
        agg_id = uuid.uuid4()
        record_id = uuid.uuid4()
        axiom.set_aggregate_state(agg_id, DataState.POSTED)
        with patch("axioms.immutability.ImmutabilityValidator._notify_constitution"):
            is_allowed, violation = axiom.enforce_operation(
                aggregate_id=agg_id,
                operation="REVERSE",
                record_id=record_id,
                user_id="user",
                is_correction=True,
                correction_method=CorrectionMethod.REVERSAL_JOURNAL,
                bypass_authorization=None,
                raise_on_violation=False,
            )
        assert not is_allowed
        assert violation is not None

    def test_enforce_state_transition_valid_sets_new_state(self):
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
        assert is_valid
        assert violation is None
        assert axiom.get_aggregate_state(agg_id) == DataState.POSTED

    def test_enforce_state_transition_invalid_without_raising(self):
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
        assert not is_valid
        assert violation is not None
        # Invalid transitions must not silently update the state registry.
        assert axiom.get_aggregate_state(agg_id) != DataState.POSTED

    def test_enforce_state_transition_raises_on_critical(self):
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

    def test_enforce_state_transition_raises_on_high_severity_too(self):
        """enforce_state_transition's raise threshold is HIGH (lower than
        enforce_operation's CRITICAL threshold) -- a HIGH-severity
        unapproved-reversal violation must also raise."""
        axiom = ImmutabilityAxiom()
        agg_id = uuid.uuid4()
        record_id = uuid.uuid4()
        with pytest.raises(ImmutabilityViolationError):
            axiom.enforce_state_transition(
                aggregate_id=agg_id,
                from_state=DataState.POSTED,
                to_state=DataState.REVERSED,
                record_id=record_id,
                user_id=None,
                require_approval=True,
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

    @pytest.mark.parametrize(
        "correction_method",
        [CorrectionMethod.AMENDMENT_ENTRY, CorrectionMethod.PRIOR_PERIOD_ADJUSTMENT],
    )
    def test_record_correction_requires_two_approvers_for_sensitive_methods(self, correction_method):
        axiom = ImmutabilityAxiom()
        with pytest.raises(ValueError, match="requires at least 2 approvers"):
            axiom.record_correction(
                original_record_id=uuid.uuid4(),
                correction_method=correction_method,
                correction_record_id=uuid.uuid4(),
                reason="Test",
                authorized_by="admin",
                approved_by=["only_one"],
                audit_reference="AUDIT-001",
            )

    def test_record_correction_reversal_journal_allows_single_approver(self):
        """REVERSAL_JOURNAL and ERROR_CORRECTION are not in the
        two-approver-required set -- a single approver must be accepted."""
        axiom = ImmutabilityAxiom()
        correction = axiom.record_correction(
            original_record_id=uuid.uuid4(),
            correction_method=CorrectionMethod.REVERSAL_JOURNAL,
            correction_record_id=uuid.uuid4(),
            reason="Test",
            authorized_by="admin",
            approved_by=["only_one"],
            audit_reference="AUDIT-001",
        )
        assert correction is not None

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
        assert not updated_original.is_active

    def test_record_correction_when_original_not_found_does_not_raise(self):
        axiom = ImmutabilityAxiom()
        correction = axiom.record_correction(
            original_record_id=uuid.uuid4(),
            correction_method=CorrectionMethod.REVERSAL_JOURNAL,
            correction_record_id=uuid.uuid4(),
            reason="Test",
            authorized_by="admin",
            approved_by=["a", "b"],
            audit_reference="AUDIT-001",
        )
        assert correction is not None

    def test_is_immutable(self):
        axiom = ImmutabilityAxiom()
        assert axiom.is_immutable(DataState.POSTED)
        assert axiom.is_immutable(DataState.REVERSED)
        assert axiom.is_immutable(DataState.ARCHIVED)
        assert axiom.is_immutable(DataState.DELETED)
        assert not axiom.is_immutable(DataState.DRAFT)
        assert not axiom.is_immutable(DataState.SUBMITTED)
        assert not axiom.is_immutable(DataState.APPROVED)

    def test_get_allowed_states_for_operation(self):
        axiom = ImmutabilityAxiom()
        assert len(axiom.get_allowed_states_for_operation("READ")) == 7
        update_states = axiom.get_allowed_states_for_operation("UPDATE")
        assert DataState.DRAFT in update_states
        assert DataState.SUBMITTED in update_states
        assert DataState.APPROVED in update_states
        assert DataState.POSTED not in update_states
        delete_states = axiom.get_allowed_states_for_operation("DELETE")
        assert DataState.DRAFT in delete_states
        assert len(delete_states) == 1
        reverse_states = axiom.get_allowed_states_for_operation("REVERSE")
        assert DataState.POSTED in reverse_states
        assert DataState.REVERSED in reverse_states
        assert DataState.ARCHIVED in reverse_states

    def test_get_allowed_states_for_unknown_operation_returns_empty(self):
        axiom = ImmutabilityAxiom()
        assert axiom.get_allowed_states_for_operation("TELEPORT") == []

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


# =============================================================================
# Tests for helper functions
# =============================================================================


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
        assert record.is_active

    @pytest.mark.parametrize(
        "label,expected",
        [
            ("DRAFT", DataState.DRAFT),
            ("SUBMITTED", DataState.SUBMITTED),
            ("APPROVED", DataState.APPROVED),
            ("POSTED", DataState.POSTED),
            ("REVERSED", DataState.REVERSED),
            ("ARCHIVED", DataState.ARCHIVED),
            ("DELETED", DataState.DELETED),
        ],
    )
    def test_state_from_string(self, label, expected):
        assert state_from_string(label) == expected

    def test_state_from_string_unknown_defaults_to_draft(self):
        assert state_from_string("not-a-real-state") == DataState.DRAFT

    def test_state_from_string_is_case_insensitive(self):
        assert state_from_string("posted") == DataState.POSTED

    @pytest.mark.parametrize(
        "label,expected",
        [
            ("JOURNAL", ImmutableRecordType.JOURNAL),
            ("INVOICE", ImmutableRecordType.INVOICE),
            ("PAYMENT", ImmutableRecordType.PAYMENT),
            ("ACCOUNT_BALANCE", ImmutableRecordType.ACCOUNT_BALANCE),
            ("PERIOD_CLOSE", ImmutableRecordType.PERIOD_CLOSE),
            ("AUDIT_EVENT", ImmutableRecordType.AUDIT_EVENT),
        ],
    )
    def test_record_type_from_string(self, label, expected):
        assert record_type_from_string(label) == expected

    def test_record_type_from_string_unknown_defaults_to_journal(self):
        assert record_type_from_string("not-a-real-type") == ImmutableRecordType.JOURNAL

    def test_get_immutability_axiom_singleton(self):
        axiom1 = get_immutability_axiom()
        axiom2 = get_immutability_axiom()
        assert axiom1 is axiom2
