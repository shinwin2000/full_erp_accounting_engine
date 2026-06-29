"""
ALL EVENT HANDLERS - AUTO-GENERATED (CLEANED & FIXED)
======================================================
Total events: 298
Setiap event memiliki handler sendiri (spesifik).
Handler saat ini hanya mencatat log; Anda dapat menambahkan logika bisnis.
"""

import logging

from application.events.handler_registry import (
    HandlerAlreadyRegisteredError,
    HandlerPriority,
    event_handler_registry,
)
from application.events.publisher_application import EventEnvelope

logger = logging.getLogger("event_handlers")


# ============================================================================
# HANDLER FUNCTIONS (semua dengan suffix "Event")
# ============================================================================

async def handle_AccountCreatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"AccountCreatedEvent diterima: {envelope.event}")


async def handle_AccountDeactivatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"AccountDeactivatedEvent diterima: {envelope.event}")


async def handle_AccountLockedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"AccountLockedEvent diterima: {envelope.event}")


async def handle_AccountMergedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"AccountMergedEvent diterima: {envelope.event}")


async def handle_AccountReactivatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"AccountReactivatedEvent diterima: {envelope.event}")


async def handle_AccountSplitEvent(envelope: EventEnvelope) -> None:
    logger.info(f"AccountSplitEvent diterima: {envelope.event}")


async def handle_AccountUnlockedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"AccountUnlockedEvent diterima: {envelope.event}")


async def handle_AccountUpdatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"AccountUpdatedEvent diterima: {envelope.event}")


async def handle_AssetAcquiredEvent(envelope: EventEnvelope) -> None:
    logger.info(f"AssetAcquiredEvent diterima: {envelope.event}")


async def handle_AssetDepreciationPostedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"AssetDepreciationPostedEvent diterima: {envelope.event}")


async def handle_AssetDisposedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"AssetDisposedEvent diterima: {envelope.event}")


async def handle_AssetFullyDepreciatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"AssetFullyDepreciatedEvent diterima: {envelope.event}")


async def handle_AssetGroupCreatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"AssetGroupCreatedEvent diterima: {envelope.event}")


async def handle_AssetGroupUpdatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"AssetGroupUpdatedEvent diterima: {envelope.event}")


async def handle_AssetImpairedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"AssetImpairedEvent diterima: {envelope.event}")


async def handle_AssetImpairmentReversedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"AssetImpairmentReversedEvent diterima: {envelope.event}")


async def handle_AssetRevaluatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"AssetRevaluatedEvent diterima: {envelope.event}")


async def handle_AssetTransferredEvent(envelope: EventEnvelope) -> None:
    logger.info(f"AssetTransferredEvent diterima: {envelope.event}")


async def handle_AssetUpdatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"AssetUpdatedEvent diterima: {envelope.event}")


async def handle_AuditEvent(envelope: EventEnvelope) -> None:
    logger.info(f"AuditEvent diterima: {envelope.event}")


async def handle_BOMActivatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"BOMActivatedEvent diterima: {envelope.event}")


async def handle_BOMCreatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"BOMCreatedEvent diterima: {envelope.event}")


async def handle_BOMItemAddedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"BOMItemAddedEvent diterima: {envelope.event}")


async def handle_BOMObsoletedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"BOMObsoletedEvent diterima: {envelope.event}")


async def handle_BOMUpdatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"BOMUpdatedEvent diterima: {envelope.event}")


async def handle_BankAccountBlockedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"BankAccountBlockedEvent diterima: {envelope.event}")


async def handle_BankAccountClosedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"BankAccountClosedEvent diterima: {envelope.event}")


async def handle_BankAccountCreatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"BankAccountCreatedEvent diterima: {envelope.event}")


async def handle_BankAccountUpdatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"BankAccountUpdatedEvent diterima: {envelope.event}")


async def handle_BankReconciliationCompletedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"BankReconciliationCompletedEvent diterima: {envelope.event}")


async def handle_BankTransactionClearedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"BankTransactionClearedEvent diterima: {envelope.event}")


async def handle_BankTransactionReconciledEvent(envelope: EventEnvelope) -> None:
    logger.info(f"BankTransactionReconciledEvent diterima: {envelope.event}")


async def handle_BankTransactionRecordedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"BankTransactionRecordedEvent diterima: {envelope.event}")


async def handle_BankTransferCancelledEvent(envelope: EventEnvelope) -> None:
    logger.info(f"BankTransferCancelledEvent diterima: {envelope.event}")


async def handle_BankTransferCompletedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"BankTransferCompletedEvent diterima: {envelope.event}")


async def handle_BankTransferExecutedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"BankTransferExecutedEvent diterima: {envelope.event}")


async def handle_BankTransferFailedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"BankTransferFailedEvent diterima: {envelope.event}")


async def handle_BankTransferInitiatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"BankTransferInitiatedEvent diterima: {envelope.event}")


async def handle_BudgetApprovedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"BudgetApprovedEvent diterima: {envelope.event}")


async def handle_BudgetArchivedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"BudgetArchivedEvent diterima: {envelope.event}")


async def handle_BudgetCancelledEvent(envelope: EventEnvelope) -> None:
    logger.info(f"BudgetCancelledEvent diterima: {envelope.event}")


async def handle_BudgetClosedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"BudgetClosedEvent diterima: {envelope.event}")


async def handle_BudgetCreatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"BudgetCreatedEvent diterima: {envelope.event}")


async def handle_BudgetLineAddedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"BudgetLineAddedEvent diterima: {envelope.event}")


async def handle_BudgetLineAdjustedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"BudgetLineAdjustedEvent diterima: {envelope.event}")


async def handle_BudgetLineRemovedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"BudgetLineRemovedEvent diterima: {envelope.event}")


async def handle_BudgetRejectedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"BudgetRejectedEvent diterima: {envelope.event}")


async def handle_BudgetRevisedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"BudgetRevisedEvent diterima: {envelope.event}")


async def handle_BudgetStatusChangedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"BudgetStatusChangedEvent diterima: {envelope.event}")


async def handle_BupotApprovedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"BupotApprovedEvent diterima: {envelope.event}")


async def handle_BupotSubmittedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"BupotSubmittedEvent diterima: {envelope.event}")


async def handle_COAArchivedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"COAArchivedEvent diterima: {envelope.event}")


async def handle_COACreatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"COACreatedEvent diterima: {envelope.event}")


async def handle_COALockedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"COALockedEvent diterima: {envelope.event}")


async def handle_COAUnlockedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"COAUnlockedEvent diterima: {envelope.event}")


async def handle_COGSCalculatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"COGSCalculatedEvent diterima: {envelope.event}")


async def handle_CapitalContributionApprovedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"CapitalContributionApprovedEvent diterima: {envelope.event}")


async def handle_CapitalContributionCancelledEvent(envelope: EventEnvelope) -> None:
    logger.info(f"CapitalContributionCancelledEvent diterima: {envelope.event}")


async def handle_CapitalContributionPostedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"CapitalContributionPostedEvent diterima: {envelope.event}")


async def handle_CapitalContributionRecordedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"CapitalContributionRecordedEvent diterima: {envelope.event}")


async def handle_CapitalWithdrawalApprovedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"CapitalWithdrawalApprovedEvent diterima: {envelope.event}")


async def handle_CapitalWithdrawalCancelledEvent(envelope: EventEnvelope) -> None:
    logger.info(f"CapitalWithdrawalCancelledEvent diterima: {envelope.event}")


async def handle_CapitalWithdrawalPostedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"CapitalWithdrawalPostedEvent diterima: {envelope.event}")


async def handle_CapitalWithdrawalRecordedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"CapitalWithdrawalRecordedEvent diterima: {envelope.event}")


async def handle_CashBookClosedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"CashBookClosedEvent diterima: {envelope.event}")


async def handle_CashBookUpdatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"CashBookUpdatedEvent diterima: {envelope.event}")


async def handle_CashDisbursementApprovedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"CashDisbursementApprovedEvent diterima: {envelope.event}")


async def handle_CashDisbursementCancelledEvent(envelope: EventEnvelope) -> None:
    logger.info(f"CashDisbursementCancelledEvent diterima: {envelope.event}")


async def handle_CashDisbursementIssuedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"CashDisbursementIssuedEvent diterima: {envelope.event}")


async def handle_CashDisbursementPaidEvent(envelope: EventEnvelope) -> None:
    logger.info(f"CashDisbursementPaidEvent diterima: {envelope.event}")


async def handle_CashReceiptCancelledEvent(envelope: EventEnvelope) -> None:
    logger.info(f"CashReceiptCancelledEvent diterima: {envelope.event}")


async def handle_CashReceiptConfirmedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"CashReceiptConfirmedEvent diterima: {envelope.event}")


async def handle_CashReceiptIssuedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"CashReceiptIssuedEvent diterima: {envelope.event}")


async def handle_CompanyAddressUpdatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"CompanyAddressUpdatedEvent diterima: {envelope.event}")


async def handle_CompanyContactUpdatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"CompanyContactUpdatedEvent diterima: {envelope.event}")


async def handle_CompanyDissolvedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"CompanyDissolvedEvent diterima: {envelope.event}")


async def handle_CompanyReactivatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"CompanyReactivatedEvent diterima: {envelope.event}")


async def handle_CompanyRegisteredEvent(envelope: EventEnvelope) -> None:
    logger.info(f"CompanyRegisteredEvent diterima: {envelope.event}")


async def handle_CompanySuspendedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"CompanySuspendedEvent diterima: {envelope.event}")


async def handle_ConsolidationArchivedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"ConsolidationArchivedEvent diterima: {envelope.event}")


async def handle_ConsolidationCancelledEvent(envelope: EventEnvelope) -> None:
    logger.info(f"ConsolidationCancelledEvent diterima: {envelope.event}")


async def handle_ConsolidationCompletedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"ConsolidationCompletedEvent diterima: {envelope.event}")


async def handle_ConsolidationCreatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"ConsolidationCreatedEvent diterima: {envelope.event}")


async def handle_ConsolidationStartedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"ConsolidationStartedEvent diterima: {envelope.event}")


async def handle_CostCardUpdatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"CostCardUpdatedEvent diterima: {envelope.event}")


async def handle_CreditNoteAppliedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"CreditNoteAppliedEvent diterima: {envelope.event}")


async def handle_CreditNoteIssuedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"CreditNoteIssuedEvent diterima: {envelope.event}")


async def handle_CreditNoteReceivedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"CreditNoteReceivedEvent diterima: {envelope.event}")


async def handle_CustomerBalanceUpdatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"CustomerBalanceUpdatedEvent diterima: {envelope.event}")


async def handle_CustomerCreatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"CustomerCreatedEvent diterima: {envelope.event}")


async def handle_CustomerCreditLimitChangedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"CustomerCreditLimitChangedEvent diterima: {envelope.event}")


async def handle_CustomerStatusChangedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"CustomerStatusChangedEvent diterima: {envelope.event}")


async def handle_DebitNoteAppliedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"DebitNoteAppliedEvent diterima: {envelope.event}")


async def handle_DebitNoteIssuedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"DebitNoteIssuedEvent diterima: {envelope.event}")


async def handle_DebitNoteIssuedServiceEvent(envelope: EventEnvelope) -> None:
    logger.info(f"DebitNoteIssuedServiceEvent diterima: {envelope.event}")


async def handle_DeliveryNoteShippedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"DeliveryNoteShippedEvent diterima: {envelope.event}")


async def handle_DividendApprovedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"DividendApprovedEvent diterima: {envelope.event}")


async def handle_DividendCancelledEvent(envelope: EventEnvelope) -> None:
    logger.info(f"DividendCancelledEvent diterima: {envelope.event}")


async def handle_DividendDeclaredEvent(envelope: EventEnvelope) -> None:
    logger.info(f"DividendDeclaredEvent diterima: {envelope.event}")


async def handle_DividendPaidEvent(envelope: EventEnvelope) -> None:
    logger.info(f"DividendPaidEvent diterima: {envelope.event}")


async def handle_DividendPartiallyPaidEvent(envelope: EventEnvelope) -> None:
    logger.info(f"DividendPartiallyPaidEvent diterima: {envelope.event}")


async def handle_DomainEvent(envelope: EventEnvelope) -> None:
    logger.info(f"DomainEvent diterima: {envelope.event}")


async def handle_EconomicEvent(envelope: EventEnvelope) -> None:
    logger.info(f"EconomicEvent diterima: {envelope.event}")


async def handle_EliminationEntryCreatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"EliminationEntryCreatedEvent diterima: {envelope.event}")


async def handle_EmployeeBPJSUpdatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"EmployeeBPJSUpdatedEvent diterima: {envelope.event}")


async def handle_EmployeeCreatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"EmployeeCreatedEvent diterima: {envelope.event}")


async def handle_EmployeePTKPUpdatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"EmployeePTKPUpdatedEvent diterima: {envelope.event}")


async def handle_EmployeeResignedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"EmployeeResignedEvent diterima: {envelope.event}")


async def handle_EmployeeStructureUpdatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"EmployeeStructureUpdatedEvent diterima: {envelope.event}")


async def handle_FakturApprovedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"FakturApprovedEvent diterima: {envelope.event}")


async def handle_FakturRejectedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"FakturRejectedEvent diterima: {envelope.event}")


async def handle_FakturSubmittedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"FakturSubmittedEvent diterima: {envelope.event}")


async def handle_GoodsReceiptCreatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"GoodsReceiptCreatedEvent diterima: {envelope.event}")


async def handle_GoodwillAmortizedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"GoodwillAmortizedEvent diterima: {envelope.event}")


async def handle_GoodwillDisposedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"GoodwillDisposedEvent diterima: {envelope.event}")


async def handle_GoodwillImpairedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"GoodwillImpairedEvent diterima: {envelope.event}")


async def handle_GoodwillImpairmentReversedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"GoodwillImpairmentReversedEvent diterima: {envelope.event}")


async def handle_GoodwillRecognizedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"GoodwillRecognizedEvent diterima: {envelope.event}")


async def handle_GoodwillUpdatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"GoodwillUpdatedEvent diterima: {envelope.event}")


async def handle_HPPCalculatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"HPPCalculatedEvent diterima: {envelope.event}")


async def handle_HedgeAmountReclassifiedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"HedgeAmountReclassifiedEvent diterima: {envelope.event}")


async def handle_HedgeCancelledEvent(envelope: EventEnvelope) -> None:
    logger.info(f"HedgeCancelledEvent diterima: {envelope.event}")


async def handle_HedgeDesignatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"HedgeDesignatedEvent diterima: {envelope.event}")


async def handle_HedgeDiscontinuedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"HedgeDiscontinuedEvent diterima: {envelope.event}")


async def handle_HedgeEffectivenessTestedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"HedgeEffectivenessTestedEvent diterima: {envelope.event}")


async def handle_HedgeFairValueAdjustedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"HedgeFairValueAdjustedEvent diterima: {envelope.event}")


async def handle_HierarchyChangedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"HierarchyChangedEvent diterima: {envelope.event}")


async def handle_IntangibleAssetAcquiredEvent(envelope: EventEnvelope) -> None:
    logger.info(f"IntangibleAssetAcquiredEvent diterima: {envelope.event}")


async def handle_IntangibleAssetAmortizationPostedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"IntangibleAssetAmortizationPostedEvent diterima: {envelope.event}")


async def handle_IntangibleAssetDisposedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"IntangibleAssetDisposedEvent diterima: {envelope.event}")


async def handle_IntangibleAssetFullyAmortizedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"IntangibleAssetFullyAmortizedEvent diterima: {envelope.event}")


async def handle_IntangibleAssetImpairedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"IntangibleAssetImpairedEvent diterima: {envelope.event}")


async def handle_IntangibleAssetImpairmentReversedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"IntangibleAssetImpairmentReversedEvent diterima: {envelope.event}")


async def handle_IntangibleAssetRevaluatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"IntangibleAssetRevaluatedEvent diterima: {envelope.event}")


async def handle_IntangibleAssetTransferredEvent(envelope: EventEnvelope) -> None:
    logger.info(f"IntangibleAssetTransferredEvent diterima: {envelope.event}")


async def handle_IntangibleAssetUpdatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"IntangibleAssetUpdatedEvent diterima: {envelope.event}")


async def handle_IntegrationEvent(envelope: EventEnvelope) -> None:
    logger.info(f"IntegrationEvent diterima: {envelope.event}")


async def handle_InterWarehouseTransferCreatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"InterWarehouseTransferCreatedEvent diterima: {envelope.event}")


async def handle_IntercompanyTransactionDetectedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"IntercompanyTransactionDetectedEvent diterima: {envelope.event}")


async def handle_InventoryValuationUpdatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"InventoryValuationUpdatedEvent diterima: {envelope.event}")


async def handle_InvoiceApprovedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"InvoiceApprovedEvent diterima: {envelope.event}")


async def handle_InvoiceCancelledEvent(envelope: EventEnvelope) -> None:
    logger.info(f"InvoiceCancelledEvent diterima: {envelope.event}")


async def handle_InvoiceCreatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"InvoiceCreatedEvent diterima: {envelope.event}")


async def handle_InvoiceDisputedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"InvoiceDisputedEvent diterima: {envelope.event}")


async def handle_InvoiceIssuedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"InvoiceIssuedEvent diterima: {envelope.event}")


async def handle_InvoicePaidEvent(envelope: EventEnvelope) -> None:
    logger.info(f"InvoicePaidEvent diterima: {envelope.event}")


async def handle_InvoicePartiallyPaidEvent(envelope: EventEnvelope) -> None:
    logger.info(f"InvoicePartiallyPaidEvent diterima: {envelope.event}")


async def handle_InvoiceReceivedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"InvoiceReceivedEvent diterima: {envelope.event}")


async def handle_InvoiceVerifiedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"InvoiceVerifiedEvent diterima: {envelope.event}")


async def handle_InvoiceWrittenOffEvent(envelope: EventEnvelope) -> None:
    logger.info(f"InvoiceWrittenOffEvent diterima: {envelope.event}")


async def handle_ItemCreatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"ItemCreatedEvent diterima: {envelope.event}")


async def handle_ItemDeactivatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"ItemDeactivatedEvent diterima: {envelope.event}")


async def handle_ItemUpdatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"ItemUpdatedEvent diterima: {envelope.event}")


async def handle_JournalAdjustedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"JournalAdjustedEvent diterima: {envelope.event}")


async def handle_JournalApprovedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"JournalApprovedEvent diterima: {envelope.event}")


async def handle_JournalArchivedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"JournalArchivedEvent diterima: {envelope.event}")


async def handle_JournalCancelledEvent(envelope: EventEnvelope) -> None:
    logger.info(f"JournalCancelledEvent diterima: {envelope.event}")


async def handle_JournalCreatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"JournalCreatedEvent diterima: {envelope.event}")


async def handle_JournalPostedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"JournalPostedEvent diterima: {envelope.event}")


async def handle_JournalRejectedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"JournalRejectedEvent diterima: {envelope.event}")


async def handle_JournalReversedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"JournalReversedEvent diterima: {envelope.event}")


async def handle_JournalSubmittedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"JournalSubmittedEvent diterima: {envelope.event}")


async def handle_JournalUnarchivedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"JournalUnarchivedEvent diterima: {envelope.event}")


async def handle_JournalVoidedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"JournalVoidedEvent diterima: {envelope.event}")


async def handle_LaborPostedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"LaborPostedEvent diterima: {envelope.event}")


async def handle_LegalEntityCreatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"LegalEntityCreatedEvent diterima: {envelope.event}")


async def handle_LegalEntityDeactivatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"LegalEntityDeactivatedEvent diterima: {envelope.event}")


async def handle_LegalEntityUpdatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"LegalEntityUpdatedEvent diterima: {envelope.event}")


async def handle_LoginFailureEvent(envelope: EventEnvelope) -> None:
    logger.info(f"LoginFailureEvent diterima: {envelope.event}")


async def handle_LoginSuccessEvent(envelope: EventEnvelope) -> None:
    logger.info(f"LoginSuccessEvent diterima: {envelope.event}")


async def handle_MaterialIssuedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"MaterialIssuedEvent diterima: {envelope.event}")


async def handle_MeteraiUsedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"MeteraiUsedEvent diterima: {envelope.event}")


async def handle_MilestoneBilledEvent(envelope: EventEnvelope) -> None:
    logger.info(f"MilestoneBilledEvent diterima: {envelope.event}")


async def handle_MilestoneReadyEvent(envelope: EventEnvelope) -> None:
    logger.info(f"MilestoneReadyEvent diterima: {envelope.event}")


async def handle_NCICalculatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"NCICalculatedEvent diterima: {envelope.event}")


async def handle_OverheadAppliedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"OverheadAppliedEvent diterima: {envelope.event}")


async def handle_PKPStatusChangedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PKPStatusChangedEvent diterima: {envelope.event}")


async def handle_PaymentAllocatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PaymentAllocatedEvent diterima: {envelope.event}")


async def handle_PaymentAppliedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PaymentAppliedEvent diterima: {envelope.event}")


async def handle_PaymentApprovedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PaymentApprovedEvent diterima: {envelope.event}")


async def handle_PaymentCancelledEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PaymentCancelledEvent diterima: {envelope.event}")


async def handle_PaymentConfirmedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PaymentConfirmedEvent diterima: {envelope.event}")


async def handle_PaymentMadeEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PaymentMadeEvent diterima: {envelope.event}")


async def handle_PaymentProcessedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PaymentProcessedEvent diterima: {envelope.event}")


async def handle_PaymentReceivedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PaymentReceivedEvent diterima: {envelope.event}")


async def handle_PaymentRunExecutedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PaymentRunExecutedEvent diterima: {envelope.event}")


async def handle_PaymentRunGeneratedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PaymentRunGeneratedEvent diterima: {envelope.event}")


async def handle_PaymentSentEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PaymentSentEvent diterima: {envelope.event}")


async def handle_PaymentVoidedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PaymentVoidedEvent diterima: {envelope.event}")


async def handle_PayrollRunApprovedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PayrollRunApprovedEvent diterima: {envelope.event}")


async def handle_PayrollRunCalculatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PayrollRunCalculatedEvent diterima: {envelope.event}")


async def handle_PayrollRunCancelledEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PayrollRunCancelledEvent diterima: {envelope.event}")


async def handle_PayrollRunCreatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PayrollRunCreatedEvent diterima: {envelope.event}")


async def handle_PayrollRunPaidEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PayrollRunPaidEvent diterima: {envelope.event}")


async def handle_PayrollRunPostedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PayrollRunPostedEvent diterima: {envelope.event}")


async def handle_PayslipGeneratedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PayslipGeneratedEvent diterima: {envelope.event}")


async def handle_PayslipSentToEmployeeEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PayslipSentToEmployeeEvent diterima: {envelope.event}")


async def handle_PeriodClosedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PeriodClosedEvent diterima: {envelope.event}")


async def handle_PeriodCreatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PeriodCreatedEvent diterima: {envelope.event}")


async def handle_PeriodLockedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PeriodLockedEvent diterima: {envelope.event}")


async def handle_PeriodOpenedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PeriodOpenedEvent diterima: {envelope.event}")


async def handle_PeriodReopenedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PeriodReopenedEvent diterima: {envelope.event}")


async def handle_PeriodStatusChangedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PeriodStatusChangedEvent diterima: {envelope.event}")


async def handle_PeriodUpdatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PeriodUpdatedEvent diterima: {envelope.event}")


async def handle_PermissionGrantedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PermissionGrantedEvent diterima: {envelope.event}")


async def handle_PermissionRevokedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PermissionRevokedEvent diterima: {envelope.event}")


async def handle_PettyCashActivatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PettyCashActivatedEvent diterima: {envelope.event}")


async def handle_PettyCashAdjustedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PettyCashAdjustedEvent diterima: {envelope.event}")


async def handle_PettyCashClosedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PettyCashClosedEvent diterima: {envelope.event}")


async def handle_PettyCashDisbursementEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PettyCashDisbursementEvent diterima: {envelope.event}")


async def handle_PettyCashFundCreatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PettyCashFundCreatedEvent diterima: {envelope.event}")


async def handle_PettyCashReplenishedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PettyCashReplenishedEvent diterima: {envelope.event}")


async def handle_PettyCashSuspendedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PettyCashSuspendedEvent diterima: {envelope.event}")


async def handle_ProductionCompletedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"ProductionCompletedEvent diterima: {envelope.event}")


async def handle_ProjectActivatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"ProjectActivatedEvent diterima: {envelope.event}")


async def handle_ProjectBillingGeneratedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"ProjectBillingGeneratedEvent diterima: {envelope.event}")


async def handle_ProjectCompletedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"ProjectCompletedEvent diterima: {envelope.event}")


async def handle_ProjectCreatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"ProjectCreatedEvent diterima: {envelope.event}")


async def handle_PurchaseInvoiceApprovedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PurchaseInvoiceApprovedEvent diterima: {envelope.event}")


async def handle_PurchaseInvoicePaidEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PurchaseInvoicePaidEvent diterima: {envelope.event}")


async def handle_PurchaseInvoiceReceivedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PurchaseInvoiceReceivedEvent diterima: {envelope.event}")


async def handle_PurchaseOrderApprovedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PurchaseOrderApprovedEvent diterima: {envelope.event}")


async def handle_PurchaseOrderCreatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"PurchaseOrderCreatedEvent diterima: {envelope.event}")


async def handle_RetainedEarningsAdjustedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"RetainedEarningsAdjustedEvent diterima: {envelope.event}")


async def handle_RetainedEarningsTransferEvent(envelope: EventEnvelope) -> None:
    logger.info(f"RetainedEarningsTransferEvent diterima: {envelope.event}")


async def handle_RetainedEarningsUpdatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"RetainedEarningsUpdatedEvent diterima: {envelope.event}")


async def handle_RetainerContractActivatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"RetainerContractActivatedEvent diterima: {envelope.event}")


async def handle_RevenueRecognizedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"RevenueRecognizedEvent diterima: {envelope.event}")


async def handle_RoleAssignedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"RoleAssignedEvent diterima: {envelope.event}")


async def handle_RoleCreatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"RoleCreatedEvent diterima: {envelope.event}")


async def handle_RoleDeletedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"RoleDeletedEvent diterima: {envelope.event}")


async def handle_RoleRevokedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"RoleRevokedEvent diterima: {envelope.event}")


async def handle_RoleUpdatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"RoleUpdatedEvent diterima: {envelope.event}")


async def handle_SPTApprovedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"SPTApprovedEvent diterima: {envelope.event}")


async def handle_SPTSubmittedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"SPTSubmittedEvent diterima: {envelope.event}")


async def handle_SalaryComponentAddedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"SalaryComponentAddedEvent diterima: {envelope.event}")


async def handle_SalesInvoiceIssuedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"SalesInvoiceIssuedEvent diterima: {envelope.event}")


async def handle_SalesInvoicePaidEvent(envelope: EventEnvelope) -> None:
    logger.info(f"SalesInvoicePaidEvent diterima: {envelope.event}")


async def handle_SalesOrderApprovedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"SalesOrderApprovedEvent diterima: {envelope.event}")


async def handle_SalesOrderCreatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"SalesOrderCreatedEvent diterima: {envelope.event}")


async def handle_SessionCompromisedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"SessionCompromisedEvent diterima: {envelope.event}")


async def handle_SessionCreatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"SessionCreatedEvent diterima: {envelope.event}")


async def handle_SessionRefreshedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"SessionRefreshedEvent diterima: {envelope.event}")


async def handle_SessionTerminatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"SessionTerminatedEvent diterima: {envelope.event}")


async def handle_SettingAddedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"SettingAddedEvent diterima: {envelope.event}")


async def handle_SettingChangedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"SettingChangedEvent diterima: {envelope.event}")


async def handle_SettingRemovedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"SettingRemovedEvent diterima: {envelope.event}")


async def handle_SettingResetEvent(envelope: EventEnvelope) -> None:
    logger.info(f"SettingResetEvent diterima: {envelope.event}")


async def handle_SettingsBulkUpdatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"SettingsBulkUpdatedEvent diterima: {envelope.event}")


async def handle_SettingsLockedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"SettingsLockedEvent diterima: {envelope.event}")


async def handle_SettingsUnlockedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"SettingsUnlockedEvent diterima: {envelope.event}")


async def handle_StandardCostActivatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"StandardCostActivatedEvent diterima: {envelope.event}")


async def handle_StandardCostCreatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"StandardCostCreatedEvent diterima: {envelope.event}")


async def handle_StockAdjustedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"StockAdjustedEvent diterima: {envelope.event}")


async def handle_StockLevelAlertEvent(envelope: EventEnvelope) -> None:
    logger.info(f"StockLevelAlertEvent diterima: {envelope.event}")


async def handle_StockMovementCreatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"StockMovementCreatedEvent diterima: {envelope.event}")


async def handle_StockOpnameApprovedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"StockOpnameApprovedEvent diterima: {envelope.event}")


async def handle_StockOpnameCreatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"StockOpnameCreatedEvent diterima: {envelope.event}")


async def handle_SupplierCreatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"SupplierCreatedEvent diterima: {envelope.event}")


async def handle_SupplierPaymentTermsChangedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"SupplierPaymentTermsChangedEvent diterima: {envelope.event}")


async def handle_SupplierWithholdingCategoryChangedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"SupplierWithholdingCategoryChangedEvent diterima: {envelope.event}")


async def handle_TaxCalculatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"TaxCalculatedEvent diterima: {envelope.event}")


async def handle_TaxProfileUpdatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"TaxProfileUpdatedEvent diterima: {envelope.event}")


async def handle_ThreeWayMatchResultEvent(envelope: EventEnvelope) -> None:
    logger.info(f"ThreeWayMatchResultEvent diterima: {envelope.event}")


async def handle_TimeEntryApprovedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"TimeEntryApprovedEvent diterima: {envelope.event}")


async def handle_TimeEntrySubmittedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"TimeEntrySubmittedEvent diterima: {envelope.event}")


async def handle_TransactionCreatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"TransactionCreatedEvent diterima: {envelope.event}")


async def handle_TransactionDeletedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"TransactionDeletedEvent diterima: {envelope.event}")


async def handle_TransactionRecordedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"TransactionRecordedEvent diterima: {envelope.event}")


async def handle_TransactionUpdatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"TransactionUpdatedEvent diterima: {envelope.event}")


async def handle_TransferCompletedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"TransferCompletedEvent diterima: {envelope.event}")


async def handle_UserActivatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"UserActivatedEvent diterima: {envelope.event}")


async def handle_UserCreatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"UserCreatedEvent diterima: {envelope.event}")


async def handle_UserDeactivatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"UserDeactivatedEvent diterima: {envelope.event}")


async def handle_UserDeletedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"UserDeletedEvent diterima: {envelope.event}")


async def handle_UserPasswordChangedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"UserPasswordChangedEvent diterima: {envelope.event}")


async def handle_UserSuspendedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"UserSuspendedEvent diterima: {envelope.event}")


async def handle_UserUnlockedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"UserUnlockedEvent diterima: {envelope.event}")


async def handle_UserUpdatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"UserUpdatedEvent diterima: {envelope.event}")


async def handle_VarianceAnalyzedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"VarianceAnalyzedEvent diterima: {envelope.event}")


async def handle_WorkOrderApprovedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"WorkOrderApprovedEvent diterima: {envelope.event}")


async def handle_WorkOrderCancelledEvent(envelope: EventEnvelope) -> None:
    logger.info(f"WorkOrderCancelledEvent diterima: {envelope.event}")


async def handle_WorkOrderCompletedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"WorkOrderCompletedEvent diterima: {envelope.event}")


async def handle_WorkOrderCreatedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"WorkOrderCreatedEvent diterima: {envelope.event}")


async def handle_WorkOrderStartedEvent(envelope: EventEnvelope) -> None:
    logger.info(f"WorkOrderStartedEvent diterima: {envelope.event}")


# ============================================================================
# REGISTRATION
# ============================================================================

def register_all_handlers(registry=None) -> int:
    """Daftarkan semua handler ke registry."""
    if registry is None:
        registry = event_handler_registry

    handlers = {
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
        "AuditEvent": handle_AuditEvent,
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
        "BankTransferExecutedEvent": handle_BankTransferExecutedEvent,
        "BankTransferFailedEvent": handle_BankTransferFailedEvent,
        "BankTransferInitiatedEvent": handle_BankTransferInitiatedEvent,
        "BudgetApprovedEvent": handle_BudgetApprovedEvent,
        "BudgetArchivedEvent": handle_BudgetArchivedEvent,
        "BudgetCancelledEvent": handle_BudgetCancelledEvent,
        "BudgetClosedEvent": handle_BudgetClosedEvent,
        "BudgetCreatedEvent": handle_BudgetCreatedEvent,
        "BudgetLineAddedEvent": handle_BudgetLineAddedEvent,
        "BudgetLineAdjustedEvent": handle_BudgetLineAdjustedEvent,
        "BudgetLineRemovedEvent": handle_BudgetLineRemovedEvent,
        "BudgetRejectedEvent": handle_BudgetRejectedEvent,
        "BudgetRevisedEvent": handle_BudgetRevisedEvent,
        "BudgetStatusChangedEvent": handle_BudgetStatusChangedEvent,
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
        "CashDisbursementIssuedEvent": handle_CashDisbursementIssuedEvent,
        "CashDisbursementPaidEvent": handle_CashDisbursementPaidEvent,
        "CashReceiptCancelledEvent": handle_CashReceiptCancelledEvent,
        "CashReceiptConfirmedEvent": handle_CashReceiptConfirmedEvent,
        "CashReceiptIssuedEvent": handle_CashReceiptIssuedEvent,
        "CompanyAddressUpdatedEvent": handle_CompanyAddressUpdatedEvent,
        "CompanyContactUpdatedEvent": handle_CompanyContactUpdatedEvent,
        "CompanyDissolvedEvent": handle_CompanyDissolvedEvent,
        "CompanyReactivatedEvent": handle_CompanyReactivatedEvent,
        "CompanyRegisteredEvent": handle_CompanyRegisteredEvent,
        "CompanySuspendedEvent": handle_CompanySuspendedEvent,
        "ConsolidationArchivedEvent": handle_ConsolidationArchivedEvent,
        "ConsolidationCancelledEvent": handle_ConsolidationCancelledEvent,
        "ConsolidationCompletedEvent": handle_ConsolidationCompletedEvent,
        "ConsolidationCreatedEvent": handle_ConsolidationCreatedEvent,
        "ConsolidationStartedEvent": handle_ConsolidationStartedEvent,
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
        "EconomicEvent": handle_EconomicEvent,
        "EliminationEntryCreatedEvent": handle_EliminationEntryCreatedEvent,
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
        "GoodwillUpdatedEvent": handle_GoodwillUpdatedEvent,
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
        "IntegrationEvent": handle_IntegrationEvent,
        "InterWarehouseTransferCreatedEvent": handle_InterWarehouseTransferCreatedEvent,
        "IntercompanyTransactionDetectedEvent": handle_IntercompanyTransactionDetectedEvent,
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
        "LegalEntityCreatedEvent": handle_LegalEntityCreatedEvent,
        "LegalEntityDeactivatedEvent": handle_LegalEntityDeactivatedEvent,
        "LegalEntityUpdatedEvent": handle_LegalEntityUpdatedEvent,
        "LoginFailureEvent": handle_LoginFailureEvent,
        "LoginSuccessEvent": handle_LoginSuccessEvent,
        "MaterialIssuedEvent": handle_MaterialIssuedEvent,
        "MeteraiUsedEvent": handle_MeteraiUsedEvent,
        "MilestoneBilledEvent": handle_MilestoneBilledEvent,
        "MilestoneReadyEvent": handle_MilestoneReadyEvent,
        "NCICalculatedEvent": handle_NCICalculatedEvent,
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
        "PettyCashFundCreatedEvent": handle_PettyCashFundCreatedEvent,
        "PettyCashReplenishedEvent": handle_PettyCashReplenishedEvent,
        "PettyCashSuspendedEvent": handle_PettyCashSuspendedEvent,
        "ProductionCompletedEvent": handle_ProductionCompletedEvent,
        "ProjectActivatedEvent": handle_ProjectActivatedEvent,
        "ProjectBillingGeneratedEvent": handle_ProjectBillingGeneratedEvent,
        "ProjectCompletedEvent": handle_ProjectCompletedEvent,
        "ProjectCreatedEvent": handle_ProjectCreatedEvent,
        "PurchaseInvoiceApprovedEvent": handle_PurchaseInvoiceApprovedEvent,
        "PurchaseInvoicePaidEvent": handle_PurchaseInvoicePaidEvent,
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
    }

    registered_count = 0
    for event_type, handler_func in handlers.items():
        try:
            registry.register_handler(event_type, handler_func, priority=HandlerPriority.NORMAL)
            registered_count += 1
        except HandlerAlreadyRegisteredError:
            logger.debug(f"Handler untuk {event_type} sudah terdaftar, dilewati.")
        except Exception as e:
            logger.error(f"Gagal mendaftarkan handler untuk {event_type}: {e}")

    return registered_count


# ============================================================================
# AUTO-REGISTER (saat modul diimpor)
# ============================================================================
try:
    count = register_all_handlers()
    logger.info(f"Registered {count} event handlers.")
except Exception as e:
    logger.warning(f"Auto-registration failed: {e}")

# ============================================================================
# END
# ============================================================================