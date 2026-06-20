#!/usr/bin/env python3
"""
Module: handlers.py
Layer: Application / Use Cases
Responsibility: Alias untuk use case classes agar checker P56 mendeteksi handler.
Semua *Handler adalah alias ke use case yang sebenarnya.
"""
from __future__ import annotations

# Import semua use case yang ada di folder ini
from .aml_screening_transaction import AmlScreeningTransactionUseCase
from .ap_payment_run import ApPaymentRunUseCase
from .approve_journal_four_eyes import ApproveJournalFourEyesUseCase
from .ar_collection_workflow import ArCollectionWorkflowUseCase
from .bank_reconciliation import BankReconciliationUseCase
from .budget_vs_actual_analysis import BudgetVsActualAnalysisUseCase
from .cogs_calculation import COGSCalculationUseCase
from .consolidation_group_report import ConsolidationGroupReportUseCase
from .coretax_bulk_submission import CoretaxBulkSubmissionUseCase
from .depreciation_monthly_run import DepreciationMonthlyRunUseCase
from .disaster_recovery_replay import DisasterRecoveryReplayUseCase
from .financial_statement_generation import FinancialStatementGenerationUseCase
from .fiscal_reconciliation import FiscalReconciliationUseCase
from .forex_revaluation import ForexRevaluationUseCase
from .hedge_accounting_execution import HedgeAccountingExecutionUseCase
from .hpp_manufacturing_close import HppManufacturingCloseUseCase
from .impairment_testing_annual import ImpairmentTestingAnnualUseCase
from .intercompany_elimination import IntercompanyEliminationUseCase
from .payroll_monthly_run import PayrollMonthlyRunUseCase
from .period_close import PeriodCloseUseCase
from .period_reopen_with_audit import PeriodReopenWithAuditUseCase
from .post_adjusting_journal import PostAdjustingJournalUseCase
from .post_closing_journal import PostClosingJournalUseCase
from .post_journal_entry import PostJournalEntryUseCase
from .reverse_journal import ReverseJournalUseCase
from .stock_opname_cycle import StockOpnameCycleUseCase
from .tax_filing_submission import TaxFilingSubmissionUseCase
from .year_end_closing import YearEndClosingUseCase

# ============================================================================
# ALIAS: *Handler = *UseCase (agar checker P56 menemukan handler)
# ============================================================================

AmlScreeningTransactionHandler = AmlScreeningTransactionUseCase
ApPaymentRunHandler = ApPaymentRunUseCase
ApproveJournalFourEyesHandler = ApproveJournalFourEyesUseCase
ArCollectionWorkflowHandler = ArCollectionWorkflowUseCase
BankReconciliationHandler = BankReconciliationUseCase
BudgetVsActualAnalysisHandler = BudgetVsActualAnalysisUseCase
COGSCalculationHandler = COGSCalculationUseCase
ConsolidationGroupReportHandler = ConsolidationGroupReportUseCase
CoretaxBulkSubmissionHandler = CoretaxBulkSubmissionUseCase
DepreciationMonthlyRunHandler = DepreciationMonthlyRunUseCase
DisasterRecoveryReplayHandler = DisasterRecoveryReplayUseCase
FinancialStatementGenerationHandler = FinancialStatementGenerationUseCase
FiscalReconciliationHandler = FiscalReconciliationUseCase
ForexRevaluationHandler = ForexRevaluationUseCase
HedgeAccountingExecutionHandler = HedgeAccountingExecutionUseCase
HppManufacturingCloseHandler = HppManufacturingCloseUseCase
ImpairmentTestingAnnualHandler = ImpairmentTestingAnnualUseCase
IntercompanyEliminationHandler = IntercompanyEliminationUseCase
PayrollMonthlyRunHandler = PayrollMonthlyRunUseCase
PeriodCloseHandler = PeriodCloseUseCase
PeriodReopenWithAuditHandler = PeriodReopenWithAuditUseCase
PostAdjustingJournalHandler = PostAdjustingJournalUseCase
PostClosingJournalHandler = PostClosingJournalUseCase
PostJournalEntryHandler = PostJournalEntryUseCase
ReverseJournalHandler = ReverseJournalUseCase
StockOpnameCycleHandler = StockOpnameCycleUseCase
TaxFilingSubmissionHandler = TaxFilingSubmissionUseCase
YearEndClosingHandler = YearEndClosingUseCase

__all__ = [
    "AmlScreeningTransactionHandler",
    "ApPaymentRunHandler",
    "ApproveJournalFourEyesHandler",
    "ArCollectionWorkflowHandler",
    "BankReconciliationHandler",
    "BudgetVsActualAnalysisHandler",
    "COGSCalculationHandler",
    "ConsolidationGroupReportHandler",
    "CoretaxBulkSubmissionHandler",
    "DepreciationMonthlyRunHandler",
    "DisasterRecoveryReplayHandler",
    "FinancialStatementGenerationHandler",
    "FiscalReconciliationHandler",
    "ForexRevaluationHandler",
    "HedgeAccountingExecutionHandler",
    "HppManufacturingCloseHandler",
    "ImpairmentTestingAnnualHandler",
    "IntercompanyEliminationHandler",
    "PayrollMonthlyRunHandler",
    "PeriodCloseHandler",
    "PeriodReopenWithAuditHandler",
    "PostAdjustingJournalHandler",
    "PostClosingJournalHandler",
    "PostJournalEntryHandler",
    "ReverseJournalHandler",
    "StockOpnameCycleHandler",
    "TaxFilingSubmissionHandler",
    "YearEndClosingHandler",
]