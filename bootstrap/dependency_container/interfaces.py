#!/usr/bin/env python3
"""
Module: interfaces.py
Layer: Bootstrap (Dependency Container)
Responsibility: Mendefinisikan interface abstrak untuk container dan komponen terkait,
               untuk memutus dependensi sirkular antara adapter_registry, service_registry,
               dan ioc_container.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypeVar

T = TypeVar("T")


class ContainerInterface(ABC):
    """Interface abstrak untuk IoC container."""

    @abstractmethod
    def resolve(self, interface: type[T] | str, **kwargs) -> T:
        pass

    @abstractmethod
    async def resolve_async(self, interface: type[T] | str, **kwargs) -> T:
        pass

    @abstractmethod
    def register(self, interface: type[T] | str, implementation: type | None = None, **kwargs) -> None:
        pass

    @abstractmethod
    def register_singleton(self, interface: type[T] | str, implementation: type | None = None, **kwargs) -> None:
        pass

    @abstractmethod
    def has_registration(self, interface: type | str) -> bool:
        pass

    @abstractmethod
    def get_registered_types(self) -> list[type | str]:
        pass


class RegistryInterface(ABC):
    """Interface abstrak untuk registry (adapter atau service)."""

    @abstractmethod
    def register_all(self) -> None:
        pass

    @abstractmethod
    def list_entries(self) -> list[str]:
        pass
