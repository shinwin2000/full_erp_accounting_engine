#!/usr/bin/env python3
"""
Package: adapters.secondary_impl
Ekspor semua implementasi repository SQLAlchemy dan adapter lainnya.
Menggunakan lazy import untuk menghindari error circular/import-time.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

__version__ = "3.0.0"

logger = logging.getLogger(__name__)

# Mapping nama atribut ke (module_path, attribute_name)
_LAZY_MAP = {
    # Account
    "SQLAlchemyAccountRepository": ("adapters.secondary_impl.sqlalchemy_account_repository_impl", "SQLAlchemyAccountRepository"),
    # AML
    "SQLAlchemyAMLRepository": ("adapters.secondary_impl.sqlalchemy_aml_repository_impl", "SQLAlchemyAMLRepository"),
    # Approval
    "SQLAlchemyApprovalRepository": ("adapters.secondary_impl.sqlalchemy_approval_repository_impl", "SQLAlchemyApprovalRepository"),
    # AP
    "SQLAlchemyAPRepository": ("adapters.secondary_impl.sqlalchemy_ap_repository_impl", "SQLAlchemyAPRepository"),
    # AR
    "SQLAlchemyARRepository": ("adapters.secondary_impl.sqlalchemy_ar_repository_impl", "SQLAlchemyARRepository"),
    # Audit
    "SQLAlchemyAuditRepository": ("adapters.secondary_impl.sqlalchemy_audit_repository", "SQLAlchemyAuditRepository"),
    # Balance Sheet
    "SQLAlchemyBalanceSheetRepository": ("adapters.secondary_impl.sqlalchemy_balance_sheet_repository", "SQLAlchemyBalanceSheetRepository"),
    # Bank Cash
    "SQLAlchemyBankCashRepository": ("adapters.secondary_impl.sqlalchemy_bank_cash_repository_impl", "SQLAlchemyBankCashRepository"),
    # BOM
    "SQLAlchemyBillOfMaterialsRepository": ("adapters.secondary_impl.sqlalchemy_bill_of_materials_repository_impl", "SQLAlchemyBillOfMaterialsRepository"),
    # Budget
    "SQLAlchemyBudgetRepository": ("adapters.secondary_impl.sqlalchemy_budget_repository_impl", "SQLAlchemyBudgetRepository"),
    # Cache
    "SQLAlchemyCacheRepository": ("adapters.secondary_impl.sqlalchemy_cache_repository", "SQLAlchemyCacheRepository"),
    "InMemoryCache": ("adapters.secondary_impl.sqlalchemy_cache_repository", "InMemoryCache"),
    "CacheAdapter": ("adapters.secondary_impl.sqlalchemy_cache_repository", "CacheAdapter"),
    "SQLAlchemyCacheAdapter": ("adapters.secondary_impl.sqlalchemy_cache_repository", "SQLAlchemyCacheAdapter"),
    # Cash Book
    "SQLAlchemyCashBookRepository": ("adapters.secondary_impl.sqlalchemy_cash_book_repository", "SQLAlchemyCashBookRepository"),
    # Cash Flow
    "SQLAlchemyCashFlowRepository": ("adapters.secondary_impl.sqlalchemy_cash_flow_repository", "SQLAlchemyCashFlowRepository"),
    # Consolidation
    "SQLAlchemyConsolidationRepository": ("adapters.secondary_impl.sqlalchemy_consolidation_repository_impl", "SQLAlchemyConsolidationRepository"),
    # Customer
    "SQLAlchemyCustomerRepository": ("adapters.secondary_impl.sqlalchemy_customer_repository_impl", "SQLAlchemyCustomerRepository"),
    "SQLAlchemyCustomerRepositoryImpl": ("adapters.secondary_impl.sqlalchemy_customer_repository_impl", "SQLAlchemyCustomerRepositoryImpl"),
    # Employee
    "SQLAlchemyEmployeeRepository": ("adapters.secondary_impl.sqlalchemy_employee_repository_impl", "SQLAlchemyEmployeeRepository"),
    # Fiscal Period
    "SQLAlchemyFiscalPeriodRepository": ("adapters.secondary_impl.sqlalchemy_fiscal_period_repository_impl", "SQLAlchemyFiscalPeriodRepository"),
    # Fixed Asset
    "SQLAlchemyFixedAssetRepository": ("adapters.secondary_impl.sqlalchemy_fixed_asset_repository_impl", "SQLAlchemyFixedAssetRepository"),
    # Forex
    "SQLAlchemyForexRepository": ("adapters.secondary_impl.sqlalchemy_forex_repository_impl", "SQLAlchemyForexRepository"),
    # General Ledger
    "SQLAlchemyGeneralLedgerRepository": ("adapters.secondary_impl.sqlalchemy_general_ledger_repository_impl", "SQLAlchemyGeneralLedgerRepository"),
    # Goods Receipt
    "SQLAlchemyGoodsReceiptRepository": ("adapters.secondary_impl.sqlalchemy_goods_receipt_repository_impl", "SQLAlchemyGoodsReceiptRepository"),
    # Goodwill
    "SQLAlchemyGoodwillRepository": ("adapters.secondary_impl.sqlalchemy_goodwill_repository_impl", "SQLAlchemyGoodwillRepository"),
    # Hedge
    "SQLAlchemyHedgeRepository": ("adapters.secondary_impl.sqlalchemy_hedge_repository_impl", "SQLAlchemyHedgeRepository"),
    # IAM
    "SQLAlchemyIAMUserRepository": ("adapters.secondary_impl.sqlalchemy_iam_user_repository_impl", "SQLAlchemyIAMUserRepository"),
    # Income Statement
    "SQLAlchemyIncomeStatementRepository": ("adapters.secondary_impl.sqlalchemy_income_statement_repository", "SQLAlchemyIncomeStatementRepository"),
    # Intangible Asset
    "SQLAlchemyIntangibleAssetRepository": ("adapters.secondary_impl.sqlalchemy_intangible_asset_repository_impl", "SQLAlchemyIntangibleAssetRepository"),
    # Inventory
    "SQLAlchemyInventoryRepository": ("adapters.secondary_impl.sqlalchemy_inventory_repository_impl", "SQLAlchemyInventoryRepository"),
    # Journal
    "SQLAlchemyJournalRepository": ("adapters.secondary_impl.sqlalchemy_journal_repository_impl", "SQLAlchemyJournalRepository"),
    # Ledger
    "SQLAlchemyLedgerRepository": ("adapters.secondary_impl.sqlalchemy_ledger_repository_impl", "SQLAlchemyLedgerRepository"),
    # Legal Entity
    "SQLAlchemyLegalEntityRepository": ("adapters.secondary_impl.sqlalchemy_legal_entity_repository_impl", "SQLAlchemyLegalEntityRepository"),
    # Manufacturing
    "SQLAlchemyManufacturingRepository": ("adapters.secondary_impl.sqlalchemy_manufacturing_repository_impl", "SQLAlchemyManufacturingRepository"),
    # Outbox
    "SQLAlchemyOutboxRepository": ("adapters.secondary_impl.sqlalchemy_outbox_repository_impl", "SQLAlchemyOutboxRepository"),
    # Payroll
    "SQLAlchemyPayrollRepository": ("adapters.secondary_impl.sqlalchemy_payroll_repository_impl", "SQLAlchemyPayrollRepository"),
    # Project
    "SQLAlchemyProjectRepository": ("adapters.secondary_impl.sqlalchemy_project_repository_impl", "SQLAlchemyProjectRepository"),
    # Purchase Order
    "SQLAlchemyPurchaseOrderRepository": ("adapters.secondary_impl.sqlalchemy_purchase_order_repository_impl", "SQLAlchemyPurchaseOrderRepository"),
    # Report
    "SQLAlchemyReportRepository": ("adapters.secondary_impl.sqlalchemy_report_repository_impl", "SQLAlchemyReportRepository"),
    "AgingBucket": ("adapters.secondary_impl.sqlalchemy_report_repository_impl", "AgingBucket"),
    # Saga
    "SQLAlchemySagaStateStoreRepository": ("adapters.secondary_impl.sqlalchemy_saga_state_store", "SQLAlchemySagaStateStoreRepository"),
    "SagaStateTable": ("adapters.secondary_impl.sqlalchemy_saga_state_store", "SagaStateTable"),
    "SagaStateStore": ("adapters.secondary_impl.sqlalchemy_saga_state_store", "SagaStateStore"),
    "SQLAlchemySagaStateStore": ("adapters.secondary_impl.sqlalchemy_saga_state_store", "SQLAlchemySagaStateStore"),
    # Sales Order
    "SQLAlchemySalesOrderRepository": ("adapters.secondary_impl.sqlalchemy_sales_order_repository_impl", "SQLAlchemySalesOrderRepository"),
    # Supplier
    "SQLAlchemySupplierRepository": ("adapters.secondary_impl.sqlalchemy_supplier_repository_impl", "SQLAlchemySupplierRepository"),
    "SupplierTable": ("adapters.secondary_impl.sqlalchemy_supplier_repository_impl", "SupplierTable"),
    # System Setting
    "SQLAlchemySystemSettingRepository": ("adapters.secondary_impl.sqlalchemy_system_setting_repository_impl", "SQLAlchemySystemSettingRepository"),
    # Tax
    "SQLAlchemyTaxRepository": ("adapters.secondary_impl.sqlalchemy_tax_repository_impl", "SQLAlchemyTaxRepository"),
    # Tax Transaction
    "SQLAlchemyTaxTransactionRepository": ("adapters.secondary_impl.sqlalchemy_tax_transaction_repository_impl", "SQLAlchemyTaxTransactionRepository"),
    # Trial Balance
    "SQLAlchemyTrialBalanceRepository": ("adapters.secondary_impl.sqlalchemy_trial_balance_repository", "SQLAlchemyTrialBalanceRepository"),
    # UMKM
    "SQLAlchemyUMKMRepository": ("adapters.secondary_impl.sqlalchemy_umkm_repository_impl", "SQLAlchemyUMKMRepository"),
    # Work Order
    "SQLAlchemyWorkOrderRepository": ("adapters.secondary_impl.sqlalchemy_work_order_repository_impl", "SQLAlchemyWorkOrderRepository"),
}

_cache = {}


def __getattr__(name: str) -> Any:
    """Lazy import repository classes."""
    if name in _cache:
        return _cache[name]
    if name not in _LAZY_MAP:
        raise AttributeError(f"module {__name__} has no attribute {name}")

    module_path, attr_name = _LAZY_MAP[name]
    try:
        module = importlib.import_module(module_path)
        value = getattr(module, attr_name)
        _cache[name] = value
        logger.debug(f"Lazy-loaded {name} from {module_path}")
        return value
    except Exception as e:
        logger.error(f"Failed to lazy-load {name} from {module_path}: {e}")
        raise AttributeError(f"module {__name__} has no attribute {name}") from e


__all__ = [
    # Account
    "SQLAlchemyAccountRepository",
    # AML
    "SQLAlchemyAMLRepository",
    # Approval
    "SQLAlchemyApprovalRepository",
    # AP
    "SQLAlchemyAPRepository",
    # AR
    "SQLAlchemyARRepository",
    # Audit
    "SQLAlchemyAuditRepository",
    # Balance Sheet
    "SQLAlchemyBalanceSheetRepository",
    # Bank Cash
    "SQLAlchemyBankCashRepository",
    # BOM
    "SQLAlchemyBillOfMaterialsRepository",
    # Budget
    "SQLAlchemyBudgetRepository",
    # Cache
    "SQLAlchemyCacheRepository",
    "InMemoryCache",
    "CacheAdapter",
    "SQLAlchemyCacheAdapter",
    # Cash Book
    "SQLAlchemyCashBookRepository",
    # Cash Flow
    "SQLAlchemyCashFlowRepository",
    # Consolidation
    "SQLAlchemyConsolidationRepository",
    # Customer
    "SQLAlchemyCustomerRepository",
    "SQLAlchemyCustomerRepositoryImpl",
    # Employee
    "SQLAlchemyEmployeeRepository",
    # Fiscal Period
    "SQLAlchemyFiscalPeriodRepository",
    # Fixed Asset
    "SQLAlchemyFixedAssetRepository",
    # Forex
    "SQLAlchemyForexRepository",
    # General Ledger
    "SQLAlchemyGeneralLedgerRepository",
    # Goods Receipt
    "SQLAlchemyGoodsReceiptRepository",
    # Goodwill
    "SQLAlchemyGoodwillRepository",
    # Hedge
    "SQLAlchemyHedgeRepository",
    # IAM
    "SQLAlchemyIAMUserRepository",
    # Income Statement
    "SQLAlchemyIncomeStatementRepository",
    # Intangible Asset
    "SQLAlchemyIntangibleAssetRepository",
    # Inventory
    "SQLAlchemyInventoryRepository",
    # Journal
    "SQLAlchemyJournalRepository",
    # Ledger
    "SQLAlchemyLedgerRepository",
    # Legal Entity
    "SQLAlchemyLegalEntityRepository",
    # Manufacturing
    "SQLAlchemyManufacturingRepository",
    # Outbox
    "SQLAlchemyOutboxRepository",
    # Payroll
    "SQLAlchemyPayrollRepository",
    # Project
    "SQLAlchemyProjectRepository",
    # Purchase Order
    "SQLAlchemyPurchaseOrderRepository",
    # Report
    "SQLAlchemyReportRepository",
    "AgingBucket",
    # Saga
    "SQLAlchemySagaStateStoreRepository",
    "SagaStateTable",
    "SagaStateStore",
    "SQLAlchemySagaStateStore",
    # Sales Order
    "SQLAlchemySalesOrderRepository",
    # Supplier
    "SQLAlchemySupplierRepository",
    "SupplierTable",
    # System Setting
    "SQLAlchemySystemSettingRepository",
    # Tax
    "SQLAlchemyTaxRepository",
    # Tax Transaction
    "SQLAlchemyTaxTransactionRepository",
    # Trial Balance
    "SQLAlchemyTrialBalanceRepository",
    # UMKM
    "SQLAlchemyUMKMRepository",
    # Work Order
    "SQLAlchemyWorkOrderRepository",
    "__version__",
]
