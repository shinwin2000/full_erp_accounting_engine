#!/usr/bin/env python3
"""
Module: ioc_container.py
Layer: Bootstrap (Dependency Container)
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
    pass


class DependencyNotFoundError(ContainerError):
    pass


class CircularDependencyError(ContainerError):
    pass


class RegistrationError(ContainerError):
    pass


class DependencyDefinition:
    __slots__ = ("_lock", "factory", "implementation", "instance", "interface", "lifetime")

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
    __slots__ = ("_aliases", "_parent", "_registrations", "_resolving", "_scoped_instances", "_singletons")

    def __init__(self, parent: IoCContainer | None = None):
        self._parent = parent
        self._registrations: dict[type | str, DependencyDefinition] = {}
        self._singletons: dict[type | str, Any] = {}
        self._scoped_instances: dict[type | str, Any] = {}
        self._resolving: set[type | str] = set()
        self._aliases: dict[str, type | str] = {}

    def register_alias(self, alias: str, target: type | str) -> None:
        if not alias:
            raise RegistrationError("Alias cannot be empty")
        if target is None:
            raise RegistrationError(f"Alias target for '{alias}' cannot be None")
        self._aliases[alias] = target
        logger.debug(f"Registered alias {alias} -> {target}")

    def _canonicalize(self, interface: type | str) -> type | str:
        seen: set[str] = set()
        current = interface
        while isinstance(current, str) and current in self._aliases:
            if current in seen:
                raise CircularDependencyError(f"Circular alias chain detected at '{current}'")
            seen.add(current)
            current = self._aliases[current]
        return current

    def register(
        self,
        interface: type[T] | str,
        implementation: type | Callable | None = None,
        lifetime: Lifetime | None = None,
        factory: Callable[..., T] | None = None,
    ) -> None:
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
        self.register(interface, implementation, Lifetime.SINGLETON, factory)

    def register_transient(self, interface: type[T] | str, implementation: type | None = None) -> None:
        self.register(interface, implementation, Lifetime.TRANSIENT)

    def register_scoped(self, interface: type[T] | str, implementation: type | None = None) -> None:
        self.register(interface, implementation, Lifetime.SCOPED)

    def register_instance(self, interface: type[T] | str, instance: T) -> None:
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
        try:
            asyncio.get_running_loop()
            raise RuntimeError(
                f"Cannot resolve {interface} synchronously inside running event loop. "
                "Use await resolve_async() instead."
            )
        except RuntimeError as e:
            if "no running event loop" in str(e):
                loop = asyncio.new_event_loop()
                try:
                    return loop.run_until_complete(self.resolve_async(interface, **kwargs))
                finally:
                    loop.close()
            raise

    def resolve_sync(self, interface: type[T] | str, **kwargs) -> T:
        return self.resolve(interface, **kwargs)

    async def resolve_async(self, interface: type[T] | str, **kwargs) -> T:
        canonical = self._canonicalize(interface)
        if self._parent and canonical in self._scoped_instances:
            return self._scoped_instances[canonical]
        if canonical in self._resolving:
            raise CircularDependencyError(f"Circular dependency on {canonical}")

        definition = self._registrations.get(canonical)
        if not definition:
            if self._parent:
                return await self._parent.resolve_async(canonical, **kwargs)
            raise DependencyNotFoundError(f"Dependency tidak terdaftar: {canonical}")

        if definition.lifetime == Lifetime.SINGLETON:
            if canonical in self._singletons:
                return self._singletons[canonical]
            self._resolving.add(canonical)
            try:
                instance = await self._create_instance(definition, **kwargs)
                self._singletons[canonical] = instance
                return instance
            finally:
                self._resolving.remove(canonical)

        elif definition.lifetime == Lifetime.SCOPED:
            if canonical in self._scoped_instances:
                return self._scoped_instances[canonical]
            self._resolving.add(canonical)
            try:
                instance = await self._create_instance(definition, **kwargs)
                self._scoped_instances[canonical] = instance
                return instance
            finally:
                self._resolving.remove(canonical)

        else:
            self._resolving.add(canonical)
            try:
                return await self._create_instance(definition, **kwargs)
            finally:
                self._resolving.remove(canonical)

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
        return self.resolve(interface, **kwargs)

    def create_scope(self) -> IoCContainer:
        return IoCContainer(parent=self)

    def clear_scoped(self) -> None:
        self._scoped_instances.clear()

    def has_registration(self, interface: type | str) -> bool:
        canonical = self._canonicalize(interface)
        return canonical in self._registrations or (
            self._parent and self._parent.has_registration(canonical)
        )

    def get_registered_types(self) -> list[type | str]:
        types = list(self._registrations.keys())
        if self._parent:
            types.extend(self._parent.get_registered_types())
        return list(set(types))

    def reset(self) -> None:
        self._registrations.clear()
        self._singletons.clear()
        self._scoped_instances.clear()
        self._resolving.clear()
        self._aliases.clear()
        logger.info("IoC container reset")

    def remove(self, interface: type | str) -> bool:
        canonical = self._canonicalize(interface)
        if canonical in self._registrations:
            del self._registrations[canonical]
            if canonical in self._singletons:
                del self._singletons[canonical]
            if canonical in self._scoped_instances:
                del self._scoped_instances[canonical]
            logger.debug(f"Removed registration: {canonical}")
            return True
        return False


Container = IoCContainer

_global_container: IoCContainer | None = None


def get_container() -> IoCContainer:
    """Get global container instance (lazy initialized)."""
    global _global_container
    if _global_container is None:
        _global_container = IoCContainer()
    return _global_container


def initialize_container() -> None:
    """
    Initialize the global container with all registrations.
    This should be called once at application startup.
    """
    container = get_container()

    # Import registrations locally to break circular dependency
    from bootstrap.dependency_container.adapter_registry import AdapterRegistry, set_adapter_registry_instance
    from bootstrap.dependency_container.service_registry import ServiceRegistrar

    # Adapter registry
    registry = AdapterRegistry(container=container)
    set_adapter_registry_instance(registry)
    registry.register_all()
    logger.info("Adapter registry completed")

    # Service registry
    try:
        loop = asyncio.get_running_loop()
        if loop.is_running():
            loop.create_task(ServiceRegistrar.register_all(container))
            logger.info("Service registry scheduled on existing loop")
        else:
            asyncio.run(ServiceRegistrar.register_all(container))
    except RuntimeError:
        asyncio.run(ServiceRegistrar.register_all(container))
    logger.info("Service registry completed")

    # Aliases
    alias_map = {
        "IJournalRepository": "JournalRepositoryPort",
        "IUnitOfWork": "UnitOfWorkPort",
        "IEventPublisher": "EventPublisherPort",
        "ITaxAuthorityPort": "CoreTaxPort",
        "IUserRepository": "IAMUserRepositoryPort",
        "IAccountRepository": "AccountRepositoryPort",
        "IArRepository": "ARRepositoryPort",
        "IApRepository": "APRepositoryPort",
        "IInventoryRepository": "InventoryRepositoryPort",
        "IFixedAssetRepository": "FixedAssetRepositoryPort",
        "IPayrollRepository": "PayrollRepositoryPort",
        "IManufacturingRepository": "ManufacturingRepositoryPort",
        "IConsolidationRepository": "ConsolidationRepositoryPort",
        "IForexRepository": "ForexRepositoryPort",
        "IHedgeRepository": "HedgeRepositoryPort",
    }
    for alias, target in alias_map.items():
        if not container.has_registration(alias):
            container.register_alias(alias, target)
    logger.info("Aliases registered")

    logger.info(f"Container initialized with {len(container.get_registered_types())} registered types")


def build_container() -> IoCContainer:
    initialize_container()
    return get_container()


def get_request_container() -> IoCContainer:
    return get_container().create_scope()


def clear_request_container() -> None:
    pass


def injectable(cls):
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
    "initialize_container",
    "injectable",
]