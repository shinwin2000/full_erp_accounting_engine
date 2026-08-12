#!/usr/bin/env python3
"""
Module: dependency_injector.py
Layer: 4 - Kernel / Dependency Injector
Responsibility: Injeksi dependensi agar kernel tetap murni.
               Menyediakan container IoC (Inversion of Control) untuk
               mengelola dependensi antar komponen kernel, services,
               repositories, dan adapters. Mendukung singleton, transient,
               dan scoped lifetimes.
"""

from __future__ import annotations

import contextlib
import functools
import inspect
import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import UTC, datetime
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    pass  # Semua tipe sudah diimpor dari collections.abc

logger = logging.getLogger(__name__)

T = TypeVar("T")

# === STATIC IMPORTS FOR KERNEL COMPONENTS (lazy, with fallback) ===
# All variables are declared with type `Callable[..., Any] | None` and
# imported using contextlib.suppress to avoid mypy/ruff issues.

get_sealed_gate: Callable[..., Any] | None = None
with contextlib.suppress(ImportError):
    from kernel.sealed_gate import get_sealed_gate  # type: ignore[assignment]

get_command_dispatcher: Callable[..., Any] | None = None
with contextlib.suppress(ImportError):
    from kernel.command_dispatcher import get_command_dispatcher  # type: ignore[assignment]

get_handler_registry: Callable[..., Any] | None = None
with contextlib.suppress(ImportError):
    from kernel.command_handler_registry import get_handler_registry  # type: ignore[assignment]

get_transactional_executor: Callable[..., Any] | None = None
with contextlib.suppress(ImportError):
    from kernel.transactional_executor import get_transactional_executor  # type: ignore[assignment]

get_distributed_lock: Callable[..., Any] | None = None
with contextlib.suppress(ImportError):
    from kernel.distributed_lock_redis import get_distributed_lock  # type: ignore[assignment]

get_audit_hook_injector: Callable[..., Any] | None = None
with contextlib.suppress(ImportError):
    from kernel.audit_hook_injector import get_audit_hook_injector  # type: ignore[assignment]

get_context_holder: Callable[..., Any] | None = None
with contextlib.suppress(ImportError):
    from kernel.context_holder import get_context_holder  # type: ignore[assignment]

get_validation_pipeline: Callable[..., Any] | None = None
with contextlib.suppress(ImportError):
    from kernel.validation_pipeline import get_validation_pipeline  # type: ignore[assignment]

get_retry_policy: Callable[..., Any] | None = None
with contextlib.suppress(ImportError):
    from kernel.retry_policy import get_retry_policy  # type: ignore[assignment]

get_circuit_breaker_registry: Callable[..., Any] | None = None
with contextlib.suppress(ImportError):
    from kernel.circuit_breaker import get_circuit_breaker_registry  # type: ignore[assignment]

get_metric_collector: Callable[..., Any] | None = None
with contextlib.suppress(ImportError):
    from kernel.metric_collector import get_metric_collector  # type: ignore[assignment]

get_lifecycle_listener: Callable[..., Any] | None = None
with contextlib.suppress(ImportError):
    from kernel.lifecycle_listener import get_lifecycle_listener  # type: ignore[assignment]

get_kernel_health_indicator_sync: Callable[..., Any] | None = None
with contextlib.suppress(ImportError):
    from kernel.health_indicator import get_kernel_health_indicator_sync  # type: ignore[assignment]


# === 0. EXCEPTIONS ===
class CircularDependencyError(Exception):
    pass


class ServiceNotFoundError(Exception):
    pass


# === 1. FALLBACK IOC CONTAINER ===
class ServiceLifetime(Enum):
    SINGLETON = auto()
    TRANSIENT = auto()
    SCOPED = auto()


class _FallbackIocContainer:
    def __init__(self, default_scope: str = "singleton"):
        self._singletons: dict[type, Any] = {}
        self._factories: dict[type, Callable[..., Any]] = {}
        self._lifetimes: dict[type, ServiceLifetime] = {}
        self._implementation_classes: dict[type, type] = {}
        self._lock = threading.RLock()
        self._scoped_instances: dict[Any, dict[type, Any]] = {}
        self._default_scope = default_scope

    def _lifetime_from_scope(self, scope: str | None = None) -> ServiceLifetime:
        scope_str = scope or self._default_scope
        mapping: dict[str, ServiceLifetime] = {
            "singleton": ServiceLifetime.SINGLETON,
            "transient": ServiceLifetime.TRANSIENT,
            "scoped": ServiceLifetime.SCOPED,
        }
        return mapping.get(scope_str, ServiceLifetime.SINGLETON)

    def register(
        self,
        interface: type[T],
        implementation: type[T],
        lifetime: ServiceLifetime | str | None = None,
    ) -> None:
        with self._lock:
            self._implementation_classes[interface] = implementation
            if lifetime is None:
                lifetime = self._lifetime_from_scope()
            if isinstance(lifetime, str):
                lifetime = self._lifetime_from_scope(lifetime)
            self._lifetimes[interface] = lifetime

    def register_factory(
        self,
        interface: type[T],
        factory: Callable[[], T],
        lifetime: ServiceLifetime | str | None = None,
    ) -> None:
        with self._lock:
            self._factories[interface] = factory
            if lifetime is None:
                lifetime = self._lifetime_from_scope()
            if isinstance(lifetime, str):
                lifetime = self._lifetime_from_scope(lifetime)
            self._lifetimes[interface] = lifetime

    def register_instance(self, interface: type[T], instance: T) -> None:
        with self._lock:
            self._singletons[interface] = instance
            self._lifetimes[interface] = ServiceLifetime.SINGLETON

    def resolve(self, interface: type[T], _resolving_stack: list[type] | None = None) -> T:
        with self._lock:
            lifetime = self._lifetimes.get(interface, ServiceLifetime.TRANSIENT)
            if lifetime == ServiceLifetime.SINGLETON and interface in self._singletons:
                return self._singletons[interface]  # type: ignore[return-value]
            if lifetime == ServiceLifetime.SCOPED:
                scope_id = id(threading.current_thread())
                if scope_id not in self._scoped_instances:
                    self._scoped_instances[scope_id] = {}
                if interface in self._scoped_instances[scope_id]:
                    return self._scoped_instances[scope_id][interface]  # type: ignore[return-value]
            if _resolving_stack is None:
                _resolving_stack = []
            if interface in _resolving_stack:
                raise CircularDependencyError(
                    f"Circular dependency detected: {_resolving_stack} -> {interface}"
                )
            _resolving_stack.append(interface)
            try:
                if interface in self._factories:
                    instance = self._factories[interface]()
                elif interface in self._implementation_classes:
                    impl_class = self._implementation_classes[interface]
                    instance = self._instantiate_with_injection(impl_class, _resolving_stack)
                else:
                    raise ServiceNotFoundError(f"No registration found for {interface}")
                if lifetime == ServiceLifetime.SINGLETON:
                    self._singletons[interface] = instance
                elif lifetime == ServiceLifetime.SCOPED:
                    self._scoped_instances[scope_id][interface] = instance
                return instance
            finally:
                _resolving_stack.pop()

    def _instantiate_with_injection(self, cls: type[T], resolving_stack: list[type]) -> T:
        sig = inspect.signature(cls.__init__)
        kwargs: dict[str, Any] = {}
        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue
            param_type = param.annotation
            if param_type == inspect.Parameter.empty:
                continue
            try:
                dependency = self.resolve(param_type, resolving_stack)
                kwargs[param_name] = dependency
            except ServiceNotFoundError:
                if param.default == inspect.Parameter.empty:
                    raise ServiceNotFoundError(
                        f"Cannot resolve required parameter '{param_name}' of type {param_type} for {cls}"
                    )
        return cls(**kwargs)

    def try_resolve(self, interface: type[T]) -> T | None:
        try:
            return self.resolve(interface)
        except ServiceNotFoundError:
            return None

    def has_registration(self, interface: type) -> bool:
        return (
            interface in self._factories
            or interface in self._singletons
            or interface in self._implementation_classes
        )

    def create_scope(self) -> _FallbackScope:
        return _FallbackScope(self)

    def reset(self) -> None:
        with self._lock:
            self._singletons.clear()
            self._factories.clear()
            self._lifetimes.clear()
            self._implementation_classes.clear()
            self._scoped_instances.clear()


class _FallbackScope:
    def __init__(self, container: _FallbackIocContainer):
        self._container = container
        self._scope_id = id(self)
        self._instances: dict[type, Any] = {}

    def resolve(self, interface: type[T]) -> T:
        if interface in self._instances:
            return self._instances[interface]  # type: ignore[return-value]
        instance = self._container.resolve(interface)
        self._instances[interface] = instance
        return instance

    def dispose(self) -> None:
        self._instances.clear()


def _get_ioc_container(default_scope: str = "singleton") -> _FallbackIocContainer:
    logger.info("Using in-memory fallback IoC container")
    return _FallbackIocContainer(default_scope=default_scope)


# ============================================================================
# BASE CLASS ABSTRAK (CONTRACT)
# ============================================================================
class BaseDependencyInjector(ABC):
    """
    Base contract for Dependency Injector.
    Semua method yang wajib diimplementasikan oleh subclass.
    """

    @abstractmethod
    def register(
        self, interface: type[T], implementation: type[T], scope: str | None = None
    ) -> None:
        """Register implementation for interface."""
        pass

    @abstractmethod
    def register_factory(
        self, interface: type[T], factory: Callable[[], T], scope: str | None = None
    ) -> None:
        """Register factory for interface."""
        pass

    @abstractmethod
    def register_singleton(self, interface: type[T], factory: Callable[[], T]) -> None:
        """Register singleton instance."""
        pass

    @abstractmethod
    def register_transient(self, interface: type[T], factory: Callable[[], T]) -> None:
        """Register transient instance."""
        pass

    @abstractmethod
    def register_scoped(self, interface: type[T], factory: Callable[[], T]) -> None:
        """Register scoped instance."""
        pass

    @abstractmethod
    def register_instance(self, interface: type[T], instance: T) -> None:
        """Register existing instance."""
        pass

    @abstractmethod
    def resolve(self, interface: type[T]) -> T:
        """Resolve dependency by interface."""
        pass

    @abstractmethod
    def try_resolve(self, interface: type[T]) -> T | None:
        """Try to resolve dependency, return None if not found."""
        pass

    @abstractmethod
    def has_registration(self, interface: type) -> bool:
        """Check if interface has registration."""
        pass

    @abstractmethod
    def create_scope(self) -> Any:
        """Create a new dependency scope."""
        pass

    @abstractmethod
    def get_statistics(self) -> dict[str, Any]:
        """Get statistics about registered dependencies."""
        pass


# === 2. DEPENDENCY INJECTOR ===
class DependencyInjector(BaseDependencyInjector):
    _instance: DependencyInjector | None = None
    _lock = threading.Lock()
    _initialized: bool = False

    def __new__(cls) -> DependencyInjector:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, scope: str = "singleton") -> None:
        if self._initialized:
            return
        self._initialized = True
        self._container = _get_ioc_container(default_scope=scope)
        self._lazy_factories: dict[str, Callable[[], Any]] = {}
        self._register_defaults()
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._version = 1

    def _register_defaults(self) -> None:
        # Register lazy factories using static imports (already imported at module level)
        self._register_lazy(
            "SealedGate",
            lambda: get_sealed_gate() if get_sealed_gate is not None else None,
        )
        self._register_lazy(
            "CommandDispatcher",
            lambda: get_command_dispatcher() if get_command_dispatcher is not None else None,
        )
        self._register_lazy(
            "CommandHandlerRegistry",
            lambda: get_handler_registry() if get_handler_registry is not None else None,
        )
        self._register_lazy(
            "TransactionalExecutor",
            lambda: get_transactional_executor() if get_transactional_executor is not None else None,
        )
        self._register_lazy(
            "DistributedLock",
            lambda: get_distributed_lock() if get_distributed_lock is not None else None,
        )
        self._register_lazy(
            "AuditHookInjector",
            lambda: get_audit_hook_injector() if get_audit_hook_injector is not None else None,
        )
        self._register_lazy(
            "ContextHolder",
            lambda: get_context_holder() if get_context_holder is not None else None,
        )
        self._register_lazy(
            "ValidationPipeline",
            lambda: get_validation_pipeline() if get_validation_pipeline is not None else None,
        )
        self._register_lazy(
            "RetryPolicy",
            lambda: get_retry_policy() if get_retry_policy is not None else None,
        )
        self._register_lazy(
            "CircuitBreakerRegistry",
            lambda: get_circuit_breaker_registry() if get_circuit_breaker_registry is not None else None,
        )
        self._register_lazy(
            "MetricCollector",
            lambda: get_metric_collector() if get_metric_collector is not None else None,
        )
        self._register_lazy(
            "LifecycleListener",
            lambda: get_lifecycle_listener() if get_lifecycle_listener is not None else None,
        )
        self._register_lazy(
            "KernelHealthIndicator",
            lambda: get_kernel_health_indicator_sync()
            if get_kernel_health_indicator_sync is not None
            else None,
        )
        logger.info("Default kernel dependencies registered")

    def _register_lazy(self, name: str, factory: Callable[[], Any]) -> None:
        self._lazy_factories[name] = factory

    # === Public API ===
    def register(
        self, interface: type[T], implementation: type[T], scope: str | None = None
    ) -> None:
        lifetime = self._container._lifetime_from_scope(scope) if scope is not None else None
        self._container.register(interface, implementation, lifetime)
        self._record_audit(
            "REGISTER",
            "system",
            {"interface": interface.__name__, "implementation": implementation.__name__},
        )

    def register_factory(
        self, interface: type[T], factory: Callable[[], T], scope: str | None = None
    ) -> None:
        lifetime = self._container._lifetime_from_scope(scope) if scope is not None else None
        self._container.register_factory(interface, factory, lifetime)
        self._record_audit("REGISTER_FACTORY", "system", {"interface": interface.__name__})

    def register_singleton(self, interface: type[T], factory: Callable[[], T]) -> None:
        self._container.register_factory(interface, factory, ServiceLifetime.SINGLETON)

    def register_transient(self, interface: type[T], factory: Callable[[], T]) -> None:
        self._container.register_factory(interface, factory, ServiceLifetime.TRANSIENT)

    def register_scoped(self, interface: type[T], factory: Callable[[], T]) -> None:
        self._container.register_factory(interface, factory, ServiceLifetime.SCOPED)

    def register_instance(self, interface: type[T], instance: T) -> None:
        self._container.register_instance(interface, instance)
        self._record_audit("REGISTER_INSTANCE", "system", {"interface": interface.__name__})

    def resolve(self, interface: type[T]) -> T:
        return self._container.resolve(interface)

    def try_resolve(self, interface: type[T]) -> T | None:
        return self._container.try_resolve(interface)

    def has_registration(self, interface: type) -> bool:
        return self._container.has_registration(interface)

    def create_scope(self) -> _FallbackScope:
        return self._container.create_scope()

    def get_registered_types(self) -> list[type]:
        types: list[type] = []
        if hasattr(self._container, "_implementation_classes"):
            types.extend(self._container._implementation_classes.keys())
        if hasattr(self._container, "_factories"):
            types.extend(self._container._factories.keys())
        if hasattr(self._container, "_singletons"):
            types.extend(self._container._singletons.keys())
        return list(set(types))

    def get_statistics(self) -> dict[str, Any]:
        return {
            "registered_interfaces": len(self.get_registered_types()),
            "singletons": len(self._container._singletons),
            "factories": len(self._container._factories),
            "implementation_classes": len(self._container._implementation_classes),
            "version": self._version,
        }

    def reset(self) -> None:
        self._container.reset()
        self._register_defaults()
        self._version += 1
        self._audit_trail = []
        self._snapshots = []

    # ==================== METODA ENTITY DASAR ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        for interface in self.get_registered_types():
            try:
                self.resolve(interface)
            except CircularDependencyError as e:
                errors.append(str(e))
            except ServiceNotFoundError:
                pass
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "registered_types": [t.__name__ for t in self.get_registered_types()],
            "singletons": {k.__name__: str(v) for k, v in self._container._singletons.items()},
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DependencyInjector:
        instance = cls()
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> DependencyInjector:
        new_instance = DependencyInjector()
        new_instance._version = self._version + 1
        return new_instance

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "registered_count": len(self.get_registered_types()),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> DependencyInjector:
        self._version += 1
        self._audit_trail.append(
            {
                "action": "TOUCH",
                "performed_by": touched_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
            }
        )
        return self

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "details": details,
            }
        )


# === 3. SINGLETON ACCESSOR ===
_dependency_injector_instance: DependencyInjector | None = None


def get_dependency_injector() -> DependencyInjector:
    global _dependency_injector_instance
    if _dependency_injector_instance is None:
        _dependency_injector_instance = DependencyInjector()
    return _dependency_injector_instance


# === 4. CONVENIENCE FUNCTIONS ===
def inject(interface: type[T]) -> T:
    return get_dependency_injector().resolve(interface)


def inject_optional(interface: type[T]) -> T | None:
    return get_dependency_injector().try_resolve(interface)


# === 5. DECORATOR FOR DEPENDENCY INJECTION ===
def autowired(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        sig = inspect.signature(func)
        bound_args = sig.bind_partial(*args, **kwargs)
        bound_args.apply_defaults()
        injector = get_dependency_injector()
        for param_name, param in sig.parameters.items():
            if (
                param_name not in bound_args.arguments
                and param.annotation != inspect.Parameter.empty
            ):
                try:
                    resolved = injector.resolve(param.annotation)
                    bound_args.arguments[param_name] = resolved
                except Exception as e:
                    logger.debug(f"Auto-inject failed for {param_name}: {e}")
        return func(*bound_args.args, **bound_args.kwargs)

    @functools.wraps(func)
    async def async_wrapper(*args, **kwargs):
        sig = inspect.signature(func)
        bound_args = sig.bind_partial(*args, **kwargs)
        bound_args.apply_defaults()
        injector = get_dependency_injector()
        for param_name, param in sig.parameters.items():
            if (
                param_name not in bound_args.arguments
                and param.annotation != inspect.Parameter.empty
            ):
                try:
                    resolved = injector.resolve(param.annotation)
                    bound_args.arguments[param_name] = resolved
                except Exception as e:
                    logger.debug(f"Auto-inject failed for {param_name}: {e}")
        return await func(*bound_args.args, **bound_args.kwargs)

    if inspect.iscoroutinefunction(func):
        return async_wrapper
    return wrapper


class Autowired:
    def __init__(self, interface: type | None = None):
        self.interface = interface
        self._instance: Any = None

    def __get__(self, instance: Any, owner: type) -> Any:
        if self._instance is not None:
            return self._instance
        interface = self.interface
        if interface is None and hasattr(owner, "__annotations__"):
            for attr_name, attr_type in owner.__annotations__.items():
                if getattr(owner, attr_name, None) is self:
                    interface = attr_type
                    break
        if interface is None:
            raise ValueError("Interface not specified and cannot be inferred")
        injector = get_dependency_injector()
        self._instance = injector.resolve(interface)
        return self._instance

    def __set_name__(self, owner: type, name: str) -> None:
        if self.interface is None and hasattr(owner, "__annotations__"):
            self.interface = owner.__annotations__.get(name)


# === 6. EXPORTS ===
__all__ = [
    "Autowired",
    "CircularDependencyError",
    "DependencyInjector",
    "ServiceNotFoundError",
    "autowired",
    "get_dependency_injector",
    "inject",
    "inject_optional",
]
