#!/usr/bin/env python3
"""
Module: bank_cash_repository_port.py
Layer: Ports (Primary)
Responsibility: Implementasi in-memory repository untuk Bank Account dan Cash Book.
               Mendukung rekening bank, buku kas, rekonsiliasi bank, transaksi transfer,
               petty cash, cash receipts/disbursements, audit trail, dan statistik.
Audit: Setiap perubahan pada rekening bank, transaksi, dan rekonsiliasi tercatat.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class BankAccountType(Enum):
    """Jenis rekening bank."""

    CHECKING = "checking"  # Giro
    SAVINGS = "savings"  # Tabungan
    DEPOSIT = "deposit"  # Deposito
    LOAN = "loan"  # Pinjaman (utang bank)


class BankAccountStatus(Enum):
    """Status rekening bank."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    CLOSED = "closed"
    FROZEN = "frozen"


class TransactionType(Enum):
    """Jenis transaksi bank."""

    DEPOSIT = "deposit"  # Setoran
    WITHDRAWAL = "withdrawal"  # Penarikan
    TRANSFER = "transfer"  # Transfer antar rekening
    BANK_CHARGE = "bank_charge"  # Biaya bank
    INTEREST = "interest"  # Bunga
    ADJUSTMENT = "adjustment"  # Koreksi
    CHECK = "check"  # Cek
    ELECTRONIC = "electronic"  # Transfer elektronik (EDI)


class ReconciliationStatus(Enum):
    """Status rekonsiliasi bank."""

    NOT_RECONCILED = "not_reconciled"
    IN_PROGRESS = "in_progress"
    RECONCILED = "reconciled"


@dataclass
class BankAccount:
    """
    Aggregate Root Bank Account.
    """

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
    statement_balance: Decimal  # Saldo menurut laporan bank terakhir
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
            "current_balance": float(self.current_balance),
            "available_balance": float(self.available_balance),
            "statement_balance": float(self.statement_balance),
            "last_statement_date": self.last_statement_date.isoformat()
            if self.last_statement_date
            else None,
            "status": self.status.value,
            "reconciliation_status": self.reconciliation_status.value,
            "reconciliation_date": self.reconciliation_date.isoformat()
            if self.reconciliation_date
            else None,
            "opening_balance": float(self.opening_balance),
            "opening_balance_date": self.opening_balance_date.isoformat(),
            "is_default": self.is_default,
            "routing_number": self.routing_number,
            "swift_code": self.swift_code,
            "iban": self.iban,
            "notes": self.notes,
        }


@dataclass
class BankTransaction:
    """
    Transaksi bank individual.
    """

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
    is_cleared: bool = False  # Telah dicairkan/kliring
    cleared_date: date | None = None
    is_reconciled: bool = False
    reconciled_date: date | None = None
    reconciled_by: UUID | None = None
    journal_id: UUID | None = None  # Journal entry yang terkait
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID = field(default_factory=lambda: UUID(int=0))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "bank_account_id": str(self.bank_account_id),
            "transaction_date": self.transaction_date.isoformat(),
            "transaction_type": self.transaction_type.value,
            "amount": float(self.amount),
            "balance_after": float(self.balance_after),
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
    """
    Buku kas (cash book) untuk kas besar/kas kecil.
    """

    id: UUID
    legal_entity_id: UUID
    currency_code: str
    cash_type: str  # "MAIN_CASH", "PETTY_CASH"
    current_balance: Decimal
    opening_balance: Decimal
    opening_balance_date: date
    petty_cash_fund: Decimal | None = None  # Untuk kas kecil: dana tetap
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID = field(default_factory=lambda: UUID(int=0))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_by: UUID = field(default_factory=lambda: UUID(int=0))


@dataclass
class CashTransaction:
    """
    Transaksi kas (cash in/out).
    """

    id: UUID
    cash_book_id: UUID
    transaction_date: date
    transaction_type: str  # "CASH_IN", "CASH_OUT"
    amount: Decimal
    description: str
    reference_type: str  # "RECEIPT", "DISBURSEMENT", "PETTY_CASH"
    reference_id: UUID
    journal_id: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID = field(default_factory=lambda: UUID(int=0))


class BankAccountRepositoryPort:
    """
    Repository untuk Bank Account.
    """

    def __init__(self):
        self._accounts: dict[UUID, BankAccount] = {}
        self._transactions: list[BankTransaction] = []
        self._number_index: dict[tuple[str, str], BankAccount] = {}  # (account_number, bank_code)
        self._audit_log: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    async def _log_audit(
        self, action: str, account_id: UUID, user_id: UUID, details: dict[str, Any]
    ):
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "account_id": str(account_id),
            "user_id": str(user_id),
            "details": details,
        }
        self._audit_log.append(entry)
        logger.info(f"BANK AUDIT: {action} on {account_id} by {user_id}")

    async def add(self, bank_account: BankAccount) -> None:
        if bank_account.id in self._accounts:
            raise ValueError(f"Account {bank_account.id} already exists")
        key = (bank_account.account_number, bank_account.bank_code)
        if key in self._number_index:
            raise ValueError(
                f"Account number {bank_account.account_number} at {bank_account.bank_code} already exists"
            )
        bank_account.created_at = datetime.now(UTC)
        bank_account.updated_at = bank_account.created_at
        bank_account.version = 1
        async with self._lock:
            self._accounts[bank_account.id] = bank_account
            self._number_index[key] = bank_account
        await self._log_audit(
            "ADD",
            bank_account.id,
            bank_account.created_by,
            {
                "account_number": bank_account.account_number,
                "bank": bank_account.bank_name,
            },
        )

    async def get_by_id(self, account_id: UUID) -> BankAccount | None:
        return self._accounts.get(account_id)

    async def get_by_account_number(
        self, account_number: str, bank_code: str
    ) -> BankAccount | None:
        return self._number_index.get((account_number, bank_code))

    async def update(self, bank_account: BankAccount) -> None:
        if bank_account.id not in self._accounts:
            raise ValueError(f"Account {bank_account.id} not found")
        old = self._accounts[bank_account.id]
        old_key = (old.account_number, old.bank_code)
        new_key = (bank_account.account_number, bank_account.bank_code)
        if old_key != new_key:
            del self._number_index[old_key]
            self._number_index[new_key] = bank_account
        bank_account.updated_at = datetime.now(UTC)
        bank_account.version = old.version + 1
        bank_account.created_at = old.created_at
        bank_account.created_by = old.created_by
        self._accounts[bank_account.id] = bank_account
        await self._log_audit(
            "UPDATE",
            bank_account.id,
            bank_account.updated_by,
            {
                "balance_change": float(bank_account.current_balance - old.current_balance)
                if bank_account.current_balance != old.current_balance
                else 0,
            },
        )

    async def delete(self, account_id: UUID, user_id: UUID, permanent: bool = False) -> bool:
        account = self._accounts.get(account_id)
        if not account:
            return False
        if permanent:
            key = (account.account_number, account.bank_code)
            if key in self._number_index:
                del self._number_index[key]
            del self._accounts[account_id]
        else:
            account.status = BankAccountStatus.CLOSED
            account.updated_at = datetime.now(UTC)
            account.updated_by = user_id
            account.version += 1
            await self.update(account)
        await self._log_audit("DELETE", account_id, user_id, {"permanent": permanent})
        return True

    async def find_by_legal_entity(self, legal_entity_id: UUID) -> list[BankAccount]:
        return [acc for acc in self._accounts.values() if acc.legal_entity_id == legal_entity_id]

    async def get_balance(self, bank_account_id: UUID, as_of_date: date) -> Decimal:
        """Saldo rekening pada tanggal tertentu berdasarkan transaksi."""
        account = await self.get_by_id(bank_account_id)
        if not account:
            raise ValueError("Account not found")
        if as_of_date < account.opening_balance_date:
            return Decimal(0)
        # Starting from opening balance
        balance = account.opening_balance
        for tx in self._transactions:
            if tx.bank_account_id == bank_account_id and tx.transaction_date <= as_of_date:
                if tx.transaction_type in (
                    TransactionType.DEPOSIT,
                    TransactionType.INTEREST,
                    TransactionType.TRANSFER,
                ):
                    balance += tx.amount
                else:
                    balance -= tx.amount
        return balance

    async def record_transaction(self, transaction: BankTransaction) -> None:
        """Mencatat transaksi bank dan update saldo akun."""
        account = await self.get_by_id(transaction.bank_account_id)
        if not account:
            raise ValueError(f"Bank account {transaction.bank_account_id} not found")
        # Update saldo akun berdasarkan transaksi
        if transaction.transaction_type in (TransactionType.DEPOSIT, TransactionType.INTEREST):
            account.current_balance += transaction.amount
            account.available_balance += transaction.amount
        elif transaction.transaction_type in (
            TransactionType.WITHDRAWAL,
            TransactionType.BANK_CHARGE,
        ):
            account.current_balance -= transaction.amount
            account.available_balance -= transaction.amount
        elif transaction.transaction_type == TransactionType.TRANSFER:
            # Transfer: amount positif untuk incoming, negatif untuk outgoing
            if transaction.amount > 0:
                account.current_balance += transaction.amount
                account.available_balance += transaction.amount
            else:
                account.current_balance -= abs(transaction.amount)
                account.available_balance -= abs(transaction.amount)
        transaction.balance_after = account.current_balance
        transaction.created_at = datetime.now(UTC)
        self._transactions.append(transaction)
        await self.update(account)
        await self._log_audit(
            "RECORD_TX",
            account.id,
            transaction.created_by,
            {
                "tx_type": transaction.transaction_type.value,
                "amount": float(transaction.amount),
            },
        )

    async def get_transactions(
        self, bank_account_id: UUID, start_date: date, end_date: date
    ) -> list[BankTransaction]:
        return [
            tx
            for tx in self._transactions
            if tx.bank_account_id == bank_account_id
            and start_date <= tx.transaction_date <= end_date
        ]

    async def reconcile(
        self,
        bank_account_id: UUID,
        statement_date: date,
        statement_balance: Decimal,
        user_id: UUID,
        journal_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Rekonsiliasi bank: mencocokkan transaksi internal dengan statement."""
        account = await self.get_by_id(bank_account_id)
        if not account:
            raise ValueError("Account not found")
        # Hitung transaksi yang belum direkonsiliasi
        unreconciled = [
            tx
            for tx in self._transactions
            if tx.bank_account_id == bank_account_id
            and not tx.is_reconciled
            and tx.transaction_date <= statement_date
        ]
        total_unreconciled = sum(
            tx.amount
            for tx in unreconciled
            if tx.transaction_type in (TransactionType.DEPOSIT, TransactionType.INTEREST)
        ) - sum(
            tx.amount
            for tx in unreconciled
            if tx.transaction_type in (TransactionType.WITHDRAWAL, TransactionType.BANK_CHARGE)
        )
        # Hitung saldo menurut sistem
        system_balance = account.opening_balance
        for tx in sorted(self._transactions, key=lambda x: x.transaction_date):
            if tx.bank_account_id == bank_account_id and tx.transaction_date <= statement_date:
                if tx.transaction_type in (TransactionType.DEPOSIT, TransactionType.INTEREST):
                    system_balance += tx.amount
                else:
                    system_balance -= tx.amount
        difference = statement_balance - system_balance
        # Tandai transaksi sebagai reconciled
        for tx in unreconciled:
            tx.is_reconciled = True
            tx.reconciled_date = statement_date
            tx.reconciled_by = user_id
        # Update akun
        account.statement_balance = statement_balance
        account.last_statement_date = statement_date
        account.reconciliation_status = ReconciliationStatus.RECONCILED
        account.reconciliation_date = statement_date
        account.updated_by = user_id
        await self.update(account)
        await self._log_audit(
            "RECONCILE",
            account.id,
            user_id,
            {
                "statement_date": statement_date.isoformat(),
                "statement_balance": float(statement_balance),
                "system_balance": float(system_balance),
                "difference": float(difference),
            },
        )
        return {
            "account_id": str(account.id),
            "statement_date": statement_date.isoformat(),
            "statement_balance": float(statement_balance),
            "system_balance": float(system_balance),
            "difference": float(difference),
            "transactions_reconciled": len(unreconciled),
        }

    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        accounts = [
            acc for acc in self._accounts.values() if acc.legal_entity_id == legal_entity_id
        ]
        total_balance = sum(acc.current_balance for acc in accounts)
        return {
            "total_accounts": len(accounts),
            "total_balance": float(total_balance),
            "active_accounts": sum(1 for acc in accounts if acc.status == BankAccountStatus.ACTIVE),
            "by_currency": {},
            "by_type": {},
        }


class CashBookRepositoryPort:
    """
    Repository untuk Cash Book (kas besar dan kas kecil).
    """

    def __init__(self):
        self._cash_books: dict[UUID, CashBook] = {}
        self._cash_transactions: list[CashTransaction] = []
        self._audit_log: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    async def _log_audit(
        self, action: str, cash_book_id: UUID, user_id: UUID, details: dict[str, Any]
    ):
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "cash_book_id": str(cash_book_id),
            "user_id": str(user_id),
            "details": details,
        }
        self._audit_log.append(entry)
        logger.info(f"CASH AUDIT: {action} on {cash_book_id} by {user_id}")

    async def add(self, cash_book: CashBook) -> None:
        if cash_book.id in self._cash_books:
            raise ValueError(f"CashBook {cash_book.id} already exists")
        cash_book.created_at = datetime.now(UTC)
        cash_book.updated_at = cash_book.created_at
        self._cash_books[cash_book.id] = cash_book
        await self._log_audit(
            "ADD", cash_book.id, cash_book.created_by, {"type": cash_book.cash_type}
        )

    async def get_by_id(self, cash_book_id: UUID) -> CashBook | None:
        return self._cash_books.get(cash_book_id)

    async def get_by_legal_entity_and_currency(
        self, legal_entity_id: UUID, currency: str, cash_type: str = "MAIN_CASH"
    ) -> CashBook | None:
        for cb in self._cash_books.values():
            if (
                cb.legal_entity_id == legal_entity_id
                and cb.currency_code == currency
                and cb.cash_type == cash_type
            ):
                return cb
        return None

    async def update(self, cash_book: CashBook) -> None:
        if cash_book.id not in self._cash_books:
            raise ValueError(f"CashBook {cash_book.id} not found")
        old = self._cash_books[cash_book.id]
        cash_book.updated_at = datetime.now(UTC)
        cash_book.created_at = old.created_at
        cash_book.created_by = old.created_by
        self._cash_books[cash_book.id] = cash_book
        await self._log_audit(
            "UPDATE",
            cash_book.id,
            cash_book.updated_by,
            {"balance": float(cash_book.current_balance)},
        )

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
        """Mencatat transaksi kas dan update saldo cash book."""
        cash_book = await self.get_by_id(cash_book_id)
        if not cash_book:
            raise ValueError(f"CashBook {cash_book_id} not found")
        if transaction_type not in ("CASH_IN", "CASH_OUT"):
            raise ValueError("transaction_type must be CASH_IN or CASH_OUT")
        if transaction_type == "CASH_IN":
            cash_book.current_balance += amount
        else:
            if amount > cash_book.current_balance:
                raise ValueError("Insufficient cash balance")
            cash_book.current_balance -= amount
        tx = CashTransaction(
            id=uuid4(),
            cash_book_id=cash_book_id,
            transaction_date=date.today(),
            transaction_type=transaction_type,
            amount=amount,
            description=description,
            reference_type=reference_type,
            reference_id=reference_id,
            journal_id=journal_id,
            created_at=datetime.now(UTC),
            created_by=user_id,
        )
        self._cash_transactions.append(tx)
        await self.update(cash_book)
        await self._log_audit(
            "RECORD_TX",
            cash_book_id,
            user_id,
            {
                "type": transaction_type,
                "amount": float(amount),
                "reference": reference_type,
            },
        )
        return tx

    async def get_balance(self, cash_book_id: UUID, as_of_date: date) -> Decimal:
        cash_book = await self.get_by_id(cash_book_id)
        if not cash_book:
            raise ValueError("CashBook not found")
        # Mulai dari opening balance
        balance = cash_book.opening_balance
        for tx in self._cash_transactions:
            if tx.cash_book_id == cash_book_id and tx.transaction_date <= as_of_date:
                if tx.transaction_type == "CASH_IN":
                    balance += tx.amount
                else:
                    balance -= tx.amount
        return balance

    async def get_transactions(
        self, cash_book_id: UUID, start_date: date, end_date: date
    ) -> list[CashTransaction]:
        return [
            tx
            for tx in self._cash_transactions
            if tx.cash_book_id == cash_book_id and start_date <= tx.transaction_date <= end_date
        ]


# ============================================================================
# ALIAS UNTUK KOMPATIBILITAS DENGAN SERVICE LAYER
# ============================================================================
# service_bank_cash.py mengimpor 'BankCashRepositoryPort'
# Jadi kita buat alias:
BankCashRepositoryPort = BankAccountRepositoryPort


# ============================================================================
# EXPORTS
# ============================================================================
__all__ = [
    "BankAccount",
    "BankAccountRepositoryPort",
    "BankAccountStatus",
    "BankAccountType",
    "BankCashRepositoryPort",  # alias untuk service layer
    "BankTransaction",
    "CashBook",
    "CashBookRepositoryPort",
    "CashTransaction",
    "ReconciliationStatus",
    "TransactionType",
]
