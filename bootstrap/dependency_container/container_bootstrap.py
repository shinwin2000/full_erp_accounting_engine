#!/usr/bin/env python3
"""
Module: container_bootstrap.py
Layer: Bootstrap (Dependency Container)

Orchestration for initializing the global container.
"""

from __future__ import annotations

import asyncio
import logging

from bootstrap.dependency_container.adapter_registry import (
    AdapterRegistry,
    set_adapter_registry_instance,
)
from bootstrap.dependency_container.ioc_container import IoCContainer, get_container
from bootstrap.dependency_container.service_registry import ServiceRegistrar

logger = logging.getLogger(__name__)


def initialize_container() -> None:
    """
    Initialize the global container with all registrations.
    This should be called once at application startup.
    """
    container = get_container()

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


__all__ = [
    "build_container",
    "initialize_container",
]
