"""
Package: application.events

Event publisher, subscriber, and handler registry for application layer events.
Supports domain events and integration events with transactional outbox pattern.
"""

from __future__ import annotations

# Handler Registry
from application.events.global_event_subscribers import handle_any_event
from application.events.handler_registry import (
    AsyncEventHandler,
    EventHandler,
    EventHandlerRegistry,
    HandlerAlreadyRegisteredError,
    HandlerEntry,
    HandlerNotFoundError,
    HandlerPriority,
    HandlerRegistryError,
    InvalidHandlerSignatureError,
    SyncEventHandler,
    event_handler_registry,
    get_handlers,
    has_handlers,
    register_default_logging_handler,
    register_handler,
    register_wildcard,
)

# Event Publisher
from application.events.publisher_application import (
    ApplicationEventPublisher,
    CachePort,
    CircuitBreakerOpenError,
    EventEnvelope,
    EventPublishError,
    EventPublishFatalError,
    EventPublishRetryableError,
    EventPublishStatus,
    MessageBrokerPort,
    OutboxPort,
    PublishMode,
    PublishResult,
    create_event_publisher,
)

# Event Subscriber
from application.events.subscriber_application import (
    ApplicationEventSubscriber,
    DeadLetterStorePort,
    DuplicateEventError,
    EventProcessingError,
    EventProcessingFatalError,
    EventProcessingRetryableError,
    IdempotencyChecker,
    KafkaConsumerPort,
    MetricsPort,
    ProcessingStatus,
    RedisClientPort,
    SubscriptionConfig,
    SubscriptionMode,
    create_event_subscriber,
)

# Bank Cash
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

# Budget
from domain.budget.domain_events import (
    BudgetApproved,
    BudgetArchived,
    BudgetCancelled,
    BudgetClosed,
    BudgetCreated,
    BudgetLineAdded,
    BudgetLineAdjusted,
    BudgetLineRemoved,
    BudgetRejected,
    BudgetRevised,
    BudgetStatusChanged,
)

# COA
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

# Consolidation
from domain.consolidation.domain_events import (
    ConsolidationArchived,
    ConsolidationCancelled,
    ConsolidationCompleted,
    ConsolidationCreated,
    ConsolidationStarted,
    EliminationEntryCreated,
    IntercompanyTransactionDetected,
    NCICalculated,
)

# Customer/Supplier/Employee
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

# Equity
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

# Fiscal Period
from domain.fiscal_period.domain_events import (
    PeriodClosedEvent,
    PeriodCreatedEvent,
    PeriodLockedEvent,
    PeriodOpenedEvent,
    PeriodReopenedEvent,
    PeriodStatusChangedEvent,
    PeriodUpdatedEvent,
)

# Fixed Asset
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

# Forex
from domain.forex.domain_events import (
    ForexRateUpdatedEvent,
    ForexRevaluationCompletedEvent,
    ForexTransactionRecordedEvent,
)

# Goodwill
from domain.goodwill.domain_events import (
    GoodwillAmortizedEvent,
    GoodwillDisposedEvent,
    GoodwillImpairedEvent,
    GoodwillImpairmentReversedEvent,
    GoodwillRecognizedEvent,
)

# Hedge
from domain.hedge.domain_events import (
    HedgeAmountReclassifiedEvent,
    HedgeCancelledEvent,
    HedgeDesignatedEvent,
    HedgeDiscontinuedEvent,
    HedgeEffectivenessTestedEvent,
    HedgeFairValueAdjustedEvent,
)

# IAM
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

# Intangible Asset
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

# Inventory
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

# --- Domain Events ---
# Journal
from domain.journal.domain_events import (
    JournalAdjustedEvent,
    JournalApprovedEvent,
    JournalArchivedEvent,
    JournalCancelledEvent,
    JournalPostedEvent,
    JournalRejectedEvent,
    JournalReversedEvent,
    JournalSubmittedEvent,
    JournalUnarchivedEvent,
    JournalVoidedEvent,
)

# Legal Entity
from domain.legal_entity.domain_events import (
    CompanyAddressUpdatedEvent,
    CompanyContactUpdatedEvent,
    CompanyDissolvedEvent,
    CompanyReactivatedEvent,
    CompanyRegisteredEvent,
    CompanySuspendedEvent,
    LegalEntityCreatedEvent,
    LegalEntityDeactivatedEvent,
    LegalEntityUpdatedEvent,
    PKPStatusChangedEvent,
    TaxProfileUpdatedEvent,
)

# Manufacturing
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

# Payroll
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

# Project
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

# Purchase & Sales (only unique events, avoid duplicates with subledger)
from domain.purchase_sales.domain_events import (
    DebitNoteIssuedServiceEvent,  # unique
    DeliveryNoteShippedEvent,
    GoodsReceiptCreatedEvent,
    InvoiceCreatedEvent,
    PurchaseInvoiceReceivedEvent,
    PurchaseOrderApprovedEvent,
    PurchaseOrderCreatedEvent,
    SalesInvoiceIssuedEvent,
    SalesInvoicePaidEvent,
    SalesOrderApprovedEvent,
    SalesOrderCreatedEvent,
)

# Subledger AP (Accounts Payable)
from domain.subledger_ap.domain_events import (
    CreditNoteReceivedEvent,
    DebitNoteIssuedEvent,
    InvoiceApprovedEvent,
    InvoiceCancelledEvent,
    InvoiceDisputedEvent,
    InvoicePaidEvent,
    InvoiceReceivedEvent,
    InvoiceVerifiedEvent,
    PaymentAppliedEvent,
    PaymentApprovedEvent,
    PaymentCancelledEvent,
    PaymentConfirmedEvent,
    PaymentMadeEvent,
    PaymentProcessedEvent,
    PaymentSentEvent,
    PaymentVoidedEvent,
    ThreeWayMatchResultEvent,
)

# Subledger AR (Accounts Receivable)
from domain.subledger_ar.domain_events import (
    CreditNoteAppliedEvent,
    CreditNoteIssuedEvent,
    InvoiceIssuedEvent,
    InvoicePartiallyPaidEvent,
    InvoiceWrittenOffEvent,
    PaymentAllocatedEvent,
    PaymentReceivedEvent,
)

# System Settings
from domain.system_settings.domain_events import (
    SettingAddedEvent,
    SettingChangedEvent,
    SettingRemovedEvent,
    SettingResetEvent,
    SettingsBulkUpdatedEvent,
    SettingsLockedEvent,
    SettingsUnlockedEvent,
)

# Tax
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

# UMKM
from domain.umkm_simplified.domain_events import (
    TaxCalculatedEvent,
    TransactionCreatedEvent,
    TransactionDeletedEvent,
    TransactionRecordedEvent,
    TransactionUpdatedEvent,
)

# ============================================================================
# all_event_handlers - Export for tests
# ============================================================================

def all_event_handlers():
    """
    Return all registered event handlers.
    This function is used by tests to verify that all handlers are registered.
    """
    try:
        if callable(get_handlers):
            try:
                return get_handlers(None)
            except TypeError:
                return get_handlers()
        elif hasattr(event_handler_registry, 'get_all_handlers'):
            return event_handler_registry.get_all_handlers()
        elif hasattr(event_handler_registry, 'handlers'):
            handlers = event_handler_registry.handlers
            if isinstance(handlers, dict):
                return list(handlers.values())
            return handlers
        else:
            return []
    except Exception:
        return []


# ============================================================================
# Exports (sorted alphabetically)
# ============================================================================

__all__ = [
    "AccountCreatedEvent",
    "AccountDeactivatedEvent",
    "AccountLockedEvent",
    "AccountMergedEvent",
    "AccountReactivatedEvent",
    "AccountSplitEvent",
    "AccountUnlockedEvent",
    "AccountUpdatedEvent",
    "ApplicationEventPublisher",
    "ApplicationEventSubscriber",
    "AssetAcquiredEvent",
    "AssetDepreciationPostedEvent",
    "AssetDisposedEvent",
    "AssetFullyDepreciatedEvent",
    "AssetGroupCreatedEvent",
    "AssetGroupUpdatedEvent",
    "AssetImpairedEvent",
    "AssetImpairmentReversedEvent",
    "AssetRevaluatedEvent",
    "AssetTransferredEvent",
    "AssetUpdatedEvent",
    "AsyncEventHandler",
    "BOMActivatedEvent",
    "BOMCreatedEvent",
    "BOMItemAddedEvent",
    "BOMObsoletedEvent",
    "BOMUpdatedEvent",
    "BankAccountBlockedEvent",
    "BankAccountClosedEvent",
    "BankAccountCreatedEvent",
    "BankAccountUpdatedEvent",
    "BankReconciliationCompletedEvent",
    "BankTransactionClearedEvent",
    "BankTransactionReconciledEvent",
    "BankTransactionRecordedEvent",
    "BankTransferCancelledEvent",
    "BankTransferCompletedEvent",
    "BankTransferFailedEvent",
    "BankTransferInitiatedEvent",
    "BudgetApproved",
    "BudgetArchived",
    "BudgetCancelled",
    "BudgetClosed",
    "BudgetCreated",
    "BudgetLineAdded",
    "BudgetLineAdjusted",
    "BudgetLineRemoved",
    "BudgetRejected",
    "BudgetRevised",
    "BudgetStatusChanged",
    "BupotApprovedEvent",
    "BupotSubmittedEvent",
    "COAArchivedEvent",
    "COACreatedEvent",
    "COALockedEvent",
    "COAUnlockedEvent",
    "COGSCalculatedEvent",
    "CachePort",
    "CapitalContributionApprovedEvent",
    "CapitalContributionCancelledEvent",
    "CapitalContributionPostedEvent",
    "CapitalContributionRecordedEvent",
    "CapitalWithdrawalApprovedEvent",
    "CapitalWithdrawalCancelledEvent",
    "CapitalWithdrawalPostedEvent",
    "CapitalWithdrawalRecordedEvent",
    "CashBookClosedEvent",
    "CashBookUpdatedEvent",
    "CashDisbursementApprovedEvent",
    "CashDisbursementCancelledEvent",
    "CashDisbursementPaidEvent",
    "CashReceiptCancelledEvent",
    "CashReceiptConfirmedEvent",
    "CircuitBreakerOpenError",
    "CompanyAddressUpdatedEvent",
    "CompanyContactUpdatedEvent",
    "CompanyDissolvedEvent",
    "CompanyReactivatedEvent",
    "CompanyRegisteredEvent",
    "CompanySuspendedEvent",
    "ConsolidationArchived",
    "ConsolidationCancelled",
    "ConsolidationCompleted",
    "ConsolidationCreated",
    "ConsolidationStarted",
    "CostCardUpdatedEvent",
    "CreditNoteAppliedEvent",
    "CreditNoteIssuedEvent",
    "CreditNoteReceivedEvent",
    "CustomerBalanceUpdatedEvent",
    "CustomerCreatedEvent",
    "CustomerCreditLimitChangedEvent",
    "CustomerStatusChangedEvent",
    "DeadLetterStorePort",
    "DebitNoteIssuedEvent",
    "DebitNoteIssuedServiceEvent",
    "DeliveryNoteShippedEvent",
    "DividendApprovedEvent",
    "DividendCancelledEvent",
    "DividendDeclaredEvent",
    "DividendPaidEvent",
    "DividendPartiallyPaidEvent",
    "DuplicateEventError",
    "EliminationEntryCreated",
    "EmployeeBPJSUpdatedEvent",
    "EmployeeCreatedEvent",
    "EmployeePTKPUpdatedEvent",
    "EmployeeResignedEvent",
    "EmployeeStructureUpdatedEvent",
    "EventEnvelope",
    "EventHandler",
    "EventHandlerRegistry",
    "EventProcessingError",
    "EventProcessingFatalError",
    "EventProcessingRetryableError",
    "EventPublishError",
    "EventPublishFatalError",
    "EventPublishRetryableError",
    "EventPublishStatus",
    "FakturApprovedEvent",
    "FakturRejectedEvent",
    "FakturSubmittedEvent",
    "ForexRateUpdatedEvent",
    "ForexRevaluationCompletedEvent",
    "ForexTransactionRecordedEvent",
    "GoodsReceiptCreatedEvent",
    "GoodwillAmortizedEvent",
    "GoodwillDisposedEvent",
    "GoodwillImpairedEvent",
    "GoodwillImpairmentReversedEvent",
    "GoodwillRecognizedEvent",
    "HPPCalculatedEvent",
    "HandlerAlreadyRegisteredError",
    "HandlerEntry",
    "HandlerNotFoundError",
    "HandlerPriority",
    "HandlerRegistryError",
    "HedgeAmountReclassifiedEvent",
    "HedgeCancelledEvent",
    "HedgeDesignatedEvent",
    "HedgeDiscontinuedEvent",
    "HedgeEffectivenessTestedEvent",
    "HedgeFairValueAdjustedEvent",
    "HierarchyChangedEvent",
    "IdempotencyChecker",
    "IntangibleAssetAcquiredEvent",
    "IntangibleAssetAmortizationPostedEvent",
    "IntangibleAssetDisposedEvent",
    "IntangibleAssetFullyAmortizedEvent",
    "IntangibleAssetImpairedEvent",
    "IntangibleAssetImpairmentReversedEvent",
    "IntangibleAssetRevaluatedEvent",
    "IntangibleAssetTransferredEvent",
    "IntangibleAssetUpdatedEvent",
    "InterWarehouseTransferCreatedEvent",
    "IntercompanyTransactionDetected",
    "InvalidHandlerSignatureError",
    "InventoryValuationUpdatedEvent",
    "InvoiceApprovedEvent",
    "InvoiceCancelledEvent",
    "InvoiceCreatedEvent",
    "InvoiceDisputedEvent",
    "InvoiceIssuedEvent",
    "InvoicePaidEvent",
    "InvoicePartiallyPaidEvent",
    "InvoiceReceivedEvent",
    "InvoiceVerifiedEvent",
    "InvoiceWrittenOffEvent",
    "ItemCreatedEvent",
    "ItemDeactivatedEvent",
    "ItemUpdatedEvent",
    "JournalAdjustedEvent",
    "JournalApprovedEvent",
    "JournalArchivedEvent",
    "JournalCancelledEvent",
    "JournalPostedEvent",
    "JournalRejectedEvent",
    "JournalReversedEvent",
    "JournalSubmittedEvent",
    "JournalUnarchivedEvent",
    "JournalVoidedEvent",
    "KafkaConsumerPort",
    "LaborPostedEvent",
    "LegalEntityCreatedEvent",
    "LegalEntityDeactivatedEvent",
    "LegalEntityUpdatedEvent",
    "LoginFailureEvent",
    "LoginSuccessEvent",
    "MaterialIssuedEvent",
    "MessageBrokerPort",
    "MeteraiUsedEvent",
    "MetricsPort",
    "MilestoneBilledEvent",
    "MilestoneReadyEvent",
    "NCICalculated",
    "OutboxPort",
    "OverheadAppliedEvent",
    "PKPStatusChangedEvent",
    "PaymentAllocatedEvent",
    "PaymentAppliedEvent",
    "PaymentApprovedEvent",
    "PaymentCancelledEvent",
    "PaymentConfirmedEvent",
    "PaymentMadeEvent",
    "PaymentProcessedEvent",
    "PaymentReceivedEvent",
    "PaymentSentEvent",
    "PaymentVoidedEvent",
    "PayrollRunApprovedEvent",
    "PayrollRunCalculatedEvent",
    "PayrollRunCancelledEvent",
    "PayrollRunCreatedEvent",
    "PayrollRunPaidEvent",
    "PayrollRunPostedEvent",
    "PayslipGeneratedEvent",
    "PayslipSentToEmployeeEvent",
    "PeriodClosedEvent",
    "PeriodCreatedEvent",
    "PeriodLockedEvent",
    "PeriodOpenedEvent",
    "PeriodReopenedEvent",
    "PeriodStatusChangedEvent",
    "PeriodUpdatedEvent",
    "PermissionGrantedEvent",
    "PermissionRevokedEvent",
    "PettyCashActivatedEvent",
    "PettyCashAdjustedEvent",
    "PettyCashClosedEvent",
    "PettyCashDisbursementEvent",
    "PettyCashReplenishedEvent",
    "PettyCashSuspendedEvent",
    "ProcessingStatus",
    "ProductionCompletedEvent",
    "ProjectActivatedEvent",
    "ProjectBillingGeneratedEvent",
    "ProjectCompletedEvent",
    "ProjectCreatedEvent",
    "PublishMode",
    "PublishResult",
    "PurchaseInvoiceReceivedEvent",
    "PurchaseOrderApprovedEvent",
    "PurchaseOrderCreatedEvent",
    "RedisClientPort",
    "RetainedEarningsAdjustedEvent",
    "RetainedEarningsTransferEvent",
    "RetainedEarningsUpdatedEvent",
    "RetainerContractActivatedEvent",
    "RevenueRecognizedEvent",
    "RoleAssignedEvent",
    "RoleCreatedEvent",
    "RoleDeletedEvent",
    "RoleRevokedEvent",
    "RoleUpdatedEvent",
    "SPTApprovedEvent",
    "SPTSubmittedEvent",
    "SalaryComponentAddedEvent",
    "SalesInvoiceIssuedEvent",
    "SalesInvoicePaidEvent",
    "SalesOrderApprovedEvent",
    "SalesOrderCreatedEvent",
    "SessionCompromisedEvent",
    "SessionCreatedEvent",
    "SessionRefreshedEvent",
    "SessionTerminatedEvent",
    "SettingAddedEvent",
    "SettingChangedEvent",
    "SettingRemovedEvent",
    "SettingResetEvent",
    "SettingsBulkUpdatedEvent",
    "SettingsLockedEvent",
    "SettingsUnlockedEvent",
    "StandardCostActivatedEvent",
    "StandardCostCreatedEvent",
    "StockAdjustedEvent",
    "StockLevelAlertEvent",
    "StockMovementCreatedEvent",
    "StockOpnameApprovedEvent",
    "StockOpnameCreatedEvent",
    "SubscriptionConfig",
    "SubscriptionMode",
    "SupplierCreatedEvent",
    "SupplierPaymentTermsChangedEvent",
    "SupplierWithholdingCategoryChangedEvent",
    "SyncEventHandler",
    "TaxCalculatedEvent",
    "TaxProfileUpdatedEvent",
    "ThreeWayMatchResultEvent",
    "TimeEntryApprovedEvent",
    "TimeEntrySubmittedEvent",
    "TransactionCreatedEvent",
    "TransactionDeletedEvent",
    "TransactionRecordedEvent",
    "TransactionUpdatedEvent",
    "TransferCompletedEvent",
    "UserActivatedEvent",
    "UserCreatedEvent",
    "UserDeactivatedEvent",
    "UserDeletedEvent",
    "UserPasswordChangedEvent",
    "UserSuspendedEvent",
    "UserUnlockedEvent",
    "UserUpdatedEvent",
    "VarianceAnalyzedEvent",
    "WorkOrderApprovedEvent",
    "WorkOrderCancelledEvent",
    "WorkOrderCompletedEvent",
    "WorkOrderCreatedEvent",
    "WorkOrderStartedEvent",
    "all_event_handlers",
    "create_event_publisher",
    "create_event_subscriber",
    "event_handler_registry",
    "get_handlers",
    "handle_any_event",
    "has_handlers",
    "register_default_logging_handler",
    "register_handler",
    "register_wildcard",
]
