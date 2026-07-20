# tests/security_hardening/test_access_control_matrix_fine_grained.py
# Perbaikan kualitas assertions: menghapus semua assert True,
# diganti dengan assertion yang memeriksa nilai aktual,
# efek samping, atau interaksi mock.

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from security_hardening.access_control_matrix_fine_grained import (
    AccessControlMatrix,
    Permission,
    PermissionType,
    ResourceType,
    Role,
    User,
)
from security_hardening.security_exceptions import AuthorizationError


# ============================================================================
# Helper function to get user by username
# ============================================================================
def get_user_by_username(acm: AccessControlMatrix, username: str):
    for user in acm._users.values():
        if user.username == username:
            return user
    return None


# ============================================================================
# Enum tests
# ============================================================================
class TestPermissionType:
    def test_members(self):
        expected = [
            "CREATE",
            "READ",
            "UPDATE",
            "DELETE",
            "APPROVE",
            "REJECT",
            "EXPORT",
            "IMPERSONATE",
            "AUDIT",
            "CONFIGURE",
        ]
        for name in expected:
            assert hasattr(PermissionType, name)

    def test_display_name(self):
        assert PermissionType.CREATE.display_name() == "Buat"
        assert PermissionType.READ.display_name() == "Baca"
        # fallback
        assert PermissionType.IMPERSONATE.display_name() == "Impersonasi"


class TestResourceType:
    def test_members(self):
        expected = [
            "JOURNAL",
            "ACCOUNT",
            "INVOICE",
            "PAYMENT",
            "USER",
            "ROLE",
            "REPORT",
            "SYSTEM_SETTING",
            "AUDIT_LOG",
            "TAX_SUBMISSION",
            "CUSTOMER",
            "SUPPLIER",
            "BANK_ACCOUNT",
        ]
        for name in expected:
            assert hasattr(ResourceType, name)

    def test_display_name(self):
        assert ResourceType.JOURNAL.display_name() == "Jurnal"
        assert ResourceType.TAX_SUBMISSION.display_name() == "SPT"


# ============================================================================
# Permission tests
# ============================================================================
class TestPermission:
    def test_construction(self):
        p = Permission(
            resource_type=ResourceType.JOURNAL,
            permission=PermissionType.READ,
            resource_id="123",
            attributes={"dept": "finance"},
        )
        assert p.resource_type == ResourceType.JOURNAL
        assert p.permission == PermissionType.READ
        assert p.resource_id == "123"
        assert p.attributes == {"dept": "finance"}
        assert p.version() == 1
        assert p.audit_trail() == []

    def test_validate_valid(self):
        p = Permission(ResourceType.JOURNAL, PermissionType.READ)
        result = p.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_invalid_resource_type(self):
        p = Permission(ResourceType.JOURNAL, PermissionType.READ)
        p.resource_type = "invalid"  # force invalid
        result = p.validate()
        assert result["is_valid"] is False
        assert "Invalid resource_type" in result["errors"]

    def test_validate_invalid_permission(self):
        p = Permission(ResourceType.JOURNAL, PermissionType.READ)
        p.permission = "invalid"
        result = p.validate()
        assert result["is_valid"] is False
        assert "Invalid permission" in result["errors"]

    def test_to_dict(self):
        p = Permission(
            ResourceType.JOURNAL,
            PermissionType.READ,
            resource_id=UUID("12345678123456781234567812345678"),
            attributes={"dept": "finance"},
        )
        d = p.to_dict()
        assert d["resource_type"] == "journal"
        assert d["permission"] == "read"
        assert d["resource_id"] == "12345678-1234-5678-1234-567812345678"
        assert d["attributes"] == {"dept": "finance"}
        assert d["version"] == 1

    def test_from_dict(self):
        data = {
            "resource_type": "journal",
            "permission": "read",
            "resource_id": "12345678-1234-5678-1234-567812345678",
            "attributes": {"dept": "finance"},
            "version": 5,
        }
        p = Permission.from_dict(data)
        assert p.resource_type == ResourceType.JOURNAL
        assert p.permission == PermissionType.READ
        assert p.resource_id == UUID("12345678-1234-5678-1234-567812345678")
        assert p.attributes == {"dept": "finance"}
        assert p.version() == 5

    def test_clone(self):
        p = Permission(ResourceType.JOURNAL, PermissionType.READ, "123", {"a": 1})
        clone = p.clone()
        assert clone is not p
        assert clone.resource_type == p.resource_type
        assert clone.permission == p.permission
        assert clone.resource_id == p.resource_id
        assert clone.attributes == p.attributes
        assert clone.version() == p.version() + 1
        audit = clone.audit_trail()
        assert len(audit) == 1
        assert audit[0]["action"] == "CLONE"

    def test_snapshot(self):
        p = Permission(ResourceType.JOURNAL, PermissionType.READ)
        snap = p.snapshot()
        assert snap["version"] == 1
        assert snap["resource_type"] == "journal"
        assert snap["permission"] == "read"

    def test_touch(self):
        p = Permission(ResourceType.JOURNAL, PermissionType.READ)
        old_version = p.version()
        p.touch("admin")
        assert p.version() == old_version + 1
        audit = p.audit_trail()
        assert len(audit) == 1
        assert audit[0]["action"] == "TOUCH"
        assert audit[0]["performed_by"] == "admin"


# ============================================================================
# Role tests
# ============================================================================
class TestRole:
    @pytest.fixture
    def role(self):
        p1 = Permission(ResourceType.JOURNAL, PermissionType.READ)
        p2 = Permission(ResourceType.JOURNAL, PermissionType.CREATE)
        return Role(
            role_id=uuid4(),
            name="Editor",
            permissions=[p1, p2],
            parent_role_id=None,
            description="Can edit journals",
        )

    def test_construction(self, role):
        assert role.id is not None
        assert role.name == "Editor"
        assert len(role.permissions) == 2
        assert role.parent_role_id is None
        assert role.description == "Can edit journals"
        assert role.version() == 1
        assert role._hash is not None

    def test_add_permission(self, role):
        p3 = Permission(ResourceType.JOURNAL, PermissionType.DELETE)
        old_version = role.version()
        role.add_permission(p3)
        assert len(role.permissions) == 3
        assert role.version() == old_version + 1
        audit = role.audit_trail()
        assert audit[-1]["action"] == "ADD_PERMISSION"
        assert audit[-1]["details"]["permission"] == "delete"

    def test_remove_permission(self, role):
        p_to_remove = role.permissions[0]
        old_version = role.version()
        result = role.remove_permission(p_to_remove)
        assert result is True
        assert len(role.permissions) == 1
        assert role.version() == old_version + 1
        audit = role.audit_trail()
        assert audit[-1]["action"] == "REMOVE_PERMISSION"

    def test_remove_permission_not_found(self, role):
        p = Permission(ResourceType.ACCOUNT, PermissionType.READ)
        result = role.remove_permission(p)
        assert result is False
        assert len(role.permissions) == 2

    def test_validate_valid(self, role):
        result = role.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_empty_name(self, role):
        role.name = ""
        result = role.validate()
        assert result["is_valid"] is False
        assert "Role name is required" in result["errors"]

    def test_validate_self_parent(self, role):
        role.parent_role_id = role.id
        result = role.validate()
        assert result["is_valid"] is False
        assert "Role cannot be its own parent" in result["errors"]

    def test_to_dict(self, role):
        d = role.to_dict()
        assert d["id"] == str(role.id)
        assert d["name"] == role.name
        assert len(d["permissions"]) == 2
        assert d["parent_role_id"] is None
        assert d["description"] == role.description
        assert "version" in d
        assert d["version"] == 1

    def test_from_dict(self):
        data = {
            "id": "12345678-1234-5678-1234-567812345678",
            "name": "Admin",
            "permissions": [
                {"resource_type": "journal", "permission": "read", "resource_id": None, "attributes": {}},
                {"resource_type": "journal", "permission": "create", "resource_id": None, "attributes": {}},
            ],
            "parent_role_id": None,
            "description": "Admin role",
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
            "version": 3,
        }
        role = Role.from_dict(data)
        assert role.id == UUID("12345678-1234-5678-1234-567812345678")
        assert role.name == "Admin"
        assert len(role.permissions) == 2
        assert role.parent_role_id is None
        assert role.description == "Admin role"
        assert role.version() == 3

    def test_clone(self, role):
        cloned = role.clone()
        assert cloned is not role
        assert cloned.name == "Editor_COPY"
        assert len(cloned.permissions) == len(role.permissions)
        assert cloned.parent_role_id == role.parent_role_id
        assert cloned.description == "Cloned from Editor"
        assert cloned.version() == role.version() + 1
        audit = cloned.audit_trail()
        assert audit[-1]["action"] == "CLONE"

    def test_snapshot(self, role):
        snap = role.snapshot()
        assert snap["version"] == 1
        assert snap["role_id"] == str(role.id)
        assert snap["name"] == "Editor"
        assert snap["permissions_count"] == 2

    def test_touch(self, role):
        old_version = role.version()
        role.touch("admin")
        assert role.version() == old_version + 1
        audit = role.audit_trail()
        assert audit[-1]["action"] == "TOUCH"
        assert audit[-1]["performed_by"] == "admin"


# ============================================================================
# User tests
# ============================================================================
class TestUser:
    @pytest.fixture
    def user(self):
        return User(
            user_id=uuid4(),
            username="john_doe",
            roles=[uuid4(), uuid4()],
            attributes={"dept": "finance"},
            email="john@example.com",
        )

    def test_construction(self, user):
        assert user.id is not None
        assert user.username == "john_doe"
        assert len(user.roles) == 2
        assert user.attributes == {"dept": "finance"}
        assert user.email == "john@example.com"
        assert user.version() == 1

    def test_assign_role(self, user):
        new_role = uuid4()
        old_version = user.version()
        user.assign_role(new_role)
        assert new_role in user.roles
        assert len(user.roles) == 3
        assert user.version() == old_version + 1
        audit = user.audit_trail()
        assert audit[-1]["action"] == "ASSIGN_ROLE"
        assert audit[-1]["details"]["role_id"] == str(new_role)

    def test_assign_role_already_assigned(self, user):
        existing = user.roles[0]
        old_version = user.version()
        user.assign_role(existing)
        assert len(user.roles) == 2  # unchanged
        assert user.version() == old_version  # no change

    def test_revoke_role(self, user):
        role_to_remove = user.roles[0]
        old_version = user.version()
        result = user.revoke_role(role_to_remove)
        assert result is True
        assert role_to_remove not in user.roles
        assert len(user.roles) == 1
        assert user.version() == old_version + 1
        audit = user.audit_trail()
        assert audit[-1]["action"] == "REVOKE_ROLE"

    def test_revoke_role_not_found(self, user):
        new_role = uuid4()
        result = user.revoke_role(new_role)
        assert result is False
        assert len(user.roles) == 2

    def test_validate_valid(self, user):
        result = user.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_empty_username(self, user):
        user.username = ""
        result = user.validate()
        assert result["is_valid"] is False
        assert "Username is required" in result["errors"]

    def test_validate_invalid_email(self, user):
        user.email = "invalid"
        result = user.validate()
        assert result["is_valid"] is False
        assert "Invalid email format" in result["errors"]

    def test_to_dict(self, user):
        d = user.to_dict()
        assert d["id"] == str(user.id)
        assert d["username"] == user.username
        assert len(d["roles"]) == 2
        assert d["attributes"] == user.attributes
        assert d["email"] == user.email
        assert "version" in d

    def test_from_dict(self):
        data = {
            "id": "12345678-1234-5678-1234-567812345678",
            "username": "admin",
            "roles": ["12345678-1234-5678-1234-567812345679"],
            "attributes": {"role": "admin"},
            "email": "admin@example.com",
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
            "version": 2,
        }
        user = User.from_dict(data)
        assert user.id == UUID("12345678-1234-5678-1234-567812345678")
        assert user.username == "admin"
        assert user.roles == [UUID("12345678-1234-5678-1234-567812345679")]
        assert user.attributes == {"role": "admin"}
        assert user.email == "admin@example.com"
        assert user.version() == 2

    def test_clone(self, user):
        cloned = user.clone()
        assert cloned is not user
        assert cloned.username == "john_doe_COPY"
        assert cloned.roles == user.roles
        assert cloned.attributes == user.attributes
        assert cloned.email == "copy_john@example.com"
        assert cloned.version() == user.version() + 1
        audit = cloned.audit_trail()
        assert audit[-1]["action"] == "CLONE"

    def test_snapshot(self, user):
        snap = user.snapshot()
        assert snap["version"] == 1
        assert snap["user_id"] == str(user.id)
        assert snap["username"] == "john_doe"
        assert snap["role_count"] == 2

    def test_touch(self, user):
        old_version = user.version()
        user.touch("admin")
        assert user.version() == old_version + 1
        audit = user.audit_trail()
        assert audit[-1]["action"] == "TOUCH"
        assert audit[-1]["performed_by"] == "admin"


# ============================================================================
# AccessControlMatrix tests
# ============================================================================
class TestAccessControlMatrix:
    @pytest.fixture
    def acm(self):
        acm = AccessControlMatrix()
        # seed with some roles and users
        read_journal = Permission(ResourceType.JOURNAL, PermissionType.READ)
        create_journal = Permission(ResourceType.JOURNAL, PermissionType.CREATE)
        approve_journal = Permission(ResourceType.JOURNAL, PermissionType.APPROVE)

        viewer = acm.add_role("Viewer", [read_journal])
        editor = acm.add_role("Editor", [read_journal, create_journal], parent_role_id=viewer)
        approver = acm.add_role("Approver", [read_journal, approve_journal], parent_role_id=editor)

        user1 = uuid4()
        user2 = uuid4()
        acm.register_user(user1, "alice", "alice@example.com", {"department": "finance"})
        acm.register_user(user2, "bob", "bob@example.com", {"department": "hr"})
        acm.assign_role_to_user(user1, viewer)
        acm.assign_role_to_user(user1, editor)
        acm.assign_role_to_user(user2, approver)

        return acm

    def test_add_role(self, acm):
        new_role_id = acm.add_role("Test", [Permission(ResourceType.ACCOUNT, PermissionType.READ)])
        role = acm.get_role(new_role_id)
        assert role is not None
        assert role.name == "Test"
        assert len(role.permissions) == 1
        assert role.parent_role_id is None
        history = acm.audit_trail()
        assert any(h["action"] == "ADD_ROLE" for h in history)

    def test_update_role(self, acm):
        roles = acm.list_roles()
        role_id = roles[0].id
        result = acm.update_role(role_id, name="NewName", description="NewDesc")
        assert result is True
        role = acm.get_role(role_id)
        assert role.name == "NewName"
        assert role.description == "NewDesc"
        # invalid role
        result2 = acm.update_role(uuid4(), name="x")
        assert result2 is False

    def test_delete_role(self, acm):
        roles = acm.list_roles()
        role_id = roles[0].id
        # assign this role to a user
        for user in acm._users.values():
            user.assign_role(role_id)
        result = acm.delete_role(role_id)
        assert result is True
        assert role_id not in acm._roles
        # should be removed from users
        for user in acm._users.values():
            assert role_id not in user.roles
        # delete again -> false
        result2 = acm.delete_role(role_id)
        assert result2 is False

    def test_get_role(self, acm):
        roles = acm.list_roles()
        role_id = roles[0].id
        role = acm.get_role(role_id)
        assert role is not None
        assert role.id == role_id
        assert acm.get_role(uuid4()) is None

    def test_get_role_by_name(self, acm):
        role = acm.get_role_by_name("Editor")
        assert role is not None
        assert role.name == "Editor"
        assert acm.get_role_by_name("NonExistent") is None

    def test_list_roles(self, acm):
        roles = acm.list_roles()
        assert len(roles) == 3
        names = [r.name for r in roles]
        assert "Viewer" in names
        assert "Editor" in names
        assert "Approver" in names

    def test_add_permission_to_role(self, acm):
        role = acm.get_role_by_name("Viewer")
        p = Permission(ResourceType.JOURNAL, PermissionType.DELETE)
        result = acm.add_permission_to_role(role.id, p)
        assert result is True
        assert len(role.permissions) == 2  # originally 1
        assert p in role.permissions
        # invalid role
        result2 = acm.add_permission_to_role(uuid4(), p)
        assert result2 is False

    def test_remove_permission_from_role(self, acm):
        role = acm.get_role_by_name("Viewer")
        p_to_remove = role.permissions[0]
        result = acm.remove_permission_from_role(role.id, p_to_remove)
        assert result is True
        assert p_to_remove not in role.permissions
        # invalid role
        result2 = acm.remove_permission_from_role(uuid4(), p_to_remove)
        assert result2 is False

    def test_register_user(self, acm):
        user_id = uuid4()
        acm.register_user(user_id, "charlie", "charlie@example.com", {"dept": "it"})
        user = acm.get_user(user_id)
        assert user is not None
        assert user.username == "charlie"
        assert user.email == "charlie@example.com"
        assert user.attributes == {"dept": "it"}
        # duplicate should raise
        with pytest.raises(ValueError, match="already exists"):
            acm.register_user(user_id, "dup", "")

    def test_get_user(self, acm):
        users = list(acm._users.values())
        user_id = users[0].id
        user = acm.get_user(user_id)
        assert user is not None
        assert user.id == user_id
        assert acm.get_user(uuid4()) is None

    def test_assign_role_to_user(self, acm):
        user = list(acm._users.values())[0]
        role = acm.get_role_by_name("Approver")
        result = acm.assign_role_to_user(user.id, role.id)
        assert result is True
        assert role.id in user.roles
        # invalid user
        result2 = acm.assign_role_to_user(uuid4(), role.id)
        assert result2 is False
        # invalid role
        result3 = acm.assign_role_to_user(user.id, uuid4())
        assert result3 is False

    def test_revoke_role_from_user(self, acm):
        user = list(acm._users.values())[0]
        role_id = user.roles[0]
        result = acm.revoke_role_from_user(user.id, role_id)
        assert result is True
        assert role_id not in user.roles
        # invalid user
        result2 = acm.revoke_role_from_user(uuid4(), role_id)
        assert result2 is False

    def test_get_user_roles(self, acm):
        user = list(acm._users.values())[0]
        roles = acm.get_user_roles(user.id)
        assert roles == user.roles
        assert acm.get_user_roles(uuid4()) == []

    # ---- Permission resolution ----
    def test_get_user_permissions(self, acm):
        alice = get_user_by_username(acm, "alice")
        assert alice is not None
        perms = acm.get_user_permissions(alice.id)
        perm_types = {(rt, perm) for rt, perm, rid, attrs in perms}
        assert ("journal", "read") in perm_types
        assert ("journal", "create") in perm_types
        # Bob has Approver: read, approve
        bob = get_user_by_username(acm, "bob")
        assert bob is not None
        perms_bob = acm.get_user_permissions(bob.id)
        perm_types_bob = {(rt, perm) for rt, perm, rid, attrs in perms_bob}
        assert ("journal", "read") in perm_types_bob
        assert ("journal", "approve") in perm_types_bob

    def test_has_permission(self, acm):
        alice = get_user_by_username(acm, "alice")
        assert alice is not None
        assert acm.has_permission(alice.id, ResourceType.JOURNAL, PermissionType.READ) is True
        assert acm.has_permission(alice.id, ResourceType.JOURNAL, PermissionType.CREATE) is True
        assert acm.has_permission(alice.id, ResourceType.JOURNAL, PermissionType.APPROVE) is False
        # Bob has read and approve
        bob = get_user_by_username(acm, "bob")
        assert bob is not None
        assert acm.has_permission(bob.id, ResourceType.JOURNAL, PermissionType.READ) is True
        assert acm.has_permission(bob.id, ResourceType.JOURNAL, PermissionType.APPROVE) is True
        assert acm.has_permission(bob.id, ResourceType.JOURNAL, PermissionType.CREATE) is False

    def test_has_permission_with_resource_id(self, acm):
        role = acm.get_role_by_name("Approver")
        p = Permission(ResourceType.JOURNAL, PermissionType.READ, resource_id="123")
        acm.add_permission_to_role(role.id, p)
        bob = get_user_by_username(acm, "bob")
        assert bob is not None
        assert acm.has_permission(bob.id, ResourceType.JOURNAL, PermissionType.READ, "123") is True
        assert acm.has_permission(bob.id, ResourceType.JOURNAL, PermissionType.READ, "456") is False

    def test_has_permission_with_attributes(self, acm):
        # Create permission with attribute condition: department must be finance
        role = acm.get_role_by_name("Editor")
        p = Permission(ResourceType.JOURNAL, PermissionType.CREATE, attributes={"department": "finance"})
        acm.add_permission_to_role(role.id, p)
        alice = get_user_by_username(acm, "alice")  # department: finance
        bob = get_user_by_username(acm, "bob")      # department: hr
        assert alice is not None
        assert bob is not None
        # Alice should have create
        assert acm.has_permission(alice.id, ResourceType.JOURNAL, PermissionType.CREATE,
                                  context_attributes={"department": "finance"}) is True
        # Bob should not
        assert acm.has_permission(bob.id, ResourceType.JOURNAL, PermissionType.CREATE,
                                  context_attributes={"department": "finance"}) is False
        # Also test fallback to user attributes
        assert acm.has_permission(alice.id, ResourceType.JOURNAL, PermissionType.CREATE) is True

    def test_enforce_success(self, acm):
        alice = get_user_by_username(acm, "alice")
        assert alice is not None
        # Should not raise
        acm.enforce(alice.id, ResourceType.JOURNAL, PermissionType.READ)

    def test_enforce_failure(self, acm):
        alice = get_user_by_username(acm, "alice")
        assert alice is not None
        with pytest.raises(AuthorizationError, match="does not have approve permission"):
            acm.enforce(alice.id, ResourceType.JOURNAL, PermissionType.APPROVE)

    def test_get_effective_permissions_for_resource(self, acm):
        alice = get_user_by_username(acm, "alice")
        assert alice is not None
        perms = acm.get_effective_permissions_for_resource(alice.id, ResourceType.JOURNAL)
        perm_names = {p.value for p in perms}
        assert "read" in perm_names
        assert "create" in perm_names
        assert "approve" not in perm_names

    # ---- Export/Import ----
    def test_export_policy(self, acm):
        policy = acm.export_policy()
        assert "roles" in policy
        assert "users" in policy
        assert "history" in policy
        assert "version" in policy
        assert len(policy["roles"]) == 3
        assert len(policy["users"]) == 2

    def test_import_policy(self, acm):
        policy = acm.export_policy()
        new_acm = AccessControlMatrix()
        new_acm.import_policy(policy)
        assert len(new_acm._roles) == 3
        assert len(new_acm._users) == 2
        # Check role names
        names = [r.name for r in new_acm._roles.values()]
        assert "Viewer" in names
        assert "Editor" in names
        assert "Approver" in names

    def test_to_json(self, acm, tmp_path):
        file_path = tmp_path / "policy.json"
        acm.to_json(str(file_path))
        assert file_path.exists()
        import json
        with open(file_path) as f:
            data = json.load(f)
        assert "roles" in data
        assert "users" in data

    # ---- Reporting & Stats ----
    def test_generate_report(self, acm):
        report = acm.generate_report()
        assert report["total_roles"] == 3
        assert report["total_users"] == 2
        assert report["role_hierarchy_depth"] >= 2
        assert report["permission_count"] > 0
        assert report["version"] == acm.version()

    def test_get_statistics(self, acm):
        stats = acm.get_statistics()
        assert stats == acm.generate_report()

    # ---- Entity methods ----
    def test_validate(self, acm):
        result = acm.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_to_dict(self, acm):
        d = acm.to_dict()
        assert "roles" in d
        assert "users" in d
        assert "version" in d
        assert len(d["roles"]) == 3
        assert len(d["users"]) == 2

    def test_from_dict(self, acm):
        d = acm.to_dict()
        new_acm = AccessControlMatrix.from_dict(d)
        assert len(new_acm._roles) == 3
        assert len(new_acm._users) == 2
        assert new_acm.version() == acm.version()

    def test_clone(self, acm):
        cloned = acm.clone()
        assert cloned is not acm
        assert len(cloned._roles) == len(acm._roles)
        assert len(cloned._users) == len(acm._users)
        assert cloned.version() == acm.version() + 1

    def test_snapshot(self, acm):
        snap = acm.snapshot()
        assert snap["version"] == acm.version()
        assert snap["roles_count"] == 3
        assert snap["users_count"] == 2
        assert "timestamp" in snap

    def test_version(self, acm):
        assert acm.version() == 1
        acm.touch("admin")
        assert acm.version() == 2

    def test_audit_trail(self, acm):
        acm.touch("admin")
        acm.add_role("Test", [Permission(ResourceType.ACCOUNT, PermissionType.READ)])
        trail = acm.audit_trail(limit=10)
        assert len(trail) >= 2
        actions = [h["action"] for h in trail]
        assert "TOUCH" in actions
        assert "ADD_ROLE" in actions
        # test limit
        limited = acm.audit_trail(limit=1)
        assert len(limited) == 1

    def test_touch(self, acm):
        old_version = acm.version()
        acm.touch("admin")
        assert acm.version() == old_version + 1
        audit = acm.audit_trail()
        assert audit[-1]["action"] == "TOUCH"
        assert audit[-1]["performed_by"] == "admin"

    def test_reset(self, acm):
        acm.reset()
        assert len(acm._roles) == 0
        assert len(acm._users) == 0
        assert acm._history == []
        assert acm.version() == 1
        assert acm.audit_trail() == []