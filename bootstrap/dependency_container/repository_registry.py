#!/usr/bin/env python3
"""
Module: repository_registry.py
Layer: Bootstrap (Dependency Container)
Responsibility: Registry khusus untuk repository pattern dengan lazy imports.
"""

from __future__ import annotations

import logging
from typing import Any

from bootstrap.dependency_container.ioc_container import IoCContainer, get_container
from ports.primary.account_repository_port import AccountRepositoryPort
from ports.primary.ap_repository_port import APRepositoryPort
from ports.primary.ar_repository_port import ARRepositoryPort
from ports.primary.bank_cash_repository_port import BankCashRepositoryPort
from ports.primary.bill_of_materials_repository_port import BillOfMaterialsRepositoryPort
from ports.primary.customer_repository_port import CustomerRepositoryPort
from ports.primary.employee_repository_port import EmployeeRepositoryPort
from ports.primary.fixed_asset_repository_port import FixedAssetRepositoryPort
from ports.primary.iam_user_repository_port import IAMUserRepositoryPort
from ports.primary.inventory_repository_port import InventoryRepositoryPort
from ports.primary.journal_repository_port import JournalRepositoryPort
from ports.primary.ledger_repository_port import LedgerRepositoryPort
from ports.primary.legal_entity_repository_port import LegalEntityRepositoryPort
from ports.primary.outbox_repository_port import OutboxRepositoryPort
from ports.primary.project_repository_port import ProjectRepositoryPort
from ports.primary.purchase_order_repository_port import PurchaseOrderRepositoryPort
from ports.primary.sales_order_repository_port import SalesOrderRepositoryPort
from ports.primary.supplier_repository_port import SupplierRepositoryPort
from ports.primary.system_setting_repository_port import SystemSettingRepositoryPort
from ports.primary.tax_repository_port import TaxRepositoryPort
from ports.primary.work_order_repository_port import WorkOrderRepositoryPort

logger = logging.getLogger(__name__)


class RepositoryRegistry:
    def __init__(self, container: IoCContainer | None = None):
        self._container = container or get_container()
        self._repositories: dict[str, type] = {}
        self._logger = logging.getLogger(f"{__name__}.RepositoryRegistry")

    def register_all(self) -> None:
        """Register all repositories to the container using lazy imports."""
        
        # Lazy imports for SQLAlchemy implementations
        from adapters.secondary_impl.sqlalchemy_account_repository_impl import SQLAlchemyAccountRepository
        from adapters.secondary_impl.sqlalchemy_ap_repository_impl import SQLAlchemyAPRepository
        from adapters.secondary_impl.sqlalchemy_ar_repository_impl import SQLAlchemyARRepository
        from adapters.secondary_impl.sqlalchemy_bank_cash_repository_impl import SQLAlchemyBankCashRepository
        from adapters.secondary_impl.sqlalchemy_bill_of_materials_repository_impl import SQLAlchemyBillOfMaterialsRepository
        from adapters.secondary_impl.sqlalchemy_customer_repository_impl import SQLAlchemyCustomerRepository
        from adapters.secondary_impl.sqlalchemy_employee_repository_impl import SQLAlchemyEmployeeRepository
        from adapters.secondary_impl.sqlalchemy_fixed_asset_repository_impl import SQLAlchemyFixedAssetRepository
        from adapters.secondary_impl.sqlalchemy_iam_user_repository_impl import SQLAlchemyIAMUserRepository
        from adapters.secondary_impl.sqlalchemy_inventory_repository_impl import SQLAlchemyInventoryRepository
        from adapters.secondary_impl.sqlalchemy_journal_repository_impl import SQLAlchemyJournalRepository
        from adapters.secondary_impl.sqlalchemy_ledger_repository_impl import SQLAlchemyLedgerRepository
        from adapters.secondary_impl.sqlalchemy_legal_entity_repository_impl import SQLAlchemyLegalEntityRepository
        from adapters.secondary_impl.sqlalchemy_outbox_repository_impl import SQLAlchemyOutboxRepository
        from adapters.secondary_impl.sqlalchemy_project_repository_impl import SQLAlchemyProjectRepository
        from adapters.secondary_impl.sqlalchemy_purchase_order_repository_impl import SQLAlchemyPurchaseOrderRepository
        from adapters.secondary_impl.sqlalchemy_sales_order_repository_impl import SQLAlchemySalesOrderRepository
        from adapters.secondary_impl.sqlalchemy_supplier_repository_impl import SQLAlchemySupplierRepository
        from adapters.secondary_impl.sqlalchemy_system_setting_repository_impl import SQLAlchemySystemSettingRepository
        from adapters.secondary_impl.sqlalchemy_tax_repository_impl import SQLAlchemyTaxRepository
        from adapters.secondary_impl.sqlalchemy_work_order_repository_impl import SQLAlchemyWorkOrderRepository

        self._container.register_singleton(JournalRepositoryPort, SQLAlchemyJournalRepository)
        self._container.register_singleton(LedgerRepositoryPort, SQLAlchemyLedgerRepository)
        self._container.register_singleton(AccountRepositoryPort, SQLAlchemyAccountRepository)
        self._container.register_singleton(ARRepositoryPort, SQLAlchemyARRepository)
        self._container.register_singleton(APRepositoryPort, SQLAlchemyAPRepository)
        self._container.register_singleton(InventoryRepositoryPort, SQLAlchemyInventoryRepository)
        self._container.register_singleton(FixedAssetRepositoryPort, SQLAlchemyFixedAssetRepository)
        self._container.register_singleton(BankCashRepositoryPort, SQLAlchemyBankCashRepository)
        self._container.register_singleton(TaxRepositoryPort, SQLAlchemyTaxRepository)
        self._container.register_singleton(LegalEntityRepositoryPort, SQLAlchemyLegalEntityRepository)
        self._container.register_singleton(IAMUserRepositoryPort, SQLAlchemyIAMUserRepository)
        self._container.register_singleton(SystemSettingRepositoryPort, SQLAlchemySystemSettingRepository)
        self._container.register_singleton(OutboxRepositoryPort, SQLAlchemyOutboxRepository)
        self._container.register_singleton(EmployeeRepositoryPort, SQLAlchemyEmployeeRepository)
        self._container.register_singleton(CustomerRepositoryPort, SQLAlchemyCustomerRepository)
        self._container.register_singleton(SupplierRepositoryPort, SQLAlchemySupplierRepository)
        self._container.register_singleton(PurchaseOrderRepositoryPort, SQLAlchemyPurchaseOrderRepository)
        self._container.register_singleton(SalesOrderRepositoryPort, SQLAlchemySalesOrderRepository)
        self._container.register_singleton(WorkOrderRepositoryPort, SQLAlchemyWorkOrderRepository)
        self._container.register_singleton(BillOfMaterialsRepositoryPort, SQLAlchemyBillOfMaterialsRepository)
        self._container.register_singleton(ProjectRepositoryPort, SQLAlchemyProjectRepository)

        self._repositories["journal"] = JournalRepositoryPort
        self._repositories["ledger"] = LedgerRepositoryPort
        self._repositories["account"] = AccountRepositoryPort
        self._repositories["ar"] = ARRepositoryPort
        self._repositories["ap"] = APRepositoryPort
        self._repositories["inventory"] = InventoryRepositoryPort
        self._repositories["fixed_asset"] = FixedAssetRepositoryPort
        self._repositories["bank_cash"] = BankCashRepositoryPort
        self._repositories["tax"] = TaxRepositoryPort
        self._repositories["legal_entity"] = LegalEntityRepositoryPort
        self._repositories["iam_user"] = IAMUserRepositoryPort
        self._repositories["system_setting"] = SystemSettingRepositoryPort
        self._repositories["outbox"] = OutboxRepositoryPort
        self._repositories["employee"] = EmployeeRepositoryPort
        self._repositories["customer"] = CustomerRepositoryPort
        self._repositories["supplier"] = SupplierRepositoryPort
        self._repositories["purchase_order"] = PurchaseOrderRepositoryPort
        self._repositories["sales_order"] = SalesOrderRepositoryPort
        self._repositories["work_order"] = WorkOrderRepositoryPort
        self._repositories["bom"] = BillOfMaterialsRepositoryPort
        self._repositories["project"] = ProjectRepositoryPort

        self._logger.info(f"Registered {len(self._repositories)} repositories")

    def register(self, name: str, interface: type) -> None:
        if not name:
            raise ValueError("Repository name cannot be empty")
        if not interface:
            raise ValueError("Repository interface cannot be None")
        self._repositories[name] = interface
        self._logger.debug(f"Registered repository: {name} -> {interface.__name__}")

    def unregister(self, name: str) -> bool:
        if name in self._repositories:
            del self._repositories[name]
            self._logger.debug(f"Unregistered repository: {name}")
            return True
        return False

    def get_repository_interface(self, name: str) -> type | None:
        if not name:
            raise ValueError("Repository name cannot be empty")
        return self._repositories.get(name)

    def resolve(self, name: str, **kwargs) -> Any:
        interface = self.get_repository_interface(name)
        if not interface:
            raise ValueError(f"Repository not found: {name}")
        return self._container.resolve(interface, **kwargs)

    async def resolve_async(self, name: str, **kwargs) -> Any:
        interface = self.get_repository_interface(name)
        if not interface:
            raise ValueError(f"Repository not found: {name}")
        return await self._container.resolve_async(interface, **kwargs)

    def list_repositories(self) -> list[str]:
        return sorted(self._repositories.keys())

    def has_repository(self, name: str) -> bool:
        return name in self._repositories

    def reset(self) -> None:
        self._repositories.clear()
        self._logger.info("Repository registry reset")


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_repository_registry: RepositoryRegistry | None = None


def get_repository_registry() -> RepositoryRegistry:
    global _repository_registry
    if _repository_registry is None:
        _repository_registry = RepositoryRegistry()
        _repository_registry.register_all()
    return _repository_registry


__all__ = [
    "RepositoryRegistry",
    "get_repository_registry",
]