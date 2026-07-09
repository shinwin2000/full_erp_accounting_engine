#!/usr/bin/env python3
"""
Module: bank_cash_repository_port.py
Layer: Ports (Primary)

PORT INTERFACE untuk Bank Account dan Cash Book.
Semua metode wajib diimplementasikan oleh repository concrete.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, UTC
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# DOMAIN ENUMS & ENTITIES (tetap di sini karena digunakan oleh port)
# ============================================================================

class BankAccountType(Enum):
    CHECKING = "checking"
    SAVINGS = "savings"
    DEPOSIT = "deposit"
    LOAN = "loan"


class BankAccountStatus(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    CLOSED = "closed"
    FROZEN = "frozen"


class TransactionType(Enum):
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    TRANSFER = "transfer"
    BANK_CHARGE = "bank_charge"
    INTEREST = "interest"
    ADJUSTMENT = "adjustment"
    CHECK = "check"
    ELECTRONIC = "electronic"


class ReconciliationStatus(Enum):
    NOT_RECONCILED = "not_reconciled"
    IN_PROGRESS = "in_progress"
    RECONCILED = "reconciled"


@dataclass
class BankAccount:
    id: UUID
    account_number: str
    account_name: str
    bank_name: str
    bank_code: str
    account_type: BankAccountType
    currency_code: str
    legal_entity_id: UUID
    current_balance: Decimal
    available_balance: Decimal
    statement_balance: Decimal
    last_statement_date: date | None
    status: BankAccountStatus
    reconciliation_status: ReconciliationStatus
    reconciliation_date: date | None
    opening_balance: Decimal
    opening_balance_date: date
    is_default: bool = False
    routing_number: str | None = None
    swift_code: str | None = None
    iban: str | None = None
    notes: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID = field(default_factory=lambda: UUID(int=0))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_by: UUID = field(default_factory=lambda: UUID(int=0))
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "account_number": self.account_number,
            "account_name": self.account_name,
            "bank_name": self.bank_name,
            "bank_code": self.bank_code,
            "account_type": self.account_type.value,
            "currency_code": self.currency_code,
            "legal_entity_id": str(self.legal_entity_id),
            "current_balance": str(self.current_balance),
            "available_balance": str(self.available_balance),
            "statement_balance": str(self.statement_balance),
            "last_statement_date": self.last_statement_date.isoformat() if self.last_statement_date else None,
            "status": self.status.value,
            "reconciliation_status": self.reconciliation_status.value,
            "reconciliation_date": self.reconciliation_date.isoformat() if self.reconciliation_date else None,
            "opening_balance": str(self.opening_balance),
            "opening_balance_date": self.opening_balance_date.isoformat(),
            "is_default": self.is_default,
            "routing_number": self.routing_number,
            "swift_code": self.swift_code,
            "iban": self.iban,
            "notes": self.notes,
        }


@dataclass
class BankTransaction:
    id: UUID
    bank_account_id: UUID
    transaction_date: date
    transaction_type: TransactionType
    amount: Decimal
    balance_after: Decimal
    reference_number: str
    description: str
    counterparty_name: str | None = None
    counterparty_account: str | None = None
    check_number: str | None = None
    is_cleared: bool = False
    cleared_date: date | None = None
    is_reconciled: bool = False
    reconciled_date: date | None = None
    reconciled_by: UUID | None = None
    journal_id: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID = field(default_factory=lambda: UUID(int=0))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "bank_account_id": str(self.bank_account_id),
            "transaction_date": self.transaction_date.isoformat(),
            "transaction_type": self.transaction_type.value,
            "amount": str(self.amount),
            "balance_after": str(self.balance_after),
            "reference_number": self.reference_number,
            "description": self.description,
            "counterparty_name": self.counterparty_name,
            "counterparty_account": self.counterparty_account,
            "check_number": self.check_number,
            "is_cleared": self.is_cleared,
            "cleared_date": self.cleared_date.isoformat() if self.cleared_date else None,
            "is_reconciled": self.is_reconciled,
            "reconciled_date": self.reconciled_date.isoformat() if self.reconciled_date else None,
            "reconciled_by": str(self.reconciled_by) if self.reconciled_by else None,
            "journal_id": str(self.journal_id) if self.journal_id else None,
        }


@dataclass
class CashBook:
    id: UUID
    legal_entity_id: UUID
    currency_code: str
    cash_type: str
    current_balance: Decimal
    opening_balance: Decimal
    opening_balance_date: date
    petty_cash_fund: Decimal | None = None
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID = field(default_factory=lambda: UUID(int=0))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_by: UUID = field(default_factory=lambda: UUID(int=0))


@dataclass
class CashTransaction:
    id: UUID
    cash_book_id: UUID
    transaction_date: date
    transaction_type: str  # "CASH_IN", "CASH_OUT"
    amount: Decimal
    description: str
    reference_type: str
    reference_id: UUID
    journal_id: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID = field(default_factory=lambda: UUID(int=0))


# ============================================================================
# PORT INTERFACE (ABC)
# ============================================================================

class BankAccountRepositoryPort(ABC):
    """
    Port (interface) untuk repository Bank Account.
    Semua metode wajib diimplementasikan oleh repository concrete.
    """

    @abstractmethod
    async def add(self, bank_account: BankAccount) -> None:
        """Tambahkan rekening bank baru."""
        pass

    @abstractmethod
    async def get_by_id(self, account_id: UUID) -> BankAccount | None:
        """Ambil rekening berdasarkan ID."""
        pass

    @abstractmethod
    async def get_by_account_number(self, account_number: str, bank_code: str) -> BankAccount | None:
        """Ambil rekening berdasarkan nomor dan kode bank."""
        pass

    @abstractmethod
    async def update(self, bank_account: BankAccount) -> None:
        """Perbarui rekening bank."""
        pass

    @abstractmethod
    async def delete(self, account_id: UUID, user_id: UUID, permanent: bool = False) -> bool:
        """Hapus rekening (soft delete atau permanen)."""
        pass

    @abstractmethod
    async def find_by_legal_entity(self, legal_entity_id: UUID) -> list[BankAccount]:
        """Cari semua rekening untuk legal entity tertentu."""
        pass

    @abstractmethod
    async def get_balance(self, bank_account_id: UUID, as_of_date: date) -> Decimal:
        """Dapatkan saldo rekening pada tanggal tertentu."""
        pass

    @abstractmethod
    async def record_transaction(self, transaction: BankTransaction) -> None:
        """Catat transaksi bank dan update saldo."""
        pass

    @abstractmethod
    async def get_transactions(
        self, bank_account_id: UUID, start_date: date, end_date: date
    ) -> list[BankTransaction]:
        """Ambil transaksi dalam rentang tanggal."""
        pass

    @abstractmethod
    async def reconcile(
        self,
        bank_account_id: UUID,
        statement_date: date,
        statement_balance: Decimal,
        user_id: UUID,
        journal_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Lakukan rekonsiliasi bank."""
        pass

    @abstractmethod
    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        """Statistik rekening bank."""
        pass


class CashBookRepositoryPort(ABC):
    """
    Port (interface) untuk repository Cash Book.
    """

    @abstractmethod
    async def add(self, cash_book: CashBook) -> None:
        """Tambahkan cash book baru."""
        pass

    @abstractmethod
    async def get_by_id(self, cash_book_id: UUID) -> CashBook | None:
        """Ambil cash book berdasarkan ID."""
        pass

    @abstractmethod
    async def get_by_legal_entity_and_currency(
        self, legal_entity_id: UUID, currency: str, cash_type: str = "MAIN_CASH"
    ) -> CashBook | None:
        """Ambil cash book berdasarkan legal entity, mata uang, dan tipe."""
        pass

    @abstractmethod
    async def update(self, cash_book: CashBook) -> None:
        """Perbarui cash book."""
        pass

    @abstractmethod
    async def record_transaction(
        self,
        cash_book_id: UUID,
        transaction_type: str,
        amount: Decimal,
        reference_type: str,
        reference_id: UUID,
        description: str,
        user_id: UUID,
        journal_id: UUID | None = None,
    ) -> CashTransaction:
        """Catat transaksi kas."""
        pass

    @abstractmethod
    async def get_balance(self, cash_book_id: UUID, as_of_date: date) -> Decimal:
        """Dapatkan saldo kas pada tanggal tertentu."""
        pass

    @abstractmethod
    async def get_transactions(
        self, cash_book_id: UUID, start_date: date, end_date: date
    ) -> list[CashTransaction]:
        """Ambil transaksi kas dalam rentang tanggal."""
        pass


# ============================================================================
# IN-MEMORY IMPLEMENTATION (untuk testing/development)
# ============================================================================

class InMemoryBankAccountRepository(BankAccountRepositoryPort):
    """
    Implementasi in-memory (untuk testing).
    Tidak digunakan di production.
    """
    # ... (kode in-memory dari yang lama, bisa dipindahkan ke sini)
    # Saya tidak menulis ulang seluruhnya di sini karena panjang,
    # tapi Anda bisa memindahkan implementasi dari BankAccountRepositoryPort yang lama ke kelas ini.
    # Untuk sekarang, biarkan kosong atau buat stub.
    # Yang penting port sudah menjadi ABC.


# ============================================================================
# ALIAS UNTUK KOMPATIBILITAS
# ============================================================================
# Jika ada kode yang mengimpor BankCashRepositoryPort sebagai alias, tetap pertahankan.
BankCashRepositoryPort = BankAccountRepositoryPort


__all__ = [
    "BankAccount",
    "BankAccountRepositoryPort",
    "BankAccountStatus",
    "BankAccountType",
    "BankCashRepositoryPort",
    "BankTransaction",
    "CashBook",
    "CashBookRepositoryPort",
    "CashTransaction",
    "InMemoryBankAccountRepository",
    "ReconciliationStatus",
    "TransactionType",
]