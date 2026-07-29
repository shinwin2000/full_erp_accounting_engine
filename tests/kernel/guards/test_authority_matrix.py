# tests/kernel/guards/test_authority_matrix.py
# Comprehensive tests for kernel/guards/authority_matrix.py

from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest

from kernel.guards.authority_matrix import (
    STANDARD_ROLES,
    Action,
    AuthorityMatrix,
    AuthorityMatrixGuard,
    BaseAuthorityMatrixGuard,
    Permission,
    PermissionEffect,
    PermissionScope,
    ResourceType,
    Role,
    _FallbackUserRepository,
    _get_user_repository,
    get_authority_matrix_guard,
)
from kernel.guards.guard_exceptions import AuthorityMatrixError

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def fixed_now():
    return datetime(2026, 7, 27, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mock_datetime(fixed_now):
    with patch("kernel.guards.authority_matrix.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.utcnow.return_value = fixed_now
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        yield mock_dt


@pytest.fixture
def user_repo():
    repo = _FallbackUserRepository()
    return repo


@pytest.fixture
def guard(user_repo):
    return AuthorityMatrixGuard(user_repo)


@pytest.fixture
def sample_permission():
    return Permission(
        resource=ResourceType.JOURNAL,
        action=Action.READ,
        scope=PermissionScope.LEGAL_ENTITY,
        effect=PermissionEffect.ALLOW,
        conditions=None,
    )


@pytest.fixture
def sample_role(sample_permission):
    return Role(
        name="test_role",
        permissions=[sample_permission],
        parent_role="maker",
        description="Test role",
        is_system_role=False,
    )


# ============================================================================
# Tests for _FallbackUserRepository
# ============================================================================

class TestFallbackUserRepository:
    def test_default_roles(self, user_repo):
        assert user_repo._user_roles["admin"] == ["admin"]
        assert user_repo._user_roles["maker"] == ["maker"]
        assert user_repo._user_roles["checker"] == ["checker", "maker"]
        assert user_repo._user_roles["auditor"] == ["auditor"]
        assert user_repo._user_roles["system"] == ["system"]

    @pytest.mark.asyncio
    async def test_get_roles_existing(self, user_repo):
        roles = await user_repo.get_roles("admin")
        assert roles == ["admin"]

    @pytest.mark.asyncio
    async def test_get_roles_non_existing(self, user_repo):
        roles = await user_repo.get_roles("unknown")
        assert roles == ["guest"]

    @pytest.mark.asyncio
    async def test_get_legal_entities(self, user_repo):
        # By default empty
        entities = await user_repo.get_legal_entities("admin")
        assert entities == []

    @pytest.mark.asyncio
    async def test_set_user_roles(self, user_repo):
        user_repo.set_user_roles("user1", ["maker", "checker"])
        roles = await user_repo.get_roles("user1")
        assert roles == ["maker", "checker"]

    @pytest.mark.asyncio
    async def test_get_legal_entities_after_set(self, user_repo):
        entity_id = uuid4()
        user_repo._user_entities["user1"] = [entity_id]
        entities = await user_repo.get_legal_entities("user1")
        assert entities == [entity_id]


# ============================================================================
# Tests for _get_user_repository
# ============================================================================

def test_get_user_repository():
    repo = _get_user_repository()
    assert isinstance(repo, _FallbackUserRepository)


# ============================================================================
# Tests for Enums (already present but we keep them)
# ============================================================================

class TestResourceType:
    def test_members(self):
        assert ResourceType.JOURNAL.value == "journal"
        assert ResourceType.ACCOUNT.value == "account"
        assert ResourceType.INVOICE.value == "invoice"


class TestAction:
    def test_members(self):
        assert Action.CREATE.value == "create"
        assert Action.READ.value == "read"
        assert Action.UPDATE.value == "update"


class TestPermissionScope:
    def test_members(self):
        assert PermissionScope.SELF.value == "self"
        assert PermissionScope.ENTITY.value == "entity"
        assert PermissionScope.ALL.value == "all"


class TestPermissionEffect:
    def test_members(self):
        assert PermissionEffect.ALLOW.value == "allow"
        assert PermissionEffect.DENY.value == "deny"


# ============================================================================
# Tests for Permission and Role
# ============================================================================

class TestPermission:
    def test_construction(self, sample_permission):
        assert sample_permission.resource == ResourceType.JOURNAL
        assert sample_permission.action == Action.READ
        assert sample_permission.scope == PermissionScope.LEGAL_ENTITY

    def test_to_dict(self, sample_permission):
        d = sample_permission.to_dict()
        assert d["resource"] == "journal"
        assert d["action"] == "read"
        assert d["scope"] == "legal_entity"
        assert d["effect"] == "allow"
        assert d["conditions"] is None


class TestRole:
    def test_construction(self, sample_role):
        assert sample_role.name == "test_role"
        assert sample_role.parent_role == "maker"
        assert len(sample_role.permissions) == 1

    def test_to_dict(self, sample_role):
        d = sample_role.to_dict()
        assert d["name"] == "test_role"
        assert d["parent_role"] == "maker"
        assert len(d["permissions"]) == 1
        assert d["is_system_role"] is False
        assert "created_at" in d


# ============================================================================
# Tests for BaseAuthorityMatrixGuard (abstract)
# ============================================================================

def test_base_class_abstract():
    with pytest.raises(TypeError):
        BaseAuthorityMatrixGuard()


# ============================================================================
# Tests for AuthorityMatrixGuard
# ============================================================================

class TestAuthorityMatrixGuard:
    def test_init(self, guard):
        assert isinstance(guard._user_repo, _FallbackUserRepository)
        assert len(guard._roles) > 0  # STANDARD_ROLES
        assert guard._version == 1
        assert guard._max_history == 10000
        assert guard._permission_cache == {}
        assert guard._authorization_history == []

    # ---- register_role ----
    def test_register_role(self, guard, sample_role):
        guard.register_role(sample_role)
        assert guard._roles["test_role"] is sample_role
        # Cache should be invalidated
        assert "test_role" not in guard._permission_cache
        # Audit trail
        assert guard._audit_trail[-1]["action"] == "REGISTER_ROLE"

    # ---- get_role ----
    def test_get_role_found(self, guard):
        role = guard.get_role("maker")
        assert role is not None
        assert role.name == "maker"

    def test_get_role_not_found(self, guard):
        assert guard.get_role("nonexistent") is None

    # ---- get_all_roles ----
    def test_get_all_roles(self, guard):
        roles = guard.get_all_roles()
        assert len(roles) == len(STANDARD_ROLES)
        names = {r.name for r in roles}
        assert names == set(STANDARD_ROLES.keys())

    # ---- _get_all_permissions_for_role ----
    def test_get_all_permissions_for_role_with_cache(self, guard):
        # First call populates cache
        perms = guard._get_all_permissions_for_role("maker")
        assert len(perms) > 0
        # Cache should contain it
        assert "maker" in guard._permission_cache
        # Second call should use cache
        perms2 = guard._get_all_permissions_for_role("maker")
        assert perms is perms2  # same set object from cache

    def test_get_all_permissions_for_role_inherits_parent(self, guard):
        perms = guard._get_all_permissions_for_role("checker")
        # checker inherits from maker
        maker_perms = guard._get_all_permissions_for_role("maker")
        # checker should have maker permissions plus its own
        assert len(perms) > len(maker_perms)
        # Check that maker permissions are included
        for p in maker_perms:
            assert p in perms

    def test_get_all_permissions_for_role_non_existent(self, guard):
        perms = guard._get_all_permissions_for_role("nonexistent")
        assert perms == set()

    # ---- has_permission ----
    @pytest.mark.asyncio
    async def test_has_permission_granted(self, guard):
        # Maker has CREATE on JOURNAL with LEGAL_ENTITY scope
        user_id = "maker"
        result = await guard.has_permission(
            user_id, ResourceType.JOURNAL, Action.CREATE, None, {}
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_has_permission_denied(self, guard):
        # Maker does not have DELETE on JOURNAL
        user_id = "maker"
        result = await guard.has_permission(
            user_id, ResourceType.JOURNAL, Action.DELETE, None, {}
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_has_permission_scope_self(self, guard, monkeypatch):
        # Create a role with SELF scope
        perm = Permission(ResourceType.REPORT, Action.READ, PermissionScope.SELF)
        role = Role(name="self_role", permissions=[perm])
        guard.register_role(role)
        # Set current legal entity
        entity_id = uuid4()
        monkeypatch.setattr("kernel.guards.authority_matrix.get_current_legal_entity", lambda: entity_id)
        # Target entity same as current -> allowed
        result = await guard.has_permission(
            "self_role", ResourceType.REPORT, Action.READ, target_entity_id=entity_id, context={}
        )
        assert result is True
        # Target entity different -> denied
        result2 = await guard.has_permission(
            "self_role", ResourceType.REPORT, Action.READ, target_entity_id=uuid4(), context={}
        )
        assert result2 is False

    @pytest.mark.asyncio
    async def test_has_permission_scope_legal_entity(self, guard, monkeypatch):
        perm = Permission(ResourceType.JOURNAL, Action.CREATE, PermissionScope.LEGAL_ENTITY)
        role = Role(name="le_role", permissions=[perm])
        guard.register_role(role)
        # No current legal entity -> denied
        monkeypatch.setattr("kernel.guards.authority_matrix.get_current_legal_entity", lambda: None)
        result = await guard.has_permission(
            "le_role", ResourceType.JOURNAL, Action.CREATE, None, {}
        )
        assert result is False
        # With current legal entity -> allowed
        monkeypatch.setattr("kernel.guards.authority_matrix.get_current_legal_entity", lambda: uuid4())
        result2 = await guard.has_permission(
            "le_role", ResourceType.JOURNAL, Action.CREATE, None, {}
        )
        assert result2 is True

    @pytest.mark.asyncio
    async def test_has_permission_conditions_success(self, guard):
        perm = Permission(
            ResourceType.JOURNAL,
            Action.CREATE,
            PermissionScope.LEGAL_ENTITY,
            conditions={"amount": {"operator": "lte", "value": 1000}}
        )
        role = Role(name="cond_role", permissions=[perm])
        guard.register_role(role)
        result = await guard.has_permission(
            "cond_role", ResourceType.JOURNAL, Action.CREATE, None, {"amount": 500}
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_has_permission_conditions_fail(self, guard):
        perm = Permission(
            ResourceType.JOURNAL,
            Action.CREATE,
            PermissionScope.LEGAL_ENTITY,
            conditions={"amount": {"operator": "lte", "value": 1000}}
        )
        role = Role(name="cond_role", permissions=[perm])
        guard.register_role(role)
        result = await guard.has_permission(
            "cond_role", ResourceType.JOURNAL, Action.CREATE, None, {"amount": 2000}
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_has_permission_conditions_missing_key(self, guard):
        perm = Permission(
            ResourceType.JOURNAL,
            Action.CREATE,
            PermissionScope.LEGAL_ENTITY,
            conditions={"amount": {"operator": "lte", "value": 1000}}
        )
        role = Role(name="cond_role", permissions=[perm])
        guard.register_role(role)
        result = await guard.has_permission(
            "cond_role", ResourceType.JOURNAL, Action.CREATE, None, {}
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_has_permission_conditions_eq(self, guard):
        perm = Permission(
            ResourceType.JOURNAL,
            Action.CREATE,
            PermissionScope.LEGAL_ENTITY,
            conditions={"status": {"operator": "eq", "value": "draft"}}
        )
        role = Role(name="eq_role", permissions=[perm])
        guard.register_role(role)
        result = await guard.has_permission(
            "eq_role", ResourceType.JOURNAL, Action.CREATE, None, {"status": "draft"}
        )
        assert result is True
        result2 = await guard.has_permission(
            "eq_role", ResourceType.JOURNAL, Action.CREATE, None, {"status": "approved"}
        )
        assert result2 is False

    @pytest.mark.asyncio
    async def test_has_permission_conditions_in(self, guard):
        perm = Permission(
            ResourceType.JOURNAL,
            Action.CREATE,
            PermissionScope.LEGAL_ENTITY,
            conditions={"type": {"operator": "in", "value": ["sales", "purchase"]}}
        )
        role = Role(name="in_role", permissions=[perm])
        guard.register_role(role)
        result = await guard.has_permission(
            "in_role", ResourceType.JOURNAL, Action.CREATE, None, {"type": "sales"}
        )
        assert result is True
        result2 = await guard.has_permission(
            "in_role", ResourceType.JOURNAL, Action.CREATE, None, {"type": "adjustment"}
        )
        assert result2 is False

    # ---- enforce ----
    @pytest.mark.asyncio
    async def test_enforce_granted(self, guard):
        result = await guard.enforce(
            ResourceType.JOURNAL, Action.CREATE, user_id="maker", raise_on_violation=True
        )
        assert result is True
        # Check authorization history
        history = guard.get_authorization_history(limit=1)
        assert len(history) == 1
        assert history[0]["granted"] is True
        assert history[0]["resource"] == "journal"
        assert history[0]["user_id"] == "maker"

    @pytest.mark.asyncio
    async def test_enforce_denied_raises(self, guard):
        with pytest.raises(AuthorityMatrixError, match="does not have delete permission"):
            await guard.enforce(
                ResourceType.JOURNAL, Action.DELETE, user_id="maker", raise_on_violation=True
            )
        # Check history
        history = guard.get_authorization_history(limit=1)
        assert len(history) == 1
        assert history[0]["granted"] is False

    @pytest.mark.asyncio
    async def test_enforce_no_user_falls_back_to_guest(self, guard):
        # No user_id provided, should default to guest
        result = await guard.enforce(
            ResourceType.REPORT, Action.READ, user_id=None, raise_on_violation=False
        )
        # Guest has READ on REPORT with SELF scope, so if no target entity, should be denied? Actually guest has REPORT:READ with SELF scope; without target entity, it's not allowed because self scope requires target_entity_id == current_entity, but if current_entity is None, it fails.
        # So result should be False.
        assert result is False

    @pytest.mark.asyncio
    async def test_enforce_with_target_entity(self, guard, monkeypatch):
        # Guest has REPORT:READ with SELF scope
        # Set current entity to match target
        entity_id = uuid4()
        monkeypatch.setattr("kernel.guards.authority_matrix.get_current_legal_entity", lambda: entity_id)
        result = await guard.enforce(
            ResourceType.REPORT, Action.READ, user_id="guest", target_entity_id=entity_id, raise_on_violation=False
        )
        assert result is True

    # ---- get_user_permissions ----
    @pytest.mark.asyncio
    async def test_get_user_permissions(self, guard):
        perms = await guard.get_user_permissions("maker")
        assert len(perms) > 0
        # Should include permissions from maker role
        expected_resources = {"journal", "invoice", "payment", "customer", "supplier", "employee"}
        for p in perms:
            if p["resource"] in expected_resources:
                assert p["action"] == "create" or p["action"] == "read"
        # Filter by resource
        journal_perms = await guard.get_user_permissions("maker", ResourceType.JOURNAL)
        for p in journal_perms:
            assert p["resource"] == "journal"

    @pytest.mark.asyncio
    async def test_get_user_permissions_fallback_guest(self, guard):
        # Non-existent user -> guest
        perms = await guard.get_user_permissions("unknown")
        assert len(perms) == 1
        assert perms[0]["resource"] == "report"
        assert perms[0]["action"] == "read"

    # ---- get_authorization_history ----
    def test_get_authorization_history(self, guard):
        # Add some history entries manually
        guard._authorization_history = [
            {"user_id": "user1", "resource": "journal", "action": "read", "granted": True},
            {"user_id": "user2", "resource": "invoice", "action": "approve", "granted": False},
            {"user_id": "user1", "resource": "payment", "action": "create", "granted": True},
        ]
        # Get all
        history = guard.get_authorization_history(limit=10)
        assert len(history) == 3
        # Filter by user
        user1_history = guard.get_authorization_history(user_id="user1")
        assert len(user1_history) == 2
        # Only denied
        denied = guard.get_authorization_history(only_denied=True)
        assert len(denied) == 1
        assert denied[0]["granted"] is False
        # Limit
        limited = guard.get_authorization_history(limit=2)
        assert len(limited) == 2

    # ---- get_statistics ----
    def test_get_statistics_empty(self, guard):
        stats = guard.get_statistics()
        assert stats["total_authorizations"] == 0
        assert stats["version"] == 1

    def test_get_statistics_with_data(self, guard):
        guard._authorization_history = [
            {"resource": "journal", "granted": True},
            {"resource": "journal", "granted": True},
            {"resource": "invoice", "granted": False},
        ]
        stats = guard.get_statistics()
        assert stats["total_authorizations"] == 3
        assert stats["granted_count"] == 2
        assert stats["denied_count"] == 1
        assert stats["grant_rate"] == 2 / 3
        assert stats["by_resource"]["journal"] == 2
        assert stats["by_resource"]["invoice"] == 1
        assert stats["registered_roles"] == len(STANDARD_ROLES)

    # ---- invalidate_cache ----
    def test_invalidate_cache(self, guard):
        # Populate cache
        guard._get_all_permissions_for_role("maker")
        assert "maker" in guard._permission_cache
        # Invalidate specific role
        guard.invalidate_cache("maker")
        assert "maker" not in guard._permission_cache
        # Populate again and invalidate all
        guard._get_all_permissions_for_role("maker")
        guard._get_all_permissions_for_role("checker")
        assert len(guard._permission_cache) > 0
        guard.invalidate_cache()
        assert len(guard._permission_cache) == 0

    # ---- reset ----
    def test_reset(self, guard):
        # Modify state
        guard._version = 5
        guard._authorization_history = [{"test": "data"}]
        guard._permission_cache["maker"] = set()
        guard.reset()
        assert guard._version == 6  # incremented
        assert guard._authorization_history == []
        assert guard._permission_cache == {}
        assert guard._roles == STANDARD_ROLES.copy()
        assert guard._audit_trail == []

    # ---- check method ----
    def test_check_valid(self, guard):
        context = {
            "user_id": "maker",
            "resource": "journal",
            "action": "create",
        }
        errors = guard.check(context)
        assert errors == []

    def test_check_missing_fields(self, guard):
        errors = guard.check({})
        assert "user_id is required" in errors
        assert "resource is required" in errors
        assert "action is required" in errors

    def test_check_invalid_resource(self, guard):
        context = {
            "user_id": "maker",
            "resource": "invalid",
            "action": "create",
        }
        errors = guard.check(context)
        assert any("Invalid resource type" in e for e in errors)

    def test_check_invalid_action(self, guard):
        context = {
            "user_id": "maker",
            "resource": "journal",
            "action": "invalid",
        }
        errors = guard.check(context)
        assert any("Invalid action" in e for e in errors)

    # ---- validate ----
    def test_validate_valid(self, guard):
        result = guard.validate()
        assert result["is_valid"] is True

    def test_validate_invalid_max_history(self, guard):
        guard._max_history = -1
        result = guard.validate()
        assert result["is_valid"] is False
        assert "max_history must be positive" in result["errors"]

    def test_validate_no_roles(self, guard):
        guard._roles = {}
        result = guard.validate()
        assert result["is_valid"] is False
        assert "No roles registered" in result["errors"]

    # ---- to_dict ----
    def test_to_dict(self, guard):
        d = guard.to_dict()
        assert d["roles_count"] == len(STANDARD_ROLES)
        assert "roles" in d
        assert d["max_history"] == 10000
        assert d["version"] == 1

    # ---- from_dict ----
    def test_from_dict(self):
        data = {
            "max_history": 5000,
            "version": 3,
        }
        instance = AuthorityMatrixGuard.from_dict(data)
        assert instance._max_history == 5000
        assert instance._version == 3

    # ---- clone ----
    def test_clone(self, guard):
        cloned = guard.clone()
        assert cloned is not guard
        assert cloned._max_history == guard._max_history
        assert cloned._version == guard._version + 1

    # ---- snapshot ----
    def test_snapshot(self, guard):
        snap = guard.snapshot()
        assert snap["version"] == 1
        assert snap["roles_count"] == len(STANDARD_ROLES)
        assert snap["cache_size"] == 0
        assert snap["history_size"] == 0
        assert "timestamp" in snap

    # ---- version ----
    def test_version(self, guard):
        assert guard.version() == 1
        guard._version = 10
        assert guard.version() == 10

    # ---- audit_trail ----
    def test_audit_trail(self, guard):
        guard._record_audit("ACTION1", "user", {"k": "v"})
        guard._record_audit("ACTION2", "user", {"k2": "v2"})
        trail = guard.audit_trail(limit=1)
        assert len(trail) == 1
        assert trail[0]["action"] == "ACTION2"
        trail_all = guard.audit_trail(limit=10)
        assert len(trail_all) == 2

    # ---- touch ----
    def test_touch(self, guard):
        old_ver = guard._version
        guard.touch("admin")
        assert guard._version == old_ver + 1
        assert guard._audit_trail[-1]["action"] == "TOUCH"

    # ---- _record_audit ----
    def test_record_audit(self, guard):
        guard._record_audit("TEST", "user", {"detail": "value"})
        assert len(guard._audit_trail) == 1
        assert guard._audit_trail[0]["action"] == "TEST"
        assert guard._audit_trail[0]["performed_by"] == "user"

    # ---- _record_authorization ----
    def test_record_authorization(self, guard):
        guard._record_authorization(
            user_id="user1",
            resource=ResourceType.JOURNAL,
            action=Action.READ,
            target_entity_id=uuid4(),
            context={"key": "value"},
            granted=True,
        )
        assert len(guard._authorization_history) == 1
        record = guard._authorization_history[0]
        assert record["user_id"] == "user1"
        assert record["resource"] == "journal"
        assert record["granted"] is True
        assert "target_entity_id" in record
        assert "context" in record


# ============================================================================
# Tests for AuthorityMatrix (simple wrapper)
# ============================================================================

class TestAuthorityMatrix:
    def test_init(self):
        matrix = AuthorityMatrix()
        assert isinstance(matrix._guard, AuthorityMatrixGuard)

    def test_has_permission_valid(self):
        matrix = AuthorityMatrix()
        # maker has CREATE on JOURNAL
        assert matrix.has_permission("maker", "journal:create") is True
        # maker does not have DELETE on JOURNAL
        assert matrix.has_permission("maker", "journal:delete") is False
        # invalid format
        assert matrix.has_permission("maker", "invalid") is False
        # invalid resource
        assert matrix.has_permission("maker", "invalid:read") is False
        # invalid action
        assert matrix.has_permission("maker", "journal:invalid") is False
        # role doesn't exist
        assert matrix.has_permission("nonexistent", "journal:read") is False
        # parent role inheritance: checker has READ on JOURNAL (inherited from maker)
        assert matrix.has_permission("checker", "journal:read") is True

    def test_get_permissions_for_role(self):
        matrix = AuthorityMatrix()
        perms = matrix.get_permissions_for_role("maker")
        assert len(perms) > 0
        assert "journal:create" in perms
        assert "journal:read" in perms
        # Non-existent role
        assert matrix.get_permissions_for_role("nonexistent") == []

    def test_add_permission_to_role_existing(self):
        matrix = AuthorityMatrix()
        # Existing role
        matrix.add_permission_to_role("maker", "system_config:update")
        # Check that permission was added to STANDARD_ROLES
        role = STANDARD_ROLES["maker"]
        found = False
        for perm in role.permissions:
            if perm.resource == ResourceType.SYSTEM_CONFIG and perm.action == Action.UPDATE:
                found = True
                break
        assert found is True

    def test_add_permission_to_role_new(self):
        matrix = AuthorityMatrix()
        matrix.add_permission_to_role("new_role", "report:export")
        assert "new_role" in STANDARD_ROLES
        role = STANDARD_ROLES["new_role"]
        assert len(role.permissions) == 1
        assert role.permissions[0].resource == ResourceType.REPORT
        assert role.permissions[0].action == Action.EXPORT

    def test_add_permission_to_role_invalid_format(self):
        matrix = AuthorityMatrix()
        # Should not add if invalid format
        matrix.add_permission_to_role("maker", "invalid")
        # Check no change
        role = STANDARD_ROLES["maker"]
        original_count = len(role.permissions)
        matrix.add_permission_to_role("maker", "invalid_format:without_colon")
        assert len(role.permissions) == original_count


# ============================================================================
# Tests for Singleton Accessor
# ============================================================================

def test_get_authority_matrix_guard():
    g1 = get_authority_matrix_guard()
    g2 = get_authority_matrix_guard()
    assert g1 is g2
    assert isinstance(g1, AuthorityMatrixGuard)


# ============================================================================
# Integration test for has_permission with real user repository
# ============================================================================

@pytest.mark.asyncio
async def test_integration_has_permission_with_repo():
    guard = AuthorityMatrixGuard()
    # admin has all permissions
    assert await guard.has_permission("admin", ResourceType.USER, Action.CREATE) is True
    assert await guard.has_permission("admin", ResourceType.SYSTEM_CONFIG, Action.UPDATE) is True
    # auditor has read-only
    assert await guard.has_permission("auditor", ResourceType.JOURNAL, Action.READ) is True
    assert await guard.has_permission("auditor", ResourceType.JOURNAL, Action.CREATE) is False


# ============================================================================
# Edge cases for check_conditions
# ============================================================================

class TestCheckConditions:
    def test_check_conditions_empty(self, guard):
        assert guard._check_conditions({}, {}) is True
        assert guard._check_conditions({"key": "value"}, {}) is False  # missing key

    def test_check_conditions_simple(self, guard):
        assert guard._check_conditions({"status": "draft"}, {"status": "draft"}) is True
        assert guard._check_conditions({"status": "draft"}, {"status": "approved"}) is False

    def test_check_conditions_operator_lte(self, guard):
        conditions = {"amount": {"operator": "lte", "value": 100}}
        assert guard._check_conditions(conditions, {"amount": 50}) is True
        assert guard._check_conditions(conditions, {"amount": 100}) is True
        assert guard._check_conditions(conditions, {"amount": 150}) is False

    def test_check_conditions_operator_gte(self, guard):
        conditions = {"amount": {"operator": "gte", "value": 100}}
        assert guard._check_conditions(conditions, {"amount": 150}) is True
        assert guard._check_conditions(conditions, {"amount": 100}) is True
        assert guard._check_conditions(conditions, {"amount": 50}) is False

    def test_check_conditions_operator_in(self, guard):
        conditions = {"type": {"operator": "in", "value": ["A", "B"]}}
        assert guard._check_conditions(conditions, {"type": "A"}) is True
        assert guard._check_conditions(conditions, {"type": "B"}) is True
        assert guard._check_conditions(conditions, {"type": "C"}) is False

    def test_check_conditions_unknown_operator(self, guard):
        conditions = {"amount": {"operator": "unknown", "value": 100}}
        assert guard._check_conditions(conditions, {"amount": 50}) is False

    def test_check_conditions_nested_dict_value(self, guard):
        conditions = {"user": {"operator": "eq", "value": "admin"}}
        assert guard._check_conditions(conditions, {"user": "admin"}) is True
        assert guard._check_conditions(conditions, {"user": "guest"}) is False
