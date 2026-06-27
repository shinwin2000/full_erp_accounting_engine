#!/usr/bin/env python3
"""
Package: adapters.secondary_impl
Ekspor semua implementasi repository SQLAlchemy dan adapter lainnya.

Versi ini mencakup seluruh repository yang digunakan dan telah dilengkapi
dengan logger package untuk keperluan debugging dan forensic check.
"""

from __future__ import annotations

import logging  # <-- TAMBAHAN: untuk logging package

# ========================================================================
# ACCOUNT
# ========================================================================
from .sqlalchemy_account_repository_impl import (
    SQLAlchemyAccountRepository,
)

# ========================================================================
# AML (ANTI MONEY LAUNDERING)
# ========================================================================
from .sqlalchemy_aml_repository_impl import (
    SQLAlchemyAMLRepository,
)

# ========================================================================
# AP (ACCOUNTS PAYABLE)
# ========================================================================
from .sqlalchemy_ap_repository_impl import (
    SQLAlchemyAPRepository,
)

# ========================================================================
# APPROVAL
# ========================================================================
from .sqlalchemy_approval_repository_impl import (
    SQLAlchemyApprovalRepository,
)

# ========================================================================
# AR (ACCOUNTS RECEIVABLE)
# ========================================================================
from .sqlalchemy_ar_repository_impl import (
    SQLAlchemyARRepository,
)

# ========================================================================
# AUDIT
# ========================================================================
from .sqlalchemy_audit_repository import (
    SQLAlchemyAuditRepository,
)

# ========================================================================
# BALANCE SHEET
# ========================================================================
from .sqlalchemy_balance_sheet_repository import (
    SQLAlchemyBalanceSheetRepository,
)

# ========================================================================
# BANK CASH
# ========================================================================
from .sqlalchemy_bank_cash_repository_impl import (
    SQLAlchemyBankCashRepository,
)

# ========================================================================
# BILL OF MATERIALS (BOM)
# ========================================================================
from .sqlalchemy_bill_of_materials_repository_impl import (
    SQLAlchemyBillOfMaterialsRepository,
)

# ========================================================================
# BUDGET
# ========================================================================
from .sqlalchemy_budget_repository_impl import (
    SQLAlchemyBudgetRepository,
)

# ========================================================================
# CACHE
# ========================================================================
from .sqlalchemy_cache_repository import (
    CacheAdapter,  # alias lama
    InMemoryCache,
    SQLAlchemyCacheAdapter,  # alias untuk backward compatibility
    SQLAlchemyCacheRepository,
)

# ========================================================================
# CASH BOOK
# ========================================================================
from .sqlalchemy_cash_book_repository import (
    SQLAlchemyCashBookRepository,
)

# ========================================================================
# CASH FLOW
# ========================================================================
from .sqlalchemy_cash_flow_repository import (
    SQLAlchemyCashFlowRepository,
)

# ========================================================================
# CONSOLIDATION
# ========================================================================
from .sqlalchemy_consolidation_repository_impl import (
    SQLAlchemyConsolidationRepository,
)

# ========================================================================
# CUSTOMER
# ========================================================================
from .sqlalchemy_customer_repository_impl import (
    SQLAlchemyCustomerRepository,
    SQLAlchemyCustomerRepositoryImpl,
)

# ========================================================================
# EMPLOYEE
# ========================================================================
from .sqlalchemy_employee_repository_impl import (
    SQLAlchemyEmployeeRepository,
)

# ========================================================================
# FISCAL PERIOD
# ========================================================================
from .sqlalchemy_fiscal_period_repository_impl import (
    SQLAlchemyFiscalPeriodRepository,
)

# ========================================================================
# FIXED ASSET
# ========================================================================
from .sqlalchemy_fixed_asset_repository_impl import (
    SQLAlchemyFixedAssetRepository,
)

# ========================================================================
# FOREX
# ========================================================================
from .sqlalchemy_forex_repository_impl import (
    SQLAlchemyForexRepository,
)

# ========================================================================
# GENERAL LEDGER
# ========================================================================
from .sqlalchemy_general_ledger_repository_impl import (
    SQLAlchemyGeneralLedgerRepository,
)

# ========================================================================
# GOODS RECEIPT
# ========================================================================
from .sqlalchemy_goods_receipt_repository_impl import (
    SQLAlchemyGoodsReceiptRepository,
)

# ========================================================================
# GOODWILL
# ========================================================================
from .sqlalchemy_goodwill_repository_impl import (
    SQLAlchemyGoodwillRepository,
)

# ========================================================================
# HEDGE
# ========================================================================
from .sqlalchemy_hedge_repository_impl import (
    SQLAlchemyHedgeRepository,
)

# ========================================================================
# IAM (USER)
# ========================================================================
from .sqlalchemy_iam_user_repository_impl import (
    SQLAlchemyIAMUserRepository,
)

# ========================================================================
# INCOME STATEMENT
# ========================================================================
from .sqlalchemy_income_statement_repository import (
    SQLAlchemyIncomeStatementRepository,
)

# ========================================================================
# INTANGIBLE ASSET
# ========================================================================
from .sqlalchemy_intangible_asset_repository_impl import (
    SQLAlchemyIntangibleAssetRepository,
)

# ========================================================================
# INVENTORY
# ========================================================================
from .sqlalchemy_inventory_repository_impl import (
    SQLAlchemyInventoryRepository,
)

# ========================================================================
# JOURNAL
# ========================================================================
from .sqlalchemy_journal_repository_impl import (
    SQLAlchemyJournalRepository,
)

# ========================================================================
# LEDGER
# ========================================================================
from .sqlalchemy_ledger_repository_impl import (
    SQLAlchemyLedgerRepository,
)

# ========================================================================
# LEGAL ENTITY
# ========================================================================
from .sqlalchemy_legal_entity_repository_impl import (
    SQLAlchemyLegalEntityRepository,
)

# ========================================================================
# MANUFACTURING
# ========================================================================
from .sqlalchemy_manufacturing_repository_impl import (
    SQLAlchemyManufacturingRepository,
)

# ========================================================================
# OUTBOX
# ========================================================================
from .sqlalchemy_outbox_repository_impl import (
    SQLAlchemyOutboxRepository,
)

# ========================================================================
# PAYROLL
# ========================================================================
from .sqlalchemy_payroll_repository_impl import (
    SQLAlchemyPayrollRepository,
)

# ========================================================================
# PROJECT
# ========================================================================
from .sqlalchemy_project_repository_impl import (
    SQLAlchemyProjectRepository,
)

# ========================================================================
# PURCHASE ORDER
# ========================================================================
from .sqlalchemy_purchase_order_repository_impl import (
    SQLAlchemyPurchaseOrderRepository,
)

# ========================================================================
# REPORT
# ========================================================================
from .sqlalchemy_report_repository_impl import (
    AgingBucket,
    SQLAlchemyReportRepository,
)

# ========================================================================
# SAGA STATE STORE
# ========================================================================
from .sqlalchemy_saga_state_store import (
    SagaStateStore,  # alias lama
    SagaStateTable,
    SQLAlchemySagaStateStore,  # alias untuk backward compatibility
    SQLAlchemySagaStateStoreRepository,
)

# ========================================================================
# SALES ORDER
# ========================================================================
from .sqlalchemy_sales_order_repository_impl import (
    SQLAlchemySalesOrderRepository,
)

# ========================================================================
# SUPPLIER
# ========================================================================
from .sqlalchemy_supplier_repository_impl import (
    SQLAlchemySupplierRepository,
    SupplierTable,
)

# ========================================================================
# SYSTEM SETTING
# ========================================================================
from .sqlalchemy_system_setting_repository_impl import (
    SQLAlchemySystemSettingRepository,
)

# ========================================================================
# TAX
# ========================================================================
from .sqlalchemy_tax_repository_impl import (
    SQLAlchemyTaxRepository,
)

# ========================================================================
# TAX TRANSACTION
# ========================================================================
from .sqlalchemy_tax_transaction_repository_impl import (
    SQLAlchemyTaxTransactionRepository,
)

# ========================================================================
# TRIAL BALANCE
# ========================================================================
from .sqlalchemy_trial_balance_repository import (
    SQLAlchemyTrialBalanceRepository,
)

# ========================================================================
# UMKM
# ========================================================================
from .sqlalchemy_umkm_repository_impl import (
    SQLAlchemyUMKMRepository,
)

# ========================================================================
# WORK ORDER
# ========================================================================
from .sqlalchemy_work_order_repository_impl import (
    SQLAlchemyWorkOrderRepository,
)

# ========================================================================
# VERSION
# ========================================================================
__version__ = "3.0.0"

# ========================================================================
# PACKAGE LOGGER (untuk debugging & forensic check)
# ========================================================================
logger = logging.getLogger(__name__)
logger.info(f"Package {__name__} version {__version__} loaded successfully.")

# ========================================================================
# FORENSIC CHECK (opsional) - Jalankan PowerShell untuk verifikasi integritas
# ========================================================================
# Contoh perintah PowerShell untuk melakukan forensic check:
#   powershell -Command "Get-ChildItem -Recurse *.py | Get-FileHash | Out-File forensic_hashes.txt"
# Anda dapat mengaktifkan fungsi di bawah jika diperlukan.
#
# def run_forensic_check():
#     import subprocess
#     subprocess.run(["powershell", "-Command",
#                     "Get-ChildItem -Recurse *.py | Get-FileHash | Out-File forensic_hashes.txt"])
#     logger.info("Forensic check completed. Hashes saved to forensic_hashes.txt.")
#
# # Uncomment baris berikut untuk menjalankan forensic check saat package di-import:
# # run_forensic_check()

# ========================================================================
# EXPORT ALL
# ========================================================================
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
