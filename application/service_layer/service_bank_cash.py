# service_bank_cash.py - Complete rewrite with full event publishing

#!/usr/bin/env python3

"""
Module: service_bank_cash.py

Layer: 8 - Application / Service Layer

Responsibility:
    Service layer for Bank and Cash Management.
    Mempublikasikan semua domain events yang sesuai.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from domain.bank_cash.bank_account_entity import BankAccount, BankAccountStatus, BankAccountType
from domain.bank_cash.bank_aggregate_root import BankAggregate
from domain.bank_cash.bank_reconciliation_engine import BankReconciliationEngine
from domain.bank_cash.bank_transaction_entity import (
    BankTransaction,
    TransactionStatus,
    TransactionType,
)
from domain.bank_cash.bank_transfer_entity import BankTransfer, TransferStatus
from domain.bank_cash.cash_book_entity import CashBook
from domain.bank_cash.cash_disbursement_entity import CashDisbursementEntity as CashDisbursement
from domain.bank_cash.cash_receipt_entity import CashReceiptEntity as CashReceipt
from domain.bank_cash.domain_events import (
    BankAccountBlockedEvent,
    BankAccountClosedEvent,
    BankAccountCreatedEvent,
    BankAccountUpdatedEvent,
    BankReconciliationCompletedEvent,
    BankTransactionClearedEvent,
    BankTransactionRecordedEvent,
    BankTransferCancelledEvent,
    BankTransferCompletedEvent,
    BankTransferExecutedEvent,
    BankTransferFailedEvent,
    BankTransferInitiatedEvent,
    CashBookClosedEvent,
    CashBookUpdatedEvent,
    CashDisbursementApprovedEvent,
    CashDisbursementCancelledEvent,
    CashDisbursementIssuedEvent,
    CashDisbursementPaidEvent,
    CashReceiptCancelledEvent,
    CashReceiptConfirmedEvent,
    CashReceiptIssuedEvent,
    PettyCashActivatedEvent,
    PettyCashAdjustedEvent,
    PettyCashClosedEvent,
    PettyCashDisbursementEvent,
    PettyCashFundCreatedEvent,
    PettyCashReplenishedEvent,
    PettyCashSuspendedEvent,
)
from domain.bank_cash.invariants import BankCashInvariantsValidator
from domain.bank_cash.petty_cash_fund_entity import PettyCashFundEntity as PettyCashFund
from domain.shared_value_objects.currency_vo import Currency
from ports.primary.bank_cash_repository_port import BankCashRepositoryPort
from ports.primary.event_publisher_port import EventPublisherPort
from ports.primary.ledger_repository_port import LedgerRepositoryPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

logger = logging.getLogger(__name__)


# ============================================================================
# DTOs
# ============================================================================


@dataclass(kw_only=True)
class CreateBankAccountRequest:
    legal_entity_id: UUID
    account_name: str
    account_number: str
    bank_name: str
    bank_code: str
    branch: str | None = None
    currency_code: str = "IDR"
    account_type: str = "CHECKING"
    opening_balance: Decimal = Decimal("0")
    reconciliation_date: date | None = None


@dataclass(kw_only=True)
class UpdateBankAccountRequest:
    account_name: str | None = None
    branch: str | None = None
    status: str | None = None


@dataclass(kw_only=True)
class BankAccountResponse:
    id: UUID
    account_name: str
    account_number: str
    bank_name: str
    currency_code: str
    current_balance: Decimal
    available_balance: Decimal
    last_reconciliation_date: date | None
    status: str | None = None
    is_locked: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(kw_only=True)
class BankTransactionRequest:
    legal_entity_id: UUID
    bank_account_id: UUID
    transaction_date: date
    amount: Decimal
    description: str
    transaction_type: str | None = None
    reference_number: str | None = None
    counterparty_name: str | None = None
    counterparty_account: str | None = None


@dataclass(kw_only=True)
class BankTransactionResponse:
    id: UUID
    bank_account_id: UUID
    transaction_date: date
    amount: Decimal
    description: str
    reference_number: str | None
    is_reconciled: bool
    transaction_type: str | None = None
    status: str | None = None


@dataclass(kw_only=True)
class BankReconciliationRequest:
    bank_account_id: UUID
    statement_date: date
    statement_ending_balance: Decimal
    user_id: UUID
    statement_transactions: list[dict[str, Any]]


@dataclass(kw_only=True)
class BankReconciliationResponse:
    reconciliation_id: UUID
    bank_account_id: UUID
    statement_date: date
    system_balance: Decimal
    statement_balance: Decimal
    difference: Decimal
    is_matched: bool
    matched_count: int
    unmatched_system_ids: list[UUID]
    unmatched_statement_refs: list[str]


@dataclass(kw_only=True)
class CashReceiptRequest:
    legal_entity_id: UUID
    cash_book_id: UUID
    receipt_date: date
    amount: Decimal
    from_party: str
    description: str
    ar_invoice_id: UUID | None = None
    payment_method: str = "CASH"


@dataclass(kw_only=True)
class CashDisbursementRequest:
    legal_entity_id: UUID
    cash_book_id: UUID
    disbursement_date: date
    amount: Decimal
    to_party: str
    description: str
    ap_invoice_id: UUID | None = None
    payment_method: str = "CASH"


@dataclass(kw_only=True)
class PettyCashRequest:
    legal_entity_id: UUID
    fund_name: str
    initial_amount: Decimal
    custodian_id: UUID
    currency_code: str = "IDR"


@dataclass(kw_only=True)
class PettyCashAdjustmentRequest:
    fund_id: UUID
    amount: Decimal
    reason: str
    user_id: UUID


@dataclass(kw_only=True)
class PettyCashDisbursementRequest:
    fund_id: UUID
    amount: Decimal
    date: date
    description: str
    recipient: str
    user_id: UUID


# ============================================================================
# Exceptions
# ============================================================================


class BankCashServiceError(Exception):
    pass


class BankAccountNotFoundError(BankCashServiceError):
    pass


class BankTransactionNotFoundError(BankCashServiceError):
    pass


class InsufficientFundsError(BankCashServiceError):
    pass


class ReconciliationError(BankCashServiceError):
    pass


class PettyCashFundError(BankCashServiceError):
    pass


class CashBookNotFoundError(BankCashServiceError):
    pass


class BankAccountBlockedError(BankCashServiceError):
    pass


class BankAccountClosedError(BankCashServiceError):
    pass


# ============================================================================
# Main Service
# ============================================================================


class BankCashService:
    """
    Service untuk manajemen bank dan kas.
    Mempublikasikan event untuk setiap operasi.
    """

    def __init__(
        self,
        bank_repo: BankCashRepositoryPort,
        ledger_repo: LedgerRepositoryPort | None = None,
        uow: UnitOfWorkPort | None = None,
        event_publisher: EventPublisherPort | None = None,
    ):
        self._bank_repo = bank_repo
        self._ledger_repo = ledger_repo
        self._uow = uow
        self._event_publisher = event_publisher
        self._validator = BankCashInvariantsValidator()
        self._reconciliation_engine = BankReconciliationEngine()
        self._stats = {
            "accounts_created": 0,
            "accounts_updated": 0,
            "accounts_blocked": 0,
            "accounts_closed": 0,
            "transactions": 0,
            "reconciliations": 0,
            "cash_receipts": 0,
            "cash_disbursements": 0,
            "petty_cash_funds": 0,
        }

        logger.info("BankCashService initialized")

    # ========================================================================
    # Bank Account Management
    # ========================================================================

    async def create_bank_account(
        self, request: CreateBankAccountRequest, user_id: UUID, correlation_id: str | None = None
    ) -> BankAccountResponse:
        """Create a new bank account."""
        existing = await self._bank_repo.find_account_by_number(
            request.legal_entity_id, request.account_number
        )
        if existing:
            raise BankCashServiceError(
                f"Bank account {request.account_number} already exists"
            )

        bank_account = BankAccount(
            id=uuid4(),
            legal_entity_id=request.legal_entity_id,
            account_name=request.account_name,
            account_number=request.account_number,
            bank_name=request.bank_name,
            bank_code=request.bank_code,
            branch=request.branch,
            currency=Currency(request.currency_code),
            account_type=BankAccountType(request.account_type),
            current_balance=request.opening_balance,
            available_balance=request.opening_balance,
            status=BankAccountStatus.ACTIVE,
            opening_balance=request.opening_balance,
            last_reconciliation_date=request.reconciliation_date,
            is_locked=False,
            created_by=user_id,
            created_at=datetime.now(UTC),
            updated_at=None,
        )

        aggregate = BankAggregate(bank_account=bank_account, version=0)
        aggregate.create(user_id)

        await self._bank_repo.save_bank_account(aggregate)
        if self._uow:
            await self._uow.commit()

        self._stats["accounts_created"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = BankAccountCreatedEvent(
                aggregate_id=bank_account.id,
                aggregate_version=1,
                legal_entity_id=bank_account.legal_entity_id,
                account_number=bank_account.account_number,
                bank_name=bank_account.bank_name,
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published BankAccountCreatedEvent for {bank_account.account_number}")

        logger.info(
            "Bank account created: %s - %s",
            bank_account.bank_name,
            bank_account.account_number
        )
        return self._to_bank_account_response(bank_account)

    async def update_bank_account(
        self,
        account_id: UUID,
        request: UpdateBankAccountRequest,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> BankAccountResponse:
        """Update bank account details."""
        agg = await self._bank_repo.get_bank_account_by_id(account_id)
        if not agg:
            raise BankAccountNotFoundError(f"Bank account {account_id} not found")

        bank_account = agg.bank_account
        changes = {}

        if request.account_name and request.account_name != bank_account.account_name:
            changes["account_name"] = {"old": bank_account.account_name, "new": request.account_name}
            bank_account.account_name = request.account_name

        if request.branch is not None and request.branch != bank_account.branch:
            changes["branch"] = {"old": bank_account.branch, "new": request.branch}
            bank_account.branch = request.branch

        if request.status:
            new_status = BankAccountStatus(request.status)
            if new_status != bank_account.status and new_status == BankAccountStatus.ACTIVE:
                bank_account.status = new_status

        if not changes:
            return self._to_bank_account_response(bank_account)

        bank_account.updated_at = datetime.now(UTC)
        bank_account.updated_by = user_id

        await self._bank_repo.save_bank_account(agg)
        if self._uow:
            await self._uow.commit()

        self._stats["accounts_updated"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = BankAccountUpdatedEvent(
                aggregate_id=bank_account.id,
                aggregate_version=agg.version,
                account_number=bank_account.account_number,
                changes=changes,
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published BankAccountUpdatedEvent for {bank_account.account_number}")

        return self._to_bank_account_response(bank_account)

    async def block_bank_account(
        self,
        account_id: UUID,
        reason: str,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> BankAccountResponse:
        """Block a bank account."""
        agg = await self._bank_repo.get_bank_account_by_id(account_id)
        if not agg:
            raise BankAccountNotFoundError(f"Bank account {account_id} not found")

        bank_account = agg.bank_account
        if bank_account.status == BankAccountStatus.CLOSED:
            raise BankAccountClosedError("Cannot block a closed account")

        bank_account.is_locked = True
        bank_account.locked_at = datetime.now(UTC)
        bank_account.locked_by = user_id
        bank_account.lock_reason = reason
        bank_account.status = BankAccountStatus.BLOCKED
        bank_account.updated_at = datetime.now(UTC)

        await self._bank_repo.save_bank_account(agg)
        if self._uow:
            await self._uow.commit()

        self._stats["accounts_blocked"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = BankAccountBlockedEvent(
                aggregate_id=bank_account.id,
                aggregate_version=agg.version,
                account_number=bank_account.account_number,
                reason=reason,
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published BankAccountBlockedEvent for {bank_account.account_number}")

        return self._to_bank_account_response(bank_account)

    async def close_bank_account(
        self,
        account_id: UUID,
        reason: str,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> BankAccountResponse:
        """Close a bank account."""
        agg = await self._bank_repo.get_bank_account_by_id(account_id)
        if not agg:
            raise BankAccountNotFoundError(f"Bank account {account_id} not found")

        bank_account = agg.bank_account
        if bank_account.current_balance != 0:
            raise BankCashServiceError(
                f"Cannot close account with balance {bank_account.current_balance}"
            )

        bank_account.status = BankAccountStatus.CLOSED
        bank_account.closed_at = datetime.now(UTC)
        bank_account.closed_by = user_id
        bank_account.close_reason = reason
        bank_account.updated_at = datetime.now(UTC)

        await self._bank_repo.save_bank_account(agg)
        if self._uow:
            await self._uow.commit()

        self._stats["accounts_closed"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = BankAccountClosedEvent(
                aggregate_id=bank_account.id,
                aggregate_version=agg.version,
                account_number=bank_account.account_number,
                reason=reason,
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published BankAccountClosedEvent for {bank_account.account_number}")

        return self._to_bank_account_response(bank_account)

    async def get_bank_account(self, account_id: UUID) -> BankAccountResponse:
        agg = await self._bank_repo.get_bank_account_by_id(account_id)
        if not agg:
            raise BankAccountNotFoundError(f"Bank account {account_id} not found")
        return self._to_bank_account_response(agg.bank_account)

    async def list_bank_accounts(
        self,
        legal_entity_id: UUID,
        status: str | None = None,
        currency: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[BankAccountResponse]:
        accounts = await self._bank_repo.list_bank_accounts(
            legal_entity_id=legal_entity_id,
            status=status,
            currency=currency,
            limit=limit,
            offset=offset,
        )
        return [self._to_bank_account_response(acc) for acc in accounts]

    # ========================================================================
    # Bank Transactions
    # ========================================================================

    async def record_transaction(
        self, request: BankTransactionRequest, user_id: UUID, correlation_id: str | None = None
    ) -> BankTransactionResponse:
        """Record a bank transaction."""
        bank_agg = await self._bank_repo.get_bank_account_by_id(request.bank_account_id)
        if not bank_agg:
            raise BankAccountNotFoundError(
                f"Bank account {request.bank_account_id} not found"
            )

        bank_account = bank_agg.bank_account
        if bank_account.status != BankAccountStatus.ACTIVE:
            raise BankCashServiceError("Bank account is not active")

        if bank_account.is_locked:
            raise BankAccountBlockedError("Bank account is locked")

        tx_type = (
            TransactionType(request.transaction_type)
            if request.transaction_type
            else TransactionType.DEPOSIT
        )
        if tx_type in (
            TransactionType.WITHDRAWAL,
            TransactionType.TRANSFER_OUT,
            TransactionType.FEE,
        ):
            if bank_account.available_balance < request.amount:
                raise InsufficientFundsError(
                    f"Insufficient funds: balance={bank_account.available_balance}, requested={request.amount}"
                )

        transaction = BankTransaction(
            id=uuid4(),
            legal_entity_id=request.legal_entity_id,
            bank_account_id=request.bank_account_id,
            transaction_date=request.transaction_date,
            amount=request.amount,
            transaction_type=tx_type,
            description=request.description,
            reference_number=request.reference_number,
            counterparty_name=request.counterparty_name,
            counterparty_account=request.counterparty_account,
            status=TransactionStatus.PENDING,
            is_reconciled=False,
            created_by=user_id,
            created_at=datetime.now(UTC),
            reconciled_at=None,
        )

        if tx_type.is_inflow():
            new_balance = bank_account.current_balance + request.amount
        else:
            new_balance = bank_account.current_balance - request.amount

        bank_account.current_balance = new_balance
        bank_account.available_balance = new_balance
        bank_account.updated_at = datetime.now(UTC)
        transaction.status = TransactionStatus.COMPLETED

        await self._bank_repo.save_bank_account(bank_agg)
        await self._bank_repo.save_transaction(transaction)
        if self._uow:
            await self._uow.commit()

        self._stats["transactions"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = BankTransactionRecordedEvent(
                aggregate_id=transaction.id,
                aggregate_version=1,
                bank_account_id=request.bank_account_id,
                amount=request.amount,
                transaction_type=tx_type.value,
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published BankTransactionRecordedEvent for {request.amount}")

        logger.info(
            "Bank transaction recorded: %s %s",
            tx_type.value,
            request.amount
        )
        return self._to_transaction_response(transaction)

    async def get_transactions(
        self,
        bank_account_id: UUID,
        from_date: date | None = None,
        to_date: date | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[BankTransactionResponse]:
        transactions = await self._bank_repo.list_transactions(
            bank_account_id=bank_account_id,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
            offset=offset,
        )
        return [self._to_transaction_response(tx) for tx in transactions]

    # ========================================================================
    # Bank Reconciliation
    # ========================================================================

    async def reconcile_bank_account(
        self, request: BankReconciliationRequest, correlation_id: str | None = None
    ) -> BankReconciliationResponse:
        """Reconcile bank account with statement."""
        self._stats["reconciliations"] += 1

        bank_agg = await self._bank_repo.get_bank_account_by_id(request.bank_account_id)
        if not bank_agg:
            raise BankAccountNotFoundError(
                f"Bank account {request.bank_account_id} not found"
            )

        bank_account = bank_agg.bank_account
        system_balance = bank_account.current_balance

        transactions = await self._bank_repo.list_unreconciled_transactions(
            request.bank_account_id, request.statement_date
        )

        result = self._reconciliation_engine.match(
            system_transactions=transactions,
            statement_transactions=request.statement_transactions,
            system_balance=system_balance,
            statement_balance=request.statement_ending_balance,
        )

        matched_ids = []
        for tx in transactions:
            if tx.id in result.matched_system_ids:
                tx.is_reconciled = True
                tx.reconciled_at = datetime.now(UTC)
                matched_ids.append(tx.id)
                await self._bank_repo.save_transaction(tx)

        # Publish cleared events for matched transactions
        if self._event_publisher:
            for tx_id in matched_ids:
                event = BankTransactionClearedEvent(
                    aggregate_id=tx_id,
                    aggregate_version=1,
                    bank_account_id=request.bank_account_id,
                    user_id=request.user_id,
                    occurred_at=datetime.now(UTC),
                )
                await self._event_publisher.publish(event, correlation_id=correlation_id)

        bank_account.last_reconciliation_date = request.statement_date
        bank_account.updated_at = datetime.now(UTC)
        await self._bank_repo.save_bank_account(bank_agg)

        reconciliation_id = uuid4()
        await self._bank_repo.save_reconciliation(
            id=reconciliation_id,
            bank_account_id=request.bank_account_id,
            statement_date=request.statement_date,
            statement_balance=request.statement_ending_balance,
            system_balance=system_balance,
            difference=result.difference,
            is_matched=result.is_matched,
            matched_count=result.matched_count,
            reconciliation_date=datetime.now(UTC),
            reconciled_by=request.user_id,
        )

        if self._uow:
            await self._uow.commit()

        if self._event_publisher:
            event = BankReconciliationCompletedEvent(
                aggregate_id=reconciliation_id,
                aggregate_version=1,
                bank_account_id=request.bank_account_id,
                statement_date=request.statement_date,
                is_matched=result.is_matched,
                user_id=request.user_id,
                occurred_at=datetime.now(UTC),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        return BankReconciliationResponse(
            reconciliation_id=reconciliation_id,
            bank_account_id=request.bank_account_id,
            statement_date=request.statement_date,
            system_balance=system_balance,
            statement_balance=request.statement_ending_balance,
            difference=result.difference,
            is_matched=result.is_matched,
            matched_count=result.matched_count,
            unmatched_system_ids=result.unmatched_system_ids,
            unmatched_statement_refs=result.unmatched_statement_refs,
        )

    # ========================================================================
    # Bank Transfer
    # ========================================================================

    async def transfer_between_accounts(
        self,
        from_account_id: UUID,
        to_account_id: UUID,
        amount: Decimal,
        transfer_date: date,
        description: str,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> BankTransfer:
        """Transfer money between two bank accounts."""
        from_agg = await self._bank_repo.get_bank_account_by_id(from_account_id)
        if not from_agg:
            raise BankAccountNotFoundError(
                f"From account {from_account_id} not found"
            )
        to_agg = await self._bank_repo.get_bank_account_by_id(to_account_id)
        if not to_agg:
            raise BankAccountNotFoundError(
                f"To account {to_account_id} not found"
            )

        if from_agg.bank_account.is_locked:
            raise BankAccountBlockedError("From account is locked")
        if to_agg.bank_account.is_locked:
            raise BankAccountBlockedError("To account is locked")

        if from_agg.bank_account.available_balance < amount:
            raise InsufficientFundsError("Insufficient funds in from account")

        transfer_id = uuid4()

        # --- PUBLISH INITIATED EVENT ---
        if self._event_publisher:
            event_init = BankTransferInitiatedEvent(
                aggregate_id=transfer_id,
                aggregate_version=1,
                from_account_id=from_account_id,
                to_account_id=to_account_id,
                amount=amount,
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
            await self._event_publisher.publish(event_init, correlation_id=correlation_id)

        try:
            transfer = BankTransfer(
                id=transfer_id,
                legal_entity_id=from_agg.bank_account.legal_entity_id,
                from_account_id=from_account_id,
                to_account_id=to_account_id,
                amount=amount,
                transfer_date=transfer_date,
                description=description,
                status=TransferStatus.COMPLETED,
                created_by=user_id,
                created_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
            )

            from_agg.bank_account.current_balance -= amount
            from_agg.bank_account.available_balance -= amount
            to_agg.bank_account.current_balance += amount
            to_agg.bank_account.available_balance += amount

            await self._bank_repo.save_bank_account(from_agg)
            await self._bank_repo.save_bank_account(to_agg)
            await self._bank_repo.save_transfer(transfer)
            if self._uow:
                await self._uow.commit()

            # --- PUBLISH COMPLETED EVENT ---
            if self._event_publisher:
                event_complete = BankTransferCompletedEvent(
                    aggregate_id=transfer_id,
                    aggregate_version=1,
                    from_account_id=from_account_id,
                    to_account_id=to_account_id,
                    amount=amount,
                    user_id=user_id,
                    occurred_at=datetime.now(UTC),
                )
                await self._event_publisher.publish(event_complete, correlation_id=correlation_id)

            logger.info(
                "Transfer %s from %s to %s completed",
                amount,
                from_account_id,
                to_account_id
            )
            return transfer

        except Exception as e:
            # --- PUBLISH FAILED EVENT ---
            if self._event_publisher:
                event_fail = BankTransferFailedEvent(
                    aggregate_id=transfer_id,
                    aggregate_version=1,
                    from_account_id=from_account_id,
                    to_account_id=to_account_id,
                    amount=amount,
                    reason=str(e),
                    user_id=user_id,
                    occurred_at=datetime.now(UTC),
                )
                await self._event_publisher.publish(event_fail, correlation_id=correlation_id)
            raise

    async def cancel_bank_transfer(
        self,
        transfer_id: UUID,
        reason: str,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> None:
        """Cancel a pending bank transfer."""
        transfer = await self._bank_repo.get_transfer_by_id(transfer_id)
        if not transfer:
            raise BankCashServiceError(f"Transfer {transfer_id} not found")

        if transfer.status != TransferStatus.PENDING:
            raise BankCashServiceError(f"Cannot cancel transfer in status {transfer.status.value}")

        transfer.status = TransferStatus.CANCELLED
        transfer.cancelled_at = datetime.now(UTC)
        transfer.cancelled_by = user_id
        transfer.cancel_reason = reason

        await self._bank_repo.save_transfer(transfer)
        if self._uow:
            await self._uow.commit()

        # --- PUBLISH CANCELLED EVENT ---
        if self._event_publisher:
            event = BankTransferCancelledEvent(
                aggregate_id=transfer_id,
                aggregate_version=1,
                from_account_id=transfer.from_account_id,
                to_account_id=transfer.to_account_id,
                amount=transfer.amount,
                reason=reason,
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published BankTransferCancelledEvent for {transfer_id}")

    # ========================================================================
    # Cash Management
    # ========================================================================

    async def create_cash_book(
        self,
        legal_entity_id: UUID,
        name: str,
        currency_code: str = "IDR",
        opening_balance: Decimal = Decimal("0"),
        user_id: UUID | None = None,
    ) -> CashBook:
        cash_book = CashBook(
            id=uuid4(),
            legal_entity_id=legal_entity_id,
            name=name,
            currency=Currency(currency_code),
            current_balance=opening_balance,
            opening_balance=opening_balance,
            created_by=user_id,
            created_at=datetime.now(UTC),
            updated_at=None,
        )
        await self._bank_repo.save_cash_book(cash_book)
        if self._uow:
            await self._uow.commit()
        return cash_book

    async def update_cash_book(
        self,
        cash_book_id: UUID,
        name: str | None = None,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> CashBook:
        cash_book = await self._bank_repo.get_cash_book_by_id(cash_book_id)
        if not cash_book:
            raise CashBookNotFoundError(f"Cash book {cash_book_id} not found")

        if name:
            cash_book.name = name
        cash_book.updated_at = datetime.now(UTC)
        cash_book.updated_by = user_id

        await self._bank_repo.save_cash_book(cash_book)
        if self._uow:
            await self._uow.commit()

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = CashBookUpdatedEvent(
                aggregate_id=cash_book_id,
                aggregate_version=1,
                cash_book_id=cash_book_id,
                changes={"name": name} if name else {},
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published CashBookUpdatedEvent for {cash_book_id}")

        return cash_book

    async def close_cash_book(
        self,
        cash_book_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> CashBook:
        cash_book = await self._bank_repo.get_cash_book_by_id(cash_book_id)
        if not cash_book:
            raise CashBookNotFoundError(f"Cash book {cash_book_id} not found")

        if cash_book.current_balance != 0:
            raise BankCashServiceError(
                f"Cannot close cash book with balance {cash_book.current_balance}"
            )

        cash_book.is_closed = True
        cash_book.closed_at = datetime.now(UTC)
        cash_book.closed_by = user_id
        cash_book.updated_at = datetime.now(UTC)

        await self._bank_repo.save_cash_book(cash_book)
        if self._uow:
            await self._uow.commit()

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = CashBookClosedEvent(
                aggregate_id=cash_book_id,
                aggregate_version=1,
                cash_book_id=cash_book_id,
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published CashBookClosedEvent for {cash_book_id}")

        return cash_book

    async def record_cash_receipt(
        self, request: CashReceiptRequest, user_id: UUID, correlation_id: str | None = None
    ) -> CashReceipt:
        cash_book = await self._bank_repo.get_cash_book_by_id(request.cash_book_id)
        if not cash_book:
            raise CashBookNotFoundError(
                f"Cash book {request.cash_book_id} not found"
            )

        receipt = CashReceipt(
            id=uuid4(),
            legal_entity_id=request.legal_entity_id,
            cash_book_id=request.cash_book_id,
            receipt_date=request.receipt_date,
            amount=request.amount,
            from_party=request.from_party,
            description=request.description,
            ar_invoice_id=request.ar_invoice_id,
            payment_method=request.payment_method,
            status="PENDING",
            created_by=user_id,
            created_at=datetime.now(UTC),
        )

        cash_book.current_balance += request.amount
        cash_book.updated_at = datetime.now(UTC)

        await self._bank_repo.save_cash_book(cash_book)
        await self._bank_repo.save_cash_receipt(receipt)
        if self._uow:
            await self._uow.commit()

        self._stats["cash_receipts"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = CashReceiptIssuedEvent(
                aggregate_id=receipt.id,
                aggregate_version=1,
                cash_book_id=request.cash_book_id,
                amount=request.amount,
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published CashReceiptIssuedEvent for {request.amount}")

        return receipt

    async def confirm_cash_receipt(
        self,
        receipt_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> CashReceipt:
        receipt = await self._bank_repo.get_cash_receipt_by_id(receipt_id)
        if not receipt:
            raise BankCashServiceError(f"Cash receipt {receipt_id} not found")

        receipt.status = "CONFIRMED"
        receipt.confirmed_at = datetime.now(UTC)
        receipt.confirmed_by = user_id

        await self._bank_repo.save_cash_receipt(receipt)
        if self._uow:
            await self._uow.commit()

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = CashReceiptConfirmedEvent(
                aggregate_id=receipt_id,
                aggregate_version=1,
                cash_book_id=receipt.cash_book_id,
                amount=receipt.amount,
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published CashReceiptConfirmedEvent for {receipt_id}")

        return receipt

    async def cancel_cash_receipt(
        self,
        receipt_id: UUID,
        reason: str,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> CashReceipt:
        receipt = await self._bank_repo.get_cash_receipt_by_id(receipt_id)
        if not receipt:
            raise BankCashServiceError(f"Cash receipt {receipt_id} not found")

        if receipt.status == "CONFIRMED":
            # Reverse the balance
            cash_book = await self._bank_repo.get_cash_book_by_id(receipt.cash_book_id)
            if cash_book:
                cash_book.current_balance -= receipt.amount
                cash_book.updated_at = datetime.now(UTC)
                await self._bank_repo.save_cash_book(cash_book)

        receipt.status = "CANCELLED"
        receipt.cancel_reason = reason
        receipt.cancelled_at = datetime.now(UTC)
        receipt.cancelled_by = user_id

        await self._bank_repo.save_cash_receipt(receipt)
        if self._uow:
            await self._uow.commit()

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = CashReceiptCancelledEvent(
                aggregate_id=receipt_id,
                aggregate_version=1,
                cash_book_id=receipt.cash_book_id,
                amount=receipt.amount,
                reason=reason,
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published CashReceiptCancelledEvent for {receipt_id}")

        return receipt

    async def record_cash_disbursement(
        self, request: CashDisbursementRequest, user_id: UUID, correlation_id: str | None = None
    ) -> CashDisbursement:
        cash_book = await self._bank_repo.get_cash_book_by_id(request.cash_book_id)
        if not cash_book:
            raise CashBookNotFoundError(
                f"Cash book {request.cash_book_id} not found"
            )

        if cash_book.current_balance < request.amount:
            raise InsufficientFundsError(
                f"Insufficient cash balance: {cash_book.current_balance}"
            )

        disbursement = CashDisbursement(
            id=uuid4(),
            legal_entity_id=request.legal_entity_id,
            cash_book_id=request.cash_book_id,
            disbursement_date=request.disbursement_date,
            amount=request.amount,
            to_party=request.to_party,
            description=request.description,
            ap_invoice_id=request.ap_invoice_id,
            payment_method=request.payment_method,
            status="PENDING",
            created_by=user_id,
            created_at=datetime.now(UTC),
        )

        cash_book.current_balance -= request.amount
        cash_book.updated_at = datetime.now(UTC)

        await self._bank_repo.save_cash_book(cash_book)
        await self._bank_repo.save_cash_disbursement(disbursement)
        if self._uow:
            await self._uow.commit()

        self._stats["cash_disbursements"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = CashDisbursementIssuedEvent(
                aggregate_id=disbursement.id,
                aggregate_version=1,
                cash_book_id=request.cash_book_id,
                amount=request.amount,
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published CashDisbursementIssuedEvent for {request.amount}")

        return disbursement

    async def approve_cash_disbursement(
        self,
        disbursement_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> CashDisbursement:
        disbursement = await self._bank_repo.get_cash_disbursement_by_id(disbursement_id)
        if not disbursement:
            raise BankCashServiceError(f"Cash disbursement {disbursement_id} not found")

        disbursement.status = "APPROVED"
        disbursement.approved_at = datetime.now(UTC)
        disbursement.approved_by = user_id

        await self._bank_repo.save_cash_disbursement(disbursement)
        if self._uow:
            await self._uow.commit()

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = CashDisbursementApprovedEvent(
                aggregate_id=disbursement_id,
                aggregate_version=1,
                cash_book_id=disbursement.cash_book_id,
                amount=disbursement.amount,
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published CashDisbursementApprovedEvent for {disbursement_id}")

        return disbursement

    async def pay_cash_disbursement(
        self,
        disbursement_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> CashDisbursement:
        disbursement = await self._bank_repo.get_cash_disbursement_by_id(disbursement_id)
        if not disbursement:
            raise BankCashServiceError(f"Cash disbursement {disbursement_id} not found")

        disbursement.status = "PAID"
        disbursement.paid_at = datetime.now(UTC)
        disbursement.paid_by = user_id

        await self._bank_repo.save_cash_disbursement(disbursement)
        if self._uow:
            await self._uow.commit()

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = CashDisbursementPaidEvent(
                aggregate_id=disbursement_id,
                aggregate_version=1,
                cash_book_id=disbursement.cash_book_id,
                amount=disbursement.amount,
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published CashDisbursementPaidEvent for {disbursement_id}")

        return disbursement

    async def cancel_cash_disbursement(
        self,
        disbursement_id: UUID,
        reason: str,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> CashDisbursement:
        disbursement = await self._bank_repo.get_cash_disbursement_by_id(disbursement_id)
        if not disbursement:
            raise BankCashServiceError(f"Cash disbursement {disbursement_id} not found")

        if disbursement.status in ("PAID", "APPROVED"):
            # Reverse the balance if already paid
            cash_book = await self._bank_repo.get_cash_book_by_id(disbursement.cash_book_id)
            if cash_book and disbursement.status == "PAID":
                cash_book.current_balance += disbursement.amount
                cash_book.updated_at = datetime.now(UTC)
                await self._bank_repo.save_cash_book(cash_book)

        disbursement.status = "CANCELLED"
        disbursement.cancel_reason = reason
        disbursement.cancelled_at = datetime.now(UTC)
        disbursement.cancelled_by = user_id

        await self._bank_repo.save_cash_disbursement(disbursement)
        if self._uow:
            await self._uow.commit()

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = CashDisbursementCancelledEvent(
                aggregate_id=disbursement_id,
                aggregate_version=1,
                cash_book_id=disbursement.cash_book_id,
                amount=disbursement.amount,
                reason=reason,
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published CashDisbursementCancelledEvent for {disbursement_id}")

        return disbursement

    # ========================================================================
    # Petty Cash Fund
    # ========================================================================

    async def create_petty_cash_fund(
        self, request: PettyCashRequest, user_id: UUID, correlation_id: str | None = None
    ) -> PettyCashFund:
        fund = PettyCashFund(
            id=uuid4(),
            legal_entity_id=request.legal_entity_id,
            fund_name=request.fund_name,
            initial_amount=request.initial_amount,
            current_balance=request.initial_amount,
            custodian_id=request.custodian_id,
            currency=Currency(request.currency_code),
            is_active=True,
            is_closed=False,
            created_by=user_id,
            created_at=datetime.now(UTC),
            last_replenishment_date=None,
        )
        await self._bank_repo.save_petty_cash_fund(fund)
        if self._uow:
            await self._uow.commit()

        self._stats["petty_cash_funds"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = PettyCashFundCreatedEvent(
                aggregate_id=fund.id,
                aggregate_version=1,
                fund_name=request.fund_name,
                initial_amount=request.initial_amount,
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published PettyCashFundCreatedEvent for {request.fund_name}")

        return fund

    async def adjust_petty_cash(
        self,
        request: PettyCashAdjustmentRequest,
        correlation_id: str | None = None,
    ) -> PettyCashFund:
        fund = await self._bank_repo.get_petty_cash_fund_by_id(request.fund_id)
        if not fund:
            raise PettyCashFundError(f"Petty cash fund {request.fund_id} not found")

        old_balance = fund.current_balance
        fund.current_balance += request.amount
        fund.updated_at = datetime.now(UTC)
        fund.updated_by = request.user_id

        await self._bank_repo.save_petty_cash_fund(fund)
        if self._uow:
            await self._uow.commit()

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = PettyCashAdjustedEvent(
                aggregate_id=request.fund_id,
                aggregate_version=fund.version + 1,
                amount=request.amount,
                old_balance=old_balance,
                new_balance=fund.current_balance,
                reason=request.reason,
                user_id=request.user_id,
                occurred_at=datetime.now(UTC),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published PettyCashAdjustedEvent for {request.fund_id}")

        return fund

    async def activate_petty_cash(
        self,
        fund_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> PettyCashFund:
        fund = await self._bank_repo.get_petty_cash_fund_by_id(fund_id)
        if not fund:
            raise PettyCashFundError(f"Petty cash fund {fund_id} not found")

        fund.is_active = True
        fund.activated_at = datetime.now(UTC)
        fund.activated_by = user_id
        fund.updated_at = datetime.now(UTC)

        await self._bank_repo.save_petty_cash_fund(fund)
        if self._uow:
            await self._uow.commit()

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = PettyCashActivatedEvent(
                aggregate_id=fund_id,
                aggregate_version=fund.version + 1,
                fund_name=fund.fund_name,
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published PettyCashActivatedEvent for {fund_id}")

        return fund

    async def close_petty_cash(
        self,
        fund_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> PettyCashFund:
        fund = await self._bank_repo.get_petty_cash_fund_by_id(fund_id)
        if not fund:
            raise PettyCashFundError(f"Petty cash fund {fund_id} not found")

        if fund.current_balance != 0:
            raise PettyCashFundError(
                f"Cannot close fund with balance {fund.current_balance}"
            )

        fund.is_closed = True
        fund.is_active = False
        fund.closed_at = datetime.now(UTC)
        fund.closed_by = user_id
        fund.updated_at = datetime.now(UTC)

        await self._bank_repo.save_petty_cash_fund(fund)
        if self._uow:
            await self._uow.commit()

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = PettyCashClosedEvent(
                aggregate_id=fund_id,
                aggregate_version=fund.version + 1,
                fund_name=fund.fund_name,
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published PettyCashClosedEvent for {fund_id}")

        return fund

    async def suspend_petty_cash(
        self,
        fund_id: UUID,
        reason: str,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> PettyCashFund:
        fund = await self._bank_repo.get_petty_cash_fund_by_id(fund_id)
        if not fund:
            raise PettyCashFundError(f"Petty cash fund {fund_id} not found")

        fund.is_active = False
        fund.suspend_reason = reason
        fund.suspended_at = datetime.now(UTC)
        fund.suspended_by = user_id
        fund.updated_at = datetime.now(UTC)

        await self._bank_repo.save_petty_cash_fund(fund)
        if self._uow:
            await self._uow.commit()

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = PettyCashSuspendedEvent(
                aggregate_id=fund_id,
                aggregate_version=fund.version + 1,
                fund_name=fund.fund_name,
                reason=reason,
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published PettyCashSuspendedEvent for {fund_id}")

        return fund

    async def record_petty_cash_disbursement(
        self,
        request: PettyCashDisbursementRequest,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        fund = await self._bank_repo.get_petty_cash_fund_by_id(request.fund_id)
        if not fund:
            raise PettyCashFundError(f"Petty cash fund {request.fund_id} not found")

        if not fund.is_active:
            raise PettyCashFundError("Petty cash fund is not active")

        if fund.current_balance < request.amount:
            raise InsufficientFundsError(
                f"Insufficient petty cash balance: {fund.current_balance}"
            )

        fund.current_balance -= request.amount
        fund.updated_at = datetime.now(UTC)
        fund.updated_by = request.user_id

        await self._bank_repo.save_petty_cash_fund(fund)
        if self._uow:
            await self._uow.commit()

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = PettyCashDisbursementEvent(
                aggregate_id=request.fund_id,
                aggregate_version=fund.version + 1,
                amount=request.amount,
                description=request.description,
                recipient=request.recipient,
                user_id=request.user_id,
                occurred_at=datetime.now(UTC),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published PettyCashDisbursementEvent for {request.fund_id}")

        return {
            "fund_id": request.fund_id,
            "amount": request.amount,
            "new_balance": fund.current_balance,
            "date": request.date,
            "description": request.description,
        }

    async def replenish_petty_cash(
        self,
        fund_id: UUID,
        amount: Decimal,
        bank_account_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> PettyCashFund:
        fund = await self._bank_repo.get_petty_cash_fund_by_id(fund_id)
        if not fund:
            raise PettyCashFundError(f"Petty cash fund {fund_id} not found")

        # Transfer from bank to petty cash
        await self.transfer_between_accounts(
            from_account_id=bank_account_id,
            to_account_id=None,  # Petty cash doesn't have bank account
            amount=amount,
            transfer_date=date.today(),
            description=f"Petty cash replenishment for {fund.fund_name}",
            user_id=user_id,
            correlation_id=correlation_id,
        )

        fund.current_balance += amount
        fund.last_replenishment_date = date.today()
        fund.updated_at = datetime.now(UTC)
        await self._bank_repo.save_petty_cash_fund(fund)
        if self._uow:
            await self._uow.commit()

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = PettyCashReplenishedEvent(
                aggregate_id=fund_id,
                aggregate_version=fund.version + 1,
                amount=amount,
                bank_account_id=bank_account_id,
                user_id=user_id,
                occurred_at=datetime.now(UTC),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)
            logger.debug(f"Published PettyCashReplenishedEvent for {fund_id}")

        return fund

    # ========================================================================
    # Bank Statement Import
    # ========================================================================

    async def import_bank_statement(
        self,
        bank_account_id: UUID,
        file_content: str,
        file_format: str,
        user_id: UUID,
    ) -> int:
        bank_agg = await self._bank_repo.get_bank_account_by_id(bank_account_id)
        if not bank_agg:
            raise BankAccountNotFoundError(
                f"Bank account {bank_account_id} not found"
            )

        parsed_txns = self._parse_statement(file_content, file_format)
        imported_count = 0
        for txn_data in parsed_txns:
            existing = await self._bank_repo.find_transaction_by_reference(
                bank_account_id, txn_data["reference"]
            )
            if existing:
                continue
            request = BankTransactionRequest(
                legal_entity_id=bank_agg.bank_account.legal_entity_id,
                bank_account_id=bank_account_id,
                transaction_date=txn_data["date"],
                amount=txn_data["amount"],
                transaction_type=txn_data["type"],
                description=txn_data["description"],
                reference_number=txn_data["reference"],
                counterparty_name=txn_data.get("counterparty"),
            )
            await self.record_transaction(request, user_id)
            imported_count += 1

        return imported_count

    def _parse_statement(self, content: str, format: str) -> list[dict[str, Any]]:
        if format.upper() == "CSV":
            reader = csv.DictReader(io.StringIO(content))
            transactions = []
            for row in reader:
                transactions.append(
                    {
                        "date": datetime.strptime(row["date"], "%Y-%m-%d").date(),
                        "amount": Decimal(row["amount"]),
                        "type": "DEPOSIT" if Decimal(row["amount"]) > 0 else "WITHDRAWAL",
                        "description": row.get("description", ""),
                        "reference": row.get("reference", ""),
                        "counterparty": row.get("counterparty"),
                    }
                )
            return transactions
        else:
            raise BankCashServiceError(f"Unsupported format: {format}")

    # ========================================================================
    # Private Helpers
    # ========================================================================

    def _to_bank_account_response(self, account: BankAccount) -> BankAccountResponse:
        return BankAccountResponse(
            id=account.id,
            account_name=account.account_name,
            account_number=account.account_number,
            bank_name=account.bank_name,
            currency_code=account.currency.code,
            current_balance=account.current_balance,
            available_balance=account.available_balance,
            status=account.status.value,
            is_locked=account.is_locked,
            last_reconciliation_date=account.last_reconciliation_date,
            created_at=account.created_at,
        )

    def _to_transaction_response(self, tx: BankTransaction) -> BankTransactionResponse:
        return BankTransactionResponse(
            id=tx.id,
            bank_account_id=tx.bank_account_id,
            transaction_date=tx.transaction_date,
            amount=tx.amount,
            transaction_type=tx.transaction_type.value,
            description=tx.description,
            reference_number=tx.reference_number,
            status=tx.status.value,
            is_reconciled=tx.is_reconciled,
        )

    def get_stats(self) -> dict[str, int]:
        return self._stats.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_bank_cash_service(
    bank_repo: BankCashRepositoryPort,
    ledger_repo: LedgerRepositoryPort | None = None,
    uow: UnitOfWorkPort | None = None,
    event_publisher: EventPublisherPort | None = None,
) -> BankCashService:
    return BankCashService(bank_repo, ledger_repo, uow, event_publisher)


__all__ = [
    "BankAccountNotFoundError",
    "BankCashService",
    "BankCashServiceError",
    "BankTransactionNotFoundError",
    "CashBookNotFoundError",
    "InsufficientFundsError",
    "PettyCashFundError",
    "ReconciliationError",
    "BankAccountBlockedError",
    "BankAccountClosedError",
    "create_bank_cash_service",
]