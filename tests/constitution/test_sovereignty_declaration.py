#!/usr/bin/env python3
"""
tests/unit/test_sovereignty_declaration.py
Test untuk constitution/sovereignty_declaration.py
Mencakup: SovereigntyBoundary, SovereigntyEvent, InterferenceRecord,
SovereigntyReport, SovereigntyDeclaration, SovereigntyGuardian
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

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


class TestSovereigntyBoundary:
    def test_create_valid_boundary(self):
        """Test creation of valid SovereigntyBoundary."""
        boundary = SovereigntyBoundary(
            domain=SovereigntyDomain.GENERAL_LEDGER,
            allowed_operations={"CREATE", "READ", "UPDATE_VIA_REVERSAL_ONLY"},
            allowed_sources={"internal_api", "cli_authorized"},
            require_crypto_signature=True,
            audit_level=ConstitutionalSeverity.CRITICAL,
            max_external_calls_per_minute=0,
            require_dual_control=True,
            min_approvers=2,
        )
        assert boundary.domain == SovereigntyDomain.GENERAL_LEDGER
        assert boundary.require_crypto_signature is True
        assert boundary.require_dual_control is True
        assert boundary.min_approvers == 2
        assert boundary.version == 1

    def test_validate_min_approvers(self):
        """Test validation rejects min_approvers < 1."""
        with pytest.raises(ValueError, match="min_approvers must be at least 1"):
            SovereigntyBoundary(
                domain=SovereigntyDomain.GENERAL_LEDGER,
                allowed_operations=set(),
                allowed_sources=set(),
                require_crypto_signature=True,
                audit_level=ConstitutionalSeverity.CRITICAL,
                min_approvers=0,
            )

    def test_allows_operation_checks(self):
        """Test allows_operation checks operation and source."""
        boundary = SovereigntyBoundary(
            domain=SovereigntyDomain.GENERAL_LEDGER,
            allowed_operations={"CREATE", "READ"},
            allowed_sources={"internal_api"},
            require_crypto_signature=True,
            audit_level=ConstitutionalSeverity.CRITICAL,
        )
        assert boundary.allows_operation("CREATE", "internal_api") is True
        assert boundary.allows_operation("DELETE", "internal_api") is False
        assert boundary.allows_operation("CREATE", "external") is False

    def test_update_creates_new_version(self):
        """Test update creates new instance with incremented version."""
        boundary = SovereigntyBoundary(
            domain=SovereigntyDomain.GENERAL_LEDGER,
            allowed_operations={"CREATE"},
            allowed_sources={"internal_api"},
            require_crypto_signature=True,
            audit_level=ConstitutionalSeverity.CRITICAL,
        )
        updated = boundary.update("admin", allowed_operations={"CREATE", "READ"})
        assert updated.allowed_operations == {"CREATE", "READ"}
        assert updated.version == 2


class TestSovereigntyEvent:
    def test_create_valid_event(self):
        """Test creation of valid SovereigntyEvent."""
        now = datetime.now(UTC)
        event = SovereigntyEvent(
            event_id=uuid.uuid4(),
            previous_status=SovereigntyStatus.SOVEREIGN,
            new_status=SovereigntyStatus.DEGRADED,
            reason="Database performance issues",
            initiated_by="admin",
            initiated_at=now,
            approved_by=["approver1", "approver2"],
            affected_domains=[SovereigntyDomain.GENERAL_LEDGER],
            expiry_at=now + timedelta(hours=24),
        )
        assert event.previous_status == SovereigntyStatus.SOVEREIGN
        assert event.new_status == SovereigntyStatus.DEGRADED
        assert event.is_active() is True

    def test_is_active_handles_expiry(self):
        """Test is_active checks expiry."""
        now = datetime.now(UTC)
        event = SovereigntyEvent(
            event_id=uuid.uuid4(),
            previous_status=SovereigntyStatus.SOVEREIGN,
            new_status=SovereigntyStatus.DEGRADED,
            reason="test",
            initiated_by="admin",
            initiated_at=now,
            approved_by=["a"],
            affected_domains=[],
            expiry_at=now - timedelta(hours=1),
        )
        assert event.is_active() is False


class TestInterferenceRecord:
    def test_create_valid_record(self):
        """Test creation of valid InterferenceRecord."""
        now = datetime.now(UTC)
        record = InterferenceRecord(
            record_id=uuid.uuid4(),
            interference_type=ExternalInterferenceType.UNAUTHORIZED_API_CALL,
            detected_at=now,
            source_module="api_gateway",
            payload_hash="abc123",
            description="Unauthorized access attempt",
            mitigated=False,
            source_ip="192.168.1.1",
            severity=InterferenceSeverity.HIGH,
        )
        assert record.interference_type == ExternalInterferenceType.UNAUTHORIZED_API_CALL
        assert record.mitigated is False
        assert record.severity == InterferenceSeverity.HIGH
        assert record.version == 1

    def test_mark_mitigated_marks_resolved(self):
        """Test mark_mitigated marks record as mitigated."""
        now = datetime.now(UTC)
        record = InterferenceRecord(
            record_id=uuid.uuid4(),
            interference_type=ExternalInterferenceType.UNAUTHORIZED_API_CALL,
            detected_at=now,
            source_module="test",
            payload_hash="abc",
            description="test",
            mitigated=False,
        )
        mitigated = record.mark_mitigated("admin", "Blocked IP")
        assert mitigated.mitigated is True
        assert mitigated.mitigated_by == "admin"
        assert mitigated.mitigation_action == "Blocked IP"


class TestSovereigntyDeclaration:
    def test_create_valid_declaration(self):
        """Test creation of valid SovereigntyDeclaration."""
        now = datetime.now(UTC)
        declaration = SovereigntyDeclaration(
            system_id="erp_system",
            system_name="Enterprise ERP",
            declaration_version="1.0.0",
            declared_at=now,
            declared_by="system_bootstrap",
            cryptographic_seal="seal123",
        )
        assert declaration.system_id == "erp_system"
        assert declaration.current_status == SovereigntyStatus.SOVEREIGN
        assert len(declaration.boundaries) > 0

    def test_check_operation_permitted_allows(self):
        """Test check_operation_permitted allows authorized operation."""
        declaration = SovereigntyDeclaration(
            system_id="test",
            system_name="test",
            declaration_version="1.0",
            declared_at=datetime.now(UTC),
            declared_by="system",
            cryptographic_seal="seal",
        )
        permitted, reason = declaration.check_operation_permitted(
            SovereigntyDomain.GENERAL_LEDGER,
            "READ",
            "internal_api",
        )
        assert permitted is True
        assert reason == "OK"

    def test_check_operation_permitted_denies_unauthorized(self):
        """Test check_operation_permitted denies unauthorized operation."""
        declaration = SovereigntyDeclaration(
            system_id="test",
            system_name="test",
            declaration_version="1.0",
            declared_at=datetime.now(UTC),
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
        """Test change_status requires approvers for downgrade."""
        declaration = SovereigntyDeclaration(
            system_id="test",
            system_name="test",
            declaration_version="1.0",
            declared_at=datetime.now(UTC),
            declared_by="system",
            cryptographic_seal="seal",
        )
        with pytest.raises(SovereigntyDeclarationError, match="requires at least 2 approvers"):
            declaration.change_status(
                SovereigntyStatus.DEGRADED,
                "Test downgrade",
                "admin",
                ["single_approver"],  # only 1
            )

    def test_change_status_success(self):
        """Test change_status changes status successfully."""
        declaration = SovereigntyDeclaration(
            system_id="test",
            system_name="test",
            declaration_version="1.0",
            declared_at=datetime.now(UTC),
            declared_by="system",
            cryptographic_seal="seal",
        )
        event = declaration.change_status(
            SovereigntyStatus.DEGRADED,
            "Performance issues",
            "admin",
            ["approver1", "approver2"],
        )
        assert event.new_status == SovereigntyStatus.DEGRADED
        assert declaration.current_status == SovereigntyStatus.DEGRADED

    def test_verify_seal_validation(self):
        """Test verify_seal validates cryptographic seal."""
        now = datetime.now(UTC)
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
        """Test record_interference creates interference record."""
        declaration = SovereigntyDeclaration(
            system_id="test",
            system_name="test",
            declaration_version="1.0",
            declared_at=datetime.now(UTC),
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

    def test_record_interference_auto_lockdown_for_catastrophic(self):
        """Test record_interference auto-lockdown for catastrophic severity."""
        declaration = SovereigntyDeclaration(
            system_id="test",
            system_name="test",
            declaration_version="1.0",
            declared_at=datetime.now(UTC),
            declared_by="system",
            cryptographic_seal="seal",
        )
        with patch.object(declaration, "change_status") as mock_change:
            declaration.record_interference(
                interference_type=ExternalInterferenceType.DATA_EXFILTRATION,
                source_module="test",
                description="Data exfiltration detected",
                payload_hash="abc",
                severity=InterferenceSeverity.CATASTROPHIC,
            )
            mock_change.assert_called_once()

    def test_generate_report(self):
        """Test generate_report creates SovereigntyReport."""
        declaration = SovereigntyDeclaration(
            system_id="test",
            system_name="test",
            declaration_version="1.0",
            declared_at=datetime.now(UTC),
            declared_by="system",
            cryptographic_seal="seal",
        )
        report = declaration.generate_report()
        assert report is not None
        assert report.current_status == declaration.current_status
        assert report.seal_valid is True

    def test_get_statistics(self):
        """Test get_statistics returns summary."""
        declaration = SovereigntyDeclaration(
            system_id="test",
            system_name="test",
            declaration_version="1.0",
            declared_at=datetime.now(UTC),
            declared_by="system",
            cryptographic_seal="seal",
        )
        stats = declaration.get_statistics()
        assert "boundaries_count" in stats
        assert stats["boundaries_count"] > 0
        assert "seal_valid" in stats


class TestSovereigntyGuardian:
    def test_singleton(self):
        """Test SovereigntyGuardian is singleton."""
        guardian1 = SovereigntyGuardian()
        guardian2 = SovereigntyGuardian()
        assert guardian1 is guardian2

    def test_guard_allows_authorized_operation(self):
        """Test guard allows authorized operation."""
        guardian = SovereigntyGuardian()
        result = guardian.guard(
            domain=SovereigntyDomain.GENERAL_LEDGER,
            operation="READ",
            source="internal_api",
            context={},
        )
        assert result is True

    def test_guard_denies_unauthorized_operation(self):
        """Test guard denies unauthorized operation."""
        guardian = SovereigntyGuardian()
        with pytest.raises(SovereigntyViolationError, match="not allowed"):
            guardian.guard(
                domain=SovereigntyDomain.GENERAL_LEDGER,
                operation="DELETE",
                source="external",
                context={},
            )

    def test_get_current_status(self):
        """Test get_current_status returns current status."""
        guardian = SovereigntyGuardian()
        status = guardian.get_current_status()
        assert status == SovereigntyStatus.SOVEREIGN

    def test_emergency_lockdown(self):
        """Test emergency_lockdown changes status."""
        guardian = SovereigntyGuardian()
        event = guardian.emergency_lockdown("Critical emergency", "admin")
        assert event.new_status == SovereigntyStatus.EMERGENCY_LOCKDOWN

    def test_record_interference_delegates(self):
        """Test record_interference delegates to declaration."""
        guardian = SovereigntyGuardian()
        record = guardian.record_interference(
            interference_type=ExternalInterferenceType.UNAUTHORIZED_API_CALL,
            source_module="test",
            description="test",
            payload_hash="abc",
        )
        assert record is not None

    def test_generate_report(self):
        """Test generate_report returns report."""
        guardian = SovereigntyGuardian()
        report = guardian.generate_report()
        assert report is not None

    def test_get_sovereignty_guardian_singleton(self):
        """Test get_sovereignty_guardian returns singleton."""
        guardian1 = get_sovereignty_guardian()
        guardian2 = get_sovereignty_guardian()
        assert guardian1 is guardian2

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_test_boundary() -> SovereigntyBoundary:
    return SovereigntyBoundary(
        domain=SovereigntyDomain.GENERAL_LEDGER,
        allowed_operations={"READ"},
        allowed_sources={"internal"},
        require_crypto_signature=True,
        audit_level=ConstitutionalSeverity.MEDIUM,
    )


class TestSovereigntyBoundaryLifecycle:
    def test_create_returns_self(self):
        boundary = create_test_boundary()
        result = boundary.create("admin")
        assert result is boundary

    def test_activate_returns_self(self):
        boundary = create_test_boundary()
        result = boundary.activate("admin")
        assert result is boundary

    def test_deactivate_returns_self(self):
        boundary = create_test_boundary()
        result = boundary.deactivate("admin")
        assert result is boundary

    def test_lock_returns_self(self):
        boundary = create_test_boundary()
        result = boundary.lock("admin", "test")
        assert result is boundary

    def test_unlock_returns_self(self):
        boundary = create_test_boundary()
        result = boundary.unlock("admin")
        assert result is boundary

    def test_validate_returns_valid(self):
        boundary = create_test_boundary()
        result = boundary.validate()
        assert result["is_valid"] is True


class TestSovereigntyEventLifecycle:
    def test_create_returns_self(self):
        event = SovereigntyEvent(
            event_id=uuid.uuid4(),
            previous_status=SovereigntyStatus.SOVEREIGN,
            new_status=SovereigntyStatus.SOVEREIGN,
            reason="test",
            initiated_by="admin",
            initiated_at=datetime.now(UTC),
            approved_by=["a"],
            affected_domains=[],
        )
        result = event.create("admin")
        assert result is event

    def test_activate_returns_self(self):
        event = SovereigntyEvent(
            event_id=uuid.uuid4(),
            previous_status=SovereigntyStatus.SOVEREIGN,
            new_status=SovereigntyStatus.SOVEREIGN,
            reason="test",
            initiated_by="admin",
            initiated_at=datetime.now(UTC),
            approved_by=["a"],
            affected_domains=[],
        )
        result = event.activate("admin")
        assert result is event

    def test_deactivate_returns_self(self):
        event = SovereigntyEvent(
            event_id=uuid.uuid4(),
            previous_status=SovereigntyStatus.SOVEREIGN,
            new_status=SovereigntyStatus.SOVEREIGN,
            reason="test",
            initiated_by="admin",
            initiated_at=datetime.now(UTC),
            approved_by=["a"],
            affected_domains=[],
        )
        result = event.deactivate("admin")
        assert result is event

    def test_lock_returns_self(self):
        event = SovereigntyEvent(
            event_id=uuid.uuid4(),
            previous_status=SovereigntyStatus.SOVEREIGN,
            new_status=SovereigntyStatus.SOVEREIGN,
            reason="test",
            initiated_by="admin",
            initiated_at=datetime.now(UTC),
            approved_by=["a"],
            affected_domains=[],
        )
        result = event.lock("admin", "test")
        assert result is event

    def test_unlock_returns_self(self):
        event = SovereigntyEvent(
            event_id=uuid.uuid4(),
            previous_status=SovereigntyStatus.SOVEREIGN,
            new_status=SovereigntyStatus.SOVEREIGN,
            reason="test",
            initiated_by="admin",
            initiated_at=datetime.now(UTC),
            approved_by=["a"],
            affected_domains=[],
        )
        result = event.unlock("admin")
        assert result is event

    def test_validate_returns_valid(self):
        event = SovereigntyEvent(
            event_id=uuid.uuid4(),
            previous_status=SovereigntyStatus.SOVEREIGN,
            new_status=SovereigntyStatus.SOVEREIGN,
            reason="test",
            initiated_by="admin",
            initiated_at=datetime.now(UTC),
            approved_by=["a"],
            affected_domains=[],
        )
        result = event.validate()
        assert result["is_valid"] is True


class TestInterferenceRecordLifecycle:
    def test_create_returns_self(self):
        record = InterferenceRecord(
            record_id=uuid.uuid4(),
            interference_type=ExternalInterferenceType.UNAUTHORIZED_API_CALL,
            detected_at=datetime.now(UTC),
            source_module="test",
            payload_hash="abc",
            description="test",
            mitigated=False,
        )
        result = record.create("admin")
        assert result is record

    def test_activate_returns_self(self):
        record = InterferenceRecord(
            record_id=uuid.uuid4(),
            interference_type=ExternalInterferenceType.UNAUTHORIZED_API_CALL,
            detected_at=datetime.now(UTC),
            source_module="test",
            payload_hash="abc",
            description="test",
            mitigated=False,
        )
        result = record.activate("admin")
        assert result is record

    def test_deactivate_returns_self(self):
        record = InterferenceRecord(
            record_id=uuid.uuid4(),
            interference_type=ExternalInterferenceType.UNAUTHORIZED_API_CALL,
            detected_at=datetime.now(UTC),
            source_module="test",
            payload_hash="abc",
            description="test",
            mitigated=False,
        )
        result = record.deactivate("admin")
        assert result is record

    def test_lock_returns_self(self):
        record = InterferenceRecord(
            record_id=uuid.uuid4(),
            interference_type=ExternalInterferenceType.UNAUTHORIZED_API_CALL,
            detected_at=datetime.now(UTC),
            source_module="test",
            payload_hash="abc",
            description="test",
            mitigated=False,
        )
        result = record.lock("admin", "test")
        assert result is record

    def test_unlock_returns_self(self):
        record = InterferenceRecord(
            record_id=uuid.uuid4(),
            interference_type=ExternalInterferenceType.UNAUTHORIZED_API_CALL,
            detected_at=datetime.now(UTC),
            source_module="test",
            payload_hash="abc",
            description="test",
            mitigated=False,
        )
        result = record.unlock("admin")
        assert result is record

    def test_validate_returns_valid(self):
        record = InterferenceRecord(
            record_id=uuid.uuid4(),
            interference_type=ExternalInterferenceType.UNAUTHORIZED_API_CALL,
            detected_at=datetime.now(UTC),
            source_module="test",
            payload_hash="abc",
            description="test",
            mitigated=False,
        )
        result = record.validate()
        assert result["is_valid"] is True


class TestSovereigntyReportLifecycle:
    def test_create_returns_self(self):
        report = SovereigntyReport(
            report_id=uuid.uuid4(),
            generated_at=datetime.now(UTC),
            current_status=SovereigntyStatus.SOVEREIGN,
            active_domains=[],
            recent_interferences=[],
            recent_status_changes=[],
            seal_valid=True,
            recommendations=[],
        )
        result = report.create("admin")
        assert result is report

    def test_activate_returns_self(self):
        report = SovereigntyReport(
            report_id=uuid.uuid4(),
            generated_at=datetime.now(UTC),
            current_status=SovereigntyStatus.SOVEREIGN,
            active_domains=[],
            recent_interferences=[],
            recent_status_changes=[],
            seal_valid=True,
            recommendations=[],
        )
        result = report.activate("admin")
        assert result is report

    def test_deactivate_returns_self(self):
        report = SovereigntyReport(
            report_id=uuid.uuid4(),
            generated_at=datetime.now(UTC),
            current_status=SovereigntyStatus.SOVEREIGN,
            active_domains=[],
            recent_interferences=[],
            recent_status_changes=[],
            seal_valid=True,
            recommendations=[],
        )
        result = report.deactivate("admin")
        assert result is report

    def test_lock_returns_self(self):
        report = SovereigntyReport(
            report_id=uuid.uuid4(),
            generated_at=datetime.now(UTC),
            current_status=SovereigntyStatus.SOVEREIGN,
            active_domains=[],
            recent_interferences=[],
            recent_status_changes=[],
            seal_valid=True,
            recommendations=[],
        )
        result = report.lock("admin", "test")
        assert result is report

    def test_unlock_returns_self(self):
        report = SovereigntyReport(
            report_id=uuid.uuid4(),
            generated_at=datetime.now(UTC),
            current_status=SovereigntyStatus.SOVEREIGN,
            active_domains=[],
            recent_interferences=[],
            recent_status_changes=[],
            seal_valid=True,
            recommendations=[],
        )
        result = report.unlock("admin")
        assert result is report

    def test_validate_returns_valid(self):
        report = SovereigntyReport(
            report_id=uuid.uuid4(),
            generated_at=datetime.now(UTC),
            current_status=SovereigntyStatus.SOVEREIGN,
            active_domains=[],
            recent_interferences=[],
            recent_status_changes=[],
            seal_valid=True,
            recommendations=[],
        )
        result = report.validate()
        assert result["is_valid"] is True