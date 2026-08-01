#!/usr/bin/env python3
"""
tests/unit/test_supreme_law.py
Test untuk constitution/supreme_law.py
Mencakup: ConstitutionalRule, AmendmentRecord, EmergencyOverride,
ViolationRecord, ConstitutionalSnapshot, Constitution, SupremeLaw

FIXES:
- Semua datetime.now(UTC) diganti dengan FIXED_NOW.
- Duplikasi struktural dihilangkan dengan parametrize.
- Semua test memiliki assertion yang bermakna.
- Negative path tests untuk semua exception.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

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
    EmergencyOverrideReason,
    SovereigntyLevel,
    SupremeLaw,
    ViolationRecord,
    get_supreme_law,
)

# ============================================================================
# FIXED DATETIME (untuk menghilangkan flaky)
# ============================================================================

FIXED_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
FIXED_PAST = FIXED_NOW - timedelta(days=1)
FIXED_FUTURE = FIXED_NOW + timedelta(days=1)


# ============================================================================
# PATCH DATETIME FIXTURE
# ============================================================================

@pytest.fixture(autouse=True)
def mock_datetime():
    """Mock datetime.now and UTC untuk semua test."""
    with patch("constitution.supreme_law.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.UTC = UTC
        yield mock_dt


# ============================================================================
# HELPER FUNCTIONS (menggunakan FIXED_NOW)
# ============================================================================

def create_test_rule(
    principle: ConstitutionalPrinciple = ConstitutionalPrinciple.IMMUTABILITY,
    sovereignty: SovereigntyLevel = SovereigntyLevel.ORDINARY,
    severity: ConstitutionalSeverity = ConstitutionalSeverity.MEDIUM,
    approved_by: list[str] | None = None,
) -> ConstitutionalRule:
    if approved_by is None:
        approved_by = ["a", "b"] if sovereignty == SovereigntyLevel.ORDINARY else ["a", "b", "c"]
    return ConstitutionalRule(
        rule_id=uuid.uuid4(),
        principle=principle,
        statement="Test rule",
        sovereignty=sovereignty,
        severity_on_violation=severity,
        effective_from=FIXED_NOW,
        effective_until=None,
        created_by="tester",
        created_at=FIXED_NOW,
        approved_by=approved_by,
        cryptographic_hash="",
    )


def create_test_amendment() -> AmendmentRecord:
    return AmendmentRecord(
        amendment_id=uuid.uuid4(),
        previous_version_id=uuid.uuid4(),
        new_version_id=uuid.uuid4(),
        changes_description="Test amendment",
        proposed_by="tester",
        proposed_at=FIXED_NOW,
        approved_by=["a", "b"],
        approved_at=FIXED_NOW,
        effective_from=FIXED_NOW,
        justification="Justification",
        impact_assessment="Low",
    )


def create_test_override(
    suspended_principles: set[ConstitutionalPrinciple] | None = None,
    duration_hours: int = 24,
) -> EmergencyOverride:
    if suspended_principles is None:
        suspended_principles = {ConstitutionalPrinciple.DOUBLE_ENTRY}
    return EmergencyOverride(
        override_id=uuid.uuid4(),
        reason=EmergencyOverrideReason.NATURAL_DISASTER,
        suspended_principles=suspended_principles,
        duration_hours=duration_hours,
        authorized_by=["a", "b"],
        authorized_at=FIXED_NOW - timedelta(hours=1),
        justification_document="Test doc",
    )


def create_test_violation(
    principle: ConstitutionalPrinciple = ConstitutionalPrinciple.DOUBLE_ENTRY,
    severity: ConstitutionalSeverity = ConstitutionalSeverity.HIGH,
) -> ViolationRecord:
    return ViolationRecord(
        violation_id=uuid.uuid4(),
        rule_id=uuid.uuid4(),
        principle=principle,
        severity=severity,
        offending_module="test",
        message="Test violation",
        timestamp=FIXED_NOW,
    )


def create_test_snapshot() -> ConstitutionalSnapshot:
    rule = create_test_rule()
    return ConstitutionalSnapshot(
        snapshot_id=uuid.uuid4(),
        effective_as_of=FIXED_NOW,
        active_rules=[rule],
        active_overrides=[],
        version="1.0",
        hash_chain_previous=None,
    )


# ============================================================================
# TESTS ConstitutionalRule
# ============================================================================

class TestConstitutionalRule:
    def test_create_valid_rule(self):
        rule = create_test_rule()
        assert rule.principle == ConstitutionalPrinciple.IMMUTABILITY
        assert rule.sovereignty == SovereigntyLevel.ORDINARY
        assert rule.severity_on_violation == ConstitutionalSeverity.MEDIUM
        assert rule.version == 1
        assert rule.cryptographic_hash != ""

    def test_validate_requires_approvers_for_absolute(self):
        with pytest.raises(ValueError, match="at least 3 approvers"):
            create_test_rule(
                sovereignty=SovereigntyLevel.ABSOLUTE,
                approved_by=["a", "b"],
            )

    def test_validate_requires_approvers_for_ordinary(self):
        with pytest.raises(ValueError, match="at least 2 approvers"):
            create_test_rule(
                sovereignty=SovereigntyLevel.ORDINARY,
                approved_by=["a"],
            )

    def test_is_active_handles_effective_dates(self):
        rule = create_test_rule()
        rule.effective_from = FIXED_NOW - timedelta(days=1)
        rule.effective_until = FIXED_NOW + timedelta(days=1)
        assert rule.is_active()
        assert not rule.is_active(FIXED_NOW - timedelta(days=2))
        assert not rule.is_active(FIXED_NOW + timedelta(days=2))

    def test_update_creates_new_version(self):
        rule = create_test_rule()
        updated = rule.update("admin", statement="Updated statement")
        assert updated.statement == "Updated statement"
        assert updated.version == rule.version + 1

    def test_delete_marks_deleted(self):
        rule = create_test_rule()
        deleted = rule.delete("admin", "Deprecated")
        assert deleted.deleted_at is not None
        assert deleted.deleted_by == "admin"
        assert deleted.effective_until is not None
        assert not deleted.is_active()

    def test_restore_recovers_deleted_rule(self):
        rule = create_test_rule()
        deleted = rule.delete("admin", "test")
        restored = deleted.restore("admin")
        assert restored.deleted_at is None
        assert restored.deleted_by is None
        assert restored.effective_until is None

    def test_to_dict_contains_fields(self):
        rule = create_test_rule()
        d = rule.to_dict()
        assert d["principle"] == "IMMUTABILITY"
        assert d["sovereignty"] == "ORDINARY"
        assert len(d["approved_by"]) == 2
        assert "rule_id" in d

    def test_from_dict_reconstructs(self):
        original = create_test_rule()
        d = original.to_dict()
        reconstructed = ConstitutionalRule.from_dict(d)
        assert reconstructed.principle == original.principle
        assert reconstructed.statement == original.statement
        assert reconstructed.sovereignty == original.sovereignty

    def test_clone_creates_new_id(self):
        rule = create_test_rule()
        rule.version = 5
        cloned = rule.clone()
        assert cloned.rule_id != rule.rule_id
        assert cloned.version == 1

    def test_validate_returns_errors(self):
        rule = create_test_rule()
        object.__setattr__(rule, "cryptographic_hash", "fakehash")
        result = rule.validate()
        assert not result["is_valid"]
        assert "Hash mismatch" in result["errors"]


# ============================================================================
# TESTS AmendmentRecord
# ============================================================================

class TestAmendmentRecord:
    def test_create_valid_amendment(self):
        amendment = create_test_amendment()
        assert amendment.proposed_by == "tester"
        assert len(amendment.approved_by) == 2
        assert amendment.version == 1

    def test_validate_requires_approvers(self):
        with pytest.raises(ValueError, match="at least 2 approvals"):
            AmendmentRecord(
                amendment_id=uuid.uuid4(),
                previous_version_id=uuid.uuid4(),
                new_version_id=uuid.uuid4(),
                changes_description="test",
                proposed_by="admin",
                proposed_at=FIXED_NOW,
                approved_by=["approver1"],
                approved_at=FIXED_NOW,
                effective_from=FIXED_NOW,
                justification="test",
                impact_assessment="test",
            )

    def test_delete_marks_deleted(self):
        amendment = create_test_amendment()
        deleted = amendment.delete("admin", "test")
        assert deleted.deleted_at is not None
        assert deleted.deleted_by == "admin"


# ============================================================================
# TESTS EmergencyOverride
# ============================================================================

class TestEmergencyOverride:
    def test_create_valid_override(self):
        override = create_test_override()
        assert override.reason == EmergencyOverrideReason.NATURAL_DISASTER
        assert override.duration_hours == 24
        assert len(override.authorized_by) == 2
        assert override.cryptographic_hash != ""

    def test_validate_duration_limit(self):
        with pytest.raises(ValueError, match="cannot exceed 72 hours"):
            EmergencyOverride(
                override_id=uuid.uuid4(),
                reason=EmergencyOverrideReason.NATURAL_DISASTER,
                suspended_principles=set(),
                duration_hours=100,
                authorized_by=["a", "b"],
                authorized_at=FIXED_NOW,
                justification_document="test",
            )

    def test_is_still_valid_handles_expiry(self):
        override = create_test_override(duration_hours=24)
        override.authorized_at = FIXED_NOW - timedelta(hours=12)
        assert override.is_still_valid()

        expired = create_test_override(duration_hours=24)
        expired.authorized_at = FIXED_NOW - timedelta(hours=48)
        assert not expired.is_still_valid()


# ============================================================================
# TESTS ViolationRecord
# ============================================================================

class TestViolationRecord:
    def test_create_valid_violation(self):
        violation = create_test_violation()
        assert violation.principle == ConstitutionalPrinciple.DOUBLE_ENTRY
        assert violation.severity == ConstitutionalSeverity.HIGH
        assert violation.offending_module == "test"
        assert not violation.is_resolved()

    def test_acknowledge_marks_acknowledged(self):
        violation = create_test_violation()
        acknowledged = violation.acknowledge("admin")
        assert acknowledged.acknowledged_by == "admin"
        assert acknowledged.acknowledged_at is not None
        assert acknowledged.version == 2

    def test_resolve_marks_resolved(self):
        violation = create_test_violation()
        resolved = violation.resolve("admin", "Corrected journal")
        assert resolved.resolved_by == "admin"
        assert resolved.resolved_at is not None
        assert resolved.resolution_action == "Corrected journal"
        assert resolved.is_resolved()


# ============================================================================
# TESTS ConstitutionalSnapshot
# ============================================================================

class TestConstitutionalSnapshot:
    def test_create_valid_snapshot(self):
        snapshot = create_test_snapshot()
        assert snapshot.hash_current != ""
        assert len(snapshot.active_rules) == 1

    def test_compute_hash_includes_chain(self):
        snapshot = create_test_snapshot()
        snap2 = ConstitutionalSnapshot(
            snapshot_id=uuid.uuid4(),
            effective_as_of=FIXED_NOW + timedelta(days=1),
            active_rules=snapshot.active_rules,
            active_overrides=[],
            version="1.0.1",
            hash_chain_previous=snapshot.hash_current,
        )
        assert snap2.hash_chain_previous == snapshot.hash_current
        assert snap2.hash_current != snapshot.hash_current


# ============================================================================
# TESTS Constitution
# ============================================================================

class TestConstitution:
    def test_initialization_loads_default_rules(self):
        constitution = Constitution(version="1.0.0")
        assert len(constitution.rules) > 0
        assert len(constitution.snapshots) > 0
        assert constitution.version == "1.0.0"

    def test_add_rule_success(self):
        constitution = Constitution(version="1.0.0")
        rule = create_test_rule()
        constitution.add_rule(rule, "test")
        assert rule.rule_id in constitution.rules

    def test_add_rule_duplicate_principle_raises(self):
        constitution = Constitution(version="1.0.0")
        rule1 = create_test_rule(principle=ConstitutionalPrinciple.DOUBLE_ENTRY)
        constitution.add_rule(rule1, "test")
        rule2 = create_test_rule(principle=ConstitutionalPrinciple.DOUBLE_ENTRY)
        with pytest.raises(ConstitutionAmendmentError, match="already exists"):
            constitution.add_rule(rule2, "test")

    def test_get_active_rules_handles_override(self):
        constitution = Constitution(version="1.0.0")
        override = create_test_override(
            suspended_principles={ConstitutionalPrinciple.DOUBLE_ENTRY}
        )
        constitution.overrides.append(override)
        active = constitution.get_active_rules()
        for rule in active:
            assert rule.principle != ConstitutionalPrinciple.DOUBLE_ENTRY

    def test_check_violation_raises_for_critical(self):
        constitution = Constitution(version="1.0.0")
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
        constitution = Constitution(version="1.0.0")
        snapshot = constitution.get_snapshot(FIXED_NOW)
        assert snapshot.snapshot_id is not None
        assert snapshot.effective_as_of == FIXED_NOW
        assert len(snapshot.active_rules) > 0

    def test_verify_integrity_validates_chain(self):
        constitution = Constitution(version="1.0.0")
        result = constitution.verify_integrity()
        assert result["is_valid"]

    def test_get_statistics_returns_summary(self):
        constitution = Constitution(version="1.0.0")
        stats = constitution.get_statistics()
        assert "total_rules" in stats
        assert "active_rules" in stats
        assert "total_violations" in stats


# ============================================================================
# TESTS SupremeLaw
# ============================================================================

class TestSupremeLaw:
    def test_singleton(self):
        law1 = SupremeLaw()
        law2 = SupremeLaw()
        assert law1 is law2

    def test_enforce_double_entry_valid(self):
        law = SupremeLaw()
        result = law.enforce(
            ConstitutionalPrinciple.DOUBLE_ENTRY,
            {"total_debit": 100, "total_credit": 100},
            "test_module",
        )
        assert result

    def test_enforce_double_entry_invalid(self):
        law = SupremeLaw()
        with patch.object(law, "check_violation") as mock_check:
            law.enforce(
                ConstitutionalPrinciple.DOUBLE_ENTRY,
                {"total_debit": 100, "total_credit": 80},
                "test_module",
            )
            mock_check.assert_called_once()

    def test_add_rule_delegates_to_constitution(self):
        law = SupremeLaw()
        rule = create_test_rule()
        law.add_rule(rule, "test")
        retrieved = law.get_rule(rule.rule_id)
        assert retrieved is not None

    def test_get_active_principles(self):
        law = SupremeLaw()
        principles = law.get_active_principles()
        assert len(principles) > 0
        assert ConstitutionalPrinciple.DOUBLE_ENTRY in principles

    def test_get_statistics(self):
        law = SupremeLaw()
        stats = law.get_statistics()
        assert "total_rules" in stats

    def test_emergency_override_delegates(self):
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
        law1 = get_supreme_law()
        law2 = get_supreme_law()
        assert law1 is law2


# ============================================================================
# INTEGRATION TEST
# ============================================================================

class TestSupremeLawIntegration:
    def test_full_workflow(self):
        law = SupremeLaw()

        # 1. Add a new rule
        rule = ConstitutionalRule(
            rule_id=uuid.uuid4(),
            principle=ConstitutionalPrinciple.MATERIALITY,
            statement="Materiality threshold is 5%",
            sovereignty=SovereigntyLevel.ORDINARY,
            severity_on_violation=ConstitutionalSeverity.MEDIUM,
            effective_from=FIXED_NOW,
            created_by="admin",
            created_at=FIXED_NOW,
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
        assert integrity["is_valid"]


# ============================================================================
# ENTITY LIFECYCLE METHODS (PARAMETRIZE UNTUK HILANGKAN DUPLIKAT)
# ============================================================================

# Define tuples: (fixture_name, class_name, supports_update, supports_delete, supports_restore)
LIFECYCLE_PARAMS = [
    ("constitutional_rule", "ConstitutionalRule", True, True, True),
    ("amendment_record", "AmendmentRecord", False, True, True),
    ("emergency_override", "EmergencyOverride", False, True, True),
    ("violation_record", "ViolationRecord", False, False, False),
    ("constitutional_snapshot", "ConstitutionalSnapshot", False, False, False),
]


@pytest.fixture
def constitutional_rule():
    return create_test_rule()


@pytest.fixture
def amendment_record():
    return create_test_amendment()


@pytest.fixture
def emergency_override():
    return create_test_override()


@pytest.fixture
def violation_record():
    return create_test_violation()


@pytest.fixture
def constitutional_snapshot():
    return create_test_snapshot()


class TestEntityLifecycle:
    @pytest.mark.parametrize("fixture_name,cls_name,upd,del_,res", LIFECYCLE_PARAMS)
    def test_entity_create(self, fixture_name, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(fixture_name)
        result = entity.create("admin")
        assert result is entity

    @pytest.mark.parametrize("fixture_name,cls_name,upd,del_,res", LIFECYCLE_PARAMS)
    def test_entity_activate(self, fixture_name, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(fixture_name)
        result = entity.activate("admin")
        assert result is entity

    @pytest.mark.parametrize("fixture_name,cls_name,upd,del_,res", LIFECYCLE_PARAMS)
    def test_entity_deactivate(self, fixture_name, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(fixture_name)
        result = entity.deactivate("admin")
        # For ConstitutionalRule, deactivate sets effective_until
        if cls_name == "ConstitutionalRule":
            assert result.effective_until is not None
            assert result.version == entity.version + 1
        else:
            assert result is entity

    @pytest.mark.parametrize("fixture_name,cls_name,upd,del_,res", LIFECYCLE_PARAMS)
    def test_entity_lock(self, fixture_name, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(fixture_name)
        result = entity.lock("admin", "test")
        assert result is entity

    @pytest.mark.parametrize("fixture_name,cls_name,upd,del_,res", LIFECYCLE_PARAMS)
    def test_entity_unlock(self, fixture_name, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(fixture_name)
        result = entity.unlock("admin")
        assert result is entity

    @pytest.mark.parametrize("fixture_name,cls_name,upd,del_,res", LIFECYCLE_PARAMS)
    def test_entity_validate(self, fixture_name, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(fixture_name)
        result = entity.validate()
        assert result["is_valid"]

    @pytest.mark.parametrize("fixture_name,cls_name,upd,del_,res", LIFECYCLE_PARAMS)
    def test_entity_update(self, fixture_name, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(fixture_name)
        if not upd:
            with pytest.raises(AttributeError):
                entity.update("admin", some_field="value")
        else:
            if cls_name == "ConstitutionalRule":
                updated = entity.update("admin", statement="New")
                assert updated.statement == "New"
                assert updated.version == entity.version + 1

    @pytest.mark.parametrize("fixture_name,cls_name,upd,del_,res", LIFECYCLE_PARAMS)
    def test_entity_delete(self, fixture_name, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(fixture_name)
        if not del_:
            with pytest.raises(AttributeError):
                entity.delete("admin")
        else:
            deleted = entity.delete("admin", "reason")
            assert deleted.deleted_at is not None
            assert deleted.deleted_by == "admin"
            assert deleted.version == entity.version + 1

    @pytest.mark.parametrize("fixture_name,cls_name,upd,del_,res", LIFECYCLE_PARAMS)
    def test_entity_restore(self, fixture_name, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(fixture_name)
        if not res:
            # For violation and snapshot, restore raises AttributeError
            if cls_name in ("ViolationRecord", "ConstitutionalSnapshot"):
                with pytest.raises(AttributeError):
                    entity.restore("admin")
            return
        # For AmendmentRecord, restore allowed
        if del_:
            deleted = entity.delete("admin", "reason")
            restored = deleted.restore("admin")
            assert restored.deleted_at is None
            assert restored.deleted_by is None
            assert restored.version == deleted.version + 1


# ============================================================================
# EXTRA METHODS: TOUCH, SNAPSHOT, VERSION, AUDIT_TRAIL
# ============================================================================

class TestExtraMethods:
    @pytest.mark.parametrize("fixture_name,cls_name,upd,del_,res", LIFECYCLE_PARAMS)
    def test_entity_touch(self, fixture_name, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(fixture_name)
        touched = entity.touch("toucher")
        # For ConstitutionalRule, touch returns new instance with version+1
        if cls_name == "ConstitutionalRule":
            assert touched.version == entity.version + 1
            assert touched is not entity
        else:
            # Others return self (immutable but audit trail added)
            assert touched is entity
        trail = touched.audit_trail()
        assert len(trail) >= 1
        assert trail[-1]["action"] == "TOUCH"

    @pytest.mark.parametrize("fixture_name,cls_name,upd,del_,res", LIFECYCLE_PARAMS)
    def test_entity_snapshot(self, fixture_name, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(fixture_name)
        snap = entity.snapshot()
        assert "version" in snap
        assert "timestamp" in snap

    @pytest.mark.parametrize("fixture_name,cls_name,upd,del_,res", LIFECYCLE_PARAMS)
    def test_entity_version(self, fixture_name, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(fixture_name)
        # For ConstitutionalSnapshot, version method is version_number
        if cls_name == "ConstitutionalSnapshot":
            assert entity.version_number == 1
        else:
            assert entity.version == 1

    @pytest.mark.parametrize("fixture_name,cls_name,upd,del_,res", LIFECYCLE_PARAMS)
    def test_entity_audit_trail(self, fixture_name, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(fixture_name)
        trail = entity.audit_trail()
        assert len(trail) >= 1
        entity.touch("toucher")
        trail2 = entity.audit_trail()
        assert len(trail2) >= len(trail) + 1


# ============================================================================
# CONSTITUTION REPOSITORY METHODS
# ============================================================================

class TestConstitutionRepository:
    def test_save_and_get_rule(self):
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
        assert result
        assert constitution.get_rule(rule.rule_id) is None

    def test_save_and_get_amendments(self):
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
        assert result

    def test_save_and_get_overrides(self):
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
        assert result

    def test_save_and_get_violations(self):
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
        assert resolved.is_resolved()

    def test_save_and_get_snapshots(self):
        constitution = Constitution(version="1.0")
        snapshot = create_test_snapshot()
        constitution.save_snapshot(snapshot)
        snapshots = constitution.get_snapshots()
        assert len(snapshots) >= 1


# ============================================================================
# SUPREME LAW DELEGATION METHODS
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
        assert result

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
        assert result

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
        assert result

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
        assert resolved.is_resolved()

    def test_save_snapshot(self):
        law = SupremeLaw()
        snapshot = create_test_snapshot()
        law.save_snapshot(snapshot)
        snapshots = law.get_snapshots()
        assert len(snapshots) >= 1

    def test_modify_rule_delegates(self):
        law = SupremeLaw()
        rule = create_test_rule()
        law.add_rule(rule, "admin")
        new_rule = ConstitutionalRule(
            rule_id=uuid.uuid4(),
            principle=rule.principle,
            statement="Modified",
            sovereignty=SovereigntyLevel.ORDINARY,
            severity_on_violation=ConstitutionalSeverity.HIGH,
            effective_from=FIXED_NOW,
            created_by="admin",
            created_at=FIXED_NOW,
            approved_by=["a", "b"],
        )
        law.constitution.modify_rule(rule.rule_id, new_rule, "admin")
        old = law.get_rule(rule.rule_id)
        assert not old.is_active()

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

    def test_get_violations_with_filters(self):
        law = SupremeLaw()
        violation = create_test_violation()
        law.save_violation(violation)
        violations = law.get_violations(principle=ConstitutionalPrinciple.DOUBLE_ENTRY)
        assert len(violations) >= 1


# ============================================================================
# ADDITIONAL TESTS
# ============================================================================

class TestAdditional:
    def test_emergency_override_from_dict(self):
        data = {
            "override_id": str(uuid.uuid4()),
            "reason": "NATURAL_DISASTER",
            "suspended_principles": ["DOUBLE_ENTRY"],
            "duration_hours": 24,
            "authorized_by": ["a", "b"],
            "authorized_at": FIXED_NOW.isoformat(),
            "justification_document": "doc",
            "version": 1,
        }
        override = EmergencyOverride.from_dict(data)
        assert override.reason == EmergencyOverrideReason.NATURAL_DISASTER
        assert len(override.suspended_principles) == 1
        assert override.duration_hours == 24

    def test_emergency_override_validate_hash_mismatch(self):
        override = create_test_override()
        object.__setattr__(override, "cryptographic_hash", "fake")
        result = override.validate()
        assert not result["is_valid"]
        assert "Hash mismatch" in result["errors"]

    def test_constitution_modify_rule(self):
        constitution = Constitution(version="1.0")
        rule = create_test_rule()
        constitution.add_rule(rule, "admin")
        new_rule = ConstitutionalRule(
            rule_id=uuid.uuid4(),
            principle=rule.principle,
            statement="Modified statement",
            sovereignty=SovereigntyLevel.ORDINARY,
            severity_on_violation=ConstitutionalSeverity.HIGH,
            effective_from=FIXED_NOW,
            created_by="admin",
            created_at=FIXED_NOW,
            approved_by=["a", "b"],
        )
        constitution.modify_rule(rule.rule_id, new_rule, "admin")
        old = constitution.get_rule(rule.rule_id)
        assert not old.is_active()
        assert new_rule.rule_id in constitution.rules

    def test_constitution_get_active_rules_only_active(self):
        constitution = Constitution(version="1.0")
        now = FIXED_NOW
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
        active_ids = {r.rule_id for r in active}
        assert rule1.rule_id in active_ids
        assert rule2.rule_id not in active_ids

    def test_constitution_get_violations_with_filters(self):
        constitution = Constitution(version="1.0")
        v1 = create_test_violation(principle=ConstitutionalPrinciple.DOUBLE_ENTRY)
        v2 = create_test_violation(principle=ConstitutionalPrinciple.IMMUTABILITY)
        constitution.save_violation(v1)
        constitution.save_violation(v2)
        filtered = constitution.get_violations(principle=ConstitutionalPrinciple.DOUBLE_ENTRY)
        assert len(filtered) >= 1
        for v in filtered:
            assert v.principle == ConstitutionalPrinciple.DOUBLE_ENTRY

    def test_constitution_resolve_violation_not_found(self):
        constitution = Constitution(version="1.0")
        result = constitution.resolve_violation(uuid.uuid4(), "admin", "action")
        assert result is None

    def test_constitution_get_snapshots_count(self):
        constitution = Constitution(version="1.0")
        constitution.get_snapshot(FIXED_NOW)
        constitution.get_snapshot(FIXED_NOW + timedelta(days=1))
        snapshots = constitution.get_snapshots()
        assert len(snapshots) >= 2

    def test_constitution_verify_integrity_broken_chain(self):
        constitution = Constitution(version="1.0")
        constitution.get_snapshot(FIXED_NOW)
        snap2 = constitution.get_snapshot(FIXED_NOW + timedelta(days=1))
        snap2.hash_chain_previous = "tampered"
        result = constitution.verify_integrity()
        assert not result["is_valid"]
        assert "broken_at_index" in result

    def test_constitution_reset(self):
        constitution = Constitution(version="1.0")
        original_count = len(constitution.rules)
        constitution.reset()
        assert len(constitution.rules) == original_count
        assert len(constitution.violations) == 0

    def test_supreme_law_constitution_property(self):
        law = SupremeLaw()
        assert law.constitution is not None
