from __future__ import annotations

"""
Package: adapters.primary_api.v1
Router API version 1.
"""

from adapters.primary_api.v1.fastapi_ap_router import router as ap_router
from adapters.primary_api.v1.fastapi_ar_router import router as ar_router
from adapters.primary_api.v1.fastapi_bank_cash_router import router as bank_cash_router
from adapters.primary_api.v1.fastapi_coa_router import router as coa_router
from adapters.primary_api.v1.fastapi_fixed_asset_router import router as fixed_asset_router
from adapters.primary_api.v1.fastapi_inventory_router import router as inventory_router
from adapters.primary_api.v1.fastapi_journal_router import router as journal_router
from adapters.primary_api.v1.fastapi_ledger_router import router as ledger_router
from adapters.primary_api.v1.fastapi_report_router import router as report_router
from adapters.primary_api.v1.fastapi_tax_coretax_router import router as tax_router

__all__ = [
    "ap_router",
    "ar_router",
    "bank_cash_router",
    "coa_router",
    "fixed_asset_router",
    "inventory_router",
    "journal_router",
    "ledger_router",
    "report_router",
    "tax_router",
]
