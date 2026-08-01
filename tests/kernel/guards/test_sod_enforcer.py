# test_sod_enforcer.py
# Comprehensive tests for kernel/guards/sod_enforcer.py
# All external dependencies are mocked.

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from kernel.guards.sod_enforcer import (
    BaseSODEnforcer,
    SODEnforcer,
    SODEnforcerError,
    SODRule,
    SODRuleType,
    SODSeverity,
    SODViolation,
    _FallbackUserRepository,
    check_segregation,
    enforce_sod,
    get_sod_enforcer,
)


# ----------------------------------------------------------------------
# Enums & Value Objects
# ----------------------------------------------------------------------
class TestSODRuleType:
    def test_members_exist(self):
        assert hasattr(SODRuleType, "MAKER_CHECKER")
        assert hasattr(SODRuleType, "CONFLICTING_ROLES")
        assert hasattr(SODRuleType, "TRANSACTION_LIMIT")
        assert hasattr(SODRuleType, "DUAL_CONTROL")
        assert hasattr(SODRuleType, "FOUR_EYES")
        assert hasattr(SODRuleType, "TIME_BASED")

    def test_member_is_instance(self):
        assert isinstance(SODRuleType.MAKER_CHECKER, SODRuleType)


class TestSODSeverity:
    def test_members_exist(self):
        assert hasattr(SODSeverity, "CRITICAL")
        assert hasattr(SODSeverity, "HIGH")
        assert hasattr(SODSeverity, "MEDIUM")
        assert hasattr(SODSeverity, "LOW")

    def test_member_is_instance(self):
        assert isinstance(SODSeverity.CRITICAL, SODSeverity)


class TestSODRule:
    def test_construction(self):
        rule = SODRule(
            rule_id="TEST_001",
            rule_type=SODRuleType.MAKER_CHECKER,
            description="Test rule",
            parameters={"key": "value"},
            is_active=True,
            severity=SODSeverity.HIGH,
            created_at=datetime.now(UTC),
            created_by="admin",
        )
        assert rule.rule_id == "TEST_001"
        assert rule.cryptographic_hash == ""  # not auto-computed

    def test_compute_hash(self):
        rule = SODRule(
            rule_id="TEST_002",
            rule_type=SODRuleType.CONFLICTING_ROLES,
            description="Test rule",
        )
        h = rule.compute_hash()
        assert isinstance(h, str)
        assert len(h) == 64

    def test_hash_mismatch_raises(self):
        with pytest.raises(ValueError, match="Cryptographic hash mismatch"):
            SODRule(
                rule_id="TEST_003",
                rule_type=SODRuleType.TRANSACTION_LIMIT,
                description="Test",
                cryptographic_hash="wronghash",
            )

    def test_to_dict(self):
        rule = SODRule(
            rule_id="TEST_004",
            rule_type=SODRuleType.DUAL_CONTROL,
            description="Dual control test",
            parameters={"required_approvers": 2},
            is_active=False,
            severity=SODSeverity.CRITICAL,
            created_at=datetime.now(UTC),
            created_by="system",
        )
        d = rule.to_dict()
        assert d["rule_id"] == "TEST_004"
        assert d["rule_type"] == "DUAL_CONTROL"
        assert d["is_active"] is False
        assert d["severity"] == "CRITICAL"


class TestSODViolation:
    def test_construction(self):
        violation = SODViolation(
            violation_id=uuid4(),
            rule_id="TEST_001",
            rule_type=SODRuleType.MAKER_CHECKER,
            severity=SODSeverity.CRITICAL,
            user_id="user1",
            transaction_id=uuid4(),
            legal_entity_id=uuid4(),
            message="Violation message",
            details={},
            detected_at=datetime.now(UTC),
            is_resolved=False,
            cryptographic_hash="",
        )
        assert violation.violation_id is not None
        assert violation.cryptographic_hash == ""

    def test_compute_hash(self):
        violation = SODViolation(
            violation_id=uuid4(),
            rule_id="TEST_002",
            rule_type=SODRuleType.CONFLICTING_ROLES,
            severity=SODSeverity.HIGH,
            user_id="user2",
            transaction_id=None,
            legal_entity_id=None,
            message="Conflict",
            details={},
            detected_at=datetime.now(UTC),
        )
        h = violation.compute_hash()
        assert isinstance(h, str)
        assert len(h) == 64

    def test_hash_mismatch_raises(self):
        with pytest.raises(ValueError, match="Cryptographic hash mismatch"):
            SODViolation(
                violation_id=uuid4(),
                rule_id="TEST_003",
                rule_type=SODRuleType.TRANSACTION_LIMIT,
                severity=SODSeverity.MEDIUM,
                user_id="user3",
                message="Hash mismatch",
                details={},
                detected_at=datetime.now(UTC),
                cryptographic_hash="wronghash",
            )

    def test_resolve(self):
        violation = SODViolation(
            violation_id=uuid4(),
            rule_id="TEST_004",
            rule_type=SODRuleType.DUAL_CONTROL,
            severity=SODSeverity.HIGH,
            user_id="user4",
            message="Need resolution",
            details={},
            detected_at=datetime.now(UTC),
            is_resolved=False,
        )
        resolved = violation.resolve("admin", "approved manually")
        assert resolved.is_resolved is True
        assert resolved.resolved_by == "admin"
        assert resolved.resolution_action == "approved manually"
        assert resolved.resolved_at is not None

    def test_to_dict(self):
        violation = SODViolation(
            violation_id=uuid4(),
            rule_id="TEST_005",
            rule_type=SODRuleType.TIME_BASED,
            severity=SODSeverity.LOW,
            user_id="user5",
            transaction_id=uuid4(),
            legal_entity_id=uuid4(),
            message="Time violation",
            details={"hours": 1},
            detected_at=datetime.now(UTC),
            is_resolved=True,
            resolved_at=datetime.now(UTC),
            resolved_by="admin",
        )
        d = violation.to_dict()
        assert d["violation_id"] == str(violation.violation_id)
        assert d["rule_id"] == "TEST_005"
        assert d["is_resolved"] is True
        assert d["resolved_by"] == "admin"


# ----------------------------------------------------------------------
# _FallbackUserRepository
# ----------------------------------------------------------------------
class TestFallbackUserRepository:
    @pytest.fixture
    def repo(self):
        return _FallbackUserRepository()

    @pytest.mark.asyncio
    async def test_get_roles_default(self, repo):
        roles = await repo.get_roles("unknown")
        assert roles == ["guest"]

    @pytest.mark.asyncio
    async def test_get_roles_known(self, repo):
        roles = await repo.get_roles("maker")
        assert roles == ["maker"]

    @pytest.mark.asyncio
    async def test_set_user_roles(self, repo):
        await repo.set_user_roles("new_user", ["role1", "role2"])
        roles = await repo.get_roles("new_user")
        assert roles == ["role1", "role2"]

    @pytest.mark.asyncio
    async def test_get_legal_entities_default(self, repo):
        entities = await repo.get_legal_entities("unknown")
        assert entities == []

    @pytest.mark.asyncio
    async def test_add_user_entity(self, repo):
        eid = uuid4()
        repo.add_user_entity("user1", eid)
        entities = await repo.get_legal_entities("user1")
        assert eid in entities

    @pytest.mark.asyncio
    async def test_get_approval_limit_default(self, repo):
        limit = await repo.get_approval_limit("unknown", "any")
        assert limit is None

    @pytest.mark.asyncio
    async def test_set_user_approval_limit(self, repo):
        await repo.set_user_approval_limit("user1", "JOURNAL", Decimal("1000"))
        limit = await repo.get_approval_limit("user1", "JOURNAL")
        assert limit == Decimal("1000")
        # Different type
        limit = await repo.get_approval_limit("user1", "PAYMENT")
        assert limit is None


# ----------------------------------------------------------------------
# BaseSODEnforcer (Abstract) - just test class defined
# ----------------------------------------------------------------------
class TestBaseSODEnforcer:
    def test_class_defined(self):
        assert BaseSODEnforcer is not None


# ----------------------------------------------------------------------
# SODEnforcer
# ----------------------------------------------------------------------
@pytest.fixture
def mock_user_repo():
    repo = MagicMock(spec=_FallbackUserRepository)
    repo.get_roles = AsyncMock(return_value=["maker"])
    repo.get_legal_entities = AsyncMock(return_value=[])
    repo.get_approval_limit = AsyncMock(return_value=None)
    repo.set_user_roles = AsyncMock()
    repo.set_user_approval_limit = AsyncMock()
    return repo


@pytest.fixture
def enforcer(mock_user_repo):
    return SODEnforcer(user_repository=mock_user_repo)


class TestSODEnforcer:
    # ----- Entity methods -----
    def test_check_valid(self, enforcer):
        context = {
            "transaction_type": "JOURNAL",
            "creator_user_id": "maker",
            "approver_user_id": "checker",
            "amount": "100.00",
        }
        errors = enforcer.check(context)
        assert errors == []

    def test_check_missing(self, enforcer):
        errors = enforcer.check({})
        assert "transaction_type is required" in errors
        assert "creator_user_id is required" in errors
        assert "approver_user_id is required" in errors

    def test_check_same_user(self, enforcer):
        context = {
            "transaction_type": "JOURNAL",
            "creator_user_id": "user1",
            "approver_user_id": "user1",
        }
        errors = enforcer.check(context)
        assert any("cannot be the same" in e for e in errors)

    def test_check_invalid_amount(self, enforcer):
        context = {
            "transaction_type": "JOURNAL",
            "creator_user_id": "maker",
            "approver_user_id": "checker",
            "amount": "not-a-number",
        }
        errors = enforcer.check(context)
        assert "amount must be a valid number" in errors

    def test_validate(self, enforcer):
        result = enforcer.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_to_dict(self, enforcer):
        d = enforcer.to_dict()
        assert "enabled" in d
        assert "strict_mode" in d
        assert "rules_count" in d
        assert "version" in d

    def test_from_dict(self):
        data = {"enabled": False, "strict_mode": False, "max_history": 5000, "version": 3}
        enforcer = SODEnforcer.from_dict(data)
        assert enforcer._enabled is False
        assert enforcer._strict_mode is False
        assert enforcer._max_history == 5000
        assert enforcer._version == 3

    def test_clone(self, enforcer):
        clone = enforcer.clone()
        assert clone is not enforcer
        assert clone._enabled == enforcer._enabled
        assert clone._strict_mode == enforcer._strict_mode
        assert clone._max_history == enforcer._max_history
        assert clone._version == enforcer._version + 1

    def test_snapshot(self, enforcer):
        snap = enforcer.snapshot()
        assert "version" in snap
        assert "violations_count" in snap
        assert "enabled" in snap
        assert "timestamp" in snap

    def test_version(self, enforcer):
        assert enforcer.version() == enforcer._version

    def test_audit_trail(self, enforcer):
        assert enforcer.audit_trail() == []
        enforcer.touch("admin")
        trail = enforcer.audit_trail(limit=10)
        assert len(trail) == 1
        assert trail[0]["action"] == "TOUCH"

    def test_touch(self, enforcer):
        old = enforcer.version()
        enforcer.touch("admin")
        assert enforcer.version() == old + 1
        trail = enforcer.audit_trail()
        assert trail[-1]["action"] == "TOUCH"
        assert trail[-1]["performed_by"] == "admin"

    # ----- Enable / strict mode -----
    def test_enable(self, enforcer):
        enforcer.enable(False)
        assert enforcer._enabled is False
        enforcer.enable(True)
        assert enforcer._enabled is True

    def test_set_strict_mode(self, enforcer):
        enforcer.set_strict_mode(False)
        assert enforcer._strict_mode is False
        enforcer.set_strict_mode(True)
        assert enforcer._strict_mode is True

    # ----- Rule management -----
    def test_register_rule(self, enforcer):
        rule = SODRule(
            rule_id="CUSTOM_001",
            rule_type=SODRuleType.CONFLICTING_ROLES,
            description="Custom rule",
            parameters={"conflicting_roles": ["role1", "role2"]},
        )
        enforcer.register_rule(rule)
        assert "CUSTOM_001" in enforcer._rules
        stored = enforcer._rules["CUSTOM_001"]
        assert stored.rule_id == "CUSTOM_001"
        assert stored.cryptographic_hash != ""
        # audit
        trail = enforcer.audit_trail()
        assert any(e["action"] == "REGISTER_RULE" for e in trail)

    def test_get_rule(self, enforcer):
        # existing
        rule = enforcer.get_rule("SOD_001")
        assert rule is not None
        assert rule.rule_id == "SOD_001"
        # non-existent
        assert enforcer.get_rule("UNKNOWN") is None

    def test_get_all_rules(self, enforcer):
        all_rules = enforcer.get_all_rules(active_only=False)
        assert len(all_rules) == len(DEFAULT_SOD_RULES)
        active = enforcer.get_all_rules(active_only=True)
        assert all(r.is_active for r in active)
        # we can deactivate a rule and see it excluded
        enforcer.update_rule_status("SOD_001", False, "admin")
        active = enforcer.get_all_rules(active_only=True)
        assert not any(r.rule_id == "SOD_001" for r in active)

    def test_update_rule_status(self, enforcer):
        # update existing
        result = enforcer.update_rule_status("SOD_001", False, "admin")
        assert result is True
        rule = enforcer.get_rule("SOD_001")
        assert rule.is_active is False
        assert rule.modified_by == "admin"
        assert rule.modified_at is not None
        # update non-existent
        result = enforcer.update_rule_status("UNKNOWN", False, "admin")
        assert result is False
        # audit
        trail = enforcer.audit_trail()
        assert any(e["action"] == "UPDATE_RULE" for e in trail)

    # ----- Check methods -----
    @pytest.mark.asyncio
    async def test_check_maker_checker_disabled(self, enforcer):
        enforcer.enable(False)
        ok, violation = await enforcer.check_maker_checker("user", "user", "JOURNAL")
        assert ok is True
        assert violation is None

    @pytest.mark.asyncio
    async def test_check_maker_checker_ok(self, enforcer):
        ok, violation = await enforcer.check_maker_checker("maker", "checker", "JOURNAL")
        assert ok is True
        assert violation is None

    @pytest.mark.asyncio
    async def test_check_maker_checker_violation(self, enforcer):
        ok, violation = await enforcer.check_maker_checker("maker", "maker", "JOURNAL")
        assert ok is False
        assert violation is not None
        assert violation.rule_id == "SOD_001"
        assert "cannot approve their own" in violation.message
        # Check that violation is recorded
        assert len(enforcer._violations) == 0  # only record when enforce called, not check alone

    @pytest.mark.asyncio
    async def test_check_conflicting_roles_disabled(self, enforcer):
        enforcer.enable(False)
        ok, violations = await enforcer.check_conflicting_roles("user", ["ar_clerk", "cashier"])
        assert ok is True
        assert violations == []

    @pytest.mark.asyncio
    async def test_check_conflicting_roles_ok(self, enforcer):
        ok, violations = await enforcer.check_conflicting_roles("user", ["maker"])
        assert ok is True
        assert violations == []

    @pytest.mark.asyncio
    async def test_check_conflicting_roles_violation(self, enforcer):
        ok, violations = await enforcer.check_conflicting_roles(
            "user", ["ar_clerk", "cashier"]
        )
        assert ok is False
        assert len(violations) == 1
        assert violations[0].rule_id == "SOD_002"

    @pytest.mark.asyncio
    async def test_check_transaction_approval_limit_disabled(self, enforcer):
        enforcer.enable(False)
        ok, violation, roles = await enforcer.check_transaction_approval_limit(
            Decimal("2000000000"), ["maker"], "JOURNAL"
        )
        assert ok is True
        assert violation is None
        assert roles == []

    @pytest.mark.asyncio
    async def test_check_transaction_approval_limit_ok(self, enforcer):
        # amount below threshold
        ok, violation, roles = await enforcer.check_transaction_approval_limit(
            Decimal("50000000"), ["maker"], "JOURNAL"
        )
        assert ok is True
        assert violation is None
        # amount above threshold with correct role
        ok, violation, roles = await enforcer.check_transaction_approval_limit(
            Decimal("2000000000"), ["cfo"], "JOURNAL"
        )
        assert ok is True
        assert violation is None

    @pytest.mark.asyncio
    async def test_check_transaction_approval_limit_violation(self, enforcer):
        ok, violation, roles = await enforcer.check_transaction_approval_limit(
            Decimal("2000000000"), ["maker"], "JOURNAL"
        )
        assert ok is False
        assert violation is not None
        assert violation.rule_id == "SOD_005"
        assert "exceeds threshold" in violation.message
        assert roles == ["cfo"]

    @pytest.mark.asyncio
    async def test_check_dual_control_disabled(self, enforcer):
        enforcer.enable(False)
        ok, violation = await enforcer.check_dual_control("PERIOD_CLOSE", ["approver1"])
        assert ok is True
        assert violation is None

    @pytest.mark.asyncio
    async def test_check_dual_control_ok(self, enforcer):
        ok, violation = await enforcer.check_dual_control(
            "PERIOD_CLOSE", ["approver1", "approver2"]
        )
        assert ok is True
        assert violation is None

    @pytest.mark.asyncio
    async def test_check_dual_control_violation(self, enforcer):
        ok, violation = await enforcer.check_dual_control("PERIOD_CLOSE", ["approver1"])
        assert ok is False
        assert violation is not None
        assert violation.rule_id == "SOD_008"
        assert "requires 2 different approvers" in violation.message

    @pytest.mark.asyncio
    async def test_check_time_based_disabled(self, enforcer):
        enforcer.enable(False)
        ok, violation = await enforcer.check_time_based(
            "PAYMENT",
            Decimal("150000000"),
            datetime.now(UTC),
            datetime.now(UTC) + timedelta(hours=1),
        )
        assert ok is True
        assert violation is None

    @pytest.mark.asyncio
    async def test_check_time_based_ok(self, enforcer):
        created = datetime.now(UTC)
        approved = created + timedelta(hours=3)
        ok, violation = await enforcer.check_time_based(
            "PAYMENT", Decimal("150000000"), created, approved
        )
        assert ok is True
        assert violation is None

    @pytest.mark.asyncio
    async def test_check_time_based_violation(self, enforcer):
        created = datetime.now(UTC)
        approved = created + timedelta(hours=1)
        ok, violation = await enforcer.check_time_based(
            "PAYMENT", Decimal("150000000"), created, approved
        )
        assert ok is False
        assert violation is not None
        assert violation.rule_id == "SOD_014"
        assert "approved too quickly" in violation.message

    # ----- Enforce -----
    @pytest.mark.asyncio
    async def test_enforce_disabled(self, enforcer):
        enforcer.enable(False)
        ok, violations = await enforcer.enforce(
            "JOURNAL", amount=Decimal("100"), creator_user_id="maker", approver_user_id="checker"
        )
        assert ok is True
        assert violations == []

    @pytest.mark.asyncio
    async def test_enforce_no_violations(self, enforcer, mock_user_repo):
        mock_user_repo.get_roles.return_value = ["maker", "checker"]  # no conflict
        ok, violations = await enforcer.enforce(
            "JOURNAL",
            amount=Decimal("50"),
            creator_user_id="maker",
            approver_user_id="checker",
            approvers=["checker", "auditor"],
            created_at=datetime.now(UTC),
            approved_at=datetime.now(UTC) + timedelta(hours=3),
        )
        assert ok is True
        assert violations == []

    @pytest.mark.asyncio
    async def test_enforce_maker_checker_violation(self, enforcer, mock_user_repo):
        mock_user_repo.get_roles.return_value = ["maker"]
        with pytest.raises(SODEnforcerError) as exc:
            await enforcer.enforce(
                "JOURNAL",
                amount=Decimal("100"),
                creator_user_id="maker",
                approver_user_id="maker",
            )
        assert "cannot approve their own" in str(exc.value)
        assert len(enforcer._violations) == 1

    @pytest.mark.asyncio
    async def test_enforce_conflicting_roles_violation(self, enforcer, mock_user_repo):
        mock_user_repo.get_roles.return_value = ["ar_clerk", "cashier"]
        with pytest.raises(SODEnforcerError) as exc:
            await enforcer.enforce(
                "INVOICE",
                creator_user_id="user",
                approver_user_id="checker",
            )
        assert "Role conflict" in str(exc.value)
        assert len(enforcer._violations) == 1

    @pytest.mark.asyncio
    async def test_enforce_transaction_limit_violation(self, enforcer, mock_user_repo):
        mock_user_repo.get_roles.return_value = ["maker"]
        with pytest.raises(SODEnforcerError) as exc:
            await enforcer.enforce(
                "JOURNAL",
                amount=Decimal("2000000000"),
                creator_user_id="maker",
                approver_user_id="checker",
            )
        assert "exceeds threshold" in str(exc.value)

    @pytest.mark.asyncio
    async def test_enforce_dual_control_violation(self, enforcer, mock_user_repo):
        mock_user_repo.get_roles.return_value = ["maker"]
        with pytest.raises(SODEnforcerError) as exc:
            await enforcer.enforce(
                "PERIOD_CLOSE",
                amount=Decimal("100"),
                creator_user_id="maker",
                approver_user_id="checker",
                approvers=["approver1"],
            )
        assert "requires 2 different approvers" in str(exc.value)

    @pytest.mark.asyncio
    async def test_enforce_time_based_violation(self, enforcer, mock_user_repo):
        mock_user_repo.get_roles.return_value = ["maker"]
        created = datetime.now(UTC)
        approved = created + timedelta(hours=1)
        with pytest.raises(SODEnforcerError) as exc:
            await enforcer.enforce(
                "PAYMENT",
                amount=Decimal("150000000"),
                creator_user_id="maker",
                approver_user_id="checker",
                created_at=created,
                approved_at=approved,
            )
        assert "approved too quickly" in str(exc.value)

    @pytest.mark.asyncio
    async def test_enforce_multiple_violations_no_raise(self, enforcer, mock_user_repo):
        mock_user_repo.get_roles.return_value = ["ar_clerk", "cashier"]
        ok, violations = await enforcer.enforce(
            "JOURNAL",
            amount=Decimal("2000000000"),
            creator_user_id="maker",
            approver_user_id="maker",
            raise_on_violation=False,
        )
        assert ok is False
        # Should have maker-checker, conflicting roles, and transaction limit violations
        assert len(violations) >= 3
        assert any(v.rule_id == "SOD_001" for v in violations)
        assert any(v.rule_id == "SOD_002" for v in violations)
        assert any(v.rule_id == "SOD_005" for v in violations)

    @pytest.mark.asyncio
    async def test_enforce_with_non_critical_in_strict_mode(self, enforcer, mock_user_repo):
        # In strict mode, HIGH severity also raises
        mock_user_repo.get_roles.return_value = ["budget_creator", "budget_approver"]  # SOD_011 HIGH
        with pytest.raises(SODEnforcerError):
            await enforcer.enforce(
                "BUDGET",
                creator_user_id="user",
                approver_user_id="checker",
                raise_on_violation=True,
            )
        # Now turn off strict mode
        enforcer.set_strict_mode(False)
        # Should not raise for HIGH
        ok, violations = await enforcer.enforce(
            "BUDGET",
            creator_user_id="user",
            approver_user_id="checker",
            raise_on_violation=True,
        )
        assert ok is False  # still violation, but not raised
        assert violations

    # ----- Private methods _create_violation and _record_violation -----
    def test_create_violation(self, enforcer):
        violation = enforcer._create_violation(
            rule_id="TEST_RULE",
            rule_type=SODRuleType.MAKER_CHECKER,
            severity=SODSeverity.CRITICAL,
            user_id="user1",
            transaction_id=uuid4(),
            legal_entity_id=uuid4(),
            message="Test violation",
            details={"key": "value"},
        )
        assert isinstance(violation, SODViolation)
        assert violation.rule_id == "TEST_RULE"
        assert violation.user_id == "user1"
        assert violation.cryptographic_hash != ""
        # hash matches
        assert violation.cryptographic_hash == violation.compute_hash()

    def test_record_violation(self, enforcer):
        violation = enforcer._create_violation(
            rule_id="TEST",
            rule_type=SODRuleType.CONFLICTING_ROLES,
            severity=SODSeverity.HIGH,
            user_id="user2",
            transaction_id=None,
            legal_entity_id=None,
            message="Record test",
            details={},
        )
        enforcer._record_violation(violation)
        assert len(enforcer._violations) == 1
        assert enforcer._violations[0] is violation
        # audit
        trail = enforcer.audit_trail()
        assert any(e["action"] == "VIOLATION" for e in trail)

    # ----- get_violations, resolve_violation, statistics, reset -----
    def test_get_violations_empty(self, enforcer):
        assert enforcer.get_violations() == []

    def test_get_violations_filter(self, enforcer):
        # Create some violations via enforce without raising
        with patch.object(enforcer, "_record_violation", side_effect=lambda v: enforcer._violations.append(v)):
            v1 = enforcer._create_violation(
                rule_id="SOD_001",
                rule_type=SODRuleType.MAKER_CHECKER,
                severity=SODSeverity.CRITICAL,
                user_id="user1",
                transaction_id=uuid4(),
                legal_entity_id=None,
                message="Violation 1",
                details={},
            )
            v2 = enforcer._create_violation(
                rule_id="SOD_002",
                rule_type=SODRuleType.CONFLICTING_ROLES,
                severity=SODSeverity.HIGH,
                user_id="user2",
                transaction_id=uuid4(),
                legal_entity_id=None,
                message="Violation 2",
                details={},
            )
            enforcer._record_violation(v1)
            enforcer._record_violation(v2)
        # get all
        all_v = enforcer.get_violations()
        assert len(all_v) == 2
        # filter by user
        user1_v = enforcer.get_violations(user_id="user1")
        assert len(user1_v) == 1
        # filter by rule_type
        maker_v = enforcer.get_violations(rule_type=SODRuleType.MAKER_CHECKER)
        assert len(maker_v) == 1
        # unresolved only
        unresolved = enforcer.get_violations(unresolved_only=True)
        assert len(unresolved) == 2
        # resolve one
        enforcer.resolve_violation(v1.violation_id, "admin", "override")
        unresolved = enforcer.get_violations(unresolved_only=True)
        assert len(unresolved) == 1
        # date filters
        start = datetime.now(UTC) - timedelta(minutes=5)
        end = datetime.now(UTC) + timedelta(minutes=5)
        filtered = enforcer.get_violations(start_date=start, end_date=end)
        assert len(filtered) == 2

    def test_resolve_violation(self, enforcer):
        # Create a violation
        violation = enforcer._create_violation(
            rule_id="SOD_001",
            rule_type=SODRuleType.MAKER_CHECKER,
            severity=SODSeverity.CRITICAL,
            user_id="user1",
            transaction_id=None,
            legal_entity_id=None,
            message="Test resolve",
            details={},
        )
        enforcer._record_violation(violation)
        # Resolve
        resolved = enforcer.resolve_violation(violation.violation_id, "admin", "approved")
        assert resolved is not None
        assert resolved.is_resolved is True
        assert resolved.resolved_by == "admin"
        # Cannot resolve again
        resolved2 = enforcer.resolve_violation(violation.violation_id, "admin", "again")
        assert resolved2 is None

    def test_get_statistics(self, enforcer):
        stats = enforcer.get_statistics()
        assert stats["total_violations"] == 0
        # Add violations
        for i in range(3):
            v = enforcer._create_violation(
                rule_id=f"SOD_00{i}",
                rule_type=SODRuleType.MAKER_CHECKER if i % 2 == 0 else SODRuleType.CONFLICTING_ROLES,
                severity=SODSeverity.CRITICAL if i == 0 else SODSeverity.HIGH,
                user_id=f"user{i}",
                transaction_id=None,
                legal_entity_id=None,
                message=f"Violation {i}",
                details={},
            )
            enforcer._record_violation(v)
        stats = enforcer.get_statistics()
        assert stats["total_violations"] == 3
        assert stats["unresolved_violations"] == 3
        assert stats["by_rule_type"]["MAKER_CHECKER"] == 2
        assert stats["by_rule_type"]["CONFLICTING_ROLES"] == 1
        assert stats["by_severity"]["CRITICAL"] == 1
        assert stats["by_severity"]["HIGH"] == 2
        assert stats["enabled"] is True
        assert stats["strict_mode"] is True
        assert stats["version"] == enforcer.version()

    def test_reset(self, enforcer):
        # Add some state
        v = enforcer._create_violation(
            rule_id="SOD_001",
            rule_type=SODRuleType.MAKER_CHECKER,
            severity=SODSeverity.CRITICAL,
            user_id="user",
            transaction_id=None,
            legal_entity_id=None,
            message="Test",
            details={},
        )
        enforcer._record_violation(v)
        enforcer._rules["CUSTOM"] = MagicMock(spec=SODRule)
        old_version = enforcer.version()
        enforcer.reset()
        assert len(enforcer._violations) == 0
        assert "CUSTOM" not in enforcer._rules
        # default rules restored
        assert "SOD_001" in enforcer._rules
        assert enforcer._enabled is True
        assert enforcer._strict_mode is True
        assert enforcer.version() == old_version + 1
        assert enforcer._audit_trail == []


# ----------------------------------------------------------------------
# Module-level functions
# ----------------------------------------------------------------------
class TestModuleFunctions:
    def test_get_sod_enforcer_singleton(self):
        instance1 = get_sod_enforcer()
        instance2 = get_sod_enforcer()
        assert instance1 is instance2
        assert isinstance(instance1, SODEnforcer)

    @pytest.mark.asyncio
    async def test_enforce_sod(self):
        with patch("kernel.guards.sod_enforcer.get_sod_enforcer") as mock_get:
            mock_enforcer = AsyncMock()
            mock_enforcer.enforce.return_value = (True, [])
            mock_get.return_value = mock_enforcer
            ok, violations = await enforce_sod(
                transaction_type="JOURNAL",
                amount=Decimal("100"),
                creator_user_id="maker",
                approver_user_id="checker",
            )
            assert ok is True
            mock_enforcer.enforce.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_check_segregation(self):
        with patch("kernel.guards.sod_enforcer.get_sod_enforcer") as mock_get:
            mock_enforcer = AsyncMock()
            mock_enforcer.check_maker_checker.return_value = (True, None)
            mock_get.return_value = mock_enforcer
            ok, violation = await check_segregation(
                transaction_type="JOURNAL",
                creator_user_id="maker",
                approver_user_id="checker",
            )
            assert ok is True
            mock_enforcer.check_maker_checker.assert_awaited_once()

    def test_aliases_exist(self):
        # Check that aliases are defined for checker compatibility
        from kernel.guards.sod_enforcer import SegregationOfDutiesGuard, SodEnforcer
        assert SodEnforcer is SODEnforcer
        assert SegregationOfDutiesGuard is SODEnforcer
