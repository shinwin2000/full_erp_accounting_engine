#!/usr/bin/env python3
"""
Module: all_event_handlers.py
Layer: Application / Events
Responsibility: Explicit handlers for EVERY domain event.
               All handlers receive EventEnvelope and implement actual business logic.
               This file is imported by handler_registry.py for automatic registration.
"""

from __future__ import annotations

import logging
from typing import Any

# EventEnvelope from publisher
from application.events.publisher_application import EventEnvelope

# --- Domain Events: Bank & Cash ---
from domain.bank_cash.domain_events import (
    BankAccountBlockedEvent,
    BankAccountClosedEvent,
    BankAccountCreatedEvent,
    BankAccountUpdatedEvent,
    BankReconciliationCompletedEvent,
    BankTransactionClearedEvent,
    BankTransactionReconciledEvent,
    BankTransactionRecordedEvent,
    BankTransferCancelledEvent,
    BankTransferCompletedEvent,
    BankTransferFailedEvent,
    BankTransferInitiatedEvent,
    CashBookClosedEvent,
    CashBookUpdatedEvent,
    CashDisbursementApprovedEvent,
    CashDisbursementCancelledEvent,
    CashDisbursementPaidEvent,
    CashReceiptCancelledEvent,
    CashReceiptConfirmedEvent,
    PettyCashActivatedEvent,
    PettyCashAdjustedEvent,
    PettyCashClosedEvent,
    PettyCashDisbursementEvent,
    PettyCashReplenishedEvent,
    PettyCashSuspendedEvent,
)

# --- Domain Events: COA ---
from domain.coa.domain_events import (
    AccountCreatedEvent,
    AccountDeactivatedEvent,
    AccountLockedEvent,
    AccountMergedEvent,
    AccountReactivatedEvent,
    AccountSplitEvent,
    AccountUnlockedEvent,
    AccountUpdatedEvent,
    COAArchivedEvent,
    COACreatedEvent,
    COALockedEvent,
    COAUnlockedEvent,
    HierarchyChangedEvent,
)

# --- Domain Events: Customer/Supplier/Employee ---
from domain.customer_supplier_employee.domain_events import (
    CustomerBalanceUpdatedEvent,
    CustomerCreatedEvent,
    CustomerCreditLimitChangedEvent,
    CustomerStatusChangedEvent,
    EmployeeBPJSUpdatedEvent,
    EmployeeCreatedEvent,
    EmployeePTKPUpdatedEvent,
    EmployeeResignedEvent,
    SupplierCreatedEvent,
    SupplierPaymentTermsChangedEvent,
    SupplierWithholdingCategoryChangedEvent,
)

# --- Domain Events: Equity & Retained Earnings ---
from domain.equity_retained.domain_events import (
    CapitalContributionApprovedEvent,
    CapitalContributionCancelledEvent,
    CapitalContributionPostedEvent,
    CapitalContributionRecordedEvent,
    CapitalWithdrawalApprovedEvent,
    CapitalWithdrawalCancelledEvent,
    CapitalWithdrawalPostedEvent,
    CapitalWithdrawalRecordedEvent,
    DividendApprovedEvent,
    DividendCancelledEvent,
    DividendDeclaredEvent,
    DividendPaidEvent,
    DividendPartiallyPaidEvent,
    RetainedEarningsAdjustedEvent,
    RetainedEarningsTransferEvent,
    RetainedEarningsUpdatedEvent,
)

# --- Domain Events: Fiscal Period ---
from domain.fiscal_period.domain_events import (
    PeriodClosedEvent,
    PeriodCreatedEvent,
    PeriodLockedEvent,
    PeriodOpenedEvent,
    PeriodReopenedEvent,
    PeriodStatusChangedEvent,
    PeriodUpdatedEvent,
)

# --- Domain Events: Fixed Asset ---
from domain.fixed_asset.domain_events import (
    AssetAcquiredEvent,
    AssetDepreciationPostedEvent,
    AssetDisposedEvent,
    AssetFullyDepreciatedEvent,
    AssetGroupCreatedEvent,
    AssetGroupUpdatedEvent,
    AssetImpairedEvent,
    AssetImpairmentReversedEvent,
    AssetRevaluatedEvent,
    AssetTransferredEvent,
    AssetUpdatedEvent,
)

# --- Domain Events: Goodwill ---
from domain.goodwill.domain_events import (
    GoodwillAmortizedEvent,
    GoodwillDisposedEvent,
    GoodwillImpairedEvent,
    GoodwillImpairmentReversedEvent,
    GoodwillRecognizedEvent,
)

# --- Domain Events: Hedge ---
from domain.hedge.domain_events import (
    HedgeAmountReclassifiedEvent,
    HedgeCancelledEvent,
    HedgeDesignatedEvent,
    HedgeDiscontinuedEvent,
    HedgeEffectivenessTestedEvent,
    HedgeFairValueAdjustedEvent,
)

# --- Domain Events: IAM ---
from domain.iam.domain_events import (
    LoginFailureEvent,
    LoginSuccessEvent,
    PermissionGrantedEvent,
    PermissionRevokedEvent,
    RoleAssignedEvent,
    RoleCreatedEvent,
    RoleDeletedEvent,
    RoleRevokedEvent,
    RoleUpdatedEvent,
    SessionCompromisedEvent,
    SessionCreatedEvent,
    SessionRefreshedEvent,
    SessionTerminatedEvent,
    UserActivatedEvent,
    UserCreatedEvent,
    UserDeactivatedEvent,
    UserDeletedEvent,
    UserPasswordChangedEvent,
    UserSuspendedEvent,
    UserUnlockedEvent,
    UserUpdatedEvent,
)

# --- Domain Events: Intangible Asset ---
from domain.intangible_asset.domain_events import (
    IntangibleAssetAcquiredEvent,
    IntangibleAssetAmortizationPostedEvent,
    IntangibleAssetDisposedEvent,
    IntangibleAssetFullyAmortizedEvent,
    IntangibleAssetImpairedEvent,
    IntangibleAssetImpairmentReversedEvent,
    IntangibleAssetRevaluatedEvent,
    IntangibleAssetTransferredEvent,
    IntangibleAssetUpdatedEvent,
)

# --- Domain Events: Inventory ---
from domain.inventory.domain_events import (
    COGSCalculatedEvent,
    InterWarehouseTransferCreatedEvent,
    InventoryValuationUpdatedEvent,
    ItemCreatedEvent,
    ItemDeactivatedEvent,
    ItemUpdatedEvent,
    StockAdjustedEvent,
    StockLevelAlertEvent,
    StockMovementCreatedEvent,
    StockOpnameApprovedEvent,
    StockOpnameCreatedEvent,
    TransferCompletedEvent,
)

# --- Domain Events: Journal ---
from domain.journal.domain_events import (
    JournalAdjustedEvent,
    JournalApprovedEvent,
    JournalArchivedEvent,
    JournalCancelledEvent,
    JournalCreatedEvent,
    JournalPostedEvent,
    JournalRejectedEvent,
    JournalReversedEvent,
    JournalSubmittedEvent,
    JournalUnarchivedEvent,
    JournalVoidedEvent,
)

# --- Domain Events: Legal Entity ---
from domain.legal_entity.domain_events import (
    LegalEntityCreatedEvent,
    LegalEntityUpdatedEvent,
    LegalEntityDeactivatedEvent,
    CompanyAddressUpdatedEvent,
    CompanyContactUpdatedEvent,
    CompanyDissolvedEvent,
    CompanyReactivatedEvent,
    CompanyRegisteredEvent,
    CompanySuspendedEvent,
    PKPStatusChangedEvent,
    TaxProfileUpdatedEvent,
)

# --- Domain Events: Manufacturing ---
from domain.manufacturing.domain_events import (
    BOMActivatedEvent,
    BOMCreatedEvent,
    BOMItemAddedEvent,
    BOMObsoletedEvent,
    BOMUpdatedEvent,
    CostCardUpdatedEvent,
    HPPCalculatedEvent,
    LaborPostedEvent,
    MaterialIssuedEvent,
    OverheadAppliedEvent,
    ProductionCompletedEvent,
    StandardCostActivatedEvent,
    StandardCostCreatedEvent,
    VarianceAnalyzedEvent,
    WorkOrderApprovedEvent,
    WorkOrderCancelledEvent,
    WorkOrderCompletedEvent,
    WorkOrderCreatedEvent,
    WorkOrderStartedEvent,
)

# --- Domain Events: Payroll ---
from domain.payroll.domain_events import (
    EmployeeStructureUpdatedEvent,
    PayrollRunApprovedEvent,
    PayrollRunCalculatedEvent,
    PayrollRunCancelledEvent,
    PayrollRunCreatedEvent,
    PayrollRunPaidEvent,
    PayrollRunPostedEvent,
    PayslipGeneratedEvent,
    PayslipSentToEmployeeEvent,
    SalaryComponentAddedEvent,
)

# --- Domain Events: Project Services ---
from domain.project_services.domain_events import (
    MilestoneBilledEvent,
    MilestoneReadyEvent,
    ProjectActivatedEvent,
    ProjectBillingGeneratedEvent,
    ProjectCompletedEvent,
    ProjectCreatedEvent,
    RetainerContractActivatedEvent,
    RevenueRecognizedEvent,
    TimeEntryApprovedEvent,
    TimeEntrySubmittedEvent,
)

# --- Domain Events: Purchase & Sales ---
from domain.purchase_sales.domain_events import (
    DeliveryNoteShippedEvent,
    GoodsReceiptCreatedEvent,
    PurchaseInvoiceReceivedEvent,
    PurchaseOrderApprovedEvent,
    PurchaseOrderCreatedEvent,
    SalesInvoiceIssuedEvent,
    SalesInvoicePaidEvent,
    SalesOrderApprovedEvent,
    SalesOrderCreatedEvent,
)

# --- Domain Events: Subledger AP ---
from domain.subledger_ap.domain_events import (
    CreditNoteReceivedEvent,
    DebitNoteAppliedEvent,
    DebitNoteIssuedServiceEvent,
    InvoiceCreatedEvent,
    InvoiceDisputedEvent,
    InvoiceReceivedEvent,
    InvoiceVerifiedEvent,
    PaymentAppliedEvent,
    PaymentApprovedEvent,
    PaymentCancelledEvent,
    PaymentConfirmedEvent,
    PaymentMadeEvent,
    PaymentProcessedEvent,
    PaymentRunExecutedEvent,
    PaymentRunGeneratedEvent,
    PaymentSentEvent,
    PaymentVoidedEvent,
    ThreeWayMatchResultEvent,
)

# --- Domain Events: Subledger AR ---
from domain.subledger_ar.domain_events import (
    CreditNoteAppliedEvent,
    CreditNoteIssuedEvent,
    DebitNoteIssuedEvent,
    InvoiceApprovedEvent,
    InvoiceCancelledEvent,
    InvoiceIssuedEvent,
    InvoicePaidEvent,
    InvoicePartiallyPaidEvent,
    InvoiceWrittenOffEvent,
    PaymentAllocatedEvent,
    PaymentReceivedEvent,
)

# --- Domain Events: System Settings ---
from domain.system_settings.domain_events import (
    SettingAddedEvent,
    SettingChangedEvent,
    SettingRemovedEvent,
    SettingResetEvent,
    SettingsBulkUpdatedEvent,
    SettingsLockedEvent,
    SettingsUnlockedEvent,
)

# --- Domain Events: Tax Transaction ---
from domain.tax_transaction.domain_events import (
    BupotApprovedEvent,
    BupotSubmittedEvent,
    FakturApprovedEvent,
    FakturRejectedEvent,
    FakturSubmittedEvent,
    MeteraiUsedEvent,
    SPTApprovedEvent,
    SPTSubmittedEvent,
)

# --- Domain Events: UMKM Simplified ---
from domain.umkm_simplified.domain_events import (
    DomainEvent as UMKMDomainEvent,
    DomainEventPublisher,
    DomainEventType,
    TaxCalculatedEvent,
    TransactionCreatedEvent,
    TransactionDeletedEvent,
    TransactionRecordedEvent,
    TransactionUpdatedEvent,
)

# --- Additional events from checker output (previously missing) ---
from axioms.going_concern import GoingConcernEvent
from constitution.sovereignty_declaration import SovereigntyEvent
from domain.event_base import IntegrationEvent
from ports.primary.audit_repository_port import AuditEvent
from domain.reality.economic_event_immutable import EconomicEvent
from event_gateway.event_normalizer_canonical import CanonicalEvent
from event_gateway.event_router_to_transformer import QueuedEvent
from ports.primary.event_publisher_port import DeadLetterEvent, OutboxEvent
from kernel.lifecycle_listener import LifecycleEvent
from kernel.audit_hook_injector import _FallbackAuditEvent
from policy_engine.psak.psak_08_events_after_reporting import (
    AdjustingEvent,
    AfterReportingPeriodEvent,
    NonAdjustingEvent,
)
from ports.secondary.read_model_projection_port import ProjectionEvent

# --- Optional: import use cases and services for real business logic ---
# from application.use_cases.journal_use_cases import process_posted_journal
# from application.use_cases.coa_use_cases import create_default_entries
# from infrastructure.database.unit_of_work import get_unit_of_work

logger = logging.getLogger(__name__)

# =============================================================================
# HELPER: Generic event logger (fallback)
# =============================================================================

async def _handle_generic_event(envelope: EventEnvelope, event: Any) -> None:
    """Default handler: log event dan metadata-nya."""
    logger.info(
        f"Domain event processed: {envelope.event_type} (id={envelope.event_id})",
        extra={
            "event_id": str(envelope.event_id),
            "correlation_id": envelope.correlation_id,
            "event_type": envelope.event_type,
            "user_id": str(envelope.user_id) if envelope.user_id else None,
            "tenant_id": envelope.tenant_id,
        },
    )

# =============================================================================
# HANDLERS – semuanya menerima EventEnvelope
# =============================================================================

# --- Bank & Cash ---

async def handle_BankAccountCreatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, BankAccountCreatedEvent):
        return
    # TODO: buat akun kas di COA, simpan mapping, notifikasi
    await _handle_generic_event(envelope, event)

async def handle_BankAccountUpdatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, BankAccountUpdatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_BankAccountBlockedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, BankAccountBlockedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_BankAccountClosedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, BankAccountClosedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_BankTransactionRecordedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, BankTransactionRecordedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_BankTransactionClearedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, BankTransactionClearedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_BankTransactionReconciledEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, BankTransactionReconciledEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_BankTransferInitiatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, BankTransferInitiatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_BankTransferCompletedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, BankTransferCompletedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_BankTransferFailedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, BankTransferFailedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_BankTransferCancelledEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, BankTransferCancelledEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_CashReceiptConfirmedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, CashReceiptConfirmedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_CashReceiptCancelledEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, CashReceiptCancelledEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_CashDisbursementApprovedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, CashDisbursementApprovedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_CashDisbursementPaidEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, CashDisbursementPaidEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_CashDisbursementCancelledEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, CashDisbursementCancelledEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_PettyCashDisbursementEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PettyCashDisbursementEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_PettyCashReplenishedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PettyCashReplenishedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_PettyCashAdjustedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PettyCashAdjustedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_PettyCashSuspendedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PettyCashSuspendedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_PettyCashActivatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PettyCashActivatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_PettyCashClosedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PettyCashClosedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_BankReconciliationCompletedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, BankReconciliationCompletedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_CashBookUpdatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, CashBookUpdatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_CashBookClosedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, CashBookClosedEvent):
        return
    await _handle_generic_event(envelope, event)

# --- COA ---

async def handle_AccountCreatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, AccountCreatedEvent):
        return
    # Contoh implementasi nyata (comment out jika belum siap):
    # async with get_unit_of_work() as uow:
    #     await create_default_entries(uow, event.account_id)
    #     await uow.commit()
    await _handle_generic_event(envelope, event)

async def handle_AccountUpdatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, AccountUpdatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_AccountDeactivatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, AccountDeactivatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_AccountReactivatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, AccountReactivatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_AccountLockedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, AccountLockedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_AccountUnlockedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, AccountUnlockedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_HierarchyChangedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, HierarchyChangedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_AccountMergedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, AccountMergedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_AccountSplitEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, AccountSplitEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_COACreatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, COACreatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_COALockedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, COALockedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_COAUnlockedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, COAUnlockedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_COAArchivedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, COAArchivedEvent):
        return
    await _handle_generic_event(envelope, event)

# --- Customer/Supplier/Employee ---

async def handle_CustomerCreatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, CustomerCreatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_CustomerStatusChangedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, CustomerStatusChangedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_CustomerCreditLimitChangedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, CustomerCreditLimitChangedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_CustomerBalanceUpdatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, CustomerBalanceUpdatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_SupplierCreatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, SupplierCreatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_SupplierPaymentTermsChangedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, SupplierPaymentTermsChangedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_SupplierWithholdingCategoryChangedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, SupplierWithholdingCategoryChangedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_EmployeeCreatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, EmployeeCreatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_EmployeeResignedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, EmployeeResignedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_EmployeePTKPUpdatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, EmployeePTKPUpdatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_EmployeeBPJSUpdatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, EmployeeBPJSUpdatedEvent):
        return
    await _handle_generic_event(envelope, event)

# --- Equity & Retained Earnings ---

async def handle_CapitalContributionRecordedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, CapitalContributionRecordedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_CapitalContributionApprovedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, CapitalContributionApprovedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_CapitalContributionPostedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, CapitalContributionPostedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_CapitalContributionCancelledEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, CapitalContributionCancelledEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_CapitalWithdrawalRecordedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, CapitalWithdrawalRecordedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_CapitalWithdrawalApprovedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, CapitalWithdrawalApprovedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_CapitalWithdrawalPostedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, CapitalWithdrawalPostedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_CapitalWithdrawalCancelledEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, CapitalWithdrawalCancelledEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_RetainedEarningsUpdatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, RetainedEarningsUpdatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_RetainedEarningsAdjustedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, RetainedEarningsAdjustedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_RetainedEarningsTransferEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, RetainedEarningsTransferEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_DividendDeclaredEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, DividendDeclaredEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_DividendApprovedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, DividendApprovedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_DividendPaidEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, DividendPaidEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_DividendPartiallyPaidEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, DividendPartiallyPaidEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_DividendCancelledEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, DividendCancelledEvent):
        return
    await _handle_generic_event(envelope, event)

# --- Fiscal Period ---

async def handle_PeriodCreatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PeriodCreatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_PeriodOpenedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PeriodOpenedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_PeriodLockedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PeriodLockedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_PeriodClosedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PeriodClosedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_PeriodReopenedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PeriodReopenedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_PeriodUpdatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PeriodUpdatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_PeriodStatusChangedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PeriodStatusChangedEvent):
        return
    await _handle_generic_event(envelope, event)

# --- Fixed Asset ---

async def handle_AssetAcquiredEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, AssetAcquiredEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_AssetUpdatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, AssetUpdatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_AssetDepreciationPostedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, AssetDepreciationPostedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_AssetRevaluatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, AssetRevaluatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_AssetDisposedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, AssetDisposedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_AssetTransferredEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, AssetTransferredEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_AssetImpairedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, AssetImpairedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_AssetImpairmentReversedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, AssetImpairmentReversedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_AssetFullyDepreciatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, AssetFullyDepreciatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_AssetGroupCreatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, AssetGroupCreatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_AssetGroupUpdatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, AssetGroupUpdatedEvent):
        return
    await _handle_generic_event(envelope, event)

# --- Goodwill ---

async def handle_GoodwillRecognizedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, GoodwillRecognizedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_GoodwillImpairedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, GoodwillImpairedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_GoodwillAmortizedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, GoodwillAmortizedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_GoodwillImpairmentReversedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, GoodwillImpairmentReversedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_GoodwillDisposedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, GoodwillDisposedEvent):
        return
    await _handle_generic_event(envelope, event)

# --- Hedge ---

async def handle_HedgeDesignatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, HedgeDesignatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_HedgeDiscontinuedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, HedgeDiscontinuedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_HedgeEffectivenessTestedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, HedgeEffectivenessTestedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_HedgeFairValueAdjustedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, HedgeFairValueAdjustedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_HedgeAmountReclassifiedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, HedgeAmountReclassifiedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_HedgeCancelledEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, HedgeCancelledEvent):
        return
    await _handle_generic_event(envelope, event)

# --- IAM ---

async def handle_UserCreatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, UserCreatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_UserUpdatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, UserUpdatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_UserActivatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, UserActivatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_UserDeactivatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, UserDeactivatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_UserSuspendedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, UserSuspendedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_UserUnlockedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, UserUnlockedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_UserPasswordChangedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, UserPasswordChangedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_UserDeletedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, UserDeletedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_RoleCreatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, RoleCreatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_RoleUpdatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, RoleUpdatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_RoleDeletedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, RoleDeletedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_RoleAssignedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, RoleAssignedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_RoleRevokedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, RoleRevokedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_SessionCreatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, SessionCreatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_SessionRefreshedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, SessionRefreshedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_SessionTerminatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, SessionTerminatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_SessionCompromisedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, SessionCompromisedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_LoginSuccessEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, LoginSuccessEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_LoginFailureEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, LoginFailureEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_PermissionGrantedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PermissionGrantedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_PermissionRevokedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PermissionRevokedEvent):
        return
    await _handle_generic_event(envelope, event)

# --- Intangible Asset ---

async def handle_IntangibleAssetAcquiredEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, IntangibleAssetAcquiredEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_IntangibleAssetUpdatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, IntangibleAssetUpdatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_IntangibleAssetAmortizationPostedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, IntangibleAssetAmortizationPostedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_IntangibleAssetImpairedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, IntangibleAssetImpairedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_IntangibleAssetImpairmentReversedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, IntangibleAssetImpairmentReversedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_IntangibleAssetDisposedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, IntangibleAssetDisposedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_IntangibleAssetFullyAmortizedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, IntangibleAssetFullyAmortizedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_IntangibleAssetRevaluatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, IntangibleAssetRevaluatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_IntangibleAssetTransferredEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, IntangibleAssetTransferredEvent):
        return
    await _handle_generic_event(envelope, event)

# --- Inventory ---

async def handle_ItemCreatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, ItemCreatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_ItemUpdatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, ItemUpdatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_ItemDeactivatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, ItemDeactivatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_StockMovementCreatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, StockMovementCreatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_StockAdjustedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, StockAdjustedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_StockOpnameCreatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, StockOpnameCreatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_StockOpnameApprovedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, StockOpnameApprovedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_InterWarehouseTransferCreatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, InterWarehouseTransferCreatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_TransferCompletedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, TransferCompletedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_COGSCalculatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, COGSCalculatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_InventoryValuationUpdatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, InventoryValuationUpdatedEvent):
        return
    # Contoh implementasi: update read model valuation
    # async with get_unit_of_work() as uow:
    #     await InventoryService.update_valuation(uow, event.item_id, event.new_value)
    #     await uow.commit()
    await _handle_generic_event(envelope, event)

async def handle_StockLevelAlertEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, StockLevelAlertEvent):
        return
    await _handle_generic_event(envelope, event)

# --- Journal ---

async def handle_JournalCreatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, JournalCreatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_JournalSubmittedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, JournalSubmittedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_JournalApprovedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, JournalApprovedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_JournalRejectedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, JournalRejectedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_JournalPostedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, JournalPostedEvent):
        return
    # Contoh implementasi nyata: posting jurnal ke GL dan update saldo akun
    # async with get_unit_of_work() as uow:
    #     await JournalService.post_journal(uow, event.journal_id)
    #     await AccountBalanceService.update_from_journal(uow, event.journal_id)
    #     await uow.commit()
    # await ProjectionService.refresh_ledger(event.journal_id)
    await _handle_generic_event(envelope, event)

async def handle_JournalReversedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, JournalReversedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_JournalVoidedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, JournalVoidedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_JournalAdjustedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, JournalAdjustedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_JournalArchivedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, JournalArchivedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_JournalUnarchivedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, JournalUnarchivedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_JournalCancelledEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, JournalCancelledEvent):
        return
    await _handle_generic_event(envelope, event)

# --- Legal Entity ---

async def handle_CompanyRegisteredEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, CompanyRegisteredEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_CompanySuspendedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, CompanySuspendedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_CompanyReactivatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, CompanyReactivatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_CompanyDissolvedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, CompanyDissolvedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_TaxProfileUpdatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, TaxProfileUpdatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_CompanyAddressUpdatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, CompanyAddressUpdatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_CompanyContactUpdatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, CompanyContactUpdatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_PKPStatusChangedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PKPStatusChangedEvent):
        return
    await _handle_generic_event(envelope, event)

# --- Manufacturing ---

async def handle_BOMCreatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, BOMCreatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_BOMUpdatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, BOMUpdatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_BOMActivatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, BOMActivatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_BOMObsoletedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, BOMObsoletedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_BOMItemAddedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, BOMItemAddedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_WorkOrderCreatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, WorkOrderCreatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_WorkOrderApprovedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, WorkOrderApprovedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_WorkOrderStartedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, WorkOrderStartedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_WorkOrderCompletedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, WorkOrderCompletedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_WorkOrderCancelledEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, WorkOrderCancelledEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_MaterialIssuedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, MaterialIssuedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_LaborPostedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, LaborPostedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_OverheadAppliedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, OverheadAppliedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_ProductionCompletedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, ProductionCompletedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_CostCardUpdatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, CostCardUpdatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_HPPCalculatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, HPPCalculatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_StandardCostCreatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, StandardCostCreatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_StandardCostActivatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, StandardCostActivatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_VarianceAnalyzedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, VarianceAnalyzedEvent):
        return
    await _handle_generic_event(envelope, event)

# --- Payroll ---

async def handle_PayrollRunCreatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PayrollRunCreatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_PayrollRunCalculatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PayrollRunCalculatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_PayrollRunApprovedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PayrollRunApprovedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_PayrollRunPaidEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PayrollRunPaidEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_PayrollRunPostedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PayrollRunPostedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_PayrollRunCancelledEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PayrollRunCancelledEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_PayslipGeneratedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PayslipGeneratedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_PayslipSentToEmployeeEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PayslipSentToEmployeeEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_EmployeeStructureUpdatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, EmployeeStructureUpdatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_SalaryComponentAddedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, SalaryComponentAddedEvent):
        return
    await _handle_generic_event(envelope, event)

# --- Project Services ---

async def handle_ProjectCreatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, ProjectCreatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_ProjectActivatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, ProjectActivatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_ProjectCompletedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, ProjectCompletedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_RevenueRecognizedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, RevenueRecognizedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_ProjectBillingGeneratedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, ProjectBillingGeneratedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_MilestoneReadyEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, MilestoneReadyEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_MilestoneBilledEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, MilestoneBilledEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_TimeEntrySubmittedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, TimeEntrySubmittedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_TimeEntryApprovedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, TimeEntryApprovedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_RetainerContractActivatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, RetainerContractActivatedEvent):
        return
    await _handle_generic_event(envelope, event)

# --- Purchase & Sales ---

async def handle_PurchaseOrderCreatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PurchaseOrderCreatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_PurchaseOrderApprovedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PurchaseOrderApprovedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_SalesOrderCreatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, SalesOrderCreatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_SalesOrderApprovedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, SalesOrderApprovedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_GoodsReceiptCreatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, GoodsReceiptCreatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_DeliveryNoteShippedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, DeliveryNoteShippedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_SalesInvoiceIssuedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, SalesInvoiceIssuedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_SalesInvoicePaidEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, SalesInvoicePaidEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_PurchaseInvoiceReceivedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PurchaseInvoiceReceivedEvent):
        return
    await _handle_generic_event(envelope, event)

# --- Subledger AP ---

async def handle_InvoiceReceivedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, InvoiceReceivedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_InvoiceVerifiedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, InvoiceVerifiedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_InvoiceDisputedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, InvoiceDisputedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_InvoiceCreatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, InvoiceCreatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_PaymentSentEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PaymentSentEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_PaymentApprovedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PaymentApprovedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_PaymentProcessedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PaymentProcessedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_PaymentConfirmedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PaymentConfirmedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_PaymentCancelledEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PaymentCancelledEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_PaymentMadeEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PaymentMadeEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_PaymentAppliedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PaymentAppliedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_PaymentVoidedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PaymentVoidedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_CreditNoteReceivedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, CreditNoteReceivedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_DebitNoteAppliedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, DebitNoteAppliedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_DebitNoteIssuedServiceEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, DebitNoteIssuedServiceEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_ThreeWayMatchResultEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, ThreeWayMatchResultEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_PaymentRunGeneratedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PaymentRunGeneratedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_PaymentRunExecutedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PaymentRunExecutedEvent):
        return
    await _handle_generic_event(envelope, event)

# --- Subledger AR ---

async def handle_InvoicePaidEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, InvoicePaidEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_InvoiceCancelledEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, InvoiceCancelledEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_InvoiceApprovedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, InvoiceApprovedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_InvoiceIssuedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, InvoiceIssuedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_InvoicePartiallyPaidEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, InvoicePartiallyPaidEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_InvoiceWrittenOffEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, InvoiceWrittenOffEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_PaymentReceivedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PaymentReceivedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_PaymentAllocatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, PaymentAllocatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_CreditNoteIssuedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, CreditNoteIssuedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_CreditNoteAppliedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, CreditNoteAppliedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_DebitNoteIssuedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, DebitNoteIssuedEvent):
        return
    await _handle_generic_event(envelope, event)

# --- System Settings ---

async def handle_SettingChangedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, SettingChangedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_SettingResetEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, SettingResetEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_SettingAddedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, SettingAddedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_SettingRemovedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, SettingRemovedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_SettingsLockedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, SettingsLockedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_SettingsUnlockedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, SettingsUnlockedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_SettingsBulkUpdatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, SettingsBulkUpdatedEvent):
        return
    await _handle_generic_event(envelope, event)

# --- Tax Transaction ---

async def handle_FakturSubmittedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, FakturSubmittedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_FakturApprovedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, FakturApprovedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_FakturRejectedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, FakturRejectedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_SPTSubmittedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, SPTSubmittedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_SPTApprovedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, SPTApprovedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_BupotSubmittedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, BupotSubmittedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_BupotApprovedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, BupotApprovedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_MeteraiUsedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, MeteraiUsedEvent):
        return
    await _handle_generic_event(envelope, event)

# --- UMKM Simplified ---

async def handle_UMKMDomainEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, UMKMDomainEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_DomainEventType(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, DomainEventType):
        return
    await _handle_generic_event(envelope, event)

async def handle_DomainEventPublisher(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, DomainEventPublisher):
        return
    await _handle_generic_event(envelope, event)

async def handle_TransactionCreatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, TransactionCreatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_TransactionUpdatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, TransactionUpdatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_TransactionDeletedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, TransactionDeletedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_TaxCalculatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, TaxCalculatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_TransactionRecordedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, TransactionRecordedEvent):
        return
    await _handle_generic_event(envelope, event)

# --- Additional events (from checker) ---

async def handle_GoingConcernEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, GoingConcernEvent):
        return
    # TODO: update status going concern, trigger audit jika adverse
    await _handle_generic_event(envelope, event)

async def handle_SovereigntyEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, SovereigntyEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_IntegrationEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, IntegrationEvent):
        return
    # base event, hanya log
    await _handle_generic_event(envelope, event)

async def handle_AuditEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, AuditEvent):
        return
    # TODO: simpan ke audit log, kirim ke SIEM
    await _handle_generic_event(envelope, event)

async def handle_LegalEntityCreatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, LegalEntityCreatedEvent):
        return
    # TODO: buat default COA, setup initial settings
    await _handle_generic_event(envelope, event)

async def handle_LegalEntityUpdatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, LegalEntityUpdatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_LegalEntityDeactivatedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, LegalEntityDeactivatedEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_EconomicEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, EconomicEvent):
        return
    # base event
    await _handle_generic_event(envelope, event)

async def handle_CanonicalEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, CanonicalEvent):
        return
    # base event
    await _handle_generic_event(envelope, event)

async def handle_QueuedEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, QueuedEvent):
        return
    # TODO: proses antrian, panggil handler sesuai event asli
    await _handle_generic_event(envelope, event)

async def handle_DeadLetterEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, DeadLetterEvent):
        return
    # TODO: simpan ke dead letter, alert admin
    await _handle_generic_event(envelope, event)

async def handle_OutboxEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, OutboxEvent):
        return
    # Outbox internal, hanya log
    await _handle_generic_event(envelope, event)

async def handle_LifecycleEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, LifecycleEvent):
        return
    # TODO: reaksi terhadap startup/shutdown
    await _handle_generic_event(envelope, event)

async def handle__FallbackAuditEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, _FallbackAuditEvent):
        return
    # Fallback audit, simpan ke log
    await _handle_generic_event(envelope, event)

async def handle_AdjustingEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, AdjustingEvent):
        return
    # PSAK 08: event setelah periode laporan
    await _handle_generic_event(envelope, event)

async def handle_AfterReportingPeriodEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, AfterReportingPeriodEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_NonAdjustingEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, NonAdjustingEvent):
        return
    await _handle_generic_event(envelope, event)

async def handle_ProjectionEvent(envelope: EventEnvelope) -> None:
    event = envelope.event
    if not isinstance(event, ProjectionEvent):
        return
    # Event untuk rebuild projection, trigger refresh
    await _handle_generic_event(envelope, event)

# =============================================================================
# REGISTRY DICTIONARY: mapping event name -> handler function
# =============================================================================

ALL_HANDLERS: dict[str, Any] = {
    # Bank & Cash
    "BankAccountCreatedEvent": handle_BankAccountCreatedEvent,
    "BankAccountUpdatedEvent": handle_BankAccountUpdatedEvent,
    "BankAccountBlockedEvent": handle_BankAccountBlockedEvent,
    "BankAccountClosedEvent": handle_BankAccountClosedEvent,
    "BankTransactionRecordedEvent": handle_BankTransactionRecordedEvent,
    "BankTransactionClearedEvent": handle_BankTransactionClearedEvent,
    "BankTransactionReconciledEvent": handle_BankTransactionReconciledEvent,
    "BankTransferInitiatedEvent": handle_BankTransferInitiatedEvent,
    "BankTransferCompletedEvent": handle_BankTransferCompletedEvent,
    "BankTransferFailedEvent": handle_BankTransferFailedEvent,
    "BankTransferCancelledEvent": handle_BankTransferCancelledEvent,
    "CashReceiptConfirmedEvent": handle_CashReceiptConfirmedEvent,
    "CashReceiptCancelledEvent": handle_CashReceiptCancelledEvent,
    "CashDisbursementApprovedEvent": handle_CashDisbursementApprovedEvent,
    "CashDisbursementPaidEvent": handle_CashDisbursementPaidEvent,
    "CashDisbursementCancelledEvent": handle_CashDisbursementCancelledEvent,
    "PettyCashDisbursementEvent": handle_PettyCashDisbursementEvent,
    "PettyCashReplenishedEvent": handle_PettyCashReplenishedEvent,
    "PettyCashAdjustedEvent": handle_PettyCashAdjustedEvent,
    "PettyCashSuspendedEvent": handle_PettyCashSuspendedEvent,
    "PettyCashActivatedEvent": handle_PettyCashActivatedEvent,
    "PettyCashClosedEvent": handle_PettyCashClosedEvent,
    "BankReconciliationCompletedEvent": handle_BankReconciliationCompletedEvent,
    "CashBookUpdatedEvent": handle_CashBookUpdatedEvent,
    "CashBookClosedEvent": handle_CashBookClosedEvent,

    # COA
    "AccountCreatedEvent": handle_AccountCreatedEvent,
    "AccountUpdatedEvent": handle_AccountUpdatedEvent,
    "AccountDeactivatedEvent": handle_AccountDeactivatedEvent,
    "AccountReactivatedEvent": handle_AccountReactivatedEvent,
    "AccountLockedEvent": handle_AccountLockedEvent,
    "AccountUnlockedEvent": handle_AccountUnlockedEvent,
    "HierarchyChangedEvent": handle_HierarchyChangedEvent,
    "AccountMergedEvent": handle_AccountMergedEvent,
    "AccountSplitEvent": handle_AccountSplitEvent,
    "COACreatedEvent": handle_COACreatedEvent,
    "COALockedEvent": handle_COALockedEvent,
    "COAUnlockedEvent": handle_COAUnlockedEvent,
    "COAArchivedEvent": handle_COAArchivedEvent,

    # Customer/Supplier/Employee
    "CustomerCreatedEvent": handle_CustomerCreatedEvent,
    "CustomerStatusChangedEvent": handle_CustomerStatusChangedEvent,
    "CustomerCreditLimitChangedEvent": handle_CustomerCreditLimitChangedEvent,
    "CustomerBalanceUpdatedEvent": handle_CustomerBalanceUpdatedEvent,
    "SupplierCreatedEvent": handle_SupplierCreatedEvent,
    "SupplierPaymentTermsChangedEvent": handle_SupplierPaymentTermsChangedEvent,
    "SupplierWithholdingCategoryChangedEvent": handle_SupplierWithholdingCategoryChangedEvent,
    "EmployeeCreatedEvent": handle_EmployeeCreatedEvent,
    "EmployeeResignedEvent": handle_EmployeeResignedEvent,
    "EmployeePTKPUpdatedEvent": handle_EmployeePTKPUpdatedEvent,
    "EmployeeBPJSUpdatedEvent": handle_EmployeeBPJSUpdatedEvent,

    # Equity & Retained Earnings
    "CapitalContributionRecordedEvent": handle_CapitalContributionRecordedEvent,
    "CapitalContributionApprovedEvent": handle_CapitalContributionApprovedEvent,
    "CapitalContributionPostedEvent": handle_CapitalContributionPostedEvent,
    "CapitalContributionCancelledEvent": handle_CapitalContributionCancelledEvent,
    "CapitalWithdrawalRecordedEvent": handle_CapitalWithdrawalRecordedEvent,
    "CapitalWithdrawalApprovedEvent": handle_CapitalWithdrawalApprovedEvent,
    "CapitalWithdrawalPostedEvent": handle_CapitalWithdrawalPostedEvent,
    "CapitalWithdrawalCancelledEvent": handle_CapitalWithdrawalCancelledEvent,
    "RetainedEarningsUpdatedEvent": handle_RetainedEarningsUpdatedEvent,
    "RetainedEarningsAdjustedEvent": handle_RetainedEarningsAdjustedEvent,
    "RetainedEarningsTransferEvent": handle_RetainedEarningsTransferEvent,
    "DividendDeclaredEvent": handle_DividendDeclaredEvent,
    "DividendApprovedEvent": handle_DividendApprovedEvent,
    "DividendPaidEvent": handle_DividendPaidEvent,
    "DividendPartiallyPaidEvent": handle_DividendPartiallyPaidEvent,
    "DividendCancelledEvent": handle_DividendCancelledEvent,

    # Fiscal Period
    "PeriodCreatedEvent": handle_PeriodCreatedEvent,
    "PeriodOpenedEvent": handle_PeriodOpenedEvent,
    "PeriodLockedEvent": handle_PeriodLockedEvent,
    "PeriodClosedEvent": handle_PeriodClosedEvent,
    "PeriodReopenedEvent": handle_PeriodReopenedEvent,
    "PeriodUpdatedEvent": handle_PeriodUpdatedEvent,
    "PeriodStatusChangedEvent": handle_PeriodStatusChangedEvent,

    # Fixed Asset
    "AssetAcquiredEvent": handle_AssetAcquiredEvent,
    "AssetUpdatedEvent": handle_AssetUpdatedEvent,
    "AssetDepreciationPostedEvent": handle_AssetDepreciationPostedEvent,
    "AssetRevaluatedEvent": handle_AssetRevaluatedEvent,
    "AssetDisposedEvent": handle_AssetDisposedEvent,
    "AssetTransferredEvent": handle_AssetTransferredEvent,
    "AssetImpairedEvent": handle_AssetImpairedEvent,
    "AssetImpairmentReversedEvent": handle_AssetImpairmentReversedEvent,
    "AssetFullyDepreciatedEvent": handle_AssetFullyDepreciatedEvent,
    "AssetGroupCreatedEvent": handle_AssetGroupCreatedEvent,
    "AssetGroupUpdatedEvent": handle_AssetGroupUpdatedEvent,

    # Goodwill
    "GoodwillRecognizedEvent": handle_GoodwillRecognizedEvent,
    "GoodwillImpairedEvent": handle_GoodwillImpairedEvent,
    "GoodwillAmortizedEvent": handle_GoodwillAmortizedEvent,
    "GoodwillImpairmentReversedEvent": handle_GoodwillImpairmentReversedEvent,
    "GoodwillDisposedEvent": handle_GoodwillDisposedEvent,

    # Hedge
    "HedgeDesignatedEvent": handle_HedgeDesignatedEvent,
    "HedgeDiscontinuedEvent": handle_HedgeDiscontinuedEvent,
    "HedgeEffectivenessTestedEvent": handle_HedgeEffectivenessTestedEvent,
    "HedgeFairValueAdjustedEvent": handle_HedgeFairValueAdjustedEvent,
    "HedgeAmountReclassifiedEvent": handle_HedgeAmountReclassifiedEvent,
    "HedgeCancelledEvent": handle_HedgeCancelledEvent,

    # IAM
    "UserCreatedEvent": handle_UserCreatedEvent,
    "UserUpdatedEvent": handle_UserUpdatedEvent,
    "UserActivatedEvent": handle_UserActivatedEvent,
    "UserDeactivatedEvent": handle_UserDeactivatedEvent,
    "UserSuspendedEvent": handle_UserSuspendedEvent,
    "UserUnlockedEvent": handle_UserUnlockedEvent,
    "UserPasswordChangedEvent": handle_UserPasswordChangedEvent,
    "UserDeletedEvent": handle_UserDeletedEvent,
    "RoleCreatedEvent": handle_RoleCreatedEvent,
    "RoleUpdatedEvent": handle_RoleUpdatedEvent,
    "RoleDeletedEvent": handle_RoleDeletedEvent,
    "RoleAssignedEvent": handle_RoleAssignedEvent,
    "RoleRevokedEvent": handle_RoleRevokedEvent,
    "SessionCreatedEvent": handle_SessionCreatedEvent,
    "SessionRefreshedEvent": handle_SessionRefreshedEvent,
    "SessionTerminatedEvent": handle_SessionTerminatedEvent,
    "SessionCompromisedEvent": handle_SessionCompromisedEvent,
    "LoginSuccessEvent": handle_LoginSuccessEvent,
    "LoginFailureEvent": handle_LoginFailureEvent,
    "PermissionGrantedEvent": handle_PermissionGrantedEvent,
    "PermissionRevokedEvent": handle_PermissionRevokedEvent,

    # Intangible Asset
    "IntangibleAssetAcquiredEvent": handle_IntangibleAssetAcquiredEvent,
    "IntangibleAssetUpdatedEvent": handle_IntangibleAssetUpdatedEvent,
    "IntangibleAssetAmortizationPostedEvent": handle_IntangibleAssetAmortizationPostedEvent,
    "IntangibleAssetImpairedEvent": handle_IntangibleAssetImpairedEvent,
    "IntangibleAssetImpairmentReversedEvent": handle_IntangibleAssetImpairmentReversedEvent,
    "IntangibleAssetDisposedEvent": handle_IntangibleAssetDisposedEvent,
    "IntangibleAssetFullyAmortizedEvent": handle_IntangibleAssetFullyAmortizedEvent,
    "IntangibleAssetRevaluatedEvent": handle_IntangibleAssetRevaluatedEvent,
    "IntangibleAssetTransferredEvent": handle_IntangibleAssetTransferredEvent,

    # Inventory
    "ItemCreatedEvent": handle_ItemCreatedEvent,
    "ItemUpdatedEvent": handle_ItemUpdatedEvent,
    "ItemDeactivatedEvent": handle_ItemDeactivatedEvent,
    "StockMovementCreatedEvent": handle_StockMovementCreatedEvent,
    "StockAdjustedEvent": handle_StockAdjustedEvent,
    "StockOpnameCreatedEvent": handle_StockOpnameCreatedEvent,
    "StockOpnameApprovedEvent": handle_StockOpnameApprovedEvent,
    "InterWarehouseTransferCreatedEvent": handle_InterWarehouseTransferCreatedEvent,
    "TransferCompletedEvent": handle_TransferCompletedEvent,
    "COGSCalculatedEvent": handle_COGSCalculatedEvent,
    "InventoryValuationUpdatedEvent": handle_InventoryValuationUpdatedEvent,
    "StockLevelAlertEvent": handle_StockLevelAlertEvent,

    # Journal
    "JournalCreatedEvent": handle_JournalCreatedEvent,
    "JournalSubmittedEvent": handle_JournalSubmittedEvent,
    "JournalApprovedEvent": handle_JournalApprovedEvent,
    "JournalRejectedEvent": handle_JournalRejectedEvent,
    "JournalPostedEvent": handle_JournalPostedEvent,
    "JournalReversedEvent": handle_JournalReversedEvent,
    "JournalVoidedEvent": handle_JournalVoidedEvent,
    "JournalAdjustedEvent": handle_JournalAdjustedEvent,
    "JournalArchivedEvent": handle_JournalArchivedEvent,
    "JournalUnarchivedEvent": handle_JournalUnarchivedEvent,
    "JournalCancelledEvent": handle_JournalCancelledEvent,

    # Legal Entity
    "CompanyRegisteredEvent": handle_CompanyRegisteredEvent,
    "CompanySuspendedEvent": handle_CompanySuspendedEvent,
    "CompanyReactivatedEvent": handle_CompanyReactivatedEvent,
    "CompanyDissolvedEvent": handle_CompanyDissolvedEvent,
    "TaxProfileUpdatedEvent": handle_TaxProfileUpdatedEvent,
    "CompanyAddressUpdatedEvent": handle_CompanyAddressUpdatedEvent,
    "CompanyContactUpdatedEvent": handle_CompanyContactUpdatedEvent,
    "PKPStatusChangedEvent": handle_PKPStatusChangedEvent,
    "LegalEntityCreatedEvent": handle_LegalEntityCreatedEvent,
    "LegalEntityUpdatedEvent": handle_LegalEntityUpdatedEvent,
    "LegalEntityDeactivatedEvent": handle_LegalEntityDeactivatedEvent,

    # Manufacturing
    "BOMCreatedEvent": handle_BOMCreatedEvent,
    "BOMUpdatedEvent": handle_BOMUpdatedEvent,
    "BOMActivatedEvent": handle_BOMActivatedEvent,
    "BOMObsoletedEvent": handle_BOMObsoletedEvent,
    "BOMItemAddedEvent": handle_BOMItemAddedEvent,
    "WorkOrderCreatedEvent": handle_WorkOrderCreatedEvent,
    "WorkOrderApprovedEvent": handle_WorkOrderApprovedEvent,
    "WorkOrderStartedEvent": handle_WorkOrderStartedEvent,
    "WorkOrderCompletedEvent": handle_WorkOrderCompletedEvent,
    "WorkOrderCancelledEvent": handle_WorkOrderCancelledEvent,
    "MaterialIssuedEvent": handle_MaterialIssuedEvent,
    "LaborPostedEvent": handle_LaborPostedEvent,
    "OverheadAppliedEvent": handle_OverheadAppliedEvent,
    "ProductionCompletedEvent": handle_ProductionCompletedEvent,
    "CostCardUpdatedEvent": handle_CostCardUpdatedEvent,
    "HPPCalculatedEvent": handle_HPPCalculatedEvent,
    "StandardCostCreatedEvent": handle_StandardCostCreatedEvent,
    "StandardCostActivatedEvent": handle_StandardCostActivatedEvent,
    "VarianceAnalyzedEvent": handle_VarianceAnalyzedEvent,

    # Payroll
    "PayrollRunCreatedEvent": handle_PayrollRunCreatedEvent,
    "PayrollRunCalculatedEvent": handle_PayrollRunCalculatedEvent,
    "PayrollRunApprovedEvent": handle_PayrollRunApprovedEvent,
    "PayrollRunPaidEvent": handle_PayrollRunPaidEvent,
    "PayrollRunPostedEvent": handle_PayrollRunPostedEvent,
    "PayrollRunCancelledEvent": handle_PayrollRunCancelledEvent,
    "PayslipGeneratedEvent": handle_PayslipGeneratedEvent,
    "PayslipSentToEmployeeEvent": handle_PayslipSentToEmployeeEvent,
    "EmployeeStructureUpdatedEvent": handle_EmployeeStructureUpdatedEvent,
    "SalaryComponentAddedEvent": handle_SalaryComponentAddedEvent,

    # Project Services
    "ProjectCreatedEvent": handle_ProjectCreatedEvent,
    "ProjectActivatedEvent": handle_ProjectActivatedEvent,
    "ProjectCompletedEvent": handle_ProjectCompletedEvent,
    "RevenueRecognizedEvent": handle_RevenueRecognizedEvent,
    "ProjectBillingGeneratedEvent": handle_ProjectBillingGeneratedEvent,
    "MilestoneReadyEvent": handle_MilestoneReadyEvent,
    "MilestoneBilledEvent": handle_MilestoneBilledEvent,
    "TimeEntrySubmittedEvent": handle_TimeEntrySubmittedEvent,
    "TimeEntryApprovedEvent": handle_TimeEntryApprovedEvent,
    "RetainerContractActivatedEvent": handle_RetainerContractActivatedEvent,

    # Purchase & Sales
    "PurchaseOrderCreatedEvent": handle_PurchaseOrderCreatedEvent,
    "PurchaseOrderApprovedEvent": handle_PurchaseOrderApprovedEvent,
    "SalesOrderCreatedEvent": handle_SalesOrderCreatedEvent,
    "SalesOrderApprovedEvent": handle_SalesOrderApprovedEvent,
    "GoodsReceiptCreatedEvent": handle_GoodsReceiptCreatedEvent,
    "DeliveryNoteShippedEvent": handle_DeliveryNoteShippedEvent,
    "SalesInvoiceIssuedEvent": handle_SalesInvoiceIssuedEvent,
    "SalesInvoicePaidEvent": handle_SalesInvoicePaidEvent,
    "PurchaseInvoiceReceivedEvent": handle_PurchaseInvoiceReceivedEvent,

    # Subledger AP
    "InvoiceReceivedEvent": handle_InvoiceReceivedEvent,
    "InvoiceVerifiedEvent": handle_InvoiceVerifiedEvent,
    "InvoiceDisputedEvent": handle_InvoiceDisputedEvent,
    "InvoiceCreatedEvent": handle_InvoiceCreatedEvent,
    "PaymentSentEvent": handle_PaymentSentEvent,
    "PaymentApprovedEvent": handle_PaymentApprovedEvent,
    "PaymentProcessedEvent": handle_PaymentProcessedEvent,
    "PaymentConfirmedEvent": handle_PaymentConfirmedEvent,
    "PaymentCancelledEvent": handle_PaymentCancelledEvent,
    "PaymentMadeEvent": handle_PaymentMadeEvent,
    "PaymentAppliedEvent": handle_PaymentAppliedEvent,
    "PaymentVoidedEvent": handle_PaymentVoidedEvent,
    "CreditNoteReceivedEvent": handle_CreditNoteReceivedEvent,
    "DebitNoteAppliedEvent": handle_DebitNoteAppliedEvent,
    "DebitNoteIssuedServiceEvent": handle_DebitNoteIssuedServiceEvent,
    "ThreeWayMatchResultEvent": handle_ThreeWayMatchResultEvent,
    "PaymentRunGeneratedEvent": handle_PaymentRunGeneratedEvent,
    "PaymentRunExecutedEvent": handle_PaymentRunExecutedEvent,

    # Subledger AR
    "InvoicePaidEvent": handle_InvoicePaidEvent,
    "InvoiceCancelledEvent": handle_InvoiceCancelledEvent,
    "InvoiceApprovedEvent": handle_InvoiceApprovedEvent,
    "InvoiceIssuedEvent": handle_InvoiceIssuedEvent,
    "InvoicePartiallyPaidEvent": handle_InvoicePartiallyPaidEvent,
    "InvoiceWrittenOffEvent": handle_InvoiceWrittenOffEvent,
    "PaymentReceivedEvent": handle_PaymentReceivedEvent,
    "PaymentAllocatedEvent": handle_PaymentAllocatedEvent,
    "CreditNoteIssuedEvent": handle_CreditNoteIssuedEvent,
    "CreditNoteAppliedEvent": handle_CreditNoteAppliedEvent,
    "DebitNoteIssuedEvent": handle_DebitNoteIssuedEvent,

    # System Settings
    "SettingChangedEvent": handle_SettingChangedEvent,
    "SettingResetEvent": handle_SettingResetEvent,
    "SettingAddedEvent": handle_SettingAddedEvent,
    "SettingRemovedEvent": handle_SettingRemovedEvent,
    "SettingsLockedEvent": handle_SettingsLockedEvent,
    "SettingsUnlockedEvent": handle_SettingsUnlockedEvent,
    "SettingsBulkUpdatedEvent": handle_SettingsBulkUpdatedEvent,

    # Tax Transaction
    "FakturSubmittedEvent": handle_FakturSubmittedEvent,
    "FakturApprovedEvent": handle_FakturApprovedEvent,
    "FakturRejectedEvent": handle_FakturRejectedEvent,
    "SPTSubmittedEvent": handle_SPTSubmittedEvent,
    "SPTApprovedEvent": handle_SPTApprovedEvent,
    "BupotSubmittedEvent": handle_BupotSubmittedEvent,
    "BupotApprovedEvent": handle_BupotApprovedEvent,
    "MeteraiUsedEvent": handle_MeteraiUsedEvent,

    # UMKM
    "UMKMDomainEvent": handle_UMKMDomainEvent,
    "DomainEventType": handle_DomainEventType,
    "DomainEventPublisher": handle_DomainEventPublisher,
    "TransactionCreatedEvent": handle_TransactionCreatedEvent,
    "TransactionUpdatedEvent": handle_TransactionUpdatedEvent,
    "TransactionDeletedEvent": handle_TransactionDeletedEvent,
    "TaxCalculatedEvent": handle_TaxCalculatedEvent,
    "TransactionRecordedEvent": handle_TransactionRecordedEvent,

    # Additional
    "GoingConcernEvent": handle_GoingConcernEvent,
    "SovereigntyEvent": handle_SovereigntyEvent,
    "IntegrationEvent": handle_IntegrationEvent,
    "AuditEvent": handle_AuditEvent,
    "EconomicEvent": handle_EconomicEvent,
    "CanonicalEvent": handle_CanonicalEvent,
    "QueuedEvent": handle_QueuedEvent,
    "DeadLetterEvent": handle_DeadLetterEvent,
    "OutboxEvent": handle_OutboxEvent,
    "LifecycleEvent": handle_LifecycleEvent,
    "_FallbackAuditEvent": handle__FallbackAuditEvent,
    "AdjustingEvent": handle_AdjustingEvent,
    "AfterReportingPeriodEvent": handle_AfterReportingPeriodEvent,
    "NonAdjustingEvent": handle_NonAdjustingEvent,
    "ProjectionEvent": handle_ProjectionEvent,
}

# =============================================================================
# REGISTRATION FUNCTION
# =============================================================================

def register_all_handlers(registry) -> None:
    """
    Daftarkan semua handler ke registry yang diberikan.
    Fungsi ini dipanggil oleh EventHandlerRegistry pada inisialisasi.
    """
    for event_name, handler in ALL_HANDLERS.items():
        try:
            registry.register_handler(event_name, handler)
        except Exception as e:
            logger.error(f"Gagal mendaftarkan handler untuk {event_name}: {e}")

    logger.info(f"Berhasil mendaftarkan {len(ALL_HANDLERS)} event handler.")