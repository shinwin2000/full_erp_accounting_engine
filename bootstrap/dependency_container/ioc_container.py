#!/usr/bin/env python3
"""
Module: ioc_container.py
Layer: Bootstrap (Dependency Container)
Responsibility: Implementasi Inversion of Control (IoC) container untuk dependency injection.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from enum import Enum
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class Lifetime(Enum):
    SINGLETON = "singleton"
    TRANSIENT = "transient"
    SCOPED = "scoped"


class ContainerError(Exception):
    """Base exception untuk IoC container."""
    pass


class DependencyNotFoundError(ContainerError):
    """Dependency tidak ditemukan."""
    pass


class CircularDependencyError(ContainerError):
    """Circular dependency terdeteksi."""
    pass


class RegistrationError(ContainerError):
    """Error saat registrasi dependency."""
    pass


class DependencyDefinition:
    __slots__ = ("interface", "implementation", "lifetime", "factory", "instance", "_lock")

    def __init__(
        self,
        interface: type | str,
        implementation: type | Callable | None,
        lifetime: Lifetime,
        factory: Callable | None = None,
    ):
        self.interface = interface
        self.implementation = implementation
        self.lifetime = lifetime
        self.factory = factory
        self.instance: Any | None = None
        self._lock = asyncio.Lock()


class IoCContainer:
    """
    IoC Container untuk dependency injection.

    Method Standards:
    - register() - Registrasi dependency
    - register_singleton() - Registrasi singleton
    - register_transient() - Registrasi transient
    - register_scoped() - Registrasi scoped
    - register_instance() - Registrasi instance
    - resolve() - Resolusi sync
    - resolve_async() - Resolusi async
    - create_scope() - Membuat scope
    - clear_scoped() - Hapus scoped instances
    - has_registration() - Cek registrasi
    - get_registered_types() - Daftar tipe terdaftar
    - reset() - Reset container
    - remove() - Hapus registrasi
    """

    __slots__ = ("_parent", "_registrations", "_resolving", "_scoped_instances", "_singletons")

    def __init__(self, parent: IoCContainer | None = None):
        self._parent = parent
        self._registrations: dict[type | str, DependencyDefinition] = {}
        self._singletons: dict[type | str, Any] = {}
        self._scoped_instances: dict[type | str, Any] = {}
        self._resolving: set[type | str] = set()

    def register(
        self,
        interface: type[T] | str,
        implementation: type | Callable | None = None,
        lifetime: Lifetime | None = None,
        factory: Callable[..., T] | None = None,
    ) -> None:
        """Register dependency."""
        if implementation is None and factory is None:
            if isinstance(interface, type):
                implementation = interface
            else:
                raise RegistrationError(
                    f"Self-registration only allowed for class types, got {interface}"
                )

        if lifetime is None:
            lifetime = Lifetime.TRANSIENT

        definition = DependencyDefinition(
            interface=interface,
            implementation=implementation,
            lifetime=lifetime,
            factory=factory,
        )
        self._registrations[interface] = definition
        logger.debug(f"Registered {interface} with lifetime {lifetime.value}")

    def register_singleton(
        self,
        interface: type[T] | str,
        implementation: type | Callable | None = None,
        factory: Callable[..., T] | None = None,
    ) -> None:
        """Register singleton."""
        self.register(interface, implementation, Lifetime.SINGLETON, factory)

    def register_transient(
        self, interface: type[T] | str, implementation: type | None = None
    ) -> None:
        """Register transient."""
        self.register(interface, implementation, Lifetime.TRANSIENT)

    def register_scoped(
        self, interface: type[T] | str, implementation: type | None = None
    ) -> None:
        """Register scoped."""
        self.register(interface, implementation, Lifetime.SCOPED)

    def register_instance(self, interface: type[T] | str, instance: T) -> None:
        """Register an existing instance."""
        definition = DependencyDefinition(
            interface=interface,
            implementation=None,
            lifetime=Lifetime.SINGLETON,
            factory=None,
        )
        definition.instance = instance
        self._registrations[interface] = definition
        self._singletons[interface] = instance
        logger.debug(f"Registered instance for {interface}")

    def resolve(self, interface: type[T] | str, **kwargs) -> T:
        """Sinkron resolve dependency."""
        try:
            asyncio.get_running_loop()
            raise RuntimeError(
                f"Cannot resolve {interface} synchronously inside running event loop. "
                "Use await resolve_async() instead."
            )
        except RuntimeError as e:
            if "no running event loop" in str(e):
                return asyncio.run(self.resolve_async(interface, **kwargs))
            raise

    def resolve_sync(self, interface: type[T] | str, **kwargs) -> T:
        """Alias untuk resolve()."""
        return self.resolve(interface, **kwargs)

    async def resolve_async(self, interface: type[T] | str, **kwargs) -> T:
        """Async resolve dependency."""
        if self._parent and interface in self._scoped_instances:
            return self._scoped_instances[interface]

        if interface in self._resolving:
            raise CircularDependencyError(f"Circular dependency on {interface}")

        definition = self._registrations.get(interface)
        if not definition:
            if self._parent:
                return await self._parent.resolve_async(interface, **kwargs)
            raise DependencyNotFoundError(f"Dependency tidak terdaftar: {interface}")

        if definition.lifetime == Lifetime.SINGLETON:
            if interface in self._singletons:
                return self._singletons[interface]
            self._resolving.add(interface)
            try:
                instance = await self._create_instance(definition, **kwargs)
                self._singletons[interface] = instance
                return instance
            finally:
                self._resolving.remove(interface)

        elif definition.lifetime == Lifetime.SCOPED:
            if interface in self._scoped_instances:
                return self._scoped_instances[interface]
            self._resolving.add(interface)
            try:
                instance = await self._create_instance(definition, **kwargs)
                self._scoped_instances[interface] = instance
                return instance
            finally:
                self._resolving.remove(interface)

        else:  # TRANSIENT
            self._resolving.add(interface)
            try:
                return await self._create_instance(definition, **kwargs)
            finally:
                self._resolving.remove(interface)

    async def _create_instance(self, definition: DependencyDefinition, **kwargs) -> Any:
        if definition.factory:
            if inspect.iscoroutinefunction(definition.factory):
                return await definition.factory(**kwargs)
            else:
                return definition.factory(**kwargs)
        elif definition.implementation:
            if isinstance(definition.implementation, type):
                return await self._construct_with_injection(definition.implementation, **kwargs)
            else:
                return definition.implementation(**kwargs)
        else:
            raise RegistrationError("No factory or implementation provided")

    async def _construct_with_injection(self, cls: type, **kwargs) -> Any:
        sig = inspect.signature(cls.__init__)
        parameters = {}
        for name, param in sig.parameters.items():
            if name == "self":
                continue
            if name in kwargs:
                parameters[name] = kwargs[name]
                continue
            param_type = param.annotation
            if param_type != inspect.Parameter.empty:
                try:
                    dep = await self.resolve_async(param_type)
                    parameters[name] = dep
                except DependencyNotFoundError:
                    if param.default != inspect.Parameter.empty:
                        parameters[name] = param.default
                    else:
                        raise
        return cls(**parameters)

    def get(self, interface: type[T] | str, **kwargs) -> T:
        """Alias untuk resolve()."""
        return self.resolve(interface, **kwargs)

    def create_scope(self) -> IoCContainer:
        """Create a new scoped container."""
        return IoCContainer(parent=self)

    def clear_scoped(self) -> None:
        """Clear all scoped instances."""
        self._scoped_instances.clear()

    def has_registration(self, interface: type | str) -> bool:
        """Check if interface is registered."""
        return interface in self._registrations or (
            self._parent and self._parent.has_registration(interface)
        )

    def get_registered_types(self) -> list[type | str]:
        """Get all registered types."""
        types = list(self._registrations.keys())
        if self._parent:
            types.extend(self._parent.get_registered_types())
        return list(set(types))

    def reset(self) -> None:
        """Reset container (clear all registrations)."""
        self._registrations.clear()
        self._singletons.clear()
        self._scoped_instances.clear()
        self._resolving.clear()
        logger.info("IoC container reset")

    def remove(self, interface: type | str) -> bool:
        """Remove a registration by interface."""
        if interface in self._registrations:
            del self._registrations[interface]
            if interface in self._singletons:
                del self._singletons[interface]
            if interface in self._scoped_instances:
                del self._scoped_instances[interface]
            logger.debug(f"Removed registration: {interface}")
            return True
        return False


Container = IoCContainer

_global_container: IoCContainer | None = None


def get_container() -> IoCContainer:
    """Get global IoC container."""
    global _global_container
    if _global_container is None:
        _global_container = IoCContainer()
    return _global_container


def build_container() -> IoCContainer:
    """Build and return the global container."""
    return get_container()


def get_request_container() -> IoCContainer:
    """Get request-scoped container."""
    return get_container().create_scope()


def clear_request_container() -> None:
    """Clear request-scoped container."""
    pass


def injectable(cls):
    """Decorator to mark a class as injectable."""
    cls._injectable = True
    return cls


__all__ = [
    "CircularDependencyError",
    "Container",
    "ContainerError",
    "DependencyNotFoundError",
    "IoCContainer",
    "Lifetime",
    "RegistrationError",
    "build_container",
    "clear_request_container",
    "get_container",
    "get_request_container",
    "injectable",
]