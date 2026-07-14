#!/usr/bin/env python3
"""
test_supreme_law.py - Comprehensive tests for constitution/supreme_law.py
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from constitution.supreme_law import (
    AmendmentRecord,
    Constitution,
    ConstitutionalPrinciple,
    ConstitutionalRule,
    ConstitutionalSeverity,
    ConstitutionalSnapshot,
    ConstitutionalViolationError,
    ConstitutionAmendmentError,
    EmergencyOverride,
    EmergencyOverrideError,
    EmergencyOverrideReason,
    SovereigntyLevel,
    SovereigntyViolationError,
    ViolationRecord,
    get_supreme_law,
)

# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def valid_rule_kwargs():
    now = datetime.now(UTC)
    return {
        "rule_id": uuid4(),
        "principle": ConstitutionalPrinciple.DOUBLE_ENTRY,
        "statement": "Every transaction must have equal debit and credit.",
        "sovereignty": SovereigntyLevel.ABSOLUTE,
        "severity_on_violation": ConstitutionalSeverity.CRITICAL,
        "effective_from": now,
        "created_by": "test_creator",
        "created_at": now,
        "approved_by": ["approver1", "approver2", "approver3"],
        "cryptographic_hash": "",
    }

@pytest.fixture
def valid_rule(valid_rule_kwargs):
    return ConstitutionalRule(**valid_rule_kwargs)

@pytest.fixture
def new_rule_kwargs():
    now = datetime.now(UTC)
    return {
        "rule_id": uuid4(),
        "principle": ConstitutionalPrinciple.CONSERVATISM,
        "statement": "Be conservative in accounting estimates.",
        "sovereignty": SovereigntyLevel.ORDINARY,
        "severity_on_violation": ConstitutionalSeverity.MEDIUM,
        "effective_from": now,
        "created_by": "test_creator",
        "created_at": now,
        "approved_by": ["approver1", "approver2"],
        "cryptographic_hash": "",
    }

@pytest.fixture
def new_rule(new_rule_kwargs):
    return ConstitutionalRule(**new_rule_kwargs)

@pytest.fixture
def valid_amendment_kwargs():
    now = datetime.now(UTC)
    return {
        "amendment_id": uuid4(),
        "previous_version_id": uuid4(),
        "new_version_id": uuid4(),
        "changes_description": "Added double-entry rule",
        "proposed_by": "test_proposer",
        "proposed_at": now,
        "approved_by": ["approver1", "approver2"],
        "approved_at": now,
        "effective_from": now,
        "justification": "Needed for accounting",
        "impact_assessment": "Low impact",
    }

@pytest.fixture
def valid_amendment(valid_amendment_kwargs):
    return AmendmentRecord(**valid_amendment_kwargs)

@pytest.fixture
def valid_override_kwargs():
    now = datetime.now(UTC)
    return {
        "override_id": uuid4(),
        "reason": EmergencyOverrideReason.NATURAL_DISASTER,
        "suspended_principles": {ConstitutionalPrinciple.CONSERVATISM},
        "duration_hours": 2,
        "authorized_by": ["auth1", "auth2"],
        "authorized_at": now,
        "justification_document": "Flood disaster override",
    }

@pytest.fixture
def valid_override(valid_override_kwargs):
    return EmergencyOverride(**valid_override_kwargs)

@pytest.fixture
def valid_violation_kwargs():
    now = datetime.now(UTC)
    return {
        "violation_id": uuid4(),
        "rule_id": uuid4(),
        "principle": ConstitutionalPrinciple.DOUBLE_ENTRY,
        "severity": ConstitutionalSeverity.HIGH,
        "offending_module": "test_module",
        "message": "Debit != Credit",
        "timestamp": now,
        "offending_user": "test_user",
        "offending_command_id": uuid4(),
    }

@pytest.fixture
def valid_violation(valid_violation_kwargs):
    return ViolationRecord(**valid_violation_kwargs)

@pytest.fixture
def constitution():
    return Constitution(version="1.0.0")

@pytest.fixture
def supreme_law():
    law = get_supreme_law()
    law.reset()
    return law


# ============================================================================
# 1. ENUM TESTS
# ============================================================================

class TestEnums:
    def test_constitutional_principle_has_expected_members(self):
        expected = [
            "DOUBLE_ENTRY", "ACCRUAL_BASIS", "GOING_CONCERN", "CONSERVATISM",
            "MATERIALITY", "SUBSTANCE_OVER_FORM", "IMMUTABILITY",
            "AUDIT_TRAIL_COMPLETENESS", "TIME_IRREVERSIBILITY", "CAUSALITY_CHAIN",
            "SEGREGATION_OF_DUTIES", "DUAL_APPROVAL", "NON_REPUDIATION",
            "ZERO_TRUST", "LEGAL_SUPREMACY", "REGULATORY_COMPLIANCE",
            "TAX_OBEDIENCE", "PERIOD_CLOSURE", "GL_SUPREMACY", "NO_RETROACTIVE_POLICY"
        ]
        assert set(expected) == {m.name for m in ConstitutionalPrinciple}

    def test_constitutional_severity_has_expected_members(self):
        expected = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
        assert set(expected) == {m.name for m in ConstitutionalSeverity}

    def test_sovereignty_level_has_expected_members(self):
        expected = ["ABSOLUTE", "ORDINARY", "DEFAULT", "SUGGESTION"]
        assert set(expected) == {m.name for m in SovereigntyLevel}

    def test_emergency_override_reason_has_expected_members(self):
        expected = ["NATURAL_DISASTER", "REGULATORY_MANDATE", "COURT_ORDER",
                    "SYSTEM_MIGRATION", "AUDIT_CORRECTION", "TECHNICAL_EMERGENCY"]
        assert set(expected) == {m.name for m in EmergencyOverrideReason}


# ============================================================================
# 2. EXCEPTION TESTS
# ============================================================================

class TestExceptions:
    def test_constitutional_violation_error(self):
        exc = ConstitutionalViolationError(
            principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
            message="Debit mismatch",
            severity=ConstitutionalSeverity.CRITICAL,
            offending_module="test",
            violation_id=uuid4()
        )
        assert exc.principle == ConstitutionalPrinciple.DOUBLE_ENTRY
        assert "Debit mismatch" in str(exc)
        assert exc.severity == ConstitutionalSeverity.CRITICAL

    def test_constitution_amendment_error(self):
        exc = ConstitutionAmendmentError("Custom message")
        assert isinstance(exc, Exception)
        assert str(exc) == "Custom message"

    def test_sovereignty_violation_error(self):
        exc = SovereigntyViolationError("Sovereignty violation")
        assert isinstance(exc, Exception)

    def test_emergency_override_error(self):
        exc = EmergencyOverrideError("Override error")
        assert isinstance(exc, Exception)


# ============================================================================
# 3. CONSTITUTIONAL RULE TESTS
# ============================================================================

class TestConstitutionalRule:
    def test_construction_valid(self, valid_rule):
        assert valid_rule.rule_id is not None
        assert valid_rule.principle == ConstitutionalPrinciple.DOUBLE_ENTRY
        assert valid_rule.sovereignty == SovereigntyLevel.ABSOLUTE
        assert len(valid_rule.approved_by) == 3
        assert valid_rule.cryptographic_hash != ""
        assert valid_rule.version == 1

    def test_validation_fails_for_absolute_with_less_than_3_approvers(self):
        kwargs = {
            "rule_id": uuid4(),
            "principle": ConstitutionalPrinciple.DOUBLE_ENTRY,
            "statement": "test",
            "sovereignty": SovereigntyLevel.ABSOLUTE,
            "severity_on_violation": ConstitutionalSeverity.CRITICAL,
            "effective_from": datetime.now(UTC),
            "created_by": "creator",
            "created_at": datetime.now(UTC),
            "approved_by": ["only_one"],
        }
        with pytest.raises(ValueError, match="Absolute sovereignty requires at least 3 approvers"):
            ConstitutionalRule(**kwargs)

    def test_validation_fails_for_ordinary_with_less_than_2_approvers(self):
        kwargs = {
            "rule_id": uuid4(),
            "principle": ConstitutionalPrinciple.DOUBLE_ENTRY,
            "statement": "test",
            "sovereignty": SovereigntyLevel.ORDINARY,
            "severity_on_violation": ConstitutionalSeverity.CRITICAL,
            "effective_from": datetime.now(UTC),
            "created_by": "creator",
            "created_at": datetime.now(UTC),
            "approved_by": ["only_one"],
        }
        with pytest.raises(ValueError, match="Ordinary sovereignty requires at least 2 approvers"):
            ConstitutionalRule(**kwargs)

    def test_compute_hash(self, valid_rule):
        hash1 = valid_rule.compute_hash()
        assert len(hash1) == 64

        rule2 = valid_rule.update("updater", statement="Different statement")
        assert rule2.cryptographic_hash == hash1

        hash2 = rule2.compute_hash()
        assert hash1 != hash2

        rule2.cryptographic_hash = hash2
        assert rule2.cryptographic_hash == hash2

    def test_to_dict_and_from_dict(self, valid_rule):
        data = valid_rule.to_dict()
        assert "rule_id" in data
        assert data["principle"] == "DOUBLE_ENTRY"
        assert data["sovereignty"] == "ABSOLUTE"
        restored = ConstitutionalRule.from_dict(data)
        assert restored.rule_id == valid_rule.rule_id
        assert restored.principle == valid_rule.principle
        assert restored.statement == valid_rule.statement

    def test_clone_creates_new_id(self, valid_rule):
        cloned = valid_rule.clone()
        assert cloned.rule_id != valid_rule.rule_id
        assert cloned.principle == valid_rule.principle
        assert cloned.version == 1

    def test_update_increments_version(self, valid_rule):
        updated = valid_rule.update("updater", statement="New statement")
        assert updated.version == valid_rule.version + 1
        assert updated.statement == "New statement"
        trail = updated.audit_trail()
        assert any(e["action"] == "UPDATE" for e in trail)

    def test_delete_sets_deleted_at_and_effective_until(self, valid_rule):
        deleted = valid_rule.delete("deleter", reason="Obsolete")
        assert deleted.deleted_at is not None
        assert deleted.effective_until is not None
        assert deleted.version == valid_rule.version + 1
        trail = deleted.audit_trail()
        assert any(e["action"] == "DELETE" for e in trail)

    def test_restore_clears_deleted_fields(self, valid_rule):
        deleted = valid_rule.delete("deleter")
        restored = deleted.restore("restorer")
        assert restored.deleted_at is None
        assert restored.deleted_by is None
        assert restored.effective_until is None
        assert restored.version == deleted.version + 1

    def test_is_active(self, valid_rule):
        now = datetime.now(UTC)
        assert valid_rule.is_active(now) is True
        future_rule = valid_rule.update("updater", effective_from=now + timedelta(days=1))
        assert future_rule.is_active(now) is False
        expired_rule = valid_rule.update("updater", effective_until=now - timedelta(days=1))
        assert expired_rule.is_active(now) is False

    def test_validate_returns_valid_if_ok(self, valid_rule):
        result = valid_rule.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_returns_errors_if_hash_mismatch(self, valid_rule):
        rule = valid_rule
        rule.cryptographic_hash = "broken_hash"
        result = rule.validate()
        assert result["is_valid"] is False
        assert any("Hash mismatch" in e for e in result["errors"])

    def test_touch_increments_version_and_audit(self, valid_rule):
        touched = valid_rule.touch("toucher")
        assert touched.version == valid_rule.version + 1
        trail = touched.audit_trail()
        assert any(e["action"] == "TOUCH" and e["performed_by"] == "toucher" for e in trail)


# ============================================================================
# 4. AMENDMENT RECORD TESTS
# ============================================================================

class TestAmendmentRecord:
    def test_construction_valid(self, valid_amendment):
        assert valid_amendment.amendment_id is not None
        assert len(valid_amendment.approved_by) >= 2
        assert valid_amendment.version == 1

    def test_validation_fails_with_less_than_2_approvals(self):
        kwargs = {
            "amendment_id": uuid4(),
            "previous_version_id": uuid4(),
            "new_version_id": uuid4(),
            "changes_description": "test",
            "proposed_by": "proposer",
            "proposed_at": datetime.now(UTC),
            "approved_by": ["only_one"],
            "approved_at": datetime.now(UTC),
            "effective_from": datetime.now(UTC),
            "justification": "test",
            "impact_assessment": "test",
        }
        with pytest.raises(ValueError, match="Amendment requires at least 2 approvals"):
            AmendmentRecord(**kwargs)

    def test_to_dict_and_from_dict(self, valid_amendment):
        data = valid_amendment.to_dict()
        assert data["amendment_id"] == str(valid_amendment.amendment_id)
        assert "changes_description" in data
        restored = AmendmentRecord.from_dict(data)
        assert restored.amendment_id == valid_amendment.amendment_id
        assert restored.changes_description == valid_amendment.changes_description

    def test_clone_creates_new_id(self, valid_amendment):
        cloned = valid_amendment.clone()
        assert cloned.amendment_id != valid_amendment.amendment_id
        assert cloned.version == 1

    def test_delete_is_allowed(self, valid_amendment):
        deleted = valid_amendment.delete("deleter")
        assert deleted.deleted_at is not None
        assert deleted.deleted_by == "deleter"
        assert deleted.version == valid_amendment.version + 1

    def test_restore_works_after_delete(self, valid_amendment):
        deleted = valid_amendment.delete("deleter")
        restored = deleted.restore("restorer")
        assert restored.deleted_at is None
        assert restored.deleted_by is None

    def test_update_raises_error(self, valid_amendment):
        with pytest.raises(AttributeError, match="immutable"):
            valid_amendment.update("updater", changes_description="new")

    def test_touch_records_audit(self, valid_amendment):
        touched = valid_amendment.touch("toucher")
        trail = touched.audit_trail()
        assert any(e["action"] == "TOUCH" and e["performed_by"] == "toucher" for e in trail)


# ============================================================================
# 5. EMERGENCY OVERRIDE TESTS
# ============================================================================

class TestEmergencyOverride:
    def test_construction_valid(self, valid_override):
        assert valid_override.override_id is not None
        assert len(valid_override.authorized_by) >= 2
        assert valid_override.cryptographic_hash != ""

    def test_validation_fails_duration_exceeds_72_hours(self):
        kwargs = {
            "override_id": uuid4(),
            "reason": EmergencyOverrideReason.NATURAL_DISASTER,
            "suspended_principles": set(),
            "duration_hours": 100,
            "authorized_by": ["a", "b"],
            "authorized_at": datetime.now(UTC),
            "justification_document": "test",
        }
        with pytest.raises(ValueError, match="cannot exceed 72 hours"):
            EmergencyOverride(**kwargs)

    def test_validation_fails_less_than_2_authorizers(self):
        kwargs = {
            "override_id": uuid4(),
            "reason": EmergencyOverrideReason.NATURAL_DISASTER,
            "suspended_principles": set(),
            "duration_hours": 2,
            "authorized_by": ["only_one"],
            "authorized_at": datetime.now(UTC),
            "justification_document": "test",
        }
        with pytest.raises(ValueError, match="at least 2 authorizers"):
            EmergencyOverride(**kwargs)

    def test_compute_hash(self, valid_override):
        h1 = valid_override.compute_hash()
        assert len(h1) == 64

        override2 = EmergencyOverride(
            override_id=uuid4(),
            reason=valid_override.reason,
            suspended_principles=valid_override.suspended_principles.copy(),
            duration_hours=valid_override.duration_hours + 1,
            authorized_by=valid_override.authorized_by.copy(),
            authorized_at=valid_override.authorized_at,
            justification_document=valid_override.justification_document,
        )
        h2 = override2.compute_hash()
        assert h1 != h2

    def test_is_still_valid(self, valid_override):
        assert valid_override.is_still_valid() is True
        expired = EmergencyOverride(
            override_id=uuid4(),
            reason=valid_override.reason,
            suspended_principles=valid_override.suspended_principles.copy(),
            duration_hours=1,
            authorized_by=valid_override.authorized_by.copy(),
            authorized_at=datetime.now(UTC) - timedelta(hours=3),
            justification_document=valid_override.justification_document,
        )
        assert expired.is_still_valid() is False

    def test_to_dict_and_from_dict(self, valid_override):
        data = valid_override.to_dict()
        assert data["override_id"] == str(valid_override.override_id)
        assert data["reason"] == "NATURAL_DISASTER"
        restored = EmergencyOverride.from_dict(data)
        assert restored.override_id == valid_override.override_id
        assert restored.reason == valid_override.reason

    def test_clone_creates_new_id(self, valid_override):
        cloned = valid_override.clone()
        assert cloned.override_id != valid_override.override_id
        assert cloned.reason == valid_override.reason

    def test_delete_works(self, valid_override):
        deleted = valid_override.delete("deleter")
        assert deleted.deleted_at is not None
        assert deleted.deleted_by == "deleter"


# ============================================================================
# 6. VIOLATION RECORD TESTS
# ============================================================================

class TestViolationRecord:
    def test_construction_valid(self, valid_violation):
        assert valid_violation.violation_id is not None
        assert valid_violation.severity == ConstitutionalSeverity.HIGH
        assert valid_violation.version == 1

    def test_acknowledge(self, valid_violation):
        acknowledged = valid_violation.acknowledge("acknowledger")
        assert acknowledged.acknowledged_by == "acknowledger"
        assert acknowledged.acknowledged_at is not None
        assert acknowledged.version == valid_violation.version + 1

    def test_acknowledge_raises_if_already_acknowledged(self, valid_violation):
        acknowledged = valid_violation.acknowledge("first")
        with pytest.raises(ValueError, match="Already acknowledged"):
            acknowledged.acknowledge("second")

    def test_resolve(self, valid_violation):
        resolved = valid_violation.resolve("resolver", "Fixed issue")
        assert resolved.resolved_by == "resolver"
        assert resolved.resolved_at is not None
        assert resolved.resolution_action == "Fixed issue"
        assert resolved.version == valid_violation.version + 1

    def test_resolve_raises_if_already_resolved(self, valid_violation):
        resolved = valid_violation.resolve("resolver", "Fixed")
        with pytest.raises(ValueError, match="Already resolved"):
            resolved.resolve("another", "Again")

    def test_is_resolved(self, valid_violation):
        assert valid_violation.is_resolved() is False
        resolved = valid_violation.resolve("resolver", "Fixed")
        assert resolved.is_resolved() is True

    def test_to_dict_and_from_dict(self, valid_violation):
        data = valid_violation.to_dict()
        assert data["violation_id"] == str(valid_violation.violation_id)
        assert data["principle"] == "DOUBLE_ENTRY"
        restored = ViolationRecord.from_dict(data)
        assert restored.violation_id == valid_violation.violation_id
        assert restored.principle == valid_violation.principle

    def test_clone_creates_new_id(self, valid_violation):
        cloned = valid_violation.clone()
        assert cloned.violation_id != valid_violation.violation_id
        assert cloned.principle == valid_violation.principle

    def test_touch_records_audit(self, valid_violation):
        touched = valid_violation.touch("toucher")
        trail = touched.audit_trail()
        assert any(e["action"] == "TOUCH" and e["performed_by"] == "toucher" for e in trail)


# ============================================================================
# 7. CONSTITUTIONAL SNAPSHOT TESTS
# ============================================================================

class TestConstitutionalSnapshot:
    def test_construction_valid(self, valid_rule, valid_override):
        snapshot = ConstitutionalSnapshot(
            snapshot_id=uuid4(),
            effective_as_of=datetime.now(UTC),
            active_rules=[valid_rule],
            active_overrides=[valid_override],
            version="1.0.0",
            hash_chain_previous="prev_hash",
        )
        assert snapshot.snapshot_id is not None
        assert snapshot.hash_current != ""
        assert len(snapshot.active_rules) == 1
        assert len(snapshot.active_overrides) == 1

    def test_compute_hash(self, valid_rule, valid_override):
        snapshot = ConstitutionalSnapshot(
            snapshot_id=uuid4(),
            effective_as_of=datetime.now(UTC),
            active_rules=[valid_rule],
            active_overrides=[valid_override],
            version="1.0.0",
            hash_chain_previous="prev_hash",
        )
        h1 = snapshot.compute_hash()
        assert len(h1) == 64
        snapshot2 = ConstitutionalSnapshot(
            snapshot_id=uuid4(),
            effective_as_of=datetime.now(UTC),
            active_rules=[valid_rule],
            active_overrides=[],
            version="1.0.0",
            hash_chain_previous="prev_hash",
        )
        assert snapshot2.compute_hash() != h1

    def test_to_dict_and_from_dict(self, valid_rule, valid_override):
        snapshot = ConstitutionalSnapshot(
            snapshot_id=uuid4(),
            effective_as_of=datetime.now(UTC),
            active_rules=[valid_rule],
            active_overrides=[valid_override],
            version="1.0.0",
            hash_chain_previous="prev_hash",
        )
        data = snapshot.to_dict()
        assert "snapshot_id" in data
        assert data["active_rules_count"] == 1
        restored = ConstitutionalSnapshot.from_dict({
            "snapshot_id": str(snapshot.snapshot_id),
            "effective_as_of": snapshot.effective_as_of.isoformat(),
            "active_rules": [valid_rule.to_dict()],
            "active_overrides": [valid_override.to_dict()],
            "version": "1.0.0",
            "hash_chain_previous": "prev_hash",
            "hash_current": snapshot.hash_current,
            "version_number": 1,
        })
        assert restored.snapshot_id == snapshot.snapshot_id


# ============================================================================
# 8. CONSTITUTION AGGREGATE TESTS (ALL FIXED)
# ============================================================================

class TestConstitution:
    def test_default_rules_loaded(self, constitution):
        rules = constitution.get_all_rules()
        assert len(rules) >= 2
        principles = {r.principle for r in rules}
        assert ConstitutionalPrinciple.DOUBLE_ENTRY in principles
        assert ConstitutionalPrinciple.IMMUTABILITY in principles

    def test_add_rule(self, constitution, new_rule):
        constitution.add_rule(new_rule, "test_authorizer")
        found = constitution.get_rule(new_rule.rule_id)
        assert found is not None
        assert found.principle == ConstitutionalPrinciple.CONSERVATISM
        assert len(constitution.amendments) > 0
        assert len(constitution.snapshots) > 0

    def test_add_duplicate_principle_raises(self, constitution, new_rule):
        constitution.add_rule(new_rule, "authorizer")
        data = new_rule.to_dict()
        data["rule_id"] = str(uuid4())
        data["cryptographic_hash"] = ""
        duplicate = ConstitutionalRule.from_dict(data)
        with pytest.raises(ConstitutionAmendmentError, match="already exists"):
            constitution.add_rule(duplicate, "authorizer")

    def test_modify_rule(self, constitution, new_rule):
        """Modify rule: old rule becomes inactive, new rule added."""
        constitution.add_rule(new_rule, "authorizer")
        data = new_rule.to_dict()
        data["rule_id"] = str(uuid4())
        data["statement"] = "Modified: Be conservative"
        data["cryptographic_hash"] = ""
        modified_rule = ConstitutionalRule.from_dict(data)

        constitution.modify_rule(new_rule.rule_id, modified_rule, "modifier")

        # Old rule should have effective_until set (inactive)
        old = constitution.get_rule(new_rule.rule_id)
        assert old is not None
        assert old.effective_until is not None

        # New rule should exist and be active
        new = constitution.get_rule(modified_rule.rule_id)
        assert new is not None
        assert new.statement == "Modified: Be conservative"
        assert new.is_active() is True

    def test_get_active_rules(self, constitution, new_rule):
        constitution.add_rule(new_rule, "authorizer")
        active = constitution.get_active_rules()
        assert new_rule.rule_id in [r.rule_id for r in active]

    def test_get_active_rules_respects_override(self, constitution, valid_override_kwargs):
        now = datetime.now(UTC)
        override = EmergencyOverride(
            override_id=uuid4(),
            reason=valid_override_kwargs["reason"],
            suspended_principles={ConstitutionalPrinciple.DOUBLE_ENTRY},
            duration_hours=2,
            authorized_by=valid_override_kwargs["authorized_by"],
            authorized_at=now,
            justification_document=valid_override_kwargs["justification_document"],
        )
        constitution.save_override(override)
        active = constitution.get_active_rules()
        assert not any(r.principle == ConstitutionalPrinciple.DOUBLE_ENTRY for r in active)

    def test_check_violation(self, constitution):
        # Use CONSERVATISM which is not CRITICAL
        rule = ConstitutionalRule(
            rule_id=uuid4(),
            principle=ConstitutionalPrinciple.CONSERVATISM,
            statement="Be conservative",
            sovereignty=SovereigntyLevel.ORDINARY,
            severity_on_violation=ConstitutionalSeverity.MEDIUM,
            effective_from=datetime.now(UTC),
            created_by="tester",
            created_at=datetime.now(UTC),
            approved_by=["a", "b"],
            cryptographic_hash="",
        )
        constitution.add_rule(rule, "tester")

        violation = constitution.check_violation(
            principle=ConstitutionalPrinciple.CONSERVATISM,
            offending_module="test",
            message="Not conservative",
            offending_user="user1",
        )
        assert violation.violation_id is not None
        assert violation.principle == ConstitutionalPrinciple.CONSERVATISM
        violations = constitution.get_violations(unresolved_only=True)
        assert any(v.violation_id == violation.violation_id for v in violations)

    def test_check_violation_critical_raises(self, constitution):
        with pytest.raises(ConstitutionalViolationError):
            constitution.check_violation(
                principle=ConstitutionalPrinciple.IMMUTABILITY,
                offending_module="test",
                message="Immutable violation",
            )

    def test_apply_emergency_override(self, constitution):
        override = constitution.apply_emergency_override(
            reason=EmergencyOverrideReason.TECHNICAL_EMERGENCY,
            suspended_principles={ConstitutionalPrinciple.CONSERVATISM},
            duration_hours=2,
            authorized_by=["auth1", "auth2"],
            justification_document="Emergency fix",
        )
        assert override.override_id is not None
        assert override.duration_hours == 2
        assert len(constitution.overrides) > 0

    def test_emergency_override_fails_duration_too_long(self, constitution):
        with pytest.raises(EmergencyOverrideError, match="cannot exceed 72 hours"):
            constitution.apply_emergency_override(
                reason=EmergencyOverrideReason.TECHNICAL_EMERGENCY,
                suspended_principles={ConstitutionalPrinciple.CONSERVATISM},
                duration_hours=100,
                authorized_by=["auth1", "auth2"],
                justification_document="Too long",
            )

    def test_emergency_override_fails_absolute_principle(self, constitution):
        with pytest.raises(EmergencyOverrideError, match="Cannot suspend absolute"):
            constitution.apply_emergency_override(
                reason=EmergencyOverrideReason.TECHNICAL_EMERGENCY,
                suspended_principles={ConstitutionalPrinciple.DOUBLE_ENTRY},
                duration_hours=2,
                authorized_by=["auth1", "auth2"],
                justification_document="Suspending absolute",
            )

    def test_get_snapshot(self, constitution, new_rule):
        constitution.add_rule(new_rule, "authorizer")
        snapshot = constitution.get_snapshot(datetime.now(UTC))
        assert snapshot.snapshot_id is not None
        assert len(snapshot.active_rules) > 0
        assert len(constitution.snapshots) > 0

    def test_verify_integrity(self, constitution):
        result = constitution.verify_integrity()
        assert result["is_valid"] is True
        constitution.get_snapshot(datetime.now(UTC))
        result = constitution.verify_integrity()
        assert result["is_valid"] is True

    def test_get_statistics(self, constitution, new_rule, valid_violation):
        constitution.add_rule(new_rule, "authorizer")
        constitution.save_violation(valid_violation)
        stats = constitution.get_statistics()
        assert stats["total_rules"] >= 3
        assert stats["total_violations"] >= 1
        assert stats["unresolved_violations"] >= 1
        assert "by_severity" in stats

    def test_reset(self, constitution, new_rule):
        constitution.add_rule(new_rule, "authorizer")
        assert len(constitution.get_all_rules()) > 0
        constitution.reset()
        assert len(constitution.get_all_rules()) >= 2
        assert len(constitution.amendments) == 0
        assert len(constitution.violations) == 0


# ============================================================================
# 9. SUPREME LAW SINGLETON TESTS
# ============================================================================

class TestSupremeLaw:
    def test_singleton(self):
        law1 = get_supreme_law()
        law2 = get_supreme_law()
        assert law1 is law2

    def test_reset_clears_state(self, supreme_law):
        rule = ConstitutionalRule(
            rule_id=uuid4(),
            principle=ConstitutionalPrinciple.CONSERVATISM,
            statement="Be conservative",
            sovereignty=SovereigntyLevel.ORDINARY,
            severity_on_violation=ConstitutionalSeverity.MEDIUM,
            effective_from=datetime.now(UTC),
            created_by="tester",
            created_at=datetime.now(UTC),
            approved_by=["a", "b"],
            cryptographic_hash="",
        )
        supreme_law.add_rule(rule, "tester")
        assert len(supreme_law.get_all_rules()) > 0
        supreme_law.reset()
        default_principles = {ConstitutionalPrinciple.DOUBLE_ENTRY, ConstitutionalPrinciple.IMMUTABILITY}
        rules = supreme_law.get_all_rules()
        assert len(rules) >= 2
        assert all(r.principle in default_principles for r in rules)

    def test_enforce_double_entry(self, supreme_law):
        context = {"total_debit": 100, "total_credit": 100}
        result = supreme_law.enforce(ConstitutionalPrinciple.DOUBLE_ENTRY, context, "test_module")
        assert result is True

    def test_enforce_double_entry_violation(self, supreme_law):
        context = {"total_debit": 100, "total_credit": 90}
        with pytest.raises(ConstitutionalViolationError):
            supreme_law.enforce(ConstitutionalPrinciple.DOUBLE_ENTRY, context, "test_module")
        violations = supreme_law.get_violations(unresolved_only=True)
        assert any(v.principle == ConstitutionalPrinciple.DOUBLE_ENTRY for v in violations)

    def test_emergency_override_delegation(self, supreme_law):
        override = supreme_law.emergency_override(
            reason=EmergencyOverrideReason.TECHNICAL_EMERGENCY,
            suspended_principles={ConstitutionalPrinciple.CONSERVATISM},
            duration_hours=2,
            authorized_by=["auth1", "auth2"],
            justification_document="test",
        )
        assert override.override_id is not None
        overrides = supreme_law.get_overrides()
        assert any(o.override_id == override.override_id for o in overrides)

    def test_get_active_principles(self, supreme_law):
        principles = supreme_law.get_active_principles()
        assert ConstitutionalPrinciple.DOUBLE_ENTRY in principles
        assert ConstitutionalPrinciple.IMMUTABILITY in principles

    def test_get_constitution_snapshot(self, supreme_law):
        snapshot = supreme_law.get_constitution_snapshot()
        assert snapshot.snapshot_id is not None

    def test_verify_integrity(self, supreme_law):
        result = supreme_law.verify_integrity()
        assert result["is_valid"] is True

    def test_get_statistics(self, supreme_law):
        stats = supreme_law.get_statistics()
        assert "total_rules" in stats

    def test_save_rule_delegation(self, supreme_law):
        rule = ConstitutionalRule(
            rule_id=uuid4(),
            principle=ConstitutionalPrinciple.CONSERVATISM,
            statement="Be conservative",
            sovereignty=SovereigntyLevel.ORDINARY,
            severity_on_violation=ConstitutionalSeverity.MEDIUM,
            effective_from=datetime.now(UTC),
            created_by="tester",
            created_at=datetime.now(UTC),
            approved_by=["a", "b"],
            cryptographic_hash="",
        )
        supreme_law.save_rule(rule)
        found = supreme_law.get_rule(rule.rule_id)
        assert found is not None
        assert found.principle == ConstitutionalPrinciple.CONSERVATISM

    def test_delete_rule_delegation(self, supreme_law):
        rule = ConstitutionalRule(
            rule_id=uuid4(),
            principle=ConstitutionalPrinciple.CONSERVATISM,
            statement="Be conservative",
            sovereignty=SovereigntyLevel.ORDINARY,
            severity_on_violation=ConstitutionalSeverity.MEDIUM,
            effective_from=datetime.now(UTC),
            created_by="tester",
            created_at=datetime.now(UTC),
            approved_by=["a", "b"],
            cryptographic_hash="",
        )
        supreme_law.save_rule(rule)
        assert supreme_law.delete_rule(rule.rule_id) is True
        assert supreme_law.get_rule(rule.rule_id) is None

    def test_save_violation_delegation(self, supreme_law):
        violation = ViolationRecord(
            violation_id=uuid4(),
            rule_id=uuid4(),
            principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
            severity=ConstitutionalSeverity.HIGH,
            offending_module="test",
            message="test",
            timestamp=datetime.now(UTC),
        )
        supreme_law.save_violation(violation)
        violations = supreme_law.get_violations()
        assert any(v.violation_id == violation.violation_id for v in violations)

    def test_resolve_violation_delegation(self, supreme_law):
        violation = ViolationRecord(
            violation_id=uuid4(),
            rule_id=uuid4(),
            principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
            severity=ConstitutionalSeverity.HIGH,
            offending_module="test",
            message="test",
            timestamp=datetime.now(UTC),
        )
        supreme_law.save_violation(violation)
        resolved = supreme_law.resolve_violation(violation.violation_id, "resolver", "Fixed")
        assert resolved is not None
        assert resolved.resolved_by == "resolver"
        assert resolved.is_resolved() is True


# ============================================================================
# 10. MODULE-LEVEL FUNCTION TESTS
# ============================================================================

def test_get_supreme_law_returns_singleton():
    law1 = get_supreme_law()
    law2 = get_supreme_law()
    assert law1 is law2
