# infrastructure/persistence_orm/__init__.py
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import Column, DateTime, ForeignKey, Table
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from infrastructure.persistence_orm.base_model import Base, TimestampMixin

logger = logging.getLogger(__name__)

# ============================================================================
# 1. LEGAL ENTITY (harus pertama agar FK ke legal_entity bisa di-resolve)
# ============================================================================
# ============================================================================
# 2. IAM TABLES (user, role, permission, session, login attempt)
# ============================================================================
from infrastructure.persistence_orm.iam_user_table import (
    IAMPermissionTable,
    IAMRoleTable,
    IAMSessionTable,
    IAMUserTable,
    LoginAttemptTable,
    iam_role_permission,
    iam_user_role,
)
from infrastructure.persistence_orm.legal_entity_table import LegalEntityTable

# ============================================================================
# 3. JUNCTION TABLE: iam_user_legal_entity
# (didefinisikan di sini setelah legal_entity dan iam_user siap)
# ============================================================================
iam_user_legal_entity = Table(
    "iam_user_legal_entity",
    Base.metadata,
    Column("user_id", PGUUID(as_uuid=True), ForeignKey("iam_user.id"), primary_key=True),
    Column("legal_entity_id", PGUUID(as_uuid=True), ForeignKey("legal_entity.id"), primary_key=True),
    Column("assigned_at", DateTime(timezone=True), server_default="now()"),
    Column("assigned_by", PGUUID(as_uuid=True), nullable=True),
    extend_existing=True,
)

# ============================================================================
# 4. PROJECTION / READ MODELS
# ============================================================================
# ============================================================================
# AUTO-GENERATED: All remaining ORM table imports (P48 fix)
# ============================================================================
from infrastructure.persistence_orm.account_table import AccountTable
from infrastructure.persistence_orm.aggregate_snapshot_table import AggregateSnapshotTable
from infrastructure.persistence_orm.aml_risk_score_table import AMLRiskScoreTable
from infrastructure.persistence_orm.aml_suspicious_transaction_table import (
    AMLSuspiciousTransactionTable,
)
from infrastructure.persistence_orm.amortization_schedule_table import AmortizationScheduleTable
from infrastructure.persistence_orm.ap_credit_note_table import APCreditNoteTable
from infrastructure.persistence_orm.ap_invoice_line_table import APInvoiceLineTable
from infrastructure.persistence_orm.ap_invoice_table import APInvoiceTable
from infrastructure.persistence_orm.ap_payment_table import APPaymentTable
from infrastructure.persistence_orm.approval_request_table import ApprovalRequestTable
from infrastructure.persistence_orm.approval_rule_table import ApprovalRuleTable
from infrastructure.persistence_orm.ar_credit_note_table import ARCreditNoteTable
from infrastructure.persistence_orm.ar_invoice_line_table import ARInvoiceLineTable
from infrastructure.persistence_orm.ar_invoice_table import ARInvoiceTable
from infrastructure.persistence_orm.ar_payment_table import ARPaymentTable
from infrastructure.persistence_orm.asset_category_alias_table import AssetCategorySingularTable
from infrastructure.persistence_orm.asset_category_table import AssetCategoryTable
from infrastructure.persistence_orm.audit_event_table import AuditEventTable
from infrastructure.persistence_orm.audit_table import AuditTable
from infrastructure.persistence_orm.bank_account_table import BankAccountTable
from infrastructure.persistence_orm.bank_reconciliation_alias_table import (
    BankReconciliationAliasTable,
)
from infrastructure.persistence_orm.bank_reconciliation_table import (
    BankReconciliationItemTable,
    BankReconciliationTable,
)
from infrastructure.persistence_orm.bank_transaction_table import BankTransactionTable
from infrastructure.persistence_orm.bill_of_materials_line_table import BillOfMaterialsLineTable
from infrastructure.persistence_orm.bill_of_materials_table import BillOfMaterialsTable
from infrastructure.persistence_orm.budget_actual_table import BudgetActualTable
from infrastructure.persistence_orm.budget_table import BudgetTable
from infrastructure.persistence_orm.cash_book_table import CashBookTable
from infrastructure.persistence_orm.company_entity_table import CompanyEntityTable
from infrastructure.persistence_orm.consolidation_group_member_table import (
    ConsolidationGroupMemberTable,
)
from infrastructure.persistence_orm.consolidation_group_table import ConsolidationGroupTable
from infrastructure.persistence_orm.coretax_audit_log_table import CoretaxAuditLogTable
from infrastructure.persistence_orm.coretax_bupot_table import CoretaxBupotTable
from infrastructure.persistence_orm.coretax_emeterai_table import CoretaxEMeteraiTable

# ============================================================================
# 6. CORETAX
# ============================================================================
from infrastructure.persistence_orm.coretax_faktur_keluaran_table import CoretaxFakturKeluaranTable
from infrastructure.persistence_orm.coretax_faktur_line_table import CoretaxFakturLineTable
from infrastructure.persistence_orm.coretax_faktur_masukan_table import CoretaxFakturMasukanTable
from infrastructure.persistence_orm.coretax_faktur_table import CoretaxFakturTable
from infrastructure.persistence_orm.coretax_nsfp_table import CoretaxNSFPTable
from infrastructure.persistence_orm.coretax_ntpn_table import CoretaxNTPNTable
from infrastructure.persistence_orm.coretax_spt_electronic_table import CoretaxSptElectronicTable
from infrastructure.persistence_orm.coretax_spt_table import CoretaxSPTTable
from infrastructure.persistence_orm.coretax_submission_log_table import CoretaxSubmissionLogTable
from infrastructure.persistence_orm.coretax_webhook_inbound_table import CoretaxWebhookInboundTable
from infrastructure.persistence_orm.cost_card_table import CostCardTable
from infrastructure.persistence_orm.customer_table import CustomerTable
from infrastructure.persistence_orm.dead_letter_table import DeadLetterTable
from infrastructure.persistence_orm.delivery_order_lines_table import DeliveryOrderLinesTable

# ============================================================================
# 9. DELIVERY ORDER
# ============================================================================
from infrastructure.persistence_orm.delivery_order_table import (
    DeliveryOrderLineTable,
    DeliveryOrderTable,
)
from infrastructure.persistence_orm.depreciation_schedule_table import DepreciationScheduleTable
from infrastructure.persistence_orm.derivative_instrument_table import DerivativeInstrumentTable
from infrastructure.persistence_orm.disposal_table import DisposalTable
from infrastructure.persistence_orm.employee_table import EmployeeTable

# ============================================================================
# 11. EQUITY
# ============================================================================
from infrastructure.persistence_orm.equity_tables import (
    CapitalContributionTable,
    DividendDeclarationTable,
    RetainedEarningsHistoryTable,
)
from infrastructure.persistence_orm.event_store_table import EventStoreTable
from infrastructure.persistence_orm.exchange_rate_table import ExchangeRateTable
from infrastructure.persistence_orm.fair_value_hierarchy_table import FairValueHierarchyTable
from infrastructure.persistence_orm.fiscal_period_table import FiscalPeriodTable
from infrastructure.persistence_orm.fixed_asset_schedule_table import FixedAssetScheduleTable
from infrastructure.persistence_orm.fixed_asset_table import FixedAssetTable
from infrastructure.persistence_orm.general_ledger_table import GeneralLedgerEntry

# ============================================================================
# 13. GOODS RECEIPT LINE & SALES ORDER LINE
# ============================================================================
from infrastructure.persistence_orm.goods_receipt_line_table import GoodsReceiptLineTable
from infrastructure.persistence_orm.goods_receipt_note_table import (
    GoodsReceiptNoteLineTable,
    GoodsReceiptNoteTable,
)
from infrastructure.persistence_orm.goodwill_impairment_table import GoodwillImpairmentTable
from infrastructure.persistence_orm.goodwill_table import GoodwillTable
from infrastructure.persistence_orm.hash_chain_table import HashChainTable
from infrastructure.persistence_orm.hedge_effectiveness_test_table import (
    HedgeEffectivenessTestTable,
)
from infrastructure.persistence_orm.hedge_instrument_table import HedgeInstrumentTable
from infrastructure.persistence_orm.hedged_item_table import HedgedItemTable
from infrastructure.persistence_orm.hedging_relationship_table import HedgingRelationshipTable
from infrastructure.persistence_orm.impairment_test_table import ImpairmentTestTable
from infrastructure.persistence_orm.intangible_asset_table import IntangibleAssetTable
from infrastructure.persistence_orm.intangible_revaluation_table import IntangibleRevaluationTable
from infrastructure.persistence_orm.integrity_check_result_table import IntegrityCheckResultTable
from infrastructure.persistence_orm.inventory_fifo_layer_table import InventoryFIFOLayerTable
from infrastructure.persistence_orm.inventory_item_table import InventoryItemTable
from infrastructure.persistence_orm.inventory_movement_table import InventoryMovementTable
from infrastructure.persistence_orm.inventory_stock_card_table import InventoryStockCardTable
from infrastructure.persistence_orm.journal_header_table import JournalHeaderTable
from infrastructure.persistence_orm.journal_line_partitioned_table import (
    JournalLinePartitionedTable,
)
from infrastructure.persistence_orm.journal_line_table import JournalLineTable
from infrastructure.persistence_orm.journal_line_template_table import JournalLineTemplateTable
from infrastructure.persistence_orm.ledger_entry_partitioned_table import (
    LedgerEntryPartitionedTable,
)
from infrastructure.persistence_orm.ledger_entry_table import LedgerEntryTable
from infrastructure.persistence_orm.ledger_entry_template_table import LedgerEntryTemplateTable
from infrastructure.persistence_orm.legal_entity_branch_table import LegalEntityBranchTable
from infrastructure.persistence_orm.login_attempt_orm_table import LoginAttemptOrmTable
from infrastructure.persistence_orm.machine_table import MachineTable
from infrastructure.persistence_orm.manufacturing_cost_card_table import ManufacturingCostCardTable

# ============================================================================
# 7. MANUFACTURING
# ============================================================================
from infrastructure.persistence_orm.manufacturing_routing_table import RoutingTable
from infrastructure.persistence_orm.manufacturing_wip_table import WorkInProcessTable
from infrastructure.persistence_orm.manufacturing_work_order_table import (
    ManufacturingWorkOrderTable,
)
from infrastructure.persistence_orm.outbox_checkpoint_table import OutboxCheckpointTable
from infrastructure.persistence_orm.outbox_dead_letter_table import OutboxDeadLetterTable
from infrastructure.persistence_orm.outbox_kafka_partition_checkpoint_table import (
    OutboxKafkaPartitionCheckpointTable,
)
from infrastructure.persistence_orm.outbox_relay_checkpoint_table import OutboxRelayCheckpointTable
from infrastructure.persistence_orm.outbox_relay_metrics_table import OutboxRelayMetricsTable
from infrastructure.persistence_orm.outbox_table import OutboxTable

# ============================================================================
# 8. PAYROLL
# ============================================================================
from infrastructure.persistence_orm.payroll_detail_table import (
    PayrollAdjustmentTable,
    PayrollDetailTable,
    SalaryStructureTable,
)
from infrastructure.persistence_orm.payroll_payslip_orm_table import PayrollPayslipOrmTable
from infrastructure.persistence_orm.payroll_run_table import PayrollRunTable
from infrastructure.persistence_orm.payslip_table import PayslipTable
from infrastructure.persistence_orm.petty_cash_fund_table import PettyCashFundTable
from infrastructure.persistence_orm.project_table import ProjectTable
from infrastructure.persistence_orm.projection_checkpoint_table import ProjectionCheckpointTable
from infrastructure.persistence_orm.projection_read_models import (
    ProjectionAPAgingTable,
    ProjectionARAgingTable,
    ProjectionCoretaxDashboardTable,
    ProjectionFinancialRatiosTable,
    ProjectionGLTable,
    ProjectionKpiAlerterTable,
    ProjectionPPHSummaryTable,
    ProjectionPPNSettlementTable,
    ProjectionProfitabilitySegmentTable,
    ProjectionTrend12MonthTable,
    ProjectionTrialBalanceTable,
    ProjectionVarianceAnalysisTable,
)
from infrastructure.persistence_orm.purchase_order_lines_table import PurchaseOrderLinesTable
from infrastructure.persistence_orm.purchase_order_table import (
    PurchaseOrderLineTable,
    PurchaseOrderTable,
)
from infrastructure.persistence_orm.report_definition_table import ReportDefinitionTable
from infrastructure.persistence_orm.report_output_table import ReportOutputTable
from infrastructure.persistence_orm.report_schedule_table import ReportScheduleTable
from infrastructure.persistence_orm.retainer_contract_table import RetainerContractTable
from infrastructure.persistence_orm.revaluation_table import RevaluationTable
from infrastructure.persistence_orm.routing_step_table import RoutingStepTable

# ============================================================================
# 5. SAGA ORCHESTRATION
# ============================================================================
from infrastructure.persistence_orm.saga_orchestration_table import (
    SagaEventTable,
    SagaInstanceTable,
    SagaLockTable,
    SagaStepLogTable,
)
from infrastructure.persistence_orm.saga_state_table import SagaStateTable
from infrastructure.persistence_orm.salary_component_table import SalaryComponentTable
from infrastructure.persistence_orm.sales_invoice_table import SalesInvoiceTable
from infrastructure.persistence_orm.sales_order_line_table import SalesOrderLineTable
from infrastructure.persistence_orm.sales_order_lines_table import SalesOrderLinesTable
from infrastructure.persistence_orm.sales_order_table import SalesOrderTable
from infrastructure.persistence_orm.snapshot_store_table import SnapshotStoreTable
from infrastructure.persistence_orm.stock_card_table import StockCardTable
from infrastructure.persistence_orm.stock_opname_line_table import StockOpnameLineTable
from infrastructure.persistence_orm.stock_opname_lines_table import StockOpnameLinesTable
from infrastructure.persistence_orm.stock_opname_table import StockOpnameTable
from infrastructure.persistence_orm.supplier_table import SupplierTable
from infrastructure.persistence_orm.system_setting_table import SystemSettingTable

# ============================================================================
# 12. TAX SETTLEMENT
# ============================================================================
from infrastructure.persistence_orm.tax_settlement_table import (
    PphWithholdingSummaryTable,
    PpnSettlementTable,
)
from infrastructure.persistence_orm.tax_transaction_table import TaxTransactionTable
from infrastructure.persistence_orm.time_entry_table import TimeEntryTable
from infrastructure.persistence_orm.umkm_business_profile_alias_table import (
    UmkmBusinessProfileTable,
)
from infrastructure.persistence_orm.umkm_business_profile_table import UMKMProfileTable

# ============================================================================
# 10. UMKM
# ============================================================================
from infrastructure.persistence_orm.umkm_journal_table import UmkmJournalTable
from infrastructure.persistence_orm.umkm_transaction_table import UMKMTransactionTable
from infrastructure.persistence_orm.warehouse_table import WarehouseTable
from infrastructure.persistence_orm.work_order_table import WorkOrderTable

# ============================================================================
# DAFTAR SEMUA MODEL UNTUK DIEKSPOR
# ============================================================================
__all__ = [
    # IAM
    "IAMUserTable",
    "IAMRoleTable",
    "IAMPermissionTable",
    "IAMSessionTable",
    "LoginAttemptTable",
    "iam_user_role",
    "iam_role_permission",
    "iam_user_legal_entity",  # penting untuk diekspor
    # Projection
    "ProjectionGLTable",
    "ProjectionTrialBalanceTable",
    "ProjectionARAgingTable",
    "ProjectionAPAgingTable",
    "ProjectionPPNSettlementTable",
    "ProjectionPPHSummaryTable",
    "ProjectionCoretaxDashboardTable",
    "ProjectionTrend12MonthTable",
    "ProjectionVarianceAnalysisTable",
    "ProjectionProfitabilitySegmentTable",
    "ProjectionFinancialRatiosTable",
    "ProjectionKpiAlerterTable",
    # Saga
    "SagaInstanceTable",
    "SagaStepLogTable",
    "SagaLockTable",
    "SagaEventTable",
    # Coretax
    "CoretaxFakturKeluaranTable",
    "CoretaxFakturMasukanTable",
    # Manufacturing
    "RoutingTable",
    "RoutingStepTable",
    "WorkInProcessTable",
    # Payroll
    "SalaryStructureTable",
    "PayrollDetailTable",
    "PayrollAdjustmentTable",
    # Delivery Order
    "DeliveryOrderTable",
    "DeliveryOrderLineTable",
    # UMKM
    "UmkmJournalTable",
    # Equity
    "CapitalContributionTable",
    "DividendDeclarationTable",
    "RetainedEarningsHistoryTable",
    # Tax Settlement
    "PpnSettlementTable",
    "PphWithholdingSummaryTable",
    # Goods Receipt Line & Sales Order Line
    "GoodsReceiptLineTable",
    "SalesOrderLineTable",
    # Legal Entity
    "LegalEntityTable",
    # Auto-generated (P48 fix)
    "AMLRiskScoreTable",
    "AMLSuspiciousTransactionTable",
    "APCreditNoteTable",
    "APInvoiceLineTable",
    "APInvoiceTable",
    "APPaymentTable",
    "ARCreditNoteTable",
    "ARInvoiceLineTable",
    "ARInvoiceTable",
    "ARPaymentTable",
    "AccountTable",
    "AmortizationScheduleTable",
    "ApprovalRequestTable",
    "ApprovalRuleTable",
    "AssetCategoryTable",
    "AuditEventTable",
    "BankAccountTable",
    "BankReconciliationItemTable",
    "BankReconciliationTable",
    "BankTransactionTable",
    "BillOfMaterialsLineTable",
    "BillOfMaterialsTable",
    "BudgetActualTable",
    "BudgetTable",
    "CashBookTable",
    "CompanyEntityTable",
    "ConsolidationGroupMemberTable",
    "ConsolidationGroupTable",
    "CoretaxBupotTable",
    "CoretaxEMeteraiTable",
    "CoretaxFakturLineTable",
    "CoretaxFakturTable",
    "CoretaxNSFPTable",
    "CoretaxNTPNTable",
    "CoretaxSPTTable",
    "CoretaxSubmissionLogTable",
    "CostCardTable",
    "CustomerTable",
    "DeadLetterTable",
    "DepreciationScheduleTable",
    "DisposalTable",
    "EmployeeTable",
    "EventStoreTable",
    "ExchangeRateTable",
    "FiscalPeriodTable",
    "FixedAssetScheduleTable",
    "FixedAssetTable",
    "GeneralLedgerEntry",
    "GoodsReceiptNoteLineTable",
    "GoodsReceiptNoteTable",
    "GoodwillImpairmentTable",
    "GoodwillTable",
    "HashChainTable",
    "HedgeEffectivenessTestTable",
    "HedgeInstrumentTable",
    "HedgedItemTable",
    "ImpairmentTestTable",
    "IntangibleAssetTable",
    "IntangibleRevaluationTable",
    "InventoryFIFOLayerTable",
    "InventoryItemTable",
    "InventoryMovementTable",
    "InventoryStockCardTable",
    "JournalHeaderTable",
    "JournalLineTable",
    "LedgerEntryTable",
    "LegalEntityBranchTable",
    "MachineTable",
    "ManufacturingCostCardTable",
    "ManufacturingWorkOrderTable",
    "OutboxCheckpointTable",
    "OutboxTable",
    "PayrollRunTable",
    "PayslipTable",
    "PettyCashFundTable",
    "ProjectTable",
    "ProjectionCheckpointTable",
    "PurchaseOrderLineTable",
    "PurchaseOrderTable",
    "ReportDefinitionTable",
    "ReportOutputTable",
    "ReportScheduleTable",
    "RetainerContractTable",
    "RevaluationTable",
    "SagaStateTable",
    "SalaryComponentTable",
    "SalesInvoiceTable",
    "SalesOrderTable",
    "SnapshotStoreTable",
    "StockCardTable",
    "StockOpnameLineTable",
    "StockOpnameTable",
    "SupplierTable",
    "SystemSettingTable",
    "TaxTransactionTable",
    "TimeEntryTable",
    "UMKMProfileTable",
    "UMKMTransactionTable",
    "WarehouseTable",
    "WorkOrderTable",
    "AggregateSnapshotTable",
    "AuditTable",
    "CoretaxAuditLogTable",
    "CoretaxSptElectronicTable",
    "CoretaxWebhookInboundTable",
    "DeliveryOrderLinesTable",
    "DerivativeInstrumentTable",
    "FairValueHierarchyTable",
    "HedgingRelationshipTable",
    "IntegrityCheckResultTable",
    "JournalLinePartitionedTable",
    "LedgerEntryPartitionedTable",
    "OutboxDeadLetterTable",
    "OutboxKafkaPartitionCheckpointTable",
    "OutboxRelayCheckpointTable",
    "OutboxRelayMetricsTable",
    "PurchaseOrderLinesTable",
    "SalesOrderLinesTable",
    "StockOpnameLinesTable",
    "BankReconciliationAliasTable",
    "JournalLineTemplateTable",
    "LedgerEntryTemplateTable",
    "UmkmBusinessProfileTable",
    "LoginAttemptOrmTable",
    "PayrollPayslipOrmTable",
    "AssetCategorySingularTable",
]

logger.info(f"Loaded {len(__all__)} ORM models from persistence_orm package.")
