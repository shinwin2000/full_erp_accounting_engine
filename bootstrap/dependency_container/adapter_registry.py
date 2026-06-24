#!/usr/bin/env python3
"""
Module: adapter_registry.py
Layer: Bootstrap (Dependency Container)
Responsibility: Registry untuk semua adapter (primary dan secondary).
               Menggunakan auto-discovery untuk mendaftarkan semua port
               yang ditemukan di ports/primary dan ports/secondary.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from bootstrap.dependency_container.ioc_container import IoCContainer

logger = logging.getLogger(__name__)


class AdapterRegistry:
    """
    Registry untuk adapter. Menggunakan auto_register_ports untuk
    mendaftarkan semua port yang ditemukan.
    """

    def __init__(self, container: Optional[IoCContainer] = None):
        self._container = container
        self._adapters: dict[str, type] = {}
        self._logger = logging.getLogger(f"{__name__}.AdapterRegistry")
        self._is_registered = False  # Idempotency flag

    def set_container(self, container: IoCContainer) -> None:
        """Set container after instantiation."""
        self._container = container

    def register_all(self) -> None:
        """Register semua adapter yang tersedia ke container menggunakan auto-discover."""
        # Cegah double scan
        if self._is_registered:
            self._logger.debug("Adapter registration already completed. Skipping redundant scan.")
            return

        if self._container is None:
            raise RuntimeError("Container not set. Call set_container() first.")

        self._logger.info("Starting adapter registration via auto-discover...")

        from bootstrap.dependency_container.auto_register_ports import register_all_ports

        registered, fallback = register_all_ports(self._container)

        self._logger.info(
            f"Auto-registered {len(registered)} ports with real implementations, "
            f"{len(fallback)} using in-memory fallback"
        )

        # ============================================================
        # 2. NAMED ADAPTERS (untuk lookup by name)
        # ============================================================
        for reg in self._container.get_registered_types():
            if hasattr(reg, "__name__"):
                name = reg.__name__.lower()
                if "repository" in name or "port" in name:
                    self._adapters[name] = reg

        # Tambahkan alias untuk kemudahan
        named_aliases = {
            "unit_of_work": "UnitOfWorkPort",
            "event_publisher": "EventPublisherPort",
            "coretax": "CoreTaxPort",
            "journal": "JournalRepositoryPort",
            "ar": "ARRepositoryPort",
            "ap": "APRepositoryPort",
            "inventory": "InventoryRepositoryPort",
            "fixed_asset": "FixedAssetRepositoryPort",
            "payroll": "PayrollRepositoryPort",
            "manufacturing": "ManufacturingRepositoryPort",
        }
        for alias, port_name in named_aliases.items():
            port_class = None
            for reg in self._container.get_registered_types():
                if hasattr(reg, "__name__") and reg.__name__ == port_name:
                    port_class = reg
                    break
            if port_class:
                self._adapters[alias] = port_class

        self._logger.info(f"Registered {len(self._adapters)} named adapter interfaces")
        self._is_registered = True

    # ================================================================
    # METODE LAINNYA (register, unregister, resolve, dll.)
    # ================================================================

    def register(self, name: str, interface: type, implementation: type | None = None) -> None:
        if not name:
            raise ValueError("Adapter name cannot be empty")
        if not interface:
            raise ValueError("Adapter interface cannot be None")
        if self._container is None:
            raise RuntimeError("Container not set.")

        if implementation:
            self._container.register_singleton(interface, implementation)
        else:
            self._container.register_singleton(interface)

        self._adapters[name] = interface
        self._logger.info(f"Registered adapter: {name} -> {interface.__name__}")

    def unregister(self, name: str) -> bool:
        if name not in self._adapters:
            self._logger.warning(f"Adapter not found for unregister: {name}")
            return False

        interface = self._adapters.pop(name)
        if self._container and interface in self._container._registrations:
            del self._container._registrations[interface]
        self._logger.info(f"Unregistered adapter: {name}")
        return True

    def get_adapter_interface(self, name: str) -> type | None:
        if not name:
            raise ValueError("Adapter name cannot be empty")
        return self._adapters.get(name)

    def resolve(self, name: str, **kwargs) -> Any:
        interface = self.get_adapter_interface(name)
        if not interface:
            raise ValueError(f"Adapter not found: {name}")
        if self._container is None:
            raise RuntimeError("Container not set.")
        return self._container.resolve(interface, **kwargs)

    async def resolve_async(self, name: str, **kwargs) -> Any:
        interface = self.get_adapter_interface(name)
        if not interface:
            raise ValueError(f"Adapter not found: {name}")
        if self._container is None:
            raise RuntimeError("Container not set.")
        return await self._container.resolve_async(interface, **kwargs)

    def list_adapters(self) -> list[str]:
        return sorted(self._adapters.keys())

    def has_adapter(self, name: str) -> bool:
        return name in self._adapters

    def reset(self) -> None:
        self._adapters.clear()
        self._is_registered = False
        self._logger.info("Adapter registry reset")


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_adapter_registry: AdapterRegistry | None = None


def set_adapter_registry_instance(registry: AdapterRegistry) -> None:
    """Set the singleton registry instance (used by ioc_container to avoid recursion)."""
    global _adapter_registry
    _adapter_registry = registry


def get_adapter_registry() -> AdapterRegistry:
    """
    Get the singleton AdapterRegistry. If not initialized, it will be created
    and initialized with the global container.
    """
    global _adapter_registry
    if _adapter_registry is None:
        # Import inside to avoid circular import at module level
        from bootstrap.dependency_container.ioc_container import get_container
        container = get_container()  # This will initialize the registry and set _adapter_registry
        # After get_container() returns, _adapter_registry should not be None
        if _adapter_registry is None:
            raise RuntimeError("Failed to initialize adapter registry")
    return _adapter_registry


async def get_uow() -> Any:
    registry = get_adapter_registry()
    return await registry.resolve_async("unit_of_work")


__all__ = [
    "AdapterRegistry",
    "set_adapter_registry_instance",
    "get_adapter_registry",
    "get_uow",
]