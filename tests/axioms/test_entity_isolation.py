#!/usr/bin/env python3
"""
tests/unit/test_entity_isolation.py
Test untuk axioms/entity_isolation.py
Mencakup: LegalEntityDefinition, InterEntityAuthorization, EntityIsolationViolation,
EntityIsolationValidator, EntityIsolationAxiom
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from axioms.entity_isolation import (
    EntityIsolationAxiom,
    EntityIsolationCheckLevel,
    EntityIsolationValidator,
    EntityIsolationViolation,
    EntityIsolationViolationError,
    EntityIsolationViolationSeverity,
    InterEntityAuthorization,
    InterEntityAuthorizationError,
    InterEntityAuthorizationType,
    LegalEntityDefinition,
    create_inter_entity_authorization_dict,
    create_legal_entity,
    get_entity_isolation_axiom,
)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_test_entity(
    entity_code: str = "TEST",
    entity_name: str = "Test Entity",
    tax_id: str = "1234567890",
    functional_currency: str = "IDR",
    fiscal_year_start: int = 1,
    country_code: str = "ID",
) -> LegalEntityDefinition:
    return LegalEntityDefinition(
        entity_id=uuid.uuid4(),
        entity_code=entity_code,
        entity_name=entity_name,
        tax_id=tax_id,
        functional_currency=functional_currency,
        fiscal_year_start=fiscal_year_start,
        country_code=country_code,
        is_active=True,
    )


def create_test_authorization(
    from_entity_id: uuid.UUID | None = None,
    to_entity_id: uuid.UUID | None = None,
    auth_type: InterEntityAuthorizationType = InterEntityAuthorizationType.CONSOLIDATION,
    allowed_operations: list[str] | None = None,
) -> InterEntityAuthorization:
    if from_entity_id is None:
        from_entity_id = uuid.uuid4()
    if to_entity_id is None:
        to_entity_id = uuid.uuid4()
    if allowed_operations is None:
        allowed_operations = ["READ", "WRITE"]
    return InterEntityAuthorization(
        auth_id=uuid.uuid4(),
        from_entity_id=from_entity_id,
        to_entity_id=to_entity_id,
        auth_type=auth_type,
        granted_by="admin",
        granted_at=datetime.now(UTC),
        expires_at=None,
        approvers=["approver1", "approver2"],
        purpose="Test purpose",
        allowed_operations=allowed_operations,
    )


def create_test_violation() -> EntityIsolationViolation:
    return EntityIsolationViolation(
        violation_id=uuid.uuid4(),
        source_entity_id=uuid.uuid4(),
        target_entity_id=uuid.uuid4(),
        attempted_operation="READ",
        user_id=uuid.uuid4(),
        module="test_module",
        severity=EntityIsolationViolationSeverity.MEDIUM,
        message="Test violation",
        was_blocked=False,
        detected_at=datetime.now(UTC),
        resolved=False,
        resolved_at=None,
        resolved_by=None,
    )


# ============================================================================
# TESTS FOR LegalEntityDefinition
# ============================================================================

class TestLegalEntityDefinition:
    def test_create_valid_entity(self):
        entity = create_test_entity()
        assert entity.entity_code == "TEST"
        assert entity.entity_name == "Test Entity"
        assert entity.is_active
        assert entity.cryptographic_hash != ""
        assert entity.version == 1

    def test_validate_entity_code_too_short(self):
        with pytest.raises(ValueError, match="Entity code too short"):
            LegalEntityDefinition(
                entity_id=uuid.uuid4(),
                entity_code="A",  # too short
                entity_name="Test",
                tax_id="12345",
                functional_currency="IDR",
                fiscal_year_start=1,
                country_code="ID",
                is_active=True,
            )

    def test_validate_tax_id_too_short(self):
        with pytest.raises(ValueError, match="Tax ID too short"):
            LegalEntityDefinition(
                entity_id=uuid.uuid4(),
                entity_code="TEST",
                entity_name="Test",
                tax_id="1234",  # too short
                functional_currency="IDR",
                fiscal_year_start=1,
                country_code="ID",
                is_active=True,
            )

    def test_validate_fiscal_year_start_range(self):
        with pytest.raises(ValueError, match="Fiscal year start must be 1-12"):
            LegalEntityDefinition(
                entity_id=uuid.uuid4(),
                entity_code="TEST",
                entity_name="Test",
                tax_id="12345",
                functional_currency="IDR",
                fiscal_year_start=13,
                country_code="ID",
                is_active=True,
            )

    def test_update_creates_new_version(self):
        entity = create_test_entity()
        updated = entity.update("admin", entity_name="Updated Name")
        assert updated.entity_name == "Updated Name"
        assert updated.version == entity.version + 1

    def test_update_does_not_change_id(self):
        entity = create_test_entity()
        updated = entity.update("admin", entity_name="Updated")
        assert updated.entity_id == entity.entity_id
        assert updated.created_at == entity.created_at

    def test_delete_marks_deleted_and_inactive(self):
        entity = create_test_entity()
        deleted = entity.delete("admin", "test")
        assert deleted.deleted_at is not None
        assert deleted.deleted_by == "admin"
        assert not deleted.is_active
        assert deleted.version == entity.version + 1

    def test_restore_recovers_deleted_entity(self):
        entity = create_test_entity()
        deleted = entity.delete("admin", "test")
        restored = deleted.restore("admin")
        assert restored.deleted_at is None
        assert restored.deleted_by is None
        assert restored.is_active
        assert restored.version == deleted.version + 1

    def test_restore_not_deleted_raises(self):
        entity = create_test_entity()
        with pytest.raises(ValueError, match="Entity not deleted"):
            entity.restore("admin")

    def test_activate_does_nothing_if_already_active(self):
        entity = create_test_entity()
        activated = entity.activate("admin")
        assert activated is entity  # returns self when already active

    def test_activate_activates_inactive_entity(self):
        entity = create_test_entity()
        deactivated = entity.deactivate("admin", "test")
        activated = deactivated.activate("admin")
        assert activated.is_active
        assert activated.version == deactivated.version + 1

    def test_deactivate_does_nothing_if_inactive(self):
        entity = create_test_entity()
        deactivated = entity.deactivate("admin", "test")
        again = deactivated.deactivate("admin", "test2")
        assert again is deactivated  # returns self

    def test_lock_returns_self(self):
        entity = create_test_entity()
        locked = entity.lock("admin", "test")
        assert locked is entity

    def test_unlock_returns_self(self):
        entity = create_test_entity()
        unlocked = entity.unlock("admin")
        assert unlocked is entity

    def test_validate_returns_valid(self):
        entity = create_test_entity()
        result = entity.validate()
        assert result["is_valid"]
        assert result["entity_id"] == str(entity.entity_id)

    def test_validate_returns_errors_on_hash_mismatch(self):
        entity = create_test_entity()
        object.__setattr__(entity, "cryptographic_hash", "fakehash")
        result = entity.validate()
        assert not result["is_valid"]
        assert "Hash mismatch" in result["errors"]

    def test_to_dict_contains_all_fields(self):
        entity = create_test_entity()
        d = entity.to_dict()
        assert d["entity_code"] == "TEST"
        assert d["entity_name"] == "Test Entity"
        assert d["tax_id"] == "1234567890"
        assert "entity_id" in d
        assert "version" in d

    def test_from_dict_reconstructs(self):
        entity = create_test_entity()
        d = entity.to_dict()
        reconstructed = LegalEntityDefinition.from_dict(d)
        assert reconstructed.entity_id == entity.entity_id
        assert reconstructed.entity_code == entity.entity_code
        assert reconstructed.entity_name == entity.entity_name
        assert reconstructed.tax_id == entity.tax_id
        assert reconstructed.functional_currency == entity.functional_currency

    def test_clone_creates_new_entity(self):
        entity = create_test_entity()
        cloned = entity.clone()
        assert cloned.entity_id != entity.entity_id
        assert cloned.entity_code == entity.entity_code + "_COPY"
        assert cloned.entity_name == entity.entity_name + " (COPY)"
        assert not cloned.is_active
        assert cloned.version == 1
        assert cloned.parent_entity_id == entity.entity_id

    def test_snapshot_returns_summary(self):
        entity = create_test_entity()
        snap = entity.snapshot()
        assert snap["entity_id"] == str(entity.entity_id)
        assert snap["entity_code"] == entity.entity_code
        assert snap["is_active"] == entity.is_active
        assert "timestamp" in snap

    def test_get_version(self):
        entity = create_test_entity()
        assert entity.get_version() == 1

    def test_audit_trail_records_actions(self):
        entity = create_test_entity()
        assert len(entity.audit_trail()) >= 1
        entity.touch("toucher")
        trail = entity.audit_trail()
        assert len(trail) >= 2
        assert trail[-1]["action"] == "TOUCH"
        assert trail[-1]["performed_by"] == "toucher"

    def test_touch_increments_version(self):
        entity = create_test_entity()
        touched = entity.touch("toucher")
        assert touched.version == entity.version + 1


# ============================================================================
# TESTS FOR InterEntityAuthorization
# ============================================================================

class TestInterEntityAuthorization:
    def test_create_valid_authorization(self):
        auth = create_test_authorization()
        assert auth.from_entity_id is not None
        assert auth.to_entity_id is not None
        assert auth.auth_type == InterEntityAuthorizationType.CONSOLIDATION
        assert len(auth.approvers) == 2
        assert auth.cryptographic_hash != ""
        assert auth.version == 1

    def test_validate_requires_allowed_operations(self):
        with pytest.raises(ValueError, match="At least one allowed operation required"):
            InterEntityAuthorization(
                auth_id=uuid.uuid4(),
                from_entity_id=uuid.uuid4(),
                to_entity_id=uuid.uuid4(),
                auth_type=InterEntityAuthorizationType.CONSOLIDATION,
                granted_by="admin",
                granted_at=datetime.now(UTC),
                expires_at=None,
                approvers=["a"],
                purpose="test",
                allowed_operations=[],
            )

    def test_update_creates_new_version(self):
        auth = create_test_authorization()
        updated = auth.update("admin", purpose="Updated purpose")
        assert updated.purpose == "Updated purpose"
        assert updated.version == auth.version + 1

    def test_delete_revokes_authorization(self):
        auth = create_test_authorization()
        deleted = auth.delete("admin", "test")
        assert deleted.revoked
        assert deleted.revoked_at is not None
        assert deleted.revoked_by == "admin"
        assert deleted.version == auth.version + 1

    def test_restore_revives_revoked_authorization(self):
        auth = create_test_authorization()
        deleted = auth.delete("admin", "test")
        restored = deleted.restore("admin")
        assert not restored.revoked
        assert restored.revoked_at is None
        assert restored.revoked_by is None
        assert restored.version == deleted.version + 1

    def test_restore_not_revoked_raises(self):
        auth = create_test_authorization()
        with pytest.raises(ValueError, match="Authorization not revoked"):
            auth.restore("admin")

    def test_activate_restores_if_revoked(self):
        auth = create_test_authorization()
        deleted = auth.delete("admin", "test")
        activated = deleted.activate("admin")
        assert not activated.revoked

    def test_deactivate_deletes_if_not_revoked(self):
        auth = create_test_authorization()
        deactivated = auth.deactivate("admin", "test")
        assert deactivated.revoked
        assert deactivated.revoked_by == "admin"

    def test_lock_returns_self(self):
        auth = create_test_authorization()
        locked = auth.lock("admin", "test")
        assert locked is auth

    def test_unlock_returns_self(self):
        auth = create_test_authorization()
        unlocked = auth.unlock("admin")
        assert unlocked is auth

    def test_validate_returns_valid(self):
        auth = create_test_authorization()
        result = auth.validate()
        assert result["is_valid"]

    def test_validate_returns_errors_on_hash_mismatch(self):
        auth = create_test_authorization()
        object.__setattr__(auth, "cryptographic_hash", "fake")
        result = auth.validate()
        assert not result["is_valid"]
        assert "Hash mismatch" in result["errors"]

    def test_to_dict_contains_fields(self):
        auth = create_test_authorization()
        d = auth.to_dict()
        assert d["auth_type"] == "CONSOLIDATION"
        assert d["purpose"] == "Test purpose"
        assert d["allowed_operations"] == ["READ", "WRITE"]
        assert "auth_id" in d

    def test_from_dict_reconstructs(self):
        auth = create_test_authorization()
        d = auth.to_dict()
        reconstructed = InterEntityAuthorization.from_dict(d)
        assert reconstructed.auth_id == auth.auth_id
        assert reconstructed.from_entity_id == auth.from_entity_id
        assert reconstructed.to_entity_id == auth.to_entity_id
        assert reconstructed.auth_type == auth.auth_type
        assert reconstructed.purpose == auth.purpose

    def test_clone_creates_new_instance(self):
        auth = create_test_authorization()
        cloned = auth.clone()
        assert cloned.auth_id != auth.auth_id
        assert cloned.from_entity_id == auth.from_entity_id
        assert cloned.to_entity_id == auth.to_entity_id
        assert cloned.auth_type == auth.auth_type
        assert cloned.version == 1

    def test_snapshot_returns_summary(self):
        auth = create_test_authorization()
        snap = auth.snapshot()
        assert snap["auth_id"] == str(auth.auth_id)
        assert snap["auth_type"] == auth.auth_type.name

    def test_get_version(self):
        auth = create_test_authorization()
        assert auth.get_version() == 1

    def test_audit_trail_records(self):
        auth = create_test_authorization()
        assert len(auth.audit_trail()) >= 1
        auth.touch("toucher")
        trail = auth.audit_trail()
        assert trail[-1]["action"] == "TOUCH"

    def test_touch_increments_version(self):
        auth = create_test_authorization()
        touched = auth.touch("toucher")
        assert touched.version == auth.version + 1

    def test_is_valid_handles_expiry(self):
        now = datetime.now(UTC)
        auth = create_test_authorization()
        auth.expires_at = now + timedelta(days=1)
        assert auth.is_valid()
        auth.expires_at = now - timedelta(days=1)
        assert not auth.is_valid()

    def test_is_valid_handles_revoked(self):
        auth = create_test_authorization()
        deleted = auth.delete("admin", "test")
        assert not deleted.is_valid()

    def test_allows_operation_case_insensitive(self):
        auth = create_test_authorization(allowed_operations=["READ", "WRITE"])
        assert auth.allows_operation("read")
        assert auth.allows_operation("WRITE")
        assert not auth.allows_operation("DELETE")


# ============================================================================
# TESTS FOR EntityIsolationViolation
# ============================================================================

class TestEntityIsolationViolation:
    def test_create_valid_violation(self):
        violation = create_test_violation()
        assert violation.source_entity_id is not None
        assert violation.target_entity_id is not None
        assert violation.attempted_operation == "READ"
        assert violation.severity == EntityIsolationViolationSeverity.MEDIUM
        assert not violation.resolved
        assert violation.cryptographic_hash != ""

    def test_validate_returns_valid(self):
        violation = create_test_violation()
        result = violation.validate()
        assert result["is_valid"]

    def test_validate_returns_errors_on_hash_mismatch(self):
        violation = create_test_violation()
        object.__setattr__(violation, "cryptographic_hash", "fake")
        result = violation.validate()
        assert not result["is_valid"]
        assert "Hash mismatch" in result["errors"]

    def test_to_dict_contains_fields(self):
        violation = create_test_violation()
        d = violation.to_dict()
        assert d["attempted_operation"] == "READ"
        assert d["module"] == "test_module"
        assert d["severity"] == "MEDIUM"
        assert "violation_id" in d

    def test_from_dict_reconstructs(self):
        violation = create_test_violation()
        d = violation.to_dict()
        reconstructed = EntityIsolationViolation.from_dict(d)
        assert reconstructed.violation_id == violation.violation_id
        assert reconstructed.source_entity_id == violation.source_entity_id
        assert reconstructed.target_entity_id == violation.target_entity_id
        assert reconstructed.attempted_operation == violation.attempted_operation

    def test_clone_creates_new_instance(self):
        violation = create_test_violation()
        cloned = violation.clone()
        assert cloned.violation_id != violation.violation_id
        assert cloned.source_entity_id == violation.source_entity_id
        assert cloned.target_entity_id == violation.target_entity_id
        assert not cloned.resolved
        assert cloned.version == 1

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

    def test_resolve_marks_resolved(self):
        violation = create_test_violation()
        resolved = violation.resolve("admin")
        assert resolved.resolved
        assert resolved.resolved_at is not None
        assert resolved.resolved_by == "admin"
        assert resolved.version == violation.version + 1

    def test_resolve_already_resolved_raises(self):
        violation = create_test_violation()
        resolved = violation.resolve("admin")
        with pytest.raises(ValueError, match="Already resolved"):
            resolved.resolve("admin2")


# ============================================================================
# TESTS FOR EntityIsolationValidator
# ============================================================================

class TestEntityIsolationValidator:
    def test_validate_access_same_entity_allows(self):
        entity_id = uuid.uuid4()
        allowed, violation = EntityIsolationValidator.validate_access(
            source_entity_id=entity_id,
            target_entity_id=entity_id,
            operation="READ",
            user_authorizations=[],
        )
        assert allowed
        assert violation is None

    def test_validate_access_with_valid_auth_allows(self):
        auth = create_test_authorization(allowed_operations=["READ"])
        allowed, violation = EntityIsolationValidator.validate_access(
            source_entity_id=auth.from_entity_id,
            target_entity_id=auth.to_entity_id,
            operation="READ",
            user_authorizations=[auth],
        )
        assert allowed
        assert violation is None

    def test_validate_access_no_auth_blocks(self):
        from_entity = uuid.uuid4()
        to_entity = uuid.uuid4()
        with patch("axioms.entity_isolation.EntityIsolationValidator._notify_constitution"):
            allowed, violation = EntityIsolationValidator.validate_access(
                source_entity_id=from_entity,
                target_entity_id=to_entity,
                operation="WRITE",
                user_authorizations=[],
                check_level=EntityIsolationCheckLevel.STRICT,
            )
        assert not allowed
        assert violation is not None
        assert violation.was_blocked

    def test_validate_access_permissive_level_allows_even_no_auth(self):
        from_entity = uuid.uuid4()
        to_entity = uuid.uuid4()
        allowed, violation = EntityIsolationValidator.validate_access(
            source_entity_id=from_entity,
            target_entity_id=to_entity,
            operation="WRITE",
            user_authorizations=[],
            check_level=EntityIsolationCheckLevel.PERMISSIVE,
        )
        assert allowed
        assert violation is None  # PERMISSIVE returns no violation

    def test_validate_access_moderate_allows_read_even_no_auth(self):
        from_entity = uuid.uuid4()
        to_entity = uuid.uuid4()
        with patch("axioms.entity_isolation.EntityIsolationValidator._notify_constitution"):
            allowed, violation = EntityIsolationValidator.validate_access(
                source_entity_id=from_entity,
                target_entity_id=to_entity,
                operation="READ",
                user_authorizations=[],
                check_level=EntityIsolationCheckLevel.MODERATE,
            )
        assert allowed  # READ allowed in MODERATE
        assert violation is not None  # violation still created, but not blocked

    def test_validate_access_moderate_blocks_write(self):
        from_entity = uuid.uuid4()
        to_entity = uuid.uuid4()
        with patch("axioms.entity_isolation.EntityIsolationValidator._notify_constitution"):
            allowed, violation = EntityIsolationValidator.validate_access(
                source_entity_id=from_entity,
                target_entity_id=to_entity,
                operation="WRITE",
                user_authorizations=[],
                check_level=EntityIsolationCheckLevel.MODERATE,
            )
        assert not allowed
        assert violation is not None
        assert violation.was_blocked


# ============================================================================
# TESTS FOR EntityIsolationAxiom
# ============================================================================

class TestEntityIsolationAxiom:
    def test_singleton(self):
        axiom1 = EntityIsolationAxiom()
        axiom2 = EntityIsolationAxiom()
        assert axiom1 is axiom2

    def test_save_and_get_entity(self):
        axiom = EntityIsolationAxiom()
        entity = create_test_entity()
        axiom.save_entity(entity)
        retrieved = axiom.get_entity(entity.entity_id)
        assert retrieved is not None
        assert retrieved.entity_id == entity.entity_id

    def test_get_entity_by_code(self):
        axiom = EntityIsolationAxiom()
        entity = create_test_entity(entity_code="CODE123")
        axiom.save_entity(entity)
        retrieved = axiom.get_entity_by_code("CODE123")
        assert retrieved is not None
        assert retrieved.entity_code == "CODE123"

    def test_get_all_entities(self):
        axiom = EntityIsolationAxiom()
        entity1 = create_test_entity(entity_code="E1")
        entity2 = create_test_entity(entity_code="E2")
        axiom.save_entity(entity1)
        axiom.save_entity(entity2)
        entities = axiom.get_all_entities(active_only=True)
        assert len(entities) >= 2

    def test_delete_entity(self):
        axiom = EntityIsolationAxiom()
        entity = create_test_entity()
        axiom.save_entity(entity)
        result = axiom.delete_entity(entity.entity_id)
        assert result
        assert axiom.get_entity(entity.entity_id) is None

    def test_save_and_get_authorization(self):
        axiom = EntityIsolationAxiom()
        auth = create_test_authorization()
        axiom.save_authorization(auth)
        auths = axiom.get_authorizations(auth.from_entity_id, auth.to_entity_id)
        assert len(auths) == 1
        assert auths[0].auth_id == auth.auth_id

    def test_get_authorizations_only_valid(self):
        axiom = EntityIsolationAxiom()
        auth_valid = create_test_authorization()
        auth_expired = create_test_authorization()
        auth_expired.expires_at = datetime.now(UTC) - timedelta(days=1)
        axiom.save_authorization(auth_valid)
        axiom.save_authorization(auth_expired)
        auths = axiom.get_authorizations(
            auth_valid.from_entity_id, auth_valid.to_entity_id, only_valid=True
        )
        assert len(auths) == 1
        assert auths[0].auth_id == auth_valid.auth_id

    def test_get_authorizations_by_entity_as_source(self):
        axiom = EntityIsolationAxiom()
        entity_id = uuid.uuid4()
        auth1 = create_test_authorization(from_entity_id=entity_id, to_entity_id=uuid.uuid4())
        auth2 = create_test_authorization(from_entity_id=uuid.uuid4(), to_entity_id=entity_id)
        axiom.save_authorization(auth1)
        axiom.save_authorization(auth2)
        source_auths = axiom.get_authorizations_by_entity(entity_id, as_source=True)
        assert len(source_auths) == 1
        assert source_auths[0].auth_id == auth1.auth_id

        target_auths = axiom.get_authorizations_by_entity(entity_id, as_source=False)
        assert len(target_auths) == 1
        assert target_auths[0].auth_id == auth2.auth_id

    def test_delete_authorization(self):
        axiom = EntityIsolationAxiom()
        auth = create_test_authorization()
        axiom.save_authorization(auth)
        result = axiom.delete_authorization(auth.auth_id)
        assert result
        auths = axiom.get_authorizations(auth.from_entity_id, auth.to_entity_id)
        assert len(auths) == 0

    def test_save_and_get_violations(self):
        axiom = EntityIsolationAxiom()
        violation = create_test_violation()
        axiom.save_violation(violation)
        violations = axiom.get_violations()
        assert len(violations) >= 1
        found = next((v for v in violations if v.violation_id == violation.violation_id), None)
        assert found is not None

    def test_resolve_violation(self):
        axiom = EntityIsolationAxiom()
        violation = create_test_violation()
        axiom.save_violation(violation)
        resolved = axiom.resolve_violation(violation.violation_id, "admin")
        assert resolved is not None
        assert resolved.resolved

    def test_set_and_get_check_level(self):
        axiom = EntityIsolationAxiom()
        axiom.set_check_level(EntityIsolationCheckLevel.MODERATE)
        assert axiom.get_check_level() == EntityIsolationCheckLevel.MODERATE

    def test_register_entity(self):
        axiom = EntityIsolationAxiom()
        entity = create_test_entity()
        axiom.register_entity(entity)
        assert axiom.get_entity(entity.entity_id) is not None

    def test_grant_authorization(self):
        axiom = EntityIsolationAxiom()
        from_entity = uuid.uuid4()
        to_entity = uuid.uuid4()
        auth = axiom.grant_authorization(
            from_entity_id=from_entity,
            to_entity_id=to_entity,
            auth_type=InterEntityAuthorizationType.CONSOLIDATION,
            granted_by="admin",
            approvers=["a", "b"],
            purpose="test",
            allowed_operations=["READ"],
        )
        assert auth is not None
        assert auth.from_entity_id == from_entity
        assert auth.to_entity_id == to_entity
        auths = axiom.get_authorizations(from_entity, to_entity)
        assert len(auths) == 1

    def test_grant_authorization_no_approvers_raises(self):
        axiom = EntityIsolationAxiom()
        with pytest.raises(InterEntityAuthorizationError, match="At least one approver required"):
            axiom.grant_authorization(
                from_entity_id=uuid.uuid4(),
                to_entity_id=uuid.uuid4(),
                auth_type=InterEntityAuthorizationType.CONSOLIDATION,
                granted_by="admin",
                approvers=[],
                purpose="test",
                allowed_operations=["READ"],
            )

    def test_enforce_access_allows_same_entity(self):
        axiom = EntityIsolationAxiom()
        entity_id = uuid.uuid4()
        allowed, violation = axiom.enforce_access(
            source_entity_id=entity_id,
            target_entity_id=entity_id,
            operation="READ",
            raise_on_violation=False,
        )
        assert allowed
        assert violation is None

    def test_enforce_access_with_valid_auth_allows(self):
        axiom = EntityIsolationAxiom()
        auth = create_test_authorization(allowed_operations=["READ"])
        axiom.save_authorization(auth)
        allowed, violation = axiom.enforce_access(
            source_entity_id=auth.from_entity_id,
            target_entity_id=auth.to_entity_id,
            operation="READ",
            raise_on_violation=False,
        )
        assert allowed
        assert violation is None

    def test_enforce_access_no_auth_raises(self):
        axiom = EntityIsolationAxiom()
        from_entity = uuid.uuid4()
        to_entity = uuid.uuid4()
        with pytest.raises(EntityIsolationViolationError):
            axiom.enforce_access(
                source_entity_id=from_entity,
                target_entity_id=to_entity,
                operation="WRITE",
                raise_on_violation=True,
            )

    def test_enforce_access_no_auth_returns_violation(self):
        axiom = EntityIsolationAxiom()
        from_entity = uuid.uuid4()
        to_entity = uuid.uuid4()
        allowed, violation = axiom.enforce_access(
            source_entity_id=from_entity,
            target_entity_id=to_entity,
            operation="READ",
            raise_on_violation=False,
            module="test",
        )
        assert not allowed
        assert violation is not None
        assert violation.module == "test"

    def test_is_same_entity(self):
        axiom = EntityIsolationAxiom()
        eid = uuid.uuid4()
        assert axiom.is_same_entity(eid, eid)
        assert not axiom.is_same_entity(eid, uuid.uuid4())

    def test_is_related_entity_same_entity(self):
        axiom = EntityIsolationAxiom()
        eid = uuid.uuid4()
        assert axiom.is_related_entity(eid, eid)

    def test_is_related_entity_parent_child(self):
        axiom = EntityIsolationAxiom()
        parent_id = uuid.uuid4()
        child = create_test_entity()
        child.parent_entity_id = parent_id
        axiom.save_entity(child)
        assert axiom.is_related_entity(parent_id, child.entity_id)
        assert axiom.is_related_entity(child.entity_id, parent_id)

    def test_is_related_entity_consolidation_group(self):
        axiom = EntityIsolationAxiom()
        entity1 = create_test_entity(consolidation_group="GROUP1")
        entity2 = create_test_entity(consolidation_group="GROUP1")
        axiom.save_entity(entity1)
        axiom.save_entity(entity2)
        assert axiom.is_related_entity(entity1.entity_id, entity2.entity_id)

    def test_is_related_entity_not_related(self):
        axiom = EntityIsolationAxiom()
        e1 = create_test_entity()
        e2 = create_test_entity()
        axiom.save_entity(e1)
        axiom.save_entity(e2)
        assert not axiom.is_related_entity(e1.entity_id, e2.entity_id)

    def test_get_statistics(self):
        axiom = EntityIsolationAxiom()
        entity = create_test_entity()
        axiom.save_entity(entity)
        auth = create_test_authorization()
        axiom.save_authorization(auth)
        stats = axiom.get_statistics()
        assert stats["total_entities"] >= 1
        assert stats["active_entities"] >= 1
        assert stats["total_authorizations"] >= 1
        assert stats["valid_authorizations"] >= 1

    def test_reset(self):
        axiom = EntityIsolationAxiom()
        entity = create_test_entity()
        axiom.save_entity(entity)
        auth = create_test_authorization()
        axiom.save_authorization(auth)
        axiom.reset()
        assert len(axiom._entities) == 0
        assert len(axiom._authorizations) == 0
        assert len(axiom._violation_history) == 0
        assert axiom.get_check_level() == EntityIsolationCheckLevel.STRICT


# ============================================================================
# TESTS FOR HELPER FUNCTIONS
# ============================================================================

class TestHelperFunctions:
    def test_create_legal_entity(self):
        entity = create_legal_entity(
            entity_code="CUST",
            entity_name="Customer Entity",
            tax_id="1234567890",
            functional_currency="USD",
            fiscal_year_start=1,
            country_code="US",
            parent_entity_id=uuid.uuid4(),
            consolidation_group="GROUP1",
        )
        assert entity.entity_code == "CUST"
        assert entity.entity_name == "Customer Entity"
        assert entity.functional_currency == "USD"
        assert entity.country_code == "US"
        assert entity.parent_entity_id is not None
        assert entity.consolidation_group == "GROUP1"
        assert entity.is_active

    def test_create_inter_entity_authorization_dict(self):
        from_entity = uuid.uuid4()
        to_entity = uuid.uuid4()
        data = create_inter_entity_authorization_dict(
            from_entity_id=from_entity,
            to_entity_id=to_entity,
            auth_type="CONSOLIDATION",
            purpose="Test",
            allowed_operations=["READ"],
            expires_in_days=10,
        )
        assert data["from_entity_id"] == from_entity
        assert data["to_entity_id"] == to_entity
        assert data["auth_type"] == "CONSOLIDATION"
        assert data["allowed_operations"] == ["READ"]
        assert data["expires_at"] is not None

    def test_get_entity_isolation_axiom_singleton(self):
        axiom1 = get_entity_isolation_axiom()
        axiom2 = get_entity_isolation_axiom()
        assert axiom1 is axiom2