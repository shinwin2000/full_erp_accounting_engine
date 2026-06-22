#!/usr/bin/env python3
"""
Module: all_event_handlers.py
Layer: Application / Events
Responsibility: Explicit handlers for EVERY domain event.
Generated automatically with specific imports (no wildcard).
"""

from __future__ import annotations

import logging
from typing import Any

from domain.bank_cash.domain_events import BankAccountBlockedEvent, BankAccountClosedEvent, BankAccountCreatedEvent, BankAccountUpdatedEvent, BankReconciliationCompletedEvent, BankTransactionClearedEvent, BankTransactionReconciledEvent, BankTransactionRecordedEvent, BankTransferCancelledEvent, BankTransferCompletedEvent, BankTransferFailedEvent, BankTransferInitiatedEvent, CashBookClosedEvent, CashBookUpdatedEvent, CashDisbursementApprovedEvent, CashDisbursementCancelledEvent, CashDisbursementPaidEvent, CashReceiptCancelledEvent, CashReceiptConfirmedEvent, PettyCashActivatedEvent, PettyCashAdjustedEvent, PettyCashClosedEvent, PettyCashDisbursementEvent, PettyCashReplenishedEvent, PettyCashSuspendedEvent
from domain.coa.domain_events import AccountCreatedEvent, AccountDeactivatedEvent, AccountLockedEvent, AccountMergedEvent, AccountReactivatedEvent, AccountSplitEvent, AccountUnlockedEvent, AccountUpdatedEvent, COAArchivedEvent, COACreatedEvent, COALockedEvent, COAUnlockedEvent, HierarchyChangedEvent
from domain.customer_supplier_employee.domain_events import CustomerBalanceUpdatedEvent, CustomerCreatedEvent, CustomerCreditLimitChangedEvent, CustomerStatusChangedEvent, EmployeeBPJSUpdatedEvent, EmployeeCreatedEvent, EmployeePTKPUpdatedEvent, EmployeeResignedEvent, SupplierCreatedEvent, SupplierPaymentTermsChangedEvent, SupplierWithholdingCategoryChangedEvent
from domain.equity_retained.domain_events import CapitalContributionApprovedEvent, CapitalContributionCancelledEvent, CapitalContributionPostedEvent, CapitalContributionRecordedEvent, CapitalWithdrawalApprovedEvent, CapitalWithdrawalCancelledEvent, CapitalWithdrawalPostedEvent, CapitalWithdrawalRecordedEvent, DividendApprovedEvent, DividendCancelledEvent, DividendDeclaredEvent, DividendPaidEvent, DividendPartiallyPaidEvent, RetainedEarningsAdjustedEvent, RetainedEarningsTransferEvent, RetainedEarningsUpdatedEvent
from domain.fiscal_period.domain_events import PeriodClosedEvent, PeriodCreatedEvent, PeriodLockedEvent, PeriodOpenedEvent, PeriodReopenedEvent, PeriodStatusChangedEvent, PeriodUpdatedEvent
from domain.fixed_asset.domain_events import AssetAcquiredEvent, AssetDepreciationPostedEvent, AssetDisposedEvent, AssetFullyDepreciatedEvent, AssetGroupCreatedEvent, AssetGroupUpdatedEvent, AssetImpairedEvent, AssetImpairmentReversedEvent, AssetRevaluatedEvent, AssetTransferredEvent, AssetUpdatedEvent
from domain.goodwill.domain_events import GoodwillAmortizedEvent, GoodwillDisposedEvent, GoodwillImpairedEvent, GoodwillImpairmentReversedEvent, GoodwillRecognizedEvent
from domain.hedge.domain_events import HedgeAmountReclassifiedEvent, HedgeCancelledEvent, HedgeDesignatedEvent, HedgeDiscontinuedEvent, HedgeEffectivenessTestedEvent, HedgeFairValueAdjustedEvent
from domain.iam.domain_events import LoginFailureEvent, LoginSuccessEvent, PermissionGrantedEvent, PermissionRevokedEvent, RoleAssignedEvent, RoleCreatedEvent, RoleDeletedEvent, RoleRevokedEvent, RoleUpdatedEvent, SessionCompromisedEvent, SessionCreatedEvent, SessionRefreshedEvent, SessionTerminatedEvent, UserActivatedEvent, UserCreatedEvent, UserDeactivatedEvent, UserDeletedEvent, UserPasswordChangedEvent, UserSuspendedEvent, UserUnlockedEvent, UserUpdatedEvent
from domain.intangible_asset.domain_events import IntangibleAssetAcquiredEvent, IntangibleAssetAmortizationPostedEvent, IntangibleAssetDisposedEvent, IntangibleAssetFullyAmortizedEvent, IntangibleAssetImpairedEvent, IntangibleAssetImpairmentReversedEvent, IntangibleAssetRevaluatedEvent, IntangibleAssetTransferredEvent, IntangibleAssetUpdatedEvent
from domain.inventory.domain_events import COGSCalculatedEvent, InterWarehouseTransferCreatedEvent, InventoryValuationUpdatedEvent, ItemCreatedEvent, ItemDeactivatedEvent, ItemUpdatedEvent, StockAdjustedEvent, StockLevelAlertEvent, StockMovementCreatedEvent, StockOpnameApprovedEvent, StockOpnameCreatedEvent, TransferCompletedEvent
from domain.journal.domain_events import JournalAdjustedEvent, JournalApprovedEvent, JournalArchivedEvent, JournalCancelledEvent, JournalCreatedEvent, JournalPostedEvent, JournalRejectedEvent, JournalReversedEvent, JournalSubmittedEvent, JournalUnarchivedEvent, JournalVoidedEvent
from domain.legal_entity.domain_events import CompanyAddressUpdatedEvent, CompanyContactUpdatedEvent, CompanyDissolvedEvent, CompanyReactivatedEvent, CompanyRegisteredEvent, CompanySuspendedEvent, PKPStatusChangedEvent, TaxProfileUpdatedEvent
from domain.manufacturing.domain_events import BOMActivatedEvent, BOMCreatedEvent, BOMItemAddedEvent, BOMObsoletedEvent, BOMUpdatedEvent, CostCardUpdatedEvent, HPPCalculatedEvent, LaborPostedEvent, MaterialIssuedEvent, OverheadAppliedEvent, ProductionCompletedEvent, StandardCostActivatedEvent, StandardCostCreatedEvent, VarianceAnalyzedEvent, WorkOrderApprovedEvent, WorkOrderCancelledEvent, WorkOrderCompletedEvent, WorkOrderCreatedEvent, WorkOrderStartedEvent
from domain.payroll.domain_events import EmployeeStructureUpdatedEvent, PayrollRunApprovedEvent, PayrollRunCalculatedEvent, PayrollRunCancelledEvent, PayrollRunCreatedEvent, PayrollRunPaidEvent, PayrollRunPostedEvent, PayslipGeneratedEvent, PayslipSentToEmployeeEvent, SalaryComponentAddedEvent
from domain.project_services.domain_events import MilestoneBilledEvent, MilestoneReadyEvent, ProjectActivatedEvent, ProjectBillingGeneratedEvent, ProjectCompletedEvent, ProjectCreatedEvent, RetainerContractActivatedEvent, RevenueRecognizedEvent, TimeEntryApprovedEvent, TimeEntrySubmittedEvent
from domain.purchase_sales.domain_events import DeliveryNoteShippedEvent, GoodsReceiptCreatedEvent, PurchaseInvoiceReceivedEvent, PurchaseOrderApprovedEvent, PurchaseOrderCreatedEvent, SalesInvoiceIssuedEvent, SalesInvoicePaidEvent, SalesOrderApprovedEvent, SalesOrderCreatedEvent
from domain.subledger_ap.domain_events import CreditNoteReceivedEvent, DebitNoteAppliedEvent, DebitNoteIssuedServiceEvent, InvoiceCreatedEvent, InvoiceDisputedEvent, InvoiceReceivedEvent, InvoiceVerifiedEvent, PaymentAppliedEvent, PaymentApprovedEvent, PaymentCancelledEvent, PaymentConfirmedEvent, PaymentMadeEvent, PaymentProcessedEvent, PaymentRunExecutedEvent, PaymentRunGeneratedEvent, PaymentSentEvent, PaymentVoidedEvent, ThreeWayMatchResultEvent
from domain.subledger_ar.domain_events import CreditNoteAppliedEvent, CreditNoteIssuedEvent, DebitNoteIssuedEvent, InvoiceApprovedEvent, InvoiceCancelledEvent, InvoiceIssuedEvent, InvoicePaidEvent, InvoicePartiallyPaidEvent, InvoiceWrittenOffEvent, PaymentAllocatedEvent, PaymentReceivedEvent
from domain.system_settings.domain_events import SettingAddedEvent, SettingChangedEvent, SettingRemovedEvent, SettingResetEvent, SettingsBulkUpdatedEvent, SettingsLockedEvent, SettingsUnlockedEvent
from domain.tax_transaction.domain_events import BupotApprovedEvent, BupotSubmittedEvent, FakturApprovedEvent, FakturRejectedEvent, FakturSubmittedEvent, MeteraiUsedEvent, SPTApprovedEvent, SPTSubmittedEvent
from domain.umkm_simplified.domain_events import DomainEvent, TaxCalculatedEvent, TransactionCreatedEvent, TransactionDeletedEvent, TransactionRecordedEvent, TransactionUpdatedEvent

logger = logging.getLogger(__name__)

async def handle_generic_event(event: Any) -> None:
    """Generic handler untuk semua event - hanya log."""
    logger.info(f"Domain event: {type(event).__name__}")

async def handle_AccountCreatedEvent(event: Any) -> None:
    """Handler untuk AccountCreatedEvent."""
    if isinstance(event, AccountCreatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected AccountCreatedEvent, got {type(event).__name__}")

async def handle_AccountDeactivatedEvent(event: Any) -> None:
    """Handler untuk AccountDeactivatedEvent."""
    if isinstance(event, AccountDeactivatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected AccountDeactivatedEvent, got {type(event).__name__}")

async def handle_AccountLockedEvent(event: Any) -> None:
    """Handler untuk AccountLockedEvent."""
    if isinstance(event, AccountLockedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected AccountLockedEvent, got {type(event).__name__}")

async def handle_AccountMergedEvent(event: Any) -> None:
    """Handler untuk AccountMergedEvent."""
    if isinstance(event, AccountMergedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected AccountMergedEvent, got {type(event).__name__}")

async def handle_AccountReactivatedEvent(event: Any) -> None:
    """Handler untuk AccountReactivatedEvent."""
    if isinstance(event, AccountReactivatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected AccountReactivatedEvent, got {type(event).__name__}")

async def handle_AccountSplitEvent(event: Any) -> None:
    """Handler untuk AccountSplitEvent."""
    if isinstance(event, AccountSplitEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected AccountSplitEvent, got {type(event).__name__}")

async def handle_AccountUnlockedEvent(event: Any) -> None:
    """Handler untuk AccountUnlockedEvent."""
    if isinstance(event, AccountUnlockedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected AccountUnlockedEvent, got {type(event).__name__}")

async def handle_AccountUpdatedEvent(event: Any) -> None:
    """Handler untuk AccountUpdatedEvent."""
    if isinstance(event, AccountUpdatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected AccountUpdatedEvent, got {type(event).__name__}")

async def handle_AssetAcquiredEvent(event: Any) -> None:
    """Handler untuk AssetAcquiredEvent."""
    if isinstance(event, AssetAcquiredEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected AssetAcquiredEvent, got {type(event).__name__}")

async def handle_AssetDepreciationPostedEvent(event: Any) -> None:
    """Handler untuk AssetDepreciationPostedEvent."""
    if isinstance(event, AssetDepreciationPostedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected AssetDepreciationPostedEvent, got {type(event).__name__}")

async def handle_AssetDisposedEvent(event: Any) -> None:
    """Handler untuk AssetDisposedEvent."""
    if isinstance(event, AssetDisposedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected AssetDisposedEvent, got {type(event).__name__}")

async def handle_AssetFullyDepreciatedEvent(event: Any) -> None:
    """Handler untuk AssetFullyDepreciatedEvent."""
    if isinstance(event, AssetFullyDepreciatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected AssetFullyDepreciatedEvent, got {type(event).__name__}")

async def handle_AssetGroupCreatedEvent(event: Any) -> None:
    """Handler untuk AssetGroupCreatedEvent."""
    if isinstance(event, AssetGroupCreatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected AssetGroupCreatedEvent, got {type(event).__name__}")

async def handle_AssetGroupUpdatedEvent(event: Any) -> None:
    """Handler untuk AssetGroupUpdatedEvent."""
    if isinstance(event, AssetGroupUpdatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected AssetGroupUpdatedEvent, got {type(event).__name__}")

async def handle_AssetImpairedEvent(event: Any) -> None:
    """Handler untuk AssetImpairedEvent."""
    if isinstance(event, AssetImpairedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected AssetImpairedEvent, got {type(event).__name__}")

async def handle_AssetImpairmentReversedEvent(event: Any) -> None:
    """Handler untuk AssetImpairmentReversedEvent."""
    if isinstance(event, AssetImpairmentReversedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected AssetImpairmentReversedEvent, got {type(event).__name__}")

async def handle_AssetRevaluatedEvent(event: Any) -> None:
    """Handler untuk AssetRevaluatedEvent."""
    if isinstance(event, AssetRevaluatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected AssetRevaluatedEvent, got {type(event).__name__}")

async def handle_AssetTransferredEvent(event: Any) -> None:
    """Handler untuk AssetTransferredEvent."""
    if isinstance(event, AssetTransferredEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected AssetTransferredEvent, got {type(event).__name__}")

async def handle_AssetUpdatedEvent(event: Any) -> None:
    """Handler untuk AssetUpdatedEvent."""
    if isinstance(event, AssetUpdatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected AssetUpdatedEvent, got {type(event).__name__}")

async def handle_BOMActivatedEvent(event: Any) -> None:
    """Handler untuk BOMActivatedEvent."""
    if isinstance(event, BOMActivatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected BOMActivatedEvent, got {type(event).__name__}")

async def handle_BOMCreatedEvent(event: Any) -> None:
    """Handler untuk BOMCreatedEvent."""
    if isinstance(event, BOMCreatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected BOMCreatedEvent, got {type(event).__name__}")

async def handle_BOMItemAddedEvent(event: Any) -> None:
    """Handler untuk BOMItemAddedEvent."""
    if isinstance(event, BOMItemAddedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected BOMItemAddedEvent, got {type(event).__name__}")

async def handle_BOMObsoletedEvent(event: Any) -> None:
    """Handler untuk BOMObsoletedEvent."""
    if isinstance(event, BOMObsoletedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected BOMObsoletedEvent, got {type(event).__name__}")

async def handle_BOMUpdatedEvent(event: Any) -> None:
    """Handler untuk BOMUpdatedEvent."""
    if isinstance(event, BOMUpdatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected BOMUpdatedEvent, got {type(event).__name__}")

async def handle_BankAccountBlockedEvent(event: Any) -> None:
    """Handler untuk BankAccountBlockedEvent."""
    if isinstance(event, BankAccountBlockedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected BankAccountBlockedEvent, got {type(event).__name__}")

async def handle_BankAccountClosedEvent(event: Any) -> None:
    """Handler untuk BankAccountClosedEvent."""
    if isinstance(event, BankAccountClosedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected BankAccountClosedEvent, got {type(event).__name__}")

async def handle_BankAccountCreatedEvent(event: Any) -> None:
    """Handler untuk BankAccountCreatedEvent."""
    if isinstance(event, BankAccountCreatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected BankAccountCreatedEvent, got {type(event).__name__}")

async def handle_BankAccountUpdatedEvent(event: Any) -> None:
    """Handler untuk BankAccountUpdatedEvent."""
    if isinstance(event, BankAccountUpdatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected BankAccountUpdatedEvent, got {type(event).__name__}")

async def handle_BankReconciliationCompletedEvent(event: Any) -> None:
    """Handler untuk BankReconciliationCompletedEvent."""
    if isinstance(event, BankReconciliationCompletedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected BankReconciliationCompletedEvent, got {type(event).__name__}")

async def handle_BankTransactionClearedEvent(event: Any) -> None:
    """Handler untuk BankTransactionClearedEvent."""
    if isinstance(event, BankTransactionClearedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected BankTransactionClearedEvent, got {type(event).__name__}")

async def handle_BankTransactionReconciledEvent(event: Any) -> None:
    """Handler untuk BankTransactionReconciledEvent."""
    if isinstance(event, BankTransactionReconciledEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected BankTransactionReconciledEvent, got {type(event).__name__}")

async def handle_BankTransactionRecordedEvent(event: Any) -> None:
    """Handler untuk BankTransactionRecordedEvent."""
    if isinstance(event, BankTransactionRecordedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected BankTransactionRecordedEvent, got {type(event).__name__}")

async def handle_BankTransferCancelledEvent(event: Any) -> None:
    """Handler untuk BankTransferCancelledEvent."""
    if isinstance(event, BankTransferCancelledEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected BankTransferCancelledEvent, got {type(event).__name__}")

async def handle_BankTransferCompletedEvent(event: Any) -> None:
    """Handler untuk BankTransferCompletedEvent."""
    if isinstance(event, BankTransferCompletedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected BankTransferCompletedEvent, got {type(event).__name__}")

async def handle_BankTransferFailedEvent(event: Any) -> None:
    """Handler untuk BankTransferFailedEvent."""
    if isinstance(event, BankTransferFailedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected BankTransferFailedEvent, got {type(event).__name__}")

async def handle_BankTransferInitiatedEvent(event: Any) -> None:
    """Handler untuk BankTransferInitiatedEvent."""
    if isinstance(event, BankTransferInitiatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected BankTransferInitiatedEvent, got {type(event).__name__}")

async def handle_BupotApprovedEvent(event: Any) -> None:
    """Handler untuk BupotApprovedEvent."""
    if isinstance(event, BupotApprovedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected BupotApprovedEvent, got {type(event).__name__}")

async def handle_BupotSubmittedEvent(event: Any) -> None:
    """Handler untuk BupotSubmittedEvent."""
    if isinstance(event, BupotSubmittedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected BupotSubmittedEvent, got {type(event).__name__}")

async def handle_COAArchivedEvent(event: Any) -> None:
    """Handler untuk COAArchivedEvent."""
    if isinstance(event, COAArchivedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected COAArchivedEvent, got {type(event).__name__}")

async def handle_COACreatedEvent(event: Any) -> None:
    """Handler untuk COACreatedEvent."""
    if isinstance(event, COACreatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected COACreatedEvent, got {type(event).__name__}")

async def handle_COALockedEvent(event: Any) -> None:
    """Handler untuk COALockedEvent."""
    if isinstance(event, COALockedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected COALockedEvent, got {type(event).__name__}")

async def handle_COAUnlockedEvent(event: Any) -> None:
    """Handler untuk COAUnlockedEvent."""
    if isinstance(event, COAUnlockedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected COAUnlockedEvent, got {type(event).__name__}")

async def handle_COGSCalculatedEvent(event: Any) -> None:
    """Handler untuk COGSCalculatedEvent."""
    if isinstance(event, COGSCalculatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected COGSCalculatedEvent, got {type(event).__name__}")

async def handle_CapitalContributionApprovedEvent(event: Any) -> None:
    """Handler untuk CapitalContributionApprovedEvent."""
    if isinstance(event, CapitalContributionApprovedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected CapitalContributionApprovedEvent, got {type(event).__name__}")

async def handle_CapitalContributionCancelledEvent(event: Any) -> None:
    """Handler untuk CapitalContributionCancelledEvent."""
    if isinstance(event, CapitalContributionCancelledEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected CapitalContributionCancelledEvent, got {type(event).__name__}")

async def handle_CapitalContributionPostedEvent(event: Any) -> None:
    """Handler untuk CapitalContributionPostedEvent."""
    if isinstance(event, CapitalContributionPostedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected CapitalContributionPostedEvent, got {type(event).__name__}")

async def handle_CapitalContributionRecordedEvent(event: Any) -> None:
    """Handler untuk CapitalContributionRecordedEvent."""
    if isinstance(event, CapitalContributionRecordedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected CapitalContributionRecordedEvent, got {type(event).__name__}")

async def handle_CapitalWithdrawalApprovedEvent(event: Any) -> None:
    """Handler untuk CapitalWithdrawalApprovedEvent."""
    if isinstance(event, CapitalWithdrawalApprovedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected CapitalWithdrawalApprovedEvent, got {type(event).__name__}")

async def handle_CapitalWithdrawalCancelledEvent(event: Any) -> None:
    """Handler untuk CapitalWithdrawalCancelledEvent."""
    if isinstance(event, CapitalWithdrawalCancelledEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected CapitalWithdrawalCancelledEvent, got {type(event).__name__}")

async def handle_CapitalWithdrawalPostedEvent(event: Any) -> None:
    """Handler untuk CapitalWithdrawalPostedEvent."""
    if isinstance(event, CapitalWithdrawalPostedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected CapitalWithdrawalPostedEvent, got {type(event).__name__}")

async def handle_CapitalWithdrawalRecordedEvent(event: Any) -> None:
    """Handler untuk CapitalWithdrawalRecordedEvent."""
    if isinstance(event, CapitalWithdrawalRecordedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected CapitalWithdrawalRecordedEvent, got {type(event).__name__}")

async def handle_CashBookClosedEvent(event: Any) -> None:
    """Handler untuk CashBookClosedEvent."""
    if isinstance(event, CashBookClosedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected CashBookClosedEvent, got {type(event).__name__}")

async def handle_CashBookUpdatedEvent(event: Any) -> None:
    """Handler untuk CashBookUpdatedEvent."""
    if isinstance(event, CashBookUpdatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected CashBookUpdatedEvent, got {type(event).__name__}")

async def handle_CashDisbursementApprovedEvent(event: Any) -> None:
    """Handler untuk CashDisbursementApprovedEvent."""
    if isinstance(event, CashDisbursementApprovedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected CashDisbursementApprovedEvent, got {type(event).__name__}")

async def handle_CashDisbursementCancelledEvent(event: Any) -> None:
    """Handler untuk CashDisbursementCancelledEvent."""
    if isinstance(event, CashDisbursementCancelledEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected CashDisbursementCancelledEvent, got {type(event).__name__}")

async def handle_CashDisbursementPaidEvent(event: Any) -> None:
    """Handler untuk CashDisbursementPaidEvent."""
    if isinstance(event, CashDisbursementPaidEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected CashDisbursementPaidEvent, got {type(event).__name__}")

async def handle_CashReceiptCancelledEvent(event: Any) -> None:
    """Handler untuk CashReceiptCancelledEvent."""
    if isinstance(event, CashReceiptCancelledEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected CashReceiptCancelledEvent, got {type(event).__name__}")

async def handle_CashReceiptConfirmedEvent(event: Any) -> None:
    """Handler untuk CashReceiptConfirmedEvent."""
    if isinstance(event, CashReceiptConfirmedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected CashReceiptConfirmedEvent, got {type(event).__name__}")

async def handle_CompanyAddressUpdatedEvent(event: Any) -> None:
    """Handler untuk CompanyAddressUpdatedEvent."""
    if isinstance(event, CompanyAddressUpdatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected CompanyAddressUpdatedEvent, got {type(event).__name__}")

async def handle_CompanyContactUpdatedEvent(event: Any) -> None:
    """Handler untuk CompanyContactUpdatedEvent."""
    if isinstance(event, CompanyContactUpdatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected CompanyContactUpdatedEvent, got {type(event).__name__}")

async def handle_CompanyDissolvedEvent(event: Any) -> None:
    """Handler untuk CompanyDissolvedEvent."""
    if isinstance(event, CompanyDissolvedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected CompanyDissolvedEvent, got {type(event).__name__}")

async def handle_CompanyReactivatedEvent(event: Any) -> None:
    """Handler untuk CompanyReactivatedEvent."""
    if isinstance(event, CompanyReactivatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected CompanyReactivatedEvent, got {type(event).__name__}")

async def handle_CompanyRegisteredEvent(event: Any) -> None:
    """Handler untuk CompanyRegisteredEvent."""
    if isinstance(event, CompanyRegisteredEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected CompanyRegisteredEvent, got {type(event).__name__}")

async def handle_CompanySuspendedEvent(event: Any) -> None:
    """Handler untuk CompanySuspendedEvent."""
    if isinstance(event, CompanySuspendedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected CompanySuspendedEvent, got {type(event).__name__}")

async def handle_CostCardUpdatedEvent(event: Any) -> None:
    """Handler untuk CostCardUpdatedEvent."""
    if isinstance(event, CostCardUpdatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected CostCardUpdatedEvent, got {type(event).__name__}")

async def handle_CreditNoteAppliedEvent(event: Any) -> None:
    """Handler untuk CreditNoteAppliedEvent."""
    if isinstance(event, CreditNoteAppliedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected CreditNoteAppliedEvent, got {type(event).__name__}")

async def handle_CreditNoteIssuedEvent(event: Any) -> None:
    """Handler untuk CreditNoteIssuedEvent."""
    if isinstance(event, CreditNoteIssuedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected CreditNoteIssuedEvent, got {type(event).__name__}")

async def handle_CreditNoteReceivedEvent(event: Any) -> None:
    """Handler untuk CreditNoteReceivedEvent."""
    if isinstance(event, CreditNoteReceivedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected CreditNoteReceivedEvent, got {type(event).__name__}")

async def handle_CustomerBalanceUpdatedEvent(event: Any) -> None:
    """Handler untuk CustomerBalanceUpdatedEvent."""
    if isinstance(event, CustomerBalanceUpdatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected CustomerBalanceUpdatedEvent, got {type(event).__name__}")

async def handle_CustomerCreatedEvent(event: Any) -> None:
    """Handler untuk CustomerCreatedEvent."""
    if isinstance(event, CustomerCreatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected CustomerCreatedEvent, got {type(event).__name__}")

async def handle_CustomerCreditLimitChangedEvent(event: Any) -> None:
    """Handler untuk CustomerCreditLimitChangedEvent."""
    if isinstance(event, CustomerCreditLimitChangedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected CustomerCreditLimitChangedEvent, got {type(event).__name__}")

async def handle_CustomerStatusChangedEvent(event: Any) -> None:
    """Handler untuk CustomerStatusChangedEvent."""
    if isinstance(event, CustomerStatusChangedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected CustomerStatusChangedEvent, got {type(event).__name__}")

async def handle_DebitNoteAppliedEvent(event: Any) -> None:
    """Handler untuk DebitNoteAppliedEvent."""
    if isinstance(event, DebitNoteAppliedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected DebitNoteAppliedEvent, got {type(event).__name__}")

async def handle_DebitNoteIssuedEvent(event: Any) -> None:
    """Handler untuk DebitNoteIssuedEvent."""
    if isinstance(event, DebitNoteIssuedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected DebitNoteIssuedEvent, got {type(event).__name__}")

async def handle_DebitNoteIssuedServiceEvent(event: Any) -> None:
    """Handler untuk DebitNoteIssuedServiceEvent."""
    if isinstance(event, DebitNoteIssuedServiceEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected DebitNoteIssuedServiceEvent, got {type(event).__name__}")

async def handle_DeliveryNoteShippedEvent(event: Any) -> None:
    """Handler untuk DeliveryNoteShippedEvent."""
    if isinstance(event, DeliveryNoteShippedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected DeliveryNoteShippedEvent, got {type(event).__name__}")

async def handle_DividendApprovedEvent(event: Any) -> None:
    """Handler untuk DividendApprovedEvent."""
    if isinstance(event, DividendApprovedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected DividendApprovedEvent, got {type(event).__name__}")

async def handle_DividendCancelledEvent(event: Any) -> None:
    """Handler untuk DividendCancelledEvent."""
    if isinstance(event, DividendCancelledEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected DividendCancelledEvent, got {type(event).__name__}")

async def handle_DividendDeclaredEvent(event: Any) -> None:
    """Handler untuk DividendDeclaredEvent."""
    if isinstance(event, DividendDeclaredEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected DividendDeclaredEvent, got {type(event).__name__}")

async def handle_DividendPaidEvent(event: Any) -> None:
    """Handler untuk DividendPaidEvent."""
    if isinstance(event, DividendPaidEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected DividendPaidEvent, got {type(event).__name__}")

async def handle_DividendPartiallyPaidEvent(event: Any) -> None:
    """Handler untuk DividendPartiallyPaidEvent."""
    if isinstance(event, DividendPartiallyPaidEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected DividendPartiallyPaidEvent, got {type(event).__name__}")

async def handle_DomainEvent(event: Any) -> None:
    """Handler untuk DomainEvent."""
    if isinstance(event, DomainEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected DomainEvent, got {type(event).__name__}")

async def handle_EmployeeBPJSUpdatedEvent(event: Any) -> None:
    """Handler untuk EmployeeBPJSUpdatedEvent."""
    if isinstance(event, EmployeeBPJSUpdatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected EmployeeBPJSUpdatedEvent, got {type(event).__name__}")

async def handle_EmployeeCreatedEvent(event: Any) -> None:
    """Handler untuk EmployeeCreatedEvent."""
    if isinstance(event, EmployeeCreatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected EmployeeCreatedEvent, got {type(event).__name__}")

async def handle_EmployeePTKPUpdatedEvent(event: Any) -> None:
    """Handler untuk EmployeePTKPUpdatedEvent."""
    if isinstance(event, EmployeePTKPUpdatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected EmployeePTKPUpdatedEvent, got {type(event).__name__}")

async def handle_EmployeeResignedEvent(event: Any) -> None:
    """Handler untuk EmployeeResignedEvent."""
    if isinstance(event, EmployeeResignedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected EmployeeResignedEvent, got {type(event).__name__}")

async def handle_EmployeeStructureUpdatedEvent(event: Any) -> None:
    """Handler untuk EmployeeStructureUpdatedEvent."""
    if isinstance(event, EmployeeStructureUpdatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected EmployeeStructureUpdatedEvent, got {type(event).__name__}")

async def handle_FakturApprovedEvent(event: Any) -> None:
    """Handler untuk FakturApprovedEvent."""
    if isinstance(event, FakturApprovedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected FakturApprovedEvent, got {type(event).__name__}")

async def handle_FakturRejectedEvent(event: Any) -> None:
    """Handler untuk FakturRejectedEvent."""
    if isinstance(event, FakturRejectedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected FakturRejectedEvent, got {type(event).__name__}")

async def handle_FakturSubmittedEvent(event: Any) -> None:
    """Handler untuk FakturSubmittedEvent."""
    if isinstance(event, FakturSubmittedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected FakturSubmittedEvent, got {type(event).__name__}")

async def handle_GoodsReceiptCreatedEvent(event: Any) -> None:
    """Handler untuk GoodsReceiptCreatedEvent."""
    if isinstance(event, GoodsReceiptCreatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected GoodsReceiptCreatedEvent, got {type(event).__name__}")

async def handle_GoodwillAmortizedEvent(event: Any) -> None:
    """Handler untuk GoodwillAmortizedEvent."""
    if isinstance(event, GoodwillAmortizedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected GoodwillAmortizedEvent, got {type(event).__name__}")

async def handle_GoodwillDisposedEvent(event: Any) -> None:
    """Handler untuk GoodwillDisposedEvent."""
    if isinstance(event, GoodwillDisposedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected GoodwillDisposedEvent, got {type(event).__name__}")

async def handle_GoodwillImpairedEvent(event: Any) -> None:
    """Handler untuk GoodwillImpairedEvent."""
    if isinstance(event, GoodwillImpairedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected GoodwillImpairedEvent, got {type(event).__name__}")

async def handle_GoodwillImpairmentReversedEvent(event: Any) -> None:
    """Handler untuk GoodwillImpairmentReversedEvent."""
    if isinstance(event, GoodwillImpairmentReversedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected GoodwillImpairmentReversedEvent, got {type(event).__name__}")

async def handle_GoodwillRecognizedEvent(event: Any) -> None:
    """Handler untuk GoodwillRecognizedEvent."""
    if isinstance(event, GoodwillRecognizedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected GoodwillRecognizedEvent, got {type(event).__name__}")

async def handle_HPPCalculatedEvent(event: Any) -> None:
    """Handler untuk HPPCalculatedEvent."""
    if isinstance(event, HPPCalculatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected HPPCalculatedEvent, got {type(event).__name__}")

async def handle_HedgeAmountReclassifiedEvent(event: Any) -> None:
    """Handler untuk HedgeAmountReclassifiedEvent."""
    if isinstance(event, HedgeAmountReclassifiedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected HedgeAmountReclassifiedEvent, got {type(event).__name__}")

async def handle_HedgeCancelledEvent(event: Any) -> None:
    """Handler untuk HedgeCancelledEvent."""
    if isinstance(event, HedgeCancelledEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected HedgeCancelledEvent, got {type(event).__name__}")

async def handle_HedgeDesignatedEvent(event: Any) -> None:
    """Handler untuk HedgeDesignatedEvent."""
    if isinstance(event, HedgeDesignatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected HedgeDesignatedEvent, got {type(event).__name__}")

async def handle_HedgeDiscontinuedEvent(event: Any) -> None:
    """Handler untuk HedgeDiscontinuedEvent."""
    if isinstance(event, HedgeDiscontinuedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected HedgeDiscontinuedEvent, got {type(event).__name__}")

async def handle_HedgeEffectivenessTestedEvent(event: Any) -> None:
    """Handler untuk HedgeEffectivenessTestedEvent."""
    if isinstance(event, HedgeEffectivenessTestedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected HedgeEffectivenessTestedEvent, got {type(event).__name__}")

async def handle_HedgeFairValueAdjustedEvent(event: Any) -> None:
    """Handler untuk HedgeFairValueAdjustedEvent."""
    if isinstance(event, HedgeFairValueAdjustedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected HedgeFairValueAdjustedEvent, got {type(event).__name__}")

async def handle_HierarchyChangedEvent(event: Any) -> None:
    """Handler untuk HierarchyChangedEvent."""
    if isinstance(event, HierarchyChangedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected HierarchyChangedEvent, got {type(event).__name__}")

async def handle_IntangibleAssetAcquiredEvent(event: Any) -> None:
    """Handler untuk IntangibleAssetAcquiredEvent."""
    if isinstance(event, IntangibleAssetAcquiredEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected IntangibleAssetAcquiredEvent, got {type(event).__name__}")

async def handle_IntangibleAssetAmortizationPostedEvent(event: Any) -> None:
    """Handler untuk IntangibleAssetAmortizationPostedEvent."""
    if isinstance(event, IntangibleAssetAmortizationPostedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected IntangibleAssetAmortizationPostedEvent, got {type(event).__name__}")

async def handle_IntangibleAssetDisposedEvent(event: Any) -> None:
    """Handler untuk IntangibleAssetDisposedEvent."""
    if isinstance(event, IntangibleAssetDisposedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected IntangibleAssetDisposedEvent, got {type(event).__name__}")

async def handle_IntangibleAssetFullyAmortizedEvent(event: Any) -> None:
    """Handler untuk IntangibleAssetFullyAmortizedEvent."""
    if isinstance(event, IntangibleAssetFullyAmortizedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected IntangibleAssetFullyAmortizedEvent, got {type(event).__name__}")

async def handle_IntangibleAssetImpairedEvent(event: Any) -> None:
    """Handler untuk IntangibleAssetImpairedEvent."""
    if isinstance(event, IntangibleAssetImpairedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected IntangibleAssetImpairedEvent, got {type(event).__name__}")

async def handle_IntangibleAssetImpairmentReversedEvent(event: Any) -> None:
    """Handler untuk IntangibleAssetImpairmentReversedEvent."""
    if isinstance(event, IntangibleAssetImpairmentReversedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected IntangibleAssetImpairmentReversedEvent, got {type(event).__name__}")

async def handle_IntangibleAssetRevaluatedEvent(event: Any) -> None:
    """Handler untuk IntangibleAssetRevaluatedEvent."""
    if isinstance(event, IntangibleAssetRevaluatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected IntangibleAssetRevaluatedEvent, got {type(event).__name__}")

async def handle_IntangibleAssetTransferredEvent(event: Any) -> None:
    """Handler untuk IntangibleAssetTransferredEvent."""
    if isinstance(event, IntangibleAssetTransferredEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected IntangibleAssetTransferredEvent, got {type(event).__name__}")

async def handle_IntangibleAssetUpdatedEvent(event: Any) -> None:
    """Handler untuk IntangibleAssetUpdatedEvent."""
    if isinstance(event, IntangibleAssetUpdatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected IntangibleAssetUpdatedEvent, got {type(event).__name__}")

async def handle_InterWarehouseTransferCreatedEvent(event: Any) -> None:
    """Handler untuk InterWarehouseTransferCreatedEvent."""
    if isinstance(event, InterWarehouseTransferCreatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected InterWarehouseTransferCreatedEvent, got {type(event).__name__}")

async def handle_InventoryValuationUpdatedEvent(event: Any) -> None:
    """Handler untuk InventoryValuationUpdatedEvent."""
    if isinstance(event, InventoryValuationUpdatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected InventoryValuationUpdatedEvent, got {type(event).__name__}")

async def handle_InvoiceApprovedEvent(event: Any) -> None:
    """Handler untuk InvoiceApprovedEvent."""
    if isinstance(event, InvoiceApprovedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected InvoiceApprovedEvent, got {type(event).__name__}")

async def handle_InvoiceCancelledEvent(event: Any) -> None:
    """Handler untuk InvoiceCancelledEvent."""
    if isinstance(event, InvoiceCancelledEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected InvoiceCancelledEvent, got {type(event).__name__}")

async def handle_InvoiceCreatedEvent(event: Any) -> None:
    """Handler untuk InvoiceCreatedEvent."""
    if isinstance(event, InvoiceCreatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected InvoiceCreatedEvent, got {type(event).__name__}")

async def handle_InvoiceDisputedEvent(event: Any) -> None:
    """Handler untuk InvoiceDisputedEvent."""
    if isinstance(event, InvoiceDisputedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected InvoiceDisputedEvent, got {type(event).__name__}")

async def handle_InvoiceIssuedEvent(event: Any) -> None:
    """Handler untuk InvoiceIssuedEvent."""
    if isinstance(event, InvoiceIssuedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected InvoiceIssuedEvent, got {type(event).__name__}")

async def handle_InvoicePaidEvent(event: Any) -> None:
    """Handler untuk InvoicePaidEvent."""
    if isinstance(event, InvoicePaidEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected InvoicePaidEvent, got {type(event).__name__}")

async def handle_InvoicePartiallyPaidEvent(event: Any) -> None:
    """Handler untuk InvoicePartiallyPaidEvent."""
    if isinstance(event, InvoicePartiallyPaidEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected InvoicePartiallyPaidEvent, got {type(event).__name__}")

async def handle_InvoiceReceivedEvent(event: Any) -> None:
    """Handler untuk InvoiceReceivedEvent."""
    if isinstance(event, InvoiceReceivedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected InvoiceReceivedEvent, got {type(event).__name__}")

async def handle_InvoiceVerifiedEvent(event: Any) -> None:
    """Handler untuk InvoiceVerifiedEvent."""
    if isinstance(event, InvoiceVerifiedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected InvoiceVerifiedEvent, got {type(event).__name__}")

async def handle_InvoiceWrittenOffEvent(event: Any) -> None:
    """Handler untuk InvoiceWrittenOffEvent."""
    if isinstance(event, InvoiceWrittenOffEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected InvoiceWrittenOffEvent, got {type(event).__name__}")

async def handle_ItemCreatedEvent(event: Any) -> None:
    """Handler untuk ItemCreatedEvent."""
    if isinstance(event, ItemCreatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected ItemCreatedEvent, got {type(event).__name__}")

async def handle_ItemDeactivatedEvent(event: Any) -> None:
    """Handler untuk ItemDeactivatedEvent."""
    if isinstance(event, ItemDeactivatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected ItemDeactivatedEvent, got {type(event).__name__}")

async def handle_ItemUpdatedEvent(event: Any) -> None:
    """Handler untuk ItemUpdatedEvent."""
    if isinstance(event, ItemUpdatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected ItemUpdatedEvent, got {type(event).__name__}")

async def handle_JournalAdjustedEvent(event: Any) -> None:
    """Handler untuk JournalAdjustedEvent."""
    if isinstance(event, JournalAdjustedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected JournalAdjustedEvent, got {type(event).__name__}")

async def handle_JournalApprovedEvent(event: Any) -> None:
    """Handler untuk JournalApprovedEvent."""
    if isinstance(event, JournalApprovedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected JournalApprovedEvent, got {type(event).__name__}")

async def handle_JournalArchivedEvent(event: Any) -> None:
    """Handler untuk JournalArchivedEvent."""
    if isinstance(event, JournalArchivedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected JournalArchivedEvent, got {type(event).__name__}")

async def handle_JournalCancelledEvent(event: Any) -> None:
    """Handler untuk JournalCancelledEvent."""
    if isinstance(event, JournalCancelledEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected JournalCancelledEvent, got {type(event).__name__}")

async def handle_JournalCreatedEvent(event: Any) -> None:
    """Handler untuk JournalCreatedEvent."""
    if isinstance(event, JournalCreatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected JournalCreatedEvent, got {type(event).__name__}")

async def handle_JournalPostedEvent(event: Any) -> None:
    """Handler untuk JournalPostedEvent."""
    if isinstance(event, JournalPostedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected JournalPostedEvent, got {type(event).__name__}")

async def handle_JournalRejectedEvent(event: Any) -> None:
    """Handler untuk JournalRejectedEvent."""
    if isinstance(event, JournalRejectedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected JournalRejectedEvent, got {type(event).__name__}")

async def handle_JournalReversedEvent(event: Any) -> None:
    """Handler untuk JournalReversedEvent."""
    if isinstance(event, JournalReversedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected JournalReversedEvent, got {type(event).__name__}")

async def handle_JournalSubmittedEvent(event: Any) -> None:
    """Handler untuk JournalSubmittedEvent."""
    if isinstance(event, JournalSubmittedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected JournalSubmittedEvent, got {type(event).__name__}")

async def handle_JournalUnarchivedEvent(event: Any) -> None:
    """Handler untuk JournalUnarchivedEvent."""
    if isinstance(event, JournalUnarchivedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected JournalUnarchivedEvent, got {type(event).__name__}")

async def handle_JournalVoidedEvent(event: Any) -> None:
    """Handler untuk JournalVoidedEvent."""
    if isinstance(event, JournalVoidedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected JournalVoidedEvent, got {type(event).__name__}")

async def handle_LaborPostedEvent(event: Any) -> None:
    """Handler untuk LaborPostedEvent."""
    if isinstance(event, LaborPostedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected LaborPostedEvent, got {type(event).__name__}")

async def handle_LoginFailureEvent(event: Any) -> None:
    """Handler untuk LoginFailureEvent."""
    if isinstance(event, LoginFailureEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected LoginFailureEvent, got {type(event).__name__}")

async def handle_LoginSuccessEvent(event: Any) -> None:
    """Handler untuk LoginSuccessEvent."""
    if isinstance(event, LoginSuccessEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected LoginSuccessEvent, got {type(event).__name__}")

async def handle_MaterialIssuedEvent(event: Any) -> None:
    """Handler untuk MaterialIssuedEvent."""
    if isinstance(event, MaterialIssuedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected MaterialIssuedEvent, got {type(event).__name__}")

async def handle_MeteraiUsedEvent(event: Any) -> None:
    """Handler untuk MeteraiUsedEvent."""
    if isinstance(event, MeteraiUsedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected MeteraiUsedEvent, got {type(event).__name__}")

async def handle_MilestoneBilledEvent(event: Any) -> None:
    """Handler untuk MilestoneBilledEvent."""
    if isinstance(event, MilestoneBilledEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected MilestoneBilledEvent, got {type(event).__name__}")

async def handle_MilestoneReadyEvent(event: Any) -> None:
    """Handler untuk MilestoneReadyEvent."""
    if isinstance(event, MilestoneReadyEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected MilestoneReadyEvent, got {type(event).__name__}")

async def handle_OverheadAppliedEvent(event: Any) -> None:
    """Handler untuk OverheadAppliedEvent."""
    if isinstance(event, OverheadAppliedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected OverheadAppliedEvent, got {type(event).__name__}")

async def handle_PKPStatusChangedEvent(event: Any) -> None:
    """Handler untuk PKPStatusChangedEvent."""
    if isinstance(event, PKPStatusChangedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PKPStatusChangedEvent, got {type(event).__name__}")

async def handle_PaymentAllocatedEvent(event: Any) -> None:
    """Handler untuk PaymentAllocatedEvent."""
    if isinstance(event, PaymentAllocatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PaymentAllocatedEvent, got {type(event).__name__}")

async def handle_PaymentAppliedEvent(event: Any) -> None:
    """Handler untuk PaymentAppliedEvent."""
    if isinstance(event, PaymentAppliedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PaymentAppliedEvent, got {type(event).__name__}")

async def handle_PaymentApprovedEvent(event: Any) -> None:
    """Handler untuk PaymentApprovedEvent."""
    if isinstance(event, PaymentApprovedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PaymentApprovedEvent, got {type(event).__name__}")

async def handle_PaymentCancelledEvent(event: Any) -> None:
    """Handler untuk PaymentCancelledEvent."""
    if isinstance(event, PaymentCancelledEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PaymentCancelledEvent, got {type(event).__name__}")

async def handle_PaymentConfirmedEvent(event: Any) -> None:
    """Handler untuk PaymentConfirmedEvent."""
    if isinstance(event, PaymentConfirmedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PaymentConfirmedEvent, got {type(event).__name__}")

async def handle_PaymentMadeEvent(event: Any) -> None:
    """Handler untuk PaymentMadeEvent."""
    if isinstance(event, PaymentMadeEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PaymentMadeEvent, got {type(event).__name__}")

async def handle_PaymentProcessedEvent(event: Any) -> None:
    """Handler untuk PaymentProcessedEvent."""
    if isinstance(event, PaymentProcessedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PaymentProcessedEvent, got {type(event).__name__}")

async def handle_PaymentReceivedEvent(event: Any) -> None:
    """Handler untuk PaymentReceivedEvent."""
    if isinstance(event, PaymentReceivedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PaymentReceivedEvent, got {type(event).__name__}")

async def handle_PaymentRunExecutedEvent(event: Any) -> None:
    """Handler untuk PaymentRunExecutedEvent."""
    if isinstance(event, PaymentRunExecutedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PaymentRunExecutedEvent, got {type(event).__name__}")

async def handle_PaymentRunGeneratedEvent(event: Any) -> None:
    """Handler untuk PaymentRunGeneratedEvent."""
    if isinstance(event, PaymentRunGeneratedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PaymentRunGeneratedEvent, got {type(event).__name__}")

async def handle_PaymentSentEvent(event: Any) -> None:
    """Handler untuk PaymentSentEvent."""
    if isinstance(event, PaymentSentEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PaymentSentEvent, got {type(event).__name__}")

async def handle_PaymentVoidedEvent(event: Any) -> None:
    """Handler untuk PaymentVoidedEvent."""
    if isinstance(event, PaymentVoidedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PaymentVoidedEvent, got {type(event).__name__}")

async def handle_PayrollRunApprovedEvent(event: Any) -> None:
    """Handler untuk PayrollRunApprovedEvent."""
    if isinstance(event, PayrollRunApprovedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PayrollRunApprovedEvent, got {type(event).__name__}")

async def handle_PayrollRunCalculatedEvent(event: Any) -> None:
    """Handler untuk PayrollRunCalculatedEvent."""
    if isinstance(event, PayrollRunCalculatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PayrollRunCalculatedEvent, got {type(event).__name__}")

async def handle_PayrollRunCancelledEvent(event: Any) -> None:
    """Handler untuk PayrollRunCancelledEvent."""
    if isinstance(event, PayrollRunCancelledEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PayrollRunCancelledEvent, got {type(event).__name__}")

async def handle_PayrollRunCreatedEvent(event: Any) -> None:
    """Handler untuk PayrollRunCreatedEvent."""
    if isinstance(event, PayrollRunCreatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PayrollRunCreatedEvent, got {type(event).__name__}")

async def handle_PayrollRunPaidEvent(event: Any) -> None:
    """Handler untuk PayrollRunPaidEvent."""
    if isinstance(event, PayrollRunPaidEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PayrollRunPaidEvent, got {type(event).__name__}")

async def handle_PayrollRunPostedEvent(event: Any) -> None:
    """Handler untuk PayrollRunPostedEvent."""
    if isinstance(event, PayrollRunPostedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PayrollRunPostedEvent, got {type(event).__name__}")

async def handle_PayslipGeneratedEvent(event: Any) -> None:
    """Handler untuk PayslipGeneratedEvent."""
    if isinstance(event, PayslipGeneratedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PayslipGeneratedEvent, got {type(event).__name__}")

async def handle_PayslipSentToEmployeeEvent(event: Any) -> None:
    """Handler untuk PayslipSentToEmployeeEvent."""
    if isinstance(event, PayslipSentToEmployeeEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PayslipSentToEmployeeEvent, got {type(event).__name__}")

async def handle_PeriodClosedEvent(event: Any) -> None:
    """Handler untuk PeriodClosedEvent."""
    if isinstance(event, PeriodClosedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PeriodClosedEvent, got {type(event).__name__}")

async def handle_PeriodCreatedEvent(event: Any) -> None:
    """Handler untuk PeriodCreatedEvent."""
    if isinstance(event, PeriodCreatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PeriodCreatedEvent, got {type(event).__name__}")

async def handle_PeriodLockedEvent(event: Any) -> None:
    """Handler untuk PeriodLockedEvent."""
    if isinstance(event, PeriodLockedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PeriodLockedEvent, got {type(event).__name__}")

async def handle_PeriodOpenedEvent(event: Any) -> None:
    """Handler untuk PeriodOpenedEvent."""
    if isinstance(event, PeriodOpenedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PeriodOpenedEvent, got {type(event).__name__}")

async def handle_PeriodReopenedEvent(event: Any) -> None:
    """Handler untuk PeriodReopenedEvent."""
    if isinstance(event, PeriodReopenedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PeriodReopenedEvent, got {type(event).__name__}")

async def handle_PeriodStatusChangedEvent(event: Any) -> None:
    """Handler untuk PeriodStatusChangedEvent."""
    if isinstance(event, PeriodStatusChangedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PeriodStatusChangedEvent, got {type(event).__name__}")

async def handle_PeriodUpdatedEvent(event: Any) -> None:
    """Handler untuk PeriodUpdatedEvent."""
    if isinstance(event, PeriodUpdatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PeriodUpdatedEvent, got {type(event).__name__}")

async def handle_PermissionGrantedEvent(event: Any) -> None:
    """Handler untuk PermissionGrantedEvent."""
    if isinstance(event, PermissionGrantedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PermissionGrantedEvent, got {type(event).__name__}")

async def handle_PermissionRevokedEvent(event: Any) -> None:
    """Handler untuk PermissionRevokedEvent."""
    if isinstance(event, PermissionRevokedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PermissionRevokedEvent, got {type(event).__name__}")

async def handle_PettyCashActivatedEvent(event: Any) -> None:
    """Handler untuk PettyCashActivatedEvent."""
    if isinstance(event, PettyCashActivatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PettyCashActivatedEvent, got {type(event).__name__}")

async def handle_PettyCashAdjustedEvent(event: Any) -> None:
    """Handler untuk PettyCashAdjustedEvent."""
    if isinstance(event, PettyCashAdjustedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PettyCashAdjustedEvent, got {type(event).__name__}")

async def handle_PettyCashClosedEvent(event: Any) -> None:
    """Handler untuk PettyCashClosedEvent."""
    if isinstance(event, PettyCashClosedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PettyCashClosedEvent, got {type(event).__name__}")

async def handle_PettyCashDisbursementEvent(event: Any) -> None:
    """Handler untuk PettyCashDisbursementEvent."""
    if isinstance(event, PettyCashDisbursementEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PettyCashDisbursementEvent, got {type(event).__name__}")

async def handle_PettyCashReplenishedEvent(event: Any) -> None:
    """Handler untuk PettyCashReplenishedEvent."""
    if isinstance(event, PettyCashReplenishedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PettyCashReplenishedEvent, got {type(event).__name__}")

async def handle_PettyCashSuspendedEvent(event: Any) -> None:
    """Handler untuk PettyCashSuspendedEvent."""
    if isinstance(event, PettyCashSuspendedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PettyCashSuspendedEvent, got {type(event).__name__}")

async def handle_ProductionCompletedEvent(event: Any) -> None:
    """Handler untuk ProductionCompletedEvent."""
    if isinstance(event, ProductionCompletedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected ProductionCompletedEvent, got {type(event).__name__}")

async def handle_ProjectActivatedEvent(event: Any) -> None:
    """Handler untuk ProjectActivatedEvent."""
    if isinstance(event, ProjectActivatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected ProjectActivatedEvent, got {type(event).__name__}")

async def handle_ProjectBillingGeneratedEvent(event: Any) -> None:
    """Handler untuk ProjectBillingGeneratedEvent."""
    if isinstance(event, ProjectBillingGeneratedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected ProjectBillingGeneratedEvent, got {type(event).__name__}")

async def handle_ProjectCompletedEvent(event: Any) -> None:
    """Handler untuk ProjectCompletedEvent."""
    if isinstance(event, ProjectCompletedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected ProjectCompletedEvent, got {type(event).__name__}")

async def handle_ProjectCreatedEvent(event: Any) -> None:
    """Handler untuk ProjectCreatedEvent."""
    if isinstance(event, ProjectCreatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected ProjectCreatedEvent, got {type(event).__name__}")

async def handle_PurchaseInvoiceReceivedEvent(event: Any) -> None:
    """Handler untuk PurchaseInvoiceReceivedEvent."""
    if isinstance(event, PurchaseInvoiceReceivedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PurchaseInvoiceReceivedEvent, got {type(event).__name__}")

async def handle_PurchaseOrderApprovedEvent(event: Any) -> None:
    """Handler untuk PurchaseOrderApprovedEvent."""
    if isinstance(event, PurchaseOrderApprovedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PurchaseOrderApprovedEvent, got {type(event).__name__}")

async def handle_PurchaseOrderCreatedEvent(event: Any) -> None:
    """Handler untuk PurchaseOrderCreatedEvent."""
    if isinstance(event, PurchaseOrderCreatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected PurchaseOrderCreatedEvent, got {type(event).__name__}")

async def handle_RetainedEarningsAdjustedEvent(event: Any) -> None:
    """Handler untuk RetainedEarningsAdjustedEvent."""
    if isinstance(event, RetainedEarningsAdjustedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected RetainedEarningsAdjustedEvent, got {type(event).__name__}")

async def handle_RetainedEarningsTransferEvent(event: Any) -> None:
    """Handler untuk RetainedEarningsTransferEvent."""
    if isinstance(event, RetainedEarningsTransferEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected RetainedEarningsTransferEvent, got {type(event).__name__}")

async def handle_RetainedEarningsUpdatedEvent(event: Any) -> None:
    """Handler untuk RetainedEarningsUpdatedEvent."""
    if isinstance(event, RetainedEarningsUpdatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected RetainedEarningsUpdatedEvent, got {type(event).__name__}")

async def handle_RetainerContractActivatedEvent(event: Any) -> None:
    """Handler untuk RetainerContractActivatedEvent."""
    if isinstance(event, RetainerContractActivatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected RetainerContractActivatedEvent, got {type(event).__name__}")

async def handle_RevenueRecognizedEvent(event: Any) -> None:
    """Handler untuk RevenueRecognizedEvent."""
    if isinstance(event, RevenueRecognizedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected RevenueRecognizedEvent, got {type(event).__name__}")

async def handle_RoleAssignedEvent(event: Any) -> None:
    """Handler untuk RoleAssignedEvent."""
    if isinstance(event, RoleAssignedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected RoleAssignedEvent, got {type(event).__name__}")

async def handle_RoleCreatedEvent(event: Any) -> None:
    """Handler untuk RoleCreatedEvent."""
    if isinstance(event, RoleCreatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected RoleCreatedEvent, got {type(event).__name__}")

async def handle_RoleDeletedEvent(event: Any) -> None:
    """Handler untuk RoleDeletedEvent."""
    if isinstance(event, RoleDeletedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected RoleDeletedEvent, got {type(event).__name__}")

async def handle_RoleRevokedEvent(event: Any) -> None:
    """Handler untuk RoleRevokedEvent."""
    if isinstance(event, RoleRevokedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected RoleRevokedEvent, got {type(event).__name__}")

async def handle_RoleUpdatedEvent(event: Any) -> None:
    """Handler untuk RoleUpdatedEvent."""
    if isinstance(event, RoleUpdatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected RoleUpdatedEvent, got {type(event).__name__}")

async def handle_SPTApprovedEvent(event: Any) -> None:
    """Handler untuk SPTApprovedEvent."""
    if isinstance(event, SPTApprovedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected SPTApprovedEvent, got {type(event).__name__}")

async def handle_SPTSubmittedEvent(event: Any) -> None:
    """Handler untuk SPTSubmittedEvent."""
    if isinstance(event, SPTSubmittedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected SPTSubmittedEvent, got {type(event).__name__}")

async def handle_SalaryComponentAddedEvent(event: Any) -> None:
    """Handler untuk SalaryComponentAddedEvent."""
    if isinstance(event, SalaryComponentAddedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected SalaryComponentAddedEvent, got {type(event).__name__}")

async def handle_SalesInvoiceIssuedEvent(event: Any) -> None:
    """Handler untuk SalesInvoiceIssuedEvent."""
    if isinstance(event, SalesInvoiceIssuedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected SalesInvoiceIssuedEvent, got {type(event).__name__}")

async def handle_SalesInvoicePaidEvent(event: Any) -> None:
    """Handler untuk SalesInvoicePaidEvent."""
    if isinstance(event, SalesInvoicePaidEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected SalesInvoicePaidEvent, got {type(event).__name__}")

async def handle_SalesOrderApprovedEvent(event: Any) -> None:
    """Handler untuk SalesOrderApprovedEvent."""
    if isinstance(event, SalesOrderApprovedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected SalesOrderApprovedEvent, got {type(event).__name__}")

async def handle_SalesOrderCreatedEvent(event: Any) -> None:
    """Handler untuk SalesOrderCreatedEvent."""
    if isinstance(event, SalesOrderCreatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected SalesOrderCreatedEvent, got {type(event).__name__}")

async def handle_SessionCompromisedEvent(event: Any) -> None:
    """Handler untuk SessionCompromisedEvent."""
    if isinstance(event, SessionCompromisedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected SessionCompromisedEvent, got {type(event).__name__}")

async def handle_SessionCreatedEvent(event: Any) -> None:
    """Handler untuk SessionCreatedEvent."""
    if isinstance(event, SessionCreatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected SessionCreatedEvent, got {type(event).__name__}")

async def handle_SessionRefreshedEvent(event: Any) -> None:
    """Handler untuk SessionRefreshedEvent."""
    if isinstance(event, SessionRefreshedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected SessionRefreshedEvent, got {type(event).__name__}")

async def handle_SessionTerminatedEvent(event: Any) -> None:
    """Handler untuk SessionTerminatedEvent."""
    if isinstance(event, SessionTerminatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected SessionTerminatedEvent, got {type(event).__name__}")

async def handle_SettingAddedEvent(event: Any) -> None:
    """Handler untuk SettingAddedEvent."""
    if isinstance(event, SettingAddedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected SettingAddedEvent, got {type(event).__name__}")

async def handle_SettingChangedEvent(event: Any) -> None:
    """Handler untuk SettingChangedEvent."""
    if isinstance(event, SettingChangedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected SettingChangedEvent, got {type(event).__name__}")

async def handle_SettingRemovedEvent(event: Any) -> None:
    """Handler untuk SettingRemovedEvent."""
    if isinstance(event, SettingRemovedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected SettingRemovedEvent, got {type(event).__name__}")

async def handle_SettingResetEvent(event: Any) -> None:
    """Handler untuk SettingResetEvent."""
    if isinstance(event, SettingResetEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected SettingResetEvent, got {type(event).__name__}")

async def handle_SettingsBulkUpdatedEvent(event: Any) -> None:
    """Handler untuk SettingsBulkUpdatedEvent."""
    if isinstance(event, SettingsBulkUpdatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected SettingsBulkUpdatedEvent, got {type(event).__name__}")

async def handle_SettingsLockedEvent(event: Any) -> None:
    """Handler untuk SettingsLockedEvent."""
    if isinstance(event, SettingsLockedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected SettingsLockedEvent, got {type(event).__name__}")

async def handle_SettingsUnlockedEvent(event: Any) -> None:
    """Handler untuk SettingsUnlockedEvent."""
    if isinstance(event, SettingsUnlockedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected SettingsUnlockedEvent, got {type(event).__name__}")

async def handle_StandardCostActivatedEvent(event: Any) -> None:
    """Handler untuk StandardCostActivatedEvent."""
    if isinstance(event, StandardCostActivatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected StandardCostActivatedEvent, got {type(event).__name__}")

async def handle_StandardCostCreatedEvent(event: Any) -> None:
    """Handler untuk StandardCostCreatedEvent."""
    if isinstance(event, StandardCostCreatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected StandardCostCreatedEvent, got {type(event).__name__}")

async def handle_StockAdjustedEvent(event: Any) -> None:
    """Handler untuk StockAdjustedEvent."""
    if isinstance(event, StockAdjustedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected StockAdjustedEvent, got {type(event).__name__}")

async def handle_StockLevelAlertEvent(event: Any) -> None:
    """Handler untuk StockLevelAlertEvent."""
    if isinstance(event, StockLevelAlertEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected StockLevelAlertEvent, got {type(event).__name__}")

async def handle_StockMovementCreatedEvent(event: Any) -> None:
    """Handler untuk StockMovementCreatedEvent."""
    if isinstance(event, StockMovementCreatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected StockMovementCreatedEvent, got {type(event).__name__}")

async def handle_StockOpnameApprovedEvent(event: Any) -> None:
    """Handler untuk StockOpnameApprovedEvent."""
    if isinstance(event, StockOpnameApprovedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected StockOpnameApprovedEvent, got {type(event).__name__}")

async def handle_StockOpnameCreatedEvent(event: Any) -> None:
    """Handler untuk StockOpnameCreatedEvent."""
    if isinstance(event, StockOpnameCreatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected StockOpnameCreatedEvent, got {type(event).__name__}")

async def handle_SupplierCreatedEvent(event: Any) -> None:
    """Handler untuk SupplierCreatedEvent."""
    if isinstance(event, SupplierCreatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected SupplierCreatedEvent, got {type(event).__name__}")

async def handle_SupplierPaymentTermsChangedEvent(event: Any) -> None:
    """Handler untuk SupplierPaymentTermsChangedEvent."""
    if isinstance(event, SupplierPaymentTermsChangedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected SupplierPaymentTermsChangedEvent, got {type(event).__name__}")

async def handle_SupplierWithholdingCategoryChangedEvent(event: Any) -> None:
    """Handler untuk SupplierWithholdingCategoryChangedEvent."""
    if isinstance(event, SupplierWithholdingCategoryChangedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected SupplierWithholdingCategoryChangedEvent, got {type(event).__name__}")

async def handle_TaxCalculatedEvent(event: Any) -> None:
    """Handler untuk TaxCalculatedEvent."""
    if isinstance(event, TaxCalculatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected TaxCalculatedEvent, got {type(event).__name__}")

async def handle_TaxProfileUpdatedEvent(event: Any) -> None:
    """Handler untuk TaxProfileUpdatedEvent."""
    if isinstance(event, TaxProfileUpdatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected TaxProfileUpdatedEvent, got {type(event).__name__}")

async def handle_ThreeWayMatchResultEvent(event: Any) -> None:
    """Handler untuk ThreeWayMatchResultEvent."""
    if isinstance(event, ThreeWayMatchResultEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected ThreeWayMatchResultEvent, got {type(event).__name__}")

async def handle_TimeEntryApprovedEvent(event: Any) -> None:
    """Handler untuk TimeEntryApprovedEvent."""
    if isinstance(event, TimeEntryApprovedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected TimeEntryApprovedEvent, got {type(event).__name__}")

async def handle_TimeEntrySubmittedEvent(event: Any) -> None:
    """Handler untuk TimeEntrySubmittedEvent."""
    if isinstance(event, TimeEntrySubmittedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected TimeEntrySubmittedEvent, got {type(event).__name__}")

async def handle_TransactionCreatedEvent(event: Any) -> None:
    """Handler untuk TransactionCreatedEvent."""
    if isinstance(event, TransactionCreatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected TransactionCreatedEvent, got {type(event).__name__}")

async def handle_TransactionDeletedEvent(event: Any) -> None:
    """Handler untuk TransactionDeletedEvent."""
    if isinstance(event, TransactionDeletedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected TransactionDeletedEvent, got {type(event).__name__}")

async def handle_TransactionRecordedEvent(event: Any) -> None:
    """Handler untuk TransactionRecordedEvent."""
    if isinstance(event, TransactionRecordedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected TransactionRecordedEvent, got {type(event).__name__}")

async def handle_TransactionUpdatedEvent(event: Any) -> None:
    """Handler untuk TransactionUpdatedEvent."""
    if isinstance(event, TransactionUpdatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected TransactionUpdatedEvent, got {type(event).__name__}")

async def handle_TransferCompletedEvent(event: Any) -> None:
    """Handler untuk TransferCompletedEvent."""
    if isinstance(event, TransferCompletedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected TransferCompletedEvent, got {type(event).__name__}")

async def handle_UserActivatedEvent(event: Any) -> None:
    """Handler untuk UserActivatedEvent."""
    if isinstance(event, UserActivatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected UserActivatedEvent, got {type(event).__name__}")

async def handle_UserCreatedEvent(event: Any) -> None:
    """Handler untuk UserCreatedEvent."""
    if isinstance(event, UserCreatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected UserCreatedEvent, got {type(event).__name__}")

async def handle_UserDeactivatedEvent(event: Any) -> None:
    """Handler untuk UserDeactivatedEvent."""
    if isinstance(event, UserDeactivatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected UserDeactivatedEvent, got {type(event).__name__}")

async def handle_UserDeletedEvent(event: Any) -> None:
    """Handler untuk UserDeletedEvent."""
    if isinstance(event, UserDeletedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected UserDeletedEvent, got {type(event).__name__}")

async def handle_UserPasswordChangedEvent(event: Any) -> None:
    """Handler untuk UserPasswordChangedEvent."""
    if isinstance(event, UserPasswordChangedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected UserPasswordChangedEvent, got {type(event).__name__}")

async def handle_UserSuspendedEvent(event: Any) -> None:
    """Handler untuk UserSuspendedEvent."""
    if isinstance(event, UserSuspendedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected UserSuspendedEvent, got {type(event).__name__}")

async def handle_UserUnlockedEvent(event: Any) -> None:
    """Handler untuk UserUnlockedEvent."""
    if isinstance(event, UserUnlockedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected UserUnlockedEvent, got {type(event).__name__}")

async def handle_UserUpdatedEvent(event: Any) -> None:
    """Handler untuk UserUpdatedEvent."""
    if isinstance(event, UserUpdatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected UserUpdatedEvent, got {type(event).__name__}")

async def handle_VarianceAnalyzedEvent(event: Any) -> None:
    """Handler untuk VarianceAnalyzedEvent."""
    if isinstance(event, VarianceAnalyzedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected VarianceAnalyzedEvent, got {type(event).__name__}")

async def handle_WorkOrderApprovedEvent(event: Any) -> None:
    """Handler untuk WorkOrderApprovedEvent."""
    if isinstance(event, WorkOrderApprovedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected WorkOrderApprovedEvent, got {type(event).__name__}")

async def handle_WorkOrderCancelledEvent(event: Any) -> None:
    """Handler untuk WorkOrderCancelledEvent."""
    if isinstance(event, WorkOrderCancelledEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected WorkOrderCancelledEvent, got {type(event).__name__}")

async def handle_WorkOrderCompletedEvent(event: Any) -> None:
    """Handler untuk WorkOrderCompletedEvent."""
    if isinstance(event, WorkOrderCompletedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected WorkOrderCompletedEvent, got {type(event).__name__}")

async def handle_WorkOrderCreatedEvent(event: Any) -> None:
    """Handler untuk WorkOrderCreatedEvent."""
    if isinstance(event, WorkOrderCreatedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected WorkOrderCreatedEvent, got {type(event).__name__}")

async def handle_WorkOrderStartedEvent(event: Any) -> None:
    """Handler untuk WorkOrderStartedEvent."""
    if isinstance(event, WorkOrderStartedEvent):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected WorkOrderStartedEvent, got {type(event).__name__}")


async def handle_DomainEventType(event: Any) -> None:
    """Handler untuk DomainEventType (Enum)."""
    if isinstance(event, DomainEventType):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected DomainEventType, got {type(event).__name__}")

async def handle_DomainEventPublisher(event: Any) -> None:
    """Handler untuk DomainEventPublisher."""
    if isinstance(event, DomainEventPublisher):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected DomainEventPublisher, got {type(event).__name__}")

async def handle_BudgetEventType(event: Any) -> None:
    """Handler untuk BudgetEventType (Enum)."""
    if isinstance(event, BudgetEventType):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected BudgetEventType, got {type(event).__name__}")

async def handle_BudgetEventPublisher(event: Any) -> None:
    """Handler untuk BudgetEventPublisher."""
    if isinstance(event, BudgetEventPublisher):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected BudgetEventPublisher, got {type(event).__name__}")

async def handle_EventStore(event: Any) -> None:
    """Handler untuk EventStore (Protocol)."""
    if isinstance(event, EventStore):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected EventStore, got {type(event).__name__}")

async def handle_ConsolidationEventType(event: Any) -> None:
    """Handler untuk ConsolidationEventType (Enum)."""
    if isinstance(event, ConsolidationEventType):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected ConsolidationEventType, got {type(event).__name__}")

async def handle_ConsolidationEventPublisher(event: Any) -> None:
    """Handler untuk ConsolidationEventPublisher."""
    if isinstance(event, ConsolidationEventPublisher):
        await handle_generic_event(event)
    else:
        raise TypeError(f"Expected ConsolidationEventPublisher, got {type(event).__name__}")


# Daftar semua handler untuk registrasi
ALL_HANDLERS = {
    "AccountCreatedEvent": handle_AccountCreatedEvent,
    "AccountDeactivatedEvent": handle_AccountDeactivatedEvent,
    "AccountLockedEvent": handle_AccountLockedEvent,
    "AccountMergedEvent": handle_AccountMergedEvent,
    "AccountReactivatedEvent": handle_AccountReactivatedEvent,
    "AccountSplitEvent": handle_AccountSplitEvent,
    "AccountUnlockedEvent": handle_AccountUnlockedEvent,
    "AccountUpdatedEvent": handle_AccountUpdatedEvent,
    "AssetAcquiredEvent": handle_AssetAcquiredEvent,
    "AssetDepreciationPostedEvent": handle_AssetDepreciationPostedEvent,
    "AssetDisposedEvent": handle_AssetDisposedEvent,
    "AssetFullyDepreciatedEvent": handle_AssetFullyDepreciatedEvent,
    "AssetGroupCreatedEvent": handle_AssetGroupCreatedEvent,
    "AssetGroupUpdatedEvent": handle_AssetGroupUpdatedEvent,
    "AssetImpairedEvent": handle_AssetImpairedEvent,
    "AssetImpairmentReversedEvent": handle_AssetImpairmentReversedEvent,
    "AssetRevaluatedEvent": handle_AssetRevaluatedEvent,
    "AssetTransferredEvent": handle_AssetTransferredEvent,
    "AssetUpdatedEvent": handle_AssetUpdatedEvent,
    "BOMActivatedEvent": handle_BOMActivatedEvent,
    "BOMCreatedEvent": handle_BOMCreatedEvent,
    "BOMItemAddedEvent": handle_BOMItemAddedEvent,
    "BOMObsoletedEvent": handle_BOMObsoletedEvent,
    "BOMUpdatedEvent": handle_BOMUpdatedEvent,
    "BankAccountBlockedEvent": handle_BankAccountBlockedEvent,
    "BankAccountClosedEvent": handle_BankAccountClosedEvent,
    "BankAccountCreatedEvent": handle_BankAccountCreatedEvent,
    "BankAccountUpdatedEvent": handle_BankAccountUpdatedEvent,
    "BankReconciliationCompletedEvent": handle_BankReconciliationCompletedEvent,
    "BankTransactionClearedEvent": handle_BankTransactionClearedEvent,
    "BankTransactionReconciledEvent": handle_BankTransactionReconciledEvent,
    "BankTransactionRecordedEvent": handle_BankTransactionRecordedEvent,
    "BankTransferCancelledEvent": handle_BankTransferCancelledEvent,
    "BankTransferCompletedEvent": handle_BankTransferCompletedEvent,
    "BankTransferFailedEvent": handle_BankTransferFailedEvent,
    "BankTransferInitiatedEvent": handle_BankTransferInitiatedEvent,
    "BupotApprovedEvent": handle_BupotApprovedEvent,
    "BupotSubmittedEvent": handle_BupotSubmittedEvent,
    "COAArchivedEvent": handle_COAArchivedEvent,
    "COACreatedEvent": handle_COACreatedEvent,
    "COALockedEvent": handle_COALockedEvent,
    "COAUnlockedEvent": handle_COAUnlockedEvent,
    "COGSCalculatedEvent": handle_COGSCalculatedEvent,
    "CapitalContributionApprovedEvent": handle_CapitalContributionApprovedEvent,
    "CapitalContributionCancelledEvent": handle_CapitalContributionCancelledEvent,
    "CapitalContributionPostedEvent": handle_CapitalContributionPostedEvent,
    "CapitalContributionRecordedEvent": handle_CapitalContributionRecordedEvent,
    "CapitalWithdrawalApprovedEvent": handle_CapitalWithdrawalApprovedEvent,
    "CapitalWithdrawalCancelledEvent": handle_CapitalWithdrawalCancelledEvent,
    "CapitalWithdrawalPostedEvent": handle_CapitalWithdrawalPostedEvent,
    "CapitalWithdrawalRecordedEvent": handle_CapitalWithdrawalRecordedEvent,
    "CashBookClosedEvent": handle_CashBookClosedEvent,
    "CashBookUpdatedEvent": handle_CashBookUpdatedEvent,
    "CashDisbursementApprovedEvent": handle_CashDisbursementApprovedEvent,
    "CashDisbursementCancelledEvent": handle_CashDisbursementCancelledEvent,
    "CashDisbursementPaidEvent": handle_CashDisbursementPaidEvent,
    "CashReceiptCancelledEvent": handle_CashReceiptCancelledEvent,
    "CashReceiptConfirmedEvent": handle_CashReceiptConfirmedEvent,
    "CompanyAddressUpdatedEvent": handle_CompanyAddressUpdatedEvent,
    "CompanyContactUpdatedEvent": handle_CompanyContactUpdatedEvent,
    "CompanyDissolvedEvent": handle_CompanyDissolvedEvent,
    "CompanyReactivatedEvent": handle_CompanyReactivatedEvent,
    "CompanyRegisteredEvent": handle_CompanyRegisteredEvent,
    "CompanySuspendedEvent": handle_CompanySuspendedEvent,
    "CostCardUpdatedEvent": handle_CostCardUpdatedEvent,
    "CreditNoteAppliedEvent": handle_CreditNoteAppliedEvent,
    "CreditNoteIssuedEvent": handle_CreditNoteIssuedEvent,
    "CreditNoteReceivedEvent": handle_CreditNoteReceivedEvent,
    "CustomerBalanceUpdatedEvent": handle_CustomerBalanceUpdatedEvent,
    "CustomerCreatedEvent": handle_CustomerCreatedEvent,
    "CustomerCreditLimitChangedEvent": handle_CustomerCreditLimitChangedEvent,
    "CustomerStatusChangedEvent": handle_CustomerStatusChangedEvent,
    "DebitNoteAppliedEvent": handle_DebitNoteAppliedEvent,
    "DebitNoteIssuedEvent": handle_DebitNoteIssuedEvent,
    "DebitNoteIssuedServiceEvent": handle_DebitNoteIssuedServiceEvent,
    "DeliveryNoteShippedEvent": handle_DeliveryNoteShippedEvent,
    "DividendApprovedEvent": handle_DividendApprovedEvent,
    "DividendCancelledEvent": handle_DividendCancelledEvent,
    "DividendDeclaredEvent": handle_DividendDeclaredEvent,
    "DividendPaidEvent": handle_DividendPaidEvent,
    "DividendPartiallyPaidEvent": handle_DividendPartiallyPaidEvent,
    "DomainEvent": handle_DomainEvent,
    "EmployeeBPJSUpdatedEvent": handle_EmployeeBPJSUpdatedEvent,
    "EmployeeCreatedEvent": handle_EmployeeCreatedEvent,
    "EmployeePTKPUpdatedEvent": handle_EmployeePTKPUpdatedEvent,
    "EmployeeResignedEvent": handle_EmployeeResignedEvent,
    "EmployeeStructureUpdatedEvent": handle_EmployeeStructureUpdatedEvent,
    "FakturApprovedEvent": handle_FakturApprovedEvent,
    "FakturRejectedEvent": handle_FakturRejectedEvent,
    "FakturSubmittedEvent": handle_FakturSubmittedEvent,
    "GoodsReceiptCreatedEvent": handle_GoodsReceiptCreatedEvent,
    "GoodwillAmortizedEvent": handle_GoodwillAmortizedEvent,
    "GoodwillDisposedEvent": handle_GoodwillDisposedEvent,
    "GoodwillImpairedEvent": handle_GoodwillImpairedEvent,
    "GoodwillImpairmentReversedEvent": handle_GoodwillImpairmentReversedEvent,
    "GoodwillRecognizedEvent": handle_GoodwillRecognizedEvent,
    "HPPCalculatedEvent": handle_HPPCalculatedEvent,
    "HedgeAmountReclassifiedEvent": handle_HedgeAmountReclassifiedEvent,
    "HedgeCancelledEvent": handle_HedgeCancelledEvent,
    "HedgeDesignatedEvent": handle_HedgeDesignatedEvent,
    "HedgeDiscontinuedEvent": handle_HedgeDiscontinuedEvent,
    "HedgeEffectivenessTestedEvent": handle_HedgeEffectivenessTestedEvent,
    "HedgeFairValueAdjustedEvent": handle_HedgeFairValueAdjustedEvent,
    "HierarchyChangedEvent": handle_HierarchyChangedEvent,
    "IntangibleAssetAcquiredEvent": handle_IntangibleAssetAcquiredEvent,
    "IntangibleAssetAmortizationPostedEvent": handle_IntangibleAssetAmortizationPostedEvent,
    "IntangibleAssetDisposedEvent": handle_IntangibleAssetDisposedEvent,
    "IntangibleAssetFullyAmortizedEvent": handle_IntangibleAssetFullyAmortizedEvent,
    "IntangibleAssetImpairedEvent": handle_IntangibleAssetImpairedEvent,
    "IntangibleAssetImpairmentReversedEvent": handle_IntangibleAssetImpairmentReversedEvent,
    "IntangibleAssetRevaluatedEvent": handle_IntangibleAssetRevaluatedEvent,
    "IntangibleAssetTransferredEvent": handle_IntangibleAssetTransferredEvent,
    "IntangibleAssetUpdatedEvent": handle_IntangibleAssetUpdatedEvent,
    "InterWarehouseTransferCreatedEvent": handle_InterWarehouseTransferCreatedEvent,
    "InventoryValuationUpdatedEvent": handle_InventoryValuationUpdatedEvent,
    "InvoiceApprovedEvent": handle_InvoiceApprovedEvent,
    "InvoiceCancelledEvent": handle_InvoiceCancelledEvent,
    "InvoiceCreatedEvent": handle_InvoiceCreatedEvent,
    "InvoiceDisputedEvent": handle_InvoiceDisputedEvent,
    "InvoiceIssuedEvent": handle_InvoiceIssuedEvent,
    "InvoicePaidEvent": handle_InvoicePaidEvent,
    "InvoicePartiallyPaidEvent": handle_InvoicePartiallyPaidEvent,
    "InvoiceReceivedEvent": handle_InvoiceReceivedEvent,
    "InvoiceVerifiedEvent": handle_InvoiceVerifiedEvent,
    "InvoiceWrittenOffEvent": handle_InvoiceWrittenOffEvent,
    "ItemCreatedEvent": handle_ItemCreatedEvent,
    "ItemDeactivatedEvent": handle_ItemDeactivatedEvent,
    "ItemUpdatedEvent": handle_ItemUpdatedEvent,
    "JournalAdjustedEvent": handle_JournalAdjustedEvent,
    "JournalApprovedEvent": handle_JournalApprovedEvent,
    "JournalArchivedEvent": handle_JournalArchivedEvent,
    "JournalCancelledEvent": handle_JournalCancelledEvent,
    "JournalCreatedEvent": handle_JournalCreatedEvent,
    "JournalPostedEvent": handle_JournalPostedEvent,
    "JournalRejectedEvent": handle_JournalRejectedEvent,
    "JournalReversedEvent": handle_JournalReversedEvent,
    "JournalSubmittedEvent": handle_JournalSubmittedEvent,
    "JournalUnarchivedEvent": handle_JournalUnarchivedEvent,
    "JournalVoidedEvent": handle_JournalVoidedEvent,
    "LaborPostedEvent": handle_LaborPostedEvent,
    "LoginFailureEvent": handle_LoginFailureEvent,
    "LoginSuccessEvent": handle_LoginSuccessEvent,
    "MaterialIssuedEvent": handle_MaterialIssuedEvent,
    "MeteraiUsedEvent": handle_MeteraiUsedEvent,
    "MilestoneBilledEvent": handle_MilestoneBilledEvent,
    "MilestoneReadyEvent": handle_MilestoneReadyEvent,
    "OverheadAppliedEvent": handle_OverheadAppliedEvent,
    "PKPStatusChangedEvent": handle_PKPStatusChangedEvent,
    "PaymentAllocatedEvent": handle_PaymentAllocatedEvent,
    "PaymentAppliedEvent": handle_PaymentAppliedEvent,
    "PaymentApprovedEvent": handle_PaymentApprovedEvent,
    "PaymentCancelledEvent": handle_PaymentCancelledEvent,
    "PaymentConfirmedEvent": handle_PaymentConfirmedEvent,
    "PaymentMadeEvent": handle_PaymentMadeEvent,
    "PaymentProcessedEvent": handle_PaymentProcessedEvent,
    "PaymentReceivedEvent": handle_PaymentReceivedEvent,
    "PaymentRunExecutedEvent": handle_PaymentRunExecutedEvent,
    "PaymentRunGeneratedEvent": handle_PaymentRunGeneratedEvent,
    "PaymentSentEvent": handle_PaymentSentEvent,
    "PaymentVoidedEvent": handle_PaymentVoidedEvent,
    "PayrollRunApprovedEvent": handle_PayrollRunApprovedEvent,
    "PayrollRunCalculatedEvent": handle_PayrollRunCalculatedEvent,
    "PayrollRunCancelledEvent": handle_PayrollRunCancelledEvent,
    "PayrollRunCreatedEvent": handle_PayrollRunCreatedEvent,
    "PayrollRunPaidEvent": handle_PayrollRunPaidEvent,
    "PayrollRunPostedEvent": handle_PayrollRunPostedEvent,
    "PayslipGeneratedEvent": handle_PayslipGeneratedEvent,
    "PayslipSentToEmployeeEvent": handle_PayslipSentToEmployeeEvent,
    "PeriodClosedEvent": handle_PeriodClosedEvent,
    "PeriodCreatedEvent": handle_PeriodCreatedEvent,
    "PeriodLockedEvent": handle_PeriodLockedEvent,
    "PeriodOpenedEvent": handle_PeriodOpenedEvent,
    "PeriodReopenedEvent": handle_PeriodReopenedEvent,
    "PeriodStatusChangedEvent": handle_PeriodStatusChangedEvent,
    "PeriodUpdatedEvent": handle_PeriodUpdatedEvent,
    "PermissionGrantedEvent": handle_PermissionGrantedEvent,
    "PermissionRevokedEvent": handle_PermissionRevokedEvent,
    "PettyCashActivatedEvent": handle_PettyCashActivatedEvent,
    "PettyCashAdjustedEvent": handle_PettyCashAdjustedEvent,
    "PettyCashClosedEvent": handle_PettyCashClosedEvent,
    "PettyCashDisbursementEvent": handle_PettyCashDisbursementEvent,
    "PettyCashReplenishedEvent": handle_PettyCashReplenishedEvent,
    "PettyCashSuspendedEvent": handle_PettyCashSuspendedEvent,
    "ProductionCompletedEvent": handle_ProductionCompletedEvent,
    "ProjectActivatedEvent": handle_ProjectActivatedEvent,
    "ProjectBillingGeneratedEvent": handle_ProjectBillingGeneratedEvent,
    "ProjectCompletedEvent": handle_ProjectCompletedEvent,
    "ProjectCreatedEvent": handle_ProjectCreatedEvent,
    "PurchaseInvoiceReceivedEvent": handle_PurchaseInvoiceReceivedEvent,
    "PurchaseOrderApprovedEvent": handle_PurchaseOrderApprovedEvent,
    "PurchaseOrderCreatedEvent": handle_PurchaseOrderCreatedEvent,
    "RetainedEarningsAdjustedEvent": handle_RetainedEarningsAdjustedEvent,
    "RetainedEarningsTransferEvent": handle_RetainedEarningsTransferEvent,
    "RetainedEarningsUpdatedEvent": handle_RetainedEarningsUpdatedEvent,
    "RetainerContractActivatedEvent": handle_RetainerContractActivatedEvent,
    "RevenueRecognizedEvent": handle_RevenueRecognizedEvent,
    "RoleAssignedEvent": handle_RoleAssignedEvent,
    "RoleCreatedEvent": handle_RoleCreatedEvent,
    "RoleDeletedEvent": handle_RoleDeletedEvent,
    "RoleRevokedEvent": handle_RoleRevokedEvent,
    "RoleUpdatedEvent": handle_RoleUpdatedEvent,
    "SPTApprovedEvent": handle_SPTApprovedEvent,
    "SPTSubmittedEvent": handle_SPTSubmittedEvent,
    "SalaryComponentAddedEvent": handle_SalaryComponentAddedEvent,
    "SalesInvoiceIssuedEvent": handle_SalesInvoiceIssuedEvent,
    "SalesInvoicePaidEvent": handle_SalesInvoicePaidEvent,
    "SalesOrderApprovedEvent": handle_SalesOrderApprovedEvent,
    "SalesOrderCreatedEvent": handle_SalesOrderCreatedEvent,
    "SessionCompromisedEvent": handle_SessionCompromisedEvent,
    "SessionCreatedEvent": handle_SessionCreatedEvent,
    "SessionRefreshedEvent": handle_SessionRefreshedEvent,
    "SessionTerminatedEvent": handle_SessionTerminatedEvent,
    "SettingAddedEvent": handle_SettingAddedEvent,
    "SettingChangedEvent": handle_SettingChangedEvent,
    "SettingRemovedEvent": handle_SettingRemovedEvent,
    "SettingResetEvent": handle_SettingResetEvent,
    "SettingsBulkUpdatedEvent": handle_SettingsBulkUpdatedEvent,
    "SettingsLockedEvent": handle_SettingsLockedEvent,
    "SettingsUnlockedEvent": handle_SettingsUnlockedEvent,
    "StandardCostActivatedEvent": handle_StandardCostActivatedEvent,
    "StandardCostCreatedEvent": handle_StandardCostCreatedEvent,
    "StockAdjustedEvent": handle_StockAdjustedEvent,
    "StockLevelAlertEvent": handle_StockLevelAlertEvent,
    "StockMovementCreatedEvent": handle_StockMovementCreatedEvent,
    "StockOpnameApprovedEvent": handle_StockOpnameApprovedEvent,
    "StockOpnameCreatedEvent": handle_StockOpnameCreatedEvent,
    "SupplierCreatedEvent": handle_SupplierCreatedEvent,
    "SupplierPaymentTermsChangedEvent": handle_SupplierPaymentTermsChangedEvent,
    "SupplierWithholdingCategoryChangedEvent": handle_SupplierWithholdingCategoryChangedEvent,
    "TaxCalculatedEvent": handle_TaxCalculatedEvent,
    "TaxProfileUpdatedEvent": handle_TaxProfileUpdatedEvent,
    "ThreeWayMatchResultEvent": handle_ThreeWayMatchResultEvent,
    "TimeEntryApprovedEvent": handle_TimeEntryApprovedEvent,
    "TimeEntrySubmittedEvent": handle_TimeEntrySubmittedEvent,
    "TransactionCreatedEvent": handle_TransactionCreatedEvent,
    "TransactionDeletedEvent": handle_TransactionDeletedEvent,
    "TransactionRecordedEvent": handle_TransactionRecordedEvent,
    "TransactionUpdatedEvent": handle_TransactionUpdatedEvent,
    "TransferCompletedEvent": handle_TransferCompletedEvent,
    "UserActivatedEvent": handle_UserActivatedEvent,
    "UserCreatedEvent": handle_UserCreatedEvent,
    "UserDeactivatedEvent": handle_UserDeactivatedEvent,
    "UserDeletedEvent": handle_UserDeletedEvent,
    "UserPasswordChangedEvent": handle_UserPasswordChangedEvent,
    "UserSuspendedEvent": handle_UserSuspendedEvent,
    "UserUnlockedEvent": handle_UserUnlockedEvent,
    "UserUpdatedEvent": handle_UserUpdatedEvent,
    "VarianceAnalyzedEvent": handle_VarianceAnalyzedEvent,
    "WorkOrderApprovedEvent": handle_WorkOrderApprovedEvent,
    "WorkOrderCancelledEvent": handle_WorkOrderCancelledEvent,
    "WorkOrderCompletedEvent": handle_WorkOrderCompletedEvent,
    "WorkOrderCreatedEvent": handle_WorkOrderCreatedEvent,
    "WorkOrderStartedEvent": handle_WorkOrderStartedEvent,
    "DomainEventType": handle_DomainEventType,
    "DomainEventPublisher": handle_DomainEventPublisher,
    "BudgetEventType": handle_BudgetEventType,
    "BudgetEventPublisher": handle_BudgetEventPublisher,
    "EventStore": handle_EventStore,
    "ConsolidationEventType": handle_ConsolidationEventType,
    "ConsolidationEventPublisher": handle_ConsolidationEventPublisher,


}

def register_all_handlers(registry) -> None:
    """Register semua event handler ke registry."""
    for event_name, handler in ALL_HANDLERS.items():
        registry.register_handler(event_name, handler)
    logger.info(f"Registered {len(ALL_HANDLERS)} event handlers.")
