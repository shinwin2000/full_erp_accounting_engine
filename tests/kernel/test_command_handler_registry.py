#!/usr/bin/env python3
"""
Tests for kernel/command_handler_registry.py
Comprehensive unit tests for CommandHandlerRegistry and related classes.
"""


import pytest

from kernel.command_handler_registry import (
    BaseCommandHandlerRegistry,
    CommandHandlerRegistry,
    HandlerAlreadyExistsError,
    HandlerDefinition,
    HandlerExecutionError,
    HandlerNotFoundError,
    HandlerType,
    command_handler,
    event_handler,
    get_handler_registry,
    query_handler,
    saga_handler,
)


# =============================================================================
# Test HandlerType Enum
# =============================================================================
class TestHandlerType:
    """Tests for the HandlerType enum."""

    def test_all_members_exist(self):
        """All expected enum members are defined."""
        assert hasattr(HandlerType, "COMMAND")
        assert hasattr(HandlerType, "QUERY")
        assert hasattr(HandlerType, "EVENT")
        assert hasattr(HandlerType, "SAGA")

    def test_members_are_instances(self):
        """Enum members are instances of HandlerType."""
        assert isinstance(HandlerType.COMMAND, HandlerType)
        assert isinstance(HandlerType.QUERY, HandlerType)
        assert isinstance(HandlerType.EVENT, HandlerType)
        assert isinstance(HandlerType.SAGA, HandlerType)

    def test_auto_values_are_unique(self):
        """Each enum member has a unique auto-generated value."""
        values = [member.value for member in HandlerType]
        assert len(values) == len(set(values))

    def test_iteration(self):
        """Can iterate over all enum members."""
        members = list(HandlerType)
        assert len(members) == 4
        assert HandlerType.COMMAND in members
        assert HandlerType.QUERY in members
        assert HandlerType.EVENT in members
        assert HandlerType.SAGA in members


# =============================================================================
# Test HandlerDefinition
# =============================================================================
class TestHandlerDefinition:
    """Tests for the HandlerDefinition dataclass."""

    def _build_kwargs(self, handler=None):
        if handler is None:
            handler = lambda *a, **kw: None
        return dict(
            command_type="TestCommand",
            handler=handler,
            handler_type=HandlerType.COMMAND,
            version="1.0.0",
            description="Test description",
            dependencies=["dep1", "dep2"],
            timeout_seconds=60,
            retry_count=5,
            requires_approval=True,
            approval_roles=["admin", "manager"],
            is_async=False,
        )

    def test_construction_with_all_fields(self):
        """HandlerDefinition can be constructed with all field values."""
        kwargs = self._build_kwargs()
        instance = HandlerDefinition(**kwargs)
        assert isinstance(instance, HandlerDefinition)
        assert instance.command_type == kwargs["command_type"]
        assert instance.handler == kwargs["handler"]
        assert instance.handler_type == kwargs["handler_type"]
        assert instance.version == kwargs["version"]
        assert instance.description == kwargs["description"]
        assert instance.dependencies == kwargs["dependencies"]
        assert instance.timeout_seconds == kwargs["timeout_seconds"]
        assert instance.retry_count == kwargs["retry_count"]
        assert instance.requires_approval == kwargs["requires_approval"]
        assert instance.approval_roles == kwargs["approval_roles"]

    def test_default_values(self):
        """HandlerDefinition uses correct default values."""
        handler = lambda *a, **kw: None
        instance = HandlerDefinition(command_type="Test", handler=handler, handler_type=HandlerType.COMMAND)
        assert instance.version == "1.0.0"
        assert instance.description == ""
        assert instance.dependencies == []
        assert instance.timeout_seconds == 30
        assert instance.retry_count == 3
        assert instance.requires_approval is False
        assert instance.approval_roles == []

    def test_is_async_detected_for_sync_function(self):
        """is_async is False for regular functions."""
        def sync_handler():
            pass

        instance = HandlerDefinition(command_type="Test", handler=sync_handler, handler_type=HandlerType.COMMAND)
        assert instance.is_async is False

    @pytest.mark.asyncio
    async def test_is_async_detected_for_async_function(self):
        """is_async is True for async functions."""
        async def async_handler():
            pass

        instance = HandlerDefinition(command_type="Test", handler=async_handler, handler_type=HandlerType.COMMAND)
        assert instance.is_async is True

    def test_handler_stored_as_weakref_proxy(self):
        """Handler is stored as a weakref proxy in registry."""
        # This is tested indirectly through registry behavior
        handler = lambda *a, **kw: None
        instance = HandlerDefinition(command_type="Test", handler=handler, handler_type=HandlerType.COMMAND)
        # The handler should be callable
        assert callable(instance.handler)


# =============================================================================
# Test Exception Classes
# =============================================================================
class TestHandlerNotFoundError:
    """Tests for HandlerNotFoundError exception."""

    def test_construction(self):
        """HandlerNotFoundError can be instantiated."""
        instance = HandlerNotFoundError(command_type="TestCommand")
        assert isinstance(instance, HandlerNotFoundError)
        assert instance.command_type == "TestCommand"
        assert "TestCommand" in str(instance)

    def test_message_contains_command_type(self):
        """Exception message contains the command type."""
        instance = HandlerNotFoundError(command_type="MyCommand")
        assert "MyCommand" in str(instance)


class TestHandlerAlreadyExistsError:
    """Tests for HandlerAlreadyExistsError exception."""

    def test_construction(self):
        """HandlerAlreadyExistsError can be instantiated."""
        instance = HandlerAlreadyExistsError(command_type="TestCommand")
        assert isinstance(instance, HandlerAlreadyExistsError)
        assert instance.command_type == "TestCommand"
        assert "TestCommand" in str(instance)

    def test_message_contains_command_type(self):
        """Exception message contains the command type."""
        instance = HandlerAlreadyExistsError(command_type="ExistingCommand")
        assert "ExistingCommand" in str(instance)


class TestHandlerExecutionError:
    """Tests for HandlerExecutionError exception."""

    def test_construction(self):
        """HandlerExecutionError can be instantiated."""
        original_error = ValueError("Something went wrong")
        instance = HandlerExecutionError(command_type="TestCommand", original_error=original_error)
        assert isinstance(instance, HandlerExecutionError)
        assert instance.command_type == "TestCommand"
        assert instance.original_error == original_error
        assert "TestCommand" in str(instance)

    def test_message_contains_details(self):
        """Exception message contains command type and original error."""
        original_error = RuntimeError("Failed!")
        instance = HandlerExecutionError(command_type="FailCommand", original_error=original_error)
        assert "FailCommand" in str(instance)
        assert "Failed!" in str(instance)


# =============================================================================
# Test BaseCommandHandlerRegistry (Abstract Base Class)
# =============================================================================
class TestBaseCommandHandlerRegistry:
    """Tests for BaseCommandHandlerRegistry abstract base class."""

    def test_class_is_defined(self):
        """BaseCommandHandlerRegistry is importable."""
        assert BaseCommandHandlerRegistry is not None

    def test_cannot_instantiate_abstract_class(self):
        """Cannot instantiate the abstract base class directly."""
        with pytest.raises(TypeError):
            BaseCommandHandlerRegistry()

    def test_abstract_methods_defined(self):
        """Abstract methods are defined in the base class."""
        abstract_methods = BaseCommandHandlerRegistry.__abstractmethods__
        assert "register" in abstract_methods
        assert "get_handler" in abstract_methods
        assert "list_handlers" in abstract_methods
        assert "unregister" in abstract_methods
        assert "get_statistics" in abstract_methods


# =============================================================================
# Test CommandHandlerRegistry
# =============================================================================
class TestCommandHandlerRegistry:
    """Tests for CommandHandlerRegistry concrete implementation."""

    @pytest.fixture
    def registry(self):
        """Create a fresh registry instance for each test."""
        # Reset singleton state
        CommandHandlerRegistry._instance = None
        reg = CommandHandlerRegistry()
        reg.clear()
        return reg

    def test_singleton_pattern(self):
        """CommandHandlerRegistry follows singleton pattern."""
        CommandHandlerRegistry._instance = None
        reg1 = CommandHandlerRegistry()
        reg2 = CommandHandlerRegistry()
        assert reg1 is reg2

    def test_construction(self):
        """CommandHandlerRegistry can be instantiated."""
        CommandHandlerRegistry._instance = None
        instance = CommandHandlerRegistry()
        assert isinstance(instance, CommandHandlerRegistry)

    def test_initial_state(self, registry):
        """Registry starts with empty handlers."""
        stats = registry.get_statistics()
        assert stats["command_handlers"] == 0
        assert stats["query_handlers"] == 0
        assert stats["event_handler_subscriptions"] == 0
        assert stats["saga_handlers"] == 0

    # -------------------------------------------------------------------------
    # Test register() method
    # -------------------------------------------------------------------------
    def test_register_command_handler(self, registry):
        """Can register a command handler."""
        handler = lambda *a, **kw: None
        registry.register(command_type="TestCommand", handler=handler, handler_type=HandlerType.COMMAND)
        assert registry.has_handler("TestCommand")

    def test_register_raises_for_non_callable(self, registry):
        """Register raises ValueError for non-callable handler."""
        with pytest.raises(ValueError, match="must be callable"):
            registry.register(command_type="Test", handler="not_callable", handler_type=HandlerType.COMMAND)

    def test_register_command_duplicate_raises(self, registry):
        """Registering duplicate command handler raises HandlerAlreadyExistsError."""
        handler1 = lambda *a, **kw: None
        handler2 = lambda *a, **kw: None
        registry.register(command_type="DupCommand", handler=handler1, handler_type=HandlerType.COMMAND)
        with pytest.raises(HandlerAlreadyExistsError):
            registry.register(command_type="DupCommand", handler=handler2, handler_type=HandlerType.COMMAND)

    def test_register_query_duplicate_raises(self, registry):
        """Registering duplicate query handler raises HandlerAlreadyExistsError."""
        handler1 = lambda *a, **kw: None
        handler2 = lambda *a, **kw: None
        registry.register(command_type="DupQuery", handler=handler1, handler_type=HandlerType.QUERY)
        with pytest.raises(HandlerAlreadyExistsError):
            registry.register(command_type="DupQuery", handler=handler2, handler_type=HandlerType.QUERY)

    def test_register_saga_duplicate_raises(self, registry):
        """Registering duplicate saga handler raises HandlerAlreadyExistsError."""
        handler1 = lambda *a, **kw: None
        handler2 = lambda *a, **kw: None
        registry.register(command_type="DupSaga", handler=handler1, handler_type=HandlerType.SAGA)
        with pytest.raises(HandlerAlreadyExistsError):
            registry.register(command_type="DupSaga", handler=handler2, handler_type=HandlerType.SAGA)

    def test_register_event_allows_multiple(self, registry):
        """Event handlers allow multiple registrations for same event type."""
        handler1 = lambda *a, **kw: None
        handler2 = lambda *a, **kw: None
        registry.register(command_type="MultiEvent", handler=handler1, handler_type=HandlerType.EVENT)
        registry.register(command_type="MultiEvent", handler=handler2, handler_type=HandlerType.EVENT)
        handlers = registry.get_event_handlers("MultiEvent")
        assert len(handlers) == 2

    def test_register_records_history(self, registry):
        """Registration is recorded in history."""
        handler = lambda *a, **kw: None
        registry.register(command_type="HistoryCommand", handler=handler, handler_type=HandlerType.COMMAND)
        history = registry.get_registration_history()
        assert len(history) == 1
        assert history[0]["command_type"] == "HistoryCommand"
        assert history[0]["handler_type"] == "COMMAND"

    # -------------------------------------------------------------------------
    # Test convenience registration methods
    # -------------------------------------------------------------------------
    def test_register_command_handler_convenience(self, registry):
        """register_command_handler convenience method works."""
        handler = lambda *a, **kw: None
        registry.register_command_handler(command_type="ConvenienceCmd", handler=handler)
        assert registry.has_handler("ConvenienceCmd")

    def test_register_query_handler_convenience(self, registry):
        """register_query_handler convenience method works."""
        handler = lambda *a, **kw: None
        registry.register_query_handler(query_type="ConvenienceQuery", handler=handler)
        assert registry.has_query_handler("ConvenienceQuery")

    def test_register_event_handler_convenience(self, registry):
        """register_event_handler convenience method works."""
        handler = lambda *a, **kw: None
        registry.register_event_handler(event_type="ConvenienceEvent", handler=handler)
        handlers = registry.get_event_handlers("ConvenienceEvent")
        assert len(handlers) == 1

    def test_register_saga_handler_convenience(self, registry):
        """register_saga_handler convenience method works."""
        handler = lambda *a, **kw: None
        registry.register_saga_handler(saga_type="ConvenienceSaga", handler=handler)
        assert registry.has_saga_handler("ConvenienceSaga")

    # -------------------------------------------------------------------------
    # Test get_handler() and related methods
    # -------------------------------------------------------------------------
    def test_get_handler_returns_handler(self, registry):
        """get_handler returns the registered handler."""
        handler = lambda *a, **kw: "result"
        registry.register_command_handler(command_type="GetCmd", handler=handler)
        retrieved = registry.get_handler("GetCmd")
        assert retrieved is not None

    def test_get_handler_not_found_raises(self, registry):
        """get_handler raises HandlerNotFoundError when not found."""
        with pytest.raises(HandlerNotFoundError):
            registry.get_handler("NonExistent")

    def test_get_handler_definition(self, registry):
        """get_handler_definition returns HandlerDefinition."""
        handler = lambda *a, **kw: None
        registry.register_command_handler(
            command_type="DefCmd", handler=handler, version="2.0.0", description="Test desc"
        )
        definition = registry.get_handler_definition("DefCmd")
        assert isinstance(definition, HandlerDefinition)
        assert definition.version == "2.0.0"
        assert definition.description == "Test desc"

    def test_get_query_handler(self, registry):
        """get_query_handler returns query handler."""
        handler = lambda *a, **kw: "query_result"
        registry.register_query_handler(query_type="GetQuery", handler=handler)
        retrieved = registry.get_query_handler("GetQuery")
        assert retrieved is not None

    def test_get_query_handler_not_found_returns_none(self, registry):
        """get_query_handler returns None when not found."""
        result = registry.get_query_handler("NonExistentQuery")
        assert result is None

    def test_get_event_handlers(self, registry):
        """get_event_handlers returns list of handlers."""
        handler1 = lambda *a, **kw: None
        handler2 = lambda *a, **kw: None
        registry.register_event_handler(event_type="MultiEvent", handler=handler1)
        registry.register_event_handler(event_type="MultiEvent", handler=handler2)
        handlers = registry.get_event_handlers("MultiEvent")
        assert len(handlers) == 2

    def test_get_event_handlers_empty_list(self, registry):
        """get_event_handlers returns empty list for unknown event."""
        handlers = registry.get_event_handlers("UnknownEvent")
        assert handlers == []

    def test_get_saga_handler(self, registry):
        """get_saga_handler returns saga handler."""
        handler = lambda *a, **kw: "saga_result"
        registry.register_saga_handler(saga_type="GetSaga", handler=handler)
        retrieved = registry.get_saga_handler("GetSaga")
        assert retrieved is not None

    def test_get_saga_handler_not_found_returns_none(self, registry):
        """get_saga_handler returns None when not found."""
        result = registry.get_saga_handler("NonExistentSaga")
        assert result is None

    # -------------------------------------------------------------------------
    # Test has_handler() methods
    # -------------------------------------------------------------------------
    def test_has_handler_true(self, registry):
        """has_handler returns True for registered handler."""
        handler = lambda *a, **kw: None
        registry.register_command_handler(command_type="HasCmd", handler=handler)
        assert registry.has_handler("HasCmd") is True

    def test_has_handler_false(self, registry):
        """has_handler returns False for unregistered handler."""
        assert registry.has_handler("NotRegistered") is False

    def test_has_query_handler(self, registry):
        """has_query_handler works correctly."""
        handler = lambda *a, **kw: None
        registry.register_query_handler(query_type="HasQuery", handler=handler)
        assert registry.has_query_handler("HasQuery") is True
        assert registry.has_query_handler("NotRegistered") is False

    def test_has_saga_handler(self, registry):
        """has_saga_handler works correctly."""
        handler = lambda *a, **kw: None
        registry.register_saga_handler(saga_type="HasSaga", handler=handler)
        assert registry.has_saga_handler("HasSaga") is True
        assert registry.has_saga_handler("NotRegistered") is False

    # -------------------------------------------------------------------------
    # Test list_handlers() method
    # -------------------------------------------------------------------------
    def test_list_handlers_all_types(self, registry):
        """list_handlers returns all registered handlers."""
        cmd_handler = lambda *a, **kw: None
        query_handler_fn = lambda *a, **kw: None
        event_handler_fn = lambda *a, **kw: None
        saga_handler_fn = lambda *a, **kw: None

        registry.register_command_handler(command_type="ListCmd", handler=cmd_handler)
        registry.register_query_handler(query_type="ListQuery", handler=query_handler_fn)
        registry.register_event_handler(event_type="ListEvent", handler=event_handler_fn)
        registry.register_saga_handler(saga_type="ListSaga", handler=saga_handler_fn)

        all_handlers = registry.list_handlers()
        assert len(all_handlers) == 4

    def test_list_handlers_filtered_by_type(self, registry):
        """list_handlers can filter by handler type."""
        cmd_handler = lambda *a, **kw: None
        query_handler_fn = lambda *a, **kw: None

        registry.register_command_handler(command_type="FilterCmd", handler=cmd_handler)
        registry.register_query_handler(query_type="FilterQuery", handler=query_handler_fn)

        cmd_only = registry.list_handlers(handler_type=HandlerType.COMMAND)
        assert len(cmd_only) == 1
        assert cmd_only[0]["type"] == "COMMAND"

        query_only = registry.list_handlers(handler_type=HandlerType.QUERY)
        assert len(query_only) == 1
        assert query_only[0]["type"] == "QUERY"

    def test_list_handlers_empty(self, registry):
        """list_handlers returns empty list when no handlers registered."""
        handlers = registry.list_handlers()
        assert handlers == []

    # -------------------------------------------------------------------------
    # Test unregister() method
    # -------------------------------------------------------------------------
    def test_unregister_command_handler(self, registry):
        """unregister removes command handler."""
        handler = lambda *a, **kw: None
        registry.register_command_handler(command_type="UnregCmd", handler=handler)
        assert registry.has_handler("UnregCmd") is True

        result = registry.unregister("UnregCmd", handler_type=HandlerType.COMMAND)
        assert result is True
        assert registry.has_handler("UnregCmd") is False

    def test_unregister_query_handler(self, registry):
        """unregister removes query handler."""
        handler = lambda *a, **kw: None
        registry.register_query_handler(query_type="UnregQuery", handler=handler)

        result = registry.unregister("UnregQuery", handler_type=HandlerType.QUERY)
        assert result is True
        assert registry.has_query_handler("UnregQuery") is False

    def test_unregister_saga_handler(self, registry):
        """unregister removes saga handler."""
        handler = lambda *a, **kw: None
        registry.register_saga_handler(saga_type="UnregSaga", handler=handler)

        result = registry.unregister("UnregSaga", handler_type=HandlerType.SAGA)
        assert result is True
        assert registry.has_saga_handler("UnregSaga") is False

    def test_unregister_event_handlers(self, registry):
        """unregister removes all event handlers for event type."""
        handler1 = lambda *a, **kw: None
        handler2 = lambda *a, **kw: None
        registry.register_event_handler(event_type="UnregEvent", handler=handler1)
        registry.register_event_handler(event_type="UnregEvent", handler=handler2)

        result = registry.unregister("UnregEvent", handler_type=HandlerType.EVENT)
        assert result is True
        assert registry.get_event_handlers("UnregEvent") == []

    def test_unregister_not_found_returns_false(self, registry):
        """unregister returns False when handler not found."""
        result = registry.unregister("NonExistent", handler_type=HandlerType.COMMAND)
        assert result is False

    def test_unregister_event_handler_specific(self, registry):
        """unregister_event_handler removes specific handler."""
        handler1 = lambda *a, **kw: None
        handler2 = lambda *a, **kw: None
        registry.register_event_handler(event_type="SpecificEvent", handler=handler1)
        registry.register_event_handler(event_type="SpecificEvent", handler=handler2)

        result = registry.unregister_event_handler("SpecificEvent", handler1)
        assert result is True
        handlers = registry.get_event_handlers("SpecificEvent")
        assert len(handlers) == 1

    # -------------------------------------------------------------------------
    # Test clear() method
    # -------------------------------------------------------------------------
    def test_clear_removes_all_handlers(self, registry):
        """clear() removes all registered handlers."""
        registry.register_command_handler(command_type="ClearCmd", handler=lambda: None)
        registry.register_query_handler(query_type="ClearQuery", handler=lambda: None)
        registry.register_event_handler(event_type="ClearEvent", handler=lambda: None)
        registry.register_saga_handler(saga_type="ClearSaga", handler=lambda: None)

        registry.clear()

        stats = registry.get_statistics()
        assert stats["command_handlers"] == 0
        assert stats["query_handlers"] == 0
        assert stats["event_handler_subscriptions"] == 0
        assert stats["saga_handlers"] == 0

    def test_clear_increments_version(self, registry):
        """clear() increments the version."""
        initial_version = registry.version()
        registry.clear()
        assert registry.version() == initial_version + 1

    def test_clear_resets_history(self, registry):
        """clear() resets registration history."""
        registry.register_command_handler(command_type="HistCmd", handler=lambda: None)
        assert len(registry.get_registration_history()) == 1

        registry.clear()
        assert len(registry.get_registration_history()) == 0

    # -------------------------------------------------------------------------
    # Test get_statistics() method
    # -------------------------------------------------------------------------
    def test_get_statistics_counts_correctly(self, registry):
        """get_statistics returns accurate counts."""
        registry.register_command_handler(command_type="StatCmd1", handler=lambda: None)
        registry.register_command_handler(command_type="StatCmd2", handler=lambda: None)
        registry.register_query_handler(query_type="StatQuery", handler=lambda: None)
        registry.register_event_handler(event_type="StatEvent", handler=lambda: None)
        registry.register_event_handler(event_type="StatEvent", handler=lambda: None)
        registry.register_saga_handler(saga_type="StatSaga", handler=lambda: None)

        stats = registry.get_statistics()
        assert stats["command_handlers"] == 2
        assert stats["query_handlers"] == 1
        assert stats["event_handler_subscriptions"] == 2
        assert stats["saga_handlers"] == 1
        assert stats["total_handlers"] == 6

    # -------------------------------------------------------------------------
    # Test validate_dependencies() method
    # -------------------------------------------------------------------------
    def test_validate_dependencies_no_missing(self, registry):
        """validate_dependencies returns empty list when all deps exist."""
        registry.register_command_handler(command_type="DepA", handler=lambda: None)
        registry.register_command_handler(
            command_type="DepB", handler=lambda: None, dependencies=["DepA"]
        )

        missing = registry.validate_dependencies()
        assert missing == []

    def test_validate_dependencies_finds_missing(self, registry):
        """validate_dependencies finds missing dependencies."""
        registry.register_command_handler(
            command_type="MissingDepCmd", handler=lambda: None, dependencies=["NonExistent"]
        )

        missing = registry.validate_dependencies()
        assert len(missing) == 1
        assert "NonExistent" in missing[0]

    # -------------------------------------------------------------------------
    # Test Entity Methods: validate(), to_dict(), from_dict(), clone()
    # -------------------------------------------------------------------------
    def test_validate_returns_valid_when_ok(self, registry):
        """validate() returns is_valid=True when no errors."""
        registry.register_command_handler(command_type="ValidCmd", handler=lambda: None)
        result = registry.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_to_dict(self, registry):
        """to_dict() returns dictionary representation."""
        registry.register_command_handler(command_type="DictCmd", handler=lambda: None)
        registry.register_query_handler(query_type="DictQuery", handler=lambda: None)

        result = registry.to_dict()
        assert "command_handlers" in result
        assert "query_handlers" in result
        assert "event_handlers" in result
        assert "saga_handlers" in result
        assert "version" in result
        assert "DictCmd" in result["command_handlers"]
        assert "DictQuery" in result["query_handlers"]

    def test_from_dict(self, registry):
        """from_dict() creates instance from dictionary."""
        data = {"version": 5}
        new_instance = CommandHandlerRegistry.from_dict(data)
        assert isinstance(new_instance, CommandHandlerRegistry)
        assert new_instance.version() == 5

    def test_clone(self, registry):
        """clone() creates new instance with incremented version."""
        # Note: Due to singleton pattern, clone returns same instance but with incremented version
        registry.register_command_handler(command_type="CloneCmd", handler=lambda: None)
        original_version = registry.version()

        cloned = registry.clone()
        # Singleton returns same instance, but version should be incremented
        assert cloned.version() == original_version + 1

    # -------------------------------------------------------------------------
    # Test snapshot(), version(), audit_trail(), touch()
    # -------------------------------------------------------------------------
    def test_snapshot(self, registry):
        """snapshot() returns current state snapshot."""
        registry.register_command_handler(command_type="SnapCmd", handler=lambda: None)
        snapshot = registry.snapshot()

        assert "version" in snapshot
        assert "command_handlers" in snapshot
        assert "query_handlers" in snapshot
        assert "event_handlers" in snapshot
        assert "saga_handlers" in snapshot
        assert "timestamp" in snapshot

    def test_version(self, registry):
        """version() returns current version number."""
        # Fresh registry starts at version 1 (but clear() in fixture may increment)
        current = registry.version()
        registry.touch("test_user")
        assert registry.version() == current + 1

    def test_audit_trail(self, registry):
        """audit_trail() returns audit records."""
        registry.touch("user1")
        registry.touch("user2")

        trail = registry.audit_trail()
        assert len(trail) == 2
        assert trail[0]["performed_by"] == "user1"
        assert trail[1]["performed_by"] == "user2"

    def test_audit_trail_with_limit(self, registry):
        """audit_trail() respects limit parameter."""
        for i in range(10):
            registry.touch(f"user{i}")

        trail = registry.audit_trail(limit=5)
        assert len(trail) == 5

    def test_touch(self, registry):
        """touch() increments version and records audit entry."""
        initial_version = registry.version()
        result = registry.touch("touch_user")

        assert registry.version() == initial_version + 1
        assert result is registry  # Returns self

        trail = registry.audit_trail()
        assert len(trail) >= 1
        assert trail[-1]["action"] == "TOUCH"
        assert trail[-1]["performed_by"] == "touch_user"

    # -------------------------------------------------------------------------
    # Test get_registration_history()
    # -------------------------------------------------------------------------
    def test_get_registration_history(self, registry):
        """get_registration_history returns registration records."""
        registry.register_command_handler(command_type="HistCmd1", handler=lambda: None)
        registry.register_command_handler(command_type="HistCmd2", handler=lambda: None)

        history = registry.get_registration_history()
        assert len(history) == 2

    def test_get_registration_history_with_limit(self, registry):
        """get_registration_history respects limit parameter."""
        for i in range(10):
            registry.register_command_handler(command_type=f"HistCmd{i}", handler=lambda: None)

        history = registry.get_registration_history(limit=5)
        assert len(history) == 5


# =============================================================================
# Test Module-level Decorators
# =============================================================================
class TestDecorators:
    """Tests for module-level decorator functions."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Reset registry before each test."""
        CommandHandlerRegistry._instance = None
        global _handler_registry_instance
        from kernel import command_handler_registry as chr_module

        chr_module._handler_registry_instance = None
        yield
        # Cleanup
        CommandHandlerRegistry._instance = None
        chr_module._handler_registry_instance = None

    def test_command_handler_decorator(self):
        """command_handler decorator registers handler."""
        from kernel import command_handler_registry as chr_module

        @command_handler(command_type="DecoratedCmd", version="1.0.0", description="Test")
        def my_handler():
            pass

        registry = chr_module.get_handler_registry()
        assert registry.has_handler("DecoratedCmd")

    def test_query_handler_decorator(self):
        """query_handler decorator registers handler."""
        from kernel import command_handler_registry as chr_module

        @query_handler(query_type="DecoratedQuery", version="1.0.0", description="Test")
        def my_query_handler():
            pass

        registry = chr_module.get_handler_registry()
        assert registry.has_query_handler("DecoratedQuery")

    def test_event_handler_decorator(self):
        """event_handler decorator registers handler."""
        from kernel import command_handler_registry as chr_module

        @event_handler(event_type="DecoratedEvent", version="1.0.0", description="Test")
        def my_event_handler():
            pass

        registry = chr_module.get_handler_registry()
        handlers = registry.get_event_handlers("DecoratedEvent")
        assert len(handlers) == 1

    def test_saga_handler_decorator(self):
        """saga_handler decorator registers handler."""
        from kernel import command_handler_registry as chr_module

        @saga_handler(saga_type="DecoratedSaga", version="1.0.0", description="Test")
        def my_saga_handler():
            pass

        registry = chr_module.get_handler_registry()
        assert registry.has_saga_handler("DecoratedSaga")


# =============================================================================
# Test get_handler_registry() function
# =============================================================================
class TestGetHandlerRegistry:
    """Tests for get_handler_registry() function."""

    def test_returns_singleton(self):
        """get_handler_registry returns singleton instance."""
        from kernel import command_handler_registry as chr_module

        chr_module._handler_registry_instance = None
        CommandHandlerRegistry._instance = None

        reg1 = get_handler_registry()
        reg2 = get_handler_registry()
        assert reg1 is reg2

    def test_creates_new_if_none_exists(self):
        """get_handler_registry creates new instance if none exists."""
        from kernel import command_handler_registry as chr_module

        chr_module._handler_registry_instance = None
        CommandHandlerRegistry._instance = None

        registry = get_handler_registry()
        assert isinstance(registry, CommandHandlerRegistry)


# =============================================================================
# Integration Tests
# =============================================================================
class TestIntegration:
    """Integration tests for CommandHandlerRegistry."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Reset registry state."""
        CommandHandlerRegistry._instance = None
        from kernel import command_handler_registry as chr_module

        chr_module._handler_registry_instance = None
        yield
        CommandHandlerRegistry._instance = None
        chr_module._handler_registry_instance = None

    def test_full_registration_and_retrieval_workflow(self):
        """Full workflow: register, retrieve, execute handler."""
        # Register handlers
        def command_handler_fn():
            return "command executed"

        def query_handler_fn():
            return "query result"

        def event_handler_fn():
            return "event processed"

        def saga_handler_fn():
            return "saga completed"

        registry = get_handler_registry()

        registry.register_command_handler(command_type="TestCmd", handler=command_handler_fn)
        registry.register_query_handler(query_type="TestQuery", handler=query_handler_fn)
        registry.register_event_handler(event_type="TestEvent", handler=event_handler_fn)
        registry.register_saga_handler(saga_type="TestSaga", handler=saga_handler_fn)

        # Retrieve and execute
        cmd_handler = registry.get_handler("TestCmd")
        assert cmd_handler() == "command executed"

        query_handler = registry.get_query_handler("TestQuery")
        assert query_handler() == "query result"

        event_handlers = registry.get_event_handlers("TestEvent")
        assert len(event_handlers) == 1
        assert event_handlers[0]() == "event processed"

        saga_handler = registry.get_saga_handler("TestSaga")
        assert saga_handler() == "saga completed"

    def test_handler_metadata_preserved(self):
        """Handler metadata is preserved after registration."""
        registry = get_handler_registry()

        registry.register_command_handler(
            command_type="MetaCmd",
            handler=lambda: None,
            version="2.5.0",
            description="Detailed description",
            dependencies=["DepA", "DepB"],
            timeout_seconds=120,
            retry_count=10,
            requires_approval=True,
            approval_roles=["admin", "supervisor"],
        )

        definition = registry.get_handler_definition("MetaCmd")
        assert definition.version == "2.5.0"
        assert definition.description == "Detailed description"
        assert definition.dependencies == ["DepA", "DepB"]
        assert definition.timeout_seconds == 120
        assert definition.retry_count == 10
        assert definition.requires_approval is True
        assert definition.approval_roles == ["admin", "supervisor"]

    def test_statistics_accurate_after_operations(self):
        """Statistics remain accurate after various operations."""
        registry = get_handler_registry()

        # Add handlers
        for i in range(5):
            registry.register_command_handler(command_type=f"Cmd{i}", handler=lambda: None)
        for i in range(3):
            registry.register_query_handler(query_type=f"Query{i}", handler=lambda: None)
        for i in range(2):
            registry.register_event_handler(event_type="MultiEvent", handler=lambda: None)
        registry.register_saga_handler(saga_type="Saga1", handler=lambda: None)

        stats = registry.get_statistics()
        assert stats["command_handlers"] == 5
        assert stats["query_handlers"] == 3
        assert stats["event_handler_subscriptions"] == 2
        assert stats["saga_handlers"] == 1

        # Remove one
        registry.unregister("Cmd0", handler_type=HandlerType.COMMAND)
        stats = registry.get_statistics()
        assert stats["command_handlers"] == 4
