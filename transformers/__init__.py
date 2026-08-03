#!/usr/bin/env python3
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

from __future__ import annotations

__all__ = [
    "BankStatementToReconciliationTransformer",
    "CoretaxWebhookToTaxCommandTransformer",
    "HRToPayrollTransformer",
    "MESToManufacturingTransformer",
    "ProcurementToAPTransformer",
    "SalesToARTransformer",
    "WarehouseToCOGSTransformer",
    "get_bank_statement_transformer",
    "get_coretax_webhook_transformer",
    "get_hr_to_payroll_transformer",
    "get_mes_to_manufacturing_transformer",
    "get_procurement_to_ap_transformer",
    "get_sales_to_ar_transformer",
    "get_warehouse_to_cogs_transformer",
    "handle_bank_statement_event",
    "handle_coretax_webhook",
    "handle_hr_event",
    "handle_mes_event",
    "handle_procurement_event",
    "handle_sales_event",
    "handle_warehouse_event",
]
