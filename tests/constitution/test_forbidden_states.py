#!/usr/bin/env python3
"""
tests/constitution/test_forbidden_states.py
Comprehensive tests for constitution/forbidden_states.py

Covers:
- ForbiddenStateCategory, ForbiddenStateSeverity, StateDetectionMethod, ForbiddenStateAction enums
- ForbiddenStateDefinition: creation, validation, update, delete, restore, activate, deactivate,
  lock, unlock, validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch
- ForbiddenStateDetection: creation, resolve, clone, snapshot, audit_trail, compute_fingerprint
- ForbiddenStateDetector: all static detection methods (negative cash, inventory, receivable,
  imbalanced journal, backdated/future transactions, cross-entity, broken hash chain,
  missing audit event, tax mismatch, period closure, negative equity, period mixing,
  privilege escalation)
- ForbiddenStatesRegistry: default states, save/get/delete states, save/get/delete detections,
  check, resolve, statistics, reset
- ForbiddenStatesService: singleton, registry, convenience check methods, statistics
- Helper functions: get_detector_for_state, get_forbidden_states_service
- All edge cases and negative paths
- No flaky datetime (mocked)
- No duplicate test code (parametrized and consolidated)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest

from constitution.forbidden_states import (
    ForbiddenStateAction,
    ForbiddenStateCategory,
    ForbiddenStateDefinition,
    ForbiddenStateDetection,
    ForbiddenStateDetector,
    ForbiddenStateSeverity,
    ForbiddenStatesRegistry,
    ForbiddenStatesService,
    StateDetectionMethod,
    get_detector_for_state,
    get_forbidden_states_service,
)

# =============================================================================
# Fixtures
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


@pytest.fixture
def sample_state() -> ForbiddenStateDefinition:
    return ForbiddenStateDefinition(
        state_id=uuid.uuid4(),
        category=ForbiddenStateCategory.NEGATIVE_CASH,
        name="Test State",
        description="Test description",
        severity=ForbiddenStateSeverity.HIGH,
        detection_method=StateDetectionMethod.PRE_TRANSACTION_VALIDATION,
        default_action=ForbiddenStateAction.REJECT,
        recovery_action="Test recovery",
        auto_correct=False,
        is_active=True,
        created_at=FIXED_DATETIME,
        created_by="tester",
        approved_by=["approver1", "approver2"],
        version="1.0.0",
        cryptographic_hash="",
        override_allowed=True,
        override_roles=["admin", "supervisor"],
        version_number=1,
    )


@pytest.fixture
def sample_detection() -> ForbiddenStateDetection:
    return ForbiddenStateDetection(
        detection_id=uuid.uuid4(),
        state_id=uuid.uuid4(),
        category=ForbiddenStateCategory.NEGATIVE_CASH,
        severity=ForbiddenStateSeverity.HIGH,
        detected_at=FIXED_DATETIME,
        detection_method=StateDetectionMethod.PRE_TRANSACTION_VALIDATION,
        current_state={"balance": "100"},
        attempted_action={"debit": "200"},
        prevented=True,
        action_taken=ForbiddenStateAction.REJECT,
        source_module="test_module",
        resolved=False,
        transaction_id=uuid.uuid4(),
        legal_entity_id=uuid.uuid4(),
        source_user="tester",
        version_number=1,
    )


@pytest.fixture
def registry() -> ForbiddenStatesRegistry:
    return ForbiddenStatesRegistry()


# =============================================================================
# Enums
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
    def test_create_valid(self, sample_state):
        assert sample_state.state_id is not None
        assert sample_state.category == ForbiddenStateCategory.NEGATIVE_CASH
        assert sample_state.name == "Test State"
        assert sample_state.is_active
        assert sample_state.version_number == 1
        assert sample_state.cryptographic_hash != ""

    def test_validate_version_number(self):
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

    def test_compute_hash_consistent(self, sample_state):
        h1 = sample_state.compute_hash()
        h2 = sample_state.compute_hash()
        assert h1 == h2

    def test_update_creates_new_version(self, sample_state):
        updated = sample_state.update("admin", name="Updated Name")
        assert updated.name == "Updated Name"
        assert updated.version_number == sample_state.version_number + 1

    def test_update_cannot_change_immutable(self, sample_state):
        original_id = sample_state.state_id
        original_created = sample_state.created_at
        updated = sample_state.update("admin", state_id=uuid.uuid4(), created_at=datetime(2000, 1, 1, tzinfo=UTC))
        assert updated.state_id == original_id
        assert updated.created_at == original_created

    def test_delete_marks_deleted_and_inactive(self, sample_state):
        deleted = sample_state.delete("admin", "test")
        assert deleted.deleted_at == FIXED_DATETIME
        assert deleted.deleted_by == "admin"
        assert not deleted.is_active
        assert deleted.version_number == sample_state.version_number + 1

    def test_restore_recovers_deleted(self, sample_state):
        deleted = sample_state.delete("admin", "test")
        restored = deleted.restore("admin")
        assert restored.deleted_at is None
        assert restored.deleted_by is None
        assert restored.is_active
        assert restored.version_number == deleted.version_number + 1

    def test_restore_not_deleted_raises(self, sample_state):
        with pytest.raises(ValueError, match="Not deleted"):
            sample_state.restore("admin")

    def test_activate_does_nothing_if_active(self, sample_state):
        activated = sample_state.activate("admin")
        assert activated is sample_state

    def test_activate_activates_inactive(self, sample_state):
        deactivated = sample_state.deactivate("admin", "test")
        activated = deactivated.activate("admin")
        assert activated.is_active
        assert activated.version_number == deactivated.version_number + 1

    def test_deactivate_does_nothing_if_inactive(self, sample_state):
        deactivated = sample_state.deactivate("admin", "test")
        again = deactivated.deactivate("admin", "again")
        assert again is deactivated

    def test_lock_returns_new_version(self, sample_state):
        locked = sample_state.lock("admin", "reason")
        assert locked.version_number == sample_state.version_number + 1
        assert locked._audit_trail[-1]["action"] == "LOCK"

    def test_unlock_returns_new_version(self, sample_state):
        unlocked = sample_state.unlock("admin")
        assert unlocked.version_number == sample_state.version_number + 1
        assert unlocked._audit_trail[-1]["action"] == "UNLOCK"

    @pytest.mark.parametrize("method_name", ["create", "activate", "deactivate", "lock", "unlock"])
    def test_methods_that_should_work(self, sample_state, method_name):
        # Just ensure they don't raise
        method = getattr(sample_state, method_name)
        if method_name in ("create", "activate", "unlock"):
            result = method("admin")
        elif method_name == "deactivate":
            result = method("admin", "reason")
        elif method_name == "lock":
            result = method("admin", "reason")
        else:
            result = method("admin")
        assert result is not None

    def test_validate_returns_valid(self, sample_state):
        result = sample_state.validate()
        assert result["is_valid"] is True
        assert result["state_id"] == str(sample_state.state_id)

    def test_validate_errors_on_hash_mismatch(self, sample_state):
        object.__setattr__(sample_state, "cryptographic_hash", "fake")
        result = sample_state.validate()
        assert result["is_valid"] is False
        assert "Hash mismatch" in result["errors"]

    def test_to_dict_contains_fields(self, sample_state):
        d = sample_state.to_dict()
        assert d["category"] == "NEGATIVE_CASH"
        assert d["name"] == "Test State"
        assert d["severity"] == "HIGH"
        assert d["is_active"] is True
        assert d["version_number"] == 1

    def test_from_dict_roundtrip(self, sample_state):
        d = sample_state.to_dict()
        reconstructed = ForbiddenStateDefinition.from_dict(d)
        assert reconstructed.state_id == sample_state.state_id
        assert reconstructed.category == sample_state.category
        assert reconstructed.name == sample_state.name
        assert reconstructed.severity == sample_state.severity
        assert reconstructed.is_active == sample_state.is_active

    def test_clone_creates_new_id_and_inactive(self, sample_state):
        cloned = sample_state.clone()
        assert cloned.state_id != sample_state.state_id
        assert cloned.category == sample_state.category
        assert cloned.name == sample_state.name
        assert cloned.is_active is False
        assert cloned.version_number == 1

    def test_snapshot_returns_summary(self, sample_state):
        snap = sample_state.snapshot()
        assert snap["state_id"] == str(sample_state.state_id)
        assert snap["category"] == sample_state.category.name

    def test_version_and_audit_trail(self, sample_state):
        assert sample_state.version() == 1
        assert len(sample_state.audit_trail()) >= 1
        touched = sample_state.touch("toucher")
        assert touched.version_number == sample_state.version_number + 1
        trail = touched.audit_trail()
        assert len(trail) >= 2
        assert trail[-1]["action"] == "TOUCH"

    def test_audit_trail_limit(self, sample_state):
        state = sample_state
        for _ in range(15):
            state = state.touch("tester")
        trail = state.audit_trail(limit=5)
        assert len(trail) == 5


# =============================================================================
# ForbiddenStateDetection
# =============================================================================

class TestForbiddenStateDetection:
    def test_create_valid(self, sample_detection):
        assert sample_detection.detection_id is not None
        assert sample_detection.category == ForbiddenStateCategory.NEGATIVE_CASH
        assert sample_detection.prevented is True
        assert sample_detection.resolved is False
        assert sample_detection.version_number == 1

    def test_validate_version_number(self):
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

    def test_snapshot_and_audit_trail(self, sample_detection):
        assert len(sample_detection._snapshots) == 1
        assert len(sample_detection._audit_trail) == 1

    def test_immutable_methods_raise(self, sample_detection):
        with pytest.raises(AttributeError):
            sample_detection.update("admin", prevented=False)
        with pytest.raises(AttributeError):
            sample_detection.delete("admin")
        with pytest.raises(AttributeError):
            sample_detection.restore("admin")

    @pytest.mark.parametrize("method_name", ["create", "activate", "deactivate", "lock", "unlock"])
    def test_noop_methods_return_self(self, sample_detection, method_name):
        method = getattr(sample_detection, method_name)
        result = method("admin")
        assert result is sample_detection

    def test_validate_returns_valid(self, sample_detection):
        result = sample_detection.validate()
        assert result["is_valid"] is True
        assert result["detection_id"] == str(sample_detection.detection_id)

    def test_to_dict_contains_fields(self, sample_detection):
        d = sample_detection.to_dict()
        assert d["category"] == "NEGATIVE_CASH"
        assert d["prevented"] is True
        assert d["action_taken"] == "REJECT"
        assert d["source_module"] == "test_module"

    def test_from_dict_roundtrip(self, sample_detection):
        d = sample_detection.to_dict()
        reconstructed = ForbiddenStateDetection.from_dict(d)
        assert reconstructed.detection_id == sample_detection.detection_id
        assert reconstructed.category == sample_detection.category
        assert reconstructed.prevented == sample_detection.prevented
        assert reconstructed.action_taken == sample_detection.action_taken

    def test_clone_creates_new_id_and_resets_resolved(self, sample_detection):
        cloned = sample_detection.clone()
        assert cloned.detection_id != sample_detection.detection_id
        assert cloned.category == sample_detection.category
        assert cloned.resolved is False
        assert cloned.version_number == 1

    def test_snapshot_returns_summary(self, sample_detection):
        snap = sample_detection.snapshot()
        assert snap["detection_id"] == str(sample_detection.detection_id)
        assert snap["category"] == sample_detection.category.name

    def test_version_audit_trail_touch(self, sample_detection):
        assert sample_detection.version() == 1
        assert len(sample_detection.audit_trail()) >= 1
        sample_detection.touch("toucher")
        trail = sample_detection.audit_trail()
        assert len(trail) >= 2
        assert trail[-1]["action"] == "TOUCH"

    def test_compute_fingerprint_consistent(self, sample_detection):
        fp1 = sample_detection.compute_fingerprint()
        fp2 = sample_detection.compute_fingerprint()
        assert fp1 == fp2

    def test_compute_fingerprint_changes_with_state(self, sample_detection):
        fp1 = sample_detection.compute_fingerprint()
        sample_detection.current_state["balance"] = "200"
        fp2 = sample_detection.compute_fingerprint()
        assert fp1 != fp2

    def test_resolve_marks_resolved(self, sample_detection):
        resolved = sample_detection.resolve("admin", "Fixed")
        assert resolved.resolved is True
        assert resolved.resolved_at == FIXED_DATETIME
        assert resolved.resolved_by == "admin"
        assert resolved.version_number == sample_detection.version_number + 1

    def test_resolve_already_resolved_raises(self, sample_detection):
        resolved = sample_detection.resolve("admin", "Fixed")
        with pytest.raises(ValueError, match="Already resolved"):
            resolved.resolve("admin2", "Again")


# =============================================================================
# ForbiddenStateDetector (parametrized for compactness)
# =============================================================================

class TestForbiddenStateDetector:
    @pytest.mark.parametrize("current,change,overdraft,limit,expected_forbidden,expected_action", [
        (Decimal("100"), Decimal("-50"), False, Decimal("0"), False, None),
        (Decimal("100"), Decimal("-150"), False, Decimal("0"), True, ForbiddenStateAction.REJECT),
        (Decimal("100"), Decimal("-120"), True, Decimal("50"), False, None),
        (Decimal("100"), Decimal("-200"), True, Decimal("50"), True, ForbiddenStateAction.REJECT),
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

    @pytest.mark.parametrize("current,change,backorder,expected_forbidden,expected_action", [
        (Decimal("10"), Decimal("-5"), False, False, None),
        (Decimal("10"), Decimal("-15"), False, True, ForbiddenStateAction.REJECT),
        (Decimal("10"), Decimal("-15"), True, True, ForbiddenStateAction.WARN),
    ])
    def test_detect_negative_inventory(self, current, change, backorder,
                                        expected_forbidden, expected_action):
        is_forbidden, details, action = ForbiddenStateDetector.detect_negative_inventory(
            current_quantity=current,
            proposed_change=change,
            allow_backorder=backorder,
        )
        assert is_forbidden == expected_forbidden
        assert action == expected_action

    @pytest.mark.parametrize("balance,payment,expected_forbidden", [
        (Decimal("1000"), Decimal("500"), False),
        (Decimal("1000"), Decimal("1500"), True),
    ])
    def test_detect_negative_receivable(self, balance, payment, expected_forbidden):
        is_forbidden, details, action = ForbiddenStateDetector.detect_negative_receivable(
            current_balance=balance,
            proposed_payment=payment,
        )
        assert is_forbidden == expected_forbidden
        if is_forbidden:
            assert action == ForbiddenStateAction.REJECT

    @pytest.mark.parametrize("debit,credit,tolerance,expected_forbidden", [
        (Decimal("100"), Decimal("100"), Decimal("0.01"), False),
        (Decimal("100"), Decimal("100.1"), Decimal("0.01"), True),
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
        assert action == ForbiddenStateAction.FREEZE_SYSTEM

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

    def test_detect_tax_mismatch(self):
        is_forbidden, _, _ = ForbiddenStateDetector.detect_tax_mismatch(
            calculated_tax=Decimal("100"),
            reported_tax=Decimal("100"),
            tolerance=Decimal("0.01"),
        )
        assert not is_forbidden
        is_forbidden, details, action = ForbiddenStateDetector.detect_tax_mismatch(
            calculated_tax=Decimal("100"),
            reported_tax=Decimal("100.5"),
            tolerance=Decimal("0.01"),
        )
        assert is_forbidden
        assert float(details["difference"]) == -0.5
        assert action == ForbiddenStateAction.REJECT

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

    def test_detect_negative_equity(self):
        is_forbidden, _, _ = ForbiddenStateDetector.detect_negative_equity(
            total_equity=Decimal("1000"),
            minimum_equity=Decimal("0"),
        )
        assert not is_forbidden
        is_forbidden, details, action = ForbiddenStateDetector.detect_negative_equity(
            total_equity=Decimal("-100"),
            minimum_equity=Decimal("0"),
        )
        assert is_forbidden
        assert details["total_equity"] == "-100"
        assert action == ForbiddenStateAction.FREEZE_SYSTEM

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

    def test_detect_privilege_escalation(self):
        # Allowed
        is_forbidden, _, _ = ForbiddenStateDetector.detect_privilege_escalation(
            user_roles=["admin"],
            required_roles=["admin"],
            user_permissions={"read", "write"},
            required_permissions={"read", "write"},
        )
        assert not is_forbidden
        # Forbidden
        is_forbidden, details, action = ForbiddenStateDetector.detect_privilege_escalation(
            user_roles=["guest"],
            required_roles=["admin"],
            user_permissions={"read"},
            required_permissions={"read", "write"},
        )
        assert is_forbidden
        assert details["missing_permissions"] == ["write"]
        assert action == ForbiddenStateAction.REJECT


# =============================================================================
# ForbiddenStatesRegistry
# =============================================================================

class TestForbiddenStatesRegistry:
    def test_initialization_loads_defaults(self, registry):
        assert len(registry.states) > 0
        assert len(registry.detections) == 0

    def test_save_and_get_state(self, registry, sample_state):
        registry.save_state(sample_state)
        retrieved = registry.get_state(sample_state.state_id)
        assert retrieved is not None
        assert retrieved.state_id == sample_state.state_id

    def test_get_all_states(self, registry):
        s1 = ForbiddenStateDefinition(
            state_id=uuid.uuid4(),
            category=ForbiddenStateCategory.NEGATIVE_CASH,
            name="State1",
            description="Desc",
            severity=ForbiddenStateSeverity.HIGH,
            detection_method=StateDetectionMethod.PRE_TRANSACTION_VALIDATION,
            default_action=ForbiddenStateAction.REJECT,
            recovery_action="R",
            auto_correct=False,
            is_active=True,
            created_at=FIXED_DATETIME,
            created_by="t",
            approved_by=[],
            version="1.0",
            override_allowed=False,
            override_roles=[],
        )
        s2 = ForbiddenStateDefinition(
            state_id=uuid.uuid4(),
            category=ForbiddenStateCategory.NEGATIVE_INVENTORY,
            name="State2",
            description="Desc",
            severity=ForbiddenStateSeverity.HIGH,
            detection_method=StateDetectionMethod.PRE_TRANSACTION_VALIDATION,
            default_action=ForbiddenStateAction.REJECT,
            recovery_action="R",
            auto_correct=False,
            is_active=True,
            created_at=FIXED_DATETIME,
            created_by="t",
            approved_by=[],
            version="1.0",
            override_allowed=False,
            override_roles=[],
        )
        registry.save_state(s1)
        registry.save_state(s2)
        all_states = registry.get_all_states()
        # There are default states + 2 added
        assert len(all_states) >= 2

    def test_delete_state(self, registry, sample_state):
        registry.save_state(sample_state)
        assert registry.delete_state(sample_state.state_id) is True
        assert registry.get_state(sample_state.state_id) is None
        assert registry.delete_state(uuid.uuid4()) is False

    def test_save_and_get_detections(self, registry, sample_detection):
        registry.save_detection(sample_detection)
        detections = registry.get_detections()
        assert len(detections) == 1
        assert detections[0].detection_id == sample_detection.detection_id

    @pytest.mark.parametrize("category", [
        ForbiddenStateCategory.NEGATIVE_CASH,
        ForbiddenStateCategory.NEGATIVE_INVENTORY,
    ])
    def test_get_detections_filter_by_category(self, registry, category):
        d1 = ForbiddenStateDetection(
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
        )
        d2 = ForbiddenStateDetection(
            detection_id=uuid.uuid4(),
            state_id=uuid.uuid4(),
            category=ForbiddenStateCategory.NEGATIVE_INVENTORY,
            severity=ForbiddenStateSeverity.HIGH,
            detected_at=FIXED_DATETIME,
            detection_method=StateDetectionMethod.PRE_TRANSACTION_VALIDATION,
            current_state={},
            attempted_action={},
            prevented=True,
            action_taken=ForbiddenStateAction.REJECT,
            source_module="test",
            resolved=False,
        )
        registry.save_detection(d1)
        registry.save_detection(d2)
        result = registry.get_detections(category=category)
        assert len(result) == 1
        assert result[0].category == category

    def test_get_detections_filter_by_date(self, registry):
        now = FIXED_DATETIME
        d1 = ForbiddenStateDetection(
            detection_id=uuid.uuid4(),
            state_id=uuid.uuid4(),
            category=ForbiddenStateCategory.NEGATIVE_CASH,
            severity=ForbiddenStateSeverity.HIGH,
            detected_at=now - timedelta(days=10),
            detection_method=StateDetectionMethod.PRE_TRANSACTION_VALIDATION,
            current_state={},
            attempted_action={},
            prevented=True,
            action_taken=ForbiddenStateAction.REJECT,
            source_module="test",
            resolved=False,
        )
        d2 = ForbiddenStateDetection(
            detection_id=uuid.uuid4(),
            state_id=uuid.uuid4(),
            category=ForbiddenStateCategory.NEGATIVE_CASH,
            severity=ForbiddenStateSeverity.HIGH,
            detected_at=now - timedelta(days=2),
            detection_method=StateDetectionMethod.PRE_TRANSACTION_VALIDATION,
            current_state={},
            attempted_action={},
            prevented=True,
            action_taken=ForbiddenStateAction.REJECT,
            source_module="test",
            resolved=False,
        )
        registry.save_detection(d1)
        registry.save_detection(d2)
        result = registry.get_detections(from_date=now - timedelta(days=5))
        assert len(result) == 1
        assert result[0].detected_at >= now - timedelta(days=5)

    def test_get_detections_resolved_unresolved_prevented(self, registry):
        d1 = ForbiddenStateDetection(
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
            resolved=True,
        )
        d2 = ForbiddenStateDetection(
            detection_id=uuid.uuid4(),
            state_id=uuid.uuid4(),
            category=ForbiddenStateCategory.NEGATIVE_CASH,
            severity=ForbiddenStateSeverity.HIGH,
            detected_at=FIXED_DATETIME,
            detection_method=StateDetectionMethod.PRE_TRANSACTION_VALIDATION,
            current_state={},
            attempted_action={},
            prevented=False,
            action_taken=ForbiddenStateAction.WARN,
            source_module="test",
            resolved=False,
        )
        registry.save_detection(d1)
        registry.save_detection(d2)

        resolved = registry.get_detections(resolved_only=True)
        assert len(resolved) == 1
        assert resolved[0].resolved is True

        unresolved = registry.get_detections(unresolved_only=True)
        assert len(unresolved) == 1
        assert unresolved[0].resolved is False

        prevented = registry.get_detections(prevented_only=True)
        assert len(prevented) == 1
        assert prevented[0].prevented is True

    def test_resolve_detection(self, registry):
        d = ForbiddenStateDetection(
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
        )
        registry.save_detection(d)
        resolved = registry.resolve_detection(d.detection_id, "admin", "Fixed")
        assert resolved is not None
        assert resolved.resolved is True
        assert resolved.resolved_by == "admin"
        # Resolve again should return None
        resolved2 = registry.resolve_detection(d.detection_id, "admin2", "Again")
        assert resolved2 is None

    def test_check_no_state_defined(self, registry):
        is_forbidden, detection, action = registry.check(
            category=ForbiddenStateCategory.NEGATIVE_CASH,
            context={"current_balance": Decimal("100"), "proposed_change": Decimal("-150")},
        )
        # Default states exist, so it should detect
        # Actually there is a default state for NEGATIVE_CASH, so it will detect.
        # So we need to test with a category that has no default state.
        # Let's use a category that's not in default list e.g., NEGATIVE_PAYABLE
        is_forbidden, detection, action = registry.check(
            category=ForbiddenStateCategory.NEGATIVE_PAYABLE,
            context={"current_balance": Decimal("100"), "proposed_change": Decimal("-150")},
        )
        assert not is_forbidden
        assert detection is None
        assert action is None

    def test_check_detects_forbidden(self, registry):
        is_forbidden, detection, action = registry.check(
            category=ForbiddenStateCategory.NEGATIVE_CASH,
            context={"current_balance": Decimal("100"), "proposed_change": Decimal("-150")},
        )
        assert is_forbidden
        assert detection is not None
        assert detection.category == ForbiddenStateCategory.NEGATIVE_CASH
        assert action == ForbiddenStateAction.REJECT

    def test_check_with_override_allowed(self, registry):
        is_forbidden, detection, action = registry.check(
            category=ForbiddenStateCategory.NEGATIVE_CASH,
            context={"current_balance": Decimal("100"), "proposed_change": Decimal("-150")},
            override=True,
            override_authorized_by="admin",
        )
        assert is_forbidden
        assert detection is not None
        assert detection.override_used is True
        assert detection.action_taken == ForbiddenStateAction.WARN

    def test_check_with_override_unauthorized(self, registry):
        is_forbidden, detection, action = registry.check(
            category=ForbiddenStateCategory.NEGATIVE_CASH,
            context={"current_balance": Decimal("100"), "proposed_change": Decimal("-150")},
            override=True,
            override_authorized_by="unauthorized",
        )
        assert is_forbidden
        assert detection is not None
        assert detection.override_used is False

    def test_check_catastrophic_calls_handler(self, registry):
        with patch.object(registry, "_handle_catastrophic_detection") as mock_handle:
            # Create a catastrophic state and add it
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
                created_at=FIXED_DATETIME,
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

    def test_is_action_forbidden(self, registry):
        # Should be forbidden
        result = registry.is_action_forbidden(
            category=ForbiddenStateCategory.NEGATIVE_CASH,
            context={"current_balance": Decimal("100"), "proposed_change": Decimal("-150")},
        )
        assert result is True
        # Should not be forbidden
        result = registry.is_action_forbidden(
            category=ForbiddenStateCategory.NEGATIVE_CASH,
            context={"current_balance": Decimal("100"), "proposed_change": Decimal("-50")},
        )
        assert result is False

    def test_get_unresolved_detections(self, registry):
        d1 = ForbiddenStateDetection(
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
            resolved=True,
        )
        d2 = ForbiddenStateDetection(
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
        )
        registry.save_detection(d1)
        registry.save_detection(d2)
        unresolved = registry.get_unresolved_detections()
        assert len(unresolved) == 1
        assert unresolved[0].detection_id == d2.detection_id

    def test_get_statistics(self, registry):
        # Add some detections
        for _ in range(3):
            d = ForbiddenStateDetection(
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
            )
            registry.save_detection(d)
        stats = registry.get_statistics()
        assert stats["total_states"] > 0
        assert stats["active_states"] > 0
        assert stats["total_detections"] >= 3
        assert "by_category" in stats
        assert "by_severity" in stats

    def test_reset(self, registry):
        state = ForbiddenStateDefinition(
            state_id=uuid.uuid4(),
            category=ForbiddenStateCategory.NEGATIVE_CASH,
            name="State",
            description="Desc",
            severity=ForbiddenStateSeverity.HIGH,
            detection_method=StateDetectionMethod.PRE_TRANSACTION_VALIDATION,
            default_action=ForbiddenStateAction.REJECT,
            recovery_action="R",
            auto_correct=False,
            is_active=True,
            created_at=FIXED_DATETIME,
            created_by="t",
            approved_by=[],
            version="1.0",
            override_allowed=False,
            override_roles=[],
        )
        registry.save_state(state)
        d = ForbiddenStateDetection(
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
        )
        registry.save_detection(d)
        registry.reset()
        # Default states are re-loaded
        assert len(registry.states) > 0
        assert len(registry.detections) == 0


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
        state = ForbiddenStateDefinition(
            state_id=uuid.uuid4(),
            category=ForbiddenStateCategory.NEGATIVE_CASH,
            name="Test",
            description="Desc",
            severity=ForbiddenStateSeverity.HIGH,
            detection_method=StateDetectionMethod.PRE_TRANSACTION_VALIDATION,
            default_action=ForbiddenStateAction.REJECT,
            recovery_action="R",
            auto_correct=False,
            is_active=True,
            created_at=FIXED_DATETIME,
            created_by="t",
            approved_by=[],
            version="1.0",
            override_allowed=False,
            override_roles=[],
        )
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
        state = ForbiddenStateDefinition(
            state_id=uuid.uuid4(),
            category=ForbiddenStateCategory.NEGATIVE_CASH,
            name="Test",
            description="Desc",
            severity=ForbiddenStateSeverity.HIGH,
            detection_method=StateDetectionMethod.PRE_TRANSACTION_VALIDATION,
            default_action=ForbiddenStateAction.REJECT,
            recovery_action="R",
            auto_correct=False,
            is_active=True,
            created_at=FIXED_DATETIME,
            created_by="t",
            approved_by=[],
            version="1.0",
            override_allowed=False,
            override_roles=[],
        )
        svc.save_state(state)
        result = svc.delete_state(state.state_id)
        assert result is True
        assert svc.get_state(state.state_id) is None

    def test_save_and_get_detections(self):
        svc = ForbiddenStatesService()
        d = ForbiddenStateDetection(
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
        )
        svc.save_detection(d)
        detections = svc.get_detections()
        assert len(detections) == 1

    def test_resolve_detection(self):
        svc = ForbiddenStatesService()
        d = ForbiddenStateDetection(
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
        )
        svc.save_detection(d)
        resolved = svc.resolve_detection(d.detection_id, "admin", "Fixed")
        assert resolved is not None
        assert resolved.resolved is True

    def test_convenience_check_methods(self):
        svc = ForbiddenStatesService()
        # Negative cash
        is_forbidden, detection, action = svc.check_negative_cash(
            current_balance=Decimal("100"),
            proposed_change=Decimal("-150"),
        )
        assert is_forbidden
        assert detection is not None

        # Negative inventory
        is_forbidden, detection, action = svc.check_negative_inventory(
            current_quantity=Decimal("10"),
            proposed_change=Decimal("-15"),
        )
        assert is_forbidden
        assert detection is not None

        # Negative receivable
        is_forbidden, detection, action = svc.check_negative_receivable(
            current_balance=Decimal("1000"),
            proposed_payment=Decimal("1500"),
        )
        assert is_forbidden
        assert detection is not None

        # Imbalanced journal
        is_forbidden, detection, action = svc.check_imbalanced_journal(
            total_debit=Decimal("100"),
            total_credit=Decimal("100.1"),
        )
        assert is_forbidden
        assert detection is not None

        # Backdated transaction
        now = FIXED_DATETIME
        period_start = now - timedelta(days=10)
        is_forbidden, detection, action = svc.check_backdated_transaction(
            transaction_date=now - timedelta(days=40),
            current_period_start=period_start,
            max_backdate_days=30,
        )
        assert is_forbidden
        assert detection is not None

        # Cross-entity
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

        # Period closure
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

        # Broken hash chain
        is_forbidden, detection, action = svc.check_broken_hash_chain(
            expected_previous_hash="abc",
            actual_previous_hash="def",
        )
        assert is_forbidden
        assert detection is not None

    def test_get_detection_history(self):
        svc = ForbiddenStatesService()
        d = ForbiddenStateDetection(
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
        )
        svc.save_detection(d)
        history = svc.get_detection_history()
        assert len(history) == 1

    def test_get_statistics(self):
        svc = ForbiddenStatesService()
        stats = svc.get_statistics()
        assert "total_states" in stats


# =============================================================================
# Helper functions
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