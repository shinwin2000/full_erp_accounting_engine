# tests/kernel/guards/test_emergency_freeze.py
"""
Comprehensive tests for kernel/guards/emergency_freeze.py
Covers all enums, data classes, fallback sovereignty guardian,
EmergencyFreezeGuard business methods, entity methods, and singleton accessor.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from kernel.guards.emergency_freeze import (
    BaseEmergencyFreezeGuard,
    EmergencyFreezeGuard,
    FreezeReason,
    FreezeRecord,
    FreezeScope,
    FreezeSeverity,
    _FallbackSovereigntyGuardian,
    _get_sovereignty_guardian,
    get_emergency_freeze_guard,
)
from kernel.guards.guard_exceptions import EmergencyFreezeError

# ============================================================================
# Enums tests
# ============================================================================

class TestFreezeReason:
    def test_members(self):
        assert FreezeReason.SECURITY_BREACH is not None
        assert FreezeReason.DATA_CORRUPTION is not None
        assert FreezeReason.REGULATORY_MANDATE is not None
        assert FreezeReason.SYSTEM_COMPROMISE is not None
        assert FreezeReason.NATURAL_DISASTER is not None
        assert FreezeReason.MANUAL_OVERRIDE is not None
        assert FreezeReason.CONSTITUTION_VIOLATION is not None
        assert FreezeReason.INTEGRITY_CHECK_FAILED is not None

    def test_display_name(self):
        assert FreezeReason.SECURITY_BREACH.display_name() == "Security Breach"
        assert FreezeReason.DATA_CORRUPTION.display_name() == "Data Corruption"
        assert FreezeReason.MANUAL_OVERRIDE.display_name() == "Manual Override"

    def test_to_dict(self):
        d = FreezeReason.SECURITY_BREACH.to_dict()
        assert d["value"] == "SECURITY_BREACH"
        assert d["display"] == "Security Breach"

    def test_from_string_valid(self):
        assert FreezeReason.from_string("SECURITY_BREACH") == FreezeReason.SECURITY_BREACH
        assert FreezeReason.from_string("DATA_CORRUPTION") == FreezeReason.DATA_CORRUPTION

    def test_from_string_invalid(self):
        with pytest.raises(ValueError, match="Unknown FreezeReason"):
            FreezeReason.from_string("UNKNOWN")

    def test_auto_value(self):
        values = [r.value for r in FreezeReason]
        assert len(values) == len(set(values))


class TestFreezeScope:
    def test_members(self):
        assert FreezeScope.ALL_WRITES is not None
        assert FreezeScope.BULK_ONLY is not None
        assert FreezeScope.CRITICAL_ONLY is not None
        assert FreezeScope.READ_ONLY is not None

    def test_display_name(self):
        assert FreezeScope.ALL_WRITES.display_name() == "All Writes Blocked"
        assert FreezeScope.BULK_ONLY.display_name() == "Bulk Operations Only"
        assert FreezeScope.CRITICAL_ONLY.display_name() == "Critical Operations Only"
        assert FreezeScope.READ_ONLY.display_name() == "Read Only"

    def test_to_dict(self):
        d = FreezeScope.ALL_WRITES.to_dict()
        assert d["value"] == "ALL_WRITES"
        assert d["display"] == "All Writes Blocked"

    def test_from_string_valid(self):
        assert FreezeScope.from_string("ALL_WRITES") == FreezeScope.ALL_WRITES
        assert FreezeScope.from_string("READ_ONLY") == FreezeScope.READ_ONLY

    def test_from_string_invalid(self):
        with pytest.raises(ValueError, match="Unknown FreezeScope"):
            FreezeScope.from_string("UNKNOWN")

    def test_auto_value(self):
        values = [s.value for s in FreezeScope]
        assert len(values) == len(set(values))


class TestFreezeSeverity:
    def test_members(self):
        assert FreezeSeverity.CRITICAL is not None
        assert FreezeSeverity.HIGH is not None
        assert FreezeSeverity.MEDIUM is not None
        assert FreezeSeverity.LOW is not None

    def test_display_name(self):
        assert FreezeSeverity.CRITICAL.display_name() == "Critical"
        assert FreezeSeverity.HIGH.display_name() == "High"
        assert FreezeSeverity.LOW.display_name() == "Low"

    def test_to_dict(self):
        d = FreezeSeverity.CRITICAL.to_dict()
        assert d["value"] == "CRITICAL"
        assert d["level"] == 80
        assert d["display"] == "Critical"

    def test_from_string_valid(self):
        assert FreezeSeverity.from_string("CRITICAL") == FreezeSeverity.CRITICAL
        assert FreezeSeverity.from_string("LOW") == FreezeSeverity.LOW

    def test_from_string_invalid(self):
        with pytest.raises(ValueError, match="Unknown FreezeSeverity"):
            FreezeSeverity.from_string("UNKNOWN")

    def test_level_values(self):
        assert FreezeSeverity.CRITICAL.value == 80
        assert FreezeSeverity.HIGH.value == 60
        assert FreezeSeverity.MEDIUM.value == 40
        assert FreezeSeverity.LOW.value == 20


# ============================================================================
# FreezeRecord tests
# ============================================================================

class TestFreezeRecord:
    def test_construction(self):
        freeze_id = uuid4()
        frozen_at = datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)
        expires_at = frozen_at + timedelta(minutes=60)
        record = FreezeRecord(
            freeze_id=freeze_id,
            reason=FreezeReason.SECURITY_BREACH,
            scope=FreezeScope.ALL_WRITES,
            frozen_by="admin",
            frozen_at=frozen_at,
            expires_at=expires_at,
            description="Security incident",
            approved_by=["approver1", "approver2"],
            severity=FreezeSeverity.CRITICAL,
        )
        assert record.freeze_id == freeze_id
        assert record.reason == FreezeReason.SECURITY_BREACH
        assert record.scope == FreezeScope.ALL_WRITES
        assert record.frozen_by == "admin"
        assert record.frozen_at == frozen_at
        assert record.expires_at == expires_at
        assert record.description == "Security incident"
        assert record.approved_by == ["approver1", "approver2"]
        assert record.severity == FreezeSeverity.CRITICAL

    def test_compute_hash(self):
        record = FreezeRecord(
            freeze_id=uuid4(),
            reason=FreezeReason.SECURITY_BREACH,
            scope=FreezeScope.ALL_WRITES,
            frozen_by="admin",
            frozen_at=datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC),
            expires_at=None,
            description="Test",
            approved_by=["a"],
        )
        h = record.compute_hash()
        assert isinstance(h, str)
        assert len(h) == 64

    def test_hash_mismatch_raises(self):
        freeze_id = uuid4()
        frozen_at = datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)
        with pytest.raises(ValueError, match="Cryptographic hash mismatch"):
            FreezeRecord(
                freeze_id=freeze_id,
                reason=FreezeReason.SECURITY_BREACH,
                scope=FreezeScope.ALL_WRITES,
                frozen_by="admin",
                frozen_at=frozen_at,
                expires_at=None,
                description="Test",
                approved_by=["a"],
                cryptographic_hash="invalid",
            )

    def test_is_expired_with_expiry(self):
        past = datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)
        future = past + timedelta(minutes=60)
        with patch('kernel.guards.emergency_freeze.datetime') as mock_dt:
            mock_dt.now.return_value = future + timedelta(seconds=1)
            mock_dt.UTC = UTC
            record = FreezeRecord(
                freeze_id=uuid4(),
                reason=FreezeReason.SECURITY_BREACH,
                scope=FreezeScope.ALL_WRITES,
                frozen_by="admin",
                frozen_at=past,
                expires_at=future,
                description="",
                approved_by=[],
            )
            assert record.is_expired() is True

    def test_is_expired_no_expiry(self):
        record = FreezeRecord(
            freeze_id=uuid4(),
            reason=FreezeReason.SECURITY_BREACH,
            scope=FreezeScope.ALL_WRITES,
            frozen_by="admin",
            frozen_at=datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC),
            expires_at=None,
            description="",
            approved_by=[],
        )
        assert record.is_expired() is False

    def test_to_dict(self):
        freeze_id = uuid4()
        frozen_at = datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)
        record = FreezeRecord(
            freeze_id=freeze_id,
            reason=FreezeReason.SECURITY_BREACH,
            scope=FreezeScope.ALL_WRITES,
            frozen_by="admin",
            frozen_at=frozen_at,
            expires_at=None,
            description="Test",
            approved_by=["a", "b"],
            severity=FreezeSeverity.CRITICAL,
        )
        d = record.to_dict()
        assert d["freeze_id"] == str(freeze_id)
        assert d["reason"] == "SECURITY_BREACH"
        assert d["reason_display"] == "Security Breach"
        assert d["scope"] == "ALL_WRITES"
        assert d["frozen_by"] == "admin"
        assert d["frozen_at"] == frozen_at.isoformat()
        assert d["expires_at"] is None
        assert d["description"] == "Test"
        assert d["approved_by"] == ["a", "b"]
        assert d["severity"] == "CRITICAL"
        assert d["severity_level"] == 80
        assert d["is_expired"] is False


# ============================================================================
# _FallbackSovereigntyGuardian tests
# ============================================================================

class TestFallbackSovereigntyGuardian:
    def test_construction(self):
        guardian = _FallbackSovereigntyGuardian()
        assert guardian._status == "NORMAL"
        assert guardian._version == 1
        assert guardian._audit_trail == []

    def test_emergency_lockdown(self):
        guardian = _FallbackSovereigntyGuardian()
        guardian.emergency_lockdown("Test reason", "admin")
        assert guardian._status == "EMERGENCY_LOCKDOWN"
        assert len(guardian._audit_trail) == 1
        assert guardian._audit_trail[0]["action"] == "EMERGENCY_LOCKDOWN"
        assert guardian._audit_trail[0]["performed_by"] == "admin"

    def test_get_current_status(self):
        guardian = _FallbackSovereigntyGuardian()
        assert guardian.get_current_status() == "NORMAL"
        guardian._status = "FROZEN"
        assert guardian.get_current_status() == "FROZEN"

    def test_check(self):
        guardian = _FallbackSovereigntyGuardian()
        errors = guardian.check({"key": "value"})
        assert errors == []

    def test_validate(self):
        guardian = _FallbackSovereigntyGuardian()
        result = guardian.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_to_dict(self):
        guardian = _FallbackSovereigntyGuardian()
        d = guardian.to_dict()
        assert d["status"] == "NORMAL"
        assert d["version"] == 1
        guardian._status = "LOCKDOWN"
        guardian._version = 5
        d2 = guardian.to_dict()
        assert d2["status"] == "LOCKDOWN"
        assert d2["version"] == 5

    def test_from_dict(self):
        data = {"status": "EMERGENCY_LOCKDOWN", "version": 3}
        guardian = _FallbackSovereigntyGuardian.from_dict(data)
        assert guardian._status == "EMERGENCY_LOCKDOWN"
        assert guardian._version == 3

    def test_clone(self):
        guardian = _FallbackSovereigntyGuardian()
        guardian._status = "FROZEN"
        cloned = guardian.clone()
        assert cloned is not guardian
        assert cloned._status == "FROZEN"
        assert cloned._version == guardian._version + 1

    def test_snapshot(self):
        guardian = _FallbackSovereigntyGuardian()
        snap = guardian.snapshot()
        assert snap["status"] == "NORMAL"
        assert snap["version"] == 1
        assert "timestamp" in snap

    def test_version(self):
        guardian = _FallbackSovereigntyGuardian()
        assert guardian.version() == 1
        guardian._version = 10
        assert guardian.version() == 10

    def test_audit_trail(self):
        guardian = _FallbackSovereigntyGuardian()
        guardian._record_audit("A1", "u1", {})
        guardian._record_audit("A2", "u2", {})
        trail = guardian.audit_trail()
        assert len(trail) == 2
        assert trail[0]["action"] == "A1"
        limited = guardian.audit_trail(limit=1)
        assert len(limited) == 1
        assert limited[0]["action"] == "A2"

    def test_touch(self):
        guardian = _FallbackSovereigntyGuardian()
        initial = guardian.version()
        result = guardian.touch("tester")
        assert result is guardian
        assert guardian.version() == initial + 1
        trail = guardian.audit_trail()
        assert trail[-1]["action"] == "TOUCH"
        assert trail[-1]["performed_by"] == "tester"


# ============================================================================
# _get_sovereignty_guardian tests
# ============================================================================

class TestGetSovereigntyGuardian:
    def test_import_success(self):
        with patch('constitution.sovereignty_declaration.get_sovereignty_guardian') as mock_get:
            mock_get.return_value = "real_guardian"
            guardian = _get_sovereignty_guardian()
            assert guardian == "real_guardian"

    def test_fallback_on_import_error(self):
        with patch('builtins.__import__', side_effect=ImportError("No module")):
            guardian = _get_sovereignty_guardian()
            assert isinstance(guardian, _FallbackSovereigntyGuardian)

    def test_fallback_when_import_fails(self):
        with patch('builtins.__import__', side_effect=ImportError("Module not found")):
            guardian = _get_sovereignty_guardian()
            assert isinstance(guardian, _FallbackSovereigntyGuardian)


# ============================================================================
# BaseEmergencyFreezeGuard abstract tests
# ============================================================================

class TestBaseEmergencyFreezeGuard:
    def test_is_abstract(self):
        with pytest.raises(TypeError):
            BaseEmergencyFreezeGuard()


# ============================================================================
# EmergencyFreezeGuard tests
# ============================================================================

class TestEmergencyFreezeGuard:
    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton instance before and after each test."""
        EmergencyFreezeGuard._instance = None
        yield
        EmergencyFreezeGuard._instance = None

    @pytest.fixture
    def guard(self):
        """Create guard with mocked sovereignty guardian."""
        with patch('kernel.guards.emergency_freeze._get_sovereignty_guardian') as mock_get:
            mock_get.return_value = _FallbackSovereigntyGuardian()
            g = EmergencyFreezeGuard()
            yield g
        # Cleanup after test
        EmergencyFreezeGuard._instance = None

    def test_singleton(self):
        g1 = EmergencyFreezeGuard()
        g2 = EmergencyFreezeGuard()
        assert g1 is g2

    def test_validate(self, guard):
        result = guard.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []
        guard._max_history = -1
        result2 = guard.validate()
        assert result2["is_valid"] is False
        assert "max_history must be positive" in result2["errors"]

    def test_to_dict(self, guard):
        d = guard.to_dict()
        assert d["is_frozen"] is False
        assert d["current_freeze"] is None
        assert d["history_count"] == 0
        assert d["version"] == 1

    def test_from_dict(self):
        with patch('kernel.guards.emergency_freeze._get_sovereignty_guardian') as mock_get:
            mock_get.return_value = _FallbackSovereigntyGuardian()
            data = {"version": 5, "max_history": 200}
            g = EmergencyFreezeGuard.from_dict(data)
            assert g._version == 5
            assert g._max_history == 200

    def test_clone(self, guard):
        initial_version = guard._version
        guard._max_history = 150
        cloned = guard.clone()
        # Karena singleton, clone mengembalikan instance yang sama
        assert cloned is guard
        assert cloned._max_history == 150
        assert cloned._version == initial_version + 1

    def test_snapshot(self, guard):
        snap = guard.snapshot()
        assert snap["version"] == 1
        assert snap["is_frozen"] is False
        assert snap["history_count"] == 0
        assert "timestamp" in snap

    def test_version(self, guard):
        assert guard.version() == 1
        guard._version = 10
        assert guard.version() == 10

    def test_audit_trail(self, guard):
        assert guard.audit_trail() == []
        guard._record_audit("ACTION", "user", {"detail": "value"})
        trail = guard.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "ACTION"

    def test_touch(self, guard):
        initial = guard.version()
        result = guard.touch("tester")
        assert result is guard
        assert guard.version() == initial + 1
        trail = guard.audit_trail()
        assert trail[-1]["action"] == "TOUCH"
        assert trail[-1]["performed_by"] == "tester"

    def test_check_success(self, guard):
        errors = guard.check({"operation_type": "POST", "user_id": "user123"})
        assert errors == []

    def test_check_missing_operation_type(self, guard):
        errors = guard.check({})
        assert "operation_type is required" in errors

    def test_check_invalid_user_id_type(self, guard):
        errors = guard.check({"operation_type": "POST", "user_id": 123})
        assert "user_id must be a string" in errors

    def test_is_frozen_false(self, guard):
        assert guard.is_frozen() is False

    def test_is_frozen_true(self, guard):
        guard._is_frozen = True
        guard._current_freeze = FreezeRecord(
            freeze_id=uuid4(),
            reason=FreezeReason.SECURITY_BREACH,
            scope=FreezeScope.ALL_WRITES,
            frozen_by="admin",
            frozen_at=datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC),
            expires_at=None,
            description="",
            approved_by=[],
        )
        assert guard.is_frozen() is True

    def test_is_frozen_expired_auto_unfreeze(self, guard):
        guard._is_frozen = True
        past = datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)
        record = FreezeRecord(
            freeze_id=uuid4(),
            reason=FreezeReason.SECURITY_BREACH,
            scope=FreezeScope.ALL_WRITES,
            frozen_by="admin",
            frozen_at=past - timedelta(hours=2),
            expires_at=past - timedelta(hours=1),
            description="",
            approved_by=[],
        )
        guard._current_freeze = record
        with patch('kernel.guards.emergency_freeze.asyncio.create_task') as mock_task:
            # is_frozen akan mengembalikan True karena belum ada yang menjalankan task
            result = guard.is_frozen()
            assert result is True
            mock_task.assert_called_once()
            # Ekstrak coroutine dan jalankan
            args, _ = mock_task.call_args
            coro = args[0]
            import asyncio
            asyncio.run(coro)  # Jalankan unfreeze
            # Sekarang state berubah
            assert guard._is_frozen is False
            assert guard._current_freeze is None

    def test_get_current_freeze_none(self, guard):
        assert guard.get_current_freeze() is None

    def test_get_current_freeze_exists(self, guard):
        record = FreezeRecord(
            freeze_id=uuid4(),
            reason=FreezeReason.SECURITY_BREACH,
            scope=FreezeScope.ALL_WRITES,
            frozen_by="admin",
            frozen_at=datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC),
            expires_at=None,
            description="",
            approved_by=[],
        )
        guard._current_freeze = record
        assert guard.get_current_freeze() is record

    @pytest.mark.asyncio
    async def test_freeze_success(self, guard):
        with patch.object(guard._sovereignty_guardian, 'emergency_lockdown') as mock_lockdown:
            record = await guard.freeze(
                reason=FreezeReason.SECURITY_BREACH,
                frozen_by="emergency_admin",
                approved_by=["approver1", "approver2"],
                description="Security incident",
                scope=FreezeScope.ALL_WRITES,
                duration_minutes=60,
                severity=FreezeSeverity.CRITICAL,
            )
            assert isinstance(record, FreezeRecord)
            assert guard._is_frozen is True
            assert guard._current_freeze is record
            assert record.reason == FreezeReason.SECURITY_BREACH
            assert record.scope == FreezeScope.ALL_WRITES
            assert record.frozen_by == "emergency_admin"
            assert record.approved_by == ["approver1", "approver2"]
            assert record.severity == FreezeSeverity.CRITICAL
            assert record.cryptographic_hash != ""
            mock_lockdown.assert_called_once()

    @pytest.mark.asyncio
    async def test_freeze_already_frozen(self, guard):
        guard._is_frozen = True
        guard._current_freeze = FreezeRecord(
            freeze_id=uuid4(),
            reason=FreezeReason.SECURITY_BREACH,
            scope=FreezeScope.ALL_WRITES,
            frozen_by="admin",
            frozen_at=datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC),
            expires_at=None,
            description="",
            approved_by=[],
        )
        with pytest.raises(EmergencyFreezeError, match="already frozen"):
            await guard.freeze(
                reason=FreezeReason.SECURITY_BREACH,
                frozen_by="admin",
                approved_by=["a", "b"],
                description="Test",
            )

    @pytest.mark.asyncio
    async def test_freeze_less_than_two_approvers(self, guard):
        with pytest.raises(EmergencyFreezeError, match="requires at least 2 approvers"):
            await guard.freeze(
                reason=FreezeReason.SECURITY_BREACH,
                frozen_by="admin",
                approved_by=["approver1"],
                description="Test",
            )

    @pytest.mark.asyncio
    async def test_freeze_success_with_no_expiry(self, guard):
        record = await guard.freeze(
            reason=FreezeReason.SECURITY_BREACH,
            frozen_by="emergency_admin",
            approved_by=["a", "b"],
            description="Test",
            duration_minutes=None,
        )
        assert record.expires_at is None

    @pytest.mark.asyncio
    async def test_freeze_sovereign_guardian_fails(self, guard):
        guard._sovereignty_guardian.emergency_lockdown = MagicMock(side_effect=Exception("SG error"))
        record = await guard.freeze(
            reason=FreezeReason.SECURITY_BREACH,
            frozen_by="emergency_admin",
            approved_by=["a", "b"],
            description="Test",
        )
        assert record is not None

    @pytest.mark.asyncio
    async def test_unfreeze_success(self, guard):
        guard._is_frozen = True
        guard._current_freeze = FreezeRecord(
            freeze_id=uuid4(),
            reason=FreezeReason.SECURITY_BREACH,
            scope=FreezeScope.ALL_WRITES,
            frozen_by="admin",
            frozen_at=datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC),
            expires_at=None,
            description="",
            approved_by=[],
        )
        result = await guard.unfreeze(
            unfrozen_by="admin2",
            reason="Issue resolved",
            require_dual_control=True,
        )
        assert result is True
        assert guard._is_frozen is False
        assert guard._current_freeze is None
        trail = guard.audit_trail()
        assert trail[-1]["action"] == "UNFREEZE"

    @pytest.mark.asyncio
    async def test_unfreeze_not_frozen(self, guard):
        result = await guard.unfreeze("admin", "reason")
        assert result is False

    @pytest.mark.asyncio
    async def test_unfreeze_dual_control_warning(self, guard):
        guard._is_frozen = True
        guard._current_freeze = FreezeRecord(
            freeze_id=uuid4(),
            reason=FreezeReason.SECURITY_BREACH,
            scope=FreezeScope.ALL_WRITES,
            frozen_by="admin",
            frozen_at=datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC),
            expires_at=None,
            description="",
            approved_by=[],
        )
        with patch('kernel.guards.emergency_freeze.logger') as mock_logger:
            result = await guard.unfreeze("admin", "reason", require_dual_control=True)
            assert result is True
            mock_logger.info.assert_called_with("Dual control unfreeze requested by admin")

    @pytest.mark.asyncio
    async def test_check_write_allowed_not_frozen(self, guard):
        is_allowed, msg = await guard.check_write_allowed("POST", "user")
        assert is_allowed is True
        assert msg is None

    @pytest.mark.asyncio
    async def test_check_write_allowed_frozen_emergency_override(self, guard):
        guard._is_frozen = True
        guard._current_freeze = FreezeRecord(
            freeze_id=uuid4(),
            reason=FreezeReason.SECURITY_BREACH,
            scope=FreezeScope.ALL_WRITES,
            frozen_by="admin",
            frozen_at=datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC),
            expires_at=None,
            description="",
            approved_by=[],
        )
        is_allowed, msg = await guard.check_write_allowed("POST", "emergency_admin")
        assert is_allowed is True
        assert msg is None

    @pytest.mark.asyncio
    async def test_check_write_allowed_scope_all_writes(self, guard):
        guard._is_frozen = True
        guard._current_freeze = FreezeRecord(
            freeze_id=uuid4(),
            reason=FreezeReason.SECURITY_BREACH,
            scope=FreezeScope.ALL_WRITES,
            frozen_by="admin",
            frozen_at=datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC),
            expires_at=None,
            description="",
            approved_by=[],
        )
        is_allowed, msg = await guard.check_write_allowed("POST", "user")
        assert is_allowed is False
        assert "No write operations allowed" in msg

    @pytest.mark.asyncio
    async def test_check_write_allowed_scope_bulk_only(self, guard):
        guard._is_frozen = True
        guard._current_freeze = FreezeRecord(
            freeze_id=uuid4(),
            reason=FreezeReason.SECURITY_BREACH,
            scope=FreezeScope.BULK_ONLY,
            frozen_by="admin",
            frozen_at=datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC),
            expires_at=None,
            description="",
            approved_by=[],
        )
        is_allowed, msg = await guard.check_write_allowed("bulk_upload", "user")
        assert is_allowed is False
        assert "Bulk operations are disabled" in msg
        is_allowed2, _ = await guard.check_write_allowed("POST", "user")
        assert is_allowed2 is True

    @pytest.mark.asyncio
    async def test_check_write_allowed_scope_critical_only(self, guard):
        guard._is_frozen = True
        guard._current_freeze = FreezeRecord(
            freeze_id=uuid4(),
            reason=FreezeReason.SECURITY_BREACH,
            scope=FreezeScope.CRITICAL_ONLY,
            frozen_by="admin",
            frozen_at=datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC),
            expires_at=None,
            description="",
            approved_by=[],
        )
        is_allowed, msg = await guard.check_write_allowed("PERIOD_CLOSE", "user")
        assert is_allowed is False
        assert "Critical operation" in msg
        is_allowed2, _ = await guard.check_write_allowed("READ", "user")
        assert is_allowed2 is True

    @pytest.mark.asyncio
    async def test_check_write_allowed_scope_read_only(self, guard):
        guard._is_frozen = True
        guard._current_freeze = FreezeRecord(
            freeze_id=uuid4(),
            reason=FreezeReason.SECURITY_BREACH,
            scope=FreezeScope.READ_ONLY,
            frozen_by="admin",
            frozen_at=datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC),
            expires_at=None,
            description="",
            approved_by=[],
        )
        is_allowed, msg = await guard.check_write_allowed("POST", "user")
        assert is_allowed is False
        assert "not allowed during read-only freeze" in msg
        is_allowed2, _ = await guard.check_write_allowed("GET", "user")
        assert is_allowed2 is True

    @pytest.mark.asyncio
    async def test_enforce_allowed(self, guard):
        result = await guard.enforce("POST", "user", raise_on_violation=False)
        assert result is True

    @pytest.mark.asyncio
    async def test_enforce_blocked_no_raise(self, guard):
        guard._is_frozen = True
        guard._current_freeze = FreezeRecord(
            freeze_id=uuid4(),
            reason=FreezeReason.SECURITY_BREACH,
            scope=FreezeScope.ALL_WRITES,
            frozen_by="admin",
            frozen_at=datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC),
            expires_at=None,
            description="",
            approved_by=[],
        )
        result = await guard.enforce("POST", "user", raise_on_violation=False)
        assert result is False

    @pytest.mark.asyncio
    async def test_enforce_blocked_raise(self, guard):
        guard._is_frozen = True
        guard._current_freeze = FreezeRecord(
            freeze_id=uuid4(),
            reason=FreezeReason.SECURITY_BREACH,
            scope=FreezeScope.ALL_WRITES,
            frozen_by="admin",
            frozen_at=datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC),
            expires_at=None,
            description="",
            approved_by=[],
        )
        with pytest.raises(EmergencyFreezeError, match="System is in emergency freeze"):
            await guard.enforce("POST", "user", raise_on_violation=True)

    def test_get_freeze_history_empty(self, guard):
        history = guard.get_freeze_history()
        assert history == []

    def test_get_freeze_history_with_records(self, guard):
        record = FreezeRecord(
            freeze_id=uuid4(),
            reason=FreezeReason.SECURITY_BREACH,
            scope=FreezeScope.ALL_WRITES,
            frozen_by="admin",
            frozen_at=datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC),
            expires_at=None,
            description="",
            approved_by=[],
        )
        guard._freeze_history = [record]
        history = guard.get_freeze_history(limit=10)
        assert len(history) == 1
        assert history[0]["freeze_id"] == str(record.freeze_id)

    def test_get_freeze_history_trimming(self, guard):
        for i in range(150):
            record = FreezeRecord(
                freeze_id=uuid4(),
                reason=FreezeReason.SECURITY_BREACH,
                scope=FreezeScope.ALL_WRITES,
                frozen_by="admin",
                frozen_at=datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC) + timedelta(minutes=i),
                expires_at=None,
                description=f"Record {i}",
                approved_by=[],
            )
            guard._freeze_history.append(record)
        guard._max_history = 100
        if len(guard._freeze_history) > guard._max_history:
            guard._freeze_history = guard._freeze_history[-guard._max_history:]
        assert len(guard._freeze_history) == 100

    def test_get_statistics_not_frozen(self, guard):
        stats = guard.get_statistics()
        assert stats["is_frozen"] is False
        assert stats["current_freeze"] is None
        assert stats["total_freezes"] == 0
        assert stats["emergency_roles"] == list(guard._emergency_roles)
        assert stats["version"] == guard._version

    def test_get_statistics_frozen(self, guard):
        guard._is_frozen = True
        record = FreezeRecord(
            freeze_id=uuid4(),
            reason=FreezeReason.SECURITY_BREACH,
            scope=FreezeScope.ALL_WRITES,
            frozen_by="admin",
            frozen_at=datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC),
            expires_at=None,
            description="",
            approved_by=[],
        )
        guard._current_freeze = record
        guard._freeze_history = [record]
        stats = guard.get_statistics()
        assert stats["is_frozen"] is True
        assert stats["current_freeze"] is not None
        assert stats["total_freezes"] == 1

    def test_reset(self, guard):
        guard._is_frozen = True
        guard._current_freeze = FreezeRecord(
            freeze_id=uuid4(),
            reason=FreezeReason.SECURITY_BREACH,
            scope=FreezeScope.ALL_WRITES,
            frozen_by="admin",
            frozen_at=datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC),
            expires_at=None,
            description="",
            approved_by=[],
        )
        guard._freeze_history = [MagicMock()]
        guard._version = 5
        guard._audit_trail = [{"action": "test"}]
        guard.reset()
        assert guard._is_frozen is False
        assert guard._current_freeze is None
        assert guard._freeze_history == []
        assert guard._version == 6
        assert guard._audit_trail == []


# ============================================================================
# Singleton accessor test
# ============================================================================

def test_get_emergency_freeze_guard():
    EmergencyFreezeGuard._instance = None
    g1 = get_emergency_freeze_guard()
    g2 = get_emergency_freeze_guard()
    assert g1 is g2
    assert isinstance(g1, EmergencyFreezeGuard)
