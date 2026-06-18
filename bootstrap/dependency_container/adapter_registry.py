#!/usr/bin/env python3
"""
Module: adapter_registry.py
Layer: Bootstrap (Dependency Container)
Responsibility: Registry untuk adapter (primary dan secondary) yang digunakan
               dalam arsitektur hexagonal. Mendaftarkan adapter ke IoC container
               untuk dependency injection.
"""

from __future__ import annotations

import logging
from typing import Any

from adapters.coretax_djp.api_oauth2_client import CoretaxOAuth2Client
from adapters.coretax_djp.nsfp_manager import NSFPManager
from adapters.secondary_impl.bank_mt940_parser_adapter import BankMT940ParserAdapter
from adapters.secondary_impl.email_smtp_notification import EmailSMTPNotification
from adapters.secondary_impl.kafka_event_publisher_impl import KafkaEventPublisherImpl
from adapters.secondary_impl.s3_file_storage_adapter_impl import S3FileStorageAdapterImpl
from adapters.secondary_impl.sqlalchemy_unit_of_work_impl import SQLAlchemyUnitOfWork

from bootstrap.dependency_container.ioc_container import IoCContainer, get_container
from ports.primary.bank_statement_import_port import BankStatementImportPort
from ports.primary.encryption_key_vault_port import EncryptionKeyVaultPort
from ports.primary.event_publisher_port import EventPublisherPort
from ports.primary.file_storage_port import FileStoragePort
from ports.primary.hash_chain_service_port import HashChainServicePort
from ports.primary.notification_port import NotificationPort
from ports.primary.tax_authority_coretax_port import CoreTaxPort
from ports.primary.timestamp_notary_port import TimestampNotaryPort
from ports.primary.unit_of_work_port import UnitOfWorkPort
from ports.secondary.analytics_export_port import AnalyticsExportPort
from ports.secondary.cqrs_query_handler_port import CQRSQueryHandlerPort
from ports.secondary.read_model_projection_port import ReadModelProjectionPort
from ports.secondary.snapshot_store_port import SnapshotStorePort

logger = logging.getLogger(__name__)


class AdapterRegistry:
    """
    Registry untuk adapter.

    Method Standards (ERP):
    - register_all() - Mendaftarkan semua adapter
    - register() - Mendaftarkan adapter tunggal
    - unregister() - Menghapus adapter
    - resolve() - Mendapatkan adapter instance (sync)
    - resolve_async() - Mendapatkan adapter instance (async)
    - get_adapter_interface() - Mendapatkan interface adapter
    - list_adapters() - Mendaftar semua adapter
    - has_adapter() - Cek ketersediaan adapter
    - reset() - Reset registry
    """

    def __init__(self, container: IoCContainer | None = None):
        self._container = container or get_container()
        self._adapters: dict[str, type] = {}
        self._logger = logging.getLogger(f"{__name__}.AdapterRegistry")

    def register_all(self) -> None:
        """Register all adapters to the container."""
        # Secondary adapters
        self._container.register_singleton(UnitOfWorkPort, SQLAlchemyUnitOfWork)
        self._container.register_singleton(EventPublisherPort, KafkaEventPublisherImpl)
        self._container.register_singleton(NotificationPort, EmailSMTPNotification)
        self._container.register_singleton(FileStoragePort, S3FileStorageAdapterImpl)
        self._container.register_singleton(BankStatementImportPort, BankMT940ParserAdapter)
        self._container.register_singleton(CoreTaxPort, CoretaxOAuth2Client)
        self._container.register_singleton(HashChainServicePort)
        self._container.register_singleton(TimestampNotaryPort)
        self._container.register_singleton(EncryptionKeyVaultPort)

        # Secondary ports (query side)
        self._container.register_singleton(ReadModelProjectionPort)
        self._container.register_singleton(SnapshotStorePort)
        self._container.register_singleton(CQRSQueryHandlerPort)
        self._container.register_singleton(AnalyticsExportPort)

        # Named adapters for lookup
        self._adapters["unit_of_work"] = UnitOfWorkPort
        self._adapters["event_publisher"] = EventPublisherPort
        self._adapters["notification"] = NotificationPort
        self._adapters["file_storage"] = FileStoragePort
        self._adapters["bank_statement_import"] = BankStatementImportPort
        self._adapters["coretax"] = CoreTaxPort
        self._adapters["hash_chain"] = HashChainServicePort
        self._adapters["timestamp_notary"] = TimestampNotaryPort
        self._adapters["encryption_vault"] = EncryptionKeyVaultPort
        self._adapters["read_model_projection"] = ReadModelProjectionPort
        self._adapters["snapshot_store"] = SnapshotStorePort
        self._adapters["cqrs_query_handler"] = CQRSQueryHandlerPort
        self._adapters["analytics_export"] = AnalyticsExportPort

        # Coretax specific adapters
        self._container.register_singleton("CoretaxClient", CoretaxOAuth2Client)
        self._container.register_singleton("NSFPManager", NSFPManager)

        self._adapters["coretax_client"] = CoretaxOAuth2Client
        self._adapters["nsfp_manager"] = NSFPManager

        self._logger.info(f"Registered {len(self._adapters)} adapters")

    def register(self, name: str, interface: type, implementation: type | None = None) -> None:
        """
        Register a single adapter.

        Args:
            name: Adapter name
            interface: Interface to register
            implementation: Implementation class (optional)
        """
        if not name:
            raise ValueError("Adapter name cannot be empty")
        if not interface:
            raise ValueError("Adapter interface cannot be None")

        if implementation:
            self._container.register_singleton(interface, implementation)
        else:
            self._container.register_singleton(interface)

        self._adapters[name] = interface
        self._logger.info(f"Registered adapter: {name} -> {interface.__name__}")

    def unregister(self, name: str) -> bool:
        """
        Unregister an adapter.

        Args:
            name: Adapter name

        Returns:
            True if unregistered, False if not found
        """
        if name not in self._adapters:
            self._logger.warning(f"Adapter not found for unregister: {name}")
            return False

        interface = self._adapters.pop(name)
        # Remove from container (implementation detail)
        if interface in self._container._registrations:
            del self._container._registrations[interface]
        self._logger.info(f"Unregistered adapter: {name}")
        return True

    def get_adapter_interface(self, name: str) -> type | None:
        """Get adapter interface by name."""
        if not name:
            raise ValueError("Adapter name cannot be empty")
        return self._adapters.get(name)

    def resolve(self, name: str, **kwargs) -> Any:
        """Resolve adapter by name (sync)."""
        interface = self.get_adapter_interface(name)
        if not interface:
            raise ValueError(f"Adapter not found: {name}")
        return self._container.resolve(interface, **kwargs)

    async def resolve_async(self, name: str, **kwargs) -> Any:
        """Resolve adapter asynchronously by name."""
        interface = self.get_adapter_interface(name)
        if not interface:
            raise ValueError(f"Adapter not found: {name}")
        return await self._container.resolve_async(interface, **kwargs)

    def list_adapters(self) -> list[str]:
        """List all registered adapter names."""
        return sorted(self._adapters.keys())

    def has_adapter(self, name: str) -> bool:
        """Check if adapter exists."""
        return name in self._adapters

    def reset(self) -> None:
        """Reset registry (clear all adapters)."""
        self._adapters.clear()
        self._logger.info("Adapter registry reset")


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_adapter_registry: AdapterRegistry | None = None


def get_adapter_registry() -> AdapterRegistry:
    """Get singleton instance of AdapterRegistry."""
    global _adapter_registry
    if _adapter_registry is None:
        _adapter_registry = AdapterRegistry()
        _adapter_registry.register_all()
    return _adapter_registry


async def get_uow() -> UnitOfWorkPort:
    """Get Unit of Work adapter for FastAPI dependency."""
    registry = get_adapter_registry()
    return await registry.resolve_async("unit_of_work")


__all__ = [
    "AdapterRegistry",
    "get_adapter_registry",
    "get_uow",
]