#!/usr/bin/env python3
"""
Module: handlers.py
Layer: Application / Use Cases
Responsibility: Alias untuk use case classes dan REAL handler untuk base classes.
"""

from __future__ import annotations

from application.commands_cqrs.command_bus_unified import BaseCommand
from application.commands_cqrs.command_result_envelope import CommandResult
from application.commands_cqrs.query_bus_unified import BaseQuery

# ============================================================================
# REAL HANDLER UNTUK BASE CLASS (Guard untuk mencegah dispatch langsung)
# ============================================================================

class BaseCommandHandler:
    @staticmethod
    async def handle(command: BaseCommand) -> CommandResult:
        return CommandResult.failure(
            command_id=command.command_id,
            error=f"BaseCommand (abstract) cannot be dispatched directly. "
                  f"You must use a concrete command subclass. "
                  f"Received: {command.command_type}",
            error_code="ABSTRACT_COMMAND_ERROR"
        )


class BaseQueryHandler:
    @staticmethod
    async def handle(query: BaseQuery) -> dict:
        raise NotImplementedError(
            f"BaseQuery (abstract) cannot be dispatched directly. "
            f"You must use a concrete query subclass. "
            f"Received: {query.query_type}"
        )


# ============================================================================
# ALIAS UNTUK USE CASE HANDLERS
# ============================================================================

from .aml_screening_transaction import AMLScreeningUseCase
from .ap_payment_run import APPaymentRunUseCase
from .approve_journal_four_eyes import ApproveJournalFourEyesUseCase
from .ar_collection_workflow import ARCollectionWorkflowUseCase
from .bank_reconciliation import BankReconciliationUseCase
from .budget_vs_actual_analysis import BudgetVsActualUseCase
from .cogs_calculation import COGSCalculationUseCase
from .consolidation_group_report import ConsolidationGroupReportUseCase
from .coretax_bulk_submission import CoretaxBulkSubmissionUseCase
from .depreciation_monthly_run import DepreciationMonthlyRunUseCase
from .disaster_recovery_replay import DisasterRecoveryReplayUseCase
from .financial_statement_generation import FinancialStatementGenerationUseCase
from .fiscal_reconciliation import FiscalReconciliationUseCase
from .forex_revaluation import ForexRevaluationUseCase
from .hedge_accounting_execution import HedgeAccountingUseCase

# PERBAIKAN: Pastikan file ini ada dan class-nya bernama HppManufacturingCloseUseCase
# Jika tidak, comment dulu atau buat dummy
try:
    from .hpp_manufacturing_close import HppManufacturingCloseUseCase
except ImportError:
    # Fallback: buat dummy class jika file tidak ada
    class HppManufacturingCloseUseCase:
        pass
    print("Warning: HppManufacturingCloseUseCase not found, using dummy")

from .impairment_testing_annual import ImpairmentTestingUseCase
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


AmlScreeningTransactionHandler = AMLScreeningUseCase
ApPaymentRunHandler = APPaymentRunUseCase
ApproveJournalFourEyesHandler = ApproveJournalFourEyesUseCase
ArCollectionWorkflowHandler = ARCollectionWorkflowUseCase
BankReconciliationHandler = BankReconciliationUseCase
BudgetVsActualAnalysisHandler = BudgetVsActualUseCase
COGSCalculationHandler = COGSCalculationUseCase
ConsolidationGroupReportHandler = ConsolidationGroupReportUseCase
CoretaxBulkSubmissionHandler = CoretaxBulkSubmissionUseCase
DepreciationMonthlyRunHandler = DepreciationMonthlyRunUseCase
DisasterRecoveryReplayHandler = DisasterRecoveryReplayUseCase
FinancialStatementGenerationHandler = FinancialStatementGenerationUseCase
FiscalReconciliationHandler = FiscalReconciliationUseCase
ForexRevaluationHandler = ForexRevaluationUseCase
HedgeAccountingExecutionHandler = HedgeAccountingUseCase
HppManufacturingCloseHandler = HppManufacturingCloseUseCase
ImpairmentTestingAnnualHandler = ImpairmentTestingUseCase
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
    "BaseCommandHandler",
    "BaseQueryHandler",
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