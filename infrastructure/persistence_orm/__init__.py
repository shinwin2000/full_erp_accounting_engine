# infrastructure/persistence_orm/__init__.py
from __future__ import annotations

import importlib
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ============================================================
# BASE MODEL (harus ada)
# ============================================================
from infrastructure.persistence_orm.base_model import Base


# ============================================================
# FUNGSI BANTU UNTUK IMPORT AMAN
# ============================================================
def _safe_import(module_name: str, class_name: str):
    try:
        module = importlib.import_module(module_name)
        return getattr(module, class_name)
    except (ImportError, AttributeError):
        logger.warning(f"Model {class_name} from {module_name} not found, using None")
        return None

# ============================================================
# IMPORT SEMUA MODEL YANG DIKETAHUI ADA (berdasarkan file yang diberikan)
# ============================================================
# Legal entity & master
from infrastructure.persistence_orm.ap_invoice_line_table import APInvoiceLineTable

# AP
from infrastructure.persistence_orm.ap_invoice_table import APInvoiceTable
from infrastructure.persistence_orm.ap_payment_table import APPaymentTable
from infrastructure.persistence_orm.goods_receipt_note_table import (
    GoodsReceiptNoteLineTable,
    GoodsReceiptNoteTable,
)
from infrastructure.persistence_orm.legal_entity_table import LegalEntityTable

# Purchase & goods receipt
from infrastructure.persistence_orm.purchase_order_table import (
    PurchaseOrderLineTable,
    PurchaseOrderTable,
)
from infrastructure.persistence_orm.supplier_table import SupplierTable

# Journal & ledger (asumsikan ada)
try:
    from infrastructure.persistence_orm.general_ledger_table import GeneralLedgerEntry
    from infrastructure.persistence_orm.journal_header_table import JournalHeaderTable
    from infrastructure.persistence_orm.journal_line_table import JournalLineTable
    from infrastructure.persistence_orm.ledger_entry_table import LedgerEntryTable
except ImportError:
    JournalHeaderTable = JournalLineTable = GeneralLedgerEntry = LedgerEntryTable = None

# COA
try:
    from infrastructure.persistence_orm.account_table import AccountTable
except ImportError:
    AccountTable = None

# IAM (opsional) - menggunakan safe import
IAMPermissionTable = _safe_import("infrastructure.persistence_orm.iam_permission_table", "IAMPermissionTable")
IAMUserTable = _safe_import("infrastructure.persistence_orm.iam_user_table", "IAMUserTable")
IAMRoleTable = _safe_import("infrastructure.persistence_orm.iam_role_table", "IAMRoleTable")
LoginAttemptTable = _safe_import("infrastructure.persistence_orm.login_attempt_table", "LoginAttemptTable")

# Model lain yang mungkin belum ada (gunakan safe import)
CustomerTable = _safe_import("infrastructure.persistence_orm.customer_table", "CustomerTable")
EmployeeTable = _safe_import("infrastructure.persistence_orm.employee_table", "EmployeeTable")
APCreditNoteTable = _safe_import("infrastructure.persistence_orm.ap_credit_note_table", "APCreditNoteTable")
ARInvoiceTable = _safe_import("infrastructure.persistence_orm.ar_invoice_table", "ARInvoiceTable")
ARInvoiceLineTable = _safe_import("infrastructure.persistence_orm.ar_invoice_line_table", "ARInvoiceLineTable")
ARPaymentTable = _safe_import("infrastructure.persistence_orm.ar_payment_table", "ARPaymentTable")
ARCreditNoteTable = _safe_import("infrastructure.persistence_orm.ar_credit_note_table", "ARCreditNoteTable")
BankAccountTable = _safe_import("infrastructure.persistence_orm.bank_account_table", "BankAccountTable")
BankTransactionTable = _safe_import("infrastructure.persistence_orm.bank_transaction_table", "BankTransactionTable")
BankReconciliationTable = _safe_import("infrastructure.persistence_orm.bank_reconciliation_table", "BankReconciliationTable")
CashBookTable = _safe_import("infrastructure.persistence_orm.cash_book_table", "CashBookTable")
PettyCashFundTable = _safe_import("infrastructure.persistence_orm.petty_cash_fund_table", "PettyCashFundTable")
FiscalPeriodTable = _safe_import("infrastructure.persistence_orm.fiscal_period_table", "FiscalPeriodTable")
FixedAssetTable = _safe_import("infrastructure.persistence_orm.fixed_asset_table", "FixedAssetTable")
FixedAssetScheduleTable = _safe_import("infrastructure.persistence_orm.fixed_asset_schedule_table", "FixedAssetScheduleTable")
DepreciationScheduleTable = _safe_import("infrastructure.persistence_orm.depreciation_schedule_table", "DepreciationScheduleTable")
DisposalTable = _safe_import("infrastructure.persistence_orm.disposal_table", "DisposalTable")
RevaluationTable = _safe_import("infrastructure.persistence_orm.revaluation_table", "RevaluationTable")
ImpairmentTestTable = _safe_import("infrastructure.persistence_orm.impairment_test_table", "ImpairmentTestTable")
AssetCategoryTable = _safe_import("infrastructure.persistence_orm.asset_category_table", "AssetCategoryTable")
IntangibleAssetTable = _safe_import("infrastructure.persistence_orm.intangible_asset_table", "IntangibleAssetTable")
AmortizationScheduleTable = _safe_import("infrastructure.persistence_orm.amortization_schedule_table", "AmortizationScheduleTable")
InventoryItemTable = _safe_import("infrastructure.persistence_orm.inventory_item_table", "InventoryItemTable")
InventoryMovementTable = _safe_import("infrastructure.persistence_orm.inventory_movement_table", "InventoryMovementTable")
InventoryStockCardTable = _safe_import("infrastructure.persistence_orm.inventory_stock_card_table", "InventoryStockCardTable")
InventoryFIFOLayerTable = _safe_import("infrastructure.persistence_orm.inventory_fifo_layer_table", "InventoryFIFOLayerTable")
StockCardTable = _safe_import("infrastructure.persistence_orm.stock_card_table", "StockCardTable")
StockOpnameTable = _safe_import("infrastructure.persistence_orm.stock_opname_table", "StockOpnameTable")
StockOpnameLineTable = _safe_import("infrastructure.persistence_orm.stock_opname_line_table", "StockOpnameLineTable")
WarehouseTable = _safe_import("infrastructure.persistence_orm.warehouse_table", "WarehouseTable")
PayrollRunTable = _safe_import("infrastructure.persistence_orm.payroll_run_table", "PayrollRunTable")
PayslipTable = _safe_import("infrastructure.persistence_orm.payslip_table", "PayslipTable")
PayrollPayslipTable = _safe_import("infrastructure.persistence_orm.payroll_payslip_table", "PayslipTable")  # alias
SalaryComponentTable = _safe_import("infrastructure.persistence_orm.salary_component_table", "SalaryComponentTable")
SalesOrderTable = _safe_import("infrastructure.persistence_orm.sales_order_table", "SalesOrderTable")
SalesInvoiceTable = _safe_import("infrastructure.persistence_orm.sales_invoice_table", "SalesInvoiceTable")
ManufacturingWorkOrderTable = _safe_import("infrastructure.persistence_orm.manufacturing_work_order_table", "ManufacturingWorkOrderTable")
BillOfMaterialsTable = _safe_import("infrastructure.persistence_orm.bill_of_materials_table", "BillOfMaterialsTable")
ManufacturingCostCardTable = _safe_import("infrastructure.persistence_orm.manufacturing_cost_card_table", "ManufacturingCostCardTable")
CostCardTable = _safe_import("infrastructure.persistence_orm.cost_card_table", "CostCardTable")
WorkOrderTable = _safe_import("infrastructure.persistence_orm.work_order_table", "WorkOrderTable")
TaxTransactionTable = _safe_import("infrastructure.persistence_orm.tax_transaction_table", "TaxTransactionTable")
CoretaxFakturTable = _safe_import("infrastructure.persistence_orm.coretax_faktur_table", "CoretaxFakturTable")
CoretaxFakturLineTable = _safe_import("infrastructure.persistence_orm.coretax_faktur_line_table", "CoretaxFakturLineTable")
CoretaxBupotTable = _safe_import("infrastructure.persistence_orm.coretax_bupot_table", "CoretaxBupotTable")
CoretaxNSFPTable = _safe_import("infrastructure.persistence_orm.coretax_nsfp_table", "CoretaxNSFPTable")
CoretaxNTPNTable = _safe_import("infrastructure.persistence_orm.coretax_ntpn_table", "CoretaxNTPNTable")
CoretaxEMeteraiTable = _safe_import("infrastructure.persistence_orm.coretax_emeterai_table", "CoretaxEMeteraiTable")
CoretaxSPTTable = _safe_import("infrastructure.persistence_orm.coretax_spt_table", "CoretaxSPTTable")
ProjectTable = _safe_import("infrastructure.persistence_orm.project_table", "ProjectTable")
TimeEntryTable = _safe_import("infrastructure.persistence_orm.time_entry_table", "TimeEntryTable")
RetainerContractTable = _safe_import("infrastructure.persistence_orm.retainer_contract_table", "RetainerContractTable")
AuditEventTable = _safe_import("infrastructure.persistence_orm.audit_event_table", "AuditEventTable")
OutboxTable = _safe_import("infrastructure.persistence_orm.outbox_table", "OutboxTable")
OutboxCheckpointTable = _safe_import("infrastructure.persistence_orm.outbox_checkpoint_table", "OutboxCheckpointTable")
SagaStateTable = _safe_import("infrastructure.persistence_orm.saga_state_table", "SagaStateTable")
EventStoreTable = _safe_import("infrastructure.persistence_orm.event_store_table", "EventStoreTable")
HashChainTable = _safe_import("infrastructure.persistence_orm.hash_chain_table", "HashChainTable")
DeadLetterEvent = _safe_import("infrastructure.persistence_orm.dead_letter_table", "DeadLetterEvent")
ConsolidationGroupTable = _safe_import("infrastructure.persistence_orm.consolidation_group_table", "ConsolidationGroupTable")
ConsolidationGroupMemberTable = _safe_import("infrastructure.persistence_orm.consolidation_group_member_table", "ConsolidationGroupMemberTable")
SystemSettingTable = _safe_import("infrastructure.persistence_orm.system_setting_table", "SystemSettingTable")
LegalEntityBranchTable = _safe_import("infrastructure.persistence_orm.legal_entity_branch_table", "LegalEntityBranchTable")
ProjectionCheckpointTable = _safe_import("infrastructure.persistence_orm.projection_checkpoint_table", "ProjectionCheckpointTable")

# ============================================================
# KUMPULKAN SEMUA MODEL YANG TIDAK None KE DALAM DICTIONARY
# ============================================================
_loaded_models = {
    name: value for name, value in locals().items()
    if not name.startswith('_') and value is not None and name not in ('Base', 'logger')
}
# Tambahkan Base secara manual
_loaded_models['Base'] = Base

# ============================================================
# UPDATE GLOBALS DAN __ALL__
# ============================================================
globals().update(_loaded_models)

__all__ = list(_loaded_models.keys())

# ============================================================
# LOG INFORMASI
# ============================================================
logger.info(f"Loaded {len(_loaded_models)} ORM models (some may be missing, imported safely)")
