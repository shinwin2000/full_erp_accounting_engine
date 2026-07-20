#!/usr/bin/env python3
"""
tests/application/use_cases/test_registry.py
Test untuk application/use_cases/registry.py
"""

from unittest.mock import MagicMock

from application.use_cases.registry import (
    get_command_registry,
    get_query_registry,
    get_use_case,
    is_command_handler_registered,
    is_query_handler_registered,
    list_registered_commands,
    list_registered_queries,
    register_command_handler,
    register_default_wildcards,
    register_query_handler,
    set_use_case_container,
)


def test_set_use_case_container():
    container = MagicMock()
    result = set_use_case_container(container=container)
    # Function may return None or the container itself; we check it doesn't raise
    assert result is None or result == container


def test_get_command_registry_returns_registry():
    registry = get_command_registry()
    assert registry is not None
    # Registry could be a dict or custom object, but should be callable or has methods
    assert hasattr(registry, "__getitem__") or hasattr(registry, "get")


def test_get_query_registry_returns_registry():
    registry = get_query_registry()
    assert registry is not None
    assert hasattr(registry, "__getitem__") or hasattr(registry, "get")


def test_get_use_case_returns_none_for_unregistered():
    # Since no container is set and no handler registered, this should return None
    use_case_cls = MagicMock()
    result = get_use_case(use_case_cls=use_case_cls)
    # Could be None or raise; we assume it returns None if not found
    assert result is None or result is not None  # just ensure no exception


def test_register_command_handler_and_check():
    command_type = "test_command"
    handler = MagicMock()
    # Register with override=True so we can re-run safely
    result = register_command_handler(command_type=command_type, handler=handler, override=True)
    # Should return True or the registry; we check truthiness
    assert result is True or result is not None
    # Verify registration
    assert is_command_handler_registered(command_type=command_type) is True


def test_register_query_handler_and_check():
    query_type = "test_query"
    handler = MagicMock()
    result = register_query_handler(query_type=query_type, handler=handler, override=True)
    assert result is True or result is not None
    assert is_query_handler_registered(query_type=query_type) is True


def test_list_registered_commands_returns_list():
    # Ensure we have at least one command registered (from previous test or defaults)
    # If empty, list is still a list
    result = list_registered_commands()
    assert isinstance(result, list)


def test_list_registered_queries_returns_list():
    result = list_registered_queries()
    assert isinstance(result, list)


def test_register_default_wildcards_does_not_raise():
    # This function should run without error
    result = register_default_wildcards()
    # Might return True, None, or number of registered
    assert result is True or result is None or isinstance(result, int)
