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
from typing import Any, TypeVar, Union, get_args, get_origin, get_type_hints

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

    def _resolve_key_by_name(self, name: str) -> type | str | None:
        """Cari key terdaftar di registry (container ini atau parent) yang
        __name__ class-nya cocok dengan string nama tipe. Dipakai sebagai
        fallback terakhir kalau get_type_hints() tidak bisa resolve suatu
        anotasi (mis. karena tipe itu hanya diimpor di bawah
        `if TYPE_CHECKING:`, pola umum untuk menghindari circular import —
        di runtime nama itu tidak pernah benar-benar ada di namespace
        modul, jadi tidak bisa dievaluasi jadi objek class)."""
        container: IoCContainer | None = self
        while container is not None:
            for key in container._registrations:
                if isinstance(key, type) and key.__name__ == name:
                    return key
            container = container._parent
        return None

    async def _construct_with_injection(self, cls: type, **kwargs) -> Any:
        sig = inspect.signature(cls.__init__)

        # PENTING: banyak modul di proyek ini pakai
        # `from __future__ import annotations` (PEP 563), yang membuat
        # SEMUA anotasi tipe di constructor jadi string mentah (mis.
        # "ARRepositoryPort") alih-alih objek class asli. `param.annotation`
        # di bawah akan mengembalikan string itu apa adanya, sedangkan
        # port didaftarkan di registry pakai objek class sebagai key —
        # dua hal berbeda sebagai dict key walau namanya identik, jadi
        # resolve akan selalu gagal (DependencyNotFoundError) walau
        # port-nya sudah benar terdaftar.
        #
        # `typing.get_type_hints()` mengevaluasi string anotasi itu balik
        # jadi objek class asli menggunakan namespace modul tempat cls
        # didefinisikan, jadi ini dipakai sebagai sumber utama tipe param.
        #
        # CATATAN TAMBAHAN: get_type_hints() sifatnya all-or-nothing — kalau
        # SATU SAJA anotasi di constructor tidak bisa dievaluasi (mis. tipe
        # yang diimpor hanya di bawah `if TYPE_CHECKING:`, jadi tidak ada
        # di namespace modul saat runtime), seluruh pemanggilan gagal dengan
        # NameError, bukan cuma parameter itu. Kalau ini terjadi, kita fallback
        # ke pencarian berdasarkan nama string di registry
        # (_resolve_key_by_name) per-parameter, alih-alih menyerah total.
        try:
            type_hints = get_type_hints(cls.__init__)
        except Exception as e:
            logger.debug(
                f"get_type_hints gagal untuk {cls.__module__}.{cls.__name__}.__init__: {e} "
                "(kemungkinan ada tipe yang cuma diimpor di bawah TYPE_CHECKING). "
                "Fallback ke resolve per-parameter berdasarkan nama string."
            )
            type_hints = {}

        parameters = {}
        for name, param in sig.parameters.items():
            if name == "self":
                continue
            if name in kwargs:
                parameters[name] = kwargs[name]
                continue

            param_type = type_hints.get(name, param.annotation)

            # Fallback tambahan: kalau param_type masih berupa string
            # (get_type_hints gagal total atau parameter ini tidak ada di
            # hasilnya), cari key terdaftar di registry yang __name__-nya
            # cocok. Ini menangani kasus tipe yang cuma diimpor di bawah
            # `if TYPE_CHECKING:` seperti ARRepositoryPort di service_ap.py.
            if isinstance(param_type, str):
                resolved_key = self._resolve_key_by_name(param_type)
                if resolved_key is not None:
                    param_type = resolved_key

            # Unwrap Optional[X] / X | None -> X, supaya tetap bisa resolve
            # ke tipe konkretnya. Kalau X sendiri juga tidak terdaftar,
            # tetap fallback ke default lewat except di bawah seperti biasa
            # (mis. `session: AsyncSession | None = None` tetap jatuh ke
            # default None, bukan salah resolve).
            origin = get_origin(param_type)
            if origin is Union:
                non_none_args = [a for a in get_args(param_type) if a is not type(None)]
                if len(non_none_args) == 1:
                    param_type = non_none_args[0]

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
    "clear_request_container",
    "get_container",
    "get_request_container",
    "injectable",
]