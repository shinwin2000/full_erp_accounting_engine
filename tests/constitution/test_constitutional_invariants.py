#!/usr/bin/env python3
"""
tests/unit/test_constitutional_invariants.py
Test untuk constitution/constitutional_invariants.py
Mencakup: InvariantDefinition, InvariantViolation, InvariantValidator,
ConstitutionalInvariants, ConstitutionalInvariantsService
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from constitution.constitutional_invariants import (
    ConstitutionalInvariants,
    ConstitutionalInvariantsService,
    InvariantDefinition,
    InvariantScope,
    InvariantSeverity,
    InvariantType,
    InvariantValidationStage,
    InvariantValidator,
    InvariantViolation,
    InvariantViolationError,
    get_constitutional_invariants_service,
    get_validator_for_invariant,
)

# ============================================================================
# Helper Functions
# ============================================================================

def create_test_invariant_def(
    invariant_type: InvariantType = InvariantType.DOUBLE_ENTRY_BALANCE,
    is_active: bool = True,
    auto_correct: bool = False,
    severity: InvariantSeverity = InvariantSeverity.CRITICAL,
    scope: InvariantScope = InvariantScope.PER_TRANSACTION,
) -> InvariantDefinition:
    now = datetime.now(UTC)
    return InvariantDefinition(
        invariant_id=uuid.uuid4(),
        invariant_type=invariant_type,
        name=f"Test {invariant_type.name}",
        description="Test description",
        scope=scope,
        severity=severity,
        validation_function_name=f"validate_{invariant_type.name.lower()}",
        validation_stage=InvariantValidationStage.PRE_EXECUTION,
        is_active=is_active,
        created_at=now,
        created_by="tester",
        approved_by=["approver1", "approver2"] if scope == InvariantScope.GLOBAL else ["approver1"],
        version="1.0.0",
        auto_correct=auto_correct,
        correction_action="Correct automatically",
    )


def create_test_violation(
    invariant_type: InvariantType = InvariantType.DOUBLE_ENTRY_BALANCE,
    severity: InvariantSeverity = InvariantSeverity.CRITICAL,
) -> InvariantViolation:
    return InvariantViolation(
        violation_id=uuid.uuid4(),
        invariant_id=uuid.uuid4(),
        invariant_type=invariant_type,
        severity=severity,
        violated_at=datetime.now(UTC),
        actual_value={"test": "actual"},
        expected_value={"test": "expected"},
        difference={"test": "diff"},
        message="Test violation",
        offending_module="test_module",
        is_resolved=False,
        transaction_id=uuid.uuid4(),
        legal_entity_id=uuid.uuid4(),
        period_id=uuid.uuid4(),
        offending_user="test_user",
    )


# ============================================================================
# Tests for InvariantDefinition
# ============================================================================

class TestInvariantDefinition:
    def test_create_valid_definition(self):
        inv = create_test_invariant_def()
        assert inv.invariant_id is not None
        assert inv.invariant_type == InvariantType.DOUBLE_ENTRY_BALANCE
        assert inv.name == "Test DOUBLE_ENTRY_BALANCE"
        assert inv.scope == InvariantScope.PER_TRANSACTION
        assert inv.severity == InvariantSeverity.CRITICAL
        assert inv.is_active
        assert inv.version_number == 1
        assert inv.cryptographic_hash != ""
        assert len(inv.approved_by) == 1

    def test_validate_requires_approvers_for_global(self):
        now = datetime.now(UTC)
        with pytest.raises(ValueError, match="at least 2 approvers"):
            InvariantDefinition(
                invariant_id=uuid.uuid4(),
                invariant_type=InvariantType.ACCOUNTING_EQUATION,
                name="test",
                description="desc",
                scope=InvariantScope.GLOBAL,
                severity=InvariantSeverity.CRITICAL,
                validation_function_name="test",
                validation_stage=InvariantValidationStage.PRE_EXECUTION,
                is_active=True,
                created_at=now,
                created_by="tester",
                approved_by=["only_one"],
                version="1.0",
            )

    def test_validate_version_positive(self):
        now = datetime.now(UTC)
        with pytest.raises(ValueError, match="Version must be >= 1"):
            InvariantDefinition(
                invariant_id=uuid.uuid4(),
                invariant_type=InvariantType.DOUBLE_ENTRY_BALANCE,
                name="test",
                description="desc",
                scope=InvariantScope.PER_TRANSACTION,
                severity=InvariantSeverity.CRITICAL,
                validation_function_name="test",
                validation_stage=InvariantValidationStage.PRE_EXECUTION,
                is_active=True,
                created_at=now,
                created_by="tester",
                approved_by=["a"],
                version="1.0",
                version_number=0,
            )

    def test_compute_hash_consistent(self):
        inv1 = create_test_invariant_def()
        inv2 = InvariantDefinition(
            invariant_id=inv1.invariant_id,
            invariant_type=inv1.invariant_type,
            name=inv1.name,
            description=inv1.description,
            scope=inv1.scope,
            severity=inv1.severity,
            validation_function_name=inv1.validation_function_name,
            validation_stage=inv1.validation_stage,
            is_active=inv1.is_active,
            created_at=inv1.created_at,
            created_by=inv1.created_by,
            approved_by=inv1.approved_by.copy(),
            version=inv1.version,
            auto_correct=inv1.auto_correct,
            correction_action=inv1.correction_action,
            version_number=inv1.version_number,
        )
        assert inv1.compute_hash() == inv2.compute_hash()

    def test_update_creates_new_version(self):
        inv = create_test_invariant_def()
        updated = inv.update("admin", description="Updated description")
        assert updated.description == "Updated description"
        assert updated.version_number == inv.version_number + 1

    def test_delete_marks_deleted_and_inactive(self):
        inv = create_test_invariant_def()
        deleted = inv.delete("admin", "reason")
        assert deleted.deleted_at is not None
        assert deleted.deleted_by == "admin"
        assert not deleted.is_active
        assert deleted.version_number == inv.version_number + 1

    def test_restore_recovers_deleted(self):
        inv = create_test_invariant_def()
        deleted = inv.delete("admin", "reason")
        restored = deleted.restore("admin")
        assert restored.deleted_at is None
        assert restored.deleted_by is None
        assert restored.is_active

    def test_restore_not_deleted_raises(self):
        inv = create_test_invariant_def()
        with pytest.raises(ValueError, match="Not deleted"):
            inv.restore("admin")

    def test_activate_does_nothing_if_active(self):
        inv = create_test_invariant_def()
        activated = inv.activate("admin")
        assert activated is inv

    def test_activate_activates_inactive(self):
        inv = create_test_invariant_def()
        deactivated = inv.deactivate("admin", "reason")
        activated = deactivated.activate("admin")
        assert activated.is_active
        assert activated.version_number == deactivated.version_number + 1

    def test_deactivate_does_nothing_if_inactive(self):
        inv = create_test_invariant_def()
        deactivated = inv.deactivate("admin", "reason")
        again = deactivated.deactivate("admin", "again")
        assert again is deactivated

    def test_lock_returns_self(self):
        inv = create_test_invariant_def()
        locked = inv.lock("admin", "reason")
        assert locked is inv

    def test_unlock_returns_self(self):
        inv = create_test_invariant_def()
        unlocked = inv.unlock("admin")
        assert unlocked is inv

    def test_create_returns_self(self):
        inv = create_test_invariant_def()
        result = inv.create("admin")
        assert result is inv

    def test_validate_returns_valid(self):
        inv = create_test_invariant_def()
        result = inv.validate()
        assert result["is_valid"]
        assert result["invariant_id"] == str(inv.invariant_id)

    def test_validate_returns_errors_on_hash_mismatch(self):
        inv = create_test_invariant_def()
        object.__setattr__(inv, "cryptographic_hash", "fake")
        result = inv.validate()
        assert not result["is_valid"]
        assert "Hash mismatch" in result["errors"]

    def test_to_dict_contains_fields(self):
        inv = create_test_invariant_def()
        d = inv.to_dict()
        assert d["invariant_type"] == "DOUBLE_ENTRY_BALANCE"
        assert d["name"] == "Test DOUBLE_ENTRY_BALANCE"
        assert d["scope"] == "PER_TRANSACTION"
        assert d["severity"] == "CRITICAL"
        assert d["is_active"]
        assert "version_number" in d

    def test_from_dict_reconstructs(self):
        inv = create_test_invariant_def()
        d = inv.to_dict()
        reconstructed = InvariantDefinition.from_dict(d)
        assert reconstructed.invariant_id == inv.invariant_id
        assert reconstructed.invariant_type == inv.invariant_type
        assert reconstructed.name == inv.name
        assert reconstructed.scope == inv.scope
        assert reconstructed.severity == inv.severity

    def test_clone_creates_new_instance(self):
        inv = create_test_invariant_def()
        cloned = inv.clone()
        assert cloned.invariant_id != inv.invariant_id
        assert cloned.invariant_type == inv.invariant_type
        assert cloned.name == inv.name
        assert not cloned.is_active
        assert cloned.version_number == 1

    def test_snapshot_returns_summary(self):
        inv = create_test_invariant_def()
        snap = inv.snapshot()
        assert snap["invariant_id"] == str(inv.invariant_id)
        assert snap["name"] == inv.name

    def test_audit_trail_records(self):
        inv = create_test_invariant_def()
        assert len(inv.audit_trail()) >= 1
        inv.touch("toucher")
        trail = inv.audit_trail()
        assert len(trail) >= 2
        assert trail[-1]["action"] == "TOUCH"

    def test_touch_increments_version(self):
        inv = create_test_invariant_def()
        touched = inv.touch("toucher")
        assert touched.version_number == inv.version_number + 1

    def test_is_active_rule_handles_deleted(self):
        inv = create_test_invariant_def()
        assert inv.is_active_rule()
        deleted = inv.delete("admin", "reason")
        assert not deleted.is_active_rule()


# ============================================================================
# Tests for InvariantViolation
# ============================================================================

class TestInvariantViolation:
    def test_create_valid_violation(self):
        violation = create_test_violation()
        assert violation.violation_id is not None
        assert violation.invariant_id is not None
        assert violation.invariant_type == InvariantType.DOUBLE_ENTRY_BALANCE
        assert violation.severity == InvariantSeverity.CRITICAL
        assert not violation.is_resolved
        assert violation.forensic_evidence_hash != ""
        assert violation.version_number == 1

    def test_validate_returns_valid(self):
        violation = create_test_violation()
        result = violation.validate()
        assert result["is_valid"]
        assert result["violation_id"] == str(violation.violation_id)

    def test_validate_returns_errors_on_forensic_hash_mismatch(self):
        violation = create_test_violation()
        object.__setattr__(violation, "forensic_evidence_hash", "fake")
        result = violation.validate()
        assert not result["is_valid"]
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
        locked = violation.lock("admin", "reason")
        assert locked is violation

    def test_unlock_returns_self(self):
        violation = create_test_violation()
        unlocked = violation.unlock("admin")
        assert unlocked is violation

    def test_create_returns_self(self):
        violation = create_test_violation()
        result = violation.create("admin")
        assert result is violation

    def test_to_dict_contains_fields(self):
        violation = create_test_violation()
        d = violation.to_dict()
        assert d["invariant_type"] == "DOUBLE_ENTRY_BALANCE"
        assert d["severity"] == "CRITICAL"
        assert not d["is_resolved"]
        assert "violation_id" in d

    def test_from_dict_reconstructs(self):
        violation = create_test_violation()
        d = violation.to_dict()
        reconstructed = InvariantViolation.from_dict(d)
        assert reconstructed.violation_id == violation.violation_id
        assert reconstructed.invariant_id == violation.invariant_id
        assert reconstructed.invariant_type == violation.invariant_type
        assert reconstructed.severity == violation.severity

    def test_clone_creates_new_instance(self):
        violation = create_test_violation()
        cloned = violation.clone()
        assert cloned.violation_id != violation.violation_id
        assert cloned.invariant_id == violation.invariant_id
        assert not cloned.is_resolved
        assert cloned.version_number == 1

    def test_snapshot_returns_summary(self):
        violation = create_test_violation()
        snap = violation.snapshot()
        assert snap["violation_id"] == str(violation.violation_id)
        assert snap["invariant_type"] == violation.invariant_type.name

    def test_audit_trail_records(self):
        violation = create_test_violation()
        assert len(violation.audit_trail()) >= 1
        violation.touch("toucher")
        trail = violation.audit_trail()
        assert len(trail) >= 2
        assert trail[-1]["action"] == "TOUCH"

    def test_is_resolved_method(self):
        violation = create_test_violation()
        assert not violation.is_resolved()

    def test_resolve_marks_resolved(self):
        violation = create_test_violation()
        resolved = violation.resolve("admin", "action")
        assert resolved.is_resolved
        assert resolved.resolved_at is not None
        assert resolved.resolved_by == "admin"
        assert resolved.resolution_action == "action"
        assert resolved.version_number == violation.version_number + 1

    def test_resolve_already_resolved_raises(self):
        violation = create_test_violation()
        resolved = violation.resolve("admin", "action")
        with pytest.raises(ValueError, match="Already resolved"):
            resolved.resolve("admin2", "action2")


# ============================================================================
# Tests for InvariantValidator
# ============================================================================

class TestInvariantValidator:
    def test_validate_accounting_equation_valid(self):
        is_valid, diff, hint = InvariantValidator.validate_accounting_equation(
            {"total_assets": Decimal("1000"), "total_liabilities": Decimal("600"), "total_equity": Decimal("400")}
        )
        assert is_valid
        assert diff["difference"] == "0"
        assert hint is None

    def test_validate_accounting_equation_invalid(self):
        is_valid, diff, hint = InvariantValidator.validate_accounting_equation(
            {"total_assets": Decimal("1000"), "total_liabilities": Decimal("500"), "total_equity": Decimal("400")}
        )
        assert not is_valid
        assert diff["difference"] == "100"
        assert hint is not None

    def test_validate_double_entry_balance_valid(self):
        is_valid, diff, hint = InvariantValidator.validate_double_entry_balance(
            {"total_debit": Decimal("500"), "total_credit": Decimal("500")}
        )
        assert is_valid
        assert diff["difference"] == "0"

    def test_validate_double_entry_balance_invalid(self):
        is_valid, diff, hint = InvariantValidator.validate_double_entry_balance(
            {"total_debit": Decimal("500"), "total_credit": Decimal("400")}
        )
        assert not is_valid
        assert diff["difference"] == "100"

    def test_validate_conservation_of_value_valid(self):
        is_valid, diff, hint = InvariantValidator.validate_conservation_of_value(
            {"source_value": Decimal("1000"), "destination_value": Decimal("990"), "transaction_fee": Decimal("10")}
        )
        assert is_valid

    def test_validate_conservation_of_value_invalid(self):
        is_valid, diff, hint = InvariantValidator.validate_conservation_of_value(
            {"source_value": Decimal("1000"), "destination_value": Decimal("900"), "transaction_fee": Decimal("10")}
        )
        assert not is_valid

    def test_validate_time_monotonicity_valid(self):
        now = datetime.now(UTC)
        context = {
            "transaction_time": now,
            "last_transaction_time": now - timedelta(minutes=5),
            "period_start": now - timedelta(days=1),
            "period_end": now + timedelta(days=1),
        }
        is_valid, diff, hint = InvariantValidator.validate_time_monotonicity(context)
        assert is_valid

    def test_validate_time_monotonicity_invalid_backward(self):
        now = datetime.now(UTC)
        context = {
            "transaction_time": now - timedelta(minutes=5),
            "last_transaction_time": now,
            "period_start": now - timedelta(days=1),
            "period_end": now + timedelta(days=1),
        }
        is_valid, diff, hint = InvariantValidator.validate_time_monotonicity(context)
        assert not is_valid
        assert "Transaction time cannot be earlier than last transaction" in hint

    def test_validate_time_monotonicity_invalid_outside_period(self):
        now = datetime.now(UTC)
        context = {
            "transaction_time": now + timedelta(days=2),
            "period_start": now - timedelta(days=1),
            "period_end": now + timedelta(days=1),
        }
        is_valid, diff, hint = InvariantValidator.validate_time_monotonicity(context)
        assert not is_valid
        assert "Transaction time outside period" in hint

    def test_validate_legal_entity_isolation_valid(self):
        le_id = uuid.uuid4()
        context = {
            "transaction_legal_entity_id": le_id,
            "accessed_legal_entity_ids": [],
            "user_legal_entity_ids": [le_id],
        }
        is_valid, diff, hint = InvariantValidator.validate_legal_entity_isolation(context)
        assert is_valid

    def test_validate_legal_entity_isolation_invalid(self):
        le_id = uuid.uuid4()
        context = {
            "transaction_legal_entity_id": le_id,
            "accessed_legal_entity_ids": [],
            "user_legal_entity_ids": [uuid.uuid4()],
        }
        is_valid, diff, hint = InvariantValidator.validate_legal_entity_isolation(context)
        assert not is_valid
        assert "User does not have access" in hint

    def test_validate_currency_consistency_valid(self):
        context = {
            "currencies": {"IDR", "USD"},
            "base_currency": "IDR",
            "exchange_rates": {"USD": Decimal("15250")},
        }
        is_valid, diff, hint = InvariantValidator.validate_currency_consistency(context)
        assert is_valid

    def test_validate_currency_consistency_invalid(self):
        context = {
            "currencies": {"IDR", "USD"},
            "base_currency": "IDR",
            "exchange_rates": {},
        }
        is_valid, diff, hint = InvariantValidator.validate_currency_consistency(context)
        assert not is_valid
        assert "missing_exchange_rate" in diff

    def test_validate_hash_chain_consistency_valid(self):
        content = "test content"
        h = hashlib.sha3_256(content.encode()).hexdigest()
        context = {"current_hash": h, "content_to_hash": content}
        is_valid, diff, hint = InvariantValidator.validate_hash_chain_consistency(context)
        assert is_valid

    def test_validate_hash_chain_consistency_invalid_hash(self):
        context = {"current_hash": "fakehash", "content_to_hash": "test"}
        is_valid, diff, hint = InvariantValidator.validate_hash_chain_consistency(context)
        assert not is_valid
        assert "Hash mismatch" in hint

    def test_validate_hash_chain_consistency_broken_chain(self):
        context = {"previous_hash": "prevhash", "expected_previous_hash": "different"}
        is_valid, diff, hint = InvariantValidator.validate_hash_chain_consistency(context)
        assert not is_valid
        assert "Hash chain broken" in hint

    def test_validate_audit_trail_completeness_valid(self):
        context = {"expected_event_count": 10, "actual_event_count": 10, "missing_sequence_numbers": []}
        is_valid, diff, hint = InvariantValidator.validate_audit_trail_completeness(context)
        assert is_valid

    def test_validate_audit_trail_completeness_invalid_missing(self):
        context = {"expected_event_count": 10, "actual_event_count": 8, "missing_sequence_numbers": []}
        is_valid, diff, hint = InvariantValidator.validate_audit_trail_completeness(context)
        assert not is_valid
        assert "Missing 2 audit events" in hint

    def test_validate_audit_trail_completeness_invalid_sequence(self):
        context = {"expected_event_count": 10, "actual_event_count": 10, "missing_sequence_numbers": [3, 4, 5]}
        is_valid, diff, hint = InvariantValidator.validate_audit_trail_completeness(context)
        assert not is_valid
        assert "Missing sequence numbers" in hint

    def test_validate_idempotency_strict_valid(self):
        context = {"idempotency_key": "key1", "previous_result": "result", "current_result": "result"}
        is_valid, diff, hint = InvariantValidator.validate_idempotency_strict(context)
        assert is_valid

    def test_validate_idempotency_strict_invalid(self):
        context = {"idempotency_key": "key1", "previous_result": "result1", "current_result": "result2"}
        is_valid, diff, hint = InvariantValidator.validate_idempotency_strict(context)
        assert not is_valid
        assert "Non-idempotent result" in hint

    def test_validate_non_negative_cash_valid(self):
        context = {"cash_balance": Decimal("100"), "proposed_change": Decimal("-50")}
        is_valid, diff, hint = InvariantValidator.validate_non_negative_cash(context)
        assert is_valid

    def test_validate_non_negative_cash_invalid(self):
        context = {"cash_balance": Decimal("100"), "proposed_change": Decimal("-150")}
        is_valid, diff, hint = InvariantValidator.validate_non_negative_cash(context)
        assert not is_valid
        assert "negative cash balance" in hint

    def test_validate_non_negative_inventory_valid(self):
        context = {"quantity": Decimal("100"), "proposed_change": Decimal("-50")}
        is_valid, diff, hint = InvariantValidator.validate_non_negative_inventory(context)
        assert is_valid

    def test_validate_non_negative_inventory_invalid(self):
        context = {"quantity": Decimal("100"), "proposed_change": Decimal("-150")}
        is_valid, diff, hint = InvariantValidator.validate_non_negative_inventory(context)
        assert not is_valid
        assert "Insufficient inventory" in hint

    def test_validate_non_negative_receivable_valid(self):
        context = {"receivable_balance": Decimal("100"), "proposed_payment": Decimal("-50")}
        is_valid, diff, hint = InvariantValidator.validate_non_negative_receivable(context)
        assert is_valid

    def test_validate_non_negative_receivable_invalid(self):
        context = {"receivable_balance": Decimal("100"), "proposed_payment": Decimal("-150")}
        is_valid, diff, hint = InvariantValidator.validate_non_negative_receivable(context)
        assert not is_valid
        assert "Payment exceeds receivable balance" in hint

    def test_validate_tax_consistency_valid(self):
        context = {"tax_collected": Decimal("1000"), "tax_submitted": Decimal("1000")}
        is_valid, diff, hint = InvariantValidator.validate_tax_consistency(context)
        assert is_valid

    def test_validate_tax_consistency_invalid(self):
        context = {"tax_collected": Decimal("1000"), "tax_submitted": Decimal("900")}
        is_valid, diff, hint = InvariantValidator.validate_tax_consistency(context)
        assert not is_valid

    def test_validate_period_closure_finality_valid(self):
        context = {"is_closed": False, "is_reopening": False}
        is_valid, diff, hint = InvariantValidator.validate_period_closure_finality(context)
        assert is_valid

    def test_validate_period_closure_finality_reopening_requires_approval(self):
        context = {"is_closed": True, "is_reopening": True, "reopening_authorization": {}}
        is_valid, diff, hint = InvariantValidator.validate_period_closure_finality(context)
        assert not is_valid
        assert "dual approval" in hint

    def test_validate_period_integrity_valid(self):
        now = datetime.now(UTC)
        context = {
            "transaction_date": now,
            "period_start": now - timedelta(days=1),
            "period_end": now + timedelta(days=1),
            "period_status": "OPEN",
        }
        is_valid, diff, hint = InvariantValidator.validate_period_integrity(context)
        assert is_valid

    def test_validate_period_integrity_closed_period(self):
        now = datetime.now(UTC)
        context = {
            "transaction_date": now,
            "period_start": now - timedelta(days=1),
            "period_end": now + timedelta(days=1),
            "period_status": "CLOSED",
        }
        is_valid, diff, hint = InvariantValidator.validate_period_integrity(context)
        assert not is_valid
        assert "Cannot post to closed period" in hint

    def test_validate_period_integrity_locked_period(self):
        now = datetime.now(UTC)
        context = {
            "transaction_date": now,
            "period_start": now - timedelta(days=1),
            "period_end": now + timedelta(days=1),
            "period_status": "LOCKED",
        }
        is_valid, diff, hint = InvariantValidator.validate_period_integrity(context)
        assert not is_valid
        assert "Period is locked" in hint

    def test_validate_period_integrity_outside_period(self):
        now = datetime.now(UTC)
        context = {
            "transaction_date": now + timedelta(days=2),
            "period_start": now - timedelta(days=1),
            "period_end": now + timedelta(days=1),
            "period_status": "OPEN",
        }
        is_valid, diff, hint = InvariantValidator.validate_period_integrity(context)
        assert not is_valid
        assert "Transaction date outside period" in hint

    def test_validate_sequence_integrity_valid(self):
        context = {"current_number": 5, "last_number": 4, "expected_next": 5, "allow_gap": False}
        is_valid, diff, hint = InvariantValidator.validate_sequence_integrity(context)
        assert is_valid

    def test_validate_sequence_integrity_gap(self):
        context = {"current_number": 6, "last_number": 4, "expected_next": 5, "allow_gap": False}
        is_valid, diff, hint = InvariantValidator.validate_sequence_integrity(context)
        assert not is_valid
        assert "Sequence gap detected" in hint

    def test_validate_currency_exposure_consistency_valid(self):
        context = {
            "foreign_currency_amounts": {"USD": Decimal("100")},
            "functional_currency_amounts": {"USD": Decimal("1525000")},
            "exchange_rates": {"USD": Decimal("15250")},
        }
        is_valid, diff, hint = InvariantValidator.validate_currency_exposure_consistency(context)
        assert is_valid

    def test_validate_currency_exposure_consistency_invalid(self):
        context = {
            "foreign_currency_amounts": {"USD": Decimal("100")},
            "functional_currency_amounts": {"USD": Decimal("1500000")},
            "exchange_rates": {"USD": Decimal("15250")},
        }
        is_valid, diff, hint = InvariantValidator.validate_currency_exposure_consistency(context)
        assert not is_valid
        assert "Currency exposure mismatch" in hint


# ============================================================================
# Tests for ConstitutionalInvariants
# ============================================================================

class TestConstitutionalInvariants:
    def test_initialization_loads_default_invariants(self):
        inv = ConstitutionalInvariants()
        assert len(inv.invariants) > 0
        assert inv.get_invariant(list(inv.invariants.keys())[0]) is not None

    def test_save_and_get_invariant(self):
        inv = ConstitutionalInvariants()
        inv_def = create_test_invariant_def()
        inv.save_invariant(inv_def)
        retrieved = inv.get_invariant(inv_def.invariant_id)
        assert retrieved is not None
        assert retrieved.invariant_id == inv_def.invariant_id

    def test_get_all_invariants(self):
        inv = ConstitutionalInvariants()
        inv_def1 = create_test_invariant_def()
        inv_def2 = create_test_invariant_def(invariant_type=InvariantType.ACCOUNTING_EQUATION)
        inv.save_invariant(inv_def1)
        inv.save_invariant(inv_def2)
        all_inv = inv.get_all_invariants()
        assert len(all_inv) >= 2

    def test_delete_invariant(self):
        inv = ConstitutionalInvariants()
        inv_def = create_test_invariant_def()
        inv.save_invariant(inv_def)
        result = inv.delete_invariant(inv_def.invariant_id)
        assert result
        assert inv.get_invariant(inv_def.invariant_id) is None

    def test_save_and_get_violations(self):
        inv = ConstitutionalInvariants()
        violation = create_test_violation()
        inv.save_violation(violation)
        violations = inv.get_violations()
        assert len(violations) >= 1
        found = next((v for v in violations if v.violation_id == violation.violation_id), None)
        assert found is not None

    def test_get_violations_filter_by_type(self):
        inv = ConstitutionalInvariants()
        v1 = create_test_violation(invariant_type=InvariantType.DOUBLE_ENTRY_BALANCE)
        v2 = create_test_violation(invariant_type=InvariantType.ACCOUNTING_EQUATION)
        inv.save_violation(v1)
        inv.save_violation(v2)
        result = inv.get_violations(invariant_type=InvariantType.ACCOUNTING_EQUATION)
        assert len(result) == 1
        assert result[0].invariant_type == InvariantType.ACCOUNTING_EQUATION

    def test_get_violations_filter_by_date(self):
        inv = ConstitutionalInvariants()
        now = datetime.now(UTC)
        v1 = create_test_violation()
        v1.violated_at = now - timedelta(days=10)
        v2 = create_test_violation()
        v2.violated_at = now - timedelta(days=2)
        inv.save_violation(v1)
        inv.save_violation(v2)
        result = inv.get_violations(from_date=now - timedelta(days=5))
        assert len(result) == 1
        assert result[0].violated_at >= now - timedelta(days=5)

    def test_get_violations_resolved_unresolved(self):
        inv = ConstitutionalInvariants()
        v1 = create_test_violation()
        v1.is_resolved = True
        v2 = create_test_violation()
        v2.is_resolved = False
        inv.save_violation(v1)
        inv.save_violation(v2)
        resolved = inv.get_violations(resolved_only=True)
        unresolved = inv.get_violations(unresolved_only=True)
        assert len(resolved) == 1
        assert resolved[0].is_resolved
        assert len(unresolved) == 1
        assert not unresolved[0].is_resolved

    def test_resolve_violation(self):
        inv = ConstitutionalInvariants()
        violation = create_test_violation()
        inv.save_violation(violation)
        resolved = inv.resolve_violation(violation.violation_id, "admin", "action")
        assert resolved is not None
        assert resolved.is_resolved
        assert resolved.resolved_by == "admin"

    def test_resolve_violation_already_resolved(self):
        inv = ConstitutionalInvariants()
        violation = create_test_violation()
        inv.save_violation(violation)
        resolved = inv.resolve_violation(violation.violation_id, "admin", "action")
        assert resolved is not None
        again = inv.resolve_violation(violation.violation_id, "admin2", "action2")
        assert again is None

    def test_validate_returns_valid(self):
        inv = ConstitutionalInvariants()
        context = {"total_debit": Decimal("100"), "total_credit": Decimal("100")}
        is_valid, violation = inv.validate(
            invariant_type=InvariantType.DOUBLE_ENTRY_BALANCE,
            context=context,
        )
        assert is_valid
        assert violation is None

    def test_validate_returns_invalid(self):
        inv = ConstitutionalInvariants()
        context = {"total_debit": Decimal("100"), "total_credit": Decimal("90")}
        is_valid, violation = inv.validate(
            invariant_type=InvariantType.DOUBLE_ENTRY_BALANCE,
            context=context,
        )
        assert not is_valid
        assert violation is not None
        assert violation.invariant_type == InvariantType.DOUBLE_ENTRY_BALANCE

    def test_validate_with_auto_correct(self):
        inv = ConstitutionalInvariants()
        inv_def = create_test_invariant_def(
            invariant_type=InvariantType.DOUBLE_ENTRY_BALANCE,
            auto_correct=True,
        )
        inv.save_invariant(inv_def)
        context = {"total_debit": Decimal("100"), "total_credit": Decimal("90")}
        is_valid, violation = inv.validate(
            invariant_type=InvariantType.DOUBLE_ENTRY_BALANCE,
            context=context,
            auto_correct=True,
        )
        assert not is_valid
        assert violation is not None
        assert violation.auto_corrected
        assert violation.auto_correction_applied is not None

    def test_validate_all_active(self):
        inv = ConstitutionalInvariants()
        context = {"total_debit": Decimal("100"), "total_credit": Decimal("90")}
        violations = inv.validate_all_active(
            context=context,
            scope_filter=InvariantScope.PER_TRANSACTION,
            stage_filter=InvariantValidationStage.PRE_EXECUTION,
        )
        assert len(violations) > 0

    def test_get_unresolved_violations(self):
        inv = ConstitutionalInvariants()
        v1 = create_test_violation()
        v1.is_resolved = False
        v2 = create_test_violation()
        v2.is_resolved = True
        inv.save_violation(v1)
        inv.save_violation(v2)
        unresolved = inv.get_unresolved_violations()
        assert len(unresolved) == 1
        assert not unresolved[0].is_resolved

    def test_add_invariant_checks_hash(self):
        inv = ConstitutionalInvariants()
        inv_def = create_test_invariant_def()
        inv.add_invariant(inv_def)
        assert inv.get_invariant(inv_def.invariant_id) is not None

    def test_add_invariant_hash_mismatch_raises(self):
        inv = ConstitutionalInvariants()
        inv_def = create_test_invariant_def()
        object.__setattr__(inv_def, "cryptographic_hash", "fake")
        with pytest.raises(ValueError, match="Hash mismatch"):
            inv.add_invariant(inv_def)

    def test_deactivate_invariant(self):
        inv = ConstitutionalInvariants()
        inv_def = create_test_invariant_def()
        inv.save_invariant(inv_def)
        inv.deactivate_invariant(inv_def.invariant_id, "admin")
        updated = inv.get_invariant(inv_def.invariant_id)
        assert not updated.is_active

    def test_get_statistics(self):
        inv = ConstitutionalInvariants()
        inv_def = create_test_invariant_def()
        inv.save_invariant(inv_def)
        violation = create_test_violation()
        inv.save_violation(violation)
        stats = inv.get_statistics()
        assert stats["total_invariants"] >= 1
        assert stats["active_invariants"] >= 1
        assert stats["total_violations"] >= 1
        assert "by_severity" in stats

    def test_reset(self):
        inv = ConstitutionalInvariants()
        inv_def = create_test_invariant_def()
        inv.save_invariant(inv_def)
        violation = create_test_violation()
        inv.save_violation(violation)
        inv.reset()
        assert len(inv.invariants) > 0
        assert len(inv.violations) == 0


# ============================================================================
# Tests for ConstitutionalInvariantsService
# ============================================================================

class TestConstitutionalInvariantsService:
    def test_singleton(self):
        svc1 = ConstitutionalInvariantsService()
        svc2 = ConstitutionalInvariantsService()
        assert svc1 is svc2

    def test_repository_methods_delegate(self):
        svc = ConstitutionalInvariantsService()
        inv_def = create_test_invariant_def()
        svc.save_invariant(inv_def)
        retrieved = svc.get_invariant(inv_def.invariant_id)
        assert retrieved is not None
        assert retrieved.invariant_id == inv_def.invariant_id

        all_inv = svc.get_all_invariants()
        assert len(all_inv) > 0

        result = svc.delete_invariant(inv_def.invariant_id)
        assert result

    def test_save_and_get_violations(self):
        svc = ConstitutionalInvariantsService()
        violation = create_test_violation()
        svc.save_violation(violation)
        violations = svc.get_violations()
        assert len(violations) >= 1

    def test_resolve_violation(self):
        svc = ConstitutionalInvariantsService()
        violation = create_test_violation()
        svc.save_violation(violation)
        resolved = svc.resolve_violation(violation.violation_id, "admin", "action")
        assert resolved is not None
        assert resolved.is_resolved

    def test_validate_delegates_and_does_not_raise_for_non_catastrophic(self):
        svc = ConstitutionalInvariantsService()
        context = {"total_debit": Decimal("100"), "total_credit": Decimal("90")}
        is_valid, violation = svc.validate(
            invariant_type=InvariantType.DOUBLE_ENTRY_BALANCE,
            context=context,
        )
        assert not is_valid
        assert violation is not None

    def test_validate_raises_for_catastrophic(self):
        svc = ConstitutionalInvariantsService()
        context = {"total_assets": Decimal("1000"), "total_liabilities": Decimal("500"), "total_equity": Decimal("400")}
        with pytest.raises(InvariantViolationError):
            svc.validate(
                invariant_type=InvariantType.ACCOUNTING_EQUATION,
                context=context,
            )

    def test_validate_all(self):
        svc = ConstitutionalInvariantsService()
        context = {"total_debit": Decimal("100"), "total_credit": Decimal("90")}
        violations = svc.validate_all(context, stage=InvariantValidationStage.PRE_EXECUTION)
        assert len(violations) > 0

    def test_convenience_validation_methods(self):
        svc = ConstitutionalInvariantsService()
        is_valid, violation = svc.validate_accounting_equation(
            total_assets=Decimal("1000"),
            total_liabilities=Decimal("600"),
            total_equity=Decimal("400"),
        )
        assert is_valid
        assert violation is None

        is_valid, violation = svc.validate_double_entry(
            total_debit=Decimal("100"),
            total_credit=Decimal("100"),
        )
        assert is_valid
        assert violation is None

        now = datetime.now(UTC)
        is_valid, violation = svc.validate_period_integrity(
            transaction_date=now,
            period_start=now - timedelta(days=1),
            period_end=now + timedelta(days=1),
            period_status="OPEN",
        )
        assert is_valid
        assert violation is None

        le_id = uuid.uuid4()
        is_valid, violation = svc.validate_legal_entity_isolation(
            transaction_legal_entity_id=le_id,
            accessed_legal_entity_ids=[],
            user_legal_entity_ids=[le_id],
        )
        assert is_valid
        assert violation is None

        is_valid, violation = svc.validate_non_negative_cash(
            current_balance=Decimal("100"),
            proposed_change=Decimal("-50"),
        )
        assert is_valid
        assert violation is None

    def test_get_active_invariants(self):
        svc = ConstitutionalInvariantsService()
        active = svc.get_active_invariants()
        assert len(active) > 0
        assert all(inv.is_active for inv in active)

    def test_get_violation_report(self):
        svc = ConstitutionalInvariantsService()
        violation = create_test_violation()
        svc.save_violation(violation)
        report = svc.get_violation_report()
        assert "total_violations" in report
        assert report["total_violations"] >= 1

    def test_get_violation_history(self):
        svc = ConstitutionalInvariantsService()
        violation = create_test_violation()
        svc.save_violation(violation)
        history = svc.get_violation_history(limit=10)
        assert len(history) >= 1

    def test_get_constitutional_invariants_service_singleton(self):
        svc1 = get_constitutional_invariants_service()
        svc2 = get_constitutional_invariants_service()
        assert svc1 is svc2


# ============================================================================
# Tests for Helper Functions
# ============================================================================

class TestHelperFunctions:
    def test_get_validator_for_invariant(self):
        validator = get_validator_for_invariant(InvariantType.DOUBLE_ENTRY_BALANCE)
        assert validator is not None
        assert callable(validator)

        validator = get_validator_for_invariant(InvariantType.ACCOUNTING_EQUATION)
        assert validator is not None
        assert callable(validator)

        validator = get_validator_for_invariant(InvariantType.TIME_MONOTONICITY)
        assert validator is not None

        for inv_type in InvariantType:
            v = get_validator_for_invariant(inv_type)
            assert v is not None, f"No validator for {inv_type}"
