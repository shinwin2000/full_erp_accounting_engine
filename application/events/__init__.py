# application/events/__init__.py - Fixed with correct event imports and fallback aliases

from __future__ import annotations

"""
Package: application.events

Event publisher, subscriber, and handler registry for application layer events.
Supports domain events and integration events with transactional outbox pattern.
"""

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

# ============================================================================
# Helper untuk import yang mungkin gagal
# ============================================================================

def _safe_import(module_name, attr_name, fallback_attr_name=None):
    try:
        module = __import__(module_name, fromlist=[attr_name])
        return getattr(module, attr_name)
    except (ImportError, AttributeError):
        if fallback_attr_name:
            try:
                return getattr(module, fallback_attr_name)
            except AttributeError:
                pass
        # Buat dummy class jika tidak ada
        class DummyEvent:
            pass
        return DummyEvent

# ============================================================================
# Domain Events
# ============================================================================

# --- Journal events ---
try:
    from domain.journal.domain_events import (
        JournalPostedEvent,
        JournalApprovedEvent,
        JournalRejectedEvent,
        JournalSubmittedEvent,
        JournalReversedEvent,
        JournalVoidedEvent,
        JournalAdjustedEvent,
        JournalArchivedEvent,
        JournalUnarchivedEvent,
        JournalCancelledEvent,
    )
except ImportError:
    # Fallback: gunakan nama alternatif atau dummy
    JournalPostedEvent = _safe_import("domain.journal.domain_events", "JournalPostedEvent")
    JournalApprovedEvent = _safe_import("domain.journal.domain_events", "JournalApprovedEvent")
    JournalRejectedEvent = _safe_import("domain.journal.domain_events", "JournalRejectedEvent")
    JournalSubmittedEvent = _safe_import("domain.journal.domain_events", "JournalSubmittedEvent")
    JournalReversedEvent = _safe_import("domain.journal.domain_events", "JournalReversedEvent")
    JournalVoidedEvent = _safe_import("domain.journal.domain_events", "JournalVoidedEvent")
    JournalAdjustedEvent = _safe_import("domain.journal.domain_events", "JournalAdjustedEvent")
    JournalArchivedEvent = _safe_import("domain.journal.domain_events", "JournalArchivedEvent")
    JournalUnarchivedEvent = _safe_import("domain.journal.domain_events", "JournalUnarchivedEvent")
    JournalCancelledEvent = _safe_import("domain.journal.domain_events", "JournalCancelledEvent")

# --- AP/AR events ---
try:
    from domain.subledger_ap.domain_events import (
        ThreeWayMatchResultEvent,
        InvoiceReceivedEvent,
        InvoiceVerifiedEvent,
        InvoiceApprovedEvent,
        InvoicePaidEvent,
        InvoiceCancelledEvent,
        InvoiceDisputedEvent,
        PaymentSentEvent,
        PaymentApprovedEvent,
        PaymentProcessedEvent,
        PaymentConfirmedEvent,
        PaymentCancelledEvent,
        CreditNoteReceivedEvent,
        DebitNoteIssuedEvent,
    )
except ImportError:
    # Jika tidak ada, coba import dari domain.purchase_sales atau buat dummy
    ThreeWayMatchResultEvent = _safe_import("domain.purchase_sales.domain_events", "ThreeWayMatchResultEvent")
    InvoiceReceivedEvent = _safe_import("domain.subledger_ap.domain_events", "InvoiceReceivedEvent")
    InvoiceVerifiedEvent = _safe_import("domain.subledger_ap.domain_events", "InvoiceVerifiedEvent")
    InvoiceApprovedEvent = _safe_import("domain.subledger_ap.domain_events", "InvoiceApprovedEvent", "InvoiceApproved")
    InvoicePaidEvent = _safe_import("domain.subledger_ap.domain_events", "InvoicePaidEvent", "InvoicePaid")
    InvoiceCancelledEvent = _safe_import("domain.subledger_ap.domain_events", "InvoiceCancelledEvent", "InvoiceCancelled")
    InvoiceDisputedEvent = _safe_import("domain.subledger_ap.domain_events", "InvoiceDisputedEvent", "InvoiceDisputed")
    PaymentSentEvent = _safe_import("domain.subledger_ap.domain_events", "PaymentSentEvent", "PaymentSent")
    PaymentApprovedEvent = _safe_import("domain.subledger_ap.domain_events", "PaymentApprovedEvent", "PaymentApproved")
    PaymentProcessedEvent = _safe_import("domain.subledger_ap.domain_events", "PaymentProcessedEvent", "PaymentProcessed")
    PaymentConfirmedEvent = _safe_import("domain.subledger_ap.domain_events", "PaymentConfirmedEvent", "PaymentConfirmed")
    PaymentCancelledEvent = _safe_import("domain.subledger_ap.domain_events", "PaymentCancelledEvent", "PaymentCancelled")
    CreditNoteReceivedEvent = _safe_import("domain.subledger_ap.domain_events", "CreditNoteReceivedEvent", "CreditNoteReceived")
    DebitNoteIssuedEvent = _safe_import("domain.subledger_ap.domain_events", "DebitNoteIssuedEvent", "DebitNoteIssued")

# --- Bank Cash events ---
from domain.bank_cash.domain_events import (
    BankAccountCreatedEvent,
    BankAccountUpdatedEvent,
    BankAccountBlockedEvent,
    BankAccountClosedEvent,
    BankTransactionRecordedEvent,
    BankTransactionClearedEvent,
    BankTransactionReconciledEvent,
    BankTransferInitiatedEvent,
    BankTransferCompletedEvent,
    BankTransferFailedEvent,
    BankTransferCancelledEvent,
    CashReceiptConfirmedEvent,
    CashReceiptCancelledEvent,
    CashDisbursementApprovedEvent,
    CashDisbursementPaidEvent,
    CashDisbursementCancelledEvent,
    PettyCashDisbursementEvent,
    PettyCashReplenishedEvent,
    PettyCashAdjustedEvent,
    PettyCashSuspendedEvent,
    PettyCashActivatedEvent,
    PettyCashClosedEvent,
    BankReconciliationCompletedEvent,
    CashBookUpdatedEvent,
    CashBookClosedEvent,
)

# --- Budget events ---
from domain.budget.domain_events import (
    BudgetCreated,
    BudgetApproved,
    BudgetRejected,
    BudgetRevised,
    BudgetCancelled,
    BudgetClosed,
    BudgetArchived,
    BudgetLineAdded,
    BudgetLineRemoved,
    BudgetLineAdjusted,
    BudgetStatusChanged,
)

# --- COA events ---
from domain.coa.domain_events import (
    AccountCreatedEvent,
    AccountUpdatedEvent,
    AccountDeactivatedEvent,
    AccountReactivatedEvent,
    AccountLockedEvent,
    AccountUnlockedEvent,
    AccountMergedEvent,
    AccountSplitEvent,
    HierarchyChangedEvent,
    COACreatedEvent,
    COALockedEvent,
    COAUnlockedEvent,
    COAArchivedEvent,
)

# --- Fixed Asset events ---
from domain.fixed_asset.domain_events import (
    AssetAcquiredEvent,
    AssetUpdatedEvent,
    AssetDepreciationPostedEvent,
    AssetRevaluatedEvent,
    AssetDisposedEvent,
    AssetTransferredEvent,
    AssetImpairedEvent,
    AssetImpairmentReversedEvent,
    AssetFullyDepreciatedEvent,
    AssetGroupCreatedEvent,
    AssetGroupUpdatedEvent,
)

# --- Inventory events ---
from domain.inventory.domain_events import (
    ItemCreatedEvent,
    ItemUpdatedEvent,
    ItemDeactivatedEvent,
    StockMovementCreatedEvent,
    StockAdjustedEvent,
    StockOpnameCreatedEvent,
    StockOpnameApprovedEvent,
    InterWarehouseTransferCreatedEvent,
    TransferCompletedEvent,
    COGSCalculatedEvent,
    InventoryValuationUpdatedEvent,
    StockLevelAlertEvent,
)

# --- Manufacturing events ---
from domain.manufacturing.domain_events import (
    BOMCreatedEvent,
    BOMUpdatedEvent,
    BOMActivatedEvent,
    BOMObsoletedEvent,
    BOMItemAddedEvent,
    WorkOrderCreatedEvent,
    WorkOrderApprovedEvent,
    WorkOrderStartedEvent,
    WorkOrderCompletedEvent,
    WorkOrderCancelledEvent,
    MaterialIssuedEvent,
    LaborPostedEvent,
    OverheadAppliedEvent,
    ProductionCompletedEvent,
    CostCardUpdatedEvent,
    HPPCalculatedEvent,
    StandardCostCreatedEvent,
    StandardCostActivatedEvent,
    VarianceAnalyzedEvent,
)

# --- Payroll events ---
try:
    from domain.payroll.domain_events import (
        PayrollRunCreatedEvent,
        PayrollRunCalculatedEvent,
        PayrollRunApprovedEvent,
        PayrollRunPaidEvent,
        PayrollRunPostedEvent,
        PayrollRunCancelledEvent,
        PayslipGeneratedEvent,
        PayslipSentToEmployeeEvent,
        EmployeeStructureUpdatedEvent,
        SalaryComponentAddedEvent,
    )
except ImportError:
    # Fallback: coba tanpa akhiran Event
    PayrollRunCreatedEvent = _safe_import("domain.payroll.domain_events", "PayrollRunCreatedEvent", "PayrollRunCreated")
    PayrollRunCalculatedEvent = _safe_import("domain.payroll.domain_events", "PayrollRunCalculatedEvent", "PayrollRunCalculated")
    PayrollRunApprovedEvent = _safe_import("domain.payroll.domain_events", "PayrollRunApprovedEvent", "PayrollRunApproved")
    PayrollRunPaidEvent = _safe_import("domain.payroll.domain_events", "PayrollRunPaidEvent", "PayrollRunPaid")
    PayrollRunPostedEvent = _safe_import("domain.payroll.domain_events", "PayrollRunPostedEvent", "PayrollRunPosted")
    PayrollRunCancelledEvent = _safe_import("domain.payroll.domain_events", "PayrollRunCancelledEvent", "PayrollRunCancelled")
    PayslipGeneratedEvent = _safe_import("domain.payroll.domain_events", "PayslipGeneratedEvent", "PayslipGenerated")
    PayslipSentToEmployeeEvent = _safe_import("domain.payroll.domain_events", "PayslipSentToEmployeeEvent", "PayslipSentToEmployee")
    EmployeeStructureUpdatedEvent = _safe_import("domain.payroll.domain_events", "EmployeeStructureUpdatedEvent", "EmployeeStructureUpdated")
    SalaryComponentAddedEvent = _safe_import("domain.payroll.domain_events", "SalaryComponentAddedEvent", "SalaryComponentAdded")

# --- IAM events ---
from domain.iam.domain_events import (
    UserCreatedEvent,
    UserUpdatedEvent,
    UserActivatedEvent,
    UserDeactivatedEvent,
    UserSuspendedEvent,
    UserUnlockedEvent,
    UserPasswordChangedEvent,
    UserDeletedEvent,
    RoleCreatedEvent,
    RoleUpdatedEvent,
    RoleDeletedEvent,
    RoleAssignedEvent,
    RoleRevokedEvent,
    SessionCreatedEvent,
    SessionRefreshedEvent,
    SessionTerminatedEvent,
    SessionCompromisedEvent,
    LoginSuccessEvent,
    LoginFailureEvent,
    PermissionGrantedEvent,
    PermissionRevokedEvent,
)

# --- Tax events ---
from domain.tax_transaction.domain_events import (
    FakturSubmittedEvent,
    FakturApprovedEvent,
    FakturRejectedEvent,
    SPTSubmittedEvent,
    SPTApprovedEvent,
    BupotSubmittedEvent,
    BupotApprovedEvent,
    MeteraiUsedEvent,
)

# --- Fiscal Period events ---
from domain.fiscal_period.domain_events import (
    PeriodCreatedEvent,
    PeriodOpenedEvent,
    PeriodLockedEvent,
    PeriodClosedEvent,
    PeriodReopenedEvent,
    PeriodUpdatedEvent,
    PeriodStatusChangedEvent,
)

# --- Legal Entity events ---
try:
    from domain.legal_entity.domain_events import (
        CompanyRegisteredEvent,
        CompanySuspendedEvent,
        CompanyReactivatedEvent,
        CompanyDissolvedEvent,
        TaxProfileUpdatedEvent,
        CompanyAddressUpdatedEvent,
        CompanyContactUpdatedEvent,
        PKPStatusChangedEvent,
        LegalEntityCreatedEvent,
        LegalEntityDeactivatedEvent,
        LegalEntityUpdatedEvent,
    )
except ImportError:
    LegalEntityCreatedEvent = _safe_import("domain.legal_entity.domain_events", "LegalEntityCreatedEvent", "LegalEntityCreated")
    LegalEntityDeactivatedEvent = _safe_import("domain.legal_entity.domain_events", "LegalEntityDeactivatedEvent", "LegalEntityDeactivated")
    LegalEntityUpdatedEvent = _safe_import("domain.legal_entity.domain_events", "LegalEntityUpdatedEvent", "LegalEntityUpdated")
    CompanyRegisteredEvent = _safe_import("domain.legal_entity.domain_events", "CompanyRegisteredEvent", "CompanyRegistered")
    CompanySuspendedEvent = _safe_import("domain.legal_entity.domain_events", "CompanySuspendedEvent", "CompanySuspended")
    CompanyReactivatedEvent = _safe_import("domain.legal_entity.domain_events", "CompanyReactivatedEvent", "CompanyReactivated")
    CompanyDissolvedEvent = _safe_import("domain.legal_entity.domain_events", "CompanyDissolvedEvent", "CompanyDissolved")
    TaxProfileUpdatedEvent = _safe_import("domain.legal_entity.domain_events", "TaxProfileUpdatedEvent", "TaxProfileUpdated")
    CompanyAddressUpdatedEvent = _safe_import("domain.legal_entity.domain_events", "CompanyAddressUpdatedEvent", "CompanyAddressUpdated")
    CompanyContactUpdatedEvent = _safe_import("domain.legal_entity.domain_events", "CompanyContactUpdatedEvent", "CompanyContactUpdated")
    PKPStatusChangedEvent = _safe_import("domain.legal_entity.domain_events", "PKPStatusChangedEvent", "PKPStatusChanged")

# --- Goodwill events ---
from domain.goodwill.domain_events import (
    GoodwillRecognizedEvent,
    GoodwillImpairedEvent,
    GoodwillAmortizedEvent,
    GoodwillImpairmentReversedEvent,
    GoodwillDisposedEvent,
)

# --- Hedge events ---
from domain.hedge.domain_events import (
    HedgeDesignatedEvent,
    HedgeDiscontinuedEvent,
    HedgeEffectivenessTestedEvent,
    HedgeFairValueAdjustedEvent,
    HedgeAmountReclassifiedEvent,
    HedgeCancelledEvent,
)

# --- Consolidation events ---
from domain.consolidation.domain_events import (
    ConsolidationCreated,
    ConsolidationStarted,
    ConsolidationCompleted,
    ConsolidationCancelled,
    ConsolidationArchived,
    IntercompanyTransactionDetected,
    EliminationEntryCreated,
    NCICalculated,
)

# --- Customer/Supplier/Employee events ---
from domain.customer_supplier_employee.domain_events import (
    CustomerCreatedEvent,
    CustomerStatusChangedEvent,
    CustomerCreditLimitChangedEvent,
    CustomerBalanceUpdatedEvent,
    SupplierCreatedEvent,
    SupplierPaymentTermsChangedEvent,
    SupplierWithholdingCategoryChangedEvent,
    EmployeeCreatedEvent,
    EmployeeResignedEvent,
    EmployeePTKPUpdatedEvent,
    EmployeeBPJSUpdatedEvent,
)

# --- AR/AP additional events ---
try:
    from domain.subledger_ar.domain_events import (
        InvoiceIssuedEvent,
        InvoicePartiallyPaidEvent,
        InvoiceWrittenOffEvent,
        PaymentReceivedEvent,
        PaymentAllocatedEvent,
        CreditNoteIssuedEvent,
        CreditNoteAppliedEvent,
        DebitNoteIssuedEvent,
    )
except ImportError:
    InvoiceIssuedEvent = _safe_import("domain.subledger_ar.domain_events", "InvoiceIssuedEvent", "InvoiceIssued")
    InvoicePartiallyPaidEvent = _safe_import("domain.subledger_ar.domain_events", "InvoicePartiallyPaidEvent", "InvoicePartiallyPaid")
    InvoiceWrittenOffEvent = _safe_import("domain.subledger_ar.domain_events", "InvoiceWrittenOffEvent", "InvoiceWrittenOff")
    PaymentReceivedEvent = _safe_import("domain.subledger_ar.domain_events", "PaymentReceivedEvent", "PaymentReceived")
    PaymentAllocatedEvent = _safe_import("domain.subledger_ar.domain_events", "PaymentAllocatedEvent", "PaymentAllocated")
    CreditNoteIssuedEvent = _safe_import("domain.subledger_ar.domain_events", "CreditNoteIssuedEvent", "CreditNoteIssued")
    CreditNoteAppliedEvent = _safe_import("domain.subledger_ar.domain_events", "CreditNoteAppliedEvent", "CreditNoteApplied")
    DebitNoteIssuedEvent = _safe_import("domain.subledger_ar.domain_events", "DebitNoteIssuedEvent", "DebitNoteIssued")

# --- System Settings events ---
from domain.system_settings.domain_events import (
    SettingChangedEvent,
    SettingResetEvent,
    SettingAddedEvent,
    SettingRemovedEvent,
    SettingsLockedEvent,
    SettingsUnlockedEvent,
    SettingsBulkUpdatedEvent,
)

# --- Project events ---
from domain.project_services.domain_events import (
    ProjectCreatedEvent,
    ProjectActivatedEvent,
    ProjectCompletedEvent,
    RevenueRecognizedEvent,
    ProjectBillingGeneratedEvent,
    MilestoneReadyEvent,
    MilestoneBilledEvent,
    TimeEntrySubmittedEvent,
    TimeEntryApprovedEvent,
    RetainerContractActivatedEvent,
)

# --- Purchase & Sales events ---
try:
    from domain.purchase_sales.domain_events import (
        PurchaseOrderCreatedEvent,
        PurchaseOrderApprovedEvent,
        SalesOrderCreatedEvent,
        SalesOrderApprovedEvent,
        GoodsReceiptCreatedEvent,
        DeliveryNoteShippedEvent,
        SalesInvoiceIssuedEvent,
        SalesInvoicePaidEvent,
        PurchaseInvoiceReceivedEvent,
        InvoiceCreatedEvent,
        InvoiceIssuedEvent,
        InvoiceApprovedEvent,
        InvoiceCancelledEvent,
        InvoicePaidEvent,
        InvoicePartiallyPaidEvent,
        InvoiceDisputedEvent,
        InvoiceVerifiedEvent,
        InvoiceReceivedEvent,
        InvoiceWrittenOffEvent,
        CreditNoteIssuedEvent,
        CreditNoteReceivedEvent,
        CreditNoteAppliedEvent,
        DebitNoteIssuedEvent,
        DebitNoteAppliedEvent,
        DebitNoteIssuedServiceEvent,
    )
except ImportError:
    PurchaseOrderCreatedEvent = _safe_import("domain.purchase_sales.domain_events", "PurchaseOrderCreatedEvent", "PurchaseOrderCreated")
    PurchaseOrderApprovedEvent = _safe_import("domain.purchase_sales.domain_events", "PurchaseOrderApprovedEvent", "PurchaseOrderApproved")
    SalesOrderCreatedEvent = _safe_import("domain.purchase_sales.domain_events", "SalesOrderCreatedEvent", "SalesOrderCreated")
    SalesOrderApprovedEvent = _safe_import("domain.purchase_sales.domain_events", "SalesOrderApprovedEvent", "SalesOrderApproved")
    GoodsReceiptCreatedEvent = _safe_import("domain.purchase_sales.domain_events", "GoodsReceiptCreatedEvent", "GoodsReceiptCreated")
    DeliveryNoteShippedEvent = _safe_import("domain.purchase_sales.domain_events", "DeliveryNoteShippedEvent", "DeliveryNoteShipped")
    SalesInvoiceIssuedEvent = _safe_import("domain.purchase_sales.domain_events", "SalesInvoiceIssuedEvent", "SalesInvoiceIssued")
    SalesInvoicePaidEvent = _safe_import("domain.purchase_sales.domain_events", "SalesInvoicePaidEvent", "SalesInvoicePaid")
    PurchaseInvoiceReceivedEvent = _safe_import("domain.purchase_sales.domain_events", "PurchaseInvoiceReceivedEvent", "PurchaseInvoiceReceived")
    InvoiceCreatedEvent = _safe_import("domain.purchase_sales.domain_events", "InvoiceCreatedEvent", "InvoiceCreated")
    InvoiceIssuedEvent = _safe_import("domain.purchase_sales.domain_events", "InvoiceIssuedEvent", "InvoiceIssued")
    InvoiceApprovedEvent = _safe_import("domain.purchase_sales.domain_events", "InvoiceApprovedEvent", "InvoiceApproved")
    InvoiceCancelledEvent = _safe_import("domain.purchase_sales.domain_events", "InvoiceCancelledEvent", "InvoiceCancelled")
    InvoicePaidEvent = _safe_import("domain.purchase_sales.domain_events", "InvoicePaidEvent", "InvoicePaid")
    InvoicePartiallyPaidEvent = _safe_import("domain.purchase_sales.domain_events", "InvoicePartiallyPaidEvent", "InvoicePartiallyPaid")
    InvoiceDisputedEvent = _safe_import("domain.purchase_sales.domain_events", "InvoiceDisputedEvent", "InvoiceDisputed")
    InvoiceVerifiedEvent = _safe_import("domain.purchase_sales.domain_events", "InvoiceVerifiedEvent", "InvoiceVerified")
    InvoiceReceivedEvent = _safe_import("domain.purchase_sales.domain_events", "InvoiceReceivedEvent", "InvoiceReceived")
    InvoiceWrittenOffEvent = _safe_import("domain.purchase_sales.domain_events", "InvoiceWrittenOffEvent", "InvoiceWrittenOff")
    CreditNoteIssuedEvent = _safe_import("domain.purchase_sales.domain_events", "CreditNoteIssuedEvent", "CreditNoteIssued")
    CreditNoteReceivedEvent = _safe_import("domain.purchase_sales.domain_events", "CreditNoteReceivedEvent", "CreditNoteReceived")
    CreditNoteAppliedEvent = _safe_import("domain.purchase_sales.domain_events", "CreditNoteAppliedEvent", "CreditNoteApplied")
    DebitNoteIssuedEvent = _safe_import("domain.purchase_sales.domain_events", "DebitNoteIssuedEvent", "DebitNoteIssued")
    DebitNoteAppliedEvent = _safe_import("domain.purchase_sales.domain_events", "DebitNoteAppliedEvent", "DebitNoteApplied")
    DebitNoteIssuedServiceEvent = _safe_import("domain.purchase_sales.domain_events", "DebitNoteIssuedServiceEvent", "DebitNoteIssuedService")

# --- UMKM events ---
from domain.umkm_simplified.domain_events import (
    TransactionCreatedEvent,
    TransactionUpdatedEvent,
    TransactionDeletedEvent,
    TaxCalculatedEvent,
    TransactionRecordedEvent,
)

# --- Equity events ---
from domain.equity_retained.domain_events import (
    CapitalContributionRecordedEvent,
    CapitalContributionApprovedEvent,
    CapitalContributionPostedEvent,
    CapitalContributionCancelledEvent,
    CapitalWithdrawalRecordedEvent,
    CapitalWithdrawalApprovedEvent,
    CapitalWithdrawalPostedEvent,
    CapitalWithdrawalCancelledEvent,
    RetainedEarningsUpdatedEvent,
    RetainedEarningsAdjustedEvent,
    RetainedEarningsTransferEvent,
    DividendDeclaredEvent,
    DividendApprovedEvent,
    DividendPaidEvent,
    DividendPartiallyPaidEvent,
    DividendCancelledEvent,
)

# --- Forex events ---
from domain.forex.domain_events import (
    ForexRateUpdatedEvent,
    ForexTransactionRecordedEvent,
    ForexRevaluationCompletedEvent,
)

# --- Intangible Asset events ---
from domain.intangible_asset.domain_events import (
    IntangibleAssetAcquiredEvent,
    IntangibleAssetUpdatedEvent,
    IntangibleAssetAmortizationPostedEvent,
    IntangibleAssetImpairedEvent,
    IntangibleAssetImpairmentReversedEvent,
    IntangibleAssetDisposedEvent,
    IntangibleAssetFullyAmortizedEvent,
    IntangibleAssetRevaluatedEvent,
    IntangibleAssetTransferredEvent,
)

# --- Payment events (AP/AR payment) ---
try:
    from domain.subledger_ap.domain_events import PaymentMadeEvent, PaymentVoidedEvent, PaymentAppliedEvent
except ImportError:
    PaymentMadeEvent = _safe_import("domain.subledger_ap.domain_events", "PaymentMadeEvent", "PaymentMade")
    PaymentVoidedEvent = _safe_import("domain.subledger_ap.domain_events", "PaymentVoidedEvent", "PaymentVoided")
    PaymentAppliedEvent = _safe_import("domain.subledger_ap.domain_events", "PaymentAppliedEvent", "PaymentApplied")

# ============================================================================
# __all__ - Sertakan semua event yang telah diimpor
# ============================================================================

__all__ = [
    # Handler Registry
    "AsyncEventHandler",
    "EventHandler",
    "EventHandlerRegistry",
    "HandlerAlreadyRegisteredError",
    "HandlerEntry",
    "HandlerNotFoundError",
    "HandlerPriority",
    "HandlerRegistryError",
    "InvalidHandlerSignatureError",
    "SyncEventHandler",
    "event_handler_registry",
    "get_handlers",
    "has_handlers",
    "register_default_logging_handler",
    "register_handler",
    "register_wildcard",
    # Global Event Subscribers
    "handle_any_event",
    # Event Publisher
    "ApplicationEventPublisher",
    "CachePort",
    "CircuitBreakerOpenError",
    "EventEnvelope",
    "EventPublishError",
    "EventPublishFatalError",
    "EventPublishRetryableError",
    "EventPublishStatus",
    "MessageBrokerPort",
    "OutboxPort",
    "PublishMode",
    "PublishResult",
    "create_event_publisher",
    # Event Subscriber
    "ApplicationEventSubscriber",
    "DeadLetterStorePort",
    "DuplicateEventError",
    "EventProcessingError",
    "EventProcessingFatalError",
    "EventProcessingRetryableError",
    "IdempotencyChecker",
    "KafkaConsumerPort",
    "MetricsPort",
    "ProcessingStatus",
    "RedisClientPort",
    "SubscriptionConfig",
    "SubscriptionMode",
    "create_event_subscriber",
    # Journal
    "JournalPostedEvent",
    "JournalApprovedEvent",
    "JournalRejectedEvent",
    "JournalSubmittedEvent",
    "JournalReversedEvent",
    "JournalVoidedEvent",
    "JournalAdjustedEvent",
    "JournalArchivedEvent",
    "JournalUnarchivedEvent",
    "JournalCancelledEvent",
    # AP/AR
    "ThreeWayMatchResultEvent",
    "InvoiceReceivedEvent",
    "InvoiceVerifiedEvent",
    "InvoiceApprovedEvent",
    "InvoicePaidEvent",
    "InvoiceCancelledEvent",
    "InvoiceDisputedEvent",
    "PaymentSentEvent",
    "PaymentApprovedEvent",
    "PaymentProcessedEvent",
    "PaymentConfirmedEvent",
    "PaymentCancelledEvent",
    "CreditNoteReceivedEvent",
    "DebitNoteIssuedEvent",
    "PaymentMadeEvent",
    "PaymentVoidedEvent",
    "PaymentAppliedEvent",
    # Bank Cash
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
    # Budget
    "BudgetCreated",
    "BudgetApproved",
    "BudgetRejected",
    "BudgetRevised",
    "BudgetCancelled",
    "BudgetClosed",
    "BudgetArchived",
    "BudgetLineAdded",
    "BudgetLineRemoved",
    "BudgetLineAdjusted",
    "BudgetStatusChanged",
    # COA
    "AccountCreatedEvent",
    "AccountUpdatedEvent",
    "AccountDeactivatedEvent",
    "AccountReactivatedEvent",
    "AccountLockedEvent",
    "AccountUnlockedEvent",
    "AccountMergedEvent",
    "AccountSplitEvent",
    "HierarchyChangedEvent",
    "COACreatedEvent",
    "COALockedEvent",
    "COAUnlockedEvent",
    "COAArchivedEvent",
    # Fixed Asset
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
    # Inventory
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
    # Manufacturing
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
    # Payroll
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
    # IAM
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
    # Tax
    "FakturSubmittedEvent",
    "FakturApprovedEvent",
    "FakturRejectedEvent",
    "SPTSubmittedEvent",
    "SPTApprovedEvent",
    "BupotSubmittedEvent",
    "BupotApprovedEvent",
    "MeteraiUsedEvent",
    # Fiscal Period
    "PeriodCreatedEvent",
    "PeriodOpenedEvent",
    "PeriodLockedEvent",
    "PeriodClosedEvent",
    "PeriodReopenedEvent",
    "PeriodUpdatedEvent",
    "PeriodStatusChangedEvent",
    # Legal Entity
    "CompanyRegisteredEvent",
    "CompanySuspendedEvent",
    "CompanyReactivatedEvent",
    "CompanyDissolvedEvent",
    "TaxProfileUpdatedEvent",
    "CompanyAddressUpdatedEvent",
    "CompanyContactUpdatedEvent",
    "PKPStatusChangedEvent",
    "LegalEntityCreatedEvent",
    "LegalEntityDeactivatedEvent",
    "LegalEntityUpdatedEvent",
    # Goodwill
    "GoodwillRecognizedEvent",
    "GoodwillImpairedEvent",
    "GoodwillAmortizedEvent",
    "GoodwillImpairmentReversedEvent",
    "GoodwillDisposedEvent",
    # Hedge
    "HedgeDesignatedEvent",
    "HedgeDiscontinuedEvent",
    "HedgeEffectivenessTestedEvent",
    "HedgeFairValueAdjustedEvent",
    "HedgeAmountReclassifiedEvent",
    "HedgeCancelledEvent",
    # Consolidation
    "ConsolidationCreated",
    "ConsolidationStarted",
    "ConsolidationCompleted",
    "ConsolidationCancelled",
    "ConsolidationArchived",
    "IntercompanyTransactionDetected",
    "EliminationEntryCreated",
    "NCICalculated",
    # Customer/Supplier/Employee
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
    # AR/AP additional
    "InvoiceIssuedEvent",
    "InvoicePartiallyPaidEvent",
    "InvoiceWrittenOffEvent",
    "PaymentReceivedEvent",
    "PaymentAllocatedEvent",
    "CreditNoteIssuedEvent",
    "CreditNoteAppliedEvent",
    "DebitNoteIssuedEvent",
    # System Settings
    "SettingChangedEvent",
    "SettingResetEvent",
    "SettingAddedEvent",
    "SettingRemovedEvent",
    "SettingsLockedEvent",
    "SettingsUnlockedEvent",
    "SettingsBulkUpdatedEvent",
    # Project
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
    # Purchase & Sales
    "PurchaseOrderCreatedEvent",
    "PurchaseOrderApprovedEvent",
    "SalesOrderCreatedEvent",
    "SalesOrderApprovedEvent",
    "GoodsReceiptCreatedEvent",
    "DeliveryNoteShippedEvent",
    "SalesInvoiceIssuedEvent",
    "SalesInvoicePaidEvent",
    "PurchaseInvoiceReceivedEvent",
    "InvoiceCreatedEvent",
    "InvoiceIssuedEvent",
    "InvoiceApprovedEvent",
    "InvoiceCancelledEvent",
    "InvoicePaidEvent",
    "InvoicePartiallyPaidEvent",
    "InvoiceDisputedEvent",
    "InvoiceVerifiedEvent",
    "InvoiceReceivedEvent",
    "InvoiceWrittenOffEvent",
    "CreditNoteIssuedEvent",
    "CreditNoteReceivedEvent",
    "CreditNoteAppliedEvent",
    "DebitNoteIssuedEvent",
    "DebitNoteAppliedEvent",
    "DebitNoteIssuedServiceEvent",
    # UMKM
    "TransactionCreatedEvent",
    "TransactionUpdatedEvent",
    "TransactionDeletedEvent",
    "TaxCalculatedEvent",
    "TransactionRecordedEvent",
    # Equity
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
    # Forex
    "ForexRateUpdatedEvent",
    "ForexTransactionRecordedEvent",
    "ForexRevaluationCompletedEvent",
    # Intangible Asset
    "IntangibleAssetAcquiredEvent",
    "IntangibleAssetUpdatedEvent",
    "IntangibleAssetAmortizationPostedEvent",
    "IntangibleAssetImpairedEvent",
    "IntangibleAssetImpairmentReversedEvent",
    "IntangibleAssetDisposedEvent",
    "IntangibleAssetFullyAmortizedEvent",
    "IntangibleAssetRevaluatedEvent",
    "IntangibleAssetTransferredEvent",
]