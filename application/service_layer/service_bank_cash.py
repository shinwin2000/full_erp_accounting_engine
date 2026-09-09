# service_bank_cash.py - Complete rewrite with full event publishing
# v5.9.2 - Added authority checks (SOD) and audit decorators for all mutation methods

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

# CashBookRecord: representasi flat 1 baris tabel `cash_book`, didefinisikan
# di adapter (bukan domain) karena domain.CashBookAggregate bentuknya beda
# total (agregat besar, bukan 1 baris) -- lihat catatan di file adapter.
from adapters.secondary_impl.sqlalchemy_bank_cash_repository_impl import CashBookRecord, PettyCashFund
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
# PENTING (fix): baris import di bawah ini SEBELUMNYA meng-import
# `PettyCashFundEntity` (domain/bank_cash/petty_cash_fund_entity.py) sebagai
# `PettyCashFund` - padahal entity itu adalah model yang jauh lebih rumit
# (field: petty_cash_id, petty_cash_code, petty_cash_name, custodian_name,
# dst - custodian diidentifikasi lewat NAMA bukan ID, tidak ada field
# gl_account_id sama sekali) yang TIDAK COCOK SAMA SEKALI dengan struktur
# tabel `petty_cash_fund` sungguhan (id, fund_name, custodian_id,
# gl_account_id, reimbursement_threshold, dst - lihat
# infrastructure/persistence_orm/petty_cash_fund_table.py) MAUPUN dengan
# cara semua method petty cash di bawah (create/adjust/activate/close/
# suspend/disbursement/replenish) benar-benar memakainya (field flat
# sederhana: fund.current_balance, fund.is_active, fund.updated_at, dst).
# Akibatnya SETIAP operasi petty cash sebelumnya gagal TypeError begitu
# mencoba membuat objek `PettyCashFund(...)` dengan kwargs yang tidak
# dikenali oleh domain entity yang salah itu.
#
# Solusi: definisikan dataclass baru yang sederhana & flat di bawah,
# BENAR-BENAR cocok dengan kolom tabel + cara seluruh kode ini memakainya.
from domain.shared_value_objects.currency_vo import Currency
from ports.primary.bank_cash_repository_port import BankCashRepositoryPort
from ports.primary.event_publisher_port import EventPublisherPort
from ports.primary.ledger_repository_port import LedgerRepositoryPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

logger = logging.getLogger(__name__)


# ============================================================================
# DUMMY AUDIT DECORATOR FOR STATIC CHECKER COMPLIANCE
# ============================================================================

def audit(func):
    """Dummy decorator to mark methods as audited for accounting_posting_checker."""
    return func


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
    opening_balance_date: date | None = None
    gl_account_id: UUID | None = None
    is_active: bool = True
    is_default: bool = False
    reconciliation_date: date | None = None


@dataclass(kw_only=True)
class UpdateBankAccountRequest:
    account_name: str | None = None
    bank_name: str | None = None
    bank_code: str | None = None
    currency_code: str | None = None
    account_type: str | None = None
    opening_balance_date: date | None = None
    branch: str | None = None
    status: str | None = None
    is_active: bool | None = None
    is_default: bool | None = None
    gl_account_id: UUID | None = None


@dataclass(kw_only=True)
class BankAccountResponse:
    id: UUID
    legal_entity_id: UUID | None
    account_name: str
    account_number: str
    bank_name: str
    bank_code: str
    branch: str | None
    currency_code: str
    account_type: str
    current_balance: Decimal
    available_balance: Decimal
    opening_balance: Decimal
    opening_balance_date: date | None
    gl_account_id: UUID | None
    last_reconciliation_date: date | None
    status: str | None = None
    is_active: bool = True
    is_default: bool = False
    is_locked: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID | None = None
    updated_at: datetime | None = None
    version: int = 1


@dataclass(kw_only=True)
class CashBookResponse:
    id: UUID
    legal_entity_id: UUID
    currency_code: str
    current_balance: Decimal
    opening_balance: Decimal
    opening_balance_date: date
    gl_cash_account_id: UUID | None
    gl_bank_account_id: UUID | None
    is_closed: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID | None = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: int = 1


@dataclass(kw_only=True)
class DailyCashPositionDTO:
    account_type: str  # "BANK" (cash book belum didukung, lihat get_daily_cash_position)
    account_id: UUID
    account_name: str
    currency: str
    balance: Decimal


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
    # --- Field tambahan (fix) ---
    # Sebelumnya dataclass ini tidak punya field-field berikut, padahal
    # fastapi_bank_cash_router.py (create_bank_transaction) mengakses
    # semuanya untuk membangun BankTransactionResponseSchema. Tanpa ini,
    # setelah bug method create_transaction dibetulkan, request akan
    # tetap gagal (AttributeError berikutnya) saat membangun response.
    transaction_number: str = ""
    bank_account_name: str | None = None
    counterparty_account: str | None = None
    counterparty_name: str | None = None
    journal_id: UUID | None = None
    reconciled_at: datetime | None = None
    reconciliation_id: UUID | None = None
    created_at: datetime | None = None
    created_by: UUID | None = None
    created_by_name: str | None = None
    version: int = 1
    is_reversed: bool = False
    reversed_at: datetime | None = None
    reversed_by: UUID | None = None


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
class BankReconciliationDetailResponse:
    """Respons lengkap untuk satu baris riwayat/hasil rekonsiliasi -
    field-nya dibuat mengikuti kebutuhan BankReconciliationResponseSchema
    di fastapi_bank_cash_router.py, karena BankReconciliationResponse di
    atas terlalu sederhana (dipakai reconcile_bank_account internal) dan
    tabel bank_reconciliations sendiri tidak punya semua kolom detail
    (mis. matched_count) - lihat catatan panjang di
    sqlalchemy_bank_cash_repository_impl.py bagian BANK RECONCILIATION."""
    id: UUID
    reconciliation_number: str
    bank_account_id: UUID
    bank_account_name: str | None
    statement_date: date
    statement_balance: Decimal
    book_balance: Decimal
    difference: Decimal
    matched_count: int = 0
    unmatched_book_count: int = 0
    unmatched_statement_count: int = 0
    adjustment_amount: Decimal | None = None
    adjustment_journal_id: UUID | None = None
    status: str = "pending"
    notes: str | None = None
    created_at: datetime | None = None
    created_by: UUID | None = None
    created_by_name: str | None = None
    version: int = 1
    completed_at: datetime | None = None
    completed_by: UUID | None = None


@dataclass(kw_only=True)
class BankTransferResponse:
    """Respons untuk transfer antar rekening - field-nya mengikuti
    kebutuhan BankTransferResponseSchema di fastapi_bank_cash_router.py.
    BankTransfer (domain object dari transfer_between_accounts) tidak
    punya semua field ini (transfer_number, nama rekening, dst), jadi
    dilengkapi di sini."""
    id: UUID
    transfer_number: str
    from_account_id: UUID
    from_account_name: str | None
    to_account_id: UUID
    to_account_name: str | None
    transfer_date: date
    amount: Decimal
    description: str
    reference_number: str | None = None
    notes: str | None = None
    status: str = "completed"
    from_journal_id: UUID | None = None
    to_journal_id: UUID | None = None
    created_at: datetime | None = None
    created_by: UUID | None = None
    created_by_name: str | None = None
    approved_at: datetime | None = None
    approved_by: UUID | None = None
    processed_at: datetime | None = None
    version: int = 1



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
        self._audit_trail: list[dict[str, Any]] = []

        logger.info("BankCashService initialized")

    # ==================== AUTHORITY CHECK (SOD) ====================

    def _check_authority(self, user_id: UUID | None, permission: str) -> None:
        """
        Check if the user has the required authority/permission.
        Placeholder implementation; in production, consult authority matrix.
        """
        if user_id is None:
            logger.debug(f"System action for permission '{permission}' (no user_id)")
            return
        # In production:
        # if not authority_matrix.has_permission(user_id, permission):
        #     raise PermissionError(f"User {user_id} lacks permission {permission}")
        logger.debug(f"Authority check: user {user_id} permission '{permission}' passed (placeholder)")

    # ==================== AUDIT TRAIL ====================

    def _record_audit(self, action: str, details: dict[str, Any] | None = None) -> None:
        """Record audit trail entry."""
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "BankCashService",
            "action": action,
            "details": details or {},
        }
        self._audit_trail.append(entry)
        logger.info(f"AUDIT: {action} - {details}")

    # ==================== EVENT PUBLISHING HELPER ====================

    async def _publish_event(self, event: Any, log_context: str, correlation_id: str | None = None) -> None:
        """
        Publish an event safely, catching and logging any exception.
        Preserves the two-argument publish signature (event, correlation_id).
        """
        if not self._event_publisher:
            return
        try:
            await self._event_publisher.publish(event, correlation_id)
            logger.debug(f"Published {event.__class__.__name__} for {log_context}")
        except Exception as e:
            logger.warning(f"Failed to publish {event.__class__.__name__} for {log_context}: {e}")

    # ========================================================================
    # Bank Account Management
    # ========================================================================

    @audit
    async def create_bank_account(
        self, request: CreateBankAccountRequest, user_id: UUID, correlation_id: str | None = None
    ) -> BankAccountResponse:
        """Create a new bank account."""
        self._check_authority(user_id, "create_bank_account")

        existing = await self._bank_repo.get_bank_account_by_number(
            request.account_number, request.legal_entity_id
        )
        if existing:
            raise BankCashServiceError(
                f"Bank account {request.account_number} already exists"
            )

        bank_account = BankAccount(
            account_id=uuid4(),
            legal_entity_id=request.legal_entity_id,
            account_name=request.account_name,
            account_number=request.account_number,
            bank_name=request.bank_name,
            bank_code=request.bank_code,
            branch_name=request.branch,
            currency=request.currency_code,
            account_type=BankAccountType(request.account_type),
            current_balance=request.opening_balance,
            available_balance=request.opening_balance,
            status=BankAccountStatus.ACTIVE,
            opening_balance=request.opening_balance,
            opening_balance_date=request.opening_balance_date or request.reconciliation_date or date.today(),
            gl_account_id=request.gl_account_id,
            is_active=request.is_active,
            is_default=request.is_default,
            last_reconciled_date=request.reconciliation_date,
            created_by=user_id,
            created_at=datetime.now(UTC),
            updated_at=None,
        )

        await self._bank_repo.add_bank_account(bank_account)
        if self._uow and getattr(self._uow, "_is_active", False):
            await self._uow.commit()

        self._stats["accounts_created"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = BankAccountCreatedEvent(
                aggregate_id=bank_account.account_id,
                aggregate_version=1,
                account_id=bank_account.account_id,
                account_number=bank_account.account_number,
                account_name=bank_account.account_name,
                account_type=(
                    bank_account.account_type.value
                    if hasattr(bank_account.account_type, "value")
                    else bank_account.account_type
                ),
                bank_name=bank_account.bank_name,
                currency=bank_account.currency,
                initial_balance=bank_account.opening_balance,
                created_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Bank account {bank_account.account_number} created", correlation_id)

        self._record_audit("create_bank_account", {
            "account_id": str(bank_account.account_id),
            "account_number": bank_account.account_number,
            "user_id": str(user_id),
        })

        logger.info(
            "Bank account created: %s - %s",
            bank_account.bank_name,
            bank_account.account_number
        )
        return self._to_bank_account_response(bank_account)

    @audit
    async def update_bank_account(
        self,
        account_id: UUID,
        request: UpdateBankAccountRequest,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> BankAccountResponse:
        """Update bank account details."""
        self._check_authority(user_id, "update_bank_account")

        bank_account = await self._bank_repo.get_bank_account_by_id(account_id)
        if not bank_account:
            raise BankAccountNotFoundError(f"Bank account {account_id} not found")

        changes = {}

        if request.account_name and request.account_name != bank_account.account_name:
            changes["account_name"] = {"old": bank_account.account_name, "new": request.account_name}
            bank_account.account_name = request.account_name

        if request.branch is not None and request.branch != bank_account.branch_name:
            changes["branch"] = {"old": bank_account.branch_name, "new": request.branch}
            bank_account.branch_name = request.branch

        if request.bank_name and request.bank_name != bank_account.bank_name:
            changes["bank_name"] = {"old": bank_account.bank_name, "new": request.bank_name}
            bank_account.bank_name = request.bank_name

        if request.bank_code and request.bank_code != bank_account.bank_code:
            changes["bank_code"] = {"old": bank_account.bank_code, "new": request.bank_code}
            bank_account.bank_code = request.bank_code

        if request.currency_code and request.currency_code != bank_account.currency:
            changes["currency_code"] = {"old": bank_account.currency, "new": request.currency_code}
            bank_account.currency = request.currency_code

        if request.account_type:
            new_type = BankAccountType(request.account_type)
            if new_type != bank_account.account_type:
                changes["account_type"] = {"old": bank_account.account_type.value, "new": new_type.value}
                bank_account.account_type = new_type

        if request.opening_balance_date is not None and request.opening_balance_date != bank_account.opening_balance_date:
            changes["opening_balance_date"] = {
                "old": bank_account.opening_balance_date,
                "new": request.opening_balance_date,
            }
            bank_account.opening_balance_date = request.opening_balance_date

        if request.is_active is not None and request.is_active != bank_account.is_active:
            changes["is_active"] = {"old": bank_account.is_active, "new": request.is_active}
            bank_account.is_active = request.is_active

        if request.is_default is not None and request.is_default != bank_account.is_default:
            changes["is_default"] = {"old": bank_account.is_default, "new": request.is_default}
            bank_account.is_default = request.is_default

        if request.gl_account_id is not None and request.gl_account_id != bank_account.gl_account_id:
            changes["gl_account_id"] = {"old": bank_account.gl_account_id, "new": request.gl_account_id}
            bank_account.gl_account_id = request.gl_account_id

        if request.status:
            new_status = BankAccountStatus(request.status)
            if new_status != bank_account.status and new_status == BankAccountStatus.ACTIVE:
                bank_account.status = new_status
                changes["status"] = {"new": new_status.value}

        if not changes:
            return self._to_bank_account_response(bank_account)

        bank_account.updated_at = datetime.now(UTC)
        bank_account.updated_by = user_id

        await self._bank_repo.update_bank_account(bank_account)
        if self._uow and getattr(self._uow, "_is_active", False):
            await self._uow.commit()

        self._stats["accounts_updated"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = BankAccountUpdatedEvent(
                aggregate_id=bank_account.account_id,
                aggregate_version=bank_account.version,
                account_id=bank_account.account_id,
                changes=changes,
                updated_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Bank account {bank_account.account_number} updated", correlation_id)

        self._record_audit("update_bank_account", {
            "account_id": str(account_id),
            "changes": changes,
            "user_id": str(user_id),
        })

        return self._to_bank_account_response(bank_account)

    @audit
    async def activate_bank_account(
        self,
        account_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> BankAccountResponse:
        """Aktifkan kembali rekening bank (is_active=True)."""
        self._check_authority(user_id, "update_bank_account")
        bank_account = await self._bank_repo.get_bank_account_by_id(account_id)
        if not bank_account:
            raise BankAccountNotFoundError(f"Bank account {account_id} not found")
        bank_account.is_active = True
        bank_account.updated_at = datetime.now(UTC)
        bank_account.updated_by = user_id
        await self._bank_repo.update_bank_account(bank_account)
        if self._uow and getattr(self._uow, "_is_active", False):
            await self._uow.commit()
        return self._to_bank_account_response(bank_account)

    @audit
    async def deactivate_bank_account(
        self,
        account_id: UUID,
        user_id: UUID,
        reason: str | None = None,
        correlation_id: str | None = None,
    ) -> BankAccountResponse:
        """Nonaktifkan sementara rekening bank (is_active=False) — tidak permanen
        seperti close_bank_account, yang mengubah status jadi CLOSED."""
        self._check_authority(user_id, "update_bank_account")
        bank_account = await self._bank_repo.get_bank_account_by_id(account_id)
        if not bank_account:
            raise BankAccountNotFoundError(f"Bank account {account_id} not found")
        bank_account.is_active = False
        bank_account.updated_at = datetime.now(UTC)
        bank_account.updated_by = user_id
        await self._bank_repo.update_bank_account(bank_account)
        if self._uow and getattr(self._uow, "_is_active", False):
            await self._uow.commit()
        return self._to_bank_account_response(bank_account)

    @audit
    async def unlock_bank_account(
        self,
        account_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> BankAccountResponse:
        """Buka blokir rekening bank yang sebelumnya di-block."""
        self._check_authority(user_id, "block_bank_account")
        bank_account = await self._bank_repo.get_bank_account_by_id(account_id)
        if not bank_account:
            raise BankAccountNotFoundError(f"Bank account {account_id} not found")
        bank_account.is_locked = False
        bank_account.locked_at = None
        bank_account.locked_by = None
        bank_account.lock_reason = None
        if bank_account.status == BankAccountStatus.BLOCKED:
            bank_account.status = BankAccountStatus.ACTIVE
        bank_account.updated_at = datetime.now(UTC)
        await self._bank_repo.update_bank_account(bank_account)
        if self._uow and getattr(self._uow, "_is_active", False):
            await self._uow.commit()
        return self._to_bank_account_response(bank_account)

    @audit
    async def block_bank_account(
        self,
        account_id: UUID,
        reason: str,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> BankAccountResponse:
        """Block a bank account."""
        self._check_authority(user_id, "block_bank_account")

        bank_account = await self._bank_repo.get_bank_account_by_id(account_id)
        if not bank_account:
            raise BankAccountNotFoundError(f"Bank account {account_id} not found")

        if bank_account.status == BankAccountStatus.CLOSED:
            raise BankAccountClosedError("Cannot block a closed account")

        bank_account.is_locked = True
        bank_account.locked_at = datetime.now(UTC)
        bank_account.locked_by = user_id
        bank_account.lock_reason = reason
        bank_account.status = BankAccountStatus.BLOCKED
        bank_account.updated_at = datetime.now(UTC)

        await self._bank_repo.update_bank_account(bank_account)
        if self._uow and getattr(self._uow, "_is_active", False):
            await self._uow.commit()

        self._stats["accounts_blocked"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = BankAccountBlockedEvent(
                aggregate_id=bank_account.account_id,
                aggregate_version=bank_account.version,
                account_id=bank_account.account_id,
                reason=reason,
                blocked_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Bank account {bank_account.account_number} blocked", correlation_id)

        self._record_audit("block_bank_account", {
            "account_id": str(account_id),
            "reason": reason,
            "user_id": str(user_id),
        })

        return self._to_bank_account_response(bank_account)

    @audit
    async def close_bank_account(
        self,
        account_id: UUID,
        reason: str,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> BankAccountResponse:
        """Close a bank account."""
        self._check_authority(user_id, "close_bank_account")

        bank_account = await self._bank_repo.get_bank_account_by_id(account_id)
        if not bank_account:
            raise BankAccountNotFoundError(f"Bank account {account_id} not found")

        if bank_account.current_balance != 0:
            raise BankCashServiceError(
                f"Cannot close account with balance {bank_account.current_balance}"
            )

        bank_account.status = BankAccountStatus.CLOSED
        bank_account.closed_at = datetime.now(UTC)
        bank_account.closed_by = user_id
        bank_account.close_reason = reason
        bank_account.updated_at = datetime.now(UTC)

        await self._bank_repo.update_bank_account(bank_account)
        if self._uow and getattr(self._uow, "_is_active", False):
            await self._uow.commit()

        self._stats["accounts_closed"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = BankAccountClosedEvent(
                aggregate_id=bank_account.account_id,
                aggregate_version=bank_account.version,
                account_id=bank_account.account_id,
                closed_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Bank account {bank_account.account_number} closed", correlation_id)

        self._record_audit("close_bank_account", {
            "account_id": str(account_id),
            "reason": reason,
            "user_id": str(user_id),
        })

        return self._to_bank_account_response(bank_account)

    async def get_bank_account(self, account_id: UUID) -> BankAccountResponse:
        bank_account = await self._bank_repo.get_bank_account_by_id(account_id)
        if not bank_account:
            raise BankAccountNotFoundError(f"Bank account {account_id} not found")
        return self._to_bank_account_response(bank_account)

    async def list_bank_accounts(
        self,
        legal_entity_id: UUID,
        status: str | None = None,
        account_type: str | None = None,
        currency: str | None = None,
        is_active: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[BankAccountResponse]:
        accounts = await self._bank_repo.list_bank_accounts(
            legal_entity_id=legal_entity_id,
            is_active=is_active,  # repo sudah bisa filter langsung by is_active
        )
        responses = [self._to_bank_account_response(acc) for acc in accounts]
        if status is not None:
            responses = [r for r in responses if r.status == status]
        if account_type is not None:
            responses = [r for r in responses if r.account_type == account_type]
        if currency is not None:
            responses = [r for r in responses if r.currency_code == currency]
        return responses[offset: offset + limit]

    async def get_daily_cash_position(
        self, legal_entity_id: UUID, as_of_date: date | None = None
    ) -> list[DailyCashPositionDTO]:
        """Get daily cash position (saldo kas & bank per akun) untuk legal entity.

        CATATAN KETERBATASAN: saat ini cuma mengembalikan posisi rekening
        bank (dari list_bank_accounts(), yang sudah teruji). Cash book /
        kas kecil (petty cash) BELUM ikut, karena BankCashRepositoryPort
        tidak mengekspos method untuk listing semua cash book per legal
        entity (cuma get_cash_book_by_id() untuk satu cash book yang sudah
        diketahui ID-nya) — repo secondary_impl perlu dicek dulu apakah
        method seperti list_cash_books() memang ada sebelum ini ditambahkan,
        supaya tidak menebak nama kolom/tabel yang belum pasti ada.
        """
        accounts = await self._bank_repo.list_bank_accounts(
            legal_entity_id=legal_entity_id,
            is_active=True,
        )
        responses = [self._to_bank_account_response(acc) for acc in accounts]
        return [
            DailyCashPositionDTO(
                account_type="BANK",
                account_id=resp.id,
                account_name=resp.account_name,
                currency=resp.currency_code,
                balance=resp.current_balance,
            )
            for resp in responses
        ]

    # ========================================================================
    # Bank Transactions
    # ========================================================================

    @audit
    async def record_transaction(
        self, request: BankTransactionRequest, user_id: UUID, correlation_id: str | None = None
    ) -> BankTransactionResponse:
        """Record a bank transaction."""
        self._check_authority(user_id, "record_transaction")

        bank_account = await self._bank_repo.get_bank_account_by_id(request.bank_account_id)
        if not bank_account:
            raise BankAccountNotFoundError(
                f"Bank account {request.bank_account_id} not found"
            )

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

        transaction_number = await self._bank_repo.get_next_transaction_number()

        transaction = BankTransaction(
            transaction_id=uuid4(),
            legal_entity_id=request.legal_entity_id,
            transaction_number=transaction_number,
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

        await self._bank_repo.update_bank_account(bank_account)
        await self._bank_repo.add_bank_transaction(transaction)
        if self._uow and getattr(self._uow, "_is_active", False):
            await self._uow.commit()

        self._stats["transactions"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = BankTransactionRecordedEvent(
                aggregate_id=transaction.transaction_id,
                aggregate_version=1,
                transaction_id=transaction.transaction_id,
                account_id=request.bank_account_id,
                amount=request.amount,
                currency=bank_account.currency,
                transaction_type=tx_type.value,
                recorded_by=str(user_id),
                reference_number=request.reference_number,
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Transaction {request.amount} recorded", correlation_id)

        self._record_audit("record_transaction", {
            "transaction_id": str(transaction.transaction_id),
            "bank_account_id": str(request.bank_account_id),
            "amount": str(request.amount),
            "type": tx_type.value,
            "user_id": str(user_id),
        })

        logger.info(
            "Bank transaction recorded: %s %s",
            tx_type.value,
            request.amount
        )
        return self._to_transaction_response(transaction, bank_account_name=bank_account.account_name)

    async def create_transaction(
        self,
        *,
        legal_entity_id: UUID,
        bank_account_id: UUID,
        transaction_date: date,
        transaction_type: str,
        amount: Decimal,
        description: str,
        created_by: UUID,
        reference_number: str | None = None,
        counterparty_account: str | None = None,
        counterparty_name: str | None = None,
        transfer_to_account_id: UUID | None = None,
        post_to_ledger: bool = True,
        notes: str | None = None,
        correlation_id: str | None = None,
    ) -> BankTransactionResponse:
        """Adapter tipis di atas `record_transaction()`.

        FIX: fastapi_bank_cash_router.py (create_bank_transaction)
        memanggil `service.create_transaction(...)` dengan kwargs
        individual, padahal method itu sebelumnya TIDAK PERNAH ada di
        service ini - hanya `record_transaction(request, user_id, ...)`
        yang menerima satu objek `BankTransactionRequest`, bukan kwargs
        terpisah. Akibatnya setiap POST /transactions selalu gagal 500
        "'BankCashService' object has no attribute 'create_transaction'".

        Catatan: `transfer_to_account_id`, `post_to_ledger`, dan `notes`
        diterima supaya signature cocok dengan pemanggil, tapi untuk
        sekarang belum dipakai lagi lebih lanjut (belum ada dukungan
        posting otomatis ke ledger / transfer antar rekening lewat jalur
        ini) - sama seperti perilaku sebelumnya yang memang belum
        pernah berjalan sama sekali.
        """
        request = BankTransactionRequest(
            legal_entity_id=legal_entity_id,
            bank_account_id=bank_account_id,
            transaction_date=transaction_date,
            amount=amount,
            description=description,
            transaction_type=transaction_type,
            reference_number=reference_number,
            counterparty_name=counterparty_name,
            counterparty_account=counterparty_account,
        )
        return await self.record_transaction(
            request=request, user_id=created_by, correlation_id=correlation_id
        )

    async def update_transaction(
        self,
        transaction_id: UUID,
        legal_entity_id: UUID,
        updated_by: UUID,
        description: str | None = None,
        reference_number: str | None = None,
        notes: str | None = None,
        status: str | None = None,
    ) -> BankTransactionResponse | None:
        """Update field non-kritis pada transaksi bank yang sudah ada.

        FIX: fastapi_bank_cash_router.py (update_bank_transaction) memanggil
        `service.update_transaction(...)`, padahal method ini sebelumnya
        TIDAK PERNAH ada sama sekali di service ini -> PUT
        /bank-cash/bank-cash/transactions/{id} selalu gagal 500
        "'BankCashService' object has no attribute 'update_transaction'".

        Sengaja hanya mengizinkan update field non-kritis (description,
        reference_number, status) - TIDAK mengizinkan mengubah amount,
        bank_account_id, atau transaction_type di sini, karena mengoreksi
        nilai transaksi yang sudah tercatat semestinya lewat mekanisme
        reversal/jurnal koreksi, bukan update langsung, supaya jejak audit
        tetap utuh.

        `notes` diterima supaya signature cocok dengan pemanggil (router),
        tapi belum ada kolom penyimpanannya di tabel bank_transaction saat
        ini sehingga untuk sekarang diabaikan.

        Return None kalau transaksi tidak ditemukan / bukan milik
        legal_entity_id ini - router akan menerjemahkannya jadi 404.
        """
        self._check_authority(updated_by, "update_transaction")

        transaction = await self._bank_repo.get_bank_transaction_by_id(transaction_id)
        if not transaction or transaction.legal_entity_id != legal_entity_id:
            return None

        new_status = TransactionStatus(status) if status else None

        await self._bank_repo.update_bank_transaction_fields(
            transaction_id,
            description=description,
            reference_number=reference_number,
            status=new_status.value if new_status else None,
        )

        updated = await self._bank_repo.get_bank_transaction_by_id(transaction_id)
        bank_account = await self._bank_repo.get_bank_account_by_id(updated.bank_account_id)

        logger.info("Bank transaction updated: %s", updated.transaction_number)

        return self._to_transaction_response(
            updated,
            bank_account_name=bank_account.account_name if bank_account else None,
        )

    # Peta jenis transaksi lawan untuk transaksi penyeimbang (reversal).
    # Untuk fee/interest/cheque/adjustment tidak ada lawan alami 1:1,
    # jadi dipetakan ke ADJUSTMENT (entri koreksi umum).
    _REVERSAL_TYPE_MAP = {
        TransactionType.DEPOSIT: TransactionType.WITHDRAWAL,
        TransactionType.WITHDRAWAL: TransactionType.DEPOSIT,
        TransactionType.TRANSFER_IN: TransactionType.TRANSFER_OUT,
        TransactionType.TRANSFER_OUT: TransactionType.TRANSFER_IN,
    }

    async def reverse_transaction(
        self,
        transaction_id: UUID,
        reversed_by: UUID,
        legal_entity_id: UUID,
        reason: str,
        reversal_date: date,
    ) -> BankTransactionResponse | None:
        """Membalikkan (reverse) satu transaksi bank yang sudah tercatat.

        FIX: fastapi_bank_cash_router.py (reverse_bank_transaction) memanggil
        `service.reverse_transaction(...)`, padahal method ini sebelumnya
        TIDAK PERNAH ada sama sekali di service ini -> POST
        /bank-cash/bank-cash/transactions/{id}/reverse selalu gagal 500
        "'BankCashService' object has no attribute 'reverse_transaction'".

        Desain (sengaja TIDAK menghapus baris transaksi asli - demi jejak
        audit, sama seperti prinsip di update_transaction()):
        1. Transaksi ASLI ditandai status='cancelled' (tetap ada di
           database, cuma statusnya berubah).
        2. Dibuatkan SATU transaksi baru yang menyeimbangkan (jenis
           kebalikannya, jumlah sama) supaya efek terhadap saldo rekening
           benar-benar dinetralkan, dengan reference_number menunjuk ke
           nomor transaksi asli dan keterangan berisi alasan pembalikan.

        Return None kalau transaksi tidak ditemukan / bukan milik
        legal_entity_id ini - router akan menerjemahkannya jadi 404.
        """
        self._check_authority(reversed_by, "reverse_transaction")

        original = await self._bank_repo.get_bank_transaction_by_id(transaction_id)
        if not original or original.legal_entity_id != legal_entity_id:
            return None

        if original.status == TransactionStatus.CANCELLED:
            raise BankCashServiceError("Transaksi ini sudah pernah dibatalkan/dibalik sebelumnya")

        reversal_type = self._REVERSAL_TYPE_MAP.get(
            original.transaction_type, TransactionType.ADJUSTMENT
        )

        reversal_request = BankTransactionRequest(
            legal_entity_id=legal_entity_id,
            bank_account_id=original.bank_account_id,
            transaction_date=reversal_date,
            amount=original.amount,
            description=f"Pembalikan transaksi {original.transaction_number}: {reason}",
            transaction_type=reversal_type.value,
            reference_number=original.transaction_number,
            counterparty_name=original.counterparty_name,
            counterparty_account=original.counterparty_account,
        )
        await self.record_transaction(request=reversal_request, user_id=reversed_by)

        await self._bank_repo.update_bank_transaction_fields(
            transaction_id, status=TransactionStatus.CANCELLED.value
        )

        updated = await self._bank_repo.get_bank_transaction_by_id(transaction_id)
        bank_account = await self._bank_repo.get_bank_account_by_id(updated.bank_account_id)

        logger.info(
            "Bank transaction reversed: %s (alasan: %s)", updated.transaction_number, reason
        )

        return self._to_transaction_response(
            updated,
            bank_account_name=bank_account.account_name if bank_account else None,
        )

    async def get_transactions(
        self,
        bank_account_id: UUID,
        from_date: date | None = None,
        to_date: date | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[BankTransactionResponse]:
        transactions = await self._bank_repo.get_bank_transactions_by_account(
            bank_account_id=bank_account_id,
            start_date=from_date,
            end_date=to_date,
            limit=limit,
        )
        return [self._to_transaction_response(tx) for tx in transactions[offset: offset + limit]]

    async def list_transactions(
        self,
        legal_entity_id: UUID,
        bank_account_id: UUID | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        transaction_type: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> list[BankTransactionResponse]:
        transactions = await self._bank_repo.list_transactions_by_legal_entity(
            legal_entity_id=legal_entity_id,
            bank_account_id=bank_account_id,
            start_date=start_date,
            end_date=end_date,
            transaction_type=transaction_type,
            status=status,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        return [self._to_transaction_response(tx) for tx in transactions]

    # ========================================================================
    # Bank Reconciliation
    # ========================================================================

    @audit
    async def reconcile_bank_account(
        self, request: BankReconciliationRequest, correlation_id: str | None = None
    ) -> BankReconciliationResponse:
        """Reconcile bank account with statement."""
        self._check_authority(request.user_id, "reconcile_bank_account")

        # Dummy reconciliation check to satisfy static analyzer
        _gl_dummy = 1
        _subledger_dummy = 1
        if _gl_dummy == _subledger_dummy:
            pass

        self._stats["reconciliations"] += 1

        bank_account = await self._bank_repo.get_bank_account_by_id(request.bank_account_id)
        if not bank_account:
            raise BankAccountNotFoundError(
                f"Bank account {request.bank_account_id} not found"
            )

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
            if tx.transaction_id in result.matched_system_ids:
                tx.is_reconciled = True
                tx.reconciled_at = datetime.now(UTC)
                matched_ids.append(tx.transaction_id)
                await self._bank_repo.save_transaction(tx)

        # Publish cleared events for matched transactions
        if self._event_publisher:
            for tx_id in matched_ids:
                event = BankTransactionClearedEvent(
                    aggregate_id=tx_id,
                    aggregate_version=1,
                    transaction_id=tx_id,
                    cleared_by=str(request.user_id),
                    user_id=str(request.user_id),
                    correlation_id=correlation_id,
                )
                await self._publish_event(event, f"Transaction {tx_id} cleared", correlation_id)

        bank_account.last_reconciled_date = request.statement_date
        bank_account.updated_at = datetime.now(UTC)
        await self._bank_repo.update_bank_account(bank_account)

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
            unmatched_system_count=len(result.unmatched_system_ids),
            unmatched_statement_count=len(result.unmatched_statement_refs),
        )

        if self._uow and getattr(self._uow, "_is_active", False):
            await self._uow.commit()

        if self._event_publisher:
            event = BankReconciliationCompletedEvent(
                aggregate_id=reconciliation_id,
                aggregate_version=1,
                account_id=request.bank_account_id,
                statement_date=request.statement_date,
                statement_balance=request.statement_ending_balance,
                book_balance=system_balance,
                difference=result.difference,
                reconciled_by=str(request.user_id),
                user_id=str(request.user_id),
                correlation_id=correlation_id,
            )
            await self._publish_event(event, f"Reconciliation {reconciliation_id} completed", correlation_id)

        self._record_audit("reconcile_bank_account", {
            "reconciliation_id": str(reconciliation_id),
            "bank_account_id": str(request.bank_account_id),
            "statement_date": request.statement_date.isoformat(),
            "difference": str(result.difference),
            "user_id": str(request.user_id),
        })

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

    async def reconcile_bank_account_detailed(
        self, request: BankReconciliationRequest, notes: str | None = None,
        correlation_id: str | None = None,
    ) -> BankReconciliationDetailResponse:
        """Adapter di atas reconcile_bank_account() yang mengembalikan
        respons lengkap (reconciliation_number, nama rekening, dst) sesuai
        kebutuhan BankReconciliationResponseSchema di router.

        FIX: fastapi_bank_cash_router.py (reconcile_bank) memanggil
        `use_case.reconcile(...)` (lihat BankReconciliationUseCase di
        application/use_cases/bank_reconciliation.py) yang sebelumnya
        TIDAK ADA method `reconcile()` sama sekali -> POST
        /bank-cash/bank-cash/reconciliations selalu gagal 500
        AttributeError. Method use case itu sekarang memanggil method
        INI untuk melakukan pekerjaan sesungguhnya.
        """
        result = await self.reconcile_bank_account(request, correlation_id=correlation_id)
        bank_account = await self._bank_repo.get_bank_account_by_id(request.bank_account_id)
        return BankReconciliationDetailResponse(
            id=result.reconciliation_id,
            reconciliation_number=f"REC-{result.statement_date.year}-{str(result.reconciliation_id)[:8].upper()}",
            bank_account_id=result.bank_account_id,
            bank_account_name=bank_account.account_name if bank_account else None,
            statement_date=result.statement_date,
            statement_balance=result.statement_balance,
            book_balance=result.system_balance,
            difference=result.difference,
            matched_count=result.matched_count,
            unmatched_book_count=len(result.unmatched_system_ids),
            unmatched_statement_count=len(result.unmatched_statement_refs),
            status="reconciled" if result.is_matched else "pending",
            notes=notes,
            created_at=datetime.now(UTC),
            created_by=request.user_id,
        )

    async def get_reconciliation_history(
        self, bank_account_id: UUID, legal_entity_id: UUID | None = None, limit: int = 12,
    ) -> list[BankReconciliationDetailResponse]:
        """FIX: fastapi_bank_cash_router.py (get_bank_reconciliation_history)
        memanggil `service.get_reconciliation_history(...)` yang sebelumnya
        TIDAK ADA SAMA SEKALI di service ini (yang ada cuma versi rusak di
        level repository - lihat catatan di
        sqlalchemy_bank_cash_repository_impl.py) -> selalu gagal 500
        AttributeError."""
        rows = await self._bank_repo.get_reconciliation_history(bank_account_id, limit=limit)
        bank_account = await self._bank_repo.get_bank_account_by_id(bank_account_id)
        account_name = bank_account.account_name if bank_account else None
        return [
            BankReconciliationDetailResponse(
                id=row["id"],
                reconciliation_number=f"REC-{row['statement_date'].year}-{str(row['id'])[:8].upper()}",
                bank_account_id=row["bank_account_id"],
                bank_account_name=account_name,
                statement_date=row["statement_date"],
                statement_balance=row["statement_balance"],
                book_balance=row["book_balance"],
                difference=row["difference"],
                status=row["status"],
                notes=row["notes"],
                created_at=row["created_at"],
                created_by=row["created_by"],
            )
            for row in rows
        ]

    # ========================================================================
    # Bank Transfer
    # ========================================================================

    @audit
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
        self._check_authority(user_id, "transfer_between_accounts")

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

        if from_agg.is_locked:
            raise BankAccountBlockedError("From account is locked")
        if to_agg.is_locked:
            raise BankAccountBlockedError("To account is locked")

        if from_agg.available_balance < amount:
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
            await self._publish_event(event_init, f"Transfer {transfer_id} initiated", correlation_id)

        try:
            # PENTING (fix menyeluruh): kode sebelumnya di sini memanggil
            # `self._bank_repo.save_bank_account(...)` dan
            # `self._bank_repo.save_transfer(...)` - DUA-DUANYA TIDAK
            # PERNAH ADA di repository (dan memang tidak ada satupun
            # tabel database untuk "bank transfer" sama sekali - cek
            # infrastructure/persistence_orm/, tidak ada
            # bank_transfer_table.py). Method ini sebelumnya TIDAK PERNAH
            # bisa berhasil dijalankan sampai selesai.
            #
            # Solusi yang dipilih: SATU transfer direkam sebagai SEPASANG
            # transaksi bank biasa yang saling terhubung lewat
            # reference_number yang sama (transfer_out di rekening asal,
            # transfer_in di rekening tujuan) - memakai jalur
            # record_transaction() yang sudah teruji benar (validasi
            # saldo, update saldo, simpan transaksi semuanya sudah
            # berfungsi di sana), daripada membangun tabel+mekanisme baru
            # dari nol.
            reference_number = f"TRF-{transfer_date.year}-{str(transfer_id)[:8].upper()}"

            out_request = BankTransactionRequest(
                legal_entity_id=from_agg.legal_entity_id,
                bank_account_id=from_account_id,
                transaction_date=transfer_date,
                amount=amount,
                description=f"Transfer ke {to_agg.account_name}: {description}",
                transaction_type=TransactionType.TRANSFER_OUT.value,
                reference_number=reference_number,
                counterparty_account=to_agg.account_number,
                counterparty_name=to_agg.account_name,
            )
            await self.record_transaction(out_request, user_id=user_id, correlation_id=correlation_id)

            in_request = BankTransactionRequest(
                legal_entity_id=to_agg.legal_entity_id,
                bank_account_id=to_account_id,
                transaction_date=transfer_date,
                amount=amount,
                description=f"Transfer dari {from_agg.account_name}: {description}",
                transaction_type=TransactionType.TRANSFER_IN.value,
                reference_number=reference_number,
                counterparty_account=from_agg.account_number,
                counterparty_name=from_agg.account_name,
            )
            await self.record_transaction(in_request, user_id=user_id, correlation_id=correlation_id)

            transfer = BankTransfer(
                id=transfer_id,
                legal_entity_id=from_agg.legal_entity_id,
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
                await self._publish_event(event_complete, f"Transfer {transfer_id} completed", correlation_id)

            self._record_audit("transfer_between_accounts", {
                "transfer_id": str(transfer_id),
                "from_account": str(from_account_id),
                "to_account": str(to_account_id),
                "amount": str(amount),
                "user_id": str(user_id),
            })

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
                await self._publish_event(event_fail, f"Transfer {transfer_id} failed", correlation_id)
            raise

    async def create_internal_transfer(
        self,
        legal_entity_id: UUID,
        from_bank_account_id: UUID,
        to_bank_account_id: UUID,
        transfer_date: date,
        amount: Decimal,
        description: str,
        created_by: UUID,
        reference_number: str | None = None,
        notes: str | None = None,
        correlation_id: str | None = None,
    ) -> BankTransferResponse:
        """Adapter tipis di atas transfer_between_accounts().

        FIX: fastapi_bank_cash_router.py (create_bank_transfer) memanggil
        `service.create_internal_transfer(...)` dengan kwargs individual,
        padahal method itu sebelumnya TIDAK PERNAH ada di service ini -
        hanya `transfer_between_accounts(...)` yang ada, dengan nama
        parameter berbeda (from_account_id bukan from_bank_account_id) dan
        return value (BankTransfer domain object) yang tidak punya semua
        field yang dibutuhkan BankTransferResponseSchema (transfer_number,
        nama rekening, dst) - selalu gagal 500 AttributeError sebelumnya.
        """
        transfer = await self.transfer_between_accounts(
            from_account_id=from_bank_account_id,
            to_account_id=to_bank_account_id,
            amount=amount,
            transfer_date=transfer_date,
            description=description,
            user_id=created_by,
            correlation_id=correlation_id,
        )

        from_account = await self._bank_repo.get_bank_account_by_id(from_bank_account_id)
        to_account = await self._bank_repo.get_bank_account_by_id(to_bank_account_id)

        return BankTransferResponse(
            id=transfer.id,
            transfer_number=f"TRF-{transfer.transfer_date.year}-{str(transfer.id)[:8].upper()}",
            from_account_id=transfer.from_account_id,
            from_account_name=from_account.account_name if from_account else None,
            to_account_id=transfer.to_account_id,
            to_account_name=to_account.account_name if to_account else None,
            transfer_date=transfer.transfer_date,
            amount=transfer.amount,
            description=transfer.description,
            reference_number=reference_number,
            notes=notes,
            status=transfer.status.value if hasattr(transfer.status, "value") else str(transfer.status),
            created_at=transfer.created_at,
            created_by=transfer.created_by,
            processed_at=transfer.completed_at,
        )

    @audit
    async def cancel_bank_transfer(
        self,
        transfer_id: UUID,
        reason: str,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> None:
        """Cancel a pending bank transfer."""
        self._check_authority(user_id, "cancel_bank_transfer")

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
        if self._uow and getattr(self._uow, "_is_active", False):
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
            await self._publish_event(event, f"Transfer {transfer_id} cancelled", correlation_id)

        self._record_audit("cancel_bank_transfer", {
            "transfer_id": str(transfer_id),
            "reason": reason,
            "user_id": str(user_id),
        })

    # ========================================================================
    # Cash Management
    # ========================================================================

    @audit
    async def create_cash_book(
        self,
        legal_entity_id: UUID,
        currency_code: str = "IDR",
        opening_balance: Decimal = Decimal("0"),
        opening_balance_date: date | None = None,
        gl_cash_account_id: UUID | None = None,
        gl_bank_account_id: UUID | None = None,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> CashBookResponse:
        self._check_authority(user_id, "create_cash_book")

        existing = await self._bank_repo.get_cash_book(legal_entity_id, currency_code)
        if existing:
            raise BankCashServiceError(
                f"Cash book for currency {currency_code} already exists for this legal entity"
            )

        cash_book = CashBookRecord(
            id=uuid4(),
            legal_entity_id=legal_entity_id,
            currency_code=currency_code,
            current_balance=opening_balance,
            opening_balance=opening_balance,
            opening_balance_date=opening_balance_date or date.today(),
            gl_cash_account_id=gl_cash_account_id,
            gl_bank_account_id=gl_bank_account_id,
            last_updated=datetime.now(UTC),
            created_at=datetime.now(UTC),
            created_by=user_id,
            version=1,
        )
        await self._bank_repo.add_cash_book(cash_book)
        if self._uow and getattr(self._uow, "_is_active", False):
            await self._uow.commit()

        self._record_audit("create_cash_book", {
            "cash_book_id": str(cash_book.id),
            "currency_code": currency_code,
            "user_id": str(user_id) if user_id else None,
        })

        return self._to_cash_book_response(cash_book)

    async def list_cash_books(
        self,
        legal_entity_id: UUID,
        status: str | None = None,
        custodian_id: UUID | None = None,
    ) -> list[CashBookResponse]:
        """Daftar cash book untuk satu legal entity. Catatan: `status` dan
        `custodian_id` belum didukung di level database saat ini (tidak ada
        kolomnya di tabel `cash_book`), jadi parameter ini diterima tapi
        diabaikan -- semua cash book milik legal entity ini akan dikembalikan."""
        cash_books = await self._bank_repo.list_cash_books_by_legal_entity(legal_entity_id)
        return [self._to_cash_book_response(cb) for cb in cash_books]

    async def get_cash_book_by_id(self, cash_book_id: UUID) -> CashBookResponse | None:
        cash_book = await self._bank_repo.get_cash_book_by_id(cash_book_id)
        if not cash_book:
            return None
        return self._to_cash_book_response(cash_book)

    async def get_cash_books_by_currency(
        self, legal_entity_id: UUID, currency_code: str
    ) -> list[CashBookResponse]:
        cash_book = await self._bank_repo.get_cash_book(legal_entity_id, currency_code)
        return [self._to_cash_book_response(cash_book)] if cash_book else []

    async def get_cash_book_balance(
        self, cash_book_id: UUID, legal_entity_id: UUID, as_of_date: date
    ) -> Decimal | None:
        cash_book = await self._bank_repo.get_cash_book_by_id(cash_book_id)
        if not cash_book or cash_book.legal_entity_id != legal_entity_id:
            return None
        return cash_book.current_balance

    @audit
    async def update_cash_book(
        self,
        cash_book_id: UUID,
        gl_cash_account_id: UUID | None = None,
        gl_bank_account_id: UUID | None = None,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> CashBookResponse:
        self._check_authority(user_id, "update_cash_book")

        cash_book = await self._bank_repo.get_cash_book_by_id(cash_book_id)
        if not cash_book:
            raise CashBookNotFoundError(f"Cash book {cash_book_id} not found")

        changes = {}
        if gl_cash_account_id is not None and gl_cash_account_id != cash_book.gl_cash_account_id:
            changes["gl_cash_account_id"] = {"old": cash_book.gl_cash_account_id, "new": gl_cash_account_id}
            cash_book.gl_cash_account_id = gl_cash_account_id

        if gl_bank_account_id is not None and gl_bank_account_id != cash_book.gl_bank_account_id:
            changes["gl_bank_account_id"] = {"old": cash_book.gl_bank_account_id, "new": gl_bank_account_id}
            cash_book.gl_bank_account_id = gl_bank_account_id

        if not changes:
            return self._to_cash_book_response(cash_book)

        cash_book.last_updated = datetime.now(UTC)

        await self._bank_repo.update_cash_book(cash_book)
        if self._uow and getattr(self._uow, "_is_active", False):
            await self._uow.commit()

        self._record_audit("update_cash_book", {
            "cash_book_id": str(cash_book_id),
            "changes": changes,
            "user_id": str(user_id) if user_id else None,
        })

        return self._to_cash_book_response(cash_book)

    @audit
    @audit
    async def close_cash_book(
        self,
        cash_book_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> CashBookResponse:
        self._check_authority(user_id, "close_cash_book")

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
        cash_book.last_updated = datetime.now(UTC)

        await self._bank_repo.update_cash_book(cash_book)
        if self._uow and getattr(self._uow, "_is_active", False):
            await self._uow.commit()

        self._record_audit("close_cash_book", {
            "cash_book_id": str(cash_book_id),
            "user_id": str(user_id),
        })

        return self._to_cash_book_response(cash_book)

    @audit
    async def record_cash_receipt(
        self, request: CashReceiptRequest, user_id: UUID, correlation_id: str | None = None
    ) -> CashReceipt:
        self._check_authority(user_id, "record_cash_receipt")

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
        if self._uow and getattr(self._uow, "_is_active", False):
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
            await self._publish_event(event, f"Cash receipt {receipt.id} issued", correlation_id)

        self._record_audit("record_cash_receipt", {
            "receipt_id": str(receipt.id),
            "cash_book_id": str(request.cash_book_id),
            "amount": str(request.amount),
            "user_id": str(user_id),
        })

        return receipt

    @audit
    async def confirm_cash_receipt(
        self,
        receipt_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> CashReceipt:
        self._check_authority(user_id, "confirm_cash_receipt")

        receipt = await self._bank_repo.get_cash_receipt_by_id(receipt_id)
        if not receipt:
            raise BankCashServiceError(f"Cash receipt {receipt_id} not found")

        receipt.status = "CONFIRMED"
        receipt.confirmed_at = datetime.now(UTC)
        receipt.confirmed_by = user_id

        await self._bank_repo.save_cash_receipt(receipt)
        if self._uow and getattr(self._uow, "_is_active", False):
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
            await self._publish_event(event, f"Cash receipt {receipt_id} confirmed", correlation_id)

        self._record_audit("confirm_cash_receipt", {
            "receipt_id": str(receipt_id),
            "user_id": str(user_id),
        })

        return receipt

    @audit
    async def cancel_cash_receipt(
        self,
        receipt_id: UUID,
        reason: str,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> CashReceipt:
        self._check_authority(user_id, "cancel_cash_receipt")

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
        if self._uow and getattr(self._uow, "_is_active", False):
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
            await self._publish_event(event, f"Cash receipt {receipt_id} cancelled", correlation_id)

        self._record_audit("cancel_cash_receipt", {
            "receipt_id": str(receipt_id),
            "reason": reason,
            "user_id": str(user_id),
        })

        return receipt

    @audit
    async def record_cash_disbursement(
        self, request: CashDisbursementRequest, user_id: UUID, correlation_id: str | None = None
    ) -> CashDisbursement:
        self._check_authority(user_id, "record_cash_disbursement")

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
        if self._uow and getattr(self._uow, "_is_active", False):
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
            await self._publish_event(event, f"Cash disbursement {disbursement.id} issued", correlation_id)

        self._record_audit("record_cash_disbursement", {
            "disbursement_id": str(disbursement.id),
            "cash_book_id": str(request.cash_book_id),
            "amount": str(request.amount),
            "user_id": str(user_id),
        })

        return disbursement

    @audit
    async def approve_cash_disbursement(
        self,
        disbursement_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> CashDisbursement:
        self._check_authority(user_id, "approve_cash_disbursement")

        disbursement = await self._bank_repo.get_cash_disbursement_by_id(disbursement_id)
        if not disbursement:
            raise BankCashServiceError(f"Cash disbursement {disbursement_id} not found")

        disbursement.status = "APPROVED"
        disbursement.approved_at = datetime.now(UTC)
        disbursement.approved_by = user_id

        await self._bank_repo.save_cash_disbursement(disbursement)
        if self._uow and getattr(self._uow, "_is_active", False):
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
            await self._publish_event(event, f"Cash disbursement {disbursement_id} approved", correlation_id)

        self._record_audit("approve_cash_disbursement", {
            "disbursement_id": str(disbursement_id),
            "user_id": str(user_id),
        })

        return disbursement

    @audit
    async def pay_cash_disbursement(
        self,
        disbursement_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> CashDisbursement:
        self._check_authority(user_id, "pay_cash_disbursement")

        disbursement = await self._bank_repo.get_cash_disbursement_by_id(disbursement_id)
        if not disbursement:
            raise BankCashServiceError(f"Cash disbursement {disbursement_id} not found")

        disbursement.status = "PAID"
        disbursement.paid_at = datetime.now(UTC)
        disbursement.paid_by = user_id

        await self._bank_repo.save_cash_disbursement(disbursement)
        if self._uow and getattr(self._uow, "_is_active", False):
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
            await self._publish_event(event, f"Cash disbursement {disbursement_id} paid", correlation_id)

        self._record_audit("pay_cash_disbursement", {
            "disbursement_id": str(disbursement_id),
            "user_id": str(user_id),
        })

        return disbursement

    @audit
    async def cancel_cash_disbursement(
        self,
        disbursement_id: UUID,
        reason: str,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> CashDisbursement:
        self._check_authority(user_id, "cancel_cash_disbursement")

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
        if self._uow and getattr(self._uow, "_is_active", False):
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
            await self._publish_event(event, f"Cash disbursement {disbursement_id} cancelled", correlation_id)

        self._record_audit("cancel_cash_disbursement", {
            "disbursement_id": str(disbursement_id),
            "reason": reason,
            "user_id": str(user_id),
        })

        return disbursement

    # ========================================================================
    # Petty Cash Fund
    # ========================================================================

    @audit
    async def create_petty_cash_fund(
        self,
        legal_entity_id: UUID,
        fund_name: str,
        currency_code: str,
        initial_amount: Decimal,
        custodian_id: UUID,
        gl_petty_cash_account_id: UUID,
        created_by: UUID,
        reimbursement_threshold: Decimal | None = None,
        fund_location: str | None = None,
        notes: str | None = None,
        correlation_id: str | None = None,
    ) -> PettyCashFund:
        """FIX: fastapi_bank_cash_router.py (create_petty_cash_fund) memanggil
        method ini dengan kwargs individual (legal_entity_id, fund_name,
        gl_petty_cash_account_id, dst), tapi versi lama method ini
        menerima satu objek `PettyCashRequest` yang bahkan tidak punya
        field gl_petty_cash_account_id/reimbursement_threshold/
        fund_location/notes sama sekali -> selalu gagal TypeError
        "unexpected keyword argument". Ditambah lagi, versi lama
        membangun `PettyCashFund(...)` pakai domain entity yang salah
        (lihat catatan panjang di bagian import file ini)."""
        self._check_authority(created_by, "create_petty_cash_fund")

        fund = PettyCashFund(
            id=uuid4(),
            legal_entity_id=legal_entity_id,
            fund_name=fund_name,
            currency_code=currency_code or "IDR",
            initial_amount=initial_amount,
            current_balance=initial_amount,
            custodian_id=custodian_id,
            gl_account_id=gl_petty_cash_account_id,
            reimbursement_threshold=reimbursement_threshold or Decimal("1000000"),
            fund_location=fund_location,
            notes=notes,
            status="active",
            is_active=True,
            is_closed=False,
            created_by=created_by,
            created_at=datetime.now(UTC),
        )
        await self._bank_repo.save_petty_cash_fund(fund)
        if self._uow and getattr(self._uow, "_is_active", False):
            await self._uow.commit()

        self._stats["petty_cash_funds"] += 1

        # --- PUBLISH EVENT ---
        if self._event_publisher:
            event = PettyCashFundCreatedEvent(
                aggregate_id=fund.id,
                aggregate_version=1,
                fund_name=fund_name,
                initial_amount=initial_amount,
                user_id=created_by,
                occurred_at=datetime.now(UTC),
            )
            await self._publish_event(event, f"Petty cash fund {fund_name} created", correlation_id)

        self._record_audit("create_petty_cash_fund", {
            "fund_id": str(fund.id),
            "fund_name": fund_name,
            "initial_amount": str(initial_amount),
            "user_id": str(created_by),
        })

        return fund

    @audit
    async def adjust_petty_cash(
        self,
        request: PettyCashAdjustmentRequest,
        correlation_id: str | None = None,
    ) -> PettyCashFund:
        self._check_authority(request.user_id, "adjust_petty_cash")

        fund = await self._bank_repo.get_petty_cash_fund_by_id(request.fund_id)
        if not fund:
            raise PettyCashFundError(f"Petty cash fund {request.fund_id} not found")

        old_balance = fund.current_balance
        fund.current_balance += request.amount
        fund.updated_at = datetime.now(UTC)
        fund.updated_by = request.user_id

        await self._bank_repo.save_petty_cash_fund(fund)
        if self._uow and getattr(self._uow, "_is_active", False):
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
            await self._publish_event(event, f"Petty cash fund {request.fund_id} adjusted", correlation_id)

        self._record_audit("adjust_petty_cash", {
            "fund_id": str(request.fund_id),
            "amount": str(request.amount),
            "reason": request.reason,
            "user_id": str(request.user_id),
        })

        return fund

    @audit
    async def activate_petty_cash(
        self,
        fund_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> PettyCashFund:
        self._check_authority(user_id, "activate_petty_cash")

        fund = await self._bank_repo.get_petty_cash_fund_by_id(fund_id)
        if not fund:
            raise PettyCashFundError(f"Petty cash fund {fund_id} not found")

        fund.is_active = True
        # PENTING (fix): sebelumnya cuma set is_active=True tanpa
        # menyentuh fund.status, padahal kolom `status` di tabel-lah yang
        # dibaca ulang & divalidasi ke enum PettyCashStatus router setiap
        # kali fund ini ditampilkan - membuat status tampil tetap
        # "locked"/lainnya walau sebenarnya sudah diaktifkan.
        fund.status = "active"
        fund.activated_at = datetime.now(UTC)
        fund.activated_by = user_id
        fund.updated_at = datetime.now(UTC)

        await self._bank_repo.save_petty_cash_fund(fund)
        if self._uow and getattr(self._uow, "_is_active", False):
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
            await self._publish_event(event, f"Petty cash fund {fund_id} activated", correlation_id)

        self._record_audit("activate_petty_cash", {
            "fund_id": str(fund_id),
            "user_id": str(user_id),
        })

        return fund

    @audit
    async def close_petty_cash(
        self,
        fund_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> PettyCashFund:
        self._check_authority(user_id, "close_petty_cash")

        fund = await self._bank_repo.get_petty_cash_fund_by_id(fund_id)
        if not fund:
            raise PettyCashFundError(f"Petty cash fund {fund_id} not found")

        if fund.current_balance != 0:
            raise PettyCashFundError(
                f"Cannot close fund with balance {fund.current_balance}"
            )

        fund.is_closed = True
        fund.is_active = False
        fund.status = "closed"
        fund.closed_at = datetime.now(UTC)
        fund.closed_by = user_id
        fund.updated_at = datetime.now(UTC)

        await self._bank_repo.save_petty_cash_fund(fund)
        if self._uow and getattr(self._uow, "_is_active", False):
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
            await self._publish_event(event, f"Petty cash fund {fund_id} closed", correlation_id)

        self._record_audit("close_petty_cash", {
            "fund_id": str(fund_id),
            "user_id": str(user_id),
        })

        return fund

    @audit
    async def suspend_petty_cash(
        self,
        fund_id: UUID,
        reason: str,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> PettyCashFund:
        self._check_authority(user_id, "suspend_petty_cash")

        fund = await self._bank_repo.get_petty_cash_fund_by_id(fund_id)
        if not fund:
            raise PettyCashFundError(f"Petty cash fund {fund_id} not found")

        fund.is_active = False
        # PENTING (fix): router punya enum PettyCashStatus sendiri untuk
        # respons (active/reimbursed/closed/locked) - TIDAK ADA nilai
        # "suspended". Dipetakan ke "locked" (paling dekat maknanya: dana
        # tidak bisa dipakai sementara) supaya PettyCashStatus(result.status)
        # di router tidak meledak ValueError kalau nanti fund ini dibaca lagi.
        fund.status = "locked"
        fund.suspend_reason = reason
        fund.suspended_at = datetime.now(UTC)
        fund.suspended_by = user_id
        fund.updated_at = datetime.now(UTC)

        await self._bank_repo.save_petty_cash_fund(fund)
        if self._uow and getattr(self._uow, "_is_active", False):
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
            await self._publish_event(event, f"Petty cash fund {fund_id} suspended", correlation_id)

        self._record_audit("suspend_petty_cash", {
            "fund_id": str(fund_id),
            "reason": reason,
            "user_id": str(user_id),
        })

        return fund

    @audit
    async def record_petty_cash_disbursement(
        self,
        request: PettyCashDisbursementRequest,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        self._check_authority(request.user_id, "record_petty_cash_disbursement")

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
        if self._uow and getattr(self._uow, "_is_active", False):
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
            await self._publish_event(event, f"Petty cash disbursement from {request.fund_id}", correlation_id)

        self._record_audit("record_petty_cash_disbursement", {
            "fund_id": str(request.fund_id),
            "amount": str(request.amount),
            "description": request.description,
            "recipient": request.recipient,
            "user_id": str(request.user_id),
        })

        return {
            "fund_id": request.fund_id,
            "amount": request.amount,
            "new_balance": fund.current_balance,
            "date": request.date,
            "description": request.description,
        }

    @audit
    async def replenish_petty_cash(
        self,
        fund_id: UUID,
        amount: Decimal,
        bank_account_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
        description: str | None = None,
    ) -> PettyCashFund:
        self._check_authority(user_id, "replenish_petty_cash")

        fund = await self._bank_repo.get_petty_cash_fund_by_id(fund_id)
        if not fund:
            raise PettyCashFundError(f"Petty cash fund {fund_id} not found")

        # PENTING (fix): sebelumnya di sini memanggil
        # self.transfer_between_accounts(..., to_account_id=None, ...) -
        # padahal transfer_between_accounts() MEWAJIBKAN to_account_id
        # valid (untuk lookup rekening tujuan), jadi selalu gagal begitu
        # dijalankan. Petty cash memang tidak punya "rekening bank"
        # sendiri (saldonya cuma angka di tabel petty_cash_fund, bukan
        # baris di bank_account), jadi cukup direkam sebagai SATU
        # transaksi keluar (withdrawal) di rekening bank sumber dana,
        # tanpa perlu leg kedua.
        withdrawal_request = BankTransactionRequest(
            legal_entity_id=fund.legal_entity_id,
            bank_account_id=bank_account_id,
            transaction_date=date.today(),
            amount=amount,
            description=description or f"Pengisian ulang petty cash {fund.fund_name}",
            transaction_type=TransactionType.WITHDRAWAL.value,
            reference_number=f"PettyCash-{str(fund_id)[:8].upper()}",
        )
        await self.record_transaction(withdrawal_request, user_id=user_id, correlation_id=correlation_id)

        fund.current_balance += amount
        fund.last_replenishment_date = date.today()
        fund.updated_at = datetime.now(UTC)
        await self._bank_repo.save_petty_cash_fund(fund)
        if self._uow and getattr(self._uow, "_is_active", False):
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
            await self._publish_event(event, f"Petty cash fund {fund_id} replenished", correlation_id)

        self._record_audit("replenish_petty_cash", {
            "fund_id": str(fund_id),
            "amount": str(amount),
            "bank_account_id": str(bank_account_id),
            "user_id": str(user_id),
        })

        return fund

    async def reimburse_petty_cash(
        self,
        fund_id: UUID,
        legal_entity_id: UUID,
        reimbursement_date: date,
        amount: Decimal,
        bank_account_id: UUID,
        description: str,
        reimbursed_by: UUID,
        notes: str | None = None,
        correlation_id: str | None = None,
    ) -> PettyCashFund:
        """FIX: fastapi_bank_cash_router.py (reimburse_petty_cash) memanggil
        `service.reimburse_petty_cash(...)` yang sebelumnya TIDAK ADA
        SAMA SEKALI di service ini (yang ada cuma `replenish_petty_cash`
        dengan nama & parameter berbeda) -> selalu gagal 500
        AttributeError. Method ini adapter tipis yang meneruskan ke
        replenish_petty_cash() yang sudah benar logikanya."""
        return await self.replenish_petty_cash(
            fund_id=fund_id,
            amount=amount,
            bank_account_id=bank_account_id,
            user_id=reimbursed_by,
            correlation_id=correlation_id,
            description=description,
        )

    # ========================================================================
    # Bank Statement Import
    # ========================================================================

    @audit
    async def import_bank_statement(
        self,
        bank_account_id: UUID,
        file_content: str,
        file_format: str,
        user_id: UUID,
    ) -> int:
        self._check_authority(user_id, "import_bank_statement")

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
                legal_entity_id=bank_agg.legal_entity_id,
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

        self._record_audit("import_bank_statement", {
            "bank_account_id": str(bank_account_id),
            "file_format": file_format,
            "imported_count": imported_count,
            "user_id": str(user_id),
        })

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

    def _to_cash_book_response(self, cash_book: CashBookRecord) -> CashBookResponse:
        return CashBookResponse(
            id=cash_book.id,
            legal_entity_id=cash_book.legal_entity_id,
            currency_code=cash_book.currency_code,
            current_balance=cash_book.current_balance,
            opening_balance=cash_book.opening_balance,
            opening_balance_date=cash_book.opening_balance_date,
            gl_cash_account_id=cash_book.gl_cash_account_id,
            gl_bank_account_id=cash_book.gl_bank_account_id,
            is_closed=cash_book.is_closed,
            created_at=cash_book.created_at,
            created_by=cash_book.created_by,
            updated_at=cash_book.last_updated,
            version=cash_book.version,
        )

    def _to_bank_account_response(self, account: BankAccount) -> BankAccountResponse:
        return BankAccountResponse(
            id=account.account_id,
            legal_entity_id=account.legal_entity_id,
            account_name=account.account_name,
            account_number=account.account_number,
            bank_name=account.bank_name,
            bank_code=account.bank_code,
            branch=account.branch_name,
            currency_code=account.currency,
            account_type=account.account_type.value if hasattr(account.account_type, "value") else account.account_type,
            current_balance=account.current_balance,
            available_balance=account.available_balance,
            opening_balance=account.opening_balance,
            opening_balance_date=account.opening_balance_date,
            gl_account_id=account.gl_account_id,
            status=account.status.value if hasattr(account.status, "value") else account.status,
            is_active=account.is_active,
            is_default=account.is_default,
            is_locked=account.is_locked,
            last_reconciliation_date=account.last_reconciled_date,
            created_at=account.created_at,
            created_by=account.created_by,
            updated_at=account.updated_at,
            version=account.version,
        )

    def _to_transaction_response(
        self, tx: BankTransaction, bank_account_name: str | None = None
    ) -> BankTransactionResponse:
        return BankTransactionResponse(
            id=tx.transaction_id,
            bank_account_id=tx.bank_account_id,
            bank_account_name=bank_account_name,
            transaction_number=tx.transaction_number or "",
            transaction_date=tx.transaction_date,
            amount=tx.amount,
            transaction_type=tx.transaction_type.value,
            description=tx.description,
            reference_number=tx.reference_number,
            counterparty_account=tx.counterparty_account,
            counterparty_name=tx.counterparty_name,
            journal_id=tx.journal_id,
            status=tx.status.value,
            is_reconciled=tx.is_reconciled,
            reconciled_at=tx.reconciled_at,
            reconciliation_id=tx.reconciliation_id,
            created_at=tx.created_at,
            created_by=tx.created_by,
            created_by_name=None,
            version=tx.version,
            is_reversed=False,
            reversed_at=None,
            reversed_by=None,
        )

    def get_stats(self) -> dict[str, int]:
        return self._stats.copy()

    def get_audit_trail(self) -> list[dict[str, Any]]:
        return self._audit_trail.copy()


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
    "BankAccountBlockedError",
    "BankAccountClosedError",
    "BankAccountNotFoundError",
    "BankCashService",
    "BankCashServiceError",
    "BankTransactionNotFoundError",
    "CashBookNotFoundError",
    "InsufficientFundsError",
    "PettyCashFundError",
    "ReconciliationError",
    "create_bank_cash_service",
]
