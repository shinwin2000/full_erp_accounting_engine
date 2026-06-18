#!/usr/bin/env python3
"""
Module: test_dependency_injector.py
Layer: Tests / Unit / Kernel

Responsibility:
    Unit tests untuk dependency injector (IoC container).
"""

from __future__ import annotations

from typing import Protocol

import pytest

from kernel.dependency_injector import (
    CircularDependencyError,
    DependencyInjector,
    ServiceNotFoundError,
)


class GreetingService(Protocol):
    def greet(self, name: str) -> str: ...


class HelloService:
    def greet(self, name: str) -> str:
        return f"Hello, {name}"


class UserService:
    def __init__(self, greeting: GreetingService):
        self.greeting = greeting

    def welcome(self, name: str) -> str:
        return self.greeting.greet(name)


def test_dependency_injector_register_and_resolve():
    injector = DependencyInjector()
    injector.register(GreetingService, HelloService)
    service = injector.resolve(GreetingService)
    assert isinstance(service, HelloService)
    assert service.greet("World") == "Hello, World"


def test_dependency_injector_with_constructor_injection():
    injector = DependencyInjector()
    injector.register(GreetingService, HelloService)
    injector.register(UserService, UserService)
    user_service = injector.resolve(UserService)
    assert user_service.welcome("Alice") == "Hello, Alice"


def test_dependency_injector_singleton_scope():
    injector = DependencyInjector(scope="singleton")
    injector.register(GreetingService, HelloService)
    s1 = injector.resolve(GreetingService)
    s2 = injector.resolve(GreetingService)
    assert s1 is s2


def test_dependency_injector_transient_scope():
    injector = DependencyInjector(scope="transient")
    injector.register(GreetingService, HelloService)
    s1 = injector.resolve(GreetingService)
    s2 = injector.resolve(GreetingService)
    assert s1 is not s2


def test_dependency_injector_circular_detection():
    class A:
        def __init__(self, b: B):
            pass

    class B:
        def __init__(self, a: A):
            pass

    injector = DependencyInjector()
    injector.register(A, A)
    injector.register(B, B)
    with pytest.raises(CircularDependencyError):
        injector.resolve(A)


def test_dependency_injector_unregistered_service():
    injector = DependencyInjector()
    with pytest.raises(ServiceNotFoundError):
        injector.resolve(GreetingService)


def test_dependency_injector_factory_registration():
    injector = DependencyInjector()

    def factory():
        return HelloService()

    injector.register_factory(GreetingService, factory)
    service = injector.resolve(GreetingService)
    assert isinstance(service, HelloService)


if __name__ == "__main__":
    pytest.main([__file__])
