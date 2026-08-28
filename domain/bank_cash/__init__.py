#!/usr/bin/env python3
"""
Package: domain.bank_cash
Layer: Domain / Bank & Cash

Responsibility:
    Mendefinisikan aggregate roots, entities, value objects, domain events,
    invariants, dan repository interfaces untuk subdomain Bank & Cash.
"""

from __future__ import annotations

import logging

# ==================== Bank Account ====================
from .bank_account_entity import (
    BankAccountEntity,
    BankAccountRepository,
    BankAccountSignature,
    BankAccountStatus,
    BankAccountType,
    DailyInterestAccrual,
    InterestCalculationMethod,
)

# ==================== Aggregates ====================
from .bank_aggregate_root import (
    BankAccountAggregate,
    BankAggregate,
    BankAggregateRepository,
    BankSummary,
    StatementPeriod,
)

# ==================== Bank Reconciliation ====================
from .bank_reconciliation_engine import (
    BankReconciliationEngine,
    MatchingMethod,
    ReconciledItemType,
    ReconciliationItem,
    ReconciliationResult,
    ReconciliationStatus,
)

# ==================== Bank Transaction ====================
from .bank_transaction_entity import (
    BankTransactionEntity,
    BankTransactionRepository,
    BankTransactionStatus,
    BankTransactionType,
    TransactionHold,
    TransactionSignature,
    TransactionStatus,
    TransactionType,
)

# ==================== Bank Transfer ====================
from .bank_transfer_entity import (
    BankTransferEntity,
    BankTransferRepository,
    TransferFee,
    TransferPriority,
    TransferSignature,
    TransferStatus,
    TransferType,
)

# ==================== Cash Aggregates ====================
from .cash_aggregate_root import (
    CashAggregate,
    CashAggregateRepository,
    CashAggregateSignature,
    CashBookAggregate,
    CashFlowType,
    DailyCashSummary,
)

# ==================== Cash Book ====================
from .cash_book_entity import (
    CashBookEntity,
    CashBookRepository,
    CashBookStatus,
    CashTransaction,
    CashTransactionType,
    DailyClosing,
)

# ==================== Cash Disbursement ====================
from .cash_disbursement_entity import (
    ApprovalHistoryEntry,
    ApprovalLevel,
    BankAccountInfo,
    CashDisbursementEntity,
    CashDisbursementRepository,
    CashDisbursementStatus,
    CashDisbursementType,
    DisbursementSignature,
    PaymentAllocation,
    PaymentMethod,
    TaxWithholdingInfo,
)

# ==================== Cash Receipt ====================
from .cash_receipt_entity import (  # type: ignore
    CashReceiptEntity,
    CashReceiptRepository,
    CashReceiptStatus,
    CashReceiptType,
    ReceiptAllocation,
    ReceiptSignature,
)

# ==================== Domain Events ====================
from .domain_events import (
    BankAccountBlockedEvent,
    BankAccountClosedEvent,
    BankAccountCreated,
    BankAccountCreatedEvent,
    BankAccountUpdated,
    BankAccountUpdatedEvent,
    BankReconciliationCompleted,
    BankReconciliationCompletedEvent,
    BankTransactionClearedEvent,
    BankTransactionReconciledEvent,
    BankTransactionRecorded,
    BankTransactionRecordedEvent,
    BankTransferCancelledEvent,
    BankTransferCompletedEvent,
    BankTransferExecuted,
    BankTransferFailedEvent,
    BankTransferInitiatedEvent,
    CashBookClosedEvent,
    CashBookUpdatedEvent,
    CashDisbursementApprovedEvent,
    CashDisbursementCancelledEvent,
    CashDisbursementIssued,
    CashDisbursementPaidEvent,
    CashReceiptCancelledEvent,
    CashReceiptConfirmedEvent,
    CashReceiptIssued,
    DomainEvent,
    DomainEventPublisher,
    DomainEventType,
    PettyCashActivatedEvent,
    PettyCashAdjustedEvent,
    PettyCashClosedEvent,
    PettyCashDisbursementEvent,
    PettyCashFundCreated,
    PettyCashReplenished,
    PettyCashReplenishedEvent,
    PettyCashSuspendedEvent,
)

# ==================== Invariants ====================
from .invariants import (
    BankCashInvariantEnforcer,
    BankCashInvariants,
    BankCashInvariantsValidator,
    InvariantResult,
)

# ==================== Petty Cash ====================
from .petty_cash_fund_entity import (
    PettyCashAuditLog,
    PettyCashFundEntity,
    PettyCashFundSignature,
    PettyCashRepository,
    PettyCashStatus,
    PettyCashTransaction,
    PettyCashTransactionType,
)

logger = logging.getLogger(__name__)

__version__ = "2.0.0"
__author__ = "ERP Accounting Engine Team"

logger.info(f"Domain Bank & Cash package loaded (version {__version__})")

__all__ = [
    "ApprovalHistoryEntry",
    "ApprovalLevel",
    "BankAccountAggregate",
    "BankAccountBlockedEvent",
    "BankAccountClosedEvent",
    "BankAccountCreated",
    "BankAccountCreatedEvent",
    "BankAccountEntity",
    "BankAccountInfo",
    "BankAccountRepository",
    "BankAccountSignature",
    "BankAccountStatus",
    "BankAccountType",
    "BankAccountUpdated",
    "BankAccountUpdatedEvent",
    "BankAggregate",
    "BankAggregateRepository",
    "BankCashInvariantEnforcer",
    "BankCashInvariants",
    "BankCashInvariantsValidator",
    "BankReconciliationCompleted",
    "BankReconciliationCompletedEvent",
    "BankReconciliationEngine",
    "BankSummary",
    "BankTransactionClearedEvent",
    "BankTransactionEntity",
    "BankTransactionReconciledEvent",
    "BankTransactionRecorded",
    "BankTransactionRecordedEvent",
    "BankTransactionRepository",
    "BankTransactionStatus",
    "BankTransactionType",
    "BankTransferCancelledEvent",
    "BankTransferCompletedEvent",
    "BankTransferEntity",
    "BankTransferExecuted",
    "BankTransferFailedEvent",
    "BankTransferInitiatedEvent",
    "BankTransferRepository",
    "CashAggregate",
    "CashAggregateRepository",
    "CashAggregateSignature",
    "CashBookAggregate",
    "CashBookClosedEvent",
    "CashBookEntity",
    "CashBookRepository",
    "CashBookStatus",
    "CashBookUpdatedEvent",
    "CashDisbursementApprovedEvent",
    "CashDisbursementCancelledEvent",
    "CashDisbursementEntity",
    "CashDisbursementIssued",
    "CashDisbursementPaidEvent",
    "CashDisbursementRepository",
    "CashDisbursementStatus",
    "CashDisbursementType",
    "CashFlowType",
    "CashReceiptCancelledEvent",
    "CashReceiptConfirmedEvent",
    "CashReceiptEntity",
    "CashReceiptIssued",
    "CashReceiptRepository",
    "CashReceiptStatus",
    "CashReceiptType",
    "CashTransaction",
    "CashTransactionType",
    "DailyCashSummary",
    "DailyClosing",
    "DailyInterestAccrual",
    "DisbursementSignature",
    "DomainEvent",
    "DomainEventPublisher",
    "DomainEventType",
    "InterestCalculationMethod",
    "InvariantResult",
    "MatchingMethod",
    "PaymentAllocation",
    "PaymentMethod",
    "PettyCashActivatedEvent",
    "PettyCashAdjustedEvent",
    "PettyCashAuditLog",
    "PettyCashClosedEvent",
    "PettyCashDisbursementEvent",
    "PettyCashFundCreated",
    "PettyCashFundEntity",
    "PettyCashFundSignature",
    "PettyCashReplenished",
    "PettyCashReplenishedEvent",
    "PettyCashRepository",
    "PettyCashStatus",
    "PettyCashSuspendedEvent",
    "PettyCashTransaction",
    "PettyCashTransactionType",
    "ReceiptAllocation",
    "ReceiptSignature",
    "ReconciledItemType",
    "ReconciliationItem",
    "ReconciliationResult",
    "ReconciliationStatus",
    "StatementPeriod",
    "TaxWithholdingInfo",
    "TransactionHold",
    "TransactionSignature",
    "TransactionStatus",
    "TransactionType",
    "TransferFee",
    "TransferPriority",
    "TransferSignature",
    "TransferStatus",
    "TransferType",
]
