#!/usr/bin/env python3
"""
tests/unit/test_forbidden_states.py
Test untuk constitution/forbidden_states.py
Mencakup semua kelas dan metode secara exhaustive.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from constitution.forbidden_states import (
    ForbiddenStateAction,
    ForbiddenStateCategory,
    ForbiddenStateDefinition,
    ForbiddenStateDetectedError,
    ForbiddenStateDetection,
    ForbiddenStateDetector,
    ForbiddenStateError,
    ForbiddenStateRecoveryError,
    ForbiddenStateSeverity,
    ForbiddenStatesRegistry,
    ForbiddenStatesService,
    StateDetectionMethod,
    get_detector_for_state,
    get_forbidden_states_service,
)


# ============================================================================
# Helper functions for creating test objects
# ============================================================================

def create_test_state(
    category: ForbiddenStateCategory = ForbiddenStateCategory.NEGATIVE_CASH,
    name: str = "Test State",
    severity: ForbiddenStateSeverity = ForbiddenStateSeverity.HIGH,
    detection_method: StateDetectionMethod = StateDetectionMethod.PRE_TRANSACTION_VALIDATION,
    default_action: ForbiddenStateAction = ForbiddenStateAction.REJECT,
    is_active: bool = True,
) -> ForbiddenStateDefinition:
    now = datetime.now(UTC)
    return ForbiddenStateDefinition(
        state_id=uuid.uuid4(),
        category=category,
        name=name,
        description="Test description",
        severity=severity,
        detection_method=detection_method,
        default_action=default_action,
        recovery_action="Test recovery",
        auto_correct=False,
        is_active=is_active,
        created_at=now,
        created_by="tester",
        approved_by=["approver1", "approver2"],
        version="1.0.0",
        cryptographic_hash="",
        override_allowed=True,
        override_roles=["admin", "supervisor"],
    )


def create_test_detection(
    category: ForbiddenStateCategory = ForbiddenStateCategory.NEGATIVE_CASH,
    severity: ForbiddenStateSeverity = ForbiddenStateSeverity.HIGH,
    prevented: bool = True,
    resolved: bool = False,
) -> ForbiddenStateDetection:
    return ForbiddenStateDetection(
        detection_id=uuid.uuid4(),
        state_id=uuid.uuid4(),
        category=category,
        severity=severity,
        detected_at=datetime.now(UTC),
        detection_method=StateDetectionMethod.PRE_TRANSACTION_VALIDATION,
        current_state={"balance": "100"},
        attempted_action={"debit": "200"},
        prevented=prevented,
        action_taken=ForbiddenStateAction.REJECT,
        source_module="test_module",
        resolved=resolved,
        transaction_id=uuid.uuid4(),
        legal_entity_id=uuid.uuid4(),
        source_user="tester",
    )


# ============================================================================
# Tests for ForbiddenStateDefinition
# ============================================================================

class TestForbiddenStateDefinition:
    def test_create_valid_state(self):
        state = create_test_state()
        assert state.state_id is not None
        assert state.category == ForbiddenStateCategory.NEGATIVE_CASH
        assert state.name == "Test State"
        assert state.severity == ForbiddenStateSeverity.HIGH
        assert state.is_active
        assert state.version_number == 1
        assert state.cryptographic_hash != ""

    def test_validate_version_number(self):
        with pytest.raises(ValueError, match="Version number must be >= 1"):
            create_test_state(version_number=0)

    def test_validate_override_roles_required(self):
        with pytest.raises(ValueError, match="Override roles required"):
            ForbiddenStateDefinition(
                state_id=uuid.uuid4(),
                category=ForbiddenStateCategory.NEGATIVE_CASH,
                name="Test",
                description="Desc",
                severity=ForbiddenStateSeverity.HIGH,
                detection_method=StateDetectionMethod.PRE_TRANSACTION_VALIDATION,
                default_action=ForbiddenStateAction.REJECT,
                recovery_action="Recovery",
                auto_correct=False,
                is_active=True,
                created_at=datetime.now(UTC),
                created_by="tester",
                approved_by=["a"],
                version="1.0",
                override_allowed=True,
                override_roles=[],
            )

    def test_private_validate_called(self):
        state = create_test_state()
        result = state.validate()
        assert result["is_valid"]

    def test_private_ensure_hash_called(self):
        state = create_test_state()
        assert state.cryptographic_hash != ""

    def test_private_take_snapshot_called(self):
        state = create_test_state()
        assert len(state._snapshots) == 1

    def test_private_record_audit_called(self):
        state = create_test_state()
        assert len(state._audit_trail) == 1

    def test_private_copy_called(self):
        state = create_test_state()
        updated = state.update("admin", name="Updated")
        assert updated.name == "Updated"

    def test_compute_hash_consistent(self):
        s1 = create_test_state()
        s2 = ForbiddenStateDefinition(
            state_id=s1.state_id,
            category=s1.category,
            name=s1.name,
            description=s1.description,
            severity=s1.severity,
            detection_method=s1.detection_method,
            default_action=s1.default_action,
            recovery_action=s1.recovery_action,
            auto_correct=s1.auto_correct,
            is_active=s1.is_active,
            created_at=s1.created_at,
            created_by=s1.created_by,
            approved_by=s1.approved_by.copy(),
            version=s1.version,
            cryptographic_hash="",
            override_allowed=s1.override_allowed,
            override_roles=s1.override_roles.copy(),
            version_number=s1.version_number,
        )
        assert s1.compute_hash() == s2.compute_hash()

    def test_update_creates_new_version(self):
        state = create_test_state()
        updated = state.update("admin", name="Updated Name")
        assert updated.name == "Updated Name"
        assert updated.version_number == state.version_number + 1

    def test_update_cannot_change_id_and_created_at(self):
        state = create_test_state()
        original_id = state.state_id
        original_created = state.created_at
        updated = state.update("admin", name="New", created_at=datetime(2000, 1, 1, tzinfo=UTC))
        assert updated.state_id == original_id
        assert updated.created_at == original_created

    def test_delete_marks_deleted_and_inactive(self):
        state = create_test_state()
        deleted = state.delete("admin", "test")
        assert deleted.deleted_at is not None
        assert deleted.deleted_by == "admin"
        assert not deleted.is_active
        assert deleted.version_number == state.version_number + 1

    def test_restore_recovers_deleted_state(self):
        state = create_test_state()
        deleted = state.delete("admin", "test")
        restored = deleted.restore("admin")
        assert restored.deleted_at is None
        assert restored.deleted_by is None
        assert restored.is_active

    def test_restore_not_deleted_raises(self):
        state = create_test_state()
        with pytest.raises(ValueError, match="Not deleted"):
            state.restore("admin")

    def test_activate_does_nothing_if_active(self):
        state = create_test_state()
        activated = state.activate("admin")
        assert activated is state

    def test_activate_activates_inactive(self):
        state = create_test_state()
        deactivated = state.deactivate("admin", "test")
        activated = deactivated.activate("admin")
        assert activated.is_active
        assert activated.version_number == deactivated.version_number + 1

    def test_deactivate_does_nothing_if_inactive(self):
        state = create_test_state()
        deactivated = state.deactivate("admin", "test")
        again = deactivated.deactivate("admin", "again")
        assert again is deactivated

    def test_lock_returns_new_instance(self):
        state = create_test_state()
        locked = state.lock("admin", "test")
        assert locked.version_number == state.version_number + 1
        assert locked._audit_trail[-1]["action"] == "LOCK"

    def test_unlock_returns_new_instance(self):
        state = create_test_state()
        unlocked = state.unlock("admin")
        assert unlocked.version_number == state.version_number + 1
        assert unlocked._audit_trail[-1]["action"] == "UNLOCK"

    def test_create_returns_self(self):
        state = create_test_state()
        result = state.create("admin")
        assert result is state

    def test_validate_returns_valid(self):
        state = create_test_state()
        result = state.validate()
        assert result["is_valid"]
        assert result["state_id"] == str(state.state_id)

    def test_validate_returns_errors_on_hash_mismatch(self):
        state = create_test_state()
        object.__setattr__(state, "cryptographic_hash", "fake")
        result = state.validate()
        assert not result["is_valid"]
        assert "Hash mismatch" in result["errors"]

    def test_to_dict_contains_fields(self):
        state = create_test_state()
        d = state.to_dict()
        assert d["category"] == "NEGATIVE_CASH"
        assert d["name"] == "Test State"
        assert d["severity"] == "HIGH"
        assert d["is_active"]
        assert "version_number" in d

    def test_from_dict_reconstructs(self):
        state = create_test_state()
        d = state.to_dict()
        reconstructed = ForbiddenStateDefinition.from_dict(d)
        assert reconstructed.state_id == state.state_id
        assert reconstructed.category == state.category
        assert reconstructed.name == state.name
        assert reconstructed.severity == state.severity
        assert reconstructed.is_active == state.is_active

    def test_clone_creates_new_state(self):
        state = create_test_state()
        cloned = state.clone()
        assert cloned.state_id != state.state_id
        assert cloned.category == state.category
        assert cloned.name == state.name
        assert not cloned.is_active
        assert cloned.version_number == 1

    def test_snapshot_returns_summary(self):
        state = create_test_state()
        snap = state.snapshot()
        assert snap["state_id"] == str(state.state_id)
        assert snap["category"] == state.category.name

    def test_version(self):
        state = create_test_state()
        assert state.version() == 1

    def test_audit_trail_records(self):
        state = create_test_state()
        assert len(state.audit_trail()) >= 1
        state.touch("toucher")
        trail = state.audit_trail()
        assert len(trail) >= 2
        assert trail[-1]["action"] == "TOUCH"

    def test_touch_increments_version(self):
        state = create_test_state()
        touched = state.touch("toucher")
        assert touched.version_number == state.version_number + 1

    def test_audit_trail_limit(self):
        state = create_test_state()
        for _ in range(15):
            state = state.touch("tester")
        trail = state.audit_trail(limit=5)
        assert len(trail) == 5


# ============================================================================
# Tests for ForbiddenStateDetection
# ============================================================================

class TestForbiddenStateDetection:
    def test_create_valid_detection(self):
        detection = create_test_detection()
        assert detection.detection_id is not None
        assert detection.category == ForbiddenStateCategory.NEGATIVE_CASH
        assert detection.prevented
        assert not detection.resolved
        assert detection.version_number == 1

    def test_validate_version_number(self):
        with pytest.raises(ValueError, match="Version number must be >= 1"):
            ForbiddenStateDetection(
                detection_id=uuid.uuid4(),
                state_id=uuid.uuid4(),
                category=ForbiddenStateCategory.NEGATIVE_CASH,
                severity=ForbiddenStateSeverity.HIGH,
                detected_at=datetime.now(UTC),
                detection_method=StateDetectionMethod.PRE_TRANSACTION_VALIDATION,
                current_state={},
                attempted_action={},
                prevented=True,
                action_taken=ForbiddenStateAction.REJECT,
                source_module="test",
                resolved=False,
                version_number=0,
            )

    def test_private_take_snapshot_called(self):
        detection = create_test_detection()
        assert len(detection._snapshots) == 1

    def test_private_record_audit_called(self):
        detection = create_test_detection()
        assert len(detection._audit_trail) == 1

    def test_update_raises(self):
        detection = create_test_detection()
        with pytest.raises(AttributeError):
            detection.update("admin", prevented=False)

    def test_delete_raises(self):
        detection = create_test_detection()
        with pytest.raises(AttributeError):
            detection.delete("admin")

    def test_restore_raises(self):
        detection = create_test_detection()
        with pytest.raises(AttributeError):
            detection.restore("admin")

    def test_activate_returns_self(self):
        detection = create_test_detection()
        activated = detection.activate("admin")
        assert activated is detection

    def test_deactivate_returns_self(self):
        detection = create_test_detection()
        deactivated = detection.deactivate("admin")
        assert deactivated is detection

    def test_lock_returns_self(self):
        detection = create_test_detection()
        locked = detection.lock("admin", "test")
        assert locked is detection

    def test_unlock_returns_self(self):
        detection = create_test_detection()
        unlocked = detection.unlock("admin")
        assert unlocked is detection

    def test_create_returns_self(self):
        detection = create_test_detection()
        result = detection.create("admin")
        assert result is detection

    def test_validate_returns_valid(self):
        detection = create_test_detection()
        result = detection.validate()
        assert result["is_valid"]
        assert result["detection_id"] == str(detection.detection_id)

    def test_validate_returns_error_on_invalid(self):
        detection = create_test_detection()
        detection.version_number = 0
        with pytest.raises(ValueError):
            ForbiddenStateDetection(
                detection_id=uuid.uuid4(),
                state_id=uuid.uuid4(),
                category=ForbiddenStateCategory.NEGATIVE_CASH,
                severity=ForbiddenStateSeverity.HIGH,
                detected_at=datetime.now(UTC),
                detection_method=StateDetectionMethod.PRE_TRANSACTION_VALIDATION,
                current_state={},
                attempted_action={},
                prevented=True,
                action_taken=ForbiddenStateAction.REJECT,
                source_module="test",
                resolved=False,
                version_number=0,
            )

    def test_to_dict_contains_fields(self):
        detection = create_test_detection()
        d = detection.to_dict()
        assert d["category"] == "NEGATIVE_CASH"
        assert d["prevented"]
        assert d["action_taken"] == "REJECT"
        assert d["source_module"] == "test_module"

    def test_from_dict_reconstructs(self):
        detection = create_test_detection()
        d = detection.to_dict()
        reconstructed = ForbiddenStateDetection.from_dict(d)
        assert reconstructed.detection_id == detection.detection_id
        assert reconstructed.category == detection.category
        assert reconstructed.prevented == detection.prevented
        assert reconstructed.action_taken == detection.action_taken

    def test_clone_creates_new_instance(self):
        detection = create_test_detection()
        cloned = detection.clone()
        assert cloned.detection_id != detection.detection_id
        assert cloned.category == detection.category
        assert not cloned.resolved
        assert cloned.version_number == 1

    def test_snapshot_returns_summary(self):
        detection = create_test_detection()
        snap = detection.snapshot()
        assert snap["detection_id"] == str(detection.detection_id)
        assert snap["category"] == detection.category.name

    def test_version(self):
        detection = create_test_detection()
        assert detection.version() == 1

    def test_audit_trail_records(self):
        detection = create_test_detection()
        assert len(detection.audit_trail()) >= 1
        detection.touch("toucher")
        trail = detection.audit_trail()
        assert len(trail) >= 2
        assert trail[-1]["action"] == "TOUCH"

    def test_compute_fingerprint_consistent(self):
        detection = create_test_detection()
        fp1 = detection.compute_fingerprint()
        fp2 = detection.compute_fingerprint()
        assert fp1 == fp2

    def test_compute_fingerprint_changes_with_state(self):
        detection = create_test_detection()
        fp1 = detection.compute_fingerprint()
        detection.current_state["balance"] = "200"
        fp2 = detection.compute_fingerprint()
        assert fp1 != fp2

    def test_resolve_marks_resolved(self):
        detection = create_test_detection()
        resolved = detection.resolve("admin", "Fixed")
        assert resolved.resolved
        assert resolved.resolved_at is not None
        assert resolved.resolved_by == "admin"
        assert resolved.version_number == detection.version_number + 1

    def test_resolve_already_resolved_raises(self):
        detection = create_test_detection()
        resolved = detection.resolve("admin", "Fixed")
        with pytest.raises(ValueError, match="Already resolved"):
            resolved.resolve("admin2", "Again")


# ============================================================================
# Tests for ForbiddenStateDetector static methods
# ============================================================================

class TestForbiddenStateDetector:
    def test_detect_negative_cash_allowed(self):
        is_forbidden, details, action = ForbiddenStateDetector.detect_negative_cash(
            current_balance=Decimal("100"),
            proposed_change=Decimal("-50"),
            allow_overdraft=False,
        )
        assert not is_forbidden
        assert details == {}
        assert action is None

    def test_detect_negative_cash_forbidden(self):
        is_forbidden, details, action = ForbiddenStateDetector.detect_negative_cash(
            current_balance=Decimal("100"),
            proposed_change=Decimal("-150"),
            allow_overdraft=False,
        )
        assert is_forbidden
        assert details["new_balance"] == "-50"
        assert action == ForbiddenStateAction.REJECT

    def test_detect_negative_cash_with_overdraft_allowed(self):
        is_forbidden, details, action = ForbiddenStateDetector.detect_negative_cash(
            current_balance=Decimal("100"),
            proposed_change=Decimal("-120"),
            allow_overdraft=True,
            overdraft_limit=Decimal("50"),
        )
        assert not is_forbidden
        assert details == {}
        assert action is None

    def test_detect_negative_cash_exceeds_overdraft(self):
        is_forbidden, details, action = ForbiddenStateDetector.detect_negative_cash(
            current_balance=Decimal("100"),
            proposed_change=Decimal("-200"),
            allow_overdraft=True,
            overdraft_limit=Decimal("50"),
        )
        assert is_forbidden
        assert details["new_balance"] == "-100"
        assert details["excess"] == "50"
        assert action == ForbiddenStateAction.REJECT

    def test_detect_negative_inventory_allowed(self):
        is_forbidden, details, action = ForbiddenStateDetector.detect_negative_inventory(
            current_quantity=Decimal("10"),
            proposed_change=Decimal("-5"),
            allow_backorder=False,
        )
        assert not is_forbidden
        assert details == {}
        assert action is None

    def test_detect_negative_inventory_forbidden(self):
        is_forbidden, details, action = ForbiddenStateDetector.detect_negative_inventory(
            current_quantity=Decimal("10"),
            proposed_change=Decimal("-15"),
            allow_backorder=False,
        )
        assert is_forbidden
        assert details["new_quantity"] == "-5"
        assert action == ForbiddenStateAction.REJECT

    def test_detect_negative_inventory_with_backorder(self):
        is_forbidden, details, action = ForbiddenStateDetector.detect_negative_inventory(
            current_quantity=Decimal("10"),
            proposed_change=Decimal("-15"),
            allow_backorder=True,
        )
        assert is_forbidden
        assert details["new_quantity"] == "-5"
        assert action == ForbiddenStateAction.WARN

    def test_detect_negative_receivable_allowed(self):
        is_forbidden, details, action = ForbiddenStateDetector.detect_negative_receivable(
            current_balance=Decimal("1000"),
            proposed_payment=Decimal("500"),
        )
        assert not is_forbidden
        assert details == {}
        assert action is None

    def test_detect_negative_receivable_forbidden(self):
        is_forbidden, details, action = ForbiddenStateDetector.detect_negative_receivable(
            current_balance=Decimal("1000"),
            proposed_payment=Decimal("1500"),
        )
        assert is_forbidden
        assert details["overpayment"] == "500"
        assert action == ForbiddenStateAction.REJECT

    def test_detect_imbalanced_journal_allowed(self):
        is_forbidden, details, action = ForbiddenStateDetector.detect_imbalanced_journal(
            total_debit=Decimal("100"),
            total_credit=Decimal("100"),
            tolerance=Decimal("0.01"),
        )
        assert not is_forbidden
        assert details == {}
        assert action is None

    def test_detect_imbalanced_journal_forbidden(self):
        is_forbidden, details, action = ForbiddenStateDetector.detect_imbalanced_journal(
            total_debit=Decimal("100"),
            total_credit=Decimal("100.1"),
            tolerance=Decimal("0.01"),
        )
        assert is_forbidden
        assert float(details["difference"]) == -0.1
        assert action == ForbiddenStateAction.REJECT

    def test_detect_backdated_transaction_allowed(self):
        now = datetime.now(UTC)
        period_start = now - timedelta(days=10)
        is_forbidden, details, action = ForbiddenStateDetector.detect_backdated_transaction(
            transaction_date=now - timedelta(days=5),
            current_period_start=period_start,
            max_backdate_days=30,
        )
        assert not is_forbidden
        assert details == {}
        assert action is None

    def test_detect_backdated_transaction_forbidden(self):
        now = datetime.now(UTC)
        period_start = now - timedelta(days=10)
        is_forbidden, details, action = ForbiddenStateDetector.detect_backdated_transaction(
            transaction_date=now - timedelta(days=40),
            current_period_start=period_start,
            max_backdate_days=30,
        )
        assert is_forbidden
        assert details["days_back"] == 30  # 40 - 10 = 30
        assert action == ForbiddenStateAction.REJECT

    def test_detect_future_transaction_allowed(self):
        now = datetime.now(UTC)
        period_end = now + timedelta(days=5)
        is_forbidden, details, action = ForbiddenStateDetector.detect_future_transaction(
            transaction_date=now + timedelta(days=2),
            current_period_end=period_end,
            max_forward_days=7,
        )
        assert not is_forbidden
        assert details == {}
        assert action is None

    def test_detect_future_transaction_forbidden(self):
        now = datetime.now(UTC)
        period_end = now + timedelta(days=5)
        is_forbidden, details, action = ForbiddenStateDetector.detect_future_transaction(
            transaction_date=now + timedelta(days=10),
            current_period_end=period_end,
            max_forward_days=7,
        )
        assert is_forbidden
        assert details["days_forward"] == 5  # 10 - 5 = 5
        assert action == ForbiddenStateAction.REJECT

    def test_detect_cross_entity_posting_allowed(self):
        tx_entity = uuid.uuid4()
        other_entity = uuid.uuid4()
        authorized = {frozenset([tx_entity, other_entity])}
        is_forbidden, details, action = ForbiddenStateDetector.detect_cross_entity_posting(
            transaction_legal_entity_id=tx_entity,
            journal_line_legal_entity_ids=[other_entity],
            authorized_inter_entities=authorized,
        )
        assert not is_forbidden
        assert details == {}
        assert action is None

    def test_detect_cross_entity_posting_forbidden(self):
        tx_entity = uuid.uuid4()
        other_entity = uuid.uuid4()
        unauthorized_entity = uuid.uuid4()
        authorized = {frozenset([tx_entity, other_entity])}
        is_forbidden, details, action = ForbiddenStateDetector.detect_cross_entity_posting(
            transaction_legal_entity_id=tx_entity,
            journal_line_legal_entity_ids=[other_entity, unauthorized_entity],
            authorized_inter_entities=authorized,
        )
        assert is_forbidden
        assert str(unauthorized_entity) in str(details["unauthorized_pair"])
        assert action == ForbiddenStateAction.REJECT

    def test_detect_broken_hash_chain_allowed(self):
        is_forbidden, details, action = ForbiddenStateDetector.detect_broken_hash_chain(
            expected_previous_hash="abc",
            actual_previous_hash="abc",
        )
        assert not is_forbidden
        assert details == {}
        assert action is None

    def test_detect_broken_hash_chain_forbidden(self):
        is_forbidden, details, action = ForbiddenStateDetector.detect_broken_hash_chain(
            expected_previous_hash="abc",
            actual_previous_hash="def",
        )
        assert is_forbidden
        assert details["expected_hash"] == "abc..."
        assert action == ForbiddenStateAction.FREEZE_SYSTEM

    def test_detect_missing_audit_event_allowed(self):
        is_forbidden, details, action = ForbiddenStateDetector.detect_missing_audit_event(
            expected_sequence=5,
            actual_sequence=6,
        )
        assert not is_forbidden
        assert details == {}
        assert action is None

    def test_detect_missing_audit_event_forbidden(self):
        is_forbidden, details, action = ForbiddenStateDetector.detect_missing_audit_event(
            expected_sequence=5,
            actual_sequence=10,
        )
        assert is_forbidden
        assert details["missing_count"] == 4
        assert action == ForbiddenStateAction.CRITICAL

    def test_detect_tax_mismatch_allowed(self):
        is_forbidden, details, action = ForbiddenStateDetector.detect_tax_mismatch(
            calculated_tax=Decimal("100"),
            reported_tax=Decimal("100"),
            tolerance=Decimal("0.01"),
        )
        assert not is_forbidden
        assert details == {}
        assert action is None

    def test_detect_tax_mismatch_forbidden(self):
        is_forbidden, details, action = ForbiddenStateDetector.detect_tax_mismatch(
            calculated_tax=Decimal("100"),
            reported_tax=Decimal("100.5"),
            tolerance=Decimal("0.01"),
        )
        assert is_forbidden
        assert float(details["difference"]) == -0.5
        assert action == ForbiddenStateAction.REJECT

    def test_detect_period_closure_violation_allowed(self):
        now = datetime.now(UTC)
        period_start = now - timedelta(days=10)
        period_end = now + timedelta(days=10)
        is_forbidden, details, action = ForbiddenStateDetector.detect_period_closure_violation(
            period_status="OPEN",
            transaction_date=now,
            period_start=period_start,
            period_end=period_end,
        )
        assert not is_forbidden
        assert details == {}
        assert action is None

    def test_detect_period_closure_violation_forbidden(self):
        now = datetime.now(UTC)
        period_start = now - timedelta(days=10)
        period_end = now + timedelta(days=10)
        is_forbidden, details, action = ForbiddenStateDetector.detect_period_closure_violation(
            period_status="CLOSED",
            transaction_date=now,
            period_start=period_start,
            period_end=period_end,
        )
        assert is_forbidden
        assert details["period_status"] == "CLOSED"
        assert action == ForbiddenStateAction.REJECT

    def test_detect_negative_equity_allowed(self):
        is_forbidden, details, action = ForbiddenStateDetector.detect_negative_equity(
            total_equity=Decimal("1000"),
            minimum_equity=Decimal("0"),
        )
        assert not is_forbidden
        assert details == {}
        assert action is None

    def test_detect_negative_equity_forbidden(self):
        is_forbidden, details, action = ForbiddenStateDetector.detect_negative_equity(
            total_equity=Decimal("-100"),
            minimum_equity=Decimal("0"),
        )
        assert is_forbidden
        assert details["total_equity"] == "-100"
        assert action == ForbiddenStateAction.FREEZE_SYSTEM

    def test_detect_period_mixing_allowed(self):
        now = datetime.now(UTC)
        period1 = (now - timedelta(days=5), now + timedelta(days=5))
        period2 = (now + timedelta(days=10), now + timedelta(days=20))
        dates = [now, now + timedelta(days=2)]
        is_forbidden, details, action = ForbiddenStateDetector.detect_period_mixing(
            transaction_dates=dates,
            period_boundaries=[period1, period2],
        )
        assert not is_forbidden
        assert details == {}
        assert action is None

    def test_detect_period_mixing_forbidden(self):
        now = datetime.now(UTC)
        period1 = (now - timedelta(days=5), now + timedelta(days=5))
        period2 = (now + timedelta(days=10), now + timedelta(days=20))
        dates = [now, now + timedelta(days=15)]
        is_forbidden, details, action = ForbiddenStateDetector.detect_period_mixing(
            transaction_dates=dates,
            period_boundaries=[period1, period2],
        )
        assert is_forbidden
        assert len(details["periods_found"]) == 2
        assert action == ForbiddenStateAction.REJECT

    def test_detect_privilege_escalation_allowed(self):
        is_forbidden, details, action = ForbiddenStateDetector.detect_privilege_escalation(
            user_roles=["admin"],
            required_roles=["admin", "finance"],
            user_permissions={"read", "write"},
            required_permissions={"read", "write"},
        )
        assert not is_forbidden
        assert details == {}
        assert action is None

    def test_detect_privilege_escalation_forbidden(self):
        is_forbidden, details, action = ForbiddenStateDetector.detect_privilege_escalation(
            user_roles=["guest"],
            required_roles=["admin"],
            user_permissions={"read"},
            required_permissions={"read", "write"},
        )
        assert is_forbidden
        assert details["missing_permissions"] == ["write"]
        assert action == ForbiddenStateAction.REJECT


# ============================================================================
# Tests for ForbiddenStatesRegistry
# ============================================================================

class TestForbiddenStatesRegistry:
    def test_initialization_loads_defaults(self):
        registry = ForbiddenStatesRegistry()
        assert len(registry.states) > 0
        assert len(registry.detections) == 0

    def test_save_and_get_state(self):
        registry = ForbiddenStatesRegistry()
        state = create_test_state()
        registry.save_state(state)
        retrieved = registry.get_state(state.state_id)
        assert retrieved is not None
        assert retrieved.state_id == state.state_id

    def test_get_all_states(self):
        registry = ForbiddenStatesRegistry()
        state1 = create_test_state()
        state2 = create_test_state(category=ForbiddenStateCategory.NEGATIVE_INVENTORY)
        registry.save_state(state1)
        registry.save_state(state2)
        states = registry.get_all_states()
        assert len(states) >= 2

    def test_delete_state(self):
        registry = ForbiddenStatesRegistry()
        state = create_test_state()
        registry.save_state(state)
        result = registry.delete_state(state.state_id)
        assert result
        assert registry.get_state(state.state_id) is None

    def test_save_and_get_detections(self):
        registry = ForbiddenStatesRegistry()
        detection = create_test_detection()
        registry.save_detection(detection)
        detections = registry.get_detections()
        assert len(detections) >= 1
        found = next((d for d in detections if d.detection_id == detection.detection_id), None)
        assert found is not None

    def test_get_detections_filter_by_category(self):
        registry = ForbiddenStatesRegistry()
        d1 = create_test_detection(category=ForbiddenStateCategory.NEGATIVE_CASH)
        d2 = create_test_detection(category=ForbiddenStateCategory.NEGATIVE_INVENTORY)
        registry.save_detection(d1)
        registry.save_detection(d2)
        result = registry.get_detections(category=ForbiddenStateCategory.NEGATIVE_CASH)
        assert len(result) == 1
        assert result[0].category == ForbiddenStateCategory.NEGATIVE_CASH

    def test_get_detections_filter_by_date(self):
        registry = ForbiddenStatesRegistry()
        now = datetime.now(UTC)
        d1 = create_test_detection()
        d1.detected_at = now - timedelta(days=10)
        d2 = create_test_detection()
        d2.detected_at = now - timedelta(days=2)
        registry.save_detection(d1)
        registry.save_detection(d2)
        result = registry.get_detections(from_date=now - timedelta(days=5))
        assert len(result) == 1
        assert result[0].detected_at >= now - timedelta(days=5)

    def test_get_detections_resolved_only(self):
        registry = ForbiddenStatesRegistry()
        d1 = create_test_detection(resolved=True)
        d2 = create_test_detection(resolved=False)
        registry.save_detection(d1)
        registry.save_detection(d2)
        result = registry.get_detections(resolved_only=True)
        assert all(d.resolved for d in result)

    def test_get_detections_unresolved_only(self):
        registry = ForbiddenStatesRegistry()
        d1 = create_test_detection(resolved=True)
        d2 = create_test_detection(resolved=False)
        registry.save_detection(d1)
        registry.save_detection(d2)
        result = registry.get_detections(unresolved_only=True)
        assert all(not d.resolved for d in result)

    def test_get_detections_prevented_only(self):
        registry = ForbiddenStatesRegistry()
        d1 = create_test_detection(prevented=True)
        d2 = create_test_detection(prevented=False)
        registry.save_detection(d1)
        registry.save_detection(d2)
        result = registry.get_detections(prevented_only=True)
        assert all(d.prevented for d in result)

    def test_resolve_detection(self):
        registry = ForbiddenStatesRegistry()
        detection = create_test_detection(resolved=False)
        registry.save_detection(detection)
        resolved = registry.resolve_detection(detection.detection_id, "admin", "Fixed")
        assert resolved is not None
        assert resolved.resolved
        assert resolved.resolved_by == "admin"

    def test_resolve_detection_not_found(self):
        registry = ForbiddenStatesRegistry()
        result = registry.resolve_detection(uuid.uuid4(), "admin", "Fixed")
        assert result is None

    def test_check_no_state_defined(self):
        registry = ForbiddenStatesRegistry()
        is_forbidden, detection, action = registry.check(
            category=ForbiddenStateCategory.NEGATIVE_CASH,
            context={"current_balance": Decimal("100"), "proposed_change": Decimal("-50")},
        )
        assert not is_forbidden
        assert detection is None
        assert action is None

    def test_check_detects_forbidden(self):
        registry = ForbiddenStatesRegistry()
        is_forbidden, detection, action = registry.check(
            category=ForbiddenStateCategory.NEGATIVE_CASH,
            context={"current_balance": Decimal("100"), "proposed_change": Decimal("-150")},
        )
        assert is_forbidden
        assert detection is not None
        assert detection.category == ForbiddenStateCategory.NEGATIVE_CASH
        assert action == ForbiddenStateAction.REJECT

    def test_check_with_override_allowed(self):
        registry = ForbiddenStatesRegistry()
        is_forbidden, detection, action = registry.check(
            category=ForbiddenStateCategory.NEGATIVE_CASH,
            context={"current_balance": Decimal("100"), "proposed_change": Decimal("-150")},
            override=True,
            override_authorized_by="admin",
        )
        assert is_forbidden
        assert detection is not None
        assert detection.override_used
        assert detection.action_taken == ForbiddenStateAction.WARN  # Override changes action

    def test_check_with_override_unauthorized(self):
        registry = ForbiddenStatesRegistry()
        is_forbidden, detection, action = registry.check(
            category=ForbiddenStateCategory.NEGATIVE_CASH,
            context={"current_balance": Decimal("100"), "proposed_change": Decimal("-150")},
            override=True,
            override_authorized_by="unauthorized",
        )
        assert is_forbidden
        assert detection is not None
        assert not detection.override_used  # Not authorized

    def test_check_with_catastrophic_severity_calls_handler(self):
        registry = ForbiddenStatesRegistry()
        with patch.object(registry, "_handle_catastrophic_detection") as mock_handle:
            state = ForbiddenStateDefinition(
                state_id=uuid.uuid4(),
                category=ForbiddenStateCategory.BROKEN_HASH_CHAIN,
                name="Test",
                description="Desc",
                severity=ForbiddenStateSeverity.CATASTROPHIC,
                detection_method=StateDetectionMethod.PRE_TRANSACTION_VALIDATION,
                default_action=ForbiddenStateAction.FREEZE_SYSTEM,
                recovery_action="Recovery",
                auto_correct=False,
                is_active=True,
                created_at=datetime.now(UTC),
                created_by="tester",
                approved_by=["a"],
                version="1.0",
                override_allowed=False,
                override_roles=[],
            )
            registry.save_state(state)
            is_forbidden, detection, action = registry.check(
                category=ForbiddenStateCategory.BROKEN_HASH_CHAIN,
                context={"expected_previous_hash": "abc", "actual_previous_hash": "def"},
            )
            assert is_forbidden
            assert detection is not None
            mock_handle.assert_called_once_with(detection)

    def test_is_action_forbidden(self):
        registry = ForbiddenStatesRegistry()
        result = registry.is_action_forbidden(
            category=ForbiddenStateCategory.NEGATIVE_CASH,
            context={"current_balance": Decimal("100"), "proposed_change": Decimal("-150")},
        )
        assert result

        result = registry.is_action_forbidden(
            category=ForbiddenStateCategory.NEGATIVE_CASH,
            context={"current_balance": Decimal("100"), "proposed_change": Decimal("-50")},
        )
        assert not result

    def test_get_unresolved_detections(self):
        registry = ForbiddenStatesRegistry()
        d1 = create_test_detection(resolved=True)
        d2 = create_test_detection(resolved=False)
        registry.save_detection(d1)
        registry.save_detection(d2)
        unresolved = registry.get_unresolved_detections()
        assert len(unresolved) == 1
        assert unresolved[0].detection_id == d2.detection_id

    def test_get_statistics(self):
        registry = ForbiddenStatesRegistry()
        d1 = create_test_detection(prevented=True)
        d2 = create_test_detection(prevented=False)
        d3 = create_test_detection(resolved=True)
        registry.save_detection(d1)
        registry.save_detection(d2)
        registry.save_detection(d3)
        stats = registry.get_statistics()
        assert stats["total_states"] > 0
        assert stats["active_states"] > 0
        assert stats["total_detections"] >= 3
        assert stats["unresolved_detections"] >= 1
        assert stats["prevented_detections"] >= 1
        assert "by_category" in stats
        assert "by_severity" in stats

    def test_reset(self):
        registry = ForbiddenStatesRegistry()
        state = create_test_state()
        registry.save_state(state)
        detection = create_test_detection()
        registry.save_detection(detection)
        registry.reset()
        assert len(registry.states) > 0
        assert len(registry.detections) == 0


# ============================================================================
# Tests for ForbiddenStatesService
# ============================================================================

class TestForbiddenStatesService:
    def test_singleton(self):
        svc1 = ForbiddenStatesService()
        svc2 = ForbiddenStatesService()
        assert svc1 is svc2

    def test_get_registry(self):
        svc = ForbiddenStatesService()
        registry = svc.get_registry()
        assert isinstance(registry, ForbiddenStatesRegistry)

    def test_save_and_get_state(self):
        svc = ForbiddenStatesService()
        state = create_test_state()
        svc.save_state(state)
        retrieved = svc.get_state(state.state_id)
        assert retrieved is not None

    def test_get_all_states(self):
        svc = ForbiddenStatesService()
        states = svc.get_all_states()
        assert len(states) > 0

    def test_delete_state(self):
        svc = ForbiddenStatesService()
        state = create_test_state()
        svc.save_state(state)
        result = svc.delete_state(state.state_id)
        assert result

    def test_save_and_get_detections(self):
        svc = ForbiddenStatesService()
        detection = create_test_detection()
        svc.save_detection(detection)
        detections = svc.get_detections()
        assert len(detections) >= 1

    def test_resolve_detection(self):
        svc = ForbiddenStatesService()
        detection = create_test_detection(resolved=False)
        svc.save_detection(detection)
        resolved = svc.resolve_detection(detection.detection_id, "admin", "Fixed")
        assert resolved is not None
        assert resolved.resolved

    def test_check_negative_cash(self):
        svc = ForbiddenStatesService()
        is_forbidden, detection, action = svc.check_negative_cash(
            current_balance=Decimal("100"),
            proposed_change=Decimal("-150"),
        )
        assert is_forbidden
        assert detection is not None
        assert action == ForbiddenStateAction.REJECT

    def test_check_negative_inventory(self):
        svc = ForbiddenStatesService()
        is_forbidden, detection, action = svc.check_negative_inventory(
            current_quantity=Decimal("10"),
            proposed_change=Decimal("-15"),
        )
        assert is_forbidden
        assert detection is not None
        assert action == ForbiddenStateAction.REJECT

    def test_check_negative_receivable(self):
        svc = ForbiddenStatesService()
        is_forbidden, detection, action = svc.check_negative_receivable(
            current_balance=Decimal("1000"),
            proposed_payment=Decimal("1500"),
        )
        assert is_forbidden
        assert detection is not None

    def test_check_imbalanced_journal(self):
        svc = ForbiddenStatesService()
        is_forbidden, detection, action = svc.check_imbalanced_journal(
            total_debit=Decimal("100"),
            total_credit=Decimal("100.1"),
        )
        assert is_forbidden
        assert detection is not None

    def test_check_backdated_transaction(self):
        svc = ForbiddenStatesService()
        now = datetime.now(UTC)
        period_start = now - timedelta(days=10)
        is_forbidden, detection, action = svc.check_backdated_transaction(
            transaction_date=now - timedelta(days=40),
            current_period_start=period_start,
            max_backdate_days=30,
        )
        assert is_forbidden
        assert detection is not None

    def test_check_cross_entity_posting(self):
        svc = ForbiddenStatesService()
        tx_entity = uuid.uuid4()
        other_entity = uuid.uuid4()
        unauthorized_entity = uuid.uuid4()
        authorized = {frozenset([tx_entity, other_entity])}
        is_forbidden, detection, action = svc.check_cross_entity_posting(
            transaction_legal_entity_id=tx_entity,
            journal_line_legal_entity_ids=[other_entity, unauthorized_entity],
            authorized_inter_entities=authorized,
        )
        assert is_forbidden
        assert detection is not None

    def test_check_period_closure(self):
        svc = ForbiddenStatesService()
        now = datetime.now(UTC)
        period_start = now - timedelta(days=10)
        period_end = now + timedelta(days=10)
        is_forbidden, detection, action = svc.check_period_closure(
            period_status="CLOSED",
            transaction_date=now,
            period_start=period_start,
            period_end=period_end,
        )
        assert is_forbidden
        assert detection is not None

    def test_check_broken_hash_chain(self):
        svc = ForbiddenStatesService()
        is_forbidden, detection, action = svc.check_broken_hash_chain(
            expected_previous_hash="abc",
            actual_previous_hash="def",
        )
        assert is_forbidden
        assert detection is not None
        assert action == ForbiddenStateAction.FREEZE_SYSTEM

    def test_get_detection_history(self):
        svc = ForbiddenStatesService()
        detection = create_test_detection()
        svc.save_detection(detection)
        history = svc.get_detection_history()
        assert len(history) >= 1

    def test_get_statistics(self):
        svc = ForbiddenStatesService()
        stats = svc.get_statistics()
        assert "total_states" in stats

    def test_get_forbidden_states_service_singleton(self):
        svc1 = get_forbidden_states_service()
        svc2 = get_forbidden_states_service()
        assert svc1 is svc2


# ============================================================================
# Tests for helper functions
# ============================================================================

class TestHelperFunctions:
    def test_get_detector_for_state_exists(self):
        detector = get_detector_for_state(ForbiddenStateCategory.NEGATIVE_CASH)
        assert detector is not None
        assert callable(detector)

    def test_get_detector_for_state_not_exists(self):
        detector = get_detector_for_state(ForbiddenStateCategory.IMBALANCED_JOURNAL)
        assert detector is not None

    def test_get_forbidden_states_service_singleton(self):
        svc1 = get_forbidden_states_service()
        svc2 = get_forbidden_states_service()
        assert svc1 is svc2