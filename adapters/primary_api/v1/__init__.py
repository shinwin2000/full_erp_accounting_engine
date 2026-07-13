from __future__ import annotations

"""
Package: adapters.primary_api.v1
Router API version 1.
"""

# Import semua router dari file-file yang ada
from adapters.primary_api.v1.fastapi_ap_router import router as ap_router
from adapters.primary_api.v1.fastapi_approval_router import router as approval_router
from adapters.primary_api.v1.fastapi_ar_router import router as ar_router
from adapters.primary_api.v1.fastapi_audit_router import router as audit_router
from adapters.primary_api.v1.fastapi_bank_cash_router import router as bank_cash_router
from adapters.primary_api.v1.fastapi_budget_router import router as budget_router
from adapters.primary_api.v1.fastapi_capital_router import router as capital_router
from adapters.primary_api.v1.fastapi_coa_router import router as coa_router
from adapters.primary_api.v1.fastapi_consolidation_router import router as consolidation_router
from adapters.primary_api.v1.fastapi_currency_exchange_router import (
    router as currency_exchange_router,
)
from adapters.primary_api.v1.fastapi_customer_router import router as customer_router
from adapters.primary_api.v1.fastapi_document_router import router as document_router
from adapters.primary_api.v1.fastapi_employee_router import router as employee_router
from adapters.primary_api.v1.fastapi_fiscal_period_router import router as fiscal_period_router
from adapters.primary_api.v1.fastapi_fixed_asset_router import router as fixed_asset_router
from adapters.primary_api.v1.fastapi_forex_router import router as forex_router
from adapters.primary_api.v1.fastapi_goodwill_router import router as goodwill_router
from adapters.primary_api.v1.fastapi_hedge_router import router as hedge_router
from adapters.primary_api.v1.fastapi_iam_router import router as iam_router
from adapters.primary_api.v1.fastapi_intangible_asset_router import (
    router as intangible_asset_router,
)
from adapters.primary_api.v1.fastapi_inventory_router import router as inventory_router
from adapters.primary_api.v1.fastapi_journal_router import router as journal_router
from adapters.primary_api.v1.fastapi_ledger_router import router as ledger_router
from adapters.primary_api.v1.fastapi_legal_entity_router import router as legal_entity_router
from adapters.primary_api.v1.fastapi_maintenance_router import router as maintenance_router
from adapters.primary_api.v1.fastapi_manufacturing_router import router as manufacturing_router
from adapters.primary_api.v1.fastapi_payment_router import router as payment_router
from adapters.primary_api.v1.fastapi_payroll_router import router as payroll_router
from adapters.primary_api.v1.fastapi_project_router import router as project_router
from adapters.primary_api.v1.fastapi_purchase_sales_router import router as purchase_sales_router
from adapters.primary_api.v1.fastapi_report_router import router as report_router
from adapters.primary_api.v1.fastapi_supplier_router import router as supplier_router
from adapters.primary_api.v1.fastapi_system_settings_router import router as system_settings_router
from adapters.primary_api.v1.fastapi_tax_coretax_router import router as tax_router
from adapters.primary_api.v1.fastapi_umkm_router import router as umkm_router

__all__ = [
    "ap_router",
    "approval_router",
    "ar_router",
    "audit_router",
    "bank_cash_router",
    "budget_router",
    "capital_router",
    "coa_router",
    "consolidation_router",
    "currency_exchange_router",
    "customer_router",
    "document_router",
    "employee_router",
    "fiscal_period_router",
    "fixed_asset_router",
    "forex_router",
    "goodwill_router",
    "hedge_router",
    "iam_router",
    "intangible_asset_router",
    "inventory_router",
    "journal_router",
    "ledger_router",
    "legal_entity_router",
    "maintenance_router",
    "manufacturing_router",
    "payment_router",
    "payroll_router",
    "project_router",
    "purchase_sales_router",
    "report_router",
    "supplier_router",
    "system_settings_router",
    "tax_router",
    "umkm_router",
]
