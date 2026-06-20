#!/usr/bin/env python3
"""
Module: adapter_registry.py
Layer: Bootstrap (Dependency Container)
Responsibility: Registry untuk adapter (primary dan secondary) yang digunakan
               dalam arsitektur hexagonal. Mendaftarkan adapter ke IoC container
               untuk dependency injection menggunakan lazy imports.
"""

from __future__ import annotations

import logging
from typing import Any

from bootstrap.dependency_container.ioc_container import IoCContainer, get_container

# ============================================================================
# IMPOR PORT (INTERFACES)
# ============================================================================
from ports.primary.account_repository_port import AccountRepositoryPort
from ports.primary.ap_repository_port import APRepositoryPort
from ports.primary.approval_repository_port import ApprovalRepositoryPort
from ports.primary.ar_repository_port import ARRepositoryPort
from ports.primary.bank_cash_repository_port import BankCashRepositoryPort
from ports.primary.bank_statement_import_port import BankStatementImportPort
from ports.primary.budget_repository_port import BudgetRepositoryPort
from ports.primary.consolidation_repository_port import ConsolidationRepositoryPort
from ports.primary.customer_repository_port import CustomerRepositoryPort
from ports.primary.employee_repository_port import EmployeeRepositoryPort
from ports.primary.encryption_key_vault_port import EncryptionKeyVaultPort
from ports.primary.event_publisher_port import EventPublisherPort
from ports.primary.file_storage_port import FileStoragePort
from ports.primary.fiscal_period_repository_port import FiscalPeriodRepositoryPort
from ports.primary.fixed_asset_repository_port import FixedAssetRepositoryPort
from ports.primary.forex_repository_port import ForexRepositoryPort
from ports.primary.goods_receipt_repository_port import GoodsReceiptRepositoryPort
from ports.primary.goodwill_repository_port import GoodwillRepositoryPort
from ports.primary.hash_chain_service_port import HashChainServicePort
from ports.primary.hedge_repository_port import HedgeRepositoryPort
from ports.primary.iam_user_repository_port import IAMUserRepositoryPort
from ports.primary.intangible_asset_repository_port import IntangibleAssetRepositoryPort
from ports.primary.inventory_repository_port import InventoryRepositoryPort
from ports.primary.journal_repository_port import JournalRepositoryPort
from ports.primary.ledger_repository_port import LedgerRepositoryPort
from ports.primary.legal_entity_repository_port import LegalEntityRepositoryPort
from ports.primary.manufacturing_repository_port import ManufacturingRepositoryPort
from ports.primary.notification_port import NotificationPort
from ports.primary.outbox_repository_port import OutboxRepositoryPort
from ports.primary.payroll_repository_port import PayrollRepositoryPort
from ports.primary.project_repository_port import ProjectRepositoryPort
from ports.primary.purchase_order_repository_port import PurchaseOrderRepositoryPort
from ports.primary.sales_order_repository_port import SalesOrderRepositoryPort
from ports.primary.supplier_repository_port import SupplierRepositoryPort
from ports.primary.system_setting_repository_port import SystemSettingRepositoryPort
from ports.primary.tax_authority_coretax_port import CoreTaxPort
from ports.primary.tax_repository_port import TaxRepositoryPort
from ports.primary.timestamp_notary_port import TimestampNotaryPort
from ports.primary.umkm_repository_port import UmkmRepositoryPort
from ports.primary.unit_of_work_port import UnitOfWorkPort
from ports.primary.work_order_repository_port import WorkOrderRepositoryPort

logger = logging.getLogger(__name__)


class AdapterRegistry:
    """
    Registry untuk adapter.
    """

    def __init__(self, container: IoCContainer | None = None):
        self._container = container or get_container()
        self._adapters: dict[str, type] = {}
        self._logger = logging.getLogger(f"{__name__}.AdapterRegistry")

    def register_all(self) -> None:
        """Register semua adapter yang tersedia ke container."""

        # ============================================================
        # IMPOR IMPLEMENTASI (lazy imports)
        # ============================================================
        # Core adapters
        from adapters.secondary_impl.sqlalchemy_unit_of_work_impl import SQLAlchemyUnitOfWork
        from adapters.secondary_impl.kafka_event_publisher_impl import KafkaEventPublisherImpl
        from adapters.secondary_impl.email_smtp_notification import EmailSMTPNotification
        from adapters.secondary_impl.s3_file_storage_adapter_impl import S3FileStorageAdapterImpl
        from adapters.secondary_impl.bank_mt940_parser_adapter import BankMT940ParserAdapter
        from adapters.secondary_impl.tax_authority_coretax_impl import CoretaxAuthorityAdapter
        from adapters.secondary_impl.timestamp_notary_impl import RFC3161TimestampAdapter
        from adapters.secondary_impl.encryption_key_vault_impl import EncryptionKeyVaultAdapter
        from adapters.secondary_impl.hash_chain_service_impl import HashChainServiceAdapter

        # Repository implementations
        from adapters.secondary_impl.sqlalchemy_account_repository_impl import SQLAlchemyAccountRepository
        from adapters.secondary_impl.sqlalchemy_ar_repository_impl import SQLAlchemyARRepository
        from adapters.secondary_impl.sqlalchemy_ap_repository_impl import SQLAlchemyAPRepository
        from adapters.secondary_impl.sqlalchemy_journal_repository_impl import SQLAlchemyJournalRepository
        from adapters.secondary_impl.sqlalchemy_ledger_repository_impl import SQLAlchemyLedgerRepository
        from adapters.secondary_impl.sqlalchemy_legal_entity_repository_impl import SQLAlchemyLegalEntityRepository
        from adapters.secondary_impl.sqlalchemy_inventory_repository_impl import SQLAlchemyInventoryRepository
        from adapters.secondary_impl.sqlalchemy_fixed_asset_repository_impl import SQLAlchemyFixedAssetRepository
        from adapters.secondary_impl.sqlalchemy_tax_repository_impl import SQLAlchemyTaxRepository
        from adapters.secondary_impl.sqlalchemy_payroll_repository_impl import SQLAlchemyPayrollRepository
        from adapters.secondary_impl.sqlalchemy_manufacturing_repository_impl import SQLAlchemyManufacturingRepository
        from adapters.secondary_impl.sqlalchemy_project_repository_impl import SQLAlchemyProjectRepository
        from adapters.secondary_impl.sqlalchemy_consolidation_repository_impl import SQLAlchemyConsolidationRepository
        from adapters.secondary_impl.sqlalchemy_forex_repository_impl import SQLAlchemyForexRepository
        from adapters.secondary_impl.sqlalchemy_hedge_repository_impl import SQLAlchemyHedgeRepository
        from adapters.secondary_impl.sqlalchemy_goodwill_repository_impl import SQLAlchemyGoodwillRepository
        from adapters.secondary_impl.sqlalchemy_intangible_asset_repository_impl import SQLAlchemyIntangibleAssetRepository
        from adapters.secondary_impl.sqlalchemy_budget_repository_impl import SQLAlchemyBudgetRepository
        from adapters.secondary_impl.sqlalchemy_approval_repository_impl import SQLAlchemyApprovalRepository
        from adapters.secondary_impl.sqlalchemy_bank_cash_repository_impl import SQLAlchemyBankCashRepository
        from adapters.secondary_impl.sqlalchemy_outbox_repository_impl import SQLAlchemyOutboxRepository
        from adapters.secondary_impl.sqlalchemy_system_setting_repository_impl import SQLAlchemySystemSettingRepository
        from adapters.secondary_impl.sqlalchemy_iam_user_repository_impl import SQLAlchemyIAMUserRepository
        from adapters.secondary_impl.sqlalchemy_employee_repository_impl import SQLAlchemyEmployeeRepository
        from adapters.secondary_impl.sqlalchemy_customer_repository_impl import SQLAlchemyCustomerRepository
        from adapters.secondary_impl.sqlalchemy_supplier_repository_impl import SQLAlchemySupplierRepository
        from adapters.secondary_impl.sqlalchemy_purchase_order_repository_impl import SQLAlchemyPurchaseOrderRepository
        from adapters.secondary_impl.sqlalchemy_sales_order_repository_impl import SQLAlchemySalesOrderRepository
        from adapters.secondary_impl.sqlalchemy_goods_receipt_repository_impl import SQLAlchemyGoodsReceiptRepository
        from adapters.secondary_impl.sqlalchemy_work_order_repository_impl import SQLAlchemyWorkOrderRepository
        from adapters.secondary_impl.sqlalchemy_bill_of_materials_repository_impl import SQLAlchemyBillOfMaterialsRepository
        from adapters.secondary_impl.sqlalchemy_fiscal_period_repository_impl import SQLAlchemyFiscalPeriodRepository
        from adapters.secondary_impl.sqlalchemy_umkm_repository_impl import SQLAlchemyUmkmRepository

        # ============================================================
        # REGISTRASI KE CONTAINER
        # ============================================================
        # Core adapters
        self._container.register_singleton(UnitOfWorkPort, SQLAlchemyUnitOfWork)
        self._container.register_singleton(EventPublisherPort, KafkaEventPublisherImpl)
        self._container.register_singleton(NotificationPort, EmailSMTPNotification)
        self._container.register_singleton(FileStoragePort, S3FileStorageAdapterImpl)
        self._container.register_singleton(BankStatementImportPort, BankMT940ParserAdapter)
        self._container.register_singleton(CoreTaxPort, CoretaxAuthorityAdapter)
        self._container.register_singleton(TimestampNotaryPort, RFC3161TimestampAdapter)
        self._container.register_singleton(EncryptionKeyVaultPort, EncryptionKeyVaultAdapter)
        self._container.register_singleton(HashChainServicePort, HashChainServiceAdapter)

        # Repository ports
        self._container.register_singleton(AccountRepositoryPort, SQLAlchemyAccountRepository)
        self._container.register_singleton(ARRepositoryPort, SQLAlchemyARRepository)
        self._container.register_singleton(APRepositoryPort, SQLAlchemyAPRepository)
        self._container.register_singleton(JournalRepositoryPort, SQLAlchemyJournalRepository)
        self._container.register_singleton(LedgerRepositoryPort, SQLAlchemyLedgerRepository)
        self._container.register_singleton(LegalEntityRepositoryPort, SQLAlchemyLegalEntityRepository)
        self._container.register_singleton(InventoryRepositoryPort, SQLAlchemyInventoryRepository)
        self._container.register_singleton(FixedAssetRepositoryPort, SQLAlchemyFixedAssetRepository)
        self._container.register_singleton(TaxRepositoryPort, SQLAlchemyTaxRepository)
        self._container.register_singleton(PayrollRepositoryPort, SQLAlchemyPayrollRepository)
        self._container.register_singleton(ManufacturingRepositoryPort, SQLAlchemyManufacturingRepository)
        self._container.register_singleton(ProjectRepositoryPort, SQLAlchemyProjectRepository)
        self._container.register_singleton(ConsolidationRepositoryPort, SQLAlchemyConsolidationRepository)
        self._container.register_singleton(ForexRepositoryPort, SQLAlchemyForexRepository)
        self._container.register_singleton(HedgeRepositoryPort, SQLAlchemyHedgeRepository)
        self._container.register_singleton(GoodwillRepositoryPort, SQLAlchemyGoodwillRepository)
        self._container.register_singleton(IntangibleAssetRepositoryPort, SQLAlchemyIntangibleAssetRepository)
        self._container.register_singleton(BudgetRepositoryPort, SQLAlchemyBudgetRepository)
        self._container.register_singleton(ApprovalRepositoryPort, SQLAlchemyApprovalRepository)
        self._container.register_singleton(BankCashRepositoryPort, SQLAlchemyBankCashRepository)
        self._container.register_singleton(OutboxRepositoryPort, SQLAlchemyOutboxRepository)
        self._container.register_singleton(SystemSettingRepositoryPort, SQLAlchemySystemSettingRepository)
        self._container.register_singleton(IAMUserRepositoryPort, SQLAlchemyIAMUserRepository)
        self._container.register_singleton(EmployeeRepositoryPort, SQLAlchemyEmployeeRepository)
        self._container.register_singleton(CustomerRepositoryPort, SQLAlchemyCustomerRepository)
        self._container.register_singleton(SupplierRepositoryPort, SQLAlchemySupplierRepository)
        self._container.register_singleton(PurchaseOrderRepositoryPort, SQLAlchemyPurchaseOrderRepository)
        self._container.register_singleton(SalesOrderRepositoryPort, SQLAlchemySalesOrderRepository)
        self._container.register_singleton(GoodsReceiptRepositoryPort, SQLAlchemyGoodsReceiptRepository)
        self._container.register_singleton(WorkOrderRepositoryPort, SQLAlchemyWorkOrderRepository)
        self._container.register_singleton(BillOfMaterialsRepositoryPort, SQLAlchemyBillOfMaterialsRepository)
        self._container.register_singleton(FiscalPeriodRepositoryPort, SQLAlchemyFiscalPeriodRepository)
        self._container.register_singleton(UmkmRepositoryPort, SQLAlchemyUmkmRepository)

        # ============================================================
        # NAMED ADAPTERS (untuk lookup by name)
        # ============================================================
        self._adapters["unit_of_work"] = UnitOfWorkPort
        self._adapters["event_publisher"] = EventPublisherPort
        self._adapters["notification"] = NotificationPort
        self._adapters["file_storage"] = FileStoragePort
        self._adapters["bank_statement_import"] = BankStatementImportPort
        self._adapters["coretax"] = CoreTaxPort
        self._adapters["timestamp_notary"] = TimestampNotaryPort
        self._adapters["encryption_vault"] = EncryptionKeyVaultPort
        self._adapters["hash_chain"] = HashChainServicePort

        self._logger.info(f"Registered {len(self._adapters)} adapter interfaces with implementations")

    # ================================================================
    # METODE LAINNYA (register, unregister, resolve, dll.)
    # ================================================================

    def register(self, name: str, interface: type, implementation: type | None = None) -> None:
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
        if name not in self._adapters:
            self._logger.warning(f"Adapter not found for unregister: {name}")
            return False

        interface = self._adapters.pop(name)
        if interface in self._container._registrations:
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
        return self._container.resolve(interface, **kwargs)

    async def resolve_async(self, name: str, **kwargs) -> Any:
        interface = self.get_adapter_interface(name)
        if not interface:
            raise ValueError(f"Adapter not found: {name}")
        return await self._container.resolve_async(interface, **kwargs)

    def list_adapters(self) -> list[str]:
        return sorted(self._adapters.keys())

    def has_adapter(self, name: str) -> bool:
        return name in self._adapters

    def reset(self) -> None:
        self._adapters.clear()
        self._logger.info("Adapter registry reset")


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_adapter_registry: AdapterRegistry | None = None


def get_adapter_registry() -> AdapterRegistry:
    global _adapter_registry
    if _adapter_registry is None:
        _adapter_registry = AdapterRegistry()
        _adapter_registry.register_all()
    return _adapter_registry


async def get_uow() -> UnitOfWorkPort:
    registry = get_adapter_registry()
    return await registry.resolve_async("unit_of_work")


__all__ = [
    "AdapterRegistry",
    "get_adapter_registry",
    "get_uow",
]