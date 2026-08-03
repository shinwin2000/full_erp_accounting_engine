# tests/kernel/guards/test_legal_entity_boundary.py
"""
Comprehensive unit tests for kernel/guards/legal_entity_boundary.py.
Covers all classes, methods, edge cases, and singleton behavior.
Uses mocking to isolate dependencies and ensure security checks work correctly.
"""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from kernel.guards.guard_exceptions import LegalEntityBoundaryError
from kernel.guards.legal_entity_boundary import (
    BaseLegalEntityBoundaryGuard,
    EntityAccessCheckResult,
    EntityAccessSeverity,
    LegalEntityBoundaryGuard,
    _FallbackUserRepository,
    get_legal_entity_boundary_guard,
)

# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def fallback_repo():
    """Create a fresh _FallbackUserRepository for each test."""
    return _FallbackUserRepository()


@pytest.fixture
def guard(fallback_repo):
    """Create a LegalEntityBoundaryGuard with a fallback repository."""
    return LegalEntityBoundaryGuard(user_repository=fallback_repo)


@pytest.fixture
def mock_user_repo():
    """Create a mock repository that implements the required methods."""
    repo = AsyncMock()
    repo.get_legal_entities = AsyncMock(return_value=[])
    repo.get_roles = AsyncMock(return_value=[])
    repo.has_cross_entity_access = AsyncMock(return_value=False)
    repo.get_user_details = AsyncMock(return_value=None)
    repo.get_entity_owner = AsyncMock(return_value=None)
    repo.get_all_entities = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def guard_with_mock_repo(mock_user_repo):
    """Create a guard with a mock repository."""
    return LegalEntityBoundaryGuard(user_repository=mock_user_repo)


# ============================================================================
# TESTS FOR _FALLBACKUSERREPOSITORY
# ============================================================================

class TestFallbackUserRepository:
    def test_initial_state(self, fallback_repo):
        assert fallback_repo._user_entities == {}
        assert fallback_repo._user_roles == {}
        assert fallback_repo._cross_entity_auths == {}
        assert fallback_repo._user_details == {}
        assert fallback_repo._entity_owners == {}

    def test_add_user_entity(self, fallback_repo):
        user_id = "user1"
        entity_id = uuid4()
        fallback_repo.add_user_entity(user_id, entity_id)
        assert user_id in fallback_repo._user_entities
        assert entity_id in fallback_repo._user_entities[user_id]

    def test_add_user_entity_multiple(self, fallback_repo):
        user_id = "user1"
        e1 = uuid4()
        e2 = uuid4()
        fallback_repo.add_user_entity(user_id, e1)
        fallback_repo.add_user_entity(user_id, e2)
        assert len(fallback_repo._user_entities[user_id]) == 2

    def test_get_legal_entities(self, fallback_repo):
        user_id = "user1"
        e1 = uuid4()
        e2 = uuid4()
        fallback_repo.add_user_entity(user_id, e1)
        fallback_repo.add_user_entity(user_id, e2)
        entities = asyncio.run(fallback_repo.get_legal_entities(user_id))
        assert set(entities) == {e1, e2}
        # Unknown user returns empty list
        entities2 = asyncio.run(fallback_repo.get_legal_entities("unknown"))
        assert entities2 == []

    def test_set_user_roles(self, fallback_repo):
        user_id = "user1"
        roles = ["admin", "finance"]
        fallback_repo.set_user_roles(user_id, roles)
        assert fallback_repo._user_roles[user_id] == roles
        # Overwrite
        new_roles = ["viewer"]
        fallback_repo.set_user_roles(user_id, new_roles)
        assert fallback_repo._user_roles[user_id] == new_roles

    def test_get_roles(self, fallback_repo):
        user_id = "user1"
        roles = ["admin"]
        fallback_repo.set_user_roles(user_id, roles)
        result = asyncio.run(fallback_repo.get_roles(user_id))
        assert result == roles
        # Unknown user returns empty list
        result2 = asyncio.run(fallback_repo.get_roles("unknown"))
        assert result2 == []

    def test_add_cross_entity_auth(self, fallback_repo):
        user_id = "user1"
        from_entity = uuid4()
        to_entity = uuid4()
        fallback_repo.add_cross_entity_auth(user_id, from_entity, to_entity)
        key = (user_id, from_entity, to_entity)
        assert key in fallback_repo._cross_entity_auths
        assert fallback_repo._cross_entity_auths[key] is True

    def test_has_cross_entity_access_true(self, fallback_repo):
        user_id = "user1"
        from_entity = uuid4()
        to_entity = uuid4()
        fallback_repo.add_cross_entity_auth(user_id, from_entity, to_entity)
        result = asyncio.run(fallback_repo.has_cross_entity_access(
            user_id, from_entity, to_entity, "TRANSFER"
        ))
        assert result is True

    def test_has_cross_entity_access_false_no_auth(self, fallback_repo):
        user_id = "user1"
        from_entity = uuid4()
        to_entity = uuid4()
        result = asyncio.run(fallback_repo.has_cross_entity_access(
            user_id, from_entity, to_entity, "TRANSFER"
        ))
        assert result is False

    def test_has_cross_entity_access_owner_both(self, fallback_repo):
        user_id = "user1"
        from_entity = uuid4()
        to_entity = uuid4()
        fallback_repo.set_entity_owner(from_entity, user_id)
        fallback_repo.set_entity_owner(to_entity, user_id)
        result = asyncio.run(fallback_repo.has_cross_entity_access(
            user_id, from_entity, to_entity, "TRANSFER"
        ))
        assert result is True

    def test_has_cross_entity_access_owner_only_one(self, fallback_repo):
        user_id = "user1"
        from_entity = uuid4()
        to_entity = uuid4()
        fallback_repo.set_entity_owner(from_entity, user_id)
        # to_entity not owned by same user
        result = asyncio.run(fallback_repo.has_cross_entity_access(
            user_id, from_entity, to_entity, "TRANSFER"
        ))
        assert result is False

    def test_set_entity_owner(self, fallback_repo):
        entity_id = uuid4()
        owner = "user1"
        fallback_repo.set_entity_owner(entity_id, owner)
        assert fallback_repo._entity_owners[entity_id] == owner
        # Overwrite
        new_owner = "user2"
        fallback_repo.set_entity_owner(entity_id, new_owner)
        assert fallback_repo._entity_owners[entity_id] == new_owner

    def test_get_entity_owner(self, fallback_repo):
        entity_id = uuid4()
        owner = "user1"
        fallback_repo.set_entity_owner(entity_id, owner)
        result = asyncio.run(fallback_repo.get_entity_owner(entity_id))
        assert result == owner
        result2 = asyncio.run(fallback_repo.get_entity_owner(uuid4()))
        assert result2 is None

    def test_add_user_details(self, fallback_repo):
        user_id = "user1"
        name = "Alice"
        email = "alice@example.com"
        dept = "Finance"
        with patch("kernel.guards.legal_entity_boundary.datetime") as mock_dt:
            fixed_now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
            mock_dt.now.return_value = fixed_now
            fallback_repo.add_user_details(user_id, name, email, dept)
        details = fallback_repo._user_details[user_id]
        assert details["user_id"] == user_id
        assert details["name"] == name
        assert details["email"] == email
        assert details["department"] == dept
        assert details["created_at"] == fixed_now

    def test_get_user_details(self, fallback_repo):
        user_id = "user1"
        fallback_repo.add_user_details(user_id, "Alice")
        result = asyncio.run(fallback_repo.get_user_details(user_id))
        assert result["name"] == "Alice"
        result2 = asyncio.run(fallback_repo.get_user_details("unknown"))
        assert result2 is None

    def test_get_all_entities(self, fallback_repo):
        e1 = uuid4()
        e2 = uuid4()
        fallback_repo.set_entity_owner(e1, "user1")
        fallback_repo.set_entity_owner(e2, "user2")
        entities = asyncio.run(fallback_repo.get_all_entities())
        assert set(entities) == {e1, e2}


# ============================================================================
# TESTS FOR ENTITYACCESSCHECKRESULT
# ============================================================================

class TestEntityAccessCheckResult:
    def test_construction(self):
        check_id = uuid4()
        user_id = "user1"
        target = uuid4()
        result = EntityAccessCheckResult(
            check_id=check_id,
            user_id=user_id,
            source_entity_id=None,
            target_entity_id=target,
            operation="READ",
            is_allowed=True,
            severity=EntityAccessSeverity.INFO,
            message="OK",
        )
        assert result.check_id == check_id
        assert result.cryptographic_hash != ""
        assert result.compute_hash() == result.cryptographic_hash

    def test_hash_mismatch_raises(self):
        with pytest.raises(ValueError, match="Cryptographic hash mismatch"):
            EntityAccessCheckResult(
                check_id=uuid4(),
                user_id="u",
                source_entity_id=None,
                target_entity_id=uuid4(),
                operation="READ",
                is_allowed=True,
                severity=EntityAccessSeverity.INFO,
                message="OK",
                cryptographic_hash="invalidhash",
            )

    def test_to_dict(self):
        check_id = uuid4()
        user_id = "user1"
        target = uuid4()
        result = EntityAccessCheckResult(
            check_id=check_id,
            user_id=user_id,
            source_entity_id=None,
            target_entity_id=target,
            operation="READ",
            is_allowed=True,
            severity=EntityAccessSeverity.INFO,
            message="OK",
            authorized_entities=[uuid4(), uuid4()],
        )
        d = result.to_dict()
        assert d["check_id"] == str(check_id)
        assert d["user_id"] == user_id
        assert d["target_entity_id"] == str(target)
        assert d["operation"] == "READ"
        assert d["is_allowed"] is True
        assert d["severity"] == "INFO"
        assert d["hash"] is not None
        assert len(d["authorized_entities"]) == 2


# ============================================================================
# TESTS FOR LEGALENTITYBOUNDARYGUARD (BASE AND CONCRETE)
# ============================================================================

class TestLegalEntityBoundaryGuardBase:
    def test_abstract_methods_exist(self):
        """BaseLegalEntityBoundaryGuard defines all abstract methods."""
        methods = [
            "enable", "set_strict_mode", "set_allowed_cross_entity_operations",
            "clear_cache", "check_entity_access", "check_multi_entity_access",
            "enforce_current_entity", "enforce_cross_entity_transfer",
            "enforce_consolidation", "get_check_history", "get_statistics",
            "reset", "check", "validate", "to_dict", "from_dict",
            "clone", "snapshot", "version", "audit_trail", "touch"
        ]
        for m in methods:
            assert hasattr(BaseLegalEntityBoundaryGuard, m)


class TestLegalEntityBoundaryGuard:
    # ---- INITIALIZATION AND STATE ----
    def test_initial_state(self, guard):
        assert guard._enabled is True
        assert guard._strict_mode is True
        assert guard._allowed_cross_entity_operations == {"READ", "REPORT", "AUDIT"}
        assert guard._max_history == 10000
        assert guard._cache_ttl_seconds == 300
        assert guard._version == 1

    def test_enable_disable(self, guard):
        guard.enable(False)
        assert guard._enabled is False
        guard.enable(True)
        assert guard._enabled is True

    def test_set_strict_mode(self, guard):
        guard.set_strict_mode(False)
        assert guard._strict_mode is False
        guard.set_strict_mode(True)
        assert guard._strict_mode is True

    # ---- Explicit test for set_allowed_cross_entity_operations ----
    def test_set_allowed_cross_entity_operations(self, guard):
        ops = ["READ", "WRITE", "DELETE"]
        guard.set_allowed_cross_entity_operations(ops)
        assert guard._allowed_cross_entity_operations == set(ops)
        # Test with empty list
        guard.set_allowed_cross_entity_operations([])
        assert guard._allowed_cross_entity_operations == set()

    def test_clear_cache(self, guard):
        guard._cache["some_key"] = (MagicMock(), datetime.now(UTC))
        assert len(guard._cache) == 1
        guard.clear_cache()
        assert len(guard._cache) == 0

    # ---- CHECK METHOD ----
    def test_check_valid_context(self, guard):
        context = {
            "target_entity_id": str(uuid4()),
            "user_id": "user1",
            "operation": "READ"
        }
        errors = guard.check(context)
        assert errors == []

    def test_check_missing_target(self, guard):
        context = {"user_id": "user1"}
        errors = guard.check(context)
        assert "target_entity_id is required" in errors

    def test_check_invalid_target_uuid(self, guard):
        context = {"target_entity_id": "not-a-uuid"}
        errors = guard.check(context)
        assert "target_entity_id must be a valid UUID" in errors

    def test_check_invalid_operation(self, guard):
        context = {"target_entity_id": str(uuid4()), "operation": "INVALID"}
        errors = guard.check(context)
        assert "operation 'INVALID' is not a valid EntityAccessOperation" in errors

    # ---- VALIDATE ----
    def test_validate_ok(self, guard):
        result = guard.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_invalid_max_history(self, guard):
        guard._max_history = -1
        result = guard.validate()
        assert result["is_valid"] is False
        assert "max_history must be positive" in result["errors"]

    def test_validate_invalid_cache_ttl(self, guard):
        guard._cache_ttl_seconds = -10
        result = guard.validate()
        assert result["is_valid"] is False
        assert "cache_ttl_seconds must be positive" in result["errors"]

    # ---- TO_DICT / FROM_DICT / CLONE ----
    def test_to_dict(self, guard):
        d = guard.to_dict()
        assert d["enabled"] is True
        assert d["strict_mode"] is True
        assert d["allowed_cross_entity_operations"] == ["READ", "REPORT", "AUDIT"]
        assert "history_count" in d
        assert "cache_size" in d
        assert "version" in d

    def test_from_dict(self):
        data = {
            "enabled": False,
            "strict_mode": False,
            "max_history": 5000,
            "cache_ttl_seconds": 120,
            "version": 3,
            "allowed_cross_entity_operations": ["READ", "WRITE"]
        }
        guard = LegalEntityBoundaryGuard.from_dict(data)
        assert guard._enabled is False
        assert guard._strict_mode is False
        assert guard._max_history == 5000
        assert guard._cache_ttl_seconds == 120
        assert guard._version == 3
        assert guard._allowed_cross_entity_operations == {"READ", "WRITE"}

    def test_clone(self, guard):
        clone = guard.clone()
        assert clone is not guard
        assert clone._enabled == guard._enabled
        assert clone._strict_mode == guard._strict_mode
        assert clone._max_history == guard._max_history
        assert clone._cache_ttl_seconds == guard._cache_ttl_seconds
        assert clone._allowed_cross_entity_operations == guard._allowed_cross_entity_operations
        assert clone._version == guard._version + 1

    # ---- SNAPSHOT / VERSION / AUDIT_TRAIL / TOUCH ----
    def test_snapshot(self, guard):
        snap = guard.snapshot()
        assert snap["version"] == guard._version
        assert "history_count" in snap
        assert "cache_size" in snap
        assert "enabled" in snap
        assert "timestamp" in snap

    def test_version(self, guard):
        assert guard.version() == 1
        guard._version = 5
        assert guard.version() == 5

    def test_audit_trail(self, guard):
        guard._record_audit("TEST", "user1", {"detail": "a"})
        guard._record_audit("TEST2", "user2", {"detail": "b"})
        trail = guard.audit_trail()
        assert len(trail) == 2
        assert trail[0]["action"] == "TEST"
        assert trail[1]["action"] == "TEST2"

    def test_touch(self, guard):
        old_version = guard.version()
        result = guard.touch("admin")
        assert result is guard
        assert guard.version() == old_version + 1
        trail = guard.audit_trail()
        assert any(e["action"] == "TOUCH" for e in trail)

    # ---- CHECK_ENTITY_ACCESS ----
    @pytest.mark.asyncio
    async def test_check_entity_access_disabled(self, guard):
        guard.enable(False)
        result = await guard.check_entity_access(uuid4(), "user1")
        assert result.is_allowed is True
        assert result.message == "Legal entity boundary guard is disabled"

    @pytest.mark.asyncio
    async def test_check_entity_access_no_user(self, guard):
        with patch("kernel.guards.legal_entity_boundary.get_current_user", return_value=None):
            result = await guard.check_entity_access(uuid4())
        assert result.is_allowed is False
        assert "No user in context" in result.message
        assert result.severity == EntityAccessSeverity.CRITICAL

    @pytest.mark.asyncio
    async def test_check_entity_access_user_has_entity(self, guard, fallback_repo):
        user_id = "user1"
        entity_id = uuid4()
        fallback_repo.add_user_entity(user_id, entity_id)
        with patch("kernel.guards.legal_entity_boundary.get_current_user", return_value=user_id):
            result = await guard.check_entity_access(entity_id)
        assert result.is_allowed is True
        assert result.severity == EntityAccessSeverity.INFO
        assert entity_id in result.authorized_entities

    @pytest.mark.asyncio
    async def test_check_entity_access_user_not_have_entity(self, guard, fallback_repo):
        user_id = "user1"
        entity_id = uuid4()
        # No access
        with patch("kernel.guards.legal_entity_boundary.get_current_user", return_value=user_id):
            result = await guard.check_entity_access(entity_id)
        assert result.is_allowed is False
        assert result.severity == EntityAccessSeverity.HIGH

    @pytest.mark.asyncio
    async def test_check_entity_access_cross_auth_allowed(self, guard, fallback_repo):
        user_id = "user1"
        from_entity = uuid4()
        to_entity = uuid4()
        fallback_repo.add_user_entity(user_id, from_entity)
        fallback_repo.add_cross_entity_auth(user_id, from_entity, to_entity)
        with patch("kernel.guards.legal_entity_boundary.get_current_user", return_value=user_id):
            with patch("kernel.guards.legal_entity_boundary.get_current_legal_entity", return_value=from_entity):
                result = await guard.check_entity_access(
                    to_entity, source_entity_id=from_entity, operation="WRITE"
                )
        assert result.is_allowed is True
        assert result.severity == EntityAccessSeverity.LOW
        assert "Cross-entity access from" in result.message

    @pytest.mark.asyncio
    async def test_check_entity_access_cross_auth_denied_strict(self, guard, fallback_repo):
        user_id = "user1"
        from_entity = uuid4()
        to_entity = uuid4()
        fallback_repo.add_user_entity(user_id, from_entity)
        # No cross auth
        with patch("kernel.guards.legal_entity_boundary.get_current_user", return_value=user_id):
            with patch("kernel.guards.legal_entity_boundary.get_current_legal_entity", return_value=from_entity):
                result = await guard.check_entity_access(
                    to_entity, source_entity_id=from_entity, operation="READ"
                )
        assert result.is_allowed is False
        assert result.severity == EntityAccessSeverity.HIGH

    @pytest.mark.asyncio
    async def test_check_entity_access_cross_auth_allowed_non_strict(self, guard, fallback_repo):
        guard.set_strict_mode(False)
        user_id = "user1"
        from_entity = uuid4()
        to_entity = uuid4()
        fallback_repo.add_user_entity(user_id, from_entity)
        with patch("kernel.guards.legal_entity_boundary.get_current_user", return_value=user_id):
            with patch("kernel.guards.legal_entity_boundary.get_current_legal_entity", return_value=from_entity):
                result = await guard.check_entity_access(
                    to_entity, source_entity_id=from_entity, operation="READ"
                )
        assert result.is_allowed is True
        assert result.severity == EntityAccessSeverity.MEDIUM
        assert "allowed in non-strict mode" in result.message

    @pytest.mark.asyncio
    async def test_check_entity_access_cache(self, guard, fallback_repo):
        user_id = "user1"
        entity_id = uuid4()
        fallback_repo.add_user_entity(user_id, entity_id)
        with patch("kernel.guards.legal_entity_boundary.get_current_user", return_value=user_id):
            result1 = await guard.check_entity_access(entity_id, use_cache=True)
            # Second call should use cache
            result2 = await guard.check_entity_access(entity_id, use_cache=True)
            # The result objects should be the same reference
            assert result1 is result2

    # ---- CHECK_MULTI_ENTITY_ACCESS ----
    @pytest.mark.asyncio
    async def test_check_multi_entity_all_allowed(self, guard, fallback_repo):
        user_id = "user1"
        entities = [uuid4(), uuid4()]
        for e in entities:
            fallback_repo.add_user_entity(user_id, e)
        with patch("kernel.guards.legal_entity_boundary.get_current_user", return_value=user_id):
            allowed, results = await guard.check_multi_entity_access(entities, require_all=True)
        assert allowed is True
        assert len(results) == 2
        assert all(r.is_allowed for r in results)

    @pytest.mark.asyncio
    async def test_check_multi_entity_some_denied_require_all(self, guard, fallback_repo):
        user_id = "user1"
        entities = [uuid4(), uuid4()]
        fallback_repo.add_user_entity(user_id, entities[0])  # only first allowed
        with patch("kernel.guards.legal_entity_boundary.get_current_user", return_value=user_id):
            allowed, results = await guard.check_multi_entity_access(entities, require_all=True)
        assert allowed is False
        assert len(results) == 1  # early exit after first denial? Actually we break on denial, so results only contain first check.
        # Let's verify: The loop breaks on denial when require_all=True, so only first result.
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_check_multi_entity_some_denied_require_any(self, guard, fallback_repo):
        user_id = "user1"
        entities = [uuid4(), uuid4()]
        fallback_repo.add_user_entity(user_id, entities[0])  # only first allowed
        with patch("kernel.guards.legal_entity_boundary.get_current_user", return_value=user_id):
            allowed, results = await guard.check_multi_entity_access(entities, require_all=False)
        assert allowed is True  # any allowed
        assert len(results) == 2

    # ---- ENFORCE_CURRENT_ENTITY ----
    @pytest.mark.asyncio
    async def test_enforce_current_entity_with_context(self, guard):
        context_entity = uuid4()
        with patch("kernel.guards.legal_entity_boundary.get_current_legal_entity", return_value=context_entity):
            result = await guard.enforce_current_entity(entity_id=None)
        assert result == context_entity

    @pytest.mark.asyncio
    async def test_enforce_current_entity_no_context_raises(self, guard):
        with patch("kernel.guards.legal_entity_boundary.get_current_legal_entity", return_value=None):
            with pytest.raises(LegalEntityBoundaryError, match="No legal entity specified"):
                await guard.enforce_current_entity(entity_id=None, raise_on_violation=True)

    @pytest.mark.asyncio
    async def test_enforce_current_entity_no_context_returns_zero(self, guard):
        with patch("kernel.guards.legal_entity_boundary.get_current_legal_entity", return_value=None):
            result = await guard.enforce_current_entity(entity_id=None, raise_on_violation=False)
        assert result == UUID(int=0)

    @pytest.mark.asyncio
    async def test_enforce_current_entity_with_provided_allowed(self, guard, fallback_repo):
        user_id = "user1"
        entity_id = uuid4()
        fallback_repo.add_user_entity(user_id, entity_id)
        with patch("kernel.guards.legal_entity_boundary.get_current_user", return_value=user_id):
            result = await guard.enforce_current_entity(entity_id=entity_id)
        assert result == entity_id

    @pytest.mark.asyncio
    async def test_enforce_current_entity_with_provided_denied(self, guard, fallback_repo):
        user_id = "user1"
        entity_id = uuid4()  # not in user's entities
        with patch("kernel.guards.legal_entity_boundary.get_current_user", return_value=user_id):
            with pytest.raises(LegalEntityBoundaryError, match="does not have access"):
                await guard.enforce_current_entity(entity_id=entity_id, raise_on_violation=True)

    @pytest.mark.asyncio
    async def test_enforce_current_entity_with_provided_denied_no_raise(self, guard, fallback_repo):
        user_id = "user1"
        entity_id = uuid4()
        with patch("kernel.guards.legal_entity_boundary.get_current_user", return_value=user_id):
            # Should return the entity even if not allowed? The method returns entity_id regardless.
            # But it will not raise.
            result = await guard.enforce_current_entity(entity_id=entity_id, raise_on_violation=False)
        assert result == entity_id

    # ---- ENFORCE_CROSS_ENTITY_TRANSFER ----
    @pytest.mark.asyncio
    async def test_enforce_cross_entity_transfer_allowed(self, guard, fallback_repo):
        user_id = "user1"
        from_entity = uuid4()
        to_entity = uuid4()
        fallback_repo.add_user_entity(user_id, from_entity)
        fallback_repo.add_user_entity(user_id, to_entity)
        with patch("kernel.guards.legal_entity_boundary.get_current_user", return_value=user_id):
            allowed, results = await guard.enforce_cross_entity_transfer(
                from_entity, to_entity, Decimal("100.00")
            )
        assert allowed is True
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_enforce_cross_entity_transfer_denied(self, guard, fallback_repo):
        user_id = "user1"
        from_entity = uuid4()
        to_entity = uuid4()
        fallback_repo.add_user_entity(user_id, from_entity)  # only from allowed
        with patch("kernel.guards.legal_entity_boundary.get_current_user", return_value=user_id):
            with pytest.raises(LegalEntityBoundaryError, match="not authorized"):
                await guard.enforce_cross_entity_transfer(
                    from_entity, to_entity, Decimal("100.00"), raise_on_violation=True
                )

    @pytest.mark.asyncio
    async def test_enforce_cross_entity_transfer_denied_no_raise(self, guard, fallback_repo):
        user_id = "user1"
        from_entity = uuid4()
        to_entity = uuid4()
        fallback_repo.add_user_entity(user_id, from_entity)
        with patch("kernel.guards.legal_entity_boundary.get_current_user", return_value=user_id):
            allowed, results = await guard.enforce_cross_entity_transfer(
                from_entity, to_entity, Decimal("100.00"), raise_on_violation=False
            )
        assert allowed is False
        assert len(results) == 2

    # ---- ENFORCE_CONSOLIDATION ----
    @pytest.mark.asyncio
    async def test_enforce_consolidation_allowed(self, guard, fallback_repo):
        user_id = "user1"
        parent = uuid4()
        children = [uuid4(), uuid4()]
        fallback_repo.add_user_entity(user_id, parent)
        for c in children:
            fallback_repo.add_cross_entity_auth(user_id, parent, c)  # allow cross-entity for consolidation
        with patch("kernel.guards.legal_entity_boundary.get_current_user", return_value=user_id):
            allowed, results = await guard.enforce_consolidation(parent, children)
        assert allowed is True
        assert len(results) == 3  # parent + 2 children

    @pytest.mark.asyncio
    async def test_enforce_consolidation_denied(self, guard, fallback_repo):
        user_id = "user1"
        parent = uuid4()
        children = [uuid4(), uuid4()]
        fallback_repo.add_user_entity(user_id, parent)
        # No cross auth for children
        with patch("kernel.guards.legal_entity_boundary.get_current_user", return_value=user_id):
            with pytest.raises(LegalEntityBoundaryError, match="not authorized"):
                await guard.enforce_consolidation(parent, children, raise_on_violation=True)

    @pytest.mark.asyncio
    async def test_enforce_consolidation_denied_no_raise(self, guard, fallback_repo):
        user_id = "user1"
        parent = uuid4()
        children = [uuid4()]
        fallback_repo.add_user_entity(user_id, parent)
        with patch("kernel.guards.legal_entity_boundary.get_current_user", return_value=user_id):
            allowed, results = await guard.enforce_consolidation(parent, children, raise_on_violation=False)
        assert allowed is False
        assert len(results) == 2

    # ---- GET_CHECK_HISTORY ----
    @pytest.mark.asyncio
    async def test_get_check_history(self, guard, fallback_repo):
        user_id = "user1"
        entity1 = uuid4()
        entity2 = uuid4()
        fallback_repo.add_user_entity(user_id, entity1)
        with patch("kernel.guards.legal_entity_boundary.get_current_user", return_value=user_id):
            await guard.check_entity_access(entity1)
            await guard.check_entity_access(entity2)  # denied
        history = guard.get_check_history()
        assert len(history) == 2

    def test_get_check_history_filters(self, guard):
        # Add some history manually
        check1 = EntityAccessCheckResult(
            check_id=uuid4(), user_id="u1", source_entity_id=None,
            target_entity_id=uuid4(), operation="READ",
            is_allowed=True, severity=EntityAccessSeverity.INFO,
            message="OK"
        )
        check2 = EntityAccessCheckResult(
            check_id=uuid4(), user_id="u2", source_entity_id=None,
            target_entity_id=uuid4(), operation="WRITE",
            is_allowed=False, severity=EntityAccessSeverity.HIGH,
            message="Denied"
        )
        with guard._lock:
            guard._check_history = [check1, check2]

        # only denied
        denied = guard.get_check_history(only_denied=True)
        assert len(denied) == 1
        assert denied[0].is_allowed is False

        # by user
        user1 = guard.get_check_history(user_id="u1")
        assert len(user1) == 1
        assert user1[0].user_id == "u1"

        # by operation
        read_ops = guard.get_check_history(operation="READ")
        assert len(read_ops) == 1
        assert read_ops[0].operation == "READ"

        # by entity
        target = check1.target_entity_id
        entity_filter = guard.get_check_history(entity_id=target)
        assert len(entity_filter) == 1
        assert entity_filter[0].target_entity_id == target

    # ---- GET_STATISTICS ----
    @pytest.mark.asyncio
    async def test_get_statistics(self, guard, fallback_repo):
        user_id = "user1"
        entity1 = uuid4()
        entity2 = uuid4()
        fallback_repo.add_user_entity(user_id, entity1)
        with patch("kernel.guards.legal_entity_boundary.get_current_user", return_value=user_id):
            await guard.check_entity_access(entity1)  # allowed
            await guard.check_entity_access(entity2)  # denied
        stats = guard.get_statistics()
        assert stats["total_checks"] == 2
        assert stats["denied_count"] == 1
        assert stats["denial_rate"] == 0.5
        assert stats["strict_mode"] is True
        assert stats["enabled"] is True
        assert "READ" in stats["by_operation"]
        # cross-entity attempts: 0 because no source_entity

    @pytest.mark.asyncio
    async def test_get_statistics_cross_entity(self, guard, fallback_repo):
        user_id = "user1"
        from_entity = uuid4()
        to_entity = uuid4()
        fallback_repo.add_user_entity(user_id, from_entity)
        with patch("kernel.guards.legal_entity_boundary.get_current_user", return_value=user_id):
            with patch("kernel.guards.legal_entity_boundary.get_current_legal_entity", return_value=from_entity):
                await guard.check_entity_access(to_entity, source_entity_id=from_entity)  # cross-entity denied
        stats = guard.get_statistics()
        assert stats["cross_entity_attempts"] == 1
        assert stats["cross_entity_denied"] == 1

    # ---- RESET ----
    def test_reset(self, guard):
        guard._check_history.append(MagicMock())
        guard._cache["key"] = (MagicMock(), datetime.now(UTC))
        guard._version = 5
        guard.reset()
        assert len(guard._check_history) == 0
        assert len(guard._cache) == 0
        assert guard._version == 6
        assert len(guard._audit_trail) == 0  # reset clears audit trail


# ============================================================================
# SINGLETON ACCESSOR TESTS
# ============================================================================

def test_get_legal_entity_boundary_guard_singleton():
    with patch("kernel.guards.legal_entity_boundary._legal_entity_boundary_guard_instance", None):
        guard1 = get_legal_entity_boundary_guard()
        guard2 = get_legal_entity_boundary_guard()
        assert guard1 is guard2
        assert isinstance(guard1, LegalEntityBoundaryGuard)


# ============================================================================
# INTEGRATION TESTS WITH REAL FALLBACK REPOSITORY
# ============================================================================

class TestIntegration:
    @pytest.mark.asyncio
    async def test_full_flow_with_fallback(self):
        repo = _FallbackUserRepository()
        guard = LegalEntityBoundaryGuard(user_repository=repo)

        user_id = "user1"
        entity1 = uuid4()
        entity2 = uuid4()

        repo.add_user_entity(user_id, entity1)
        repo.set_user_roles(user_id, ["finance"])
        repo.add_user_details(user_id, "Alice", "alice@x.com")

        with patch("kernel.guards.legal_entity_boundary.get_current_user", return_value=user_id):
            # Access allowed
            result1 = await guard.check_entity_access(entity1)
            assert result1.is_allowed is True
            # Access denied
            result2 = await guard.check_entity_access(entity2)
            assert result2.is_allowed is False

            # Cross-entity transfer
            repo.add_user_entity(user_id, entity2)  # now both allowed
            allowed, results = await guard.enforce_cross_entity_transfer(entity1, entity2, Decimal("100"))
            assert allowed is True

            # Consolidation with cross auth
            child = uuid4()
            repo.add_cross_entity_auth(user_id, entity1, child)
            allowed, _results = await guard.enforce_consolidation(entity1, [child])
            assert allowed is True

        stats = guard.get_statistics()
        assert stats["total_checks"] >= 3  # at least three checks
        assert stats["denied_count"] == 1
