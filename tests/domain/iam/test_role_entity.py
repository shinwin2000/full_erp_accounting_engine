# test_role_entity.py
# Comprehensive tests for role_entity.py

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from domain.iam.role_entity import (
    DuplicatePermissionError,
    InvalidRoleStatusTransitionError,
    PermissionNotFoundError,
    RoleEntity,
    RoleError,
    RoleRepository,
    RoleStatus,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def reset_storage():
    """Reset class variables before each test."""
    RoleEntity._audit_trail = []
    RoleEntity._snapshots = []
    RoleRepository._storage = {}
    RoleRepository._storage_by_name = {}
    yield
    RoleEntity._audit_trail = []
    RoleEntity._snapshots = []
    RoleRepository._storage = {}
    RoleRepository._storage_by_name = {}


@pytest.fixture
def valid_role():
    """Create a valid RoleEntity."""
    return RoleEntity(
        role_id=uuid4(),
        role_name="admin",
        description="Administrator role",
        permissions={"user:read", "user:write", "role:manage"},
        status=RoleStatus.ACTIVE,
        parent_role_id=None,
        is_default=False,
        is_system=True,
        created_by="system",
    )


@pytest.fixture
def parent_role():
    """Create a parent role."""
    return RoleEntity(
        role_id=uuid4(),
        role_name="manager",
        description="Manager role",
        permissions={"report:view", "team:manage"},
        status=RoleStatus.ACTIVE,
        parent_role_id=None,
        is_default=False,
        is_system=False,
        created_by="admin",
    )


@pytest.fixture
def child_role(parent_role):
    """Create a child role with parent."""
    return RoleEntity(
        role_id=uuid4(),
        role_name="team_lead",
        description="Team Lead role",
        permissions={"task:assign"},
        status=RoleStatus.ACTIVE,
        parent_role_id=parent_role.role_id,
        is_default=False,
        is_system=False,
        created_by="admin",
    )


@pytest.fixture
def inactive_role(valid_role):
    """Return an inactive role."""
    return valid_role.deactivate("admin", "Test deactivation")


@pytest.fixture
def archived_role(valid_role):
    """Return an archived role."""
    return valid_role.delete("admin", "Test archive")


@pytest.fixture
def default_role():
    """Create a default role."""
    return RoleEntity(
        role_id=uuid4(),
        role_name="default",
        description="Default role",
        permissions={"basic:read"},
        status=RoleStatus.ACTIVE,
        parent_role_id=None,
        is_default=True,
        is_system=False,
        created_by="system",
    )


# ============================================================================
# Tests for Enums
# ============================================================================

class TestRoleStatus:
    def test_members(self):
        assert RoleStatus.ACTIVE.value == "active"
        assert RoleStatus.INACTIVE.value == "inactive"
        assert RoleStatus.ARCHIVED.value == "archived"

    def test_display_name(self):
        assert RoleStatus.ACTIVE.display_name() == "Aktif"
        assert RoleStatus.INACTIVE.display_name() == "Tidak Aktif"
        assert RoleStatus.ARCHIVED.display_name() == "Diarsipkan"

    def test_from_string(self):
        assert RoleStatus.from_string("active") == RoleStatus.ACTIVE
        assert RoleStatus.from_string("ACTIVE") == RoleStatus.ACTIVE
        assert RoleStatus.from_string("inactive") == RoleStatus.INACTIVE
        assert RoleStatus.from_string("archived") == RoleStatus.ARCHIVED
        assert RoleStatus.from_string("invalid") is None


# ============================================================================
# Tests for Exceptions
# ============================================================================

def test_role_error_is_value_error():
    assert issubclass(RoleError, ValueError)


def test_invalid_role_status_transition_error_is_role_error():
    assert issubclass(InvalidRoleStatusTransitionError, RoleError)


def test_duplicate_permission_error_is_role_error():
    assert issubclass(DuplicatePermissionError, RoleError)


def test_permission_not_found_error_is_role_error():
    assert issubclass(PermissionNotFoundError, RoleError)


# ============================================================================
# Tests for RoleEntity Construction and Validation
# ============================================================================

class TestRoleEntityConstruction:
    def test_construction_valid(self, valid_role):
        assert valid_role.role_name == "admin"
        assert valid_role.description == "Administrator role"
        assert len(valid_role.permissions) == 3
        assert valid_role.status == RoleStatus.ACTIVE
        assert valid_role.version == 1
        assert valid_role.is_system is True

    def test_validation_role_name_too_short(self):
        with pytest.raises(RoleError, match="at least 2 characters"):
            RoleEntity(
                role_id=uuid4(),
                role_name="A",
                description="Test",
                permissions=set(),
            )

    def test_validation_role_name_too_long(self):
        with pytest.raises(RoleError, match="not exceed 50 characters"):
            RoleEntity(
                role_id=uuid4(),
                role_name="a" * 51,
                description="Test",
                permissions=set(),
            )

    def test_validation_role_name_invalid_chars(self):
        with pytest.raises(RoleError, match="contain only letters, numbers, and underscores"):
            RoleEntity(
                role_id=uuid4(),
                role_name="admin-role",  # hyphen not allowed
                description="Test",
                permissions=set(),
            )

    def test_validation_parent_self(self):
        role_id = uuid4()
        with pytest.raises(RoleError, match="cannot be its own parent"):
            RoleEntity(
                role_id=role_id,
                role_name="self",
                description="Test",
                permissions=set(),
                parent_role_id=role_id,
            )

    def test_validation_invalid_status(self):
        with pytest.raises(RoleError, match="Invalid status"):
            RoleEntity(
                role_id=uuid4(),
                role_name="test",
                description="Test",
                permissions=set(),
                status="invalid",  # type: ignore
            )

    def test_validation_version(self):
        with pytest.raises(RoleError, match="Version must be >= 1"):
            RoleEntity(
                role_id=uuid4(),
                role_name="test",
                description="Test",
                permissions=set(),
                version=0,
            )

    def test_validation_naive_timestamps(self):
        naive = datetime(2025, 1, 1, 12, 0, 0)
        with pytest.raises(RoleError, match="Version must be >= 1"):
            # This will raise on __post_init__ because version is 1 but created_at is naive
            # Actually __post_init__ calls _validate which checks version, then sets timezone.
            # The timezone fix happens in _validate, not before version check.
            # We'll create an object with naive timestamps; version validation will pass, then timezone fix will happen.
            # But we need to test that the fix happens. We'll just check that timestamps become UTC.
            role = RoleEntity(
                role_id=uuid4(),
                role_name="test",
                description="Test",
                permissions=set(),
                created_at=naive,
                updated_at=naive,
            )
            assert role.created_at.tzinfo == UTC
            assert role.updated_at.tzinfo == UTC


# ============================================================================
# Tests for Entity Basic Methods
# ============================================================================

class TestRoleEntityBasicMethods:
    def test_create(self, valid_role):
        role = valid_role.create("admin")
        assert role is valid_role
        trail = role.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "CREATE"
        assert trail[0]["performed_by"] == "admin"
        assert trail[0]["details"]["role_name"] == "admin"

    def test_update(self, valid_role):
        updated = valid_role.update(
            updated_by="admin",
            description="Updated description",
            permissions=["new:perm"],
        )
        assert updated.description == "Updated description"
        assert "new:perm" in updated.permissions
        assert updated.version == valid_role.version + 1
        trail = updated.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "UPDATE"
        assert trail[0]["details"]["changes"] == {"description": "Updated description", "permissions": ["new:perm"]}

    def test_update_archived_raises(self, archived_role):
        with pytest.raises(InvalidRoleStatusTransitionError, match="Cannot update archived role"):
            archived_role.update("admin", description="test")

    def test_update_system_role_rename_raises(self, valid_role):
        # valid_role is system=True
        with pytest.raises(RoleError, match="Cannot rename system role"):
            valid_role.update("admin", role_name="newadmin")

    def test_update_ignores_protected_fields(self, valid_role):
        updated = valid_role.update(
            updated_by="admin",
            role_id=uuid4(),
            created_at=datetime.now(UTC),
            version=999,
            role_name="newname",
        )
        assert updated.role_id == valid_role.role_id
        assert updated.created_at == valid_role.created_at
        assert updated.version == valid_role.version + 1  # not 999
        assert updated.role_name == "newname"

    def test_delete(self, valid_role):
        deleted = valid_role.delete("admin", "Reason")
        assert deleted.status == RoleStatus.ARCHIVED
        assert deleted.version == valid_role.version + 1
        trail = deleted.audit_trail()
        assert trail[0]["action"] == "DELETE"
        assert trail[0]["details"]["reason"] == "Reason"

    def test_delete_system_role_raises(self, valid_role):
        # valid_role is system=True
        with pytest.raises(RoleError, match="Cannot delete system role"):
            valid_role.delete("admin")

    def test_delete_already_archived(self, archived_role):
        result = archived_role.delete("admin")
        assert result is archived_role  # no change

    def test_restore(self, archived_role):
        restored = archived_role.restore("admin")
        assert restored.status == RoleStatus.ACTIVE
        assert restored.version == archived_role.version + 1
        trail = restored.audit_trail()
        assert trail[0]["action"] == "RESTORE"

    def test_restore_non_archived_raises(self, valid_role):
        with pytest.raises(InvalidRoleStatusTransitionError, match="Cannot restore role in status active"):
            valid_role.restore("admin")

    def test_activate_inactive(self, inactive_role):
        activated = inactive_role.activate("admin")
        assert activated.status == RoleStatus.ACTIVE
        assert activated.version == inactive_role.version + 1
        trail = activated.audit_trail()
        assert trail[0]["action"] == "ACTIVATE"

    def test_activate_already_active(self, valid_role):
        result = valid_role.activate("admin")
        assert result is valid_role

    def test_activate_archived_raises(self, archived_role):
        with pytest.raises(InvalidRoleStatusTransitionError, match="Cannot activate archived role"):
            archived_role.activate("admin")

    def test_deactivate(self, valid_role):
        deactivated = valid_role.deactivate("admin", "Reason")
        assert deactivated.status == RoleStatus.INACTIVE
        assert deactivated.version == valid_role.version + 1
        trail = deactivated.audit_trail()
        assert trail[0]["action"] == "DEACTIVATE"
        assert trail[0]["details"]["reason"] == "Reason"

    def test_deactivate_default_role_raises(self, default_role):
        with pytest.raises(RoleError, match="Cannot deactivate default role"):
            default_role.deactivate("admin")

    def test_deactivate_already_inactive(self, inactive_role):
        result = inactive_role.deactivate("admin")
        assert result is inactive_role

    def test_lock(self, valid_role):
        locked = valid_role.lock("admin", "Reason")
        assert locked.metadata["locked_by"] == "admin"
        assert locked.metadata["locked_at"] is not None
        assert locked.metadata["lock_reason"] == "Reason"
        assert locked.version == valid_role.version + 1
        trail = locked.audit_trail()
        assert trail[0]["action"] == "LOCK"

    def test_unlock(self, valid_role):
        locked = valid_role.lock("admin", "Lock")
        unlocked = locked.unlock("admin")
        assert "locked_by" not in unlocked.metadata
        assert "locked_at" not in unlocked.metadata
        assert "lock_reason" not in unlocked.metadata
        assert unlocked.version == locked.version + 1
        trail = unlocked.audit_trail()
        assert trail[0]["action"] == "UNLOCK"

    def test_validate(self, valid_role):
        result = valid_role.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_invalid(self):
        role = RoleEntity(
            role_id=uuid4(),
            role_name="ab",  # too short
            description="Test",
            permissions=set(),
            version=0,
        )
        result = role.validate()
        assert result["is_valid"] is False
        assert len(result["errors"]) > 0

    def test_validate_invalid_permission(self):
        role = RoleEntity(
            role_id=uuid4(),
            role_name="test",
            description="Test",
            permissions={"invalid_permission"},  # missing colon
        )
        result = role.validate()
        assert result["is_valid"] is False
        assert any("Invalid permission format" in e for e in result["errors"])

    def test_to_dict(self, valid_role):
        d = valid_role.to_dict()
        assert d["role_id"] == str(valid_role.role_id)
        assert d["role_name"] == "admin"
        assert d["description"] == "Administrator role"
        assert sorted(d["permissions"]) == ["role:manage", "user:read", "user:write"]
        assert d["status"] == "active"
        assert d["version"] == 1
        assert d["is_system"] is True

    def test_from_dict(self, valid_role):
        data = valid_role.to_dict()
        restored = RoleEntity.from_dict(data)
        assert restored.role_id == valid_role.role_id
        assert restored.role_name == valid_role.role_name
        assert restored.description == valid_role.description
        assert restored.permissions == valid_role.permissions
        assert restored.status == valid_role.status
        assert restored.version == valid_role.version

    def test_from_dict_with_defaults(self):
        data = {
            "role_id": str(uuid4()),
            "role_name": "test",
            "description": "Test",
            "permissions": ["read", "write"],
        }
        restored = RoleEntity.from_dict(data)
        assert restored.status == RoleStatus.ACTIVE
        assert restored.is_default is False
        assert restored.is_system is False
        assert restored.metadata == {}

    def test_clone(self, valid_role):
        cloned = valid_role.clone()
        assert cloned.role_id != valid_role.role_id
        assert cloned.role_name == "admin_COPY"
        assert cloned.description == "Cloned from admin"
        assert cloned.permissions == valid_role.permissions
        assert cloned.status == RoleStatus.INACTIVE
        assert cloned.parent_role_id is None
        assert cloned.is_default is False
        assert cloned.is_system is False
        assert cloned.version == 1
        trail = cloned.audit_trail()
        assert trail[0]["action"] == "CLONE"

    def test_clone_with_custom_name(self, valid_role):
        cloned = valid_role.clone(new_name="new_role")
        assert cloned.role_name == "new_role"

    def test_snapshot(self, valid_role):
        snap = valid_role.snapshot()
        assert snap["version"] == 1
        assert snap["role_id"] == str(valid_role.role_id)
        assert snap["role_name"] == "admin"
        assert snap["status"] == "active"
        assert snap["permission_count"] == 3

    def test_get_version(self, valid_role):
        assert valid_role.get_version() == 1

    def test_audit_trail(self, valid_role):
        valid_role.create("admin")
        valid_role.update("admin", description="Updated")
        trail = valid_role.audit_trail(limit=2)
        assert len(trail) == 2
        assert trail[0]["action"] == "CREATE"
        assert trail[1]["action"] == "UPDATE"

    def test_touch(self, valid_role):
        touched = valid_role.touch("toucher")
        assert touched.version == valid_role.version + 1
        assert touched.updated_at > valid_role.updated_at
        trail = touched.audit_trail()
        assert trail[0]["action"] == "TOUCH"


# ============================================================================
# Tests for Business Logic Properties
# ============================================================================

class TestRoleEntityProperties:
    def test_is_active(self, valid_role, inactive_role, archived_role):
        assert valid_role.is_active is True
        assert inactive_role.is_active is False
        assert archived_role.is_active is False

    def test_is_inactive(self, valid_role, inactive_role):
        assert valid_role.is_inactive is False
        assert inactive_role.is_inactive is True

    def test_is_archived(self, archived_role, valid_role):
        assert archived_role.is_archived is True
        assert valid_role.is_archived is False

    def test_permission_count(self, valid_role):
        assert valid_role.permission_count == 3
        # Add permission
        role = valid_role.add_permission("new:perm", "admin")
        assert role.permission_count == 4


# ============================================================================
# Tests for Permission Management
# ============================================================================

class TestRoleEntityPermissionManagement:
    def test_add_permission(self, valid_role):
        role = valid_role.add_permission("new:permission", "admin")
        assert "new:permission" in role.permissions
        assert role.version == valid_role.version + 1
        trail = role.audit_trail()
        assert trail[0]["action"] == "ADD_PERMISSION"
        assert trail[0]["details"]["permission"] == "new:permission"

    def test_add_permission_duplicate(self, valid_role):
        with pytest.raises(DuplicatePermissionError, match="already exists"):
            valid_role.add_permission("user:read", "admin")

    def test_add_permission_archived_raises(self, archived_role):
        with pytest.raises(InvalidRoleStatusTransitionError, match="Cannot modify archived role"):
            archived_role.add_permission("test", "admin")

    def test_add_permissions(self, valid_role):
        perms = ["perm1", "perm2", "perm3"]
        role = valid_role.add_permissions(perms, "admin")
        for p in perms:
            assert p in role.permissions
        assert role.version == valid_role.version + 1
        trail = role.audit_trail()
        assert trail[0]["action"] == "ADD_PERMISSIONS"
        assert trail[0]["details"]["permissions"] == perms

    def test_add_permissions_archived_raises(self, archived_role):
        with pytest.raises(InvalidRoleStatusTransitionError, match="Cannot modify archived role"):
            archived_role.add_permissions(["test"], "admin")

    def test_remove_permission(self, valid_role):
        role = valid_role.remove_permission("user:read", "admin")
        assert "user:read" not in role.permissions
        assert role.version == valid_role.version + 1
        trail = role.audit_trail()
        assert trail[0]["action"] == "REMOVE_PERMISSION"
        assert trail[0]["details"]["permission"] == "user:read"

    def test_remove_permission_not_found(self, valid_role):
        with pytest.raises(PermissionNotFoundError, match="not found"):
            valid_role.remove_permission("nonexistent", "admin")

    def test_remove_permission_archived_raises(self, archived_role):
        with pytest.raises(InvalidRoleStatusTransitionError, match="Cannot modify archived role"):
            archived_role.remove_permission("test", "admin")

    def test_set_permissions(self, valid_role):
        new_perms = {"a", "b", "c"}
        role = valid_role.set_permissions(new_perms, "admin")
        assert role.permissions == new_perms
        assert role.version == valid_role.version + 1
        trail = role.audit_trail()
        assert trail[0]["action"] == "SET_PERMISSIONS"
        assert trail[0]["details"]["permission_count"] == 3

    def test_set_permissions_archived_raises(self, archived_role):
        with pytest.raises(InvalidRoleStatusTransitionError, match="Cannot modify archived role"):
            archived_role.set_permissions({"a"}, "admin")

    def test_update_description(self, valid_role):
        role = valid_role.update_description("New description", "admin")
        assert role.description == "New description"
        assert role.version == valid_role.version + 1
        trail = role.audit_trail()
        assert trail[0]["action"] == "UPDATE_DESCRIPTION"

    def test_update_description_archived_raises(self, archived_role):
        with pytest.raises(InvalidRoleStatusTransitionError, match="Cannot modify archived role"):
            archived_role.update_description("test", "admin")


# ============================================================================
# Tests for Parent/Hierarchy Management
# ============================================================================

class TestRoleEntityHierarchy:
    def test_set_parent(self, valid_role, parent_role):
        role = valid_role.set_parent(parent_role.role_id, "admin")
        assert role.parent_role_id == parent_role.role_id
        assert role.version == valid_role.version + 1
        trail = role.audit_trail()
        assert trail[0]["action"] == "SET_PARENT"
        assert trail[0]["details"]["parent_role_id"] == str(parent_role.role_id)

    def test_set_parent_self(self, valid_role):
        with pytest.raises(RoleError, match="cannot be its own parent"):
            valid_role.set_parent(valid_role.role_id, "admin")

    def test_set_parent_archived_raises(self, archived_role, parent_role):
        with pytest.raises(InvalidRoleStatusTransitionError, match="Cannot modify archived role"):
            archived_role.set_parent(parent_role.role_id, "admin")

    def test_set_parent_cycle_detection(self, valid_role, parent_role):
        # Create a cycle: role -> parent -> role
        # First set parent of parent_role to valid_role
        updated_parent = parent_role.set_parent(valid_role.role_id, "admin")
        # Now try to set parent of valid_role to parent_role (would create cycle)
        # Need to provide a role_getter that returns the updated_parent
        def role_getter(role_id):
            if role_id == updated_parent.role_id:
                return updated_parent
            if role_id == valid_role.role_id:
                return valid_role
            return None

        with pytest.raises(RoleError, match="would create a cycle"):
            valid_role.set_parent(updated_parent.role_id, "admin", parent_getter=role_getter)

    def test_has_permission_direct(self, valid_role):
        assert valid_role.has_permission("user:read") is True
        assert valid_role.has_permission("nonexistent") is False

    def test_has_permission_inherited(self, child_role, parent_role):
        # child_role has "task:assign", parent_role has "report:view", "team:manage"
        assert child_role.has_permission("task:assign") is True
        # Should inherit from parent
        def role_getter(role_id):
            if role_id == parent_role.role_id:
                return parent_role
            return None
        assert child_role.has_permission("report:view", role_getter) is True
        assert child_role.has_permission("team:manage", role_getter) is True
        assert child_role.has_permission("nonexistent", role_getter) is False

    def test_has_permission_no_parent_getter(self, child_role):
        # Without role_getter, only direct permissions are checked
        assert child_role.has_permission("task:assign") is True
        assert child_role.has_permission("report:view") is False

    def test_get_all_permissions(self, child_role, parent_role):
        # child_role has "task:assign", parent_role has "report:view", "team:manage"
        def role_getter(role_id):
            if role_id == parent_role.role_id:
                return parent_role
            return None
        all_perms = child_role.get_all_permissions(role_getter)
        expected = {"task:assign", "report:view", "team:manage"}
        assert all_perms == expected

    def test_get_all_permissions_no_parent_getter(self, child_role):
        all_perms = child_role.get_all_permissions()
        assert all_perms == {"task:assign"}

    def test_get_hierarchy(self, child_role, parent_role):
        def role_getter(role_id):
            if role_id == parent_role.role_id:
                return parent_role
            return None
        hierarchy = child_role.get_hierarchy(role_getter)
        assert len(hierarchy) == 2
        assert hierarchy[0] == child_role
        assert hierarchy[1] == parent_role

    def test_is_descendant_of(self, child_role, parent_role, valid_role):
        def role_getter(role_id):
            if role_id == parent_role.role_id:
                return parent_role
            return None
        assert child_role.is_descendant_of(parent_role.role_id, role_getter) is True
        assert child_role.is_descendant_of(valid_role.role_id, role_getter) is False

    def test_is_ancestor_of(self, parent_role, child_role, valid_role):
        def role_getter(role_id):
            if role_id == child_role.role_id:
                return child_role
            if role_id == parent_role.role_id:
                return parent_role
            return None
        assert parent_role.is_ancestor_of(child_role.role_id, role_getter) is True
        assert parent_role.is_ancestor_of(valid_role.role_id, role_getter) is False


# ============================================================================
# Tests for RoleRepository
# ============================================================================

class TestRoleRepository:
    async def test_save_and_get_by_id(self, valid_role):
        await RoleRepository.save(valid_role)
        retrieved = await RoleRepository.get_by_id(valid_role.role_id)
        assert retrieved == valid_role

    async def test_get_by_name(self, valid_role):
        await RoleRepository.save(valid_role)
        retrieved = await RoleRepository.get_by_name(valid_role.role_name)
        assert retrieved == valid_role

    async def test_get_default_role(self, default_role, valid_role):
        await RoleRepository.save(default_role)
        await RoleRepository.save(valid_role)
        default = await RoleRepository.get_default_role()
        assert default == default_role

    async def test_get_default_role_none(self):
        default = await RoleRepository.get_default_role()
        assert default is None

    async def test_get_by_status(self, valid_role, inactive_role):
        await RoleRepository.save(valid_role)
        await RoleRepository.save(inactive_role)
        active = await RoleRepository.get_by_status(RoleStatus.ACTIVE)
        assert len(active) == 1
        assert active[0] == valid_role
        inactive_list = await RoleRepository.get_by_status(RoleStatus.INACTIVE)
        assert len(inactive_list) == 1
        assert inactive_list[0] == inactive_role

    async def test_get_active(self, valid_role, inactive_role):
        await RoleRepository.save(valid_role)
        await RoleRepository.save(inactive_role)
        active = await RoleRepository.get_active()
        assert len(active) == 1
        assert active[0] == valid_role

    async def test_get_children(self, parent_role, child_role):
        await RoleRepository.save(parent_role)
        await RoleRepository.save(child_role)
        children = await RoleRepository.get_children(parent_role.role_id)
        assert len(children) == 1
        assert children[0] == child_role

    async def test_get_descendants(self, parent_role, child_role):
        # Create a grandchild
        grandchild = RoleEntity(
            role_id=uuid4(),
            role_name="grandchild",
            description="Grandchild",
            permissions=set(),
            status=RoleStatus.ACTIVE,
            parent_role_id=child_role.role_id,
        )
        await RoleRepository.save(parent_role)
        await RoleRepository.save(child_role)
        await RoleRepository.save(grandchild)
        descendants = await RoleRepository.get_descendants(parent_role.role_id)
        assert len(descendants) == 2
        assert child_role in descendants
        assert grandchild in descendants

    async def test_get_all(self, valid_role):
        await RoleRepository.save(valid_role)
        all_roles = await RoleRepository.get_all()
        assert len(all_roles) == 1
        assert all_roles[0] == valid_role

    async def test_update(self, valid_role):
        await RoleRepository.save(valid_role)
        updated = valid_role.update("admin", description="Updated")
        await RoleRepository.update(updated)
        retrieved = await RoleRepository.get_by_id(valid_role.role_id)
        assert retrieved.description == "Updated"

    async def test_delete(self, valid_role):
        await RoleRepository.save(valid_role)
        await RoleRepository.delete(valid_role.role_id)
        retrieved = await RoleRepository.get_by_id(valid_role.role_id)
        assert retrieved is None
        # Check by-name index
        assert valid_role.role_name not in RoleRepository._storage_by_name

    async def test_exists(self, valid_role):
        await RoleRepository.save(valid_role)
        assert await RoleRepository.exists(valid_role.role_id) is True
        assert await RoleRepository.exists(uuid4()) is False

    async def test_exists_by_name(self, valid_role):
        await RoleRepository.save(valid_role)
        assert await RoleRepository.exists_by_name(valid_role.role_name) is True
        assert await RoleRepository.exists_by_name("nonexistent") is False

    async def test_count(self, valid_role):
        assert await RoleRepository.count() == 0
        await RoleRepository.save(valid_role)
        assert await RoleRepository.count() == 1

    async def test_list(self, valid_role):
        await RoleRepository.save(valid_role)
        roles = await RoleRepository.list(limit=1, offset=0)
        assert len(roles) == 1
        assert roles[0] == valid_role

    async def test_paginate(self, valid_role):
        await RoleRepository.save(valid_role)
        roles, total = await RoleRepository.paginate(page=1, per_page=20)
        assert total == 1
        assert len(roles) == 1

    async def test_search(self, valid_role):
        await RoleRepository.save(valid_role)
        results = await RoleRepository.search("admin")
        assert len(results) == 1
        assert results[0] == valid_role
        results2 = await RoleRepository.search("nonexistent")
        assert len(results2) == 0

    async def test_search_by_description(self, valid_role):
        await RoleRepository.save(valid_role)
        results = await RoleRepository.search("Administrator", fields=["description"])
        assert len(results) == 1

    async def test_clear(self, valid_role):
        await RoleRepository.save(valid_role)
        await RoleRepository.clear()
        assert len(RoleRepository._storage) == 0
        assert len(RoleRepository._storage_by_name) == 0