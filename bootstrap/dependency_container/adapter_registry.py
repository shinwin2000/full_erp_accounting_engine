#!/usr/bin/env python3
"""
Module: adapter_registry.py
Layer: Bootstrap (Dependency Container)
"""

from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bootstrap.dependency_container.interfaces import ContainerInterface

from bootstrap.dependency_container.auto_register_ports import register_all_ports

logger = logging.getLogger(__name__)


class AdapterRegistry:
    def __init__(self, container: ContainerInterface | None = None):
        self._container = container
        self._adapters: dict[str, type] = {}
        self._logger = logging.getLogger(f"{__name__}.AdapterRegistry")
        self._is_registered = False

    def set_container(self, container: ContainerInterface) -> None:
        self._container = container

    def register_all(self) -> None:
        if self._is_registered:
            self._logger.debug("Adapter registration already completed. Skipping redundant scan.")
            return

        if self._container is None:
            raise RuntimeError("Container not set. Call set_container() first.")

        self._logger.info("Starting adapter registration via auto-discover...")

        registered, fallback = register_all_ports(self._container)

        self._logger.info(
            f"Auto-registered {len(registered)} ports with real implementations, "
            f"{len(fallback)} using in-memory fallback"
        )

        # Manual registrations
        self._manual_register_customer_supplier()
        self._manual_register_core_tax()

        # Named adapters
        for reg in self._container.get_registered_types():
            if hasattr(reg, "__name__"):
                name = reg.__name__.lower()
                if "repository" in name or "port" in name:
                    self._adapters[name] = reg

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

    def _manual_register_customer_supplier(self) -> None:
        try:
            CustomerRepositoryPort = self._import_port_class("ports.primary.customer_repository_port")
            SupplierRepositoryPort = self._import_port_class("ports.primary.customer_supplier_repository_port")
            SQLAlchemyCustomerRepository = self._import_impl_class(
                "adapters.secondary_impl.sqlalchemy_customer_repository_impl",
                "SQLAlchemyCustomerRepository"
            )
            SQLAlchemySupplierRepository = self._import_impl_class(
                "adapters.secondary_impl.sqlalchemy_supplier_repository_impl",
                "SQLAlchemySupplierRepository"
            )

            if CustomerRepositoryPort and SQLAlchemyCustomerRepository:
                if not self._container.has_registration(CustomerRepositoryPort):
                    self._container.register_singleton(CustomerRepositoryPort, SQLAlchemyCustomerRepository)
                    self._logger.info("Manually registered CustomerRepositoryPort -> SQLAlchemyCustomerRepository")

            if SupplierRepositoryPort and SQLAlchemySupplierRepository:
                if not self._container.has_registration(SupplierRepositoryPort):
                    self._container.register_singleton(SupplierRepositoryPort, SQLAlchemySupplierRepository)
                    self._logger.info("Manually registered SupplierRepositoryPort -> SQLAlchemySupplierRepository")
        except Exception as e:
            self._logger.warning(f"Manual registration Customer/Supplier failed: {e}")

    def _manual_register_core_tax(self) -> None:
        try:
            CoreTaxPort = self._import_port_class("ports.primary.core_tax_port")
            TaxAuthorityCoretaxAdapter = self._import_impl_class(
                "adapters.secondary_impl.tax_authority_coretax_adapter",
                "TaxAuthorityCoretaxAdapter"
            )
            if CoreTaxPort and TaxAuthorityCoretaxAdapter:
                if self._container.has_registration(CoreTaxPort) and hasattr(self._container, "remove"):
                    self._container.remove(CoreTaxPort)
                self._container.register_singleton(CoreTaxPort, TaxAuthorityCoretaxAdapter)
                self._logger.info("Manually registered CoreTaxPort -> TaxAuthorityCoretaxAdapter")
        except Exception as e:
            self._logger.warning(f"Manual registration CoreTax failed: {e}")

    def _import_port_class(self, module_path: str, class_name: str | None = None) -> type | None:
        try:
            mod = importlib.import_module(module_path)
            if class_name:
                return getattr(mod, class_name, None)
            for attr in dir(mod):
                if attr.endswith("Port"):
                    return getattr(mod, attr)
            return None
        except ImportError:
            return None

    def _import_impl_class(self, module_path: str, class_name: str) -> type | None:
        try:
            mod = importlib.import_module(module_path)
            return getattr(mod, class_name, None)
        except ImportError:
            return None

    def register(self, name: str, interface: type, implementation: type | None = None) -> None:
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
            return False
        interface = self._adapters.pop(name)
        if self._container and hasattr(self._container, "remove"):
            self._container.remove(interface)
        self._logger.info(f"Unregistered adapter: {name}")
        return True

    def get_adapter_interface(self, name: str) -> type | None:
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


_adapter_registry: AdapterRegistry | None = None


def set_adapter_registry_instance(registry: AdapterRegistry) -> None:
    global _adapter_registry
    _adapter_registry = registry


def get_adapter_registry() -> AdapterRegistry:
    global _adapter_registry
    if _adapter_registry is None:
        from bootstrap.dependency_container.ioc_container import get_container
        container = get_container()
        registry = AdapterRegistry(container)
        _adapter_registry = registry
        registry.register_all()
    return _adapter_registry


async def get_uow() -> Any:
    registry = get_adapter_registry()
    return await registry.resolve_async("unit_of_work")


__all__ = [
    "AdapterRegistry",
    "get_adapter_registry",
    "get_uow",
    "set_adapter_registry_instance",
]