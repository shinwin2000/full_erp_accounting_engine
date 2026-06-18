#!/usr/bin/env python3
from __future__ import annotations

"""
Package: transformers
Layer: Transformers

Responsibility:
    Event transformers untuk mengubah event dari external system ke internal command.
    Setiap transformer memiliki metode entity dasar: validate, to_dict, from_dict,
    clone, snapshot, version, audit_trail, touch.

Modules:
    - bank_statement_to_reconciliation: Bank statement → reconciliation command
    - coretax_webhook_to_tax_command: Coretax webhook → tax command
    - hr_to_payroll: HR event → payroll command
    - mes_to_manufacturing: MES event → manufacturing command
    - procurement_to_ap: Procurement event → AP invoice command
    - sales_to_ar: Sales event → AR invoice command
    - warehouse_to_cogs: Warehouse event → COGS journal command
"""

import logging

logger = logging.getLogger(__name__)

__all__ = [
    # Bank
    "BankStatementToReconciliationTransformer",
    "get_bank_statement_transformer",
    "handle_bank_statement_event",
    # Coretax
    "CoretaxWebhookToTaxCommandTransformer",
    "get_coretax_webhook_transformer",
    "handle_coretax_webhook",
    # HR to Payroll
    "HRToPayrollTransformer",
    "get_hr_to_payroll_transformer",
    "handle_hr_event",
    # MES to Manufacturing
    "MESToManufacturingTransformer",
    "get_mes_to_manufacturing_transformer",
    "handle_mes_event",
    # Procurement to AP
    "ProcurementToAPTransformer",
    "get_procurement_to_ap_transformer",
    "handle_procurement_event",
    # Sales to AR
    "SalesToARTransformer",
    "get_sales_to_ar_transformer",
    "handle_sales_event",
    # Warehouse to COGS
    "WarehouseToCOGSTransformer",
    "get_warehouse_to_cogs_transformer",
    "handle_warehouse_event",
]
