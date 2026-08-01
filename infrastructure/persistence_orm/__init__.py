# infrastructure/persistence_orm/__init__.py
"""
Package: infrastructure.persistence_orm
SQLAlchemy ORM models and tables - lazy imports to avoid circular dependencies.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ============================================================================
# DAFTAR SEMUA MODUL YANG SEHARUSNYA ADA
# ============================================================================
_MODULE_NAMES = [
    "account_table",
    "aggregate_snapshot_table",
    "aml_risk_score_table",
    "aml_suspicious_transaction_table",
    "amortization_schedule_table",
    "ap_credit_note_table",
    "ap_invoice_line_table",
    "ap_invoice_table",
    "ap_payment_table",
    "approval_request_table",
    "approval_rule_table",
    "ar_credit_note_table",
    "ar_debit_note_table",
    "ar_invoice_line_table",
    "ar_invoice_table",
    "ar_payment_table",
    "asset_category_alias_table",
    "asset_category_table",
    "audit_event_table",
    "audit_table",
    "bank_account_table",
    "bank_reconciliation_alias_table",
    "bank_reconciliation_table",
    "bank_transaction_table",
    "base_model",
    "bill_of_materials_line_table",
    "bill_of_materials_table",
    "budget_actual_table",
    "budget_table",
    "cash_book_table",
    "company_entity_table",
    "consolidation_group_member_table",
    "consolidation_group_table",
    "coretax_audit_log_table",
    "coretax_bupot_table",
    "coretax_emeterai_table",
    "coretax_faktur_keluaran_table",
    "coretax_faktur_line_table",
    "coretax_faktur_masukan_table",
    "coretax_faktur_table",
    "coretax_nsfp_table",
    "coretax_ntpn_table",
    "coretax_spt_electronic_table",
    "coretax_spt_table",
    "coretax_submission_log_table",
    "coretax_webhook_inbound_table",
    "cost_card_table",
    "customer_table",
    "dead_letter_table",
    "delivery_order_lines_table",
    "delivery_order_table",
    "depreciation_schedule_table",
    "derivative_instrument_table",
    "disposal_table",
    "employee_table",
    "equity_tables",
    "event_store_table",
    "exchange_rate_table",
    "fair_value_hierarchy_table",
    "fiscal_period_table",
    "fixed_asset_schedule_table",
    "fixed_asset_table",
    "general_ledger_table",
    "goods_receipt_line_table",
    "goods_receipt_note_table",
    "goodwill_impairment_table",
    "goodwill_table",
    "hash_chain_table",
    "hedge_effectiveness_test_table",
    "hedge_instrument_table",
    "hedged_item_table",
    "hedging_relationship_table",
    "iam_user_table",
    "impairment_test_table",
    "intangible_asset_table",
    "intangible_revaluation_table",
    "integrity_check_result_table",
    "inventory_fifo_layer_table",
    "inventory_item_table",
    "inventory_movement_table",
    "inventory_stock_card_table",
    "journal_header_table",
    "journal_line_partitioned_table",
    "journal_line_table",
    "journal_line_template_table",
    "ledger_entry_partitioned_table",
    "ledger_entry_table",
    "ledger_entry_template_table",
    "legal_entity_branch_table",
    "legal_entity_table",
    "login_attempt_orm_table",
    "machine_table",
    "manufacturing_cost_card_table",
    "manufacturing_routing_table",
    "manufacturing_wip_table",
    "manufacturing_work_order_table",
    "outbox_checkpoint_table",
    "outbox_dead_letter_table",
    "outbox_kafka_partition_checkpoint_table",
    "outbox_relay_checkpoint_table",
    "outbox_relay_metrics_table",
    "outbox_table",
    "payroll_detail_table",
    "payroll_run_table",
    "payslip_table",
    "petty_cash_fund_table",
    "project_table",
    "projection_checkpoint_table",
    "projection_read_models",
    "purchase_order_lines_table",
    "purchase_order_table",
    "report_definition_table",
    "report_output_table",
    "report_schedule_table",
    "retainer_contract_table",
    "revaluation_table",
    "routing_step_table",
    "saga_orchestration_table",
    "saga_state_table",
    "salary_component_table",
    "sales_invoice_table",
    "sales_order_line_table",
    "sales_order_lines_table",
    "sales_order_table",
    "snapshot_store_table",
    "stock_card_table",
    "stock_opname_line_table",
    "stock_opname_lines_table",
    "stock_opname_table",
    "supplier_table",
    "system_setting_table",
    "tax_settlement_table",
    "tax_transaction_table",
    "time_entry_table",
    "umkm_business_profile_alias_table",
    "umkm_business_profile_table",
    "umkm_journal_table",
    "umkm_transaction_table",
    "warehouse_table",
    "work_order_table",
]

# ============================================================================
# LAZY IMPORTER
# ============================================================================
def __getattr__(name: str) -> Any:
    """Lazy import modul ORM saat atribut diakses."""
    if name in _MODULE_NAMES:
        try:
            # Impor modul di dalam package yang sama
            module = importlib.import_module(f".{name}", __package__)
            return module
        except ImportError as e:
            logger.warning(f"Failed to lazy import '{name}': {e}")
            raise AttributeError(f"module {__name__} has no attribute {name}") from e
    raise AttributeError(f"module {__name__} has no attribute {name}")


# ============================================================================
# EAGER LOADER (dipanggil sekali saat startup aplikasi)
# ============================================================================
def load_all_models() -> None:
    """Import semua modul ORM secara eksplisit agar seluruh class terdaftar
    di SQLAlchemy class registry sebelum mapper relationship di-resolve.
    Wajib dipanggil sekali saat startup, sebelum request pertama masuk."""
    for name in _MODULE_NAMES:
        try:
            importlib.import_module(f".{name}", __package__)
        except ImportError as e:
            logger.warning(f"Failed to eager-load ORM module '{name}': {e}")

# ============================================================================
# EKSPOR (untuk memudahkan IDE dan static analysis)
# ============================================================================
__all__ = [*_MODULE_NAMES, "load_all_models"]

