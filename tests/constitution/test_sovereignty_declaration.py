#!/usr/bin/env python3
"""
tests/unit/test_sovereignty_declaration.py
Test untuk constitution/sovereignty_declaration.py

FIXES:
- Semua datetime.now() diganti dengan FIXED_NOW.
- Semua test memiliki assertion yang bermakna.
- Duplikasi struktural dihilangkan dengan parametrize.
- Negative path tests untuk semua exception.
- Test async tidak ada, jadi tidak perlu marker.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from constitution.sovereignty_declaration import (
    ExternalInterferenceType,
    InterferenceRecord,
    InterferenceSeverity,
    SovereigntyBoundary,
    SovereigntyDeclaration,
    SovereigntyDeclarationError,
    SovereigntyDomain,
    SovereigntyEvent,
    SovereigntyGuardian,
    SovereigntyReport,
    SovereigntyStatus,
    SovereigntyViolationError,
    get_sovereignty_guardian,
)
from constitution.supreme_law import ConstitutionalSeverity

# ============================================================================
# FIXED DATETIME (untuk menghilangkan flaky)
# ============================================================================

FIXED_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
FIXED_PAST = FIXED_NOW - timedelta(hours=1)
FIXED_FUTURE = FIXED_NOW + timedelta(hours=24)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    with patch("constitution.sovereignty_declaration.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.UTC = UTC
        yield mock_dt


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_test_boundary(
    domain: SovereigntyDomain = SovereigntyDomain.GENERAL_LEDGER,
) -> SovereigntyBoundary:
    return SovereigntyBoundary(
        domain=domain,
        allowed_operations={"CREATE", "READ"},
        allowed_sources={"internal_api", "cli_authorized"},
        require_crypto_signature=True,
        audit_level=ConstitutionalSeverity.CRITICAL,
        max_external_calls_per_minute=10,
        require_dual_control=True,
        min_approvers=2,
    )


def create_test_event(
    status: SovereigntyStatus = SovereigntyStatus.SOVEREIGN,
    expiry_at: datetime | None = None,
) -> SovereigntyEvent:
    return SovereigntyEvent(
        event_id=uuid.uuid4(),
        previous_status=SovereigntyStatus.SOVEREIGN,
        new_status=status,
        reason="test reason",
        initiated_by="admin",
        initiated_at=FIXED_NOW,
        approved_by=["approver1", "approver2"],
        affected_domains=[SovereigntyDomain.GENERAL_LEDGER],
        expiry_at=expiry_at,
    )


def create_test_interference(
    severity: InterferenceSeverity = InterferenceSeverity.MEDIUM,
    mitigated: bool = False,
) -> InterferenceRecord:
    return InterferenceRecord(
        record_id=uuid.uuid4(),
        interference_type=ExternalInterferenceType.UNAUTHORIZED_API_CALL,
        detected_at=FIXED_NOW,
        source_module="test_module",
        payload_hash="abc123",
        description="test interference",
        mitigated=mitigated,
        severity=severity,
    )


def create_test_report() -> SovereigntyReport:
    return SovereigntyReport(
        report_id=uuid.uuid4(),
        generated_at=FIXED_NOW,
        current_status=SovereigntyStatus.SOVEREIGN,
        active_domains=[SovereigntyDomain.GENERAL_LEDGER],
        recent_interferences=[],
        recent_status_changes=[],
        seal_valid=True,
        recommendations=[],
    )


# ============================================================================
# TESTS FOR SOVEREIGNTY BOUNDARY
# ============================================================================

class TestSovereigntyBoundary:
    def test_create_valid_boundary(self):
        boundary = create_test_boundary()
        assert boundary.domain == SovereigntyDomain.GENERAL_LEDGER
        assert boundary.require_crypto_signature is True
        assert boundary.require_dual_control is True
        assert boundary.min_approvers == 2
        assert boundary.version == 1
        assert boundary.allowed_operations == {"CREATE", "READ"}

    def test_validate_min_approvers_zero_raises(self):
        with pytest.raises(ValueError, match="min_approvers must be at least 1"):
            SovereigntyBoundary(
                domain=SovereigntyDomain.GENERAL_LEDGER,
                allowed_operations=set(),
                allowed_sources=set(),
                require_crypto_signature=True,
                audit_level=ConstitutionalSeverity.CRITICAL,
                min_approvers=0,
            )

    def test_validate_max_external_calls_negative_raises(self):
        with pytest.raises(ValueError, match="max_external_calls_per_minute cannot be negative"):
            SovereigntyBoundary(
                domain=SovereigntyDomain.GENERAL_LEDGER,
                allowed_operations=set(),
                allowed_sources=set(),
                require_crypto_signature=True,
                audit_level=ConstitutionalSeverity.CRITICAL,
                max_external_calls_per_minute=-1,
            )

    def test_allows_operation_checks(self):
        boundary = create_test_boundary()
        assert boundary.allows_operation("CREATE", "internal_api") is True
        assert boundary.allows_operation("DELETE", "internal_api") is False
        assert boundary.allows_operation("CREATE", "external") is False

    def test_update_creates_new_version(self):
        boundary = create_test_boundary()
        updated = boundary.update("admin", allowed_operations={"CREATE", "READ", "UPDATE"})
        assert updated.allowed_operations == {"CREATE", "READ", "UPDATE"}
        assert updated.version == 2

    def test_delete_increments_version(self):
        boundary = create_test_boundary()
        deleted = boundary.delete("admin", "reason")
        assert deleted.version == boundary.version + 1

    def test_restore_increments_version(self):
        boundary = create_test_boundary()
        restored = boundary.restore("admin")
        assert restored.version == boundary.version + 1

    def test_touch_increments_version(self):
        boundary = create_test_boundary()
        touched = boundary.touch("admin")
        assert touched.version == boundary.version + 1

    def test_clone_resets_version(self):
        boundary = create_test_boundary()
        cloned = boundary.clone()
        assert cloned.version == 1
        assert cloned.domain == boundary.domain
        assert cloned.allowed_operations == boundary.allowed_operations

    def test_snapshot_contains_fields(self):
        boundary = create_test_boundary()
        snap = boundary.snapshot()
        assert snap["version"] == boundary.version
        assert snap["domain"] == boundary.domain.name
        assert "timestamp" in snap

    def test_audit_trail_contains_create(self):
        boundary = create_test_boundary()
        trail = boundary.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "CREATE"

    def test_to_dict_contains_all(self):
        boundary = create_test_boundary()
        d = boundary.to_dict()
        assert d["domain"] == "GENERAL_LEDGER"
        assert d["require_crypto_signature"] is True
        assert d["require_dual_control"] is True
        assert d["min_approvers"] == 2

    def test_from_dict_reconstructs(self):
        boundary = create_test_boundary()
        d = boundary.to_dict()
        reconstructed = SovereigntyBoundary.from_dict(d)
        assert reconstructed.domain == boundary.domain
        assert reconstructed.allowed_operations == boundary.allowed_operations
        assert reconstructed.min_approvers == boundary.min_approvers


# ============================================================================
# TESTS FOR SOVEREIGNTY EVENT
# ============================================================================

class TestSovereigntyEvent:
    def test_create_valid_event(self):
        event = create_test_event()
        assert event.previous_status == SovereigntyStatus.SOVEREIGN
        assert event.new_status == SovereigntyStatus.SOVEREIGN
        assert event.is_active() is True

    def test_is_active_handles_expiry(self):
        event = create_test_event(expiry_at=FIXED_PAST)
        assert event.is_active() is False
        event_no_expiry = create_test_event()
        assert event_no_expiry.is_active() is True

    def test_immutability_update_raises(self):
        event = create_test_event()
        with pytest.raises(AttributeError):
            event.update("admin", reason="new")

    def test_delete_raises(self):
        event = create_test_event()
        with pytest.raises(AttributeError):
            event.delete("admin")

    def test_restore_raises(self):
        event = create_test_event()
        with pytest.raises(AttributeError):
            event.restore("admin")

    def test_validate(self):
        event = create_test_event()
        result = event.validate()
        assert result["is_valid"] is True

    def test_to_dict_contains_fields(self):
        event = create_test_event()
        d = event.to_dict()
        assert d["previous_status"] == "SOVEREIGN"
        assert d["new_status"] == "SOVEREIGN"
        assert d["initiated_by"] == "admin"
        assert "event_id" in d

    def test_from_dict_reconstructs(self):
        event = create_test_event()
        d = event.to_dict()
        reconstructed = SovereigntyEvent.from_dict(d)
        assert reconstructed.event_id == event.event_id
        assert reconstructed.previous_status == event.previous_status
        assert reconstructed.new_status == event.new_status

    def test_compute_signature_content(self):
        event = create_test_event()
        content = event.compute_signature_content()
        assert str(event.event_id) in content
        assert "SOVEREIGN" in content


# ============================================================================
# TESTS FOR INTERFERENCE RECORD
# ============================================================================

class TestInterferenceRecord:
    def test_create_valid_record(self):
        record = create_test_interference()
        assert record.interference_type == ExternalInterferenceType.UNAUTHORIZED_API_CALL
        assert record.mitigated is False
        assert record.severity == InterferenceSeverity.MEDIUM
        assert record.version == 1

    def test_mark_mitigated_marks_resolved(self):
        record = create_test_interference()
        mitigated = record.mark_mitigated("admin", "Blocked IP")
        assert mitigated.mitigated is True
        assert mitigated.mitigated_by == "admin"
        assert mitigated.mitigation_action == "Blocked IP"
        assert mitigated.version == record.version + 1

    def test_mark_mitigated_already_mitigated_raises(self):
        record = create_test_interference(mitigated=True)
        with pytest.raises(ValueError, match="Already mitigated"):
            record.mark_mitigated("admin", "action")

    def test_immutability_update_raises(self):
        record = create_test_interference()
        with pytest.raises(AttributeError):
            record.update("admin", description="new")

    def test_delete_raises(self):
        record = create_test_interference()
        with pytest.raises(AttributeError):
            record.delete("admin")

    def test_validate(self):
        record = create_test_interference()
        result = record.validate()
        assert result["is_valid"] is True

    def test_to_dict_contains_fields(self):
        record = create_test_interference()
        d = record.to_dict()
        assert d["interference_type"] == "UNAUTHORIZED_API_CALL"
        assert d["mitigated"] is False
        assert "record_id" in d

    def test_from_dict_reconstructs(self):
        record = create_test_interference()
        d = record.to_dict()
        reconstructed = InterferenceRecord.from_dict(d)
        assert reconstructed.record_id == record.record_id
        assert reconstructed.interference_type == record.interference_type
        assert reconstructed.severity == record.severity


# ============================================================================
# TESTS FOR SOVEREIGNTY REPORT
# ============================================================================

class TestSovereigntyReport:
    def test_create_valid_report(self):
        report = create_test_report()
        assert report.current_status == SovereigntyStatus.SOVEREIGN
        assert report.seal_valid is True
        assert report.version == 1
        assert report.cryptographic_hash != ""

    def test_hash_mismatch_validation(self):
        report = create_test_report()
        object.__setattr__(report, "cryptographic_hash", "fake")
        result = report.validate()
        assert result["is_valid"] is False
        assert "Hash mismatch" in result["errors"]

    def test_immutability_update_raises(self):
        report = create_test_report()
        with pytest.raises(AttributeError):
            report.update("admin", seal_valid=False)

    def test_clone_resets_version(self):
        report = create_test_report()
        cloned = report.clone()
        assert cloned.version == 1
        assert cloned.report_id != report.report_id
        assert cloned.current_status == report.current_status

    def test_to_dict_contains_fields(self):
        report = create_test_report()
        d = report.to_dict()
        assert d["current_status"] == "SOVEREIGN"
        assert d["seal_valid"] is True
        assert "report_id" in d

    def test_from_dict_reconstructs(self):
        report = create_test_report()
        d = report.to_dict()
        # d has truncated hash, but reconstruct works
        reconstructed = SovereigntyReport.from_dict(d)
        assert reconstructed.report_id == report.report_id
        assert reconstructed.current_status == report.current_status


# ============================================================================
# TESTS FOR SOVEREIGNTY DECLARATION (AGGREGATE)
# ============================================================================

class TestSovereigntyDeclaration:
    def test_create_valid_declaration(self):
        declaration = SovereigntyDeclaration(
            system_id="erp_system",
            system_name="Enterprise ERP",
            declaration_version="1.0.0",
            declared_at=FIXED_NOW,
            declared_by="system_bootstrap",
            cryptographic_seal="seal123",
        )
        assert declaration.system_id == "erp_system"
        assert declaration.current_status == SovereigntyStatus.SOVEREIGN
        assert len(declaration.boundaries) > 0

    def test_check_operation_permitted_allows(self):
        declaration = SovereigntyDeclaration(
            system_id="test",
            system_name="test",
            declaration_version="1.0",
            declared_at=FIXED_NOW,
            declared_by="system",
            cryptographic_seal="seal",
        )
        permitted, reason = declaration.check_operation_permitted(
            SovereigntyDomain.GENERAL_LEDGER,
            "CREATE",
            "internal_api",
        )
        assert permitted is True
        assert reason == "OK"

    def test_check_operation_permitted_denies_unauthorized(self):
        declaration = SovereigntyDeclaration(
            system_id="test",
            system_name="test",
            declaration_version="1.0",
            declared_at=FIXED_NOW,
            declared_by="system",
            cryptographic_seal="seal",
        )
        permitted, reason = declaration.check_operation_permitted(
            SovereigntyDomain.GENERAL_LEDGER,
            "DELETE",
            "external",
        )
        assert permitted is False
        assert "not allowed" in reason

    def test_change_status_requires_approvers_for_downgrade(self):
        declaration = SovereigntyDeclaration(
            system_id="test",
            system_name="test",
            declaration_version="1.0",
            declared_at=FIXED_NOW,
            declared_by="system",
            cryptographic_seal="seal",
        )
        with pytest.raises(SovereigntyDeclarationError, match="requires at least 2 approvers"):
            declaration.change_status(
                SovereigntyStatus.DEGRADED,
                "Test downgrade",
                "admin",
                ["single_approver"],
            )

    def test_change_status_success(self):
        declaration = SovereigntyDeclaration(
            system_id="test",
            system_name="test",
            declaration_version="1.0",
            declared_at=FIXED_NOW,
            declared_by="system",
            cryptographic_seal="seal",
        )
        event = declaration.change_status(
            SovereigntyStatus.DEGRADED,
            "Performance issues",
            "admin",
            ["approver1", "approver2"],
            expiry_at=FIXED_FUTURE,
        )
        assert event.new_status == SovereigntyStatus.DEGRADED
        assert declaration.current_status == SovereigntyStatus.DEGRADED

    def test_change_status_to_emergency_lockdown_requires_emergency_admin(self):
        declaration = SovereigntyDeclaration(
            system_id="test",
            system_name="test",
            declaration_version="1.0",
            declared_at=FIXED_NOW,
            declared_by="system",
            cryptographic_seal="seal",
        )
        with pytest.raises(SovereigntyDeclarationError, match="requires emergency_admin approval"):
            declaration.change_status(
                SovereigntyStatus.EMERGENCY_LOCKDOWN,
                "Emergency",
                "admin",
                ["approver1", "approver2"],
            )

    def test_change_status_to_emergency_lockdown_with_emergency_admin(self):
        declaration = SovereigntyDeclaration(
            system_id="test",
            system_name="test",
            declaration_version="1.0",
            declared_at=FIXED_NOW,
            declared_by="system",
            cryptographic_seal="seal",
        )
        event = declaration.change_status(
            SovereigntyStatus.EMERGENCY_LOCKDOWN,
            "Emergency",
            "admin",
            ["approver1", "approver2", "emergency_admin"],
            expiry_at=FIXED_FUTURE,
        )
        assert event.new_status == SovereigntyStatus.EMERGENCY_LOCKDOWN
        assert declaration.current_status == SovereigntyStatus.EMERGENCY_LOCKDOWN

    def test_verify_seal_validation(self):
        now = FIXED_NOW
        content = f"test_system|test|1.0|{now.isoformat()}|system"
        seal = hashlib.sha3_256(content.encode()).hexdigest()
        declaration = SovereigntyDeclaration(
            system_id="test_system",
            system_name="test",
            declaration_version="1.0",
            declared_at=now,
            declared_by="system",
            cryptographic_seal=seal,
        )
        assert declaration.verify_seal() is True
        # Invalid seal
        declaration.cryptographic_seal = "invalid"
        assert declaration.verify_seal() is False

    def test_record_interference_creates_record(self):
        declaration = SovereigntyDeclaration(
            system_id="test",
            system_name="test",
            declaration_version="1.0",
            declared_at=FIXED_NOW,
            declared_by="system",
            cryptographic_seal="seal",
        )
        record = declaration.record_interference(
            interference_type=ExternalInterferenceType.UNAUTHORIZED_API_CALL,
            source_module="test_module",
            description="Test interference",
            payload_hash="abc123",
            severity=InterferenceSeverity.MEDIUM,
        )
        assert record is not None
        assert len(declaration.interference_log) == 1
        assert record.interference_type == ExternalInterferenceType.UNAUTHORIZED_API_CALL

    def test_record_interference_auto_lockdown_for_catastrophic(self):
        declaration = SovereigntyDeclaration(
            system_id="test",
            system_name="test",
            declaration_version="1.0",
            declared_at=FIXED_NOW,
            declared_by="system",
            cryptographic_seal="seal",
        )
        with patch.object(declaration, "change_status") as mock_change:
            record = declaration.record_interference(
                interference_type=ExternalInterferenceType.DATA_EXFILTRATION,
                source_module="test",
                description="Data exfiltration detected",
                payload_hash="abc",
                severity=InterferenceSeverity.CATASTROPHIC,
            )
            mock_change.assert_called_once()
            # Verify that change_status was called with EMERGENCY_LOCKDOWN
            args, _kwargs = mock_change.call_args
            assert args[0] == SovereigntyStatus.EMERGENCY_LOCKDOWN
        assert record is not None

    def test_generate_report(self):
        declaration = SovereigntyDeclaration(
            system_id="test",
            system_name="test",
            declaration_version="1.0",
            declared_at=FIXED_NOW,
            declared_by="system",
            cryptographic_seal="seal",
        )
        report = declaration.generate_report()
        assert report is not None
        assert report.current_status == declaration.current_status
        assert report.seal_valid is True

    def test_get_statistics(self):
        declaration = SovereigntyDeclaration(
            system_id="test",
            system_name="test",
            declaration_version="1.0",
            declared_at=FIXED_NOW,
            declared_by="system",
            cryptographic_seal="seal",
        )
        stats = declaration.get_statistics()
        assert "boundaries_count" in stats
        assert stats["boundaries_count"] > 0
        assert "seal_valid" in stats
        assert stats["current_status"] == "SOVEREIGN"

    def test_reset_restores_defaults(self):
        declaration = SovereigntyDeclaration(
            system_id="test",
            system_name="test",
            declaration_version="1.0",
            declared_at=FIXED_NOW,
            declared_by="system",
            cryptographic_seal="seal",
        )
        declaration.reset()
        assert len(declaration.boundaries) > 0
        assert len(declaration.status_history) == 1
        assert declaration.current_status == SovereigntyStatus.SOVEREIGN


# ============================================================================
# TESTS FOR SOVEREIGNTY GUARDIAN
# ============================================================================

class TestSovereigntyGuardian:
    def test_singleton(self):
        guardian1 = SovereigntyGuardian()
        guardian2 = SovereigntyGuardian()
        assert guardian1 is guardian2

    def test_guard_allows_authorized_operation(self):
        guardian = SovereigntyGuardian()
        result = guardian.guard(
            domain=SovereigntyDomain.GENERAL_LEDGER,
            operation="READ",
            source="internal_api",
            context={},
        )
        assert result is True

    def test_guard_denies_unauthorized_operation(self):
        guardian = SovereigntyGuardian()
        with pytest.raises(SovereigntyViolationError, match="not allowed"):
            guardian.guard(
                domain=SovereigntyDomain.GENERAL_LEDGER,
                operation="DELETE",
                source="external",
                context={},
            )

    def test_guard_raises_on_unresolved_critical_interference(self):
        guardian = SovereigntyGuardian()
        # Inject an unresolved critical interference
        rec = create_test_interference(severity=InterferenceSeverity.CRITICAL, mitigated=False)
        guardian._declaration.interference_log.append(rec)
        with pytest.raises(Exception):  # ExternalInterferenceDetectedError
            guardian.guard(
                domain=SovereigntyDomain.GENERAL_LEDGER,
                operation="READ",
                source="internal_api",
                context={},
            )

    def test_get_current_status(self):
        guardian = SovereigntyGuardian()
        status = guardian.get_current_status()
        assert status == SovereigntyStatus.SOVEREIGN

    def test_is_system_operational(self):
        guardian = SovereigntyGuardian()
        assert guardian.is_system_operational() is True
        # Change to degraded
        guardian._declaration.change_status(
            SovereigntyStatus.DEGRADED,
            "test",
            "admin",
            ["a", "b"],
            expiry_at=FIXED_FUTURE,
        )
        assert guardian.is_system_operational() is False

    def test_emergency_lockdown(self):
        guardian = SovereigntyGuardian()
        with patch.object(guardian._declaration, "change_status") as mock_change:
            event = MagicMock()
            mock_change.return_value = event
            result = guardian.emergency_lockdown("Critical", "admin")
            assert result is event
            mock_change.assert_called_once_with(
                SovereigntyStatus.EMERGENCY_LOCKDOWN,
                "Critical",
                "admin",
                ["admin"],
                expiry_at=FIXED_NOW + timedelta(hours=1),
            )

    def test_record_interference_delegates(self):
        guardian = SovereigntyGuardian()
        record = guardian.record_interference(
            interference_type=ExternalInterferenceType.UNAUTHORIZED_API_CALL,
            source_module="test",
            description="test",
            payload_hash="abc",
        )
        assert record is not None
        assert len(guardian._declaration.interference_log) == 1

    def test_generate_report(self):
        guardian = SovereigntyGuardian()
        report = guardian.generate_report()
        assert report is not None

    def test_get_boundary(self):
        guardian = SovereigntyGuardian()
        boundary = guardian.get_boundary(SovereigntyDomain.GENERAL_LEDGER)
        assert boundary is not None
        assert boundary.domain == SovereigntyDomain.GENERAL_LEDGER

    def test_get_statistics(self):
        guardian = SovereigntyGuardian()
        stats = guardian.get_statistics()
        assert "boundaries_count" in stats

    def test_reset(self):
        guardian = SovereigntyGuardian()
        guardian.reset()
        assert len(guardian._declaration.boundaries) > 0
        assert guardian._declaration.current_status == SovereigntyStatus.SOVEREIGN

    def test_get_sovereignty_guardian_singleton(self):
        guardian1 = get_sovereignty_guardian()
        guardian2 = get_sovereignty_guardian()
        assert guardian1 is guardian2


# ============================================================================
# PARAMETRIZED LIFECYCLE TESTS (untuk menghilangkan duplikasi)
# ============================================================================

# Daftar entity fixtures dan metode dasar yang didukung
ENTITY_LIFECYCLE = [
    (create_test_boundary, "SovereigntyBoundary", True, True, True),
    (create_test_event, "SovereigntyEvent", False, False, False),
    (create_test_interference, "InterferenceRecord", False, False, False),
    (create_test_report, "SovereigntyReport", False, False, False),
]


@pytest.mark.parametrize("creator,cls_name,upd,del_,res", ENTITY_LIFECYCLE)
def test_entity_create(creator, cls_name, upd, del_, res):
    entity = creator()
    result = entity.create("admin")
    assert result is entity


@pytest.mark.parametrize("creator,cls_name,upd,del_,res", ENTITY_LIFECYCLE)
def test_entity_activate(creator, cls_name, upd, del_, res):
    entity = creator()
    result = entity.activate("admin")
    assert result is entity


@pytest.mark.parametrize("creator,cls_name,upd,del_,res", ENTITY_LIFECYCLE)
def test_entity_deactivate(creator, cls_name, upd, del_, res):
    entity = creator()
    result = entity.deactivate("admin")
    assert result is entity


@pytest.mark.parametrize("creator,cls_name,upd,del_,res", ENTITY_LIFECYCLE)
def test_entity_lock(creator, cls_name, upd, del_, res):
    entity = creator()
    result = entity.lock("admin", "test")
    assert result is entity


@pytest.mark.parametrize("creator,cls_name,upd,del_,res", ENTITY_LIFECYCLE)
def test_entity_unlock(creator, cls_name, upd, del_, res):
    entity = creator()
    result = entity.unlock("admin")
    assert result is entity


@pytest.mark.parametrize("creator,cls_name,upd,del_,res", ENTITY_LIFECYCLE)
def test_entity_validate(creator, cls_name, upd, del_, res):
    entity = creator()
    result = entity.validate()
    assert result["is_valid"] is True


@pytest.mark.parametrize("creator,cls_name,upd,del_,res", ENTITY_LIFECYCLE)
def test_entity_touch(creator, cls_name, upd, del_, res):
    entity = creator()
    touched = entity.touch("admin")
    if cls_name == "SovereigntyBoundary":
        assert touched.version == entity.version + 1
        assert touched is not entity
    else:
        # Others return self (immutable)
        assert touched is entity
    trail = touched.audit_trail()
    assert len(trail) >= 1
    assert trail[-1]["action"] == "TOUCH"


@pytest.mark.parametrize("creator,cls_name,upd,del_,res", ENTITY_LIFECYCLE)
def test_entity_snapshot(creator, cls_name, upd, del_, res):
    entity = creator()
    snap = entity.snapshot()
    assert "version" in snap
    assert "timestamp" in snap


@pytest.mark.parametrize("creator,cls_name,upd,del_,res", ENTITY_LIFECYCLE)
def test_entity_audit_trail(creator, cls_name, upd, del_, res):
    entity = creator()
    trail = entity.audit_trail()
    assert len(trail) >= 1


@pytest.mark.parametrize("creator,cls_name,upd,del_,res", ENTITY_LIFECYCLE)
def test_entity_clone(creator, cls_name, upd, del_, res):
    entity = creator()
    cloned = entity.clone()
    assert cloned is not entity
    assert cloned.version == 1


@pytest.mark.parametrize("creator,cls_name,upd,del_,res", ENTITY_LIFECYCLE)
def test_entity_update(creator, cls_name, upd, del_, res):
    entity = creator()
    if not upd:
        with pytest.raises(AttributeError):
            entity.update("admin", some_field="value")
    else:
        # Only SovereigntyBoundary supports update
        if cls_name == "SovereigntyBoundary":
            updated = entity.update("admin", allowed_operations={"READ"})
            assert updated.allowed_operations == {"READ"}
            assert updated.version == entity.version + 1


@pytest.mark.parametrize("creator,cls_name,upd,del_,res", ENTITY_LIFECYCLE)
def test_entity_delete(creator, cls_name, upd, del_, res):
    entity = creator()
    if not del_:
        with pytest.raises(AttributeError):
            entity.delete("admin")
    else:
        # Only SovereigntyBoundary supports delete
        if cls_name == "SovereigntyBoundary":
            deleted = entity.delete("admin", "reason")
            assert deleted.version == entity.version + 1


@pytest.mark.parametrize("creator,cls_name,upd,del_,res", ENTITY_LIFECYCLE)
def test_entity_restore(creator, cls_name, upd, del_, res):
    entity = creator()
    if not res:
        with pytest.raises(AttributeError):
            entity.restore("admin")
    else:
        # Only SovereigntyBoundary supports restore
        if cls_name == "SovereigntyBoundary":
            restored = entity.restore("admin")
            assert restored.version == entity.version + 1


# ============================================================================
# ADDITIONAL TESTS FOR SOVEREIGNTY DECLARATION REPOSITORY METHODS
# ============================================================================

class TestSovereigntyDeclarationRepository:
    def test_save_and_get_boundary(self):
        dec = SovereigntyDeclaration(
            system_id="test", system_name="test", declaration_version="1.0",
            declared_at=FIXED_NOW, declared_by="system", cryptographic_seal="seal"
        )
        boundary = create_test_boundary()
        dec.save_boundary(boundary)
        retrieved = dec.get_boundary(boundary.domain)
        assert retrieved is not None
        assert retrieved.domain == boundary.domain

    def test_get_all_boundaries(self):
        dec = SovereigntyDeclaration(
            system_id="test", system_name="test", declaration_version="1.0",
            declared_at=FIXED_NOW, declared_by="system", cryptographic_seal="seal"
        )
        boundaries = dec.get_all_boundaries()
        assert len(boundaries) > 0

    def test_delete_boundary(self):
        dec = SovereigntyDeclaration(
            system_id="test", system_name="test", declaration_version="1.0",
            declared_at=FIXED_NOW, declared_by="system", cryptographic_seal="seal"
        )
        boundary = create_test_boundary()
        dec.save_boundary(boundary)
        result = dec.delete_boundary(boundary.domain)
        assert result is True
        assert dec.get_boundary(boundary.domain) is None

    def test_save_and_get_status_event(self):
        dec = SovereigntyDeclaration(
            system_id="test", system_name="test", declaration_version="1.0",
            declared_at=FIXED_NOW, declared_by="system", cryptographic_seal="seal"
        )
        event = create_test_event()
        dec.save_status_event(event)
        events = dec.get_status_events()
        assert len(events) >= 1
        assert events[-1].event_id == event.event_id

    def test_delete_status_event(self):
        dec = SovereigntyDeclaration(
            system_id="test", system_name="test", declaration_version="1.0",
            declared_at=FIXED_NOW, declared_by="system", cryptographic_seal="seal"
        )
        event = create_test_event()
        dec.save_status_event(event)
        result = dec.delete_status_event(event.event_id)
        assert result is True
        assert event.event_id not in [e.event_id for e in dec.status_history]

    def test_save_and_get_interference(self):
        dec = SovereigntyDeclaration(
            system_id="test", system_name="test", declaration_version="1.0",
            declared_at=FIXED_NOW, declared_by="system", cryptographic_seal="seal"
        )
        record = create_test_interference()
        dec.save_interference(record)
        interferences = dec.get_interferences()
        assert len(interferences) >= 1
        assert interferences[-1].record_id == record.record_id

    def test_get_interferences_unmitigated_only(self):
        dec = SovereigntyDeclaration(
            system_id="test", system_name="test", declaration_version="1.0",
            declared_at=FIXED_NOW, declared_by="system", cryptographic_seal="seal"
        )
        r1 = create_test_interference(mitigated=True)
        r2 = create_test_interference(mitigated=False)
        dec.save_interference(r1)
        dec.save_interference(r2)
        unmitigated = dec.get_interferences(only_unmitigated=True)
        assert len(unmitigated) == 1
        assert unmitigated[0].record_id == r2.record_id

    def test_delete_interference(self):
        dec = SovereigntyDeclaration(
            system_id="test", system_name="test", declaration_version="1.0",
            declared_at=FIXED_NOW, declared_by="system", cryptographic_seal="seal"
        )
        record = create_test_interference()
        dec.save_interference(record)
        result = dec.delete_interference(record.record_id)
        assert result is True
        assert record.record_id not in [r.record_id for r in dec.interference_log]
