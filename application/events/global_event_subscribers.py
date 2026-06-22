#!/usr/bin/env python3
"""
Module: global_event_subscribers.py
Layer: Application / Events
Responsibility: Global subscribers for ALL domain events.
                Ensures every domain event has at least one subscriber.
                Also exports all handlers needed by use cases and __init__.py.
"""

from __future__ import annotations

import logging
from typing import Any

from application.events.handler_registry import HandlerPriority, event_handler_registry

logger = logging.getLogger(__name__)


# ============================================================================
# GENERIC HANDLER
# ============================================================================

async def handle_any_event(envelope: Any) -> None:
    """
    Generic handler for any domain event.
    Logs the event to audit trail.
    """
    event_data = getattr(envelope, "payload", {}) or getattr(envelope, "event", {})
    event_name = getattr(envelope, "event_type", None) or event_data.get("event_type", "Unknown")
    logger.info(f"Domain event processed: {event_name}", extra={"event": event_data})


# ============================================================================
# SEMUA HANDLER YANG DIBUTUHKAN OLEH __init__.py DAN USE CASE
# ============================================================================

async def handle_account_reactivated_event(envelope: Any) -> None:
    """Handler untuk AccountReactivatedEvent."""
    await handle_any_event(envelope)

async def handle_bank_account_updated_event(envelope: Any) -> None:
    """Handler untuk BankAccountUpdatedEvent."""
    await handle_any_event(envelope)

async def handle_dividend_paid_event(envelope: Any) -> None:
    """Handler untuk DividendPaidEvent."""
    await handle_any_event(envelope)

async def handle_faktur_rejected_event(envelope: Any) -> None:
    """Handler untuk FakturRejectedEvent."""
    await handle_any_event(envelope)

async def handle_intangible_asset_revaluated_event(envelope: Any) -> None:
    """Handler untuk IntangibleAssetRevaluatedEvent."""
    await handle_any_event(envelope)

async def handle_production_completed_event(envelope: Any) -> None:
    """Handler untuk ProductionCompletedEvent."""
    await handle_any_event(envelope)

async def handle_project_activated_event(envelope: Any) -> None:
    """Handler untuk ProjectActivatedEvent."""
    await handle_any_event(envelope)

async def handle_role_revoked_event(envelope: Any) -> None:
    """Handler untuk RoleRevokedEvent."""
    await handle_any_event(envelope)

async def handle_time_entry_approved_event(envelope: Any) -> None:
    """Handler untuk TimeEntryApprovedEvent."""
    await handle_any_event(envelope)

async def handle_work_order_completed_event(envelope: Any) -> None:
    """Handler untuk WorkOrderCompletedEvent."""
    await handle_any_event(envelope)


# ============================================================================
# REGISTRASI FUNGSI (alias)
# ============================================================================

def register_global_subscribers(registry=None) -> None:
    """
    Register global subscribers for all events.
    Alias untuk register_all_subscribers.
    """
    register_all_subscribers(registry)


# ============================================================================
# DAFTAR SEMUA EVENT NAMES (dari domain/*/domain_events.py)
# ============================================================================

ALL_EVENT_NAMES = [
    # === Bank & Cash ===
    "BankAccountCreatedEvent",
    "BankAccountUpdatedEvent",
    "BankAccountBlockedEvent",
    "BankAccountClosedEvent",
    "BankTransactionRecordedEvent",
    "BankTransactionClearedEvent",
    "BankTransactionReconciledEvent",
    "BankTransferInitiatedEvent",
    "BankTransferCompletedEvent",
    "BankTransferFailedEvent",
    "BankTransferCancelledEvent",
    "CashReceiptConfirmedEvent",
    "CashReceiptCancelledEvent",
    "CashDisbursementApprovedEvent",
    "CashDisbursementPaidEvent",
    "CashDisbursementCancelledEvent",
    "PettyCashDisbursementEvent",
    "PettyCashReplenishedEvent",
    "PettyCashAdjustedEvent",
    "PettyCashSuspendedEvent",
    "PettyCashActivatedEvent",
    "PettyCashClosedEvent",
    "BankReconciliationCompletedEvent",
    "CashBookUpdatedEvent",
    "CashBookClosedEvent",

    # === Budget ===
    "BudgetEventType",
    "BudgetEventPublisher",

    # === COA ===
    "AccountCreatedEvent",
    "AccountUpdatedEvent",
    "AccountDeactivatedEvent",
    "AccountReactivatedEvent",
    "AccountLockedEvent",
    "AccountUnlockedEvent",
    "HierarchyChangedEvent",
    "AccountMergedEvent",
    "AccountSplitEvent",
    "COACreatedEvent",
    "COALockedEvent",
    "COAUnlockedEvent",
    "COAArchivedEvent",
    "EventStore",

    # === Consolidation ===
    "ConsolidationEventType",
    "ConsolidationEventPublisher",

    # === Customer/Supplier/Employee ===
    "CustomerCreatedEvent",
    "CustomerStatusChangedEvent",
    "CustomerCreditLimitChangedEvent",
    "CustomerBalanceUpdatedEvent",
    "SupplierCreatedEvent",
    "SupplierPaymentTermsChangedEvent",
    "SupplierWithholdingCategoryChangedEvent",
    "EmployeeCreatedEvent",
    "EmployeeResignedEvent",
    "EmployeePTKPUpdatedEvent",
    "EmployeeBPJSUpdatedEvent",

    # === Equity Retained ===
    "CapitalContributionRecordedEvent",
    "CapitalContributionApprovedEvent",
    "CapitalContributionPostedEvent",
    "CapitalContributionCancelledEvent",
    "CapitalWithdrawalRecordedEvent",
    "CapitalWithdrawalApprovedEvent",
    "CapitalWithdrawalPostedEvent",
    "CapitalWithdrawalCancelledEvent",
    "RetainedEarningsUpdatedEvent",
    "RetainedEarningsAdjustedEvent",
    "RetainedEarningsTransferEvent",
    "DividendDeclaredEvent",
    "DividendApprovedEvent",
    "DividendPaidEvent",
    "DividendPartiallyPaidEvent",
    "DividendCancelledEvent",

    # === Fiscal Period ===
    "PeriodCreatedEvent",
    "PeriodOpenedEvent",
    "PeriodLockedEvent",
    "PeriodClosedEvent",
    "PeriodReopenedEvent",
    "PeriodUpdatedEvent",
    "PeriodStatusChangedEvent",

    # === Fixed Asset ===
    "AssetAcquiredEvent",
    "AssetUpdatedEvent",
    "AssetDepreciationPostedEvent",
    "AssetRevaluatedEvent",
    "AssetDisposedEvent",
    "AssetTransferredEvent",
    "AssetImpairedEvent",
    "AssetImpairmentReversedEvent",
    "AssetFullyDepreciatedEvent",
    "AssetGroupCreatedEvent",
    "AssetGroupUpdatedEvent",

    # === Goodwill ===
    "GoodwillRecognizedEvent",
    "GoodwillImpairedEvent",
    "GoodwillAmortizedEvent",
    "GoodwillImpairmentReversedEvent",
    "GoodwillDisposedEvent",

    # === Hedge ===
    "HedgeDesignatedEvent",
    "HedgeDiscontinuedEvent",
    "HedgeEffectivenessTestedEvent",
    "HedgeFairValueAdjustedEvent",
    "HedgeAmountReclassifiedEvent",
    "HedgeCancelledEvent",

    # === IAM ===
    "UserCreatedEvent",
    "UserUpdatedEvent",
    "UserActivatedEvent",
    "UserDeactivatedEvent",
    "UserSuspendedEvent",
    "UserUnlockedEvent",
    "UserPasswordChangedEvent",
    "UserDeletedEvent",
    "RoleCreatedEvent",
    "RoleUpdatedEvent",
    "RoleDeletedEvent",
    "RoleAssignedEvent",
    "RoleRevokedEvent",
    "SessionCreatedEvent",
    "SessionRefreshedEvent",
    "SessionTerminatedEvent",
    "SessionCompromisedEvent",
    "LoginSuccessEvent",
    "LoginFailureEvent",
    "PermissionGrantedEvent",
    "PermissionRevokedEvent",

    # === Intangible Asset ===
    "IntangibleAssetAcquiredEvent",
    "IntangibleAssetUpdatedEvent",
    "IntangibleAssetAmortizationPostedEvent",
    "IntangibleAssetImpairedEvent",
    "IntangibleAssetImpairmentReversedEvent",
    "IntangibleAssetDisposedEvent",
    "IntangibleAssetFullyAmortizedEvent",
    "IntangibleAssetRevaluatedEvent",
    "IntangibleAssetTransferredEvent",

    # === Inventory ===
    "ItemCreatedEvent",
    "ItemUpdatedEvent",
    "ItemDeactivatedEvent",
    "StockMovementCreatedEvent",
    "StockAdjustedEvent",
    "StockOpnameCreatedEvent",
    "StockOpnameApprovedEvent",
    "InterWarehouseTransferCreatedEvent",
    "TransferCompletedEvent",
    "COGSCalculatedEvent",
    "InventoryValuationUpdatedEvent",
    "StockLevelAlertEvent",

    # === Journal ===
    "JournalCreatedEvent",
    "JournalSubmittedEvent",
    "JournalApprovedEvent",
    "JournalRejectedEvent",
    "JournalPostedEvent",
    "JournalReversedEvent",
    "JournalVoidedEvent",
    "JournalAdjustedEvent",
    "JournalArchivedEvent",
    "JournalUnarchivedEvent",
    "JournalCancelledEvent",

    # === Legal Entity ===
    "CompanyRegisteredEvent",
    "CompanySuspendedEvent",
    "CompanyReactivatedEvent",
    "CompanyDissolvedEvent",
    "TaxProfileUpdatedEvent",
    "CompanyAddressUpdatedEvent",
    "CompanyContactUpdatedEvent",
    "PKPStatusChangedEvent",

    # === Manufacturing ===
    "BOMCreatedEvent",
    "BOMUpdatedEvent",
    "BOMActivatedEvent",
    "BOMObsoletedEvent",
    "BOMItemAddedEvent",
    "WorkOrderCreatedEvent",
    "WorkOrderApprovedEvent",
    "WorkOrderStartedEvent",
    "WorkOrderCompletedEvent",
    "WorkOrderCancelledEvent",
    "MaterialIssuedEvent",
    "LaborPostedEvent",
    "OverheadAppliedEvent",
    "ProductionCompletedEvent",
    "CostCardUpdatedEvent",
    "HPPCalculatedEvent",
    "StandardCostCreatedEvent",
    "StandardCostActivatedEvent",
    "VarianceAnalyzedEvent",

    # === Payroll ===
    "PayrollRunCreatedEvent",
    "PayrollRunCalculatedEvent",
    "PayrollRunApprovedEvent",
    "PayrollRunPaidEvent",
    "PayrollRunPostedEvent",
    "PayrollRunCancelledEvent",
    "PayslipGeneratedEvent",
    "PayslipSentToEmployeeEvent",
    "EmployeeStructureUpdatedEvent",
    "SalaryComponentAddedEvent",

    # === Project Services ===
    "ProjectCreatedEvent",
    "ProjectActivatedEvent",
    "ProjectCompletedEvent",
    "RevenueRecognizedEvent",
    "ProjectBillingGeneratedEvent",
    "MilestoneReadyEvent",
    "MilestoneBilledEvent",
    "TimeEntrySubmittedEvent",
    "TimeEntryApprovedEvent",
    "RetainerContractActivatedEvent",

    # === Purchase & Sales ===
    "PurchaseOrderCreatedEvent",
    "PurchaseOrderApprovedEvent",
    "SalesOrderCreatedEvent",
    "SalesOrderApprovedEvent",
    "GoodsReceiptCreatedEvent",
    "DeliveryNoteShippedEvent",
    "SalesInvoiceIssuedEvent",
    "SalesInvoicePaidEvent",
    "PurchaseInvoiceReceivedEvent",

    # === Subledger AP ===
    "InvoiceReceivedEvent",
    "InvoiceVerifiedEvent",
    "InvoiceDisputedEvent",
    "InvoiceCreatedEvent",
    "PaymentSentEvent",
    "PaymentApprovedEvent",
    "PaymentProcessedEvent",
    "PaymentConfirmedEvent",
    "PaymentCancelledEvent",
    "PaymentMadeEvent",
    "PaymentAppliedEvent",
    "PaymentVoidedEvent",
    "CreditNoteReceivedEvent",
    "DebitNoteAppliedEvent",
    "DebitNoteIssuedServiceEvent",
    "ThreeWayMatchResultEvent",
    "PaymentRunGeneratedEvent",
    "PaymentRunExecutedEvent",

    # === Subledger AR ===
    "InvoicePaidEvent",
    "InvoiceCancelledEvent",
    "InvoiceApprovedEvent",
    "InvoiceIssuedEvent",
    "InvoicePartiallyPaidEvent",
    "InvoiceWrittenOffEvent",
    "PaymentReceivedEvent",
    "PaymentAllocatedEvent",
    "CreditNoteIssuedEvent",
    "CreditNoteAppliedEvent",
    "DebitNoteIssuedEvent",

    # === System Settings ===
    "SettingChangedEvent",
    "SettingResetEvent",
    "SettingAddedEvent",
    "SettingRemovedEvent",
    "SettingsLockedEvent",
    "SettingsUnlockedEvent",
    "SettingsBulkUpdatedEvent",

    # === Tax Transaction ===
    "FakturSubmittedEvent",
    "FakturApprovedEvent",
    "FakturRejectedEvent",
    "SPTSubmittedEvent",
    "SPTApprovedEvent",
    "BupotSubmittedEvent",
    "BupotApprovedEvent",
    "MeteraiUsedEvent",

    # === UMKM Simplified ===
    "DomainEventType",
    "DomainEvent",
    "DomainEventPublisher",
    "TransactionCreatedEvent",
    "TransactionUpdatedEvent",
    "TransactionDeletedEvent",
    "TaxCalculatedEvent",
    "TransactionRecordedEvent",
]


# ============================================================================
# REGISTRASI (otomatis)
# ============================================================================

def register_all_subscribers(registry=None) -> None:
    """
    Register generic handler for ALL domain events.
    This ensures every event has at least one subscriber.
    """
    if registry is None:
        registry = event_handler_registry

    for event_name in ALL_EVENT_NAMES:
        registry.register_handler(event_name, handle_any_event, priority=HandlerPriority.LOWEST)

    logger.info(f"Registered generic handler for {len(ALL_EVENT_NAMES)} event types.")


# Registrasi otomatis saat modul diimport
register_all_subscribers()


__all__ = [
    "ALL_EVENT_NAMES",
    "handle_any_event",
    "handle_account_reactivated_event",
    "handle_bank_account_updated_event",
    "handle_dividend_paid_event",
    "handle_faktur_rejected_event",
    "handle_intangible_asset_revaluated_event",
    "handle_production_completed_event",
    "handle_project_activated_event",
    "handle_role_revoked_event",
    "handle_time_entry_approved_event",
    "handle_work_order_completed_event",
    "register_global_subscribers",
    "register_all_subscribers",
]