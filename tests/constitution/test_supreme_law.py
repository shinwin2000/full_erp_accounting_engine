#!/usr/bin/env python3
"""
tests/unit/test_supreme_law.py
Test untuk constitution/supreme_law.py
Mencakup: ConstitutionalRule, AmendmentRecord, EmergencyOverride,
ViolationRecord, ConstitutionalSnapshot, Constitution, SupremeLaw
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from constitution.supreme_law import (
    AmendmentRecord,
    Constitution,
    ConstitutionAmendmentError,
    ConstitutionalPrinciple,
    ConstitutionalRule,
    ConstitutionalSeverity,
    ConstitutionalSnapshot,
    ConstitutionalViolationError,
    EmergencyOverride,
    EmergencyOverrideReason,
    SovereigntyLevel,
    SupremeLaw,
    ViolationRecord,
    get_supreme_law,
)


class TestConstitutionalRule:
    def test_create_valid_rule(self):
        """Test creation of valid ConstitutionalRule."""
        now = datetime.now(UTC)
        rule = ConstitutionalRule(
            rule_id=uuid.uuid4(),
            principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
            statement="Every transaction must have equal debit and credit totals.",
            sovereignty=SovereigntyLevel.ABSOLUTE,
            severity_on_violation=ConstitutionalSeverity.CRITICAL,
            effective_from=now,
            created_by="test_user",
            created_at=now,
            approved_by=["approver1", "approver2", "approver3"],
        )
        assert rule.principle == ConstitutionalPrinciple.DOUBLE_ENTRY
        assert rule.sovereignty == SovereigntyLevel.ABSOLUTE
        assert rule.severity_on_violation == ConstitutionalSeverity.CRITICAL
        assert rule.version == 1
        assert rule.cryptographic_hash != ""

    def test_validate_requires_approvers_for_absolute(self):
        """Test validation requires at least 3 approvers for ABSOLUTE."""
        now = datetime.now(UTC)
        with pytest.raises(ValueError, match="at least 3 approvers"):
            ConstitutionalRule(
                rule_id=uuid.uuid4(),
                principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
                statement="test",
                sovereignty=SovereigntyLevel.ABSOLUTE,
                severity_on_violation=ConstitutionalSeverity.CRITICAL,
                effective_from=now,
                created_by="test",
                created_at=now,
                approved_by=["approver1"],  # only 1
            )

    def test_validate_requires_approvers_for_ordinary(self):
        """Test validation requires at least 2 approvers for ORDINARY."""
        now = datetime.now(UTC)
        with pytest.raises(ValueError, match="at least 2 approvers"):
            ConstitutionalRule(
                rule_id=uuid.uuid4(),
                principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
                statement="test",
                sovereignty=SovereigntyLevel.ORDINARY,
                severity_on_violation=ConstitutionalSeverity.HIGH,
                effective_from=now,
                created_by="test",
                created_at=now,
                approved_by=["approver1"],  # only 1
            )

    def test_is_active_handles_effective_dates(self):
        """Test is_active correctly checks effective dates."""
        now = datetime.now(UTC)
        rule = ConstitutionalRule(
            rule_id=uuid.uuid4(),
            principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
            statement="test",
            sovereignty=SovereigntyLevel.ABSOLUTE,
            severity_on_violation=ConstitutionalSeverity.CRITICAL,
            effective_from=now - timedelta(days=1),
            effective_until=now + timedelta(days=1),
            created_by="test",
            created_at=now,
            approved_by=["a", "b", "c"],
        )
        assert rule.is_active() is True
        assert rule.is_active(now - timedelta(days=2)) is False
        assert rule.is_active(now + timedelta(days=2)) is False

    def test_update_creates_new_version(self):
        """Test update creates new instance with incremented version."""
        now = datetime.now(UTC)
        rule = ConstitutionalRule(
            rule_id=uuid.uuid4(),
            principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
            statement="Original",
            sovereignty=SovereigntyLevel.ABSOLUTE,
            severity_on_violation=ConstitutionalSeverity.CRITICAL,
            effective_from=now,
            created_by="test",
            created_at=now,
            approved_by=["a", "b", "c"],
        )
        updated = rule.update("admin", statement="Updated statement")
        assert updated.statement == "Updated statement"
        assert updated.version == rule.version + 1

    def test_delete_marks_deleted(self):
        """Test delete sets deleted_at and effective_until."""
        now = datetime.now(UTC)
        rule = ConstitutionalRule(
            rule_id=uuid.uuid4(),
            principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
            statement="test",
            sovereignty=SovereigntyLevel.ABSOLUTE,
            severity_on_violation=ConstitutionalSeverity.CRITICAL,
            effective_from=now,
            created_by="test",
            created_at=now,
            approved_by=["a", "b", "c"],
        )
        deleted = rule.delete("admin", "Deprecated")
        assert deleted.deleted_at is not None
        assert deleted.deleted_by == "admin"
        assert deleted.effective_until is not None
        assert deleted.is_active() is False

    def test_restore_recovers_deleted_rule(self):
        """Test restore recovers deleted rule."""
        now = datetime.now(UTC)
        rule = ConstitutionalRule(
            rule_id=uuid.uuid4(),
            principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
            statement="test",
            sovereignty=SovereigntyLevel.ABSOLUTE,
            severity_on_violation=ConstitutionalSeverity.CRITICAL,
            effective_from=now,
            created_by="test",
            created_at=now,
            approved_by=["a", "b", "c"],
        )
        deleted = rule.delete("admin", "test")
        restored = deleted.restore("admin")
        assert restored.deleted_at is None
        assert restored.deleted_by is None
        assert restored.effective_until is None

    def test_to_dict_contains_fields(self):
        """Test to_dict returns expected structure."""
        now = datetime.now(UTC)
        rule = ConstitutionalRule(
            rule_id=uuid.uuid4(),
            principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
            statement="test",
            sovereignty=SovereigntyLevel.ABSOLUTE,
            severity_on_violation=ConstitutionalSeverity.CRITICAL,
            effective_from=now,
            created_by="test",
            created_at=now,
            approved_by=["a", "b", "c"],
        )
        d = rule.to_dict()
        assert d["principle"] == "DOUBLE_ENTRY"
        assert d["sovereignty"] == "ABSOLUTE"
        assert d["approved_by"] == ["a", "b", "c"]
        assert "rule_id" in d

    def test_from_dict_reconstructs(self):
        """Test from_dict reconstructs object."""
        now = datetime.now(UTC)
        original = ConstitutionalRule(
            rule_id=uuid.uuid4(),
            principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
            statement="test",
            sovereignty=SovereigntyLevel.ABSOLUTE,
            severity_on_violation=ConstitutionalSeverity.CRITICAL,
            effective_from=now,
            created_by="test",
            created_at=now,
            approved_by=["a", "b", "c"],
        )
        d = original.to_dict()
        reconstructed = ConstitutionalRule.from_dict(d)
        assert reconstructed.principle == original.principle
        assert reconstructed.statement == original.statement
        assert reconstructed.sovereignty == original.sovereignty

    def test_clone_creates_new_id(self):
        """Test clone creates new ID and resets version."""
        now = datetime.now(UTC)
        rule = ConstitutionalRule(
            rule_id=uuid.uuid4(),
            principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
            statement="test",
            sovereignty=SovereigntyLevel.ABSOLUTE,
            severity_on_violation=ConstitutionalSeverity.CRITICAL,
            effective_from=now,
            created_by="test",
            created_at=now,
            approved_by=["a", "b", "c"],
            version=5,
        )
        cloned = rule.clone()
        assert cloned.rule_id != rule.rule_id
        assert cloned.version == 1

    def test_validate_returns_errors(self):
        """Test validate returns errors for invalid state."""
        now = datetime.now(UTC)
        rule = ConstitutionalRule(
            rule_id=uuid.uuid4(),
            principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
            statement="test",
            sovereignty=SovereigntyLevel.ABSOLUTE,
            severity_on_violation=ConstitutionalSeverity.CRITICAL,
            effective_from=now,
            created_by="test",
            created_at=now,
            approved_by=["a", "b", "c"],
        )
        # Force hash mismatch
        object.__setattr__(rule, "cryptographic_hash", "fakehash")
        result = rule.validate()
        assert result["is_valid"] is False
        assert "Hash mismatch" in result["errors"]


class TestAmendmentRecord:
    def test_create_valid_amendment(self):
        """Test creation of valid AmendmentRecord."""
        now = datetime.now(UTC)
        amendment = AmendmentRecord(
            amendment_id=uuid.uuid4(),
            previous_version_id=uuid.uuid4(),
            new_version_id=uuid.uuid4(),
            changes_description="Updated rule",
            proposed_by="admin",
            proposed_at=now,
            approved_by=["approver1", "approver2"],
            approved_at=now,
            effective_from=now + timedelta(days=1),
            justification="Need to update",
            impact_assessment="Low impact",
        )
        assert amendment.proposed_by == "admin"
        assert len(amendment.approved_by) == 2
        assert amendment.version == 1

    def test_validate_requires_approvers(self):
        """Test validation requires at least 2 approvers."""
        now = datetime.now(UTC)
        with pytest.raises(ValueError, match="at least 2 approvals"):
            AmendmentRecord(
                amendment_id=uuid.uuid4(),
                previous_version_id=uuid.uuid4(),
                new_version_id=uuid.uuid4(),
                changes_description="test",
                proposed_by="admin",
                proposed_at=now,
                approved_by=["approver1"],  # only 1
                approved_at=now,
                effective_from=now,
                justification="test",
                impact_assessment="test",
            )

    def test_delete_marks_deleted(self):
        """Test delete marks record as deleted."""
        now = datetime.now(UTC)
        amendment = AmendmentRecord(
            amendment_id=uuid.uuid4(),
            previous_version_id=uuid.uuid4(),
            new_version_id=uuid.uuid4(),
            changes_description="test",
            proposed_by="admin",
            proposed_at=now,
            approved_by=["a", "b"],
            approved_at=now,
            effective_from=now,
            justification="test",
            impact_assessment="test",
        )
        deleted = amendment.delete("admin", "test")
        assert deleted.deleted_at is not None
        assert deleted.deleted_by == "admin"


class TestEmergencyOverride:
    def test_create_valid_override(self):
        """Test creation of valid EmergencyOverride."""
        now = datetime.now(UTC)
        override = EmergencyOverride(
            override_id=uuid.uuid4(),
            reason=EmergencyOverrideReason.NATURAL_DISASTER,
            suspended_principles={ConstitutionalPrinciple.DOUBLE_ENTRY},
            duration_hours=24,
            authorized_by=["authorizer1", "authorizer2"],
            authorized_at=now,
            justification_document="Justification doc",
        )
        assert override.reason == EmergencyOverrideReason.NATURAL_DISASTER
        assert override.duration_hours == 24
        assert len(override.authorized_by) == 2
        assert override.cryptographic_hash != ""

    def test_validate_duration_limit(self):
        """Test validation rejects duration > 72 hours."""
        with pytest.raises(ValueError, match="cannot exceed 72 hours"):
            EmergencyOverride(
                override_id=uuid.uuid4(),
                reason=EmergencyOverrideReason.NATURAL_DISASTER,
                suspended_principles=set(),
                duration_hours=100,
                authorized_by=["a", "b"],
                authorized_at=datetime.now(UTC),
                justification_document="test",
            )

    def test_is_still_valid_handles_expiry(self):
        """Test is_still_valid checks duration expiry."""
        now = datetime.now(UTC)
        override = EmergencyOverride(
            override_id=uuid.uuid4(),
            reason=EmergencyOverrideReason.NATURAL_DISASTER,
            suspended_principles=set(),
            duration_hours=24,
            authorized_by=["a", "b"],
            authorized_at=now - timedelta(hours=12),
            justification_document="test",
        )
        assert override.is_still_valid() is True

        expired = EmergencyOverride(
            override_id=uuid.uuid4(),
            reason=EmergencyOverrideReason.NATURAL_DISASTER,
            suspended_principles=set(),
            duration_hours=24,
            authorized_by=["a", "b"],
            authorized_at=now - timedelta(hours=48),
            justification_document="test",
        )
        assert expired.is_still_valid() is False


class TestViolationRecord:
    def test_create_valid_violation(self):
        """Test creation of valid ViolationRecord."""
        now = datetime.now(UTC)
        violation = ViolationRecord(
            violation_id=uuid.uuid4(),
            rule_id=uuid.uuid4(),
            principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
            severity=ConstitutionalSeverity.HIGH,
            offending_module="journal",
            message="Debit != Credit",
            timestamp=now,
            offending_user="user123",
        )
        assert violation.principle == ConstitutionalPrinciple.DOUBLE_ENTRY
        assert violation.severity == ConstitutionalSeverity.HIGH
        assert violation.offending_module == "journal"
        assert violation.is_resolved() is False

    def test_acknowledge_marks_acknowledged(self):
        """Test acknowledge marks violation as acknowledged."""
        now = datetime.now(UTC)
        violation = ViolationRecord(
            violation_id=uuid.uuid4(),
            rule_id=uuid.uuid4(),
            principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
            severity=ConstitutionalSeverity.HIGH,
            offending_module="journal",
            message="test",
            timestamp=now,
        )
        acknowledged = violation.acknowledge("admin")
        assert acknowledged.acknowledged_by == "admin"
        assert acknowledged.acknowledged_at is not None
        assert acknowledged.version == 2

    def test_resolve_marks_resolved(self):
        """Test resolve marks violation as resolved."""
        now = datetime.now(UTC)
        violation = ViolationRecord(
            violation_id=uuid.uuid4(),
            rule_id=uuid.uuid4(),
            principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
            severity=ConstitutionalSeverity.HIGH,
            offending_module="journal",
            message="test",
            timestamp=now,
        )
        resolved = violation.resolve("admin", "Corrected journal")
        assert resolved.resolved_by == "admin"
        assert resolved.resolved_at is not None
        assert resolved.resolution_action == "Corrected journal"
        assert resolved.is_resolved() is True


class TestConstitutionalSnapshot:
    def test_create_valid_snapshot(self):
        """Test creation of valid ConstitutionalSnapshot."""
        now = datetime.now(UTC)
        rule = ConstitutionalRule(
            rule_id=uuid.uuid4(),
            principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
            statement="test",
            sovereignty=SovereigntyLevel.ABSOLUTE,
            severity_on_violation=ConstitutionalSeverity.CRITICAL,
            effective_from=now,
            created_by="test",
            created_at=now,
            approved_by=["a", "b", "c"],
        )
        snapshot = ConstitutionalSnapshot(
            snapshot_id=uuid.uuid4(),
            effective_as_of=now,
            active_rules=[rule],
            active_overrides=[],
            version="1.0.0",
            hash_chain_previous=None,
        )
        assert snapshot.hash_current != ""
        assert len(snapshot.active_rules) == 1

    def test_compute_hash_includes_chain(self):
        """Test compute_hash includes previous hash in chain."""
        now = datetime.now(UTC)
        rule = ConstitutionalRule(
            rule_id=uuid.uuid4(),
            principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
            statement="test",
            sovereignty=SovereigntyLevel.ABSOLUTE,
            severity_on_violation=ConstitutionalSeverity.CRITICAL,
            effective_from=now,
            created_by="test",
            created_at=now,
            approved_by=["a", "b", "c"],
        )
        snap1 = ConstitutionalSnapshot(
            snapshot_id=uuid.uuid4(),
            effective_as_of=now,
            active_rules=[rule],
            active_overrides=[],
            version="1.0.0",
            hash_chain_previous=None,
        )
        snap2 = ConstitutionalSnapshot(
            snapshot_id=uuid.uuid4(),
            effective_as_of=now + timedelta(days=1),
            active_rules=[rule],
            active_overrides=[],
            version="1.0.1",
            hash_chain_previous=snap1.hash_current,
        )
        assert snap2.hash_chain_previous == snap1.hash_current
        assert snap2.hash_current != snap1.hash_current


class TestConstitution:
    def test_initialization_loads_default_rules(self):
        """Test Constitution loads default rules on init."""
        constitution = Constitution(version="1.0.0")
        assert len(constitution.rules) > 0
        assert len(constitution.snapshots) > 0
        assert constitution.version == "1.0.0"

    def test_add_rule_success(self):
        """Test add_rule adds rule to constitution."""
        constitution = Constitution(version="1.0.0")
        now = datetime.now(UTC)
        rule = ConstitutionalRule(
            rule_id=uuid.uuid4(),
            principle=ConstitutionalPrinciple.IMMUTABILITY,
            statement="test rule",
            sovereignty=SovereigntyLevel.ABSOLUTE,
            severity_on_violation=ConstitutionalSeverity.CRITICAL,
            effective_from=now,
            created_by="test",
            created_at=now,
            approved_by=["a", "b", "c"],
        )
        constitution.add_rule(rule, "test")
        assert rule.rule_id in constitution.rules

    def test_add_rule_duplicate_principle_raises(self):
        """Test add_rule raises if rule for principle already exists."""
        constitution = Constitution(version="1.0.0")
        now = datetime.now(UTC)
        rule1 = ConstitutionalRule(
            rule_id=uuid.uuid4(),
            principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
            statement="test1",
            sovereignty=SovereigntyLevel.ABSOLUTE,
            severity_on_violation=ConstitutionalSeverity.CRITICAL,
            effective_from=now,
            created_by="test",
            created_at=now,
            approved_by=["a", "b", "c"],
        )
        constitution.add_rule(rule1, "test")
        rule2 = ConstitutionalRule(
            rule_id=uuid.uuid4(),
            principle=ConstitutionalPrinciple.DOUBLE_ENTRY,  # same
            statement="test2",
            sovereignty=SovereigntyLevel.ABSOLUTE,
            severity_on_violation=ConstitutionalSeverity.CRITICAL,
            effective_from=now,
            created_by="test",
            created_at=now,
            approved_by=["a", "b", "c"],
        )
        with pytest.raises(ConstitutionAmendmentError, match="already exists"):
            constitution.add_rule(rule2, "test")

    def test_get_active_rules_handles_override(self):
        """Test get_active_rules excludes suspended principles."""
        constitution = Constitution(version="1.0.0")
        now = datetime.now(UTC)
        # Add an override that suspends DOUBLE_ENTRY
        override = EmergencyOverride(
            override_id=uuid.uuid4(),
            reason=EmergencyOverrideReason.NATURAL_DISASTER,
            suspended_principles={ConstitutionalPrinciple.DOUBLE_ENTRY},
            duration_hours=24,
            authorized_by=["a", "b"],
            authorized_at=now - timedelta(hours=1),
            justification_document="test",
        )
        constitution.overrides.append(override)
        active = constitution.get_active_rules()
        # DOUBLE_ENTRY rules should be excluded
        for rule in active:
            assert rule.principle != ConstitutionalPrinciple.DOUBLE_ENTRY

    def test_check_violation_raises_for_critical(self):
        """Test check_violation raises for CRITICAL severity."""
        constitution = Constitution(version="1.0.0")
        # Find a rule with CRITICAL severity
        rule = next(
            (r for r in constitution.rules.values()
             if r.severity_on_violation == ConstitutionalSeverity.CRITICAL),
            None
        )
        if rule:
            with pytest.raises(ConstitutionalViolationError):
                constitution.check_violation(
                    rule.principle,
                    "test_module",
                    "Violation message",
                    "user1",
                    uuid.uuid4(),
                )

    def test_apply_emergency_override_success(self):
        """Test apply_emergency_override creates override."""
        constitution = Constitution(version="1.0.0")
        override = constitution.apply_emergency_override(
            reason=EmergencyOverrideReason.NATURAL_DISASTER,
            suspended_principles=set(),
            duration_hours=24,
            authorized_by=["a", "b"],
            justification_document="test",
        )
        assert override.override_id is not None
        assert override.duration_hours == 24
        assert len(constitution.overrides) > 0

    def test_apply_emergency_override_cannot_suspend_absolute(self):
        """Test cannot suspend ABSOLUTE principles."""
        constitution = Constitution(version="1.0.0")
        with pytest.raises(Exception, match="Cannot suspend absolute principles"):
            constitution.apply_emergency_override(
                reason=EmergencyOverrideReason.NATURAL_DISASTER,
                suspended_principles={ConstitutionalPrinciple.DOUBLE_ENTRY},
                duration_hours=24,
                authorized_by=["a", "b"],
                justification_document="test",
            )

    def test_get_snapshot_creates_snapshot(self):
        """Test get_snapshot creates ConstitutionalSnapshot."""
        constitution = Constitution(version="1.0.0")
        now = datetime.now(UTC)
        snapshot = constitution.get_snapshot(now)
        assert snapshot.snapshot_id is not None
        assert snapshot.effective_as_of == now
        assert len(snapshot.active_rules) > 0

    def test_verify_integrity_validates_chain(self):
        """Test verify_integrity validates hash chain."""
        constitution = Constitution(version="1.0.0")
        result = constitution.verify_integrity()
        assert result["is_valid"] is True

    def test_get_statistics_returns_summary(self):
        """Test get_statistics returns summary."""
        constitution = Constitution(version="1.0.0")
        stats = constitution.get_statistics()
        assert "total_rules" in stats
        assert "active_rules" in stats
        assert "total_violations" in stats


class TestSupremeLaw:
    def test_singleton(self):
        """Test SupremeLaw is singleton."""
        law1 = SupremeLaw()
        law2 = SupremeLaw()
        assert law1 is law2

    def test_enforce_double_entry_valid(self):
        """Test enforce passes for valid double entry."""
        law = SupremeLaw()
        result = law.enforce(
            ConstitutionalPrinciple.DOUBLE_ENTRY,
            {"total_debit": 100, "total_credit": 100},
            "test_module",
        )
        assert result is True

    def test_enforce_double_entry_invalid(self):
        """Test enforce creates violation for invalid double entry."""
        law = SupremeLaw()
        with patch.object(law, "check_violation") as mock_check:
            law.enforce(
                ConstitutionalPrinciple.DOUBLE_ENTRY,
                {"total_debit": 100, "total_credit": 80},
                "test_module",
            )
            mock_check.assert_called_once()

    def test_add_rule_delegates_to_constitution(self):
        """Test add_rule delegates to constitution."""
        law = SupremeLaw()
        now = datetime.now(UTC)
        rule = ConstitutionalRule(
            rule_id=uuid.uuid4(),
            principle=ConstitutionalPrinciple.IMMUTABILITY,
            statement="test",
            sovereignty=SovereigntyLevel.ABSOLUTE,
            severity_on_violation=ConstitutionalSeverity.CRITICAL,
            effective_from=now,
            created_by="test",
            created_at=now,
            approved_by=["a", "b", "c"],
        )
        law.add_rule(rule, "test")
        retrieved = law.get_rule(rule.rule_id)
        assert retrieved is not None

    def test_get_active_principles(self):
        """Test get_active_principles returns list of principles."""
        law = SupremeLaw()
        principles = law.get_active_principles()
        assert len(principles) > 0
        assert ConstitutionalPrinciple.DOUBLE_ENTRY in principles

    def test_get_statistics(self):
        """Test get_statistics returns statistics."""
        law = SupremeLaw()
        stats = law.get_statistics()
        assert "total_rules" in stats

    def test_emergency_override_delegates(self):
        """Test emergency_override delegates to constitution."""
        law = SupremeLaw()
        override = law.emergency_override(
            reason=EmergencyOverrideReason.NATURAL_DISASTER,
            suspended_principles=set(),
            duration_hours=24,
            authorized_by=["a", "b"],
            justification_document="test",
        )
        assert override is not None

    def test_get_supreme_law_singleton(self):
        """Test get_supreme_law returns singleton."""
        law1 = get_supreme_law()
        law2 = get_supreme_law()
        assert law1 is law2


class TestSupremeLawIntegration:
    def test_full_workflow(self):
        """Test complete workflow: add rule, check violation, get snapshot."""
        law = SupremeLaw()

        # 1. Add a new rule
        now = datetime.now(UTC)
        rule = ConstitutionalRule(
            rule_id=uuid.uuid4(),
            principle=ConstitutionalPrinciple.MATERIALITY,
            statement="Materiality threshold is 5%",
            sovereignty=SovereigntyLevel.ORDINARY,
            severity_on_violation=ConstitutionalSeverity.MEDIUM,
            effective_from=now,
            created_by="admin",
            created_at=now,
            approved_by=["approver1", "approver2"],
        )
        law.add_rule(rule, "admin")

        # 2. Get active principles (should include MATERIALITY)
        principles = law.get_active_principles()
        assert ConstitutionalPrinciple.MATERIALITY in principles

        # 3. Check a violation (non-critical, shouldn't raise)
        violation = law.check_violation(
            ConstitutionalPrinciple.MATERIALITY,
            "test_module",
            "Materiality threshold exceeded",
            "user1",
            uuid.uuid4(),
        )
        assert violation is not None
        assert violation.principle == ConstitutionalPrinciple.MATERIALITY

        # 4. Get snapshot
        snapshot = law.get_constitution_snapshot()
        assert snapshot is not None
        assert len(snapshot.active_rules) > 0

        # 5. Verify integrity
        integrity = law.verify_integrity()
        assert integrity["is_valid"] is True

# ============================================================================
# HELPER FUNCTIONS UNTUK TEST
# ============================================================================

def create_test_rule() -> ConstitutionalRule:
    now = datetime.now(UTC)
    return ConstitutionalRule(
        rule_id=uuid.uuid4(),
        principle=ConstitutionalPrinciple.IMMUTABILITY,
        statement="Test rule",
        sovereignty=SovereigntyLevel.ORDINARY,
        severity_on_violation=ConstitutionalSeverity.MEDIUM,
        effective_from=now,
        created_by="tester",
        created_at=now,
        approved_by=["a", "b"],
        cryptographic_hash="",
    )

def create_test_amendment() -> AmendmentRecord:
    now = datetime.now(UTC)
    return AmendmentRecord(
        amendment_id=uuid.uuid4(),
        previous_version_id=uuid.uuid4(),
        new_version_id=uuid.uuid4(),
        changes_description="Test amendment",
        proposed_by="tester",
        proposed_at=now,
        approved_by=["a", "b"],
        approved_at=now,
        effective_from=now + timedelta(days=1),
        justification="Justification",
        impact_assessment="Low",
    )

def create_test_override() -> EmergencyOverride:
    now = datetime.now(UTC)
    return EmergencyOverride(
        override_id=uuid.uuid4(),
        reason=EmergencyOverrideReason.NATURAL_DISASTER,
        suspended_principles={ConstitutionalPrinciple.DOUBLE_ENTRY},
        duration_hours=24,
        authorized_by=["a", "b"],
        authorized_at=now,
        justification_document="Test doc",
    )

def create_test_violation() -> ViolationRecord:
    now = datetime.now(UTC)
    return ViolationRecord(
        violation_id=uuid.uuid4(),
        rule_id=uuid.uuid4(),
        principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
        severity=ConstitutionalSeverity.HIGH,
        offending_module="test",
        message="Test violation",
        timestamp=now,
    )

def create_test_snapshot() -> ConstitutionalSnapshot:
    now = datetime.now(UTC)
    rule = create_test_rule()
    return ConstitutionalSnapshot(
        snapshot_id=uuid.uuid4(),
        effective_as_of=now,
        active_rules=[rule],
        active_overrides=[],
        version="1.0",
        hash_chain_previous=None,
    )


# ============================================================================
# TEST LIFECYCLE METHODS
# ============================================================================

class TestConstitutionalRuleLifecycle:
    def test_create_returns_self(self):
        rule = create_test_rule()
        result = rule.create("admin")
        assert result is rule

    def test_activate_returns_self(self):
        rule = create_test_rule()
        result = rule.activate("admin")
        assert result is rule

    def test_deactivate_sets_effective_until(self):
        rule = create_test_rule()
        result = rule.deactivate("admin", "test")
        assert result.effective_until is not None
        assert result.version == rule.version + 1

    def test_lock_returns_self(self):
        rule = create_test_rule()
        result = rule.lock("admin", "test")
        assert result is rule

    def test_unlock_returns_self(self):
        rule = create_test_rule()
        result = rule.unlock("admin")
        assert result is rule


class TestAmendmentRecordLifecycle:
    def test_create_returns_self(self):
        record = create_test_amendment()
        result = record.create("admin")
        assert result is record

    def test_activate_returns_self(self):
        record = create_test_amendment()
        result = record.activate("admin")
        assert result is record

    def test_deactivate_returns_self(self):
        record = create_test_amendment()
        result = record.deactivate("admin")
        assert result is record

    def test_lock_returns_self(self):
        record = create_test_amendment()
        result = record.lock("admin", "test")
        assert result is record

    def test_unlock_returns_self(self):
        record = create_test_amendment()
        result = record.unlock("admin")
        assert result is record

    def test_validate_returns_valid(self):
        record = create_test_amendment()
        result = record.validate()
        assert result["is_valid"] is True

    def test_compute_signature_content(self):
        record = create_test_amendment()
        sig = record.compute_signature_content()
        assert "|" in sig
        assert str(record.amendment_id) in sig

    def test_verify_signature_returns_true(self):
        record = create_test_amendment()
        assert record.verify_signature({}) is True


class TestEmergencyOverrideLifecycle:
    def test_create_returns_self(self):
        override = create_test_override()
        result = override.create("admin")
        assert result is override

    def test_activate_returns_self(self):
        override = create_test_override()
        result = override.activate("admin")
        assert result is override

    def test_deactivate_returns_self(self):
        override = create_test_override()
        result = override.deactivate("admin")
        assert result is override

    def test_lock_returns_self(self):
        override = create_test_override()
        result = override.lock("admin", "test")
        assert result is override

    def test_unlock_returns_self(self):
        override = create_test_override()
        result = override.unlock("admin")
        assert result is override

    def test_validate_returns_valid(self):
        override = create_test_override()
        result = override.validate()
        assert result["is_valid"] is True


class TestViolationRecordLifecycle:
    def test_create_returns_self(self):
        violation = create_test_violation()
        result = violation.create("admin")
        assert result is violation

    def test_activate_returns_self(self):
        violation = create_test_violation()
        result = violation.activate("admin")
        assert result is violation

    def test_deactivate_returns_self(self):
        violation = create_test_violation()
        result = violation.deactivate("admin")
        assert result is violation

    def test_lock_returns_self(self):
        violation = create_test_violation()
        result = violation.lock("admin", "test")
        assert result is violation

    def test_unlock_returns_self(self):
        violation = create_test_violation()
        result = violation.unlock("admin")
        assert result is violation

    def test_validate_returns_valid(self):
        violation = create_test_violation()
        result = violation.validate()
        assert result["is_valid"] is True


class TestConstitutionalSnapshotLifecycle:
    def test_create_returns_self(self):
        snapshot = create_test_snapshot()
        result = snapshot.create("admin")
        assert result is snapshot

    def test_activate_returns_self(self):
        snapshot = create_test_snapshot()
        result = snapshot.activate("admin")
        assert result is snapshot

    def test_deactivate_returns_self(self):
        snapshot = create_test_snapshot()
        result = snapshot.deactivate("admin")
        assert result is snapshot

    def test_lock_returns_self(self):
        snapshot = create_test_snapshot()
        result = snapshot.lock("admin", "test")
        assert result is snapshot

    def test_unlock_returns_self(self):
        snapshot = create_test_snapshot()
        result = snapshot.unlock("admin")
        assert result is snapshot

    def test_validate_returns_valid(self):
        snapshot = create_test_snapshot()
        result = snapshot.validate()
        assert result["is_valid"] is True


# ============================================================================
# TEST CONSTITUTION REPOSITORY METHODS
# ============================================================================

class TestConstitutionRepositoryMethods:
    def test_save_rule_and_get_rule(self):
        constitution = Constitution(version="1.0")
        rule = create_test_rule()
        constitution.save_rule(rule)
        retrieved = constitution.get_rule(rule.rule_id)
        assert retrieved is not None
        assert retrieved.rule_id == rule.rule_id

    def test_get_all_rules(self):
        constitution = Constitution(version="1.0")
        rules = constitution.get_all_rules()
        assert len(rules) > 0

    def test_delete_rule(self):
        constitution = Constitution(version="1.0")
        rule = create_test_rule()
        constitution.save_rule(rule)
        result = constitution.delete_rule(rule.rule_id)
        assert result is True
        assert constitution.get_rule(rule.rule_id) is None

    def test_save_amendment_and_get_amendments(self):
        constitution = Constitution(version="1.0")
        amendment = create_test_amendment()
        constitution.save_amendment(amendment)
        amendments = constitution.get_amendments()
        assert len(amendments) >= 1

    def test_delete_amendment(self):
        constitution = Constitution(version="1.0")
        amendment = create_test_amendment()
        constitution.save_amendment(amendment)
        result = constitution.delete_amendment(amendment.amendment_id)
        assert result is True

    def test_save_override_and_get_overrides(self):
        constitution = Constitution(version="1.0")
        override = create_test_override()
        constitution.save_override(override)
        overrides = constitution.get_overrides()
        assert len(overrides) >= 1

    def test_delete_override(self):
        constitution = Constitution(version="1.0")
        override = create_test_override()
        constitution.save_override(override)
        result = constitution.delete_override(override.override_id)
        assert result is True

    def test_save_violation_and_get_violations(self):
        constitution = Constitution(version="1.0")
        violation = create_test_violation()
        constitution.save_violation(violation)
        violations = constitution.get_violations()
        assert len(violations) >= 1

    def test_resolve_violation(self):
        constitution = Constitution(version="1.0")
        violation = create_test_violation()
        constitution.save_violation(violation)
        resolved = constitution.resolve_violation(violation.violation_id, "admin", "action")
        assert resolved is not None
        assert resolved.is_resolved() is True

    def test_save_snapshot_and_get_snapshots(self):
        constitution = Constitution(version="1.0")
        snapshot = create_test_snapshot()
        constitution.save_snapshot(snapshot)
        snapshots = constitution.get_snapshots()
        assert len(snapshots) >= 1


# ============================================================================
# TEST SUPREME LAW DELEGATION METHODS
# ============================================================================

class TestSupremeLawDelegation:
    def test_save_rule(self):
        law = SupremeLaw()
        rule = create_test_rule()
        law.save_rule(rule)
        retrieved = law.get_rule(rule.rule_id)
        assert retrieved is not None

    def test_delete_rule(self):
        law = SupremeLaw()
        rule = create_test_rule()
        law.save_rule(rule)
        result = law.delete_rule(rule.rule_id)
        assert result is True

    def test_save_amendment(self):
        law = SupremeLaw()
        amendment = create_test_amendment()
        law.save_amendment(amendment)
        amendments = law.get_amendments()
        assert len(amendments) >= 1

    def test_delete_amendment(self):
        law = SupremeLaw()
        amendment = create_test_amendment()
        law.save_amendment(amendment)
        result = law.delete_amendment(amendment.amendment_id)
        assert result is True

    def test_save_override(self):
        law = SupremeLaw()
        override = create_test_override()
        law.save_override(override)
        overrides = law.get_overrides()
        assert len(overrides) >= 1

    def test_delete_override(self):
        law = SupremeLaw()
        override = create_test_override()
        law.save_override(override)
        result = law.delete_override(override.override_id)
        assert result is True

    def test_save_violation(self):
        law = SupremeLaw()
        violation = create_test_violation()
        law.save_violation(violation)
        violations = law.get_violations()
        assert len(violations) >= 1

    def test_resolve_violation(self):
        law = SupremeLaw()
        violation = create_test_violation()
        law.save_violation(violation)
        resolved = law.resolve_violation(violation.violation_id, "admin", "action")
        assert resolved is not None
        assert resolved.is_resolved() is True

    def test_save_snapshot(self):
        law = SupremeLaw()
        snapshot = create_test_snapshot()
        law.save_snapshot(snapshot)
        snapshots = law.get_snapshots()
        assert len(snapshots) >= 1

# ============================================================================
# TEST ADDITIONAL METHODS - TOUCH, SNAPSHOT, VERSION, AUDIT_TRAIL
# ============================================================================

class TestConstitutionalRuleExtraMethods:
    def test_touch_creates_audit_trail(self):
        rule = create_test_rule()
        touched = rule.touch("toucher")
        assert touched.version == rule.version + 1
        trail = touched.audit_trail()
        assert len(trail) >= 1
        assert trail[-1]["action"] == "TOUCH"

    def test_snapshot_returns_dict(self):
        rule = create_test_rule()
        snap = rule.snapshot()
        assert "version" in snap
        assert "rule_id" in snap
        assert "principle" in snap
        assert snap["principle"] == "IMMUTABILITY"

    def test_version_returns_current_version(self):
        rule = create_test_rule()
        assert rule.version == 1
        updated = rule.update("admin", statement="new")
        assert updated.version == 2

    def test_audit_trail_limit(self):
        rule = create_test_rule()
        rule.touch("a")
        rule.touch("b")
        rule.touch("c")
        trail = rule.audit_trail(limit=2)
        assert len(trail) == 2


class TestAmendmentRecordExtraMethods:
    def test_touch_creates_audit_trail(self):
        record = create_test_amendment()
        touched = record.touch("toucher")
        trail = touched.audit_trail()
        assert len(trail) >= 1
        assert trail[-1]["action"] == "TOUCH"

    def test_snapshot_returns_dict(self):
        record = create_test_amendment()
        snap = record.snapshot()
        assert "version" in snap
        assert "amendment_id" in snap

    def test_version_returns_current_version(self):
        record = create_test_amendment()
        assert record.version == 1


class TestEmergencyOverrideExtraMethods:
    def test_touch_creates_audit_trail(self):
        override = create_test_override()
        touched = override.touch("toucher")
        trail = touched.audit_trail()
        assert len(trail) >= 1
        assert trail[-1]["action"] == "TOUCH"

    def test_snapshot_returns_dict(self):
        override = create_test_override()
        snap = override.snapshot()
        assert "version" in snap
        assert "override_id" in snap

    def test_version_returns_current_version(self):
        override = create_test_override()
        assert override.version == 1


class TestViolationRecordExtraMethods:
    def test_touch_creates_audit_trail(self):
        violation = create_test_violation()
        touched = violation.touch("toucher")
        trail = touched.audit_trail()
        assert len(trail) >= 1
        assert trail[-1]["action"] == "TOUCH"

    def test_snapshot_returns_dict(self):
        violation = create_test_violation()
        snap = violation.snapshot()
        assert "version" in snap
        assert "violation_id" in snap

    def test_version_returns_current_version(self):
        violation = create_test_violation()
        assert violation.version == 1


class TestConstitutionalSnapshotExtraMethods:
    def test_touch_creates_audit_trail(self):
        snapshot = create_test_snapshot()
        touched = snapshot.touch("toucher")
        trail = touched.audit_trail()
        assert len(trail) >= 1
        assert trail[-1]["action"] == "TOUCH"

    def test_snapshot_returns_dict(self):
        snapshot = create_test_snapshot()
        snap = snapshot.snapshot()
        assert "version" in snap
        assert "snapshot_id" in snap

    def test_version_returns_current_version(self):
        snapshot = create_test_snapshot()
        assert snapshot.version_number == 1


# ============================================================================
# TEST CONSTITUTION ADDITIONAL METHODS
# ============================================================================

class TestConstitutionExtraMethods:
    def test_modify_rule(self):
        constitution = Constitution(version="1.0")
        rule = create_test_rule()
        constitution.add_rule(rule, "admin")

        now = datetime.now(UTC)
        new_rule = ConstitutionalRule(
            rule_id=uuid.uuid4(),
            principle=rule.principle,
            statement="Modified statement",
            sovereignty=SovereigntyLevel.ORDINARY,
            severity_on_violation=ConstitutionalSeverity.HIGH,
            effective_from=now,
            created_by="admin",
            created_at=now,
            approved_by=["a", "b"],
        )
        constitution.modify_rule(rule.rule_id, new_rule, "admin")
        # Old rule should be inactive
        old = constitution.get_rule(rule.rule_id)
        assert old.is_active() is False
        # New rule should exist
        assert new_rule.rule_id in constitution.rules

    def test_get_active_rules_returns_only_active(self):
        constitution = Constitution(version="1.0")
        now = datetime.now(UTC)
        # Create one active and one inactive rule
        rule1 = ConstitutionalRule(
            rule_id=uuid.uuid4(),
            principle=ConstitutionalPrinciple.IMMUTABILITY,
            statement="Active",
            sovereignty=SovereigntyLevel.ORDINARY,
            severity_on_violation=ConstitutionalSeverity.MEDIUM,
            effective_from=now - timedelta(days=1),
            effective_until=now + timedelta(days=1),
            created_by="tester",
            created_at=now,
            approved_by=["a", "b"],
        )
        rule2 = ConstitutionalRule(
            rule_id=uuid.uuid4(),
            principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
            statement="Inactive",
            sovereignty=SovereigntyLevel.ORDINARY,
            severity_on_violation=ConstitutionalSeverity.MEDIUM,
            effective_from=now - timedelta(days=2),
            effective_until=now - timedelta(days=1),
            created_by="tester",
            created_at=now,
            approved_by=["a", "b"],
        )
        constitution.save_rule(rule1)
        constitution.save_rule(rule2)
        active = constitution.get_active_rules()
        # At least rule1 should be active
        active_ids = {r.rule_id for r in active}
        assert rule1.rule_id in active_ids
        # rule2 might be inactive

    def test_get_violations_with_filters(self):
        constitution = Constitution(version="1.0")
        violation1 = create_test_violation()
        violation2 = create_test_violation()
        violation2.principle = ConstitutionalPrinciple.IMMUTABILITY
        constitution.save_violation(violation1)
        constitution.save_violation(violation2)

        # Filter by principle
        filtered = constitution.get_violations(principle=ConstitutionalPrinciple.DOUBLE_ENTRY)
        assert len(filtered) >= 1
        for v in filtered:
            assert v.principle == ConstitutionalPrinciple.DOUBLE_ENTRY

        # Filter unresolved only
        resolved = violation1.resolve("admin", "action")
        constitution.save_violation(resolved)
        unresolved = constitution.get_violations(unresolved_only=True)
        assert len(unresolved) >= 1

    def test_resolve_violation_not_found(self):
        constitution = Constitution(version="1.0")
        result = constitution.resolve_violation(uuid.uuid4(), "admin", "action")
        assert result is None

    def test_get_snapshots(self):
        constitution = Constitution(version="1.0")
        now = datetime.now(UTC)
        snap1 = constitution.get_snapshot(now)
        snap2 = constitution.get_snapshot(now + timedelta(days=1))
        snapshots = constitution.get_snapshots()
        assert len(snapshots) >= 2

    def test_verify_integrity_broken_chain(self):
        constitution = Constitution(version="1.0")
        now = datetime.now(UTC)
        snap1 = constitution.get_snapshot(now)
        snap2 = constitution.get_snapshot(now + timedelta(days=1))
        # Tamper with chain
        snap2.hash_chain_previous = "tampered"
        result = constitution.verify_integrity()
        assert result["is_valid"] is False
        assert "broken_at_index" in result

    def test_reset_reinitializes(self):
        constitution = Constitution(version="1.0")
        original_count = len(constitution.rules)
        constitution.reset()
        assert len(constitution.rules) == original_count
        assert len(constitution.violations) == 0

    def test_constitution_property(self):
        law = SupremeLaw()
        assert law.constitution is not None


# ============================================================================
# TEST EMERGENCY OVERRIDE ADDITIONAL
# ============================================================================

class TestEmergencyOverrideExtra:
    def test_from_dict(self):
        now = datetime.now(UTC)
        data = {
            "override_id": str(uuid.uuid4()),
            "reason": "NATURAL_DISASTER",
            "suspended_principles": ["DOUBLE_ENTRY"],
            "duration_hours": 24,
            "authorized_by": ["a", "b"],
            "authorized_at": now.isoformat(),
            "justification_document": "doc",
            "version": 1,
        }
        override = EmergencyOverride.from_dict(data)
        assert override.reason == EmergencyOverrideReason.NATURAL_DISASTER
        assert len(override.suspended_principles) == 1
        assert override.duration_hours == 24

    def test_validate_hash_mismatch(self):
        override = create_test_override()
        object.__setattr__(override, "cryptographic_hash", "fake")
        result = override.validate()
        assert result["is_valid"] is False
        assert "Hash mismatch" in result["errors"]


# ============================================================================
# TEST SUPREME LAW EXTRA DELEGATION METHODS
# ============================================================================

class TestSupremeLawExtraDelegation:
    def test_modify_rule_delegates(self):
        law = SupremeLaw()
        now = datetime.now(UTC)
        rule = create_test_rule()
        law.add_rule(rule, "admin")
        new_rule = ConstitutionalRule(
            rule_id=uuid.uuid4(),
            principle=rule.principle,
            statement="Modified",
            sovereignty=SovereigntyLevel.ORDINARY,
            severity_on_violation=ConstitutionalSeverity.HIGH,
            effective_from=now,
            created_by="admin",
            created_at=now,
            approved_by=["a", "b"],
        )
        # This modifies via constitution.modify_rule
        law.constitution.modify_rule(rule.rule_id, new_rule, "admin")
        old = law.get_rule(rule.rule_id)
        assert old.is_active() is False

    def test_get_snapshots_delegates(self):
        law = SupremeLaw()
        snapshots = law.get_snapshots()
        assert len(snapshots) > 0

    def test_get_constitution_snapshot(self):
        law = SupremeLaw()
        snapshot = law.get_constitution_snapshot()
        assert snapshot is not None

    def test_verify_integrity_delegates(self):
        law = SupremeLaw()
        result = law.verify_integrity()
        assert "is_valid" in result

    def test_reset_delegates(self):
        law = SupremeLaw()
        law.reset()
        # Should still have default rules
        assert len(law.constitution.rules) > 0

    def test_emergency_override_integration(self):
        law = SupremeLaw()
        override = law.emergency_override(
            reason=EmergencyOverrideReason.NATURAL_DISASTER,
            suspended_principles=set(),
            duration_hours=12,
            authorized_by=["a", "b"],
            justification_document="test",
        )
        assert override is not None
        assert override.duration_hours == 12

    def test_get_violations_with_filters_delegates(self):
        law = SupremeLaw()
        violation = create_test_violation()
        law.save_violation(violation)
        violations = law.get_violations(principle=ConstitutionalPrinciple.DOUBLE_ENTRY)
        assert len(violations) >= 1

    def test_resolve_violation_delegates(self):
        law = SupremeLaw()
        violation = create_test_violation()
        law.save_violation(violation)
        resolved = law.resolve_violation(violation.violation_id, "admin", "action")
        assert resolved is not None
        assert resolved.is_resolved() is True