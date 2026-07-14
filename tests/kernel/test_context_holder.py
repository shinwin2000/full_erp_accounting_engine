#!/usr/bin/env python3
"""
Tests for kernel/context_holder.py
Tests ExecutionContext, ContextSnapshot, ContextHolder, and convenience functions.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from kernel.context_holder import (
    BaseContextHolder,
    ContextHolder,
    ContextSnapshot,
    ExecutionContext,
    enrich_with_context,
    get_context_holder,
    get_correlation_id,
    get_current_legal_entity,
    get_current_permissions,
    get_current_roles,
    get_current_user,
)


class TestExecutionContext:
    """Tests for the ExecutionContext value object / model."""

    def _build_kwargs(self):
        return dict(
            user_id="user-123",
            legal_entity_id=uuid4(),
            correlation_id="corr-456",
            command_id=uuid4(),
            causation_id=uuid4(),
            tenant_id="tenant-789",
            roles=["admin", "user"],
            permissions=["read", "write"],
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0",
            started_at=datetime.now(UTC),
        )

    def test_construction_success(self):
        """ExecutionContext can be constructed with valid field values."""
        kwargs = self._build_kwargs()
        instance = ExecutionContext(**kwargs)
        assert isinstance(instance, ExecutionContext)
        assert instance.user_id == kwargs["user_id"]
        assert instance.legal_entity_id == kwargs["legal_entity_id"]

    def test_default_values(self):
        """ExecutionContext has correct default values for optional fields."""
        instance = ExecutionContext(user_id="user-1", legal_entity_id=uuid4())
        assert instance.correlation_id is None
        assert instance.command_id is None
        assert instance.causation_id is None
        assert instance.tenant_id is None
        assert instance.roles == []
        assert instance.permissions == []
        assert instance.ip_address is None
        assert instance.user_agent is None
        assert isinstance(instance.started_at, datetime)

    def test_to_dict(self):
        """to_dict() returns a dictionary representation."""
        kwargs = self._build_kwargs()
        instance = ExecutionContext(**kwargs)
        result = instance.to_dict()
        assert isinstance(result, dict)
        assert result["user_id"] == kwargs["user_id"]
        assert result["legal_entity_id"] == str(kwargs["legal_entity_id"])
        assert result["correlation_id"] == kwargs["correlation_id"]
        assert result["roles"] == kwargs["roles"]
        assert result["permissions"] == kwargs["permissions"][:10]

    def test_from_dict(self):
        """from_dict() creates an instance from a dictionary."""
        data = {
            "user_id": "user-123",
            "legal_entity_id": str(uuid4()),
            "correlation_id": "corr-456",
            "command_id": str(uuid4()),
            "causation_id": str(uuid4()),
            "tenant_id": "tenant-789",
            "roles": ["admin"],
            "permissions": ["read"],
            "ip_address": "192.168.1.1",
            "user_agent": "Mozilla/5.0",
            "started_at": datetime.now(UTC).isoformat(),
        }
        instance = ExecutionContext.from_dict(data)
        assert isinstance(instance, ExecutionContext)
        assert instance.user_id == data["user_id"]
        assert str(instance.legal_entity_id) == data["legal_entity_id"]

    def test_clone(self):
        """clone() creates a copy with independent lists."""
        kwargs = self._build_kwargs()
        instance = ExecutionContext(**kwargs)
        cloned = instance.clone()
        assert cloned.user_id == instance.user_id
        assert cloned.legal_entity_id == instance.legal_entity_id
        assert cloned.roles is not instance.roles
        assert cloned.permissions is not instance.permissions
        assert cloned.roles == instance.roles
        assert cloned.permissions == instance.permissions

    def test_snapshot(self):
        """snapshot() returns a minimal snapshot dictionary."""
        kwargs = self._build_kwargs()
        instance = ExecutionContext(**kwargs)
        snap = instance.snapshot()
        assert isinstance(snap, dict)
        assert snap["user_id"] == instance.user_id
        assert snap["legal_entity_id"] == str(instance.legal_entity_id)
        assert "started_at" in snap

    def test_version(self):
        """version() returns the version number."""
        instance = ExecutionContext(user_id="user-1", legal_entity_id=uuid4())
        assert instance.version() == 1

    def test_audit_trail(self):
        """audit_trail() returns a list containing the current state."""
        kwargs = self._build_kwargs()
        instance = ExecutionContext(**kwargs)
        trail = instance.audit_trail()
        assert isinstance(trail, list)
        assert len(trail) == 1
        assert trail[0]["user_id"] == kwargs["user_id"]

    def test_touch(self):
        """touch() returns a new instance with updated timestamp."""
        kwargs = self._build_kwargs()
        instance = ExecutionContext(**kwargs)
        original_time = instance.started_at
        touched = instance.touch("system")
        assert touched is not instance
        assert touched.started_at >= original_time
        assert touched.user_id == instance.user_id

    def test_has_role_true(self):
        """has_role() returns True when role exists."""
        instance = ExecutionContext(
            user_id="user-1", legal_entity_id=uuid4(), roles=["admin", "user"]
        )
        assert instance.has_role("admin") is True
        assert instance.has_role("user") is True

    def test_has_role_false(self):
        """has_role() returns False when role does not exist."""
        instance = ExecutionContext(
            user_id="user-1", legal_entity_id=uuid4(), roles=["user"]
        )
        assert instance.has_role("admin") is False

    def test_has_permission_true(self):
        """has_permission() returns True when permission exists."""
        instance = ExecutionContext(
            user_id="user-1", legal_entity_id=uuid4(), permissions=["read", "write"]
        )
        assert instance.has_permission("read") is True

    def test_has_permission_false(self):
        """has_permission() returns False when permission does not exist."""
        instance = ExecutionContext(
            user_id="user-1", legal_entity_id=uuid4(), permissions=["read"]
        )
        assert instance.has_permission("delete") is False

    def test_has_any_permission_true(self):
        """has_any_permission() returns True when any permission exists."""
        instance = ExecutionContext(
            user_id="user-1", legal_entity_id=uuid4(), permissions=["read"]
        )
        assert instance.has_any_permission("read", "delete") is True

    def test_has_any_permission_false(self):
        """has_any_permission() returns False when no permissions exist."""
        instance = ExecutionContext(
            user_id="user-1", legal_entity_id=uuid4(), permissions=["write"]
        )
        assert instance.has_any_permission("read", "delete") is False

    def test_validate_success(self):
        """validate() returns success when required fields are present."""
        instance = ExecutionContext(user_id="user-1", legal_entity_id=uuid4())
        result = instance.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_missing_user_id(self):
        """validate() fails when user_id is missing."""
        instance = ExecutionContext(user_id="", legal_entity_id=uuid4())
        result = instance.validate()
        assert result["is_valid"] is False
        assert "user_id is required" in result["errors"]

    def test_validate_missing_legal_entity_id(self):
        """validate() fails when legal_entity_id is missing."""
        instance = ExecutionContext(user_id="user-1", legal_entity_id=None)
        result = instance.validate()
        assert result["is_valid"] is False
        assert "legal_entity_id is required" in result["errors"]

    def test_to_dict_truncates_long_user_agent(self):
        """to_dict() truncates long user_agent to 100 characters."""
        long_ua = "x" * 200
        instance = ExecutionContext(
            user_id="user-1", legal_entity_id=uuid4(), user_agent=long_ua
        )
        result = instance.to_dict()
        assert len(result["user_agent"]) == 100

    def test_from_dict_without_optional_fields(self):
        """from_dict() handles missing optional fields gracefully."""
        data = {
            "user_id": "user-123",
            "legal_entity_id": str(uuid4()),
        }
        instance = ExecutionContext.from_dict(data)
        assert instance.user_id == "user-123"
        assert instance.correlation_id is None


class TestContextSnapshot:
    """Tests for the ContextSnapshot value object / model."""

    def test_construction_success(self):
        """ContextSnapshot can be constructed with valid field values."""
        ctx = ExecutionContext(user_id="user-1", legal_entity_id=uuid4())
        timestamp = datetime.now(UTC)
        instance = ContextSnapshot(context=ctx, timestamp=timestamp)
        assert isinstance(instance, ContextSnapshot)
        assert instance.context == ctx
        assert instance.timestamp == timestamp

    def test_construction_with_none_context(self):
        """ContextSnapshot can be constructed with None context."""
        timestamp = datetime.now(UTC)
        instance = ContextSnapshot(context=None, timestamp=timestamp)
        assert instance.context is None
        assert instance.timestamp == timestamp


class TestBaseContextHolder:
    """Tests for BaseContextHolder abstract base class."""

    def test_class_defined(self):
        """BaseContextHolder is an abstract base class and is importable."""
        assert BaseContextHolder is not None

    def test_is_abstract(self):
        """BaseContextHolder cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseContextHolder()

    def test_has_required_abstract_methods(self):
        """BaseContextHolder defines all required abstract methods."""
        abstract_methods = BaseContextHolder.__abstractmethods__
        required = {
            "set_context",
            "get_context",
            "push_context",
            "pop_context",
            "clear_context",
            "get_current_user_id",
            "get_current_legal_entity_id",
            "get_correlation_id",
            "get_current_roles",
            "get_current_permissions",
            "create_child_context",
            "get_context_snapshot",
        }
        assert required.issubset(abstract_methods)


class TestContextHolder:
    """Tests for ContextHolder concrete implementation."""

    @pytest.fixture
    def holder(self):
        """Create a fresh ContextHolder instance for testing."""
        # Reset singleton state before each test
        ContextHolder._instance = None
        holder = ContextHolder()
        holder.reset()
        yield holder
        holder.reset()
        ContextHolder._instance = None

    def test_singleton_pattern(self):
        """ContextHolder follows singleton pattern."""
        ContextHolder._instance = None
        h1 = ContextHolder()
        h2 = ContextHolder()
        assert h1 is h2
        ContextHolder._instance = None

    def test_construction(self):
        """ContextHolder can be instantiated."""
        ContextHolder._instance = None
        instance = ContextHolder()
        assert isinstance(instance, ContextHolder)
        ContextHolder._instance = None

    def test_initial_state(self, holder):
        """ContextHolder starts with no context."""
        assert holder.get_context() is None
        assert holder.has_context() is False
        assert holder.get_current_user_id() is None
        assert holder.get_current_legal_entity_id() is None
        assert holder.get_correlation_id() is None
        assert holder.get_current_roles() == []
        assert holder.get_current_permissions() == []

    def test_set_context(self, holder):
        """set_context() stores and returns previous context."""
        ctx = ExecutionContext(user_id="user-1", legal_entity_id=uuid4())
        previous = holder.set_context(ctx)
        assert previous is None
        assert holder.get_context() == ctx
        assert holder.has_context() is True

    def test_set_context_returns_previous(self, holder):
        """set_context() returns the previous context."""
        ctx1 = ExecutionContext(user_id="user-1", legal_entity_id=uuid4())
        ctx2 = ExecutionContext(user_id="user-2", legal_entity_id=uuid4())
        holder.set_context(ctx1)
        previous = holder.set_context(ctx2)
        assert previous == ctx1
        assert holder.get_context() == ctx2

    def test_get_context(self, holder):
        """get_context() returns the current context."""
        ctx = ExecutionContext(user_id="user-1", legal_entity_id=uuid4())
        holder.set_context(ctx)
        assert holder.get_context() == ctx

    def test_get_current_user_id(self, holder):
        """get_current_user_id() extracts user_id from context."""
        ctx = ExecutionContext(user_id="user-123", legal_entity_id=uuid4())
        holder.set_context(ctx)
        assert holder.get_current_user_id() == "user-123"

    def test_get_current_user_id_no_context(self, holder):
        """get_current_user_id() returns None when no context."""
        assert holder.get_current_user_id() is None

    def test_get_current_legal_entity_id(self, holder):
        """get_current_legal_entity_id() extracts legal_entity_id from context."""
        entity_id = uuid4()
        ctx = ExecutionContext(user_id="user-1", legal_entity_id=entity_id)
        holder.set_context(ctx)
        assert holder.get_current_legal_entity_id() == entity_id

    def test_get_correlation_id(self, holder):
        """get_correlation_id() extracts correlation_id from context."""
        ctx = ExecutionContext(
            user_id="user-1", legal_entity_id=uuid4(), correlation_id="corr-123"
        )
        holder.set_context(ctx)
        assert holder.get_correlation_id() == "corr-123"

    def test_get_current_roles(self, holder):
        """get_current_roles() extracts roles from context."""
        ctx = ExecutionContext(
            user_id="user-1", legal_entity_id=uuid4(), roles=["admin", "user"]
        )
        holder.set_context(ctx)
        assert holder.get_current_roles() == ["admin", "user"]

    def test_get_current_roles_empty(self, holder):
        """get_current_roles() returns empty list when no context."""
        assert holder.get_current_roles() == []

    def test_get_current_permissions(self, holder):
        """get_current_permissions() extracts permissions from context."""
        ctx = ExecutionContext(
            user_id="user-1", legal_entity_id=uuid4(), permissions=["read", "write"]
        )
        holder.set_context(ctx)
        assert holder.get_current_permissions() == ["read", "write"]

    def test_push_context(self, holder):
        """push_context() saves current context and sets new one."""
        ctx1 = ExecutionContext(user_id="user-1", legal_entity_id=uuid4())
        ctx2 = ExecutionContext(user_id="user-2", legal_entity_id=uuid4())
        holder.set_context(ctx1)
        holder.push_context(ctx2)
        assert holder.get_context() == ctx2

    def test_pop_context(self, holder):
        """pop_context() restores previous context."""
        ctx1 = ExecutionContext(user_id="user-1", legal_entity_id=uuid4())
        ctx2 = ExecutionContext(user_id="user-2", legal_entity_id=uuid4())
        holder.set_context(ctx1)
        holder.push_context(ctx2)
        popped = holder.pop_context()
        # pop_context returns the restored context (ctx1), not the popped one
        assert holder.get_context() == ctx1

    def test_pop_context_empty_stack(self, holder):
        """pop_context() clears context when stack is empty."""
        ctx = ExecutionContext(user_id="user-1", legal_entity_id=uuid4())
        holder.set_context(ctx)
        popped = holder.pop_context()
        assert popped is None
        assert holder.get_context() is None

    def test_run_in_context(self, holder):
        """run_in_context() executes function with context and restores."""
        ctx = ExecutionContext(user_id="user-1", legal_entity_id=uuid4())
        original_ctx = ExecutionContext(user_id="original", legal_entity_id=uuid4())
        holder.set_context(original_ctx)

        def my_func():
            return holder.get_current_user_id()

        result = holder.run_in_context(ctx, my_func)
        assert result == "user-1"
        assert holder.get_current_user_id() == "original"

    @pytest.mark.asyncio
    async def test_run_in_context_async(self, holder):
        """run_in_context_async() executes coroutine with context and restores."""
        ctx = ExecutionContext(user_id="user-1", legal_entity_id=uuid4())
        original_ctx = ExecutionContext(user_id="original", legal_entity_id=uuid4())
        holder.set_context(original_ctx)

        async def my_coro():
            return holder.get_current_user_id()

        result = await holder.run_in_context_async(ctx, my_coro)
        assert result == "user-1"
        assert holder.get_current_user_id() == "original"

    def test_clear_context(self, holder):
        """clear_context() removes the current context."""
        ctx = ExecutionContext(user_id="user-1", legal_entity_id=uuid4())
        holder.set_context(ctx)
        holder.clear_context()
        assert holder.get_context() is None
        assert holder.has_context() is False

    def test_has_context_true(self, holder):
        """has_context() returns True when context exists."""
        ctx = ExecutionContext(user_id="user-1", legal_entity_id=uuid4())
        holder.set_context(ctx)
        assert holder.has_context() is True

    def test_has_context_false(self, holder):
        """has_context() returns False when no context."""
        assert holder.has_context() is False

    def test_enrich_with_context(self, holder):
        """enrich_with_context() adds context data to dictionary."""
        ctx = ExecutionContext(
            user_id="user-1",
            legal_entity_id=uuid4(),
            correlation_id="corr-123",
            command_id=uuid4(),
        )
        holder.set_context(ctx)
        data = {"key": "value"}
        enriched = holder.enrich_with_context(data)
        assert "_context" in enriched
        assert enriched["_context"]["user_id"] == "user-1"
        assert enriched["_context"]["correlation_id"] == "corr-123"
        assert enriched["key"] == "value"

    def test_enrich_with_context_no_context(self, holder):
        """enrich_with_context() returns original data when no context."""
        data = {"key": "value"}
        enriched = holder.enrich_with_context(data)
        assert enriched == data

    def test_enrich_with_context_preserves_existing(self, holder):
        """enrich_with_context() preserves existing _context data."""
        ctx = ExecutionContext(user_id="user-1", legal_entity_id=uuid4())
        holder.set_context(ctx)
        data = {"_context": {"existing": "data"}}
        enriched = holder.enrich_with_context(data)
        assert enriched["_context"]["existing"] == "data"
        assert enriched["_context"]["user_id"] == "user-1"

    def test_create_child_context(self, holder):
        """create_child_context() creates child from current context."""
        parent_ctx = ExecutionContext(
            user_id="user-1",
            legal_entity_id=uuid4(),
            correlation_id="corr-123",
            roles=["admin"],
            permissions=["read"],
        )
        holder.set_context(parent_ctx)
        child_ctx = holder.create_child_context()
        assert child_ctx.user_id == parent_ctx.user_id
        assert child_ctx.legal_entity_id == parent_ctx.legal_entity_id
        assert child_ctx.correlation_id == parent_ctx.correlation_id
        assert child_ctx.causation_id == parent_ctx.command_id
        assert child_ctx.command_id is not None

    def test_create_child_context_with_ids(self, holder):
        """create_child_context() uses provided command_id and causation_id."""
        parent_ctx = ExecutionContext(
            user_id="user-1", legal_entity_id=uuid4(), command_id=uuid4()
        )
        holder.set_context(parent_ctx)
        new_command_id = uuid4()
        new_causation_id = uuid4()
        child_ctx = holder.create_child_context(
            command_id=new_command_id, causation_id=new_causation_id
        )
        assert child_ctx.command_id == new_command_id
        assert child_ctx.causation_id == new_causation_id

    def test_create_child_context_no_parent(self, holder):
        """create_child_context() raises when no parent context."""
        with pytest.raises(RuntimeError, match="No current context"):
            holder.create_child_context()

    def test_get_context_snapshot(self, holder):
        """get_context_snapshot() returns context as dictionary."""
        ctx = ExecutionContext(user_id="user-1", legal_entity_id=uuid4())
        holder.set_context(ctx)
        snap = holder.get_context_snapshot()
        assert isinstance(snap, dict)
        assert snap["user_id"] == "user-1"

    def test_get_context_snapshot_no_context(self, holder):
        """get_context_snapshot() returns None when no context."""
        assert holder.get_context_snapshot() is None

    def test_validate_with_context(self, holder):
        """validate() checks context validity."""
        ctx = ExecutionContext(user_id="user-1", legal_entity_id=uuid4())
        holder.set_context(ctx)
        result = holder.validate()
        assert result["is_valid"] is True

    def test_validate_without_context(self, holder):
        """validate() returns success when no context."""
        result = holder.validate()
        assert result["is_valid"] is True

    def test_to_dict_with_context(self, holder):
        """to_dict() returns holder state including context."""
        ctx = ExecutionContext(user_id="user-1", legal_entity_id=uuid4())
        holder.set_context(ctx)
        result = holder.to_dict()
        assert result["has_context"] is True
        assert result["context"]["user_id"] == "user-1"
        assert result["stack_depth"] == 0

    def test_to_dict_without_context(self, holder):
        """to_dict() returns holder state without context."""
        result = holder.to_dict()
        assert result["has_context"] is False
        assert result["context"] is None

    def test_from_dict(self, holder):
        """from_dict() creates holder from dictionary."""
        data = {
            "context": {
                "user_id": "user-123",
                "legal_entity_id": str(uuid4()),
            },
            "version": 2,
        }
        new_holder = ContextHolder.from_dict(data)
        assert new_holder.get_current_user_id() == "user-123"
        assert new_holder.version() == 2

    def test_clone(self, holder):
        """clone() increments version on the singleton instance."""
        ctx = ExecutionContext(user_id="user-1", legal_entity_id=uuid4())
        holder.set_context(ctx)
        initial_version = holder.version()
        cloned = holder.clone()
        # Due to singleton pattern, clone returns same instance with incremented version
        assert cloned.get_current_user_id() == "user-1"
        assert cloned.version() > initial_version

    def test_snapshot(self, holder):
        """snapshot() returns holder snapshot."""
        ctx = ExecutionContext(user_id="user-1", legal_entity_id=uuid4())
        holder.set_context(ctx)
        snap = holder.snapshot()
        assert isinstance(snap, dict)
        assert "version" in snap
        assert "timestamp" in snap
        assert snap["has_context"] is True

    def test_version(self, holder):
        """version() returns current version."""
        assert holder.version() == 1

    def test_audit_trail(self, holder):
        """audit_trail() returns recorded audit entries."""
        holder.touch("system")
        trail = holder.audit_trail()
        assert isinstance(trail, list)
        assert len(trail) >= 1

    def test_audit_trail_limit(self, holder):
        """audit_trail(limit) limits returned entries."""
        for i in range(10):
            holder.touch(f"user-{i}")
        trail = holder.audit_trail(limit=5)
        assert len(trail) <= 5

    def test_touch(self, holder):
        """touch() increments version and records audit entry."""
        initial_version = holder.version()
        holder.touch("system")
        assert holder.version() == initial_version + 1

    def test_reset(self, holder):
        """reset() clears all state."""
        ctx = ExecutionContext(user_id="user-1", legal_entity_id=uuid4())
        holder.set_context(ctx)
        holder.push_context(ExecutionContext(user_id="user-2", legal_entity_id=uuid4()))
        holder.touch("system")
        holder.reset()
        assert holder.get_context() is None
        assert holder.version() == 1
        assert holder.audit_trail() == []


class TestModuleFunctions:
    """Tests for module-level convenience functions."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton state before and after each test."""
        from kernel import context_holder

        context_holder._context_holder_instance = None
        # Also reset the ContextHolder class singleton
        ContextHolder._instance = None
        yield
        context_holder._context_holder_instance = None
        ContextHolder._instance = None

    def test_get_context_holder_singleton(self):
        """get_context_holder() returns singleton instance."""
        h1 = get_context_holder()
        h2 = get_context_holder()
        assert h1 is h2

    def test_get_current_user_no_context(self):
        """get_current_user() returns None when no context."""
        assert get_current_user() is None

    def test_get_current_user_with_context(self):
        """get_current_user() returns user_id from context."""
        holder = get_context_holder()
        ctx = ExecutionContext(user_id="user-123", legal_entity_id=uuid4())
        holder.set_context(ctx)
        assert get_current_user() == "user-123"

    def test_get_current_legal_entity_with_context(self):
        """get_current_legal_entity() returns entity_id from context."""
        holder = get_context_holder()
        entity_id = uuid4()
        ctx = ExecutionContext(user_id="user-1", legal_entity_id=entity_id)
        holder.set_context(ctx)
        assert get_current_legal_entity() == entity_id

    def test_get_current_legal_entity_no_context(self):
        """get_current_legal_entity() returns None when no context."""
        # Ensure fresh state by resetting both singletons
        ContextHolder._instance = None
        from kernel import context_holder
        context_holder._context_holder_instance = None
        assert get_current_legal_entity() is None

    def test_get_correlation_id_no_context(self):
        """get_correlation_id() returns None when no context."""
        assert get_correlation_id() is None

    def test_get_correlation_id_with_context(self):
        """get_correlation_id() returns correlation_id from context."""
        holder = get_context_holder()
        ctx = ExecutionContext(
            user_id="user-1", legal_entity_id=uuid4(), correlation_id="corr-123"
        )
        holder.set_context(ctx)
        assert get_correlation_id() == "corr-123"

    def test_get_current_roles_no_context(self):
        """get_current_roles() returns empty list when no context."""
        assert get_current_roles() == []

    def test_get_current_roles_with_context(self):
        """get_current_roles() returns roles from context."""
        holder = get_context_holder()
        ctx = ExecutionContext(
            user_id="user-1", legal_entity_id=uuid4(), roles=["admin", "user"]
        )
        holder.set_context(ctx)
        assert get_current_roles() == ["admin", "user"]

    def test_get_current_permissions_no_context(self):
        """get_current_permissions() returns empty list when no context."""
        assert get_current_permissions() == []

    def test_get_current_permissions_with_context(self):
        """get_current_permissions() returns permissions from context."""
        holder = get_context_holder()
        ctx = ExecutionContext(
            user_id="user-1", legal_entity_id=uuid4(), permissions=["read", "write"]
        )
        holder.set_context(ctx)
        assert get_current_permissions() == ["read", "write"]

    def test_enrich_with_context_no_context(self):
        """enrich_with_context() returns original data when no context."""
        # Ensure fresh state by resetting both singletons
        ContextHolder._instance = None
        from kernel import context_holder
        context_holder._context_holder_instance = None
        data = {"key": "value"}
        result = enrich_with_context(data)
        assert result == data

    def test_enrich_with_context_with_context(self):
        """enrich_with_context() adds context to data."""
        holder = get_context_holder()
        ctx = ExecutionContext(
            user_id="user-1",
            legal_entity_id=uuid4(),
            correlation_id="corr-123",
        )
        holder.set_context(ctx)
        data = {"key": "value"}
        result = enrich_with_context(data)
        assert "_context" in result
        assert result["_context"]["user_id"] == "user-1"


class TestIntegration:
    """Integration tests for context holder workflow."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton state before and after each test."""
        from kernel import context_holder

        context_holder._context_holder_instance = None
        yield
        context_holder._context_holder_instance = None

    def test_full_context_lifecycle(self):
        """Test complete context lifecycle: set, use, push, pop, clear."""
        holder = get_context_holder()

        # Set initial context
        ctx1 = ExecutionContext(
            user_id="user-1",
            legal_entity_id=uuid4(),
            correlation_id="corr-1",
            roles=["user"],
        )
        holder.set_context(ctx1)
        assert get_current_user() == "user-1"

        # Push nested context
        ctx2 = ExecutionContext(
            user_id="user-2",
            legal_entity_id=uuid4(),
            correlation_id="corr-2",
            roles=["admin"],
        )
        holder.push_context(ctx2)
        assert get_current_user() == "user-2"

        # Create child context
        child = holder.create_child_context()
        assert child.user_id == "user-2"
        assert child.correlation_id == "corr-2"

        # Pop back to original
        holder.pop_context()
        assert get_current_user() == "user-1"

        # Clear context
        holder.clear_context()
        assert get_current_user() is None

    def test_context_propagation_via_run_in_context(self):
        """Test context propagation using run_in_context."""
        holder = get_context_holder()
        original_ctx = ExecutionContext(
            user_id="original", legal_entity_id=uuid4()
        )
        holder.set_context(original_ctx)

        new_ctx = ExecutionContext(user_id="temp", legal_entity_id=uuid4())

        def check_context():
            return get_current_user()

        result = holder.run_in_context(new_ctx, check_context)
        assert result == "temp"
        assert get_current_user() == "original"

    @pytest.mark.asyncio
    async def test_context_propagation_async(self):
        """Test context propagation in async context."""
        holder = get_context_holder()
        original_ctx = ExecutionContext(
            user_id="original", legal_entity_id=uuid4()
        )
        holder.set_context(original_ctx)

        new_ctx = ExecutionContext(user_id="async-temp", legal_entity_id=uuid4())

        async def check_context():
            return get_current_user()

        result = await holder.run_in_context_async(new_ctx, check_context)
        assert result == "async-temp"
        assert get_current_user() == "original"

    def test_context_snapshot_and_restore(self):
        """Test taking snapshot and restoring context."""
        holder = get_context_holder()
        ctx = ExecutionContext(
            user_id="user-1",
            legal_entity_id=uuid4(),
            correlation_id="corr-123",
            roles=["admin"],
            permissions=["read", "write"],
        )
        holder.set_context(ctx)

        # Take snapshot
        snap = holder.get_context_snapshot()
        assert snap["user_id"] == "user-1"

        # Clear and restore
        holder.clear_context()
        assert holder.get_context() is None

        # Restore from snapshot
        restored_ctx = ExecutionContext.from_dict(snap)
        holder.set_context(restored_ctx)
        assert get_current_user() == "user-1"
        assert get_correlation_id() == "corr-123"

    def test_multiple_context_operations(self):
        """Test multiple push/pop operations."""
        holder = get_context_holder()

        contexts = []
        for i in range(5):
            ctx = ExecutionContext(user_id=f"user-{i}", legal_entity_id=uuid4())
            contexts.append(ctx)
            if i == 0:
                holder.set_context(ctx)
            else:
                holder.push_context(ctx)

        # Verify deepest context
        assert get_current_user() == "user-4"

        # Pop all
        for i in range(4, 0, -1):
            holder.pop_context()
            assert get_current_user() == f"user-{i-1}"

        # Final pop clears
        holder.pop_context()
        assert get_current_user() is None

    def test_enrich_data_workflow(self):
        """Test enriching data with context throughout workflow."""
        holder = get_context_holder()
        ctx = ExecutionContext(
            user_id="user-1",
            legal_entity_id=uuid4(),
            correlation_id="corr-123",
            command_id=uuid4(),
        )
        holder.set_context(ctx)

        # Enrich outgoing data
        payload = {"action": "create", "data": {"name": "test"}}
        enriched = enrich_with_context(payload)

        assert enriched["action"] == "create"
        assert enriched["_context"]["user_id"] == "user-1"
        assert enriched["_context"]["correlation_id"] == "corr-123"
        assert enriched["_context"]["command_id"] == str(ctx.command_id)
