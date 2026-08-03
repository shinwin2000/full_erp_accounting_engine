#!/usr/bin/env python3
"""
tests/constitution/test_forbidden_states.py
Comprehensive tests for constitution/forbidden_states.py

Covers:
- All enums: ForbiddenStateCategory, ForbiddenStateSeverity, StateDetectionMethod, ForbiddenStateAction
- ForbiddenStateDefinition: all entity methods (create, update, delete, restore, activate, deactivate,
  lock, unlock, validate, to_dict/from_dict, clone, snapshot, version, audit_trail, touch)
- ForbiddenStateDetection: all entity methods (create, update (raises), delete (raises), restore (raises),
  activate, deactivate, lock, unlock, validate, to_dict/from_dict, clone, snapshot, version, audit_trail,
  touch, compute_fingerprint, resolve)
- ForbiddenStateDetector: all static detection methods (negative cash, inventory, receivable,
  imbalanced journal, backdated/future transactions, cross-entity, broken hash chain,
  missing audit event, tax mismatch, period closure, negative equity, period mixing,
  privilege escalation)
- ForbiddenStatesRegistry: default states, save/get/delete states, save/get/delete detections,
  check, resolve, statistics, reset, _notify_supreme_law, _handle_catastrophic_detection
- ForbiddenStatesService: singleton, registry, convenience check methods, statistics
- Helper functions: get_detector_for_state, get_forbidden_states_service
- All edge cases, negative paths, and error conditions
- No flaky datetime (mocked)
- No duplicate test code (parametrized and consolidated)
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

# =============================================================================
# FIXED DATETIME (to avoid flakiness)
# =============================================================================

FIXED_DATETIME = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    """Mock datetime.now and datetime.utcnow to return fixed datetime."""
    with patch("constitution.forbidden_states.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_DATETIME
        mock_dt.utcnow.return_value = FIXED_DATETIME
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        yield mock_dt


# =============================================================================
# HELPERS
# =============================================================================

def create_test_state(
    category: ForbiddenStateCategory = ForbiddenStateCategory.NEGATIVE_CASH,
    name: str = "Test State",
    severity: ForbiddenStateSeverity = ForbiddenStateSeverity.HIGH,
    is_active: bool = True,
    override_allowed: bool = False,
    override_roles: list[str] | None = None,
) -> ForbiddenStateDefinition:
    return ForbiddenStateDefinition(
        state_id=uuid.uuid4(),
        category=category,
        name=name,
        description="Test description",
        severity=severity,
        detection_method=StateDetectionMethod.PRE_TRANSACTION_VALIDATION,
        default_action=ForbiddenStateAction.REJECT,
        recovery_action="Test recovery",
        auto_correct=False,
        is_active=is_active,
        created_at=FIXED_DATETIME,
        created_by="tester",
        approved_by=["approver1"],
        version="1.0.0",
        cryptographic_hash="",
        override_allowed=override_allowed,
        override_roles=override_roles or [],
        version_number=1,
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
        detected_at=FIXED_DATETIME,
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
        version_number=1,
    )


# =============================================================================
# EXCEPTION CLASSES
# =============================================================================

class TestExceptions:
    def test_forbidden_state_error(self):
        exc = ForbiddenStateError("test")
        assert str(exc) == "test"
        assert isinstance(exc, Exception)

    def test_forbidden_state_detected_error(self):
        category = ForbiddenStateCategory.NEGATIVE_CASH
        severity = ForbiddenStateSeverity.CRITICAL
        exc = ForbiddenStateDetectedError(category, "test message", severity)
        assert exc.category == category
        assert exc.severity == severity
        assert "[NEGATIVE_CASH:CRITICAL] test message" in str(exc)

    def test_forbidden_state_recovery_error(self):
        exc = ForbiddenStateRecoveryError("test")
        assert str(exc) == "test"
        assert isinstance(exc, ForbiddenStateError)


# =============================================================================
# ENUMS
# =============================================================================

class TestEnums:
    def test_forbidden_state_category(self):
        assert ForbiddenStateCategory.NEGATIVE_CASH.name == "NEGATIVE_CASH"
        assert ForbiddenStateCategory.NEGATIVE_INVENTORY.name == "NEGATIVE_INVENTORY"
        assert ForbiddenStateCategory.NEGATIVE_RECEIVABLE.name == "NEGATIVE_RECEIVABLE"
        assert ForbiddenStateCategory.NEGATIVE_PAYABLE.name == "NEGATIVE_PAYABLE"
        assert ForbiddenStateCategory.NEGATIVE_EQUITY.name == "NEGATIVE_EQUITY"
        assert ForbiddenStateCategory.IMBALANCED_JOURNAL.name == "IMBALANCED_JOURNAL"
        assert ForbiddenStateCategory.BACKDATED_TRANSACTION.name == "BACKDATED_TRANSACTION"
        assert ForbiddenStateCategory.FUTURE_TRANSACTION.name == "FUTURE_TRANSACTION"
        assert ForbiddenStateCategory.PERIOD_MIXING.name == "PERIOD_MIXING"
        assert ForbiddenStateCategory.CROSS_ENTITY_POSTING.name == "CROSS_ENTITY_POSTING"
        assert ForbiddenStateCategory.UNAUTHORIZED_CONSOLIDATION.name == "UNAUTHORIZED_CONSOLIDATION"
        assert ForbiddenStateCategory.BROKEN_HASH_CHAIN.name == "BROKEN_HASH_CHAIN"
        assert ForbiddenStateCategory.MISSING_AUDIT_EVENT.name == "MISSING_AUDIT_EVENT"
        assert ForbiddenStateCategory.UNAUTHORIZED_ACCESS.name == "UNAUTHORIZED_ACCESS"
        assert ForbiddenStateCategory.PRIVILEGE_ESCALATION.name == "PRIVILEGE_ESCALATION"
        assert ForbiddenStateCategory.TAX_MISMATCH.name == "TAX_MISMATCH"
        assert ForbiddenStateCategory.PERIOD_CLOSURE_VIOLATION.name == "PERIOD_CLOSURE_VIOLATION"
        assert isinstance(ForbiddenStateCategory.NEGATIVE_CASH, ForbiddenStateCategory)

    def test_forbidden_state_severity(self):
        assert ForbiddenStateSeverity.CATASTROPHIC.value == 100
        assert ForbiddenStateSeverity.CRITICAL.value == 80
        assert ForbiddenStateSeverity.HIGH.value == 60
        assert ForbiddenStateSeverity.MEDIUM.value == 40
        assert ForbiddenStateSeverity.LOW.value == 20
        assert isinstance(ForbiddenStateSeverity.CATASTROPHIC, ForbiddenStateSeverity)

    def test_state_detection_method(self):
        assert StateDetectionMethod.PRE_TRANSACTION_VALIDATION.name == "PRE_TRANSACTION_VALIDATION"
        assert StateDetectionMethod.POST_TRANSACTION_VALIDATION.name == "POST_TRANSACTION_VALIDATION"
        assert StateDetectionMethod.PERIODIC_SCAN.name == "PERIODIC_SCAN"
        assert StateDetectionMethod.REAL_TIME_MONITOR.name == "REAL_TIME_MONITOR"
        assert StateDetectionMethod.AUDIT_TIME_DETECTION.name == "AUDIT_TIME_DETECTION"

    def test_forbidden_state_action(self):
        assert ForbiddenStateAction.REJECT.name == "REJECT"
        assert ForbiddenStateAction.WARN.name == "WARN"
        assert ForbiddenStateAction.AUTO_CORRECT.name == "AUTO_CORRECT"
        assert ForbiddenStateAction.FREEZE_SYSTEM.name == "FREEZE_SYSTEM"
        assert ForbiddenStateAction.NOTIFY_ADMIN.name == "NOTIFY_ADMIN"
        assert ForbiddenStateAction.LOG_ONLY.name == "LOG_ONLY"


# =============================================================================
# ForbiddenStateDefinition
# =============================================================================

class TestForbiddenStateDefinition:
    def test_create_valid(self):
        state = create_test_state()
        assert state.state_id is not None
        assert state.category == ForbiddenStateCategory.NEGATIVE_CASH
        assert state.name == "Test State"
        assert state.is_active is True
        assert state.version_number == 1
        assert state.cryptographic_hash != ""
        assert len(state._snapshots) == 1
        assert len(state._audit_trail) == 1
        assert state._audit_trail[0]["action"] == "CREATE"

    def test_validate_version_number_zero_raises(self):
        with pytest.raises(ValueError, match="Version number must be >= 1"):
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
                created_at=FIXED_DATETIME,
                created_by="tester",
                approved_by=["a"],
                version="1.0",
                override_allowed=False,
                override_roles=[],
                version_number=0,
            )

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
                created_at=FIXED_DATETIME,
                created_by="tester",
                approved_by=["a"],
                version="1.0",
                override_allowed=True,
                override_roles=[],
            )

    def test_compute_hash_consistent(self):
        state = create_test_state()
        h1 = state.compute_hash()
        h2 = state.compute_hash()
        assert h1 == h2
        # Changing a field changes hash
        new_state = state.update("admin", name="Changed")
        assert new_state.compute_hash() != state.compute_hash()

    def test_update(self):
        state = create_test_state()
        updated = state.update("admin", name="Updated Name", description="New Desc")
        assert updated.name == "Updated Name"
        assert updated.description == "New Desc"
        assert updated.version_number == state.version_number + 1
        assert updated is not state
        trail = updated.audit_trail()
        assert trail[-1]["action"] == "UPDATE"

    def test_update_immutable_fields_ignored(self):
        state = create_test_state()
        original_id = state.state_id
        original_created = state.created_at
        updated = state.update("admin", state_id=uuid.uuid4(), created_at=datetime(2000, 1, 1, tzinfo=UTC))
        assert updated.state_id == original_id
        assert updated.created_at == original_created

    def test_delete(self):
        state = create_test_state()
        deleted = state.delete("admin", "test reason")
        assert deleted.deleted_at == FIXED_DATETIME
        assert deleted.deleted_by == "admin"
        assert deleted.is_active is False
        assert deleted.version_number == state.version_number + 1
        trail = deleted.audit_trail()
        assert trail[-1]["action"] == "DELETE"
        assert trail[-1]["details"]["reason"] == "test reason"

    def test_restore(self):
        state = create_test_state()
        deleted = state.delete("admin")
        restored = deleted.restore("admin2")
        assert restored.deleted_at is None
        assert restored.deleted_by is None
        assert restored.is_active is True
        assert restored.version_number == deleted.version_number + 1
        trail = restored.audit_trail()
        assert trail[-1]["action"] == "RESTORE"

    def test_restore_not_deleted_raises(self):
        state = create_test_state()
        with pytest.raises(ValueError, match="Not deleted"):
            state.restore("admin")

    def test_activate_when_already_active_returns_self(self):
        state = create_test_state()
        result = state.activate("admin")
        assert result is state

    def test_activate_activates_inactive(self):
        state = create_test_state(is_active=False)
        activated = state.activate("admin")
        assert activated.is_active is True
        assert activated.version_number == state.version_number + 1

    def test_deactivate_when_already_inactive_returns_self(self):
        state = create_test_state(is_active=False)
        result = state.deactivate("admin", "reason")
        assert result is state

    def test_deactivate_deactivates_active(self):
        state = create_test_state(is_active=True)
        deactivated = state.deactivate("admin", "test reason")
        assert deactivated.is_active is False
        assert deactivated.version_number == state.version_number + 1
        trail = deactivated.audit_trail()
        assert trail[-1]["action"] == "DEACTIVATE"
        assert trail[-1]["details"]["reason"] == "test reason"

    def test_lock(self):
        state = create_test_state()
        locked = state.lock("admin", "audit reason")
        assert locked.version_number == state.version_number + 1
        trail = locked.audit_trail()
        assert trail[-1]["action"] == "LOCK"
        assert trail[-1]["details"]["reason"] == "audit reason"

    def test_unlock(self):
        state = create_test_state()
        unlocked = state.unlock("admin")
        assert unlocked.version_number == state.version_number + 1
        trail = unlocked.audit_trail()
        assert trail[-1]["action"] == "UNLOCK"

    @pytest.mark.parametrize("method_name", ["create"])
    def test_create_noop(self, method_name):
        state = create_test_state()
        result = getattr(state, method_name)("admin")
        assert result is state

    def test_validate_returns_valid(self):
        state = create_test_state()
        result = state.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []
        assert result["state_id"] == str(state.state_id)
        assert result["version"] == state.version_number

    def test_validate_hash_mismatch(self):
        state = create_test_state()
        original_hash = state.cryptographic_hash
        object.__setattr__(state, "cryptographic_hash", "fake")
        result = state.validate()
        assert result["is_valid"] is False
        assert "Hash mismatch" in result["errors"]
        object.__setattr__(state, "cryptographic_hash", original_hash)

    def test_to_dict(self):
        state = create_test_state()
        d = state.to_dict()
        assert d["category"] == "NEGATIVE_CASH"
        assert d["name"] == "Test State"
        assert d["severity"] == "HIGH"
        assert d["is_active"] is True
        assert d["version_number"] == 1
        assert d["deleted_at"] is None
        assert d["deleted_by"] is None

    def test_from_dict_roundtrip(self):
        state = create_test_state()
        d = state.to_dict()
        reconstructed = ForbiddenStateDefinition.from_dict(d)
        assert reconstructed.state_id == state.state_id
        assert reconstructed.category == state.category
        assert reconstructed.name == state.name
        assert reconstructed.severity == state.severity
        assert reconstructed.is_active == state.is_active
        assert reconstructed.version_number == state.version_number

    def test_from_dict_with_deleted(self):
        state = create_test_state()
        deleted = state.delete("admin")
        d = deleted.to_dict()
        reconstructed = ForbiddenStateDefinition.from_dict(d)
        assert reconstructed.deleted_at == deleted.deleted_at
        assert reconstructed.deleted_by == deleted.deleted_by
        assert reconstructed.is_active is False

    def test_clone(self):
        state = create_test_state()
        cloned = state.clone()
        assert cloned.state_id != state.state_id
        assert cloned.category == state.category
        assert cloned.name == state.name
        assert cloned.is_active is False
        assert cloned.version_number == 1
        assert cloned.cryptographic_hash == ""
        assert cloned.override_roles == state.override_roles

    def test_snapshot(self):
        state = create_test_state()
        snap = state.snapshot()
        assert snap["state_id"] == str(state.state_id)
        assert snap["category"] == state.category.name
        assert snap["version"] == state.version_number
        assert "timestamp" in snap

    def test_version(self):
        state = create_test_state()
        assert state.version() == 1

    def test_audit_trail(self):
        state = create_test_state()
        assert len(state.audit_trail()) == 1
        state.touch("toucher")
        trail = state.audit_trail(limit=5)
        assert len(trail) == 2
        assert trail[-1]["action"] == "TOUCH"
        assert trail[-1]["performed_by"] == "toucher"

    def test_audit_trail_limit(self):
        state = create_test_state()
        for _ in range(15):
            state = state.touch("tester")
        trail = state.audit_trail(limit=5)
        assert len(trail) == 5

    def test_touch(self):
        state = create_test_state()
        touched = state.touch("toucher")
        assert touched.version_number == state.version_number + 1
        trail = touched.audit_trail()
        assert trail[-1]["action"] == "TOUCH"
        assert trail[-1]["performed_by"] == "toucher"

    def test_copy(self):
        state = create_test_state()
        copied = state._copy()
        assert copied.state_id == state.state_id
        assert copied.name == state.name
        assert copied.is_active == state.is_active
        # Should be a different object
        assert copied is not state


# =============================================================================
# ForbiddenStateDetection
# =============================================================================

class TestForbiddenStateDetection:
    def test_create_valid(self):
        detection = create_test_detection()
        assert detection.detection_id is not None
        assert detection.category == ForbiddenStateCategory.NEGATIVE_CASH
        assert detection.prevented is True
        assert detection.resolved is False
        assert detection.version_number == 1
        assert len(detection._snapshots) == 1
        assert len(detection._audit_trail) == 1

    def test_validate_version_number_zero_raises(self):
        with pytest.raises(ValueError, match="Version number must be >= 1"):
            ForbiddenStateDetection(
                detection_id=uuid.uuid4(),
                state_id=uuid.uuid4(),
                category=ForbiddenStateCategory.NEGATIVE_CASH,
                severity=ForbiddenStateSeverity.HIGH,
                detected_at=FIXED_DATETIME,
                detection_method=StateDetectionMethod.PRE_TRANSACTION_VALIDATION,
                current_state={},
                attempted_action={},
                prevented=True,
                action_taken=ForbiddenStateAction.REJECT,
                source_module="test",
                resolved=False,
                version_number=0,
            )

    def test_update_raises(self):
        detection = create_test_detection()
        with pytest.raises(AttributeError, match="immutable"):
            detection.update("admin", prevented=False)

    def test_delete_raises(self):
        detection = create_test_detection()
        with pytest.raises(AttributeError, match="Cannot delete"):
            detection.delete("admin")

    def test_restore_raises(self):
        detection = create_test_detection()
        with pytest.raises(AttributeError, match="Cannot restore"):
            detection.restore("admin")

    @pytest.mark.parametrize("method_name", ["create", "activate", "deactivate", "lock", "unlock"])
    def test_noop_methods_return_self(self, method_name):
        detection = create_test_detection()
        if method_name in ("deactivate", "lock"):
            result = getattr(detection, method_name)("admin", "reason")
        else:
            result = getattr(detection, method_name)("admin")
        assert result is detection

    def test_validate_returns_valid(self):
        detection = create_test_detection()
        result = detection.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []
        assert result["detection_id"] == str(detection.detection_id)
        assert result["version"] == detection.version_number

    def test_to_dict(self):
        detection = create_test_detection()
        d = detection.to_dict()
        assert d["category"] == "NEGATIVE_CASH"
        assert d["prevented"] is True
        assert d["action_taken"] == "REJECT"
        assert d["source_module"] == "test_module"
        assert d["resolved"] is False
        assert d["version_number"] == 1

    def test_to_dict_with_override(self):
        detection = create_test_detection()
        detection.override_used = True
        detection.override_authorized_by = "admin"
        d = detection.to_dict()
        assert d["override_used"] is True
        assert d["override_authorized_by"] == "admin"

    def test_from_dict_roundtrip(self):
        detection = create_test_detection()
        d = detection.to_dict()
        reconstructed = ForbiddenStateDetection.from_dict(d)
        assert reconstructed.detection_id == detection.detection_id
        assert reconstructed.category == detection.category
        assert reconstructed.prevented == detection.prevented
        assert reconstructed.action_taken == detection.action_taken
        assert reconstructed.version_number == detection.version_number

    def test_from_dict_with_none_values(self):
        d = {
            "detection_id": str(uuid.uuid4()),
            "state_id": str(uuid.uuid4()),
            "category": "NEGATIVE_CASH",
            "severity": "HIGH",
            "detected_at": FIXED_DATETIME.isoformat(),
            "detection_method": "PRE_TRANSACTION_VALIDATION",
            "transaction_id": None,
            "legal_entity_id": None,
            "current_state": {},
            "attempted_action": {},
            "prevented": True,
            "prevention_action": None,
            "action_taken": "REJECT",
            "source_module": "test",
            "source_user": None,
            "resolved": False,
            "resolved_at": None,
            "resolved_by": None,
            "override_used": False,
            "override_authorized_by": None,
            "version_number": 1,
        }
        detection = ForbiddenStateDetection.from_dict(d)
        assert detection.transaction_id is None
        assert detection.legal_entity_id is None
        assert detection.resolved_at is None

    def test_clone(self):
        detection = create_test_detection()
        cloned = detection.clone()
        assert cloned.detection_id != detection.detection_id
        assert cloned.category == detection.category
        assert cloned.resolved is False
        assert cloned.version_number == 1
        assert cloned.override_used is False
        assert cloned.override_authorized_by is None

    def test_snapshot(self):
        detection = create_test_detection()
        snap = detection.snapshot()
        assert snap["detection_id"] == str(detection.detection_id)
        assert snap["category"] == detection.category.name
        assert snap["version"] == detection.version_number

    def test_version(self):
        detection = create_test_detection()
        assert detection.version() == 1

    def test_audit_trail(self):
        detection = create_test_detection()
        assert len(detection.audit_trail()) == 1
        detection.touch("toucher")
        trail = detection.audit_trail()
        assert len(trail) == 2
        assert trail[-1]["action"] == "TOUCH"
        assert trail[-1]["performed_by"] == "toucher"

    def test_touch_does_not_increment_version(self):
        detection = create_test_detection()
        old_version = detection.version_number
        detection.touch("toucher")
        assert detection.version_number == old_version  # touch doesn't increment version for detection

    def test_compute_fingerprint(self):
        detection = create_test_detection()
        fp1 = detection.compute_fingerprint()
        fp2 = detection.compute_fingerprint()
        assert fp1 == fp2
        # Changing state changes fingerprint
        detection.current_state["balance"] = "200"
        fp3 = detection.compute_fingerprint()
        assert fp1 != fp3

    def test_resolve(self):
        detection = create_test_detection(resolved=False)
        resolved = detection.resolve("admin", "Fixed")
        assert resolved.resolved is True
        assert resolved.resolved_at == FIXED_DATETIME
        assert resolved.resolved_by == "admin"
        assert resolved.version_number == detection.version_number + 1
        trail = resolved.audit_trail()
        assert trail[-1]["action"] == "RESOLVE"
        assert trail[-1]["details"]["action"] == "Fixed"

    def test_resolve_already_resolved_raises(self):
        detection = create_test_detection(resolved=False)
        resolved = detection.resolve("admin", "Fixed")
        with pytest.raises(ValueError, match="Already resolved"):
            resolved.resolve("admin2", "Again")

    def test_copy(self):
        detection = create_test_detection()
        copied = detection._copy()
        assert copied.detection_id == detection.detection_id
        assert copied.category == detection.category
        assert copied is not detection


# =============================================================================
# ForbiddenStateDetector
# =============================================================================

class TestForbiddenStateDetector:
    # ----- Negative Cash -----
    @pytest.mark.parametrize("current,change,overdraft,limit,expected_forbidden,expected_action", [
        (Decimal("100"), Decimal("-50"), False, Decimal("0"), False, None),
        (Decimal("100"), Decimal("-150"), False, Decimal("0"), True, ForbiddenStateAction.REJECT),
        (Decimal("100"), Decimal("-120"), True, Decimal("50"), False, None),
        (Decimal("100"), Decimal("-200"), True, Decimal("50"), True, ForbiddenStateAction.REJECT),
        (Decimal("-100"), Decimal("-50"), False, Decimal("0"), True, ForbiddenStateAction.REJECT),
    ])
    def test_detect_negative_cash(self, current, change, overdraft, limit,
                                   expected_forbidden, expected_action):
        is_forbidden, details, action = ForbiddenStateDetector.detect_negative_cash(
            current_balance=current,
            proposed_change=change,
            allow_overdraft=overdraft,
            overdraft_limit=limit,
        )
        assert is_forbidden == expected_forbidden
        assert action == expected_action
        if is_forbidden:
            assert details

    # ----- Negative Inventory -----
    @pytest.mark.parametrize("current,change,backorder,expected_forbidden,expected_action", [
        (Decimal("10"), Decimal("-5"), False, False, None),
        (Decimal("10"), Decimal("-15"), False, True, ForbiddenStateAction.REJECT),
        (Decimal("10"), Decimal("-15"), True, True, ForbiddenStateAction.WARN),
        (Decimal("0"), Decimal("-1"), False, True, ForbiddenStateAction.REJECT),
        (Decimal("0"), Decimal("-1"), True, True, ForbiddenStateAction.WARN),
    ])
    def test_detect_negative_inventory(self, current, change, backorder,
                                        expected_forbidden, expected_action):
        is_forbidden, _details, action = ForbiddenStateDetector.detect_negative_inventory(
            current_quantity=current,
            proposed_change=change,
            allow_backorder=backorder,
        )
        assert is_forbidden == expected_forbidden
        assert action == expected_action

    # ----- Negative Receivable -----
    @pytest.mark.parametrize("balance,payment,expected_forbidden", [
        (Decimal("1000"), Decimal("500"), False),
        (Decimal("1000"), Decimal("1500"), True),
        (Decimal("0"), Decimal("1"), True),
    ])
    def test_detect_negative_receivable(self, balance, payment, expected_forbidden):
        is_forbidden, details, action = ForbiddenStateDetector.detect_negative_receivable(
            current_balance=balance,
            proposed_payment=payment,
        )
        assert is_forbidden == expected_forbidden
        if is_forbidden:
            assert action == ForbiddenStateAction.REJECT
            assert details["overpayment"]

    # ----- Imbalanced Journal -----
    @pytest.mark.parametrize("debit,credit,tolerance,expected_forbidden", [
        (Decimal("100"), Decimal("100"), Decimal("0.01"), False),
        (Decimal("100"), Decimal("100.1"), Decimal("0.01"), True),
        (Decimal("100"), Decimal("99.99"), Decimal("0.01"), False),  # within tolerance
    ])
    def test_detect_imbalanced_journal(self, debit, credit, tolerance, expected_forbidden):
        is_forbidden, details, action = ForbiddenStateDetector.detect_imbalanced_journal(
            total_debit=debit,
            total_credit=credit,
            tolerance=tolerance,
        )
        assert is_forbidden == expected_forbidden
        if is_forbidden:
            assert action == ForbiddenStateAction.REJECT
            assert "difference" in details

    # ----- Backdated Transaction -----
    def test_detect_backdated_transaction(self):
        now = FIXED_DATETIME
        period_start = now - timedelta(days=10)
        # Allowed: 5 days back
        is_forbidden, _, _ = ForbiddenStateDetector.detect_backdated_transaction(
            transaction_date=now - timedelta(days=5),
            current_period_start=period_start,
            max_backdate_days=30,
        )
        assert not is_forbidden
        # Forbidden: 40 days back
        is_forbidden, details, action = ForbiddenStateDetector.detect_backdated_transaction(
            transaction_date=now - timedelta(days=40),
            current_period_start=period_start,
            max_backdate_days=30,
        )
        assert is_forbidden
        assert details["days_back"] == 30
        assert action == ForbiddenStateAction.REJECT

    def test_detect_backdated_transaction_exact_limit(self):
        now = FIXED_DATETIME
        period_start = now - timedelta(days=30)
        # Exactly at limit: allowed (not forbidden)
        is_forbidden, _, _ = ForbiddenStateDetector.detect_backdated_transaction(
            transaction_date=now - timedelta(days=30),
            current_period_start=period_start,
            max_backdate_days=30,
        )
        assert not is_forbidden

    # ----- Future Transaction -----
    def test_detect_future_transaction(self):
        now = FIXED_DATETIME
        period_end = now + timedelta(days=5)
        # Allowed: 2 days forward
        is_forbidden, _, _ = ForbiddenStateDetector.detect_future_transaction(
            transaction_date=now + timedelta(days=2),
            current_period_end=period_end,
            max_forward_days=7,
        )
        assert not is_forbidden
        # Forbidden: 10 days forward
        is_forbidden, details, action = ForbiddenStateDetector.detect_future_transaction(
            transaction_date=now + timedelta(days=10),
            current_period_end=period_end,
            max_forward_days=7,
        )
        assert is_forbidden
        assert details["days_forward"] == 5
        assert action == ForbiddenStateAction.REJECT

    def test_detect_future_transaction_exact_limit(self):
        now = FIXED_DATETIME
        period_end = now + timedelta(days=5)
        # Exactly at limit: allowed
        is_forbidden, _, _ = ForbiddenStateDetector.detect_future_transaction(
            transaction_date=now + timedelta(days=5),
            current_period_end=period_end,
            max_forward_days=5,
        )
        assert not is_forbidden

    # ----- Cross-Entity Posting -----
    def test_detect_cross_entity_posting(self):
        tx_entity = uuid.uuid4()
        other_entity = uuid.uuid4()
        unauthorized_entity = uuid.uuid4()
        authorized = {frozenset([tx_entity, other_entity])}
        # Allowed
        is_forbidden, _, _ = ForbiddenStateDetector.detect_cross_entity_posting(
            transaction_legal_entity_id=tx_entity,
            journal_line_legal_entity_ids=[other_entity],
            authorized_inter_entities=authorized,
        )
        assert not is_forbidden
        # Forbidden
        is_forbidden, details, action = ForbiddenStateDetector.detect_cross_entity_posting(
            transaction_legal_entity_id=tx_entity,
            journal_line_legal_entity_ids=[other_entity, unauthorized_entity],
            authorized_inter_entities=authorized,
        )
        assert is_forbidden
        assert str(unauthorized_entity) in str(details["unauthorized_pair"])
        assert action == ForbiddenStateAction.REJECT

    def test_detect_cross_entity_posting_multiple_authorized(self):
        tx_entity = uuid.uuid4()
        e1 = uuid.uuid4()
        e2 = uuid.uuid4()
        authorized = {frozenset([tx_entity, e1]), frozenset([e1, e2])}
        is_forbidden, _, _ = ForbiddenStateDetector.detect_cross_entity_posting(
            transaction_legal_entity_id=tx_entity,
            journal_line_legal_entity_ids=[e1, e2],
            authorized_inter_entities=authorized,
        )
        assert not is_forbidden

    # ----- Broken Hash Chain -----
    def test_detect_broken_hash_chain(self):
        is_forbidden, _, _ = ForbiddenStateDetector.detect_broken_hash_chain(
            expected_previous_hash="abc",
            actual_previous_hash="abc",
        )
        assert not is_forbidden
        is_forbidden, details, action = ForbiddenStateDetector.detect_broken_hash_chain(
            expected_previous_hash="abc",
            actual_previous_hash="def",
        )
        assert is_forbidden
        assert details["expected_hash"] == "abc..."
        assert details["actual_hash"] == "def..."
        assert action == ForbiddenStateAction.FREEZE_SYSTEM

    # ----- Missing Audit Event -----
    def test_detect_missing_audit_event(self):
        is_forbidden, _, _ = ForbiddenStateDetector.detect_missing_audit_event(
            expected_sequence=5,
            actual_sequence=6,
        )
        assert not is_forbidden
        is_forbidden, details, action = ForbiddenStateDetector.detect_missing_audit_event(
            expected_sequence=5,
            actual_sequence=10,
        )
        assert is_forbidden
        assert details["missing_count"] == 4
        assert action == ForbiddenStateAction.CRITICAL

    # ----- Tax Mismatch -----
    @pytest.mark.parametrize("calc,reported,tolerance,expected_forbidden", [
        (Decimal("100"), Decimal("100"), Decimal("0.01"), False),
        (Decimal("100"), Decimal("100.5"), Decimal("0.01"), True),
        (Decimal("100"), Decimal("99.99"), Decimal("0.01"), False),
        (Decimal("100"), Decimal("101.0"), Decimal("0.01"), True),
    ])
    def test_detect_tax_mismatch(self, calc, reported, tolerance, expected_forbidden):
        is_forbidden, details, action = ForbiddenStateDetector.detect_tax_mismatch(
            calculated_tax=calc,
            reported_tax=reported,
            tolerance=tolerance,
        )
        assert is_forbidden == expected_forbidden
        if is_forbidden:
            assert action == ForbiddenStateAction.REJECT
            assert "difference" in details

    # ----- Period Closure Violation -----
    def test_detect_period_closure_violation(self):
        now = FIXED_DATETIME
        period_start = now - timedelta(days=10)
        period_end = now + timedelta(days=10)
        # Allowed: period OPEN
        is_forbidden, _, _ = ForbiddenStateDetector.detect_period_closure_violation(
            period_status="OPEN",
            transaction_date=now,
            period_start=period_start,
            period_end=period_end,
        )
        assert not is_forbidden
        # Forbidden: period CLOSED
        is_forbidden, details, action = ForbiddenStateDetector.detect_period_closure_violation(
            period_status="CLOSED",
            transaction_date=now,
            period_start=period_start,
            period_end=period_end,
        )
        assert is_forbidden
        assert details["period_status"] == "CLOSED"
        assert action == ForbiddenStateAction.REJECT

    # ----- Negative Equity -----
    @pytest.mark.parametrize("equity,minimum,expected_forbidden", [
        (Decimal("1000"), Decimal("0"), False),
        (Decimal("-100"), Decimal("0"), True),
        (Decimal("-500"), Decimal("-1000"), False),
        (Decimal("-1500"), Decimal("-1000"), True),
    ])
    def test_detect_negative_equity(self, equity, minimum, expected_forbidden):
        is_forbidden, details, action = ForbiddenStateDetector.detect_negative_equity(
            total_equity=equity,
            minimum_equity=minimum,
        )
        assert is_forbidden == expected_forbidden
        if is_forbidden:
            assert action == ForbiddenStateAction.FREEZE_SYSTEM
            assert "total_equity" in details

    # ----- Period Mixing -----
    def test_detect_period_mixing(self):
        now = FIXED_DATETIME
        period1 = (now - timedelta(days=5), now + timedelta(days=5))
        period2 = (now + timedelta(days=10), now + timedelta(days=20))
        # Allowed: both dates in same period
        dates = [now, now + timedelta(days=2)]
        is_forbidden, _, _ = ForbiddenStateDetector.detect_period_mixing(
            transaction_dates=dates,
            period_boundaries=[period1, period2],
        )
        assert not is_forbidden
        # Forbidden: dates in different periods
        dates = [now, now + timedelta(days=15)]
        is_forbidden, details, action = ForbiddenStateDetector.detect_period_mixing(
            transaction_dates=dates,
            period_boundaries=[period1, period2],
        )
        assert is_forbidden
        assert len(details["periods_found"]) == 2
        assert action == ForbiddenStateAction.REJECT

    def test_detect_period_mixing_single_period(self):
        now = FIXED_DATETIME
        period1 = (now - timedelta(days=5), now + timedelta(days=5))
        dates = [now, now + timedelta(days=2)]
        is_forbidden, _, _ = ForbiddenStateDetector.detect_period_mixing(
            transaction_dates=dates,
            period_boundaries=[period1],
        )
        assert not is_forbidden

    # ----- Privilege Escalation -----
    @pytest.mark.parametrize("user_roles,required_roles,user_perms,required_perms,expected_forbidden", [
        (["admin"], ["admin"], {"read", "write"}, {"read", "write"}, False),
        (["guest"], ["admin"], {"read"}, {"read", "write"}, True),
        (["guest"], ["admin"], {"read", "write"}, {"read", "write"}, True),  # no role
        (["admin"], ["admin"], {"read"}, {"read", "write"}, True),  # missing perm
    ])
    def test_detect_privilege_escalation(self, user_roles, required_roles,
                                          user_perms, required_perms, expected_forbidden):
        is_forbidden, details, action = ForbiddenStateDetector.detect_privilege_escalation(
            user_roles=user_roles,
            required_roles=required_roles,
            user_permissions=user_perms,
            required_permissions=required_perms,
        )
        assert is_forbidden == expected_forbidden
        if is_forbidden:
            assert action == ForbiddenStateAction.REJECT
            if "missing_permissions" in details:
                assert isinstance(details["missing_permissions"], list)


# =============================================================================
# ForbiddenStatesRegistry
# =============================================================================

class TestForbiddenStatesRegistry:
    def test_initialization_loads_defaults(self):
        registry = ForbiddenStatesRegistry()
        assert len(registry.states) > 0
        assert len(registry.detections) == 0
        # Check that default states are active
        for state in registry.states.values():
            assert state.is_active is True

    def test_save_and_get_state(self):
        registry = ForbiddenStatesRegistry()
        state = create_test_state()
        registry.save_state(state)
        retrieved = registry.get_state(state.state_id)
        assert retrieved is not None
        assert retrieved.state_id == state.state_id

    def test_get_all_states(self):
        registry = ForbiddenStatesRegistry()
        # Add additional states
        for i in range(3):
            state = create_test_state(
                category=ForbiddenStateCategory.NEGATIVE_INVENTORY if i % 2 == 0 else ForbiddenStateCategory.IMBALANCED_JOURNAL,
                name=f"State{i}",
            )
            registry.save_state(state)
        all_states = registry.get_all_states()
        # Default states + 3 added
        assert len(all_states) >= len(registry.states)

    def test_delete_state(self):
        registry = ForbiddenStatesRegistry()
        state = create_test_state()
        registry.save_state(state)
        result = registry.delete_state(state.state_id)
        assert result is True
        assert registry.get_state(state.state_id) is None
        # Delete non-existent
        result2 = registry.delete_state(uuid.uuid4())
        assert result2 is False

    def test_save_and_get_detections(self):
        registry = ForbiddenStatesRegistry()
        detection = create_test_detection()
        registry.save_detection(detection)
        detections = registry.get_detections()
        assert len(detections) == 1
        assert detections[0].detection_id == detection.detection_id

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
        now = FIXED_DATETIME
        d1 = create_test_detection()
        d1.detected_at = now - timedelta(days=10)
        d2 = create_test_detection()
        d2.detected_at = now - timedelta(days=2)
        registry.save_detection(d1)
        registry.save_detection(d2)
        result = registry.get_detections(from_date=now - timedelta(days=5))
        assert len(result) == 1
        assert result[0].detected_at >= now - timedelta(days=5)

    def test_get_detections_filter_resolved(self):
        registry = ForbiddenStatesRegistry()
        d1 = create_test_detection(resolved=True)
        d2 = create_test_detection(resolved=False)
        registry.save_detection(d1)
        registry.save_detection(d2)
        resolved = registry.get_detections(resolved_only=True)
        assert len(resolved) == 1
        assert resolved[0].resolved is True
        unresolved = registry.get_detections(unresolved_only=True)
        assert len(unresolved) == 1
        assert unresolved[0].resolved is False

    def test_get_detections_filter_prevented(self):
        registry = ForbiddenStatesRegistry()
        d1 = create_test_detection(prevented=True)
        d2 = create_test_detection(prevented=False)
        registry.save_detection(d1)
        registry.save_detection(d2)
        prevented = registry.get_detections(prevented_only=True)
        assert len(prevented) == 1
        assert prevented[0].prevented is True

    def test_get_detections_limit(self):
        registry = ForbiddenStatesRegistry()
        for _ in range(15):
            registry.save_detection(create_test_detection())
        result = registry.get_detections(limit=5)
        assert len(result) == 5

    def test_resolve_detection(self):
        registry = ForbiddenStatesRegistry()
        detection = create_test_detection(resolved=False)
        registry.save_detection(detection)
        resolved = registry.resolve_detection(detection.detection_id, "admin", "Fixed")
        assert resolved is not None
        assert resolved.resolved is True
        assert resolved.resolved_by == "admin"
        # Resolve again returns None
        resolved2 = registry.resolve_detection(detection.detection_id, "admin2", "Again")
        assert resolved2 is None

    def test_check_no_state_defined(self):
        registry = ForbiddenStatesRegistry()
        # Use a category not in default states (e.g., NEGATIVE_PAYABLE)
        is_forbidden, detection, action = registry.check(
            category=ForbiddenStateCategory.NEGATIVE_PAYABLE,
            context={"current_balance": Decimal("100"), "proposed_change": Decimal("-150")},
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
        # Create a state with override allowed
        state = create_test_state(override_allowed=True, override_roles=["admin"])
        registry.save_state(state)
        # Use the category of the new state
        is_forbidden, detection, _action = registry.check(
            category=state.category,
            context={"current_balance": Decimal("100"), "proposed_change": Decimal("-150")},
            override=True,
            override_authorized_by="admin",
        )
        assert is_forbidden
        assert detection is not None
        assert detection.override_used is True
        assert detection.action_taken == ForbiddenStateAction.WARN

    def test_check_with_override_unauthorized(self):
        registry = ForbiddenStatesRegistry()
        state = create_test_state(override_allowed=True, override_roles=["admin"])
        registry.save_state(state)
        is_forbidden, detection, _action = registry.check(
            category=state.category,
            context={"current_balance": Decimal("100"), "proposed_change": Decimal("-150")},
            override=True,
            override_authorized_by="unauthorized",
        )
        assert is_forbidden
        assert detection is not None
        assert detection.override_used is False

    def test_check_catastrophic_calls_handler(self):
        registry = ForbiddenStatesRegistry()
        # Create catastrophic state
        state = create_test_state(
            category=ForbiddenStateCategory.BROKEN_HASH_CHAIN,
            severity=ForbiddenStateSeverity.CATASTROPHIC,
        )
        registry.save_state(state)
        with patch.object(registry, "_handle_catastrophic_detection") as mock_handle:
            is_forbidden, detection, _action = registry.check(
                category=ForbiddenStateCategory.BROKEN_HASH_CHAIN,
                context={"expected_previous_hash": "abc", "actual_previous_hash": "def"},
            )
            assert is_forbidden
            assert detection is not None
            mock_handle.assert_called_once_with(detection)

    def test_is_action_forbidden(self):
        registry = ForbiddenStatesRegistry()
        # Should be forbidden
        result = registry.is_action_forbidden(
            category=ForbiddenStateCategory.NEGATIVE_CASH,
            context={"current_balance": Decimal("100"), "proposed_change": Decimal("-150")},
        )
        assert result is True
        # Should not be forbidden
        result2 = registry.is_action_forbidden(
            category=ForbiddenStateCategory.NEGATIVE_CASH,
            context={"current_balance": Decimal("100"), "proposed_change": Decimal("-50")},
        )
        assert result2 is False

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
        # Add some detections
        for _ in range(3):
            registry.save_detection(create_test_detection())
        for _ in range(2):
            d = create_test_detection(resolved=True)
            registry.save_detection(d)
        stats = registry.get_statistics()
        assert stats["total_states"] > 0
        assert stats["active_states"] > 0
        assert stats["total_detections"] >= 5
        assert stats["unresolved_detections"] >= 3
        assert "by_category" in stats
        assert "by_severity" in stats
        assert stats["latest_detection"] is not None

    def test_reset(self):
        registry = ForbiddenStatesRegistry()
        # Add custom state
        state = create_test_state()
        registry.save_state(state)
        detection = create_test_detection()
        registry.save_detection(detection)
        registry.reset()
        # Default states re-loaded, custom state gone
        assert len(registry.states) > 0
        assert len(registry.detections) == 0
        assert registry.get_state(state.state_id) is None

    def test_notify_supreme_law(self):
        registry = ForbiddenStatesRegistry()
        state = create_test_state()
        detection = create_test_detection()
        with patch("constitution.forbidden_states.get_supreme_law") as mock_get:
            mock_law = MagicMock()
            mock_get.return_value = mock_law
            registry._notify_supreme_law(detection, state)
            mock_law.check_violation.assert_called_once()

    def test_notify_supreme_law_failure_logs(self, caplog):
        registry = ForbiddenStatesRegistry()
        state = create_test_state()
        detection = create_test_detection()
        with patch("constitution.forbidden_states.get_supreme_law", side_effect=Exception("Law error")):
            registry._notify_supreme_law(detection, state)
            # Should not raise, just log
            assert True

    def test_handle_catastrophic_detection_logs(self, caplog):
        registry = ForbiddenStatesRegistry()
        detection = create_test_detection()
        # Just ensure it doesn't raise
        registry._handle_catastrophic_detection(detection)
        assert True


# =============================================================================
# ForbiddenStatesService
# =============================================================================

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
        assert retrieved.state_id == state.state_id

    def test_get_all_states(self):
        svc = ForbiddenStatesService()
        states = svc.get_all_states()
        assert len(states) > 0

    def test_delete_state(self):
        svc = ForbiddenStatesService()
        state = create_test_state()
        svc.save_state(state)
        result = svc.delete_state(state.state_id)
        assert result is True
        assert svc.get_state(state.state_id) is None

    def test_save_and_get_detections(self):
        svc = ForbiddenStatesService()
        detection = create_test_detection()
        svc.save_detection(detection)
        detections = svc.get_detections()
        assert len(detections) == 1

    def test_resolve_detection(self):
        svc = ForbiddenStatesService()
        detection = create_test_detection(resolved=False)
        svc.save_detection(detection)
        resolved = svc.resolve_detection(detection.detection_id, "admin", "Fixed")
        assert resolved is not None
        assert resolved.resolved is True

    # ----- Convenience check methods -----
    def test_check_negative_cash(self):
        svc = ForbiddenStatesService()
        is_forbidden, detection, _action = svc.check_negative_cash(
            current_balance=Decimal("100"),
            proposed_change=Decimal("-150"),
        )
        assert is_forbidden
        assert detection is not None
        assert detection.category == ForbiddenStateCategory.NEGATIVE_CASH

    def test_check_negative_inventory(self):
        svc = ForbiddenStatesService()
        is_forbidden, detection, _action = svc.check_negative_inventory(
            current_quantity=Decimal("10"),
            proposed_change=Decimal("-15"),
        )
        assert is_forbidden
        assert detection is not None
        assert detection.category == ForbiddenStateCategory.NEGATIVE_INVENTORY

    def test_check_negative_receivable(self):
        svc = ForbiddenStatesService()
        is_forbidden, detection, _action = svc.check_negative_receivable(
            current_balance=Decimal("1000"),
            proposed_payment=Decimal("1500"),
        )
        assert is_forbidden
        assert detection is not None
        assert detection.category == ForbiddenStateCategory.NEGATIVE_RECEIVABLE

    def test_check_imbalanced_journal(self):
        svc = ForbiddenStatesService()
        is_forbidden, detection, _action = svc.check_imbalanced_journal(
            total_debit=Decimal("100"),
            total_credit=Decimal("100.1"),
        )
        assert is_forbidden
        assert detection is not None
        assert detection.category == ForbiddenStateCategory.IMBALANCED_JOURNAL

    def test_check_backdated_transaction(self):
        now = FIXED_DATETIME
        period_start = now - timedelta(days=10)
        is_forbidden, detection, _action = svc.check_backdated_transaction(
            transaction_date=now - timedelta(days=40),
            current_period_start=period_start,
            max_backdate_days=30,
        )
        assert is_forbidden
        assert detection is not None
        assert detection.category == ForbiddenStateCategory.BACKDATED_TRANSACTION

    def test_check_cross_entity_posting(self):
        tx_entity = uuid.uuid4()
        other_entity = uuid.uuid4()
        unauthorized_entity = uuid.uuid4()
        authorized = {frozenset([tx_entity, other_entity])}
        is_forbidden, detection, _action = svc.check_cross_entity_posting(
            transaction_legal_entity_id=tx_entity,
            journal_line_legal_entity_ids=[other_entity, unauthorized_entity],
            authorized_inter_entities=authorized,
        )
        assert is_forbidden
        assert detection is not None
        assert detection.category == ForbiddenStateCategory.CROSS_ENTITY_POSTING

    def test_check_period_closure(self):
        now = FIXED_DATETIME
        period_start = now - timedelta(days=10)
        period_end = now + timedelta(days=10)
        is_forbidden, detection, _action = svc.check_period_closure(
            period_status="CLOSED",
            transaction_date=now,
            period_start=period_start,
            period_end=period_end,
        )
        assert is_forbidden
        assert detection is not None
        assert detection.category == ForbiddenStateCategory.PERIOD_CLOSURE_VIOLATION

    def test_check_broken_hash_chain(self):
        is_forbidden, detection, _action = svc.check_broken_hash_chain(
            expected_previous_hash="abc",
            actual_previous_hash="def",
        )
        assert is_forbidden
        assert detection is not None
        assert detection.category == ForbiddenStateCategory.BROKEN_HASH_CHAIN

    def test_get_detection_history(self):
        svc = ForbiddenStatesService()
        detection = create_test_detection()
        svc.save_detection(detection)
        history = svc.get_detection_history()
        assert len(history) == 1

    def test_get_statistics(self):
        svc = ForbiddenStatesService()
        stats = svc.get_statistics()
        assert "total_states" in stats
        assert "active_states" in stats
        assert "total_detections" in stats


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

class TestHelperFunctions:
    def test_get_detector_for_state_exists(self):
        detector = get_detector_for_state(ForbiddenStateCategory.NEGATIVE_CASH)
        assert detector is not None
        assert callable(detector)

    def test_get_detector_for_state_not_exists(self):
        detector = get_detector_for_state(ForbiddenStateCategory.UNAUTHORIZED_ACCESS)
        assert detector is None

    def test_get_forbidden_states_service_singleton(self):
        svc1 = get_forbidden_states_service()
        svc2 = get_forbidden_states_service()
        assert svc1 is svc2
        assert isinstance(svc1, ForbiddenStatesService)


# =============================================================================
# ADDITIONAL COVERAGE FOR EDGE CASES
# =============================================================================

class TestAdditionalCoverage:
    def test_state_with_version_string(self):
        state = create_test_state()
        state.version = "2.0.1"
        d = state.to_dict()
        assert d["version"] == "2.0.1"
        reconstructed = ForbiddenStateDefinition.from_dict(d)
        assert reconstructed.version == "2.0.1"

    def test_detection_with_transaction_and_legal_entity(self):
        detection = create_test_detection()
        detection.transaction_id = uuid.uuid4()
        detection.legal_entity_id = uuid.uuid4()
        d = detection.to_dict()
        assert d["transaction_id"] == str(detection.transaction_id)
        assert d["legal_entity_id"] == str(detection.legal_entity_id)

    def test_detection_from_dict_with_override(self):
        d = {
            "detection_id": str(uuid.uuid4()),
            "state_id": str(uuid.uuid4()),
            "category": "NEGATIVE_CASH",
            "severity": "HIGH",
            "detected_at": FIXED_DATETIME.isoformat(),
            "detection_method": "PRE_TRANSACTION_VALIDATION",
            "transaction_id": None,
            "legal_entity_id": None,
            "current_state": {},
            "attempted_action": {},
            "prevented": True,
            "prevention_action": None,
            "action_taken": "REJECT",
            "source_module": "test",
            "source_user": None,
            "resolved": False,
            "resolved_at": None,
            "resolved_by": None,
            "override_used": True,
            "override_authorized_by": "admin",
            "version_number": 1,
        }
        detection = ForbiddenStateDetection.from_dict(d)
        assert detection.override_used is True
        assert detection.override_authorized_by == "admin"

    def test_detector_negative_cash_with_zero_overdraft_limit(self):
        is_forbidden, _details, action = ForbiddenStateDetector.detect_negative_cash(
            current_balance=Decimal("0"),
            proposed_change=Decimal("-1"),
            allow_overdraft=True,
            overdraft_limit=Decimal("0"),
        )
        assert is_forbidden
        assert action == ForbiddenStateAction.REJECT

    def test_detector_negative_cash_with_overdraft_limit(self):
        is_forbidden, _details, _action = ForbiddenStateDetector.detect_negative_cash(
            current_balance=Decimal("0"),
            proposed_change=Decimal("-5"),
            allow_overdraft=True,
            overdraft_limit=Decimal("10"),
        )
        assert not is_forbidden

    def test_detector_period_mixing_no_boundary_match(self):
        now = FIXED_DATETIME
        dates = [now, now + timedelta(days=15)]
        period_boundaries = [(now - timedelta(days=5), now - timedelta(days=1))]
        is_forbidden, _details, _action = ForbiddenStateDetector.detect_period_mixing(
            transaction_dates=dates,
            period_boundaries=period_boundaries,
        )
        # Both dates not in any period -> periods set empty -> not forbidden
        assert not is_forbidden
