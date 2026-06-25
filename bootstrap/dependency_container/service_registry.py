#!/usr/bin/env python3
"""
Module: service_registry.py
Layer: Bootstrap (Dependency Container)
Responsibility: Registry khusus untuk APPLICATION SERVICES.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from bootstrap.dependency_container.interfaces import ContainerInterface

from bootstrap.dependency_container.ioc_container import Lifetime  # enum tidak menyebabkan siklus

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ServiceRegistry:
    """
    Registry untuk application services.
    """

    def __init__(self, container: ContainerInterface | None = None):
        # Hindari import sirkular: jika container None, kita akan set nanti
        self._container = container
        self._services: dict[str, type] = {}
        self._aliases: dict[str, str] = {}
        self._logger = logging.getLogger(f"{__name__}.ServiceRegistry")

    def set_container(self, container: ContainerInterface) -> None:
        self._container = container

    def register_service(
        self,
        interface: type[T],
        implementation: type | None = None,
        lifetime: Lifetime = Lifetime.SINGLETON,
        name: str | None = None,
    ) -> None:
        if not interface:
            raise ValueError("Service interface cannot be None")
        if self._container is None:
            raise RuntimeError("Container not set. Call set_container() first.")
        service_name = name or interface.__name__
        self._services[service_name] = interface
        if implementation:
            self._container.register(interface, implementation, lifetime=lifetime)
        else:
            self._container.register(interface, interface, lifetime=lifetime)
        self._logger.info(f"Registered service: {service_name}")

    def register_alias(self, alias: str, target: str) -> None:
        if not alias or not target:
            raise ValueError("Alias and target cannot be empty")
        self._aliases[alias] = target
        self._logger.debug(f"Registered alias: {alias} -> {target}")

    def get_service(self, service_name: str) -> type | None:
        if not service_name:
            raise ValueError("Service name cannot be empty")
        if service_name in self._aliases:
            service_name = self._aliases[service_name]
        return self._services.get(service_name)

    def resolve(self, interface: type[T], **kwargs) -> T:
        if self._container is None:
            raise RuntimeError("Container not set.")
        return self._container.resolve(interface, **kwargs)

    async def resolve_async(self, interface: type[T], **kwargs) -> T:
        if self._container is None:
            raise RuntimeError("Container not set.")
        return await self._container.resolve_async(interface, **kwargs)

    def resolve_by_name(self, name: str, **kwargs) -> Any:
        interface = self.get_service(name)
        if not interface:
            raise ValueError(f"Service not found: {name}")
        return self.resolve(interface, **kwargs)

    async def resolve_by_name_async(self, name: str, **kwargs) -> Any:
        interface = self.get_service(name)
        if not interface:
            raise ValueError(f"Service not found: {name}")
        return await self.resolve_async(interface, **kwargs)

    def list_services(self) -> list[str]:
        return sorted(self._services.keys())

    def has_service(self, service_name: str) -> bool:
        return service_name in self._services or service_name in self._aliases

    def unregister(self, service_name: str) -> bool:
        if service_name in self._services:
            del self._services[service_name]
            self._logger.debug(f"Unregistered service: {service_name}")
            return True
        if service_name in self._aliases:
            del self._aliases[service_name]
            self._logger.debug(f"Unregistered alias: {service_name}")
            return True
        return False

    def reset(self) -> None:
        self._services.clear()
        self._aliases.clear()
        self._logger.info("Service registry reset")


def service(
    interface: type | None = None,
    name: str | None = None,
    lifetime: Lifetime = Lifetime.SINGLETON,
):
    def decorator(cls):
        service_name = name or cls.__name__
        service_interface = interface or cls
        registry = ServiceRegistry()  # container akan di-set nanti di register_all
        registry.register_service(service_interface, cls, lifetime, service_name)
        return cls
    return decorator


class ServiceRegistrar:
    """
    Registrasi semua application services.
    """

    @staticmethod
    async def register_all(container: ContainerInterface | None = None) -> None:
        # Jika container None, ambil dari get_container (lazy import)
        if container is None:
            from bootstrap.dependency_container.ioc_container import get_container
            container = get_container()

        # Buat ServiceRegistry dan set container
        registry = ServiceRegistry(container)

        # ==================== APPLICATION SERVICES ====================
        try:
            from application.service_layer.service_coa import COAService
            from application.service_layer.service_journal import JournalService
            from application.service_layer.service_ledger import LedgerService
            from application.service_layer.service_ar import ARService
            from application.service_layer.service_ap import APService
            from application.service_layer.service_inventory import InventoryService
            from application.service_layer.service_fixed_asset import FixedAssetService
            from application.service_layer.service_bank_cash import BankCashService
            from application.service_layer.service_tax import TaxService
            from application.service_layer.service_coretax import CoretaxService
            from application.service_layer.service_payroll import PayrollService
            from application.service_layer.service_manufacturing import ManufacturingService
            from application.service_layer.service_report import ReportService

            container.register_singleton(COAService, COAService)
            container.register_singleton(JournalService, JournalService)
            container.register_singleton(LedgerService, LedgerService)
            container.register_singleton(ARService, ARService)
            container.register_singleton(APService, APService)
            container.register_singleton(InventoryService, InventoryService)
            container.register_singleton(FixedAssetService, FixedAssetService)
            container.register_singleton(BankCashService, BankCashService)
            container.register_singleton(TaxService, TaxService)
            container.register_singleton(CoretaxService, CoretaxService)
            container.register_singleton(PayrollService, PayrollService)
            container.register_singleton(ManufacturingService, ManufacturingService)
            container.register_singleton(ReportService, ReportService)
            logger.info("Application services registered")
        except ImportError as e:
            logger.warning(f"Some application services could not be imported: {e}")

        # ==================== COMMAND & QUERY BUS ====================
        try:
            from application.commands_cqrs.command_bus_unified import CommandBusUnified
            from application.commands_cqrs.query_bus_unified import QueryBusUnified
            container.register_singleton(CommandBusUnified, CommandBusUnified)
            container.register_singleton(QueryBusUnified, QueryBusUnified)
            logger.info("Command/Query buses registered")
        except ImportError as e:
            logger.warning(f"CQRS buses not available: {e}")

        # ... (lanjutkan dengan kernel, factories, dll. sama seperti sebelumnya)
        # ==================== KERNEL SINGLETONS ====================
        try:
            gate_mod = importlib.import_module("kernel.sealed_gate")
            SealedGate = getattr(gate_mod, "SealedGate")
            get_sealed_gate = getattr(gate_mod, "get_sealed_gate")
            container.register_singleton(SealedGate, factory=get_sealed_gate)
            logger.info("Kernel singletons registered")
        except ImportError as e:
            logger.warning(f"Kernel singletons not available: {e}")

        # ==================== INFRASTRUCTURE FACTORIES ====================
        try:
            from adapters.secondary_impl.sqlalchemy_unit_of_work_impl import get_uow_factory
            container.register_singleton("UoWFactory", factory=get_uow_factory)
        except ImportError:
            pass

        try:
            from infrastructure.caching.redis_manager import get_redis_manager
            container.register_singleton("RedisManager", factory=get_redis_manager)
        except ImportError:
            pass

        try:
            gate_mod = importlib.import_module("event_gateway.event_gate_singleton")
            get_event_gate = getattr(gate_mod, "get_event_gate")
            container.register_singleton("EventGate", factory=get_event_gate)
        except ImportError:
            pass

        try:
            from infrastructure.message_broker.kafka_producer_wrapper import get_kafka_producer
            container.register_singleton("KafkaProducer", factory=get_kafka_producer)
        except ImportError:
            pass

        try:
            from infrastructure.message_broker.transactional_outbox_poller import get_outbox_poller
            container.register_singleton("OutboxPoller", factory=get_outbox_poller)
        except ImportError:
            pass

        logger.info("All application services registered to IoC container")

    @staticmethod
    def register_all_sync() -> None:
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(ServiceRegistrar.register_all())
            loop.close()
        except Exception as e:
            logger.error(f"Service registration failed: {e}")
            raise


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_service_registry: ServiceRegistry | None = None


def get_service_registry() -> ServiceRegistry:
    global _service_registry
    if _service_registry is None:
        # Lazy import untuk menghindari siklus
        from bootstrap.dependency_container.ioc_container import get_container
        _service_registry = ServiceRegistry(get_container())
    return _service_registry


__all__ = [
    "ServiceRegistrar",
    "ServiceRegistry",
    "get_service_registry",
    "service",
]