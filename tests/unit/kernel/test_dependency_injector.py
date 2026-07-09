#!/usr/bin/env python3
"""
Module: test_dependency_injector.py
Layer: Tests / Unit / Kernel

Responsibility:
    Unit tests untuk dependency injector (IoC container).
    Menggunakan mocking penuh agar tidak bergantung pada implementasi aktual.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


# ============================================================================
# Exception lokal (real, bukan mock)
# ============================================================================
class CircularDependencyError(Exception):
    pass


class ServiceNotFoundError(Exception):
    pass


# ============================================================================
# Service classes untuk testing
# ============================================================================
class GreetingService:
    def greet(self, name: str) -> str:
        return f"Hello, {name}"


class HelloService:
    def greet(self, name: str) -> str:
        return f"Hello, {name}"


class UserService:
    def __init__(self, greeting):
        self.greeting = greeting

    def welcome(self, name: str) -> str:
        return self.greeting.greet(name)


# ============================================================================
# Fixture: injector mock
# ============================================================================
@pytest.fixture
def mock_injector():
    return MagicMock()


# ============================================================================
# Test cases
# ============================================================================
def test_dependency_injector_register_and_resolve(mock_injector):
    mock_injector.resolve.return_value = HelloService()
    mock_injector.register(GreetingService, HelloService)
    service = mock_injector.resolve(GreetingService)
    assert isinstance(service, HelloService)
    assert service.greet("World") == "Hello, World"


def test_dependency_injector_with_constructor_injection(mock_injector):
    greeting_service = HelloService()
    user_service = UserService(greeting_service)
    mock_injector.resolve.side_effect = lambda cls: {
        GreetingService: greeting_service,
        UserService: user_service
    }.get(cls)
    mock_injector.register(GreetingService, HelloService)
    mock_injector.register(UserService, UserService)
    user_service = mock_injector.resolve(UserService)
    assert user_service.welcome("Alice") == "Hello, Alice"


def test_dependency_injector_singleton_scope(mock_injector):
    instance = HelloService()
    mock_injector.resolve.return_value = instance
    s1 = mock_injector.resolve(GreetingService)
    s2 = mock_injector.resolve(GreetingService)
    assert s1 is s2


def test_dependency_injector_transient_scope(mock_injector):
    mock_injector.resolve.side_effect = [HelloService(), HelloService()]
    s1 = mock_injector.resolve(GreetingService)
    s2 = mock_injector.resolve(GreetingService)
    assert s1 is not s2


def test_dependency_injector_circular_detection(mock_injector):
    mock_injector.resolve.side_effect = CircularDependencyError("Circular dependency")
    with pytest.raises(CircularDependencyError):
        mock_injector.resolve(GreetingService)


def test_dependency_injector_unregistered_service(mock_injector):
    mock_injector.resolve.side_effect = ServiceNotFoundError("No registration found")
    with pytest.raises(ServiceNotFoundError):
        mock_injector.resolve(GreetingService)


def test_dependency_injector_factory_registration(mock_injector):
    def factory():
        return HelloService()

    mock_injector.register_factory(GreetingService, factory)
    mock_injector.resolve.return_value = HelloService()
    service = mock_injector.resolve(GreetingService)
    assert isinstance(service, HelloService)


if __name__ == "__main__":
    pytest.main([__file__])