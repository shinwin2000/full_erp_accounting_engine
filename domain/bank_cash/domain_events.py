#!/usr/bin/env python3
"""
Module: domain_events.py
Layer: Domain / Bank & Cash
Responsibility: Event domain untuk Bank & Cash.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class DomainEventType(Enum):
    BANK_ACCOUNT_CREATED = "bank_account_created"
    BANK_ACCOUNT_UPDATED = "bank_account_updated"
    BANK_ACCOUNT_BLOCKED = "bank_account_blocked"
    BANK_ACCOUNT_CLOSED = "bank_account_closed"
    BANK_TRANSACTION_RECORDED = "bank_transaction_recorded"
    BANK_TRANSACTION_CLEARED = "bank_transaction_cleared"
    BANK_TRANSACTION_RECONCILED = "bank_transaction_reconciled"
    BANK_TRANSFER_INITIATED = "bank_transfer_initiated"
    BANK_TRANSFER_COMPLETED = "bank_transfer_completed"
    BANK_TRANSFER_FAILED = "bank_transfer_failed"
    BANK_TRANSFER_CANCELLED = "bank_transfer_cancelled"
    CASH_RECEIPT_CONFIRMED = "cash_receipt_confirmed"
    CASH_RECEIPT_CANCELLED = "cash_receipt_cancelled"
    CASH_DISBURSEMENT_APPROVED = "cash_disbursement_approved"
    CASH_DISBURSEMENT_PAID = "cash_disbursement_paid"
    CASH_DISBURSEMENT_CANCELLED = "cash_disbursement_cancelled"
    PETTY_CASH_DISBURSEMENT = "petty_cash_disbursement"
    PETTY_CASH_REPLENISHED = "petty_cash_replenished"
    PETTY_CASH_ADJUSTED = "petty_cash_adjusted"
    PETTY_CASH_SUSPENDED = "petty_cash_suspended"
    PETTY_CASH_ACTIVATED = "petty_cash_activated"
    PETTY_CASH_CLOSED = "petty_cash_closed"
    BANK_RECONCILIATION_COMPLETED = "bank_reconciliation_completed"
    CASH_BOOK_UPDATED = "cash_book_updated"
    CASH_BOOK_CLOSED = "cash_book_closed"


@dataclass
class DomainEvent:
    event_id: UUID
    event_type: DomainEventType
    aggregate_id: UUID
    aggregate_version: int
    occurred_at: datetime
    event_data: dict[str, Any]
    user_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "event_id": str(self.event_id),
                "event_type": self.event_type.value,
                "aggregate_id": str(self.aggregate_id),
                "aggregate_version": self.aggregate_version,
                "occurred_at": self.occurred_at.isoformat(),
                "user_id": self.user_id,
                "correlation_id": self.correlation_id,
                "causation_id": self.causation_id,
                "event_data": self.event_data,
            },
            default=str,
        )

    @classmethod
    def from_json(cls, json_str: str) -> DomainEvent:
        data = json.loads(json_str)
        return cls(
            event_id=UUID(data["event_id"]),
            event_type=DomainEventType(data["event_type"]),
            aggregate_id=UUID(data["aggregate_id"]),
            aggregate_version=data["aggregate_version"],
            occurred_at=datetime.fromisoformat(data["occurred_at"]),
            event_data=data["event_data"],
            user_id=data.get("user_id"),
            correlation_id=data.get("correlation_id"),
            causation_id=data.get("causation_id"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type.value,
            "aggregate_id": str(self.aggregate_id),
            "aggregate_version": self.aggregate_version,
            "occurred_at": self.occurred_at.isoformat(),
            "user_id": self.user_id,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "event_data": self.event_data,
        }


# === BANK ACCOUNT EVENTS ===


@dataclass
class BankAccountCreatedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        account_id: UUID,
        account_number: str,
        account_name: str,
        account_type: str,
        bank_name: str,
        currency: str,
        initial_balance: Decimal,
        created_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "account_id": str(account_id),
            "account_number": account_number,
            "account_name": account_name,
            "account_type": account_type,
            "bank_name": bank_name,
            "currency": currency,
            "initial_balance": str(initial_balance),
            "created_by": created_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.BANK_ACCOUNT_CREATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class BankAccountUpdatedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        account_id: UUID,
        changes: dict[str, Any],
        updated_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "account_id": str(account_id),
            "changes": changes,
            "updated_by": updated_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.BANK_ACCOUNT_UPDATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class BankAccountBlockedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        account_id: UUID,
        reason: str,
        blocked_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "account_id": str(account_id),
            "reason": reason,
            "blocked_by": blocked_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.BANK_ACCOUNT_BLOCKED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class BankAccountClosedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        account_id: UUID,
        closed_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "account_id": str(account_id),
            "closed_by": closed_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.BANK_ACCOUNT_CLOSED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# === BANK TRANSACTION EVENTS ===


@dataclass
class BankTransactionRecordedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        transaction_id: UUID,
        account_id: UUID,
        amount: Decimal,
        currency: str,
        transaction_type: str,
        recorded_by: str,
        reference_number: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "transaction_id": str(transaction_id),
            "account_id": str(account_id),
            "amount": str(amount),
            "currency": currency,
            "transaction_type": transaction_type,
            "recorded_by": recorded_by,
            "reference_number": reference_number,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.BANK_TRANSACTION_RECORDED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class BankTransactionClearedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        transaction_id: UUID,
        cleared_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "transaction_id": str(transaction_id),
            "cleared_by": cleared_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.BANK_TRANSACTION_CLEARED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class BankTransactionReconciledEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        transaction_id: UUID,
        reconciled_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "transaction_id": str(transaction_id),
            "reconciled_by": reconciled_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.BANK_TRANSACTION_RECONCILED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# === BANK TRANSFER EVENTS ===


@dataclass
class BankTransferInitiatedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        transfer_id: UUID,
        from_account_id: UUID,
        to_account_id: UUID,
        amount: Decimal,
        currency: str,
        initiated_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "transfer_id": str(transfer_id),
            "from_account_id": str(from_account_id),
            "to_account_id": str(to_account_id),
            "amount": str(amount),
            "currency": currency,
            "initiated_by": initiated_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.BANK_TRANSFER_INITIATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class BankTransferCompletedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        transfer_id: UUID,
        completed_by: str,
        reference: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "transfer_id": str(transfer_id),
            "completed_by": completed_by,
            "reference": reference,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.BANK_TRANSFER_COMPLETED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class BankTransferFailedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        transfer_id: UUID,
        reason: str,
        failed_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "transfer_id": str(transfer_id),
            "reason": reason,
            "failed_by": failed_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.BANK_TRANSFER_FAILED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class BankTransferCancelledEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        transfer_id: UUID,
        reason: str,
        cancelled_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "transfer_id": str(transfer_id),
            "reason": reason,
            "cancelled_by": cancelled_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.BANK_TRANSFER_CANCELLED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# === CASH RECEIPT EVENTS ===


@dataclass
class CashReceiptConfirmedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        receipt_id: UUID,
        receipt_number: str,
        amount: Decimal,
        currency: str,
        confirmed_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "receipt_id": str(receipt_id),
            "receipt_number": receipt_number,
            "amount": str(amount),
            "currency": currency,
            "confirmed_by": confirmed_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.CASH_RECEIPT_CONFIRMED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class CashReceiptCancelledEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        receipt_id: UUID,
        reason: str,
        cancelled_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "receipt_id": str(receipt_id),
            "reason": reason,
            "cancelled_by": cancelled_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.CASH_RECEIPT_CANCELLED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# === CASH DISBURSEMENT EVENTS ===


@dataclass
class CashDisbursementApprovedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        disbursement_id: UUID,
        amount: Decimal,
        currency: str,
        approved_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "disbursement_id": str(disbursement_id),
            "amount": str(amount),
            "currency": currency,
            "approved_by": approved_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.CASH_DISBURSEMENT_APPROVED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class CashDisbursementPaidEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        disbursement_id: UUID,
        paid_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "disbursement_id": str(disbursement_id),
            "paid_by": paid_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.CASH_DISBURSEMENT_PAID,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class CashDisbursementCancelledEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        disbursement_id: UUID,
        reason: str,
        cancelled_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "disbursement_id": str(disbursement_id),
            "reason": reason,
            "cancelled_by": cancelled_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.CASH_DISBURSEMENT_CANCELLED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# === PETTY CASH EVENTS ===


@dataclass
class PettyCashDisbursementEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        petty_cash_id: UUID,
        amount: Decimal,
        description: str,
        approved_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "petty_cash_id": str(petty_cash_id),
            "amount": str(amount),
            "description": description,
            "approved_by": approved_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.PETTY_CASH_DISBURSEMENT,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class PettyCashReplenishedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        petty_cash_id: UUID,
        amount: Decimal,
        replenished_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "petty_cash_id": str(petty_cash_id),
            "amount": str(amount),
            "replenished_by": replenished_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.PETTY_CASH_REPLENISHED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class PettyCashAdjustedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        petty_cash_id: UUID,
        adjustment_amount: Decimal,
        reason: str,
        adjusted_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "petty_cash_id": str(petty_cash_id),
            "adjustment_amount": str(adjustment_amount),
            "reason": reason,
            "adjusted_by": adjusted_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.PETTY_CASH_ADJUSTED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class PettyCashSuspendedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        petty_cash_id: UUID,
        reason: str,
        suspended_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "petty_cash_id": str(petty_cash_id),
            "reason": reason,
            "suspended_by": suspended_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.PETTY_CASH_SUSPENDED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class PettyCashActivatedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        petty_cash_id: UUID,
        activated_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "petty_cash_id": str(petty_cash_id),
            "activated_by": activated_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.PETTY_CASH_ACTIVATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class PettyCashClosedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        petty_cash_id: UUID,
        final_balance: Decimal,
        closed_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "petty_cash_id": str(petty_cash_id),
            "final_balance": str(final_balance),
            "closed_by": closed_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.PETTY_CASH_CLOSED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# === RECONCILIATION & CASH BOOK EVENTS ===


@dataclass
class BankReconciliationCompletedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        account_id: UUID,
        statement_date: datetime,
        statement_balance: Decimal,
        book_balance: Decimal,
        difference: Decimal,
        reconciled_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "account_id": str(account_id),
            "statement_date": statement_date.isoformat(),
            "statement_balance": str(statement_balance),
            "book_balance": str(book_balance),
            "difference": str(difference),
            "reconciled_by": reconciled_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.BANK_RECONCILIATION_COMPLETED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class CashBookUpdatedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        cash_book_id: UUID,
        new_balance: Decimal,
        transaction_type: str,
        amount: Decimal,
        updated_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "cash_book_id": str(cash_book_id),
            "new_balance": str(new_balance),
            "transaction_type": transaction_type,
            "amount": str(amount),
            "updated_by": updated_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.CASH_BOOK_UPDATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class CashBookClosedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        cash_book_id: UUID,
        closed_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "cash_book_id": str(cash_book_id),
            "closed_by": closed_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.CASH_BOOK_CLOSED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# === DOMAIN EVENT PUBLISHER ===


class DomainEventPublisher:
    async def publish(self, event: DomainEvent) -> None:
        logger.info(
            f"Publishing event: {event.event_type.value} for aggregate {event.aggregate_id}"
        )
        if not hasattr(self, "_published_events"):
            self._published_events = []
        self._published_events.append(event)

    async def publish_many(self, events: list[DomainEvent]) -> None:
        for event in events:
            await self.publish(event)

    def get_published_events(self) -> list[DomainEvent]:
        return getattr(self, "_published_events", [])

    def clear(self) -> None:
        if hasattr(self, "_published_events"):
            self._published_events = []


# === COMPATIBILITY SHIMS FOR APPLICATION SERVICE LAYER ===


class BankAccountCreated(DomainEvent):
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        if "event_id" not in kwargs:
            self.event_id = uuid4()
        if "event_data" not in kwargs:
            self.event_data = kwargs
        if "occurred_at" not in kwargs:
            self.occurred_at = datetime.now(UTC)
        if "event_type" not in kwargs:
            self.event_type = DomainEventType.BANK_ACCOUNT_CREATED


class BankAccountUpdated(DomainEvent):
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        if "event_id" not in kwargs:
            self.event_id = uuid4()
        if "event_data" not in kwargs:
            self.event_data = kwargs
        if "occurred_at" not in kwargs:
            self.occurred_at = datetime.now(UTC)
        if "event_type" not in kwargs:
            self.event_type = DomainEventType.BANK_ACCOUNT_UPDATED


class BankTransactionRecorded(DomainEvent):
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        if "event_id" not in kwargs:
            self.event_id = uuid4()
        if "event_data" not in kwargs:
            self.event_data = kwargs
        if "occurred_at" not in kwargs:
            self.occurred_at = datetime.now(UTC)
        if "event_type" not in kwargs:
            self.event_type = DomainEventType.BANK_TRANSACTION_RECORDED


class BankReconciliationCompleted(DomainEvent):
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        if "event_id" not in kwargs:
            self.event_id = uuid4()
        if "event_data" not in kwargs:
            self.event_data = kwargs
        if "occurred_at" not in kwargs:
            self.occurred_at = datetime.now(UTC)
        if "event_type" not in kwargs:
            self.event_type = DomainEventType.BANK_RECONCILIATION_COMPLETED


class BankTransferExecuted(DomainEvent):
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        if "event_id" not in kwargs:
            self.event_id = uuid4()
        if "event_data" not in kwargs:
            self.event_data = kwargs
        if "occurred_at" not in kwargs:
            self.occurred_at = datetime.now(UTC)
        if "event_type" not in kwargs:
            self.event_type = DomainEventType.BANK_TRANSFER_COMPLETED


class CashReceiptIssued(DomainEvent):
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        if "event_id" not in kwargs:
            self.event_id = uuid4()
        if "event_data" not in kwargs:
            self.event_data = kwargs
        if "occurred_at" not in kwargs:
            self.occurred_at = datetime.now(UTC)
        if "event_type" not in kwargs:
            self.event_type = DomainEventType.CASH_RECEIPT_CONFIRMED


class CashDisbursementIssued(DomainEvent):
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        if "event_id" not in kwargs:
            self.event_id = uuid4()
        if "event_data" not in kwargs:
            self.event_data = kwargs
        if "occurred_at" not in kwargs:
            self.occurred_at = datetime.now(UTC)
        if "event_type" not in kwargs:
            self.event_type = DomainEventType.CASH_DISBURSEMENT_PAID


class PettyCashFundCreated(DomainEvent):
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        if "event_id" not in kwargs:
            self.event_id = uuid4()
        if "event_data" not in kwargs:
            self.event_data = kwargs
        if "occurred_at" not in kwargs:
            self.occurred_at = datetime.now(UTC)
        if "event_type" not in kwargs:
            self.event_type = DomainEventType.PETTY_CASH_REPLENISHED


class PettyCashReplenished(DomainEvent):
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        if "event_id" not in kwargs:
            self.event_id = uuid4()
        if "event_data" not in kwargs:
            self.event_data = kwargs
        if "occurred_at" not in kwargs:
            self.occurred_at = datetime.now(UTC)
        if "event_type" not in kwargs:
            self.event_type = DomainEventType.PETTY_CASH_REPLENISHED


__all__ = [
    "BankAccountCreated",
    "BankAccountCreatedEvent",
    "BankAccountUpdated",
    "BankAccountUpdatedEvent",
    "BankReconciliationCompleted",
    "BankReconciliationCompletedEvent",
    "BankTransactionRecorded",
    "BankTransactionRecordedEvent",
    "BankTransferExecuted",
    "CashDisbursementIssued",
    "CashReceiptIssued",
    "DomainEvent",
    "DomainEventPublisher",
    "DomainEventType",
    "PettyCashFundCreated",
    "PettyCashReplenished",
]
