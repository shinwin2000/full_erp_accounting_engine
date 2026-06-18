#!/usr/bin/env python3
"""
Module: factory_provider.py
Layer: Bootstrap (Dependency Container)
Responsibility: Provider untuk factory pattern dalam dependency injection.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from typing import Any, TypeVar

from bootstrap.dependency_container.ioc_container import IoCContainer, get_container

logger = logging.getLogger(__name__)

T = TypeVar("T")


class FactoryProviderError(Exception):
    """Base exception untuk factory provider."""
    pass


class FactoryNotFoundError(FactoryProviderError):
    """Factory tidak ditemukan."""
    pass


class FactoryExecutionError(FactoryProviderError):
    """Error saat mengeksekusi factory."""
    pass


class FactoryProvider:
    """
    Provider untuk factory pattern.

    Method Standards:
    - register() - Mendaftarkan factory
    - register_for_type() - Mendaftarkan factory untuk tipe
    - get() - Mendapatkan factory by name
    - get_for_type() - Mendapatkan factory by type
    - create() - Membuat instance via factory (sync)
    - create_for_type() - Membuat instance via factory for type
    - has_factory() - Cek factory
    - list_factories() - Daftar factory
    - reset() - Reset factory
    - remove() - Menghapus factory
    """

    def __init__(self, container: IoCContainer | None = None):
        self._container = container or get_container()
        self._factories: dict[str, Callable] = {}
        self._type_factories: dict[type, Callable] = {}
        self._logger = logging.getLogger(f"{__name__}.FactoryProvider")

    def register(self, name: str, factory: Callable) -> None:
        """Register a factory function."""
        if not name:
            raise ValueError("Factory name cannot be empty")
        if not callable(factory):
            raise ValueError("Factory must be callable")
        self._factories[name] = factory
        self._logger.debug(f"Registered factory: {name}")

    def register_for_type(self, type_: type[T], factory: Callable[..., T]) -> None:
        """Register a factory for a specific type."""
        if not type_:
            raise ValueError("Type cannot be None")
        if not callable(factory):
            raise ValueError("Factory must be callable")
        self._type_factories[type_] = factory
        self._logger.debug(f"Registered factory for type: {type_.__name__}")

    def get(self, name: str) -> Callable:
        """Get factory by name."""
        if not name:
            raise ValueError("Factory name cannot be empty")
        if name not in self._factories:
            raise FactoryNotFoundError(f"Factory not found: {name}")
        return self._factories[name]

    def get_for_type(self, type_: type) -> Callable | None:
        """Get factory for type."""
        if not type_:
            raise ValueError("Type cannot be None")
        return self._type_factories.get(type_)

    async def create(self, name: str, *args, **kwargs) -> Any:
        """Create instance using factory."""
        factory = self.get(name)
        try:
            if inspect.iscoroutinefunction(factory):
                result = await factory(*args, **kwargs)
            else:
                result = factory(*args, **kwargs)
            self._logger.debug(f"Factory {name} executed successfully")
            return result
        except Exception as e:
            self._logger.error(f"Factory {name} execution failed: {e}")
            raise FactoryExecutionError(f"Factory {name} failed: {e}") from e

    async def create_for_type(self, type_: type[T], *args, **kwargs) -> T:
        """Create instance using factory for type."""
        factory = self.get_for_type(type_)
        if not factory:
            return await self._container.resolve_async(type_)
        if inspect.iscoroutinefunction(factory):
            return await factory(*args, **kwargs)
        else:
            return factory(*args, **kwargs)

    def has_factory(self, name: str) -> bool:
        """Check if factory exists."""
        return name in self._factories

    def list_factories(self) -> list[str]:
        """List all registered factory names."""
        return sorted(self._factories.keys())

    def reset(self) -> None:
        """Reset all factories."""
        self._factories.clear()
        self._type_factories.clear()
        self._logger.info("Factory provider reset")

    def remove(self, name: str) -> bool:
        """Remove a factory by name."""
        if name in self._factories:
            del self._factories[name]
            self._logger.debug(f"Removed factory: {name}")
            return True
        return False


# ============================================================================
# DEFAULT FACTORIES
# ============================================================================

class DefaultFactories:
    """Pre-defined factories for common types."""

    @staticmethod
    async def create_uow():
        """Factory for Unit of Work."""
        from adapters.secondary_impl.sqlalchemy_unit_of_work_impl import get_uow_factory
        factory = get_uow_factory()
        return factory.create()

    @staticmethod
    async def create_command_bus():
        """Factory for Command Bus."""
        from application.commands_cqrs.command_bus_unified import get_command_bus
        return await get_command_bus()

    @staticmethod
    async def create_query_bus():
        """Factory for Query Bus."""
        from application.commands_cqrs.query_bus_unified import get_query_bus
        return await get_query_bus()


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_factory_provider: FactoryProvider | None = None


def get_factory_provider() -> FactoryProvider:
    """Get singleton instance of FactoryProvider."""
    global _factory_provider
    if _factory_provider is None:
        _factory_provider = FactoryProvider()
        _factory_provider.register("uow", DefaultFactories.create_uow)
        _factory_provider.register("command_bus", DefaultFactories.create_command_bus)
        _factory_provider.register("query_bus", DefaultFactories.create_query_bus)
    return _factory_provider


def factory(name: str | None = None):
    """Decorator to register a function as factory."""

    def decorator(func):
        factory_name = name or func.__name__
        get_factory_provider().register(factory_name, func)
        return func

    return decorator


__all__ = [
    "FactoryExecutionError",
    "FactoryNotFoundError",
    "FactoryProvider",
    "FactoryProviderError",
    "factory",
    "get_factory_provider",
]