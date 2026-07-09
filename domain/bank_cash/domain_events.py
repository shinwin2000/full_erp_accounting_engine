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
    """
    Base class untuk semua domain event.

    Attributes:
        event_id: UUID unik event.
        event_type: Jenis event (DomainEventType).
        aggregate_id: UUID agregat yang terkait.
        aggregate_version: Versi agregat saat event terjadi.
        occurred_at: Waktu kejadian.
        event_data: Data payload event.
        user_id: ID pengguna yang memicu event (opsional).
        correlation_id: ID korelasi untuk tracing (opsional).
        causation_id: ID penyebab event (opsional).
    """
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
    """
    Event yang diterbitkan ketika akun bank baru dibuat.

    Attributes:
        aggregate_id: ID agregat akun bank.
        aggregate_version: Versi agregat.
        account_id: ID akun bank.
        account_number: Nomor akun.
        account_name: Nama akun.
        account_type: Jenis akun (misal: checking, savings).
        bank_name: Nama bank.
        currency: Mata uang akun.
        initial_balance: Saldo awal.
        created_by: User ID pembuat.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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
    """
    Event yang diterbitkan ketika data akun bank diubah.

    Attributes:
        aggregate_id: ID agregat akun bank.
        aggregate_version: Versi agregat.
        account_id: ID akun bank.
        changes: Dictionary perubahan field yang diubah.
        updated_by: User ID pengubah.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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
    """
    Event yang diterbitkan ketika akun bank diblokir.

    Attributes:
        aggregate_id: ID agregat akun bank.
        aggregate_version: Versi agregat.
        account_id: ID akun bank.
        reason: Alasan pemblokiran.
        blocked_by: User ID pemblokir.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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
    """
    Event yang diterbitkan ketika akun bank ditutup.

    Attributes:
        aggregate_id: ID agregat akun bank.
        aggregate_version: Versi agregat.
        account_id: ID akun bank.
        closed_by: User ID penutup.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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
    """
    Event yang diterbitkan ketika transaksi bank dicatat.

    Attributes:
        aggregate_id: ID agregat transaksi.
        aggregate_version: Versi agregat.
        transaction_id: ID transaksi.
        account_id: ID akun bank terkait.
        amount: Jumlah transaksi.
        currency: Mata uang transaksi.
        transaction_type: Jenis transaksi (debit/kredit).
        recorded_by: User ID pencatat.
        reference_number: Nomor referensi (opsional).
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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
    """
    Event yang diterbitkan ketika transaksi bank sudah clear.

    Attributes:
        aggregate_id: ID agregat transaksi.
        aggregate_version: Versi agregat.
        transaction_id: ID transaksi.
        cleared_by: User ID yang men-clear.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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
    """
    Event yang diterbitkan ketika transaksi bank direkonsiliasi.

    Attributes:
        aggregate_id: ID agregat transaksi.
        aggregate_version: Versi agregat.
        transaction_id: ID transaksi.
        reconciled_by: User ID yang melakukan rekonsiliasi.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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
    """
    Event yang diterbitkan ketika transfer bank dimulai.

    Attributes:
        aggregate_id: ID agregat transfer.
        aggregate_version: Versi agregat.
        transfer_id: ID transfer.
        from_account_id: ID akun sumber.
        to_account_id: ID akun tujuan.
        amount: Jumlah transfer.
        currency: Mata uang transfer.
        initiated_by: User ID pemrakarsa.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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
    """
    Event yang diterbitkan ketika transfer bank berhasil diselesaikan.

    Attributes:
        aggregate_id: ID agregat transfer.
        aggregate_version: Versi agregat.
        transfer_id: ID transfer.
        completed_by: User ID penyelesaian.
        reference: Referensi transfer (opsional).
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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
    """
    Event yang diterbitkan ketika transfer bank gagal.

    Attributes:
        aggregate_id: ID agregat transfer.
        aggregate_version: Versi agregat.
        transfer_id: ID transfer.
        reason: Alasan kegagalan.
        failed_by: User ID yang mencatat kegagalan.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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
    """
    Event yang diterbitkan ketika transfer bank dibatalkan.

    Attributes:
        aggregate_id: ID agregat transfer.
        aggregate_version: Versi agregat.
        transfer_id: ID transfer.
        reason: Alasan pembatalan.
        cancelled_by: User ID pembatalan.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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
    """
    Event yang diterbitkan ketika penerimaan kas dikonfirmasi.

    Attributes:
        aggregate_id: ID agregat penerimaan.
        aggregate_version: Versi agregat.
        receipt_id: ID penerimaan.
        receipt_number: Nomor bukti penerimaan.
        amount: Jumlah penerimaan.
        currency: Mata uang penerimaan.
        confirmed_by: User ID konfirmasi.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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
    """
    Event yang diterbitkan ketika penerimaan kas dibatalkan.

    Attributes:
        aggregate_id: ID agregat penerimaan.
        aggregate_version: Versi agregat.
        receipt_id: ID penerimaan.
        reason: Alasan pembatalan.
        cancelled_by: User ID pembatalan.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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
    """
    Event yang diterbitkan ketika pengeluaran kas disetujui.

    Attributes:
        aggregate_id: ID agregat pengeluaran.
        aggregate_version: Versi agregat.
        disbursement_id: ID pengeluaran.
        amount: Jumlah pengeluaran.
        currency: Mata uang pengeluaran.
        approved_by: User ID persetujuan.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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
    """
    Event yang diterbitkan ketika pengeluaran kas dibayarkan.

    Attributes:
        aggregate_id: ID agregat pengeluaran.
        aggregate_version: Versi agregat.
        disbursement_id: ID pengeluaran.
        paid_by: User ID pembayaran.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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
    """
    Event yang diterbitkan ketika pengeluaran kas dibatalkan.

    Attributes:
        aggregate_id: ID agregat pengeluaran.
        aggregate_version: Versi agregat.
        disbursement_id: ID pengeluaran.
        reason: Alasan pembatalan.
        cancelled_by: User ID pembatalan.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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
    """
    Event yang diterbitkan ketika terjadi pengeluaran kas kecil.

    Attributes:
        aggregate_id: ID agregat kas kecil.
        aggregate_version: Versi agregat.
        petty_cash_id: ID kas kecil.
        amount: Jumlah pengeluaran.
        description: Deskripsi pengeluaran.
        approved_by: User ID persetujuan.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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
    """
    Event yang diterbitkan ketika kas kecil diisi ulang.

    Attributes:
        aggregate_id: ID agregat kas kecil.
        aggregate_version: Versi agregat.
        petty_cash_id: ID kas kecil.
        amount: Jumlah pengisian ulang.
        replenished_by: User ID pengisi ulang.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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
    """
    Event yang diterbitkan ketika saldo kas kecil disesuaikan.

    Attributes:
        aggregate_id: ID agregat kas kecil.
        aggregate_version: Versi agregat.
        petty_cash_id: ID kas kecil.
        adjustment_amount: Jumlah penyesuaian (positif/negatif).
        reason: Alasan penyesuaian.
        adjusted_by: User ID penyesuai.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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
    """
    Event yang diterbitkan ketika kas kecil ditangguhkan.

    Attributes:
        aggregate_id: ID agregat kas kecil.
        aggregate_version: Versi agregat.
        petty_cash_id: ID kas kecil.
        reason: Alasan penangguhan.
        suspended_by: User ID penangguh.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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
    """
    Event yang diterbitkan ketika kas kecil diaktifkan kembali.

    Attributes:
        aggregate_id: ID agregat kas kecil.
        aggregate_version: Versi agregat.
        petty_cash_id: ID kas kecil.
        activated_by: User ID pengaktif.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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
    """
    Event yang diterbitkan ketika kas kecil ditutup.

    Attributes:
        aggregate_id: ID agregat kas kecil.
        aggregate_version: Versi agregat.
        petty_cash_id: ID kas kecil.
        final_balance: Saldo akhir kas kecil.
        closed_by: User ID penutup.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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
    """
    Event yang diterbitkan ketika rekonsiliasi bank selesai.

    Attributes:
        aggregate_id: ID agregat rekonsiliasi.
        aggregate_version: Versi agregat.
        account_id: ID akun bank.
        statement_date: Tanggal laporan bank.
        statement_balance: Saldo menurut laporan bank.
        book_balance: Saldo menurut buku.
        difference: Selisih saldo.
        reconciled_by: User ID yang melakukan rekonsiliasi.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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
    """
    Event yang diterbitkan ketika buku kas diperbarui.

    Attributes:
        aggregate_id: ID agregat buku kas.
        aggregate_version: Versi agregat.
        cash_book_id: ID buku kas.
        new_balance: Saldo baru.
        transaction_type: Jenis transaksi.
        amount: Jumlah transaksi.
        updated_by: User ID pembaru.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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
    """
    Event yang diterbitkan ketika buku kas ditutup.

    Attributes:
        aggregate_id: ID agregat buku kas.
        aggregate_version: Versi agregat.
        cash_book_id: ID buku kas.
        closed_by: User ID penutup.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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
    """
    Publisher untuk domain event, digunakan untuk menyebarkan event ke handler.
    """
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

# Shim classes (tanpa suffix Event) untuk kompatibilitas dengan service layer


class BankAccountCreated(DomainEvent):
    """
    Shim class untuk event BankAccountCreated (tanpa suffix 'Event') – kompatibilitas.
    """
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
    """
    Shim class untuk event BankAccountUpdated (tanpa suffix 'Event') – kompatibilitas.
    """
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
    """
    Shim class untuk event BankTransactionRecorded (tanpa suffix 'Event') – kompatibilitas.
    """
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
    """
    Shim class untuk event BankReconciliationCompleted (tanpa suffix 'Event') – kompatibilitas.
    """
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
    """
    Shim class untuk event BankTransferExecuted (tanpa suffix 'Event') – kompatibilitas.
    """
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
    """
    Shim class untuk event CashReceiptIssued (tanpa suffix 'Event') – kompatibilitas.
    """
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
    """
    Shim class untuk event CashDisbursementIssued (tanpa suffix 'Event') – kompatibilitas.
    """
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
    """
    Shim class untuk event PettyCashFundCreated (tanpa suffix 'Event') – kompatibilitas.
    """
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
    """
    Shim class untuk event PettyCashReplenished (tanpa suffix 'Event') – kompatibilitas.
    """
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


# === ALIAS UNTUK KOMPATIBILITAS DENGAN ROUTER ===
# Router mengimpor dengan suffix "Event"

BankTransferExecutedEvent = BankTransferExecuted
BankTransferExecutedEvent.__name__ = "BankTransferExecutedEvent"

CashReceiptIssuedEvent = CashReceiptIssued
CashReceiptIssuedEvent.__name__ = "CashReceiptIssuedEvent"

CashDisbursementIssuedEvent = CashDisbursementIssued
CashDisbursementIssuedEvent.__name__ = "CashDisbursementIssuedEvent"

PettyCashFundCreatedEvent = PettyCashFundCreated
PettyCashFundCreatedEvent.__name__ = "PettyCashFundCreatedEvent"

PettyCashReplenishedEvent = PettyCashReplenished
PettyCashReplenishedEvent.__name__ = "PettyCashReplenishedEvent"

# Alias untuk domain event dataclass yang sudah punya suffix Event
# Tidak perlu alias tambahan karena sudah ada.

__all__ = [
    # DomainEvent base
    "DomainEvent",
    "DomainEventPublisher",
    "DomainEventType",
    # Bank Account Events (dataclass)
    "BankAccountCreatedEvent",
    "BankAccountUpdatedEvent",
    "BankAccountBlockedEvent",
    "BankAccountClosedEvent",
    # Bank Transaction Events (dataclass)
    "BankTransactionRecordedEvent",
    "BankTransactionClearedEvent",
    "BankTransactionReconciledEvent",
    # Bank Transfer Events (dataclass)
    "BankTransferInitiatedEvent",
    "BankTransferCompletedEvent",
    "BankTransferFailedEvent",
    "BankTransferCancelledEvent",
    # Cash Receipt Events (dataclass)
    "CashReceiptConfirmedEvent",
    "CashReceiptCancelledEvent",
    # Cash Disbursement Events (dataclass)
    "CashDisbursementApprovedEvent",
    "CashDisbursementPaidEvent",
    "CashDisbursementCancelledEvent",
    # Petty Cash Events (dataclass)
    "PettyCashDisbursementEvent",
    "PettyCashReplenishedEvent",
    "PettyCashAdjustedEvent",
    "PettyCashSuspendedEvent",
    "PettyCashActivatedEvent",
    "PettyCashClosedEvent",
    # Reconciliation & Cash Book Events (dataclass)
    "BankReconciliationCompletedEvent",
    "CashBookUpdatedEvent",
    "CashBookClosedEvent",
    # Shim classes (tanpa suffix Event)
    "BankAccountCreated",
    "BankAccountUpdated",
    "BankTransactionRecorded",
    "BankReconciliationCompleted",
    "BankTransferExecuted",
    "CashReceiptIssued",
    "CashDisbursementIssued",
    "PettyCashFundCreated",
    "PettyCashReplenished",
    # Alias dengan suffix Event untuk router
    "BankTransferExecutedEvent",
    "CashReceiptIssuedEvent",
    "CashDisbursementIssuedEvent",
    "PettyCashFundCreatedEvent",
    "PettyCashReplenishedEvent",
]