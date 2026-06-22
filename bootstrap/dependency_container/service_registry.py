#!/usr/bin/env python3
"""
Module: service_registry.py
Layer: Bootstrap (Dependency Container)
Responsibility: Registry untuk service layer (use cases, services, repositories).
"""

from __future__ import annotations

import logging
from typing import Any, TypeVar

from bootstrap.dependency_container.ioc_container import IoCContainer, Lifetime, get_container

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ServiceRegistry:
    """
    Registry untuk service layer.
    """

    def __init__(self, container: IoCContainer | None = None):
        self._container = container or get_container()
        self._services: dict[str, type] = {}
        self._aliases: dict[str, str] = {}
        self._logger = logging.getLogger(f"{__name__}.ServiceRegistry")

    def register_service(
        self,
        interface: type[T],
        implementation: type | None = None,
        lifetime: Lifetime = Lifetime.SINGLETON,
        name: str | None = None,
    ) -> None:
        if not interface:
            raise ValueError("Service interface cannot be None")
        service_name = name or interface.__name__
        self._services[service_name] = interface
        if implementation:
            self._container.register(interface, implementation, lifetime)
        else:
            self._container.register(interface, interface, lifetime)
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
        return self._container.resolve(interface, **kwargs)

    async def resolve_async(self, interface: type[T], **kwargs) -> T:
        return await self._container.resolve_async(interface, **kwargs)

    def resolve_by_name(self, name: str, **kwargs) -> Any:
        interface = self.get_service(name)
        if not interface:
            raise ValueError(f"Service not found: {name}")
        return self._container.resolve(interface, **kwargs)

    async def resolve_by_name_async(self, name: str, **kwargs) -> Any:
        interface = self.get_service(name)
        if not interface:
            raise ValueError(f"Service not found: {name}")
        return await self._container.resolve_async(interface, **kwargs)

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
        registry = ServiceRegistry()
        registry.register_service(service_interface, cls, lifetime, service_name)
        return cls
    return decorator


class ServiceRegistrar:
    """Utility to register all services at once."""

    @staticmethod
    async def register_all() -> None:
        container = get_container()

        # ==================== CORE SERVICES ====================
        from application.service_layer.service_ap import APService
        from application.service_layer.service_ar import ARService
        from application.service_layer.service_bank_cash import BankCashService
        from application.service_layer.service_coa import COAService
        from application.service_layer.service_coretax import CoretaxService
        from application.service_layer.service_fixed_asset import FixedAssetService
        from application.service_layer.service_inventory import InventoryService
        from application.service_layer.service_journal import JournalService
        from application.service_layer.service_ledger import LedgerService
        from application.service_layer.service_manufacturing import ManufacturingService
        from application.service_layer.service_payroll import PayrollService
        from application.service_layer.service_report import ReportService
        from application.service_layer.service_tax import TaxService

        container.register_singleton(JournalService, JournalService)
        container.register_singleton(LedgerService, LedgerService)
        container.register_singleton(COAService, COAService)
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

        # ==================== REPOSITORY IMPLEMENTATIONS ====================
        from adapters.secondary_impl.kafka_event_publisher_impl import KafkaEventPublisherImpl
        from adapters.secondary_impl.sqlalchemy_account_repository_impl import (
            SQLAlchemyAccountRepository,
        )
        from adapters.secondary_impl.sqlalchemy_ap_repository_impl import SQLAlchemyAPRepository
        from adapters.secondary_impl.sqlalchemy_ar_repository_impl import SQLAlchemyARRepository
        from adapters.secondary_impl.sqlalchemy_bank_cash_repository_impl import (
            SQLAlchemyBankCashRepository,
        )
        from adapters.secondary_impl.sqlalchemy_consolidation_repository_impl import (
            SQLAlchemyConsolidationRepository,
        )
        from adapters.secondary_impl.sqlalchemy_fixed_asset_repository_impl import (
            SQLAlchemyFixedAssetRepository,
        )
        from adapters.secondary_impl.sqlalchemy_forex_repository_impl import (
            SQLAlchemyForexRepository,
        )
        from adapters.secondary_impl.sqlalchemy_hedge_repository_impl import (
            SQLAlchemyHedgeRepository,
        )
        from adapters.secondary_impl.sqlalchemy_iam_user_repository_impl import (
            SQLAlchemyIAMUserRepository,
        )
        from adapters.secondary_impl.sqlalchemy_inventory_repository_impl import (
            SQLAlchemyInventoryRepository,
        )
        from adapters.secondary_impl.sqlalchemy_journal_repository_impl import (
            SQLAlchemyJournalRepository,
        )
        from adapters.secondary_impl.sqlalchemy_ledger_repository_impl import (
            SQLAlchemyLedgerRepository,
        )
        from adapters.secondary_impl.sqlalchemy_legal_entity_repository_impl import (
            SQLAlchemyLegalEntityRepository,
        )
        from adapters.secondary_impl.sqlalchemy_manufacturing_repository_impl import (
            SQLAlchemyManufacturingRepository,
        )
        from adapters.secondary_impl.sqlalchemy_outbox_repository_impl import (
            SQLAlchemyOutboxRepository,
        )
        from adapters.secondary_impl.sqlalchemy_payroll_repository_impl import (
            SQLAlchemyPayrollRepository,
        )
        from adapters.secondary_impl.sqlalchemy_system_setting_repository_impl import (
            SQLAlchemySystemSettingRepository,
        )
        from adapters.secondary_impl.sqlalchemy_tax_repository_impl import SQLAlchemyTaxRepository
        from adapters.secondary_impl.sqlalchemy_unit_of_work_impl import SQLAlchemyUnitOfWork
        from adapters.secondary_impl.tax_authority_coretax_impl import CoretaxAuthorityAdapter

        # ==================== PORT INTERFACES ====================
        from ports.primary.account_repository_port import AccountRepositoryPort
        from ports.primary.ap_repository_port import APRepositoryPort
        from ports.primary.ar_repository_port import ARRepositoryPort
        from ports.primary.bank_cash_repository_port import BankCashRepositoryPort
        from ports.primary.consolidation_repository_port import ConsolidationRepositoryPort
        from ports.primary.event_publisher_port import EventPublisherPort
        from ports.primary.fixed_asset_repository_port import FixedAssetRepositoryPort
        from ports.primary.forex_repository_port import ForexRepositoryPort
        from ports.primary.hedge_repository_port import HedgeRepositoryPort
        from ports.primary.iam_user_repository_port import IAMUserRepositoryPort
        from ports.primary.inventory_repository_port import InventoryRepositoryPort
        from ports.primary.journal_repository_port import JournalRepositoryPort
        from ports.primary.ledger_repository_port import LedgerRepositoryPort
        from ports.primary.legal_entity_repository_port import LegalEntityRepositoryPort
        from ports.primary.manufacturing_repository_port import ManufacturingRepositoryPort
        from ports.primary.outbox_repository_port import OutboxRepositoryPort
        from ports.primary.payroll_repository_port import PayrollRepositoryPort
        from ports.primary.system_setting_repository_port import SystemSettingRepositoryPort
        from ports.primary.tax_authority_coretax_port import CoreTaxPort
        from ports.primary.tax_repository_port import TaxRepositoryPort
        from ports.primary.unit_of_work_port import UnitOfWorkPort

        # ==================== REGISTER REPOSITORIES ====================
        container.register_singleton(JournalRepositoryPort, SQLAlchemyJournalRepository)
        container.register_singleton(LedgerRepositoryPort, SQLAlchemyLedgerRepository)
        container.register_singleton(AccountRepositoryPort, SQLAlchemyAccountRepository)
        container.register_singleton(ARRepositoryPort, SQLAlchemyARRepository)
        container.register_singleton(APRepositoryPort, SQLAlchemyAPRepository)
        container.register_singleton(InventoryRepositoryPort, SQLAlchemyInventoryRepository)
        container.register_singleton(FixedAssetRepositoryPort, SQLAlchemyFixedAssetRepository)
        container.register_singleton(BankCashRepositoryPort, SQLAlchemyBankCashRepository)
        container.register_singleton(TaxRepositoryPort, SQLAlchemyTaxRepository)
        container.register_singleton(LegalEntityRepositoryPort, SQLAlchemyLegalEntityRepository)
        container.register_singleton(IAMUserRepositoryPort, SQLAlchemyIAMUserRepository)
        container.register_singleton(SystemSettingRepositoryPort, SQLAlchemySystemSettingRepository)
        container.register_singleton(OutboxRepositoryPort, SQLAlchemyOutboxRepository)
        container.register_singleton(PayrollRepositoryPort, SQLAlchemyPayrollRepository)
        container.register_singleton(ManufacturingRepositoryPort, SQLAlchemyManufacturingRepository)
        container.register_singleton(ConsolidationRepositoryPort, SQLAlchemyConsolidationRepository)
        container.register_singleton(ForexRepositoryPort, SQLAlchemyForexRepository)
        container.register_singleton(HedgeRepositoryPort, SQLAlchemyHedgeRepository)
        container.register_singleton(UnitOfWorkPort, SQLAlchemyUnitOfWork)
        container.register_singleton(EventPublisherPort, KafkaEventPublisherImpl)
        container.register_singleton(CoreTaxPort, CoretaxAuthorityAdapter)

        # ==================== ALIAS UNTUK P55 ====================
        registry = ServiceRegistry()
        registry.register_alias("IJournalRepository", "JournalRepositoryPort")
        registry.register_alias("IUnitOfWork", "UnitOfWorkPort")
        registry.register_alias("IEventPublisher", "EventPublisherPort")
        registry.register_alias("ITaxAuthorityPort", "CoreTaxPort")
        registry.register_alias("IUserRepository", "IAMUserRepositoryPort")
        registry.register_alias("IAccountRepository", "AccountRepositoryPort")
        registry.register_alias("IArRepository", "ARRepositoryPort")
        registry.register_alias("IApRepository", "APRepositoryPort")
        registry.register_alias("IInventoryRepository", "InventoryRepositoryPort")
        registry.register_alias("IFixedAssetRepository", "FixedAssetRepositoryPort")
        registry.register_alias("IPayrollRepository", "PayrollRepositoryPort")
        registry.register_alias("IManufacturingRepository", "ManufacturingRepositoryPort")
        registry.register_alias("IConsolidationRepository", "ConsolidationRepositoryPort")
        registry.register_alias("IForexRepository", "ForexRepositoryPort")
        registry.register_alias("IHedgeRepository", "HedgeRepositoryPort")

        # ==================== COMMAND & QUERY BUS ====================
        from application.commands_cqrs.command_bus_unified import CommandBusUnified
        from application.commands_cqrs.query_bus_unified import QueryBusUnified

        container.register_singleton(CommandBusUnified, CommandBusUnified)
        container.register_singleton(QueryBusUnified, QueryBusUnified)

        # ==================== KERNEL ====================
        from kernel.sealed_gate import SealedGate, get_sealed_gate
        container.register_singleton(SealedGate, factory=get_sealed_gate)

        # ==================== INFRASTRUCTURE ====================
        from adapters.secondary_impl.sqlalchemy_unit_of_work_impl import get_uow_factory
        container.register_singleton("UoWFactory", factory=get_uow_factory)

        from infrastructure.caching.redis_manager import get_redis_manager
        container.register_singleton("RedisManager", factory=get_redis_manager)

        from event_gateway.event_gate_singleton import get_event_gate
        container.register_singleton("EventGate", factory=get_event_gate)

        from infrastructure.message_broker.kafka_producer_wrapper import get_kafka_producer
        container.register_singleton("KafkaProducer", factory=get_kafka_producer)

        # ==================== OUTBOX & MESSAGE BROKER ====================
        container.register_singleton("outbox_repository", SQLAlchemyOutboxRepository)
        container.register_singleton("message_broker", factory=get_kafka_producer)

        from infrastructure.message_broker.transactional_outbox_poller import get_outbox_poller
        container.register_singleton("OutboxPoller", factory=get_outbox_poller)

        logger.info("All services registered to IoC container")


_service_registry: ServiceRegistry | None = None


def get_service_registry() -> ServiceRegistry:
    global _service_registry
    if _service_registry is None:
        _service_registry = ServiceRegistry()
    return _service_registry


__all__ = [
    "ServiceRegistrar",
    "ServiceRegistry",
    "get_service_registry",
    "service",
]
