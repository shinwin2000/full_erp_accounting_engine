# test_sod_matrix_rbac_enhanced.py
# Comprehensive tests for security_hardening/sod_matrix_rbac_enhanced.py
# Covers all classes, methods, edge cases, exceptions, and domain logic.

import json
from unittest.mock import patch

import pytest

from security_hardening.sod_matrix_rbac_enhanced import (
    PermissionType,
    RBACEnforcer,
    RoleType,
    SODConflictSeverity,
    SODError,
    SODMatrix,
    SoDRule,
    SODViolationError,
)


# -------------------- Fixtures --------------------
@pytest.fixture
def sod_rule():
    return SoDRule(
        permission_a=PermissionType.JOURNAL_CREATE.value,
        permission_b=PermissionType.JOURNAL_APPROVE.value,
        severity=SODConflictSeverity.CRITICAL,
        description="User cannot both create and approve a journal entry",
    )


@pytest.fixture
def sod_matrix():
    matrix = SODMatrix()
    # Clear default rules and add custom for controlled testing
    matrix._rules.clear()
    matrix._version = 1
    return matrix


@pytest.fixture
def rbac_enforcer(sod_matrix):
    return RBACEnforcer(sod_matrix=sod_matrix)


# -------------------- Tests for Enums --------------------
class TestEnums:
    def test_sod_conflict_severity(self):
        assert SODConflictSeverity.LOW.value == "low"
        assert SODConflictSeverity.MEDIUM.value == "medium"
        assert SODConflictSeverity.HIGH.value == "high"
        assert SODConflictSeverity.CRITICAL.value == "critical"
        assert SODConflictSeverity.LOW.display_name() == "Rendah"
        assert SODConflictSeverity.CRITICAL.display_name() == "Kritis"

    def test_permission_type(self):
        assert PermissionType.JOURNAL_CREATE.value == "journal.create"
        assert PermissionType.ANY.value == "*"
        assert PermissionType.JOURNAL_CREATE.display_name() == "Buat Jurnal"
        assert PermissionType.ANY.display_name() == "Semua"

    def test_role_type(self):
        assert RoleType.ACCOUNTANT.value == "accountant"
        assert RoleType.CFO.value == "cfo"
        assert RoleType.ACCOUNTANT.display_name() == "Akuntan"
        assert RoleType.CFO.display_name() == "CFO"


# -------------------- Tests for Exceptions --------------------
class TestExceptions:
    def test_sod_error(self):
        with pytest.raises(SODError):
            raise SODError("Test")

    def test_sod_violation_error(self):
        with pytest.raises(SODViolationError) as excinfo:
            raise SODViolationError("Violation", SODConflictSeverity.HIGH, rule_id="rule123")
        assert excinfo.value.severity == SODConflictSeverity.HIGH
        assert excinfo.value.rule_id == "rule123"


# -------------------- Tests for SoDRule --------------------
class TestSoDRule:
    def test_construction(self, sod_rule):
        assert sod_rule.permission_a == "journal.create"
        assert sod_rule.permission_b == "journal.approve"
        assert sod_rule.severity == SODConflictSeverity.CRITICAL
        assert sod_rule.description == "User cannot both create and approve a journal entry"
        assert sod_rule.enabled is True
        assert sod_rule.id is not None
        assert len(sod_rule._snapshots) == 1

    def test_id_generated_if_not_provided(self):
        rule = SoDRule(
            permission_a="a",
            permission_b="b",
            severity=SODConflictSeverity.MEDIUM,
            description="test",
        )
        assert rule.id is not None
        assert len(rule.id) == 12  # md5 first 12 chars

    def test_conflicts_with_both_permissions_present(self, sod_rule):
        perms = {"journal.create", "journal.approve", "other"}
        has_conflict, severity, desc = sod_rule.conflicts_with(perms)
        assert has_conflict is True
        assert severity == SODConflictSeverity.CRITICAL
        assert desc == sod_rule.description

    def test_conflicts_with_any_permission(self):
        rule = SoDRule(
            permission_a=PermissionType.ANY.value,
            permission_b="journal.approve",
            severity=SODConflictSeverity.HIGH,
            description="any conflict",
        )
        perms = {"journal.approve", "other"}
        has_conflict, _, _ = rule.conflicts_with(perms)
        assert has_conflict is True
        perms2 = {"other"}
        has_conflict2, _, _ = rule.conflicts_with(perms2)
        assert has_conflict2 is False  # because "journal.approve" missing

    def test_conflicts_with_only_one_permission(self, sod_rule):
        perms = {"journal.create"}
        has_conflict, _, _ = sod_rule.conflicts_with(perms)
        assert has_conflict is False
        perms2 = {"journal.approve"}
        has_conflict2, _, _ = sod_rule.conflicts_with(perms2)
        assert has_conflict2 is False

    def test_validate_valid(self, sod_rule):
        result = sod_rule.validate()
        assert result["is_valid"] is True

    def test_validate_invalid_missing_fields(self):
        rule = SoDRule(
            permission_a="",
            permission_b="",
            severity=SODConflictSeverity.LOW,
            description="",
        )
        result = rule.validate()
        assert result["is_valid"] is False
        errors = result["errors"]
        assert any("permission_a is required" in e for e in errors)
        assert any("permission_b is required" in e for e in errors)
        assert any("description is required" in e for e in errors)

    def test_to_dict(self, sod_rule):
        d = sod_rule.to_dict()
        assert d["id"] == sod_rule.id
        assert d["permission_a"] == "journal.create"
        assert d["permission_b"] == "journal.approve"
        assert d["severity"] == "critical"
        assert d["description"] == sod_rule.description
        assert d["enabled"] is True
        assert d["version"] == 1

    def test_from_dict(self, sod_rule):
        d = sod_rule.to_dict()
        restored = SoDRule.from_dict(d)
        assert restored.id == sod_rule.id
        assert restored.permission_a == sod_rule.permission_a
        assert restored.permission_b == sod_rule.permission_b
        assert restored.severity == sod_rule.severity
        assert restored.description == sod_rule.description
        assert restored.enabled == sod_rule.enabled
        assert restored._version == sod_rule._version

    def test_clone(self, sod_rule):
        cloned = sod_rule.clone()
        assert cloned.id != sod_rule.id
        assert cloned.permission_a == sod_rule.permission_a
        assert cloned.permission_b == sod_rule.permission_b
        assert cloned.severity == sod_rule.severity
        assert cloned.enabled == sod_rule.enabled
        assert cloned._version == sod_rule._version + 1
        assert len(cloned._audit_trail) == 1
        assert cloned._audit_trail[0]["action"] == "CLONE"

    def test_snapshot(self, sod_rule):
        snap = sod_rule.snapshot()
        assert snap["version"] == sod_rule._version
        assert snap["id"] == sod_rule.id
        assert snap["permission_a"] == "journal.create"
        assert snap["permission_b"] == "journal.approve"
        assert snap["severity"] == "critical"
        assert "timestamp" in snap

    def test_version(self, sod_rule):
        assert sod_rule.version() == sod_rule._version

    def test_audit_trail(self, sod_rule):
        # initially empty
        assert sod_rule.audit_trail() == []
        # touch adds entry
        sod_rule.touch("tester")
        trail = sod_rule.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TOUCH"
        assert trail[0]["performed_by"] == "tester"

    def test_touch(self, sod_rule):
        old_version = sod_rule._version
        touched = sod_rule.touch("tester")
        assert touched._version == old_version + 1
        assert len(touched._audit_trail) == 1
        assert touched._audit_trail[0]["action"] == "TOUCH"


# -------------------- Tests for SODMatrix --------------------
class TestSODMatrix:
    def test_init_default_rules(self):
        matrix = SODMatrix()
        rules = matrix.get_all_rules()
        assert len(rules) > 0  # default rules loaded
        assert matrix._version == 1
        assert len(matrix._snapshots) == 1

    def test_add_rule(self, sod_matrix, sod_rule):
        sod_matrix.add_rule(sod_rule)
        assert sod_rule.id in sod_matrix._rules
        assert len(sod_matrix._rules) == 1
        # audit trail
        trail = sod_matrix.audit_trail()
        assert any(entry["action"] == "ADD_RULE" for entry in trail)

    def test_add_rule_duplicate_id(self, sod_matrix, sod_rule):
        sod_matrix.add_rule(sod_rule)
        # duplicate with same id (should be skipped with warning)
        duplicate = sod_rule.clone()
        duplicate.id = sod_rule.id
        sod_matrix.add_rule(duplicate)
        assert len(sod_matrix._rules) == 1

    def test_add_rule_duplicate_permissions(self, sod_matrix):
        rule1 = SoDRule(
            permission_a="a",
            permission_b="b",
            severity=SODConflictSeverity.MEDIUM,
            description="desc",
        )
        rule2 = SoDRule(
            permission_a="b",
            permission_b="a",
            severity=SODConflictSeverity.HIGH,
            description="desc2",
        )
        sod_matrix.add_rule(rule1)
        sod_matrix.add_rule(rule2)
        assert len(sod_matrix._rules) == 1  # duplicate reversed, skipped

    def test_remove_rule(self, sod_matrix, sod_rule):
        sod_matrix.add_rule(sod_rule)
        assert sod_matrix.remove_rule(sod_rule.id) is True
        assert sod_rule.id not in sod_matrix._rules
        # remove non-existing returns False
        assert sod_matrix.remove_rule("nonexistent") is False
        trail = sod_matrix.audit_trail()
        assert any(entry["action"] == "REMOVE_RULE" for entry in trail)

    def test_get_rule(self, sod_matrix, sod_rule):
        sod_matrix.add_rule(sod_rule)
        assert sod_matrix.get_rule(sod_rule.id) == sod_rule
        assert sod_matrix.get_rule("nonexistent") is None

    def test_get_all_rules(self, sod_matrix, sod_rule):
        sod_matrix.add_rule(sod_rule)
        rules = sod_matrix.get_all_rules()
        assert len(rules) == 1
        assert rules[0] == sod_rule

    def test_enable_rule(self, sod_matrix, sod_rule):
        sod_matrix.add_rule(sod_rule)
        assert sod_matrix.enable_rule(sod_rule.id, False) is True
        assert sod_rule.enabled is False
        assert sod_matrix.enable_rule("nonexistent", False) is False
        trail = sod_matrix.audit_trail()
        assert any(entry["action"] == "ENABLE_RULE" for entry in trail)

    def test_check_permissions(self, sod_matrix, sod_rule):
        sod_matrix.add_rule(sod_rule)
        perms = {"journal.create", "journal.approve"}
        conflicts = sod_matrix.check_permissions(perms)
        assert len(conflicts) == 1
        rule, msg = conflicts[0]
        assert rule.id == sod_rule.id
        assert "User has both" in msg
        # no conflict if only one
        conflicts2 = sod_matrix.check_permissions({"journal.create"})
        assert len(conflicts2) == 0

    def test_check_permissions_disabled_rule(self, sod_matrix, sod_rule):
        sod_matrix.add_rule(sod_rule)
        sod_rule.enabled = False
        perms = {"journal.create", "journal.approve"}
        conflicts = sod_matrix.check_permissions(perms)
        assert len(conflicts) == 0

    def test_enforce_no_raise(self, sod_matrix, sod_rule):
        sod_matrix.add_rule(sod_rule)
        perms = {"journal.create", "journal.approve"}
        conflicts = sod_matrix.enforce(perms, raise_on_critical=False)
        assert len(conflicts) == 1
        # with critical raise_on_critical=True, should raise
        with pytest.raises(SODViolationError) as excinfo:
            sod_matrix.enforce(perms, raise_on_critical=True)
        assert excinfo.value.severity == SODConflictSeverity.CRITICAL
        assert excinfo.value.rule_id == sod_rule.id

    def test_enforce_high_severity(self, sod_matrix):
        rule = SoDRule(
            permission_a="x",
            permission_b="y",
            severity=SODConflictSeverity.HIGH,
            description="high conflict",
        )
        sod_matrix.add_rule(rule)
        perms = {"x", "y"}
        # with raise_on_high=True, should raise
        with pytest.raises(SODViolationError) as excinfo:
            sod_matrix.enforce(perms, raise_on_critical=False, raise_on_high=True)
        assert excinfo.value.severity == SODConflictSeverity.HIGH

    def test_is_compliant(self, sod_matrix, sod_rule):
        sod_matrix.add_rule(sod_rule)
        perms_compliant = {"journal.create"}
        assert sod_matrix.is_compliant(perms_compliant) is True
        perms_non_compliant = {"journal.create", "journal.approve"}
        assert sod_matrix.is_compliant(perms_non_compliant) is False

    def test_get_conflict_summary(self, sod_matrix, sod_rule):
        sod_matrix.add_rule(sod_rule)
        perms = {"journal.create", "journal.approve", "other"}
        summary = sod_matrix.get_conflict_summary(perms)
        assert summary["critical"] == 1
        assert summary["high"] == 0
        assert summary["medium"] == 0
        assert summary["low"] == 0

    def test_validate(self, sod_matrix, sod_rule):
        sod_matrix.add_rule(sod_rule)
        result = sod_matrix.validate()
        assert result["is_valid"] is True
        # invalid rule: set description empty
        bad_rule = SoDRule(
            permission_a="a",
            permission_b="b",
            severity=SODConflictSeverity.LOW,
            description="",
        )
        sod_matrix.add_rule(bad_rule)
        result2 = sod_matrix.validate()
        assert result2["is_valid"] is False
        assert any("description is required" in e for e in result2["errors"])

    def test_to_dict(self, sod_matrix, sod_rule):
        sod_matrix.add_rule(sod_rule)
        d = sod_matrix.to_dict()
        assert d["total_rules"] == 1
        assert len(d["rules"]) == 1
        assert d["rules"][0]["id"] == sod_rule.id
        assert d["version"] == 1

    def test_from_dict(self, sod_matrix, sod_rule):
        sod_matrix.add_rule(sod_rule)
        d = sod_matrix.to_dict()
        restored = SODMatrix.from_dict(d)
        assert len(restored._rules) == 1
        restored_rule = restored.get_rule(sod_rule.id)
        assert restored_rule is not None
        assert restored_rule.permission_a == sod_rule.permission_a
        assert restored._version == sod_rule._version

    def test_clone(self, sod_matrix, sod_rule):
        sod_matrix.add_rule(sod_rule)
        cloned = sod_matrix.clone()
        assert len(cloned._rules) == 1
        cloned_rule = cloned.get_rule(sod_rule.id)
        assert cloned_rule.id != sod_rule.id  # because clone creates new id
        assert cloned_rule.permission_a == sod_rule.permission_a
        assert cloned._version == sod_matrix._version + 1

    def test_snapshot(self, sod_matrix):
        snap = sod_matrix.snapshot()
        assert snap["version"] == sod_matrix._version
        assert snap["rules_count"] == 0
        assert "timestamp" in snap

    def test_version(self, sod_matrix):
        assert sod_matrix.version() == sod_matrix._version

    def test_audit_trail(self, sod_matrix, sod_rule):
        sod_matrix.add_rule(sod_rule)
        trail = sod_matrix.audit_trail()
        assert any(entry["action"] == "ADD_RULE" for entry in trail)

    def test_touch(self, sod_matrix):
        old_version = sod_matrix._version
        touched = sod_matrix.touch("tester")
        assert touched._version == old_version + 1
        trail = touched.audit_trail()
        assert any(entry["action"] == "TOUCH" for entry in trail)

    def test_reset(self, sod_matrix, sod_rule):
        sod_matrix.add_rule(sod_rule)
        sod_matrix.reset()
        assert len(sod_matrix._rules) > 0  # default rules re-added
        assert sod_matrix._version == 1  # reset sets version to 1
        assert len(sod_matrix._audit_trail) == 1  # just the RESET entry
        trail = sod_matrix.audit_trail()
        assert any(entry["action"] == "RESET" for entry in trail)

    def test_export_to_json(self, sod_matrix, sod_rule, tmp_path):
        sod_matrix.add_rule(sod_rule)
        file_path = tmp_path / "sod_matrix.json"
        sod_matrix.export_to_json(str(file_path))
        assert file_path.exists()
        with open(file_path) as f:
            data = json.load(f)
        assert data["total_rules"] == 1


# -------------------- Tests for RBACEnforcer --------------------
class TestRBACEnforcer:
    def test_init(self, rbac_enforcer):
        assert rbac_enforcer._role_permissions == {}
        assert rbac_enforcer._user_roles == {}
        assert rbac_enforcer._version == 1
        assert len(rbac_enforcer._snapshots) == 1

    def test_define_role(self, rbac_enforcer):
        rbac_enforcer.define_role("accountant", {"journal.create", "view"})
        assert "accountant" in rbac_enforcer._role_permissions
        assert rbac_enforcer._role_permissions["accountant"] == {"journal.create", "view"}
        trail = rbac_enforcer.audit_trail()
        assert any(entry["action"] == "DEFINE_ROLE" for entry in trail)

    def test_define_role_with_inheritance(self, rbac_enforcer):
        rbac_enforcer.define_role("parent", {"p1", "p2"})
        rbac_enforcer.define_role("child", {"c1"}, inherits_from=["parent"])
        assert "child" in rbac_enforcer._role_hierarchy
        assert rbac_enforcer._role_hierarchy["child"] == {"parent"}
        assert rbac_enforcer._role_children["parent"] == {"child"}

    def test_update_role_permissions(self, rbac_enforcer):
        rbac_enforcer.define_role("accountant", {"old"})
        rbac_enforcer.update_role_permissions("accountant", {"new1", "new2"})
        assert rbac_enforcer._role_permissions["accountant"] == {"new1", "new2"}

    def test_update_role_permissions_not_defined(self, rbac_enforcer):
        with pytest.raises(ValueError, match="Role nonexistent not defined"):
            rbac_enforcer.update_role_permissions("nonexistent", set())

    def test_add_permission_to_role(self, rbac_enforcer):
        rbac_enforcer.define_role("accountant", set())
        rbac_enforcer.add_permission_to_role("accountant", "new_perm")
        assert "new_perm" in rbac_enforcer._role_permissions["accountant"]
        # add to non-existing role: creates role
        rbac_enforcer.add_permission_to_role("new_role", "perm")
        assert "new_role" in rbac_enforcer._role_permissions
        assert "perm" in rbac_enforcer._role_permissions["new_role"]

    def test_remove_permission_from_role(self, rbac_enforcer):
        rbac_enforcer.define_role("accountant", {"p1", "p2"})
        assert rbac_enforcer.remove_permission_from_role("accountant", "p1") is True
        assert "p1" not in rbac_enforcer._role_permissions["accountant"]
        # remove non-existent permission
        assert rbac_enforcer.remove_permission_from_role("accountant", "p3") is False
        # remove from non-existent role
        assert rbac_enforcer.remove_permission_from_role("nonexistent", "p") is False

    def test_delete_role(self, rbac_enforcer):
        rbac_enforcer.define_role("parent", {"p"})
        rbac_enforcer.define_role("child", {"c"}, inherits_from=["parent"])
        rbac_enforcer.assign_role("user1", "child")
        # delete parent should cascade (remove from hierarchy and user roles)
        assert rbac_enforcer.delete_role("parent") is True
        assert "parent" not in rbac_enforcer._role_permissions
        assert "parent" not in rbac_enforcer._role_hierarchy
        assert "parent" not in rbac_enforcer._role_children
        # child still exists but its inheritance parent removed
        assert "child" in rbac_enforcer._role_permissions
        assert rbac_enforcer._role_hierarchy["child"] == set()  # parent removed
        # user roles updated (child still assigned)
        assert "child" in rbac_enforcer.get_user_roles("user1")
        # delete non-existent returns False
        assert rbac_enforcer.delete_role("nonexistent") is False

    def test_get_role_permissions(self, rbac_enforcer):
        rbac_enforcer.define_role("accountant", {"p1", "p2"})
        assert rbac_enforcer.get_role_permissions("accountant") == {"p1", "p2"}
        assert rbac_enforcer.get_role_permissions("nonexistent") == set()

    def test_get_effective_permissions_for_role(self, rbac_enforcer):
        rbac_enforcer.define_role("parent", {"p1", "p2"})
        rbac_enforcer.define_role("child", {"c1"}, inherits_from=["parent"])
        perms = rbac_enforcer.get_effective_permissions_for_role("child")
        assert perms == {"c1", "p1", "p2"}

    def test_get_effective_permissions_for_role_cycle(self, rbac_enforcer):
        # create cycle: a->b, b->a
        rbac_enforcer.define_role("a", {"pa"})
        rbac_enforcer.define_role("b", {"pb"}, inherits_from=["a"])
        # manually add cycle
        rbac_enforcer._role_hierarchy["a"].add("b")
        perms = rbac_enforcer.get_effective_permissions_for_role("a")
        # should not infinite loop, returns only direct perms because visited prevents cycle
        assert perms == {"pa"}  # doesn't include b's perms because cycle

    def test_get_role_hierarchy_tree(self, rbac_enforcer):
        rbac_enforcer.define_role("root", {"r"})
        rbac_enforcer.define_role("child1", {"c1"}, inherits_from=["root"])
        rbac_enforcer.define_role("child2", {"c2"}, inherits_from=["root"])
        tree = rbac_enforcer.get_role_hierarchy_tree("root")
        assert tree["role"] == "root"
        assert set(tree["permissions"]) == {"r"}
        children = tree["children"]
        assert len(children) == 2
        child_names = {c["role"] for c in children}
        assert child_names == {"child1", "child2"}

    def test_assign_role(self, rbac_enforcer):
        rbac_enforcer.define_role("accountant", set())
        rbac_enforcer.assign_role("user1", "accountant")
        assert "user1" in rbac_enforcer._user_roles
        assert "accountant" in rbac_enforcer._user_roles["user1"]
        # assign non-existent role raises
        with pytest.raises(ValueError, match="Role nonexistent not defined"):
            rbac_enforcer.assign_role("user1", "nonexistent")

    def test_revoke_role(self, rbac_enforcer):
        rbac_enforcer.define_role("accountant", set())
        rbac_enforcer.assign_role("user1", "accountant")
        assert rbac_enforcer.revoke_role("user1", "accountant") is True
        assert "accountant" not in rbac_enforcer._user_roles["user1"]
        # revoke non-existent role
        assert rbac_enforcer.revoke_role("user1", "nonexistent") is False
        # revoke from non-existent user
        assert rbac_enforcer.revoke_role("nonexistent", "accountant") is False

    def test_get_user_roles(self, rbac_enforcer):
        rbac_enforcer.define_role("r1", set())
        rbac_enforcer.define_role("r2", set())
        rbac_enforcer.assign_role("user1", "r1")
        rbac_enforcer.assign_role("user1", "r2")
        assert rbac_enforcer.get_user_roles("user1") == {"r1", "r2"}
        assert rbac_enforcer.get_user_roles("nonexistent") == set()

    def test_get_user_permissions(self, rbac_enforcer):
        rbac_enforcer.define_role("r1", {"p1", "p2"})
        rbac_enforcer.define_role("r2", {"p3"}, inherits_from=["r1"])
        rbac_enforcer.assign_role("user1", "r2")
        perms = rbac_enforcer.get_user_permissions("user1")
        assert perms == {"p1", "p2", "p3"}

    def test_get_users_with_role(self, rbac_enforcer):
        rbac_enforcer.define_role("r1", set())
        rbac_enforcer.assign_role("u1", "r1")
        rbac_enforcer.assign_role("u2", "r1")
        assert set(rbac_enforcer.get_users_with_role("r1")) == {"u1", "u2"}
        assert rbac_enforcer.get_users_with_role("nonexistent") == []

    def test_has_permission(self, rbac_enforcer):
        rbac_enforcer.define_role("r1", {"p1"})
        rbac_enforcer.assign_role("user1", "r1")
        assert rbac_enforcer.has_permission("user1", "p1") is True
        assert rbac_enforcer.has_permission("user1", "p2") is False
        assert rbac_enforcer.has_permission("nonexistent", "p1") is False

    def test_enforce_permission_success(self, rbac_enforcer):
        rbac_enforcer.define_role("r1", {"p1"})
        rbac_enforcer.assign_role("user1", "r1")
        # should not raise
        rbac_enforcer.enforce_permission("user1", "p1")
        # with missing permission, should raise AuthorizationError
        with pytest.raises(Exception) as excinfo:  # AuthorizationError imported dynamically
            rbac_enforcer.enforce_permission("user1", "p2")
        assert "missing required permission" in str(excinfo.value)

    def test_has_any_permission(self, rbac_enforcer):
        rbac_enforcer.define_role("r1", {"p1", "p2"})
        rbac_enforcer.assign_role("user1", "r1")
        assert rbac_enforcer.has_any_permission("user1", ["p1", "p3"]) is True
        assert rbac_enforcer.has_any_permission("user1", ["p3", "p4"]) is False

    def test_has_all_permissions(self, rbac_enforcer):
        rbac_enforcer.define_role("r1", {"p1", "p2"})
        rbac_enforcer.assign_role("user1", "r1")
        assert rbac_enforcer.has_all_permissions("user1", ["p1", "p2"]) is True
        assert rbac_enforcer.has_all_permissions("user1", ["p1", "p3"]) is False

    # ---- SOD Integration ----
    def test_enforce_sod(self, rbac_enforcer):
        # define rules and permissions
        rule = SoDRule(
            permission_a="create",
            permission_b="approve",
            severity=SODConflictSeverity.CRITICAL,
            description="conflict",
        )
        rbac_enforcer._sod.add_rule(rule)
        rbac_enforcer.define_role("r1", {"create", "approve"})
        rbac_enforcer.assign_role("user1", "r1")
        conflicts = rbac_enforcer.enforce_sod("user1", raise_on_critical=False)
        assert len(conflicts) == 1
        # with raise
        with pytest.raises(SODViolationError):
            rbac_enforcer.enforce_sod("user1", raise_on_critical=True)

    def test_is_sod_compliant(self, rbac_enforcer):
        rule = SoDRule(
            permission_a="create",
            permission_b="approve",
            severity=SODConflictSeverity.CRITICAL,
            description="conflict",
        )
        rbac_enforcer._sod.add_rule(rule)
        rbac_enforcer.define_role("r1", {"create"})
        rbac_enforcer.assign_role("user1", "r1")
        assert rbac_enforcer.is_sod_compliant("user1") is True
        rbac_enforcer.define_role("r2", {"approve"})
        rbac_enforcer.assign_role("user1", "r2")
        assert rbac_enforcer.is_sod_compliant("user1") is False

    def test_check_sod_conflict(self, rbac_enforcer):
        rule = SoDRule(
            permission_a="create",
            permission_b="approve",
            severity=SODConflictSeverity.CRITICAL,
            description="conflict",
        )
        rbac_enforcer._sod.add_rule(rule)
        rbac_enforcer.define_role("r1", {"create", "approve"})
        rbac_enforcer.assign_role("user1", "r1")
        conflicts = rbac_enforcer.check_sod_conflict("user1")
        assert len(conflicts) == 1
        assert conflicts[0][0].id == rule.id

    def test_get_sod_conflict_summary(self, rbac_enforcer):
        rule = SoDRule(
            permission_a="create",
            permission_b="approve",
            severity=SODConflictSeverity.CRITICAL,
            description="conflict",
        )
        rbac_enforcer._sod.add_rule(rule)
        rbac_enforcer.define_role("r1", {"create", "approve"})
        rbac_enforcer.assign_role("user1", "r1")
        summary = rbac_enforcer.get_sod_conflict_summary("user1")
        assert summary["critical"] == 1
        assert summary["high"] == 0

    # ---- Reporting ----
    def test_get_all_roles(self, rbac_enforcer):
        rbac_enforcer.define_role("r1", set())
        rbac_enforcer.define_role("r2", set())
        assert set(rbac_enforcer.get_all_roles()) == {"r1", "r2"}

    def test_get_all_users(self, rbac_enforcer):
        rbac_enforcer.define_role("r1", set())
        rbac_enforcer.assign_role("u1", "r1")
        rbac_enforcer.assign_role("u2", "r1")
        assert set(rbac_enforcer.get_all_users()) == {"u1", "u2"}

    def test_generate_report(self, rbac_enforcer):
        rbac_enforcer.define_role("r1", {"p1", "p2"})
        rbac_enforcer.assign_role("user1", "r1")
        report = rbac_enforcer.generate_report()
        assert report["total_users"] == 1
        assert report["total_roles"] == 1
        assert "user_compliance" in report
        assert report["user_compliance"]["user1"]["roles"] == ["r1"]
        assert report["compliant_users"] == 1
        assert report["compliant_percentage"] == 100.0

    def test_export_to_json(self, rbac_enforcer, tmp_path):
        rbac_enforcer.define_role("r1", {"p1"})
        rbac_enforcer.assign_role("user1", "r1")
        file_path = tmp_path / "rbac.json"
        rbac_enforcer.export_to_json(str(file_path))
        assert file_path.exists()
        with open(file_path) as f:
            data = json.load(f)
        assert "roles" in data
        assert data["roles"]["r1"] == ["p1"]
        assert "user_roles" in data
        assert data["user_roles"]["user1"] == ["r1"]

    # ---- Entity methods for RBACEnforcer ----
    def test_validate(self, rbac_enforcer):
        result = rbac_enforcer.validate()
        assert result["is_valid"] is True
        # add invalid permission type (non-string)
        rbac_enforcer.define_role("r1", {1, 2})  # ints not strings
        result2 = rbac_enforcer.validate()
        assert result2["is_valid"] is False
        assert any("invalid permission type" in e for e in result2["errors"])

    def test_to_dict(self, rbac_enforcer):
        rbac_enforcer.define_role("r1", {"p1"})
        rbac_enforcer.assign_role("user1", "r1")
        d = rbac_enforcer.to_dict()
        assert d["roles"]["r1"] == ["p1"]
        assert d["user_roles"]["user1"] == ["r1"]
        assert "sod_matrix" in d

    def test_from_dict(self, rbac_enforcer):
        rbac_enforcer.define_role("r1", {"p1"})
        rbac_enforcer.assign_role("user1", "r1")
        d = rbac_enforcer.to_dict()
        restored = RBACEnforcer.from_dict(d)
        assert restored._role_permissions["r1"] == {"p1"}
        assert restored._user_roles["user1"] == {"r1"}
        assert restored._version == rbac_enforcer._version

    def test_clone(self, rbac_enforcer):
        rbac_enforcer.define_role("r1", {"p1"})
        rbac_enforcer.assign_role("user1", "r1")
        cloned = rbac_enforcer.clone()
        assert cloned._role_permissions["r1"] == {"p1"}
        assert cloned._user_roles["user1"] == {"r1"}
        assert cloned._version == rbac_enforcer._version + 1
        assert cloned._sod is not rbac_enforcer._sod  # cloned SOD matrix

    def test_snapshot(self, rbac_enforcer):
        snap = rbac_enforcer.snapshot()
        assert snap["version"] == rbac_enforcer._version
        assert snap["roles_count"] == 0
        assert snap["users_count"] == 0
        assert "timestamp" in snap

    def test_version(self, rbac_enforcer):
        assert rbac_enforcer.version() == rbac_enforcer._version

    def test_audit_trail(self, rbac_enforcer):
        rbac_enforcer.define_role("r1", set())
        trail = rbac_enforcer.audit_trail()
        assert any(entry["action"] == "DEFINE_ROLE" for entry in trail)

    def test_touch(self, rbac_enforcer):
        old_version = rbac_enforcer._version
        touched = rbac_enforcer.touch("tester")
        assert touched._version == old_version + 1
        trail = touched.audit_trail()
        assert any(entry["action"] == "TOUCH" for entry in trail)

    def test_reset(self, rbac_enforcer):
        rbac_enforcer.define_role("r1", {"p1"})
        rbac_enforcer.assign_role("user1", "r1")
        rbac_enforcer.reset()
        assert rbac_enforcer._role_permissions == {}
        assert rbac_enforcer._user_roles == {}
        assert rbac_enforcer._version == 1
        # SOD matrix is reset too (default rules re-added)
        assert len(rbac_enforcer._sod.get_all_rules()) > 0
        trail = rbac_enforcer.audit_trail()
        assert any(entry["action"] == "RESET" for entry in trail)

    # ---- Additional edge cases ----
    def test_enforce_permission_import_error(self, rbac_enforcer):
        # Mock the import to fail to test fallback? Actually the exception is raised from within.
        # We'll just test that missing permission raises an exception.
        rbac_enforcer.define_role("r1", {"p1"})
        rbac_enforcer.assign_role("user1", "r1")
        # The function tries to import AuthorizationError; if not available, it might raise AttributeError.
        # To avoid that, we can patch the import.
        with patch("security_hardening.sod_matrix_rbac_enhanced.security_exceptions") as mock_sec:
            mock_sec.AuthorizationError = Exception  # mock to be a generic exception
            # We'll just ensure it raises an exception
            with pytest.raises(Exception):
                rbac_enforcer.enforce_permission("user1", "p2")
