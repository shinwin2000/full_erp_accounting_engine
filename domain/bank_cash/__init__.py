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

logger = logging.getLogger(__name__)

__version__ = "2.0.0"
__author__ = "ERP Accounting Engine Team"

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
from .cash_receipt_entity import (
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

# ==================== Log package loaded ====================
logger.info(f"Domain Bank & Cash package loaded (version {__version__})")

# ==================== Exports ====================
__all__ = [
    # Bank Account
    "BankAccountEntity",
    "BankAccountStatus",
    "BankAccountType",
    "BankAccountRepository",
    "BankAccountSignature",
    "DailyInterestAccrual",
    "InterestCalculationMethod",
    # Bank Transaction
    "BankTransactionEntity",
    "BankTransactionType",
    "BankTransactionStatus",
    "BankTransactionRepository",
    "TransactionHold",
    "TransactionSignature",
    "TransactionStatus",
    "TransactionType",
    # Bank Transfer
    "BankTransferEntity",
    "TransferStatus",
    "TransferType",
    "TransferPriority",
    "TransferFee",
    "TransferSignature",
    "BankTransferRepository",
    # Reconciliation
    "BankReconciliationEngine",
    "ReconciliationResult",
    "ReconciliationStatus",
    "ReconciliationItem",
    "ReconciledItemType",
    "MatchingMethod",
    # Cash Book
    "CashBookEntity",
    "CashBookStatus",
    "CashTransactionType",
    "CashTransaction",
    "DailyClosing",
    "CashBookRepository",
    # Petty Cash
    "PettyCashFundEntity",
    "PettyCashStatus",
    "PettyCashTransactionType",
    "PettyCashTransaction",
    "PettyCashRepository",
    "PettyCashAuditLog",
    "PettyCashFundSignature",
    # Cash Receipt
    "CashReceiptEntity",
    "CashReceiptStatus",
    "CashReceiptType",
    "PaymentMethod",
    "ReceiptAllocation",
    "ReceiptSignature",
    "CashReceiptRepository",
    # Cash Disbursement
    "CashDisbursementEntity",
    "CashDisbursementStatus",
    "CashDisbursementType",
    "ApprovalLevel",
    "ApprovalHistoryEntry",
    "PaymentAllocation",
    "BankAccountInfo",
    "TaxWithholdingInfo",
    "DisbursementSignature",
    "CashDisbursementRepository",
    # Aggregates
    "BankAggregate",
    "BankAccountAggregate",
    "BankSummary",
    "StatementPeriod",
    "BankAggregateRepository",
    "CashAggregate",
    "CashBookAggregate",
    "CashFlowType",
    "DailyCashSummary",
    "CashAggregateSignature",
    "CashAggregateRepository",
    # Events
    "DomainEvent",
    "DomainEventType",
    "DomainEventPublisher",
    "BankAccountCreated",
    "BankAccountCreatedEvent",
    "BankAccountUpdated",
    "BankAccountUpdatedEvent",
    "BankAccountBlockedEvent",
    "BankAccountClosedEvent",
    "BankTransactionRecorded",
    "BankTransactionRecordedEvent",
    "BankTransactionClearedEvent",
    "BankTransactionReconciledEvent",
    "BankTransferInitiatedEvent",
    "BankTransferCompletedEvent",
    "BankTransferFailedEvent",
    "BankTransferCancelledEvent",
    "BankTransferExecuted",
    "CashReceiptConfirmedEvent",
    "CashReceiptCancelledEvent",
    "CashReceiptIssued",
    "CashDisbursementApprovedEvent",
    "CashDisbursementPaidEvent",
    "CashDisbursementCancelledEvent",
    "CashDisbursementIssued",
    "PettyCashDisbursementEvent",
    "PettyCashReplenished",
    "PettyCashReplenishedEvent",
    "PettyCashAdjustedEvent",
    "PettyCashSuspendedEvent",
    "PettyCashActivatedEvent",
    "PettyCashClosedEvent",
    "PettyCashFundCreated",
    "BankReconciliationCompleted",
    "BankReconciliationCompletedEvent",
    "CashBookUpdatedEvent",
    "CashBookClosedEvent",
    # Invariants
    "InvariantResult",
    "BankCashInvariants",
    "BankCashInvariantEnforcer",
    "BankCashInvariantsValidator",
]
