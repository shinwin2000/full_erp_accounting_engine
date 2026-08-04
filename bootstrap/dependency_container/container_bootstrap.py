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
    # FIX: sebelumnya, jika dipanggil dari dalam running event loop,
    # `loop.create_task(...)` hanya MENJADWALKAN coroutine tanpa menunggunya
    # selesai (fire-and-forget). Akibatnya initialize_container() bisa return
    # SEBELUM ServiceRegistrar.register_all() benar-benar selesai mendaftarkan
    # service, menyebabkan DependencyNotFoundError yang intermiten (race
    # condition) pada request pertama setelah startup.
    try:
        asyncio.get_running_loop()
        running_in_loop = True
    except RuntimeError:
        running_in_loop = False

    if running_in_loop:
        # Tidak bisa memakai asyncio.run() di dalam loop yang sudah berjalan,
        # dan initialize_container() ini sendiri bukan fungsi async (tidak bisa
        # di-`await`). Sebagai gantinya kita jalankan registrasi secara blocking
        # lewat thread terpisah dengan event loop barunya sendiri, supaya
        # register_all() benar-benar SELESAI sebelum initialize_container()
        # return (bukan fire-and-forget seperti sebelumnya).
        # Catatan: pemanggil yang sudah berada di dalam coroutine async
        # sebaiknya memanggil `await ServiceRegistrar.register_all(container)`
        # secara langsung (seperti yang dilakukan app/main.py) daripada lewat
        # initialize_container() ini.
        import concurrent.futures

        def _run_in_new_loop() -> None:
            new_loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(new_loop)
                new_loop.run_until_complete(ServiceRegistrar.register_all(container))
            finally:
                new_loop.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(_run_in_new_loop).result()
    else:
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
