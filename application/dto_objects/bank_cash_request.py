# bank_cash_request.py - Hardened version with complete implementation

#!/usr/bin/env python3

"""
Module: bank_cash_request.py
Layer: 8 - Application / DTO Objects

Responsibility: Request DTOs untuk Bank & Cash Service.

Fitur:
- Manajemen rekening bank (create, update, get, list)
- Transaksi bank (deposit, withdrawal, transfer)
- Rekonsiliasi bank (start, complete, get status)
- Kas besar / kas kecil (create, top-up, disbursement)
- Petty cash (replenish, get balance)
- Validasi lengkap untuk semua request
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

# ============================================================================
# Constants
# ============================================================================

VALID_BANK_ACCOUNT_TYPES = ["checking", "savings", "deposit", "loan"]
VALID_CURRENCIES = ["IDR", "USD", "EUR", "SGD", "JPY", "CNY"]
VALID_TRANSACTION_TYPES = [
    "deposit",
    "withdrawal",
    "transfer",
    "bank_charge",
    "interest",
    "adjustment",
    "check",
    "electronic",
]
VALID_PAYMENT_METHODS = ["cash", "transfer", "giro", "credit_card", "check"]
VALID_RECONCILIATION_STATUS = ["not_reconciled", "in_progress", "reconciled"]
VALID_CASH_TYPE = ["MAIN_CASH", "PETTY_CASH"]


# ============================================================================
# Bank Account DTOs
# ============================================================================


@dataclass(kw_only=True)
class CreateBankAccountRequest:
    """Request DTO untuk membuat rekening bank baru."""

    legal_entity_id: UUID
    account_number: str
    account_name: str
    bank_name: str
    bank_code: str
    currency_code: str = "IDR"
    account_type: str = "checking"
    opening_balance: Decimal = Decimal(0)
    opening_balance_date: date = field(default_factory=date.today)
    allow_overdraft: bool = False
    overdraft_limit: Decimal = Decimal(0)
    routing_number: str | None = None
    swift_code: str | None = None
    iban: str | None = None
    is_default: bool = False
    notes: str | None = None

    def __post_init__(self) -> None:
        if not self.account_number or len(self.account_number.strip()) < 3:
            raise ValueError("Account number must be at least 3 characters")
        if not self.account_name:
            raise ValueError("Account name is required")
        if not self.bank_name:
            raise ValueError("Bank name is required")
        if not self.bank_code:
            raise ValueError("Bank code is required")
        if self.currency_code not in VALID_CURRENCIES:
            raise ValueError(
                f"Invalid currency: {self.currency_code}. Must be one of {VALID_CURRENCIES}"
            )
        if self.account_type not in VALID_BANK_ACCOUNT_TYPES:
            raise ValueError(
                f"Invalid account type: {self.account_type}. Must be one of {VALID_BANK_ACCOUNT_TYPES}"
            )
        if self.opening_balance < 0:
            raise ValueError(f"Opening balance cannot be negative: {self.opening_balance}")
        if self.allow_overdraft and self.overdraft_limit < 0:
            raise ValueError(f"Overdraft limit must be non-negative: {self.overdraft_limit}")
        if self.opening_balance_date < date(2000, 1, 1):
            raise ValueError(f"Opening balance date is invalid: {self.opening_balance_date}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "account_number": self.account_number,
            "account_name": self.account_name,
            "bank_name": self.bank_name,
            "bank_code": self.bank_code,
            "currency_code": self.currency_code,
            "account_type": self.account_type,
            "opening_balance": str(self.opening_balance),
            "opening_balance_date": self.opening_balance_date.isoformat(),
            "allow_overdraft": self.allow_overdraft,
            "overdraft_limit": str(self.overdraft_limit),
            "routing_number": self.routing_number,
            "swift_code": self.swift_code,
            "iban": self.iban,
            "is_default": self.is_default,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CreateBankAccountRequest:
        return cls(
            legal_entity_id=UUID(data["legal_entity_id"]),
            account_number=data["account_number"],
            account_name=data["account_name"],
            bank_name=data["bank_name"],
            bank_code=data["bank_code"],
            currency_code=data.get("currency_code", "IDR"),
            account_type=data.get("account_type", "checking"),
            opening_balance=Decimal(str(data.get("opening_balance", 0))),
            opening_balance_date=date.fromisoformat(data["opening_balance_date"]),
            allow_overdraft=data.get("allow_overdraft", False),
            overdraft_limit=Decimal(str(data.get("overdraft_limit", 0))),
            routing_number=data.get("routing_number"),
            swift_code=data.get("swift_code"),
            iban=data.get("iban"),
            is_default=data.get("is_default", False),
            notes=data.get("notes"),
        )


@dataclass(kw_only=True)
class UpdateBankAccountRequest:
    """Request DTO untuk update rekening bank."""

    account_id: UUID
    account_name: str | None = None
    status: str | None = None  # active, inactive, closed, frozen
    allow_overdraft: bool | None = None
    overdraft_limit: Decimal | None = None
    is_default: bool | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        if not any(
            [
                self.account_name,
                self.status,
                self.allow_overdraft,
                self.overdraft_limit,
                self.is_default,
                self.notes,
            ]
        ):
            raise ValueError("At least one field to update must be provided")
        if self.status and self.status not in ["active", "inactive", "closed", "frozen"]:
            raise ValueError(
                f"Invalid status: {self.status}. Must be active, inactive, closed, or frozen"
            )
        if self.overdraft_limit is not None and self.overdraft_limit < 0:
            raise ValueError(f"Overdraft limit cannot be negative: {self.overdraft_limit}")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"account_id": str(self.account_id)}
        if self.account_name is not None:
            result["account_name"] = self.account_name
        if self.status is not None:
            result["status"] = self.status
        if self.allow_overdraft is not None:
            result["allow_overdraft"] = self.allow_overdraft
        if self.overdraft_limit is not None:
            result["overdraft_limit"] = str(self.overdraft_limit)
        if self.is_default is not None:
            result["is_default"] = self.is_default
        if self.notes is not None:
            result["notes"] = self.notes
        return result


@dataclass(kw_only=True)
class GetBankAccountRequest:
    """Request DTO untuk mendapatkan detail rekening bank."""

    account_id: UUID
    legal_entity_id: UUID

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": str(self.account_id),
            "legal_entity_id": str(self.legal_entity_id),
        }


@dataclass(kw_only=True)
class ListBankAccountsRequest:
    """Request DTO untuk mendapatkan daftar rekening bank dengan filter."""

    legal_entity_id: UUID
    status: str | None = None
    currency_code: str | None = None
    account_type: str | None = None
    is_default: bool | None = None
    limit: int = 100
    offset: int = 0

    def __post_init__(self) -> None:
        if self.limit < 1 or self.limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        if self.offset < 0:
            raise ValueError("offset must be >= 0")
        if self.status and self.status not in ["active", "inactive", "closed", "frozen"]:
            raise ValueError(f"Invalid status: {self.status}")
        if self.currency_code and self.currency_code not in VALID_CURRENCIES:
            raise ValueError(f"Invalid currency: {self.currency_code}")
        if self.account_type and self.account_type not in VALID_BANK_ACCOUNT_TYPES:
            raise ValueError(f"Invalid account type: {self.account_type}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "status": self.status,
            "currency_code": self.currency_code,
            "account_type": self.account_type,
            "is_default": self.is_default,
            "limit": self.limit,
            "offset": self.offset,
        }


# ============================================================================
# Bank Transaction DTOs
# ============================================================================


@dataclass(kw_only=True)
class DepositRequest:
    """Request DTO untuk setoran tunai/cek ke rekening bank."""

    bank_account_id: UUID
    amount: Decimal
    transaction_date: date
    description: str
    reference_number: str | None = None
    counterparty_name: str | None = None
    check_number: str | None = None
    journal_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise ValueError(f"Deposit amount must be positive: {self.amount}")
        if not self.description:
            raise ValueError("Description is required")
        if self.reference_number and len(self.reference_number) > 50:
            raise ValueError("Reference number too long (max 50 chars)")
        if self.check_number and len(self.check_number) > 20:
            raise ValueError("Check number too long (max 20 chars)")

    def to_dict(self) -> dict[str, Any]:
        return {
            "bank_account_id": str(self.bank_account_id),
            "amount": str(self.amount),
            "transaction_date": self.transaction_date.isoformat(),
            "description": self.description,
            "reference_number": self.reference_number,
            "counterparty_name": self.counterparty_name,
            "check_number": self.check_number,
            "journal_id": str(self.journal_id) if self.journal_id else None,
        }


@dataclass(kw_only=True)
class WithdrawalRequest:
    """Request DTO untuk penarikan dari rekening bank."""

    bank_account_id: UUID
    amount: Decimal
    transaction_date: date
    description: str
    reference_number: str | None = None
    check_number: str | None = None
    journal_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise ValueError(f"Withdrawal amount must be positive: {self.amount}")
        if not self.description:
            raise ValueError("Description is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "bank_account_id": str(self.bank_account_id),
            "amount": str(self.amount),
            "transaction_date": self.transaction_date.isoformat(),
            "description": self.description,
            "reference_number": self.reference_number,
            "check_number": self.check_number,
            "journal_id": str(self.journal_id) if self.journal_id else None,
        }


@dataclass(kw_only=True)
class TransferRequest:
    """Request DTO untuk transfer antar rekening bank (internal)."""

    from_account_id: UUID
    to_account_id: UUID
    amount: Decimal
    transaction_date: date
    description: str
    reference_number: str | None = None

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise ValueError(f"Transfer amount must be positive: {self.amount}")
        if self.from_account_id == self.to_account_id:
            raise ValueError("Source and destination accounts cannot be the same")
        if not self.description:
            raise ValueError("Description is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_account_id": str(self.from_account_id),
            "to_account_id": str(self.to_account_id),
            "amount": str(self.amount),
            "transaction_date": self.transaction_date.isoformat(),
            "description": self.description,
            "reference_number": self.reference_number,
        }


@dataclass(kw_only=True)
class BankChargeRequest:
    """Request DTO untuk biaya administrasi bank."""

    bank_account_id: UUID
    amount: Decimal
    transaction_date: date
    description: str
    reference_number: str | None = None
    journal_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise ValueError(f"Bank charge amount must be positive: {self.amount}")
        if not self.description:
            raise ValueError("Description is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "bank_account_id": str(self.bank_account_id),
            "amount": str(self.amount),
            "transaction_date": self.transaction_date.isoformat(),
            "description": self.description,
            "reference_number": self.reference_number,
            "journal_id": str(self.journal_id) if self.journal_id else None,
        }


@dataclass(kw_only=True)
class InterestRequest:
    """Request DTO untuk bunga bank."""

    bank_account_id: UUID
    amount: Decimal
    transaction_date: date
    description: str
    reference_number: str | None = None
    journal_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise ValueError(f"Interest amount must be positive: {self.amount}")
        if not self.description:
            raise ValueError("Description is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "bank_account_id": str(self.bank_account_id),
            "amount": str(self.amount),
            "transaction_date": self.transaction_date.isoformat(),
            "description": self.description,
            "reference_number": self.reference_number,
            "journal_id": str(self.journal_id) if self.journal_id else None,
        }


# ============================================================================
# Bank Reconciliation DTOs
# ============================================================================


@dataclass(kw_only=True)
class StartReconciliationRequest:
    """Request DTO untuk memulai rekonsiliasi bank."""

    bank_account_id: UUID
    statement_date: date
    statement_balance: Decimal
    statement_balance_source: str = "manual"  # manual, import, api

    def __post_init__(self) -> None:
        if self.statement_balance < 0:
            raise ValueError(f"Statement balance cannot be negative: {self.statement_balance}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "bank_account_id": str(self.bank_account_id),
            "statement_date": self.statement_date.isoformat(),
            "statement_balance": str(self.statement_balance),
            "statement_balance_source": self.statement_balance_source,
        }


@dataclass(kw_only=True)
class CompleteReconciliationRequest:
    """Request DTO untuk menyelesaikan rekonsiliasi bank."""

    bank_account_id: UUID
    reconciliation_id: UUID
    reconciled_by: UUID
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "bank_account_id": str(self.bank_account_id),
            "reconciliation_id": str(self.reconciliation_id),
            "reconciled_by": str(self.reconciled_by),
            "notes": self.notes,
        }


@dataclass(kw_only=True)
class GetReconciliationStatusRequest:
    """Request DTO untuk mendapatkan status rekonsiliasi."""

    bank_account_id: UUID
    legal_entity_id: UUID

    def to_dict(self) -> dict[str, Any]:
        return {
            "bank_account_id": str(self.bank_account_id),
            "legal_entity_id": str(self.legal_entity_id),
        }


# ============================================================================
# Cash Book DTOs
# ============================================================================


@dataclass(kw_only=True)
class CreateCashBookRequest:
    """Request DTO untuk membuat buku kas (main cash atau petty cash)."""

    legal_entity_id: UUID
    currency_code: str = "IDR"
    cash_type: str = "MAIN_CASH"  # MAIN_CASH or PETTY_CASH
    opening_balance: Decimal = Decimal(0)
    opening_balance_date: date = field(default_factory=date.today)
    petty_cash_fund: Decimal | None = None  # For petty cash: fixed fund amount

    def __post_init__(self) -> None:
        if self.currency_code not in VALID_CURRENCIES:
            raise ValueError(f"Invalid currency: {self.currency_code}")
        if self.cash_type not in VALID_CASH_TYPE:
            raise ValueError(
                f"Invalid cash_type: {self.cash_type}. Must be MAIN_CASH or PETTY_CASH"
            )
        if self.opening_balance < 0:
            raise ValueError(f"Opening balance cannot be negative: {self.opening_balance}")
        if self.cash_type == "PETTY_CASH" and self.petty_cash_fund is None:
            raise ValueError("Petty cash requires petty_cash_fund amount")
        if self.petty_cash_fund is not None and self.petty_cash_fund <= 0:
            raise ValueError(f"Petty cash fund must be positive: {self.petty_cash_fund}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "currency_code": self.currency_code,
            "cash_type": self.cash_type,
            "opening_balance": str(self.opening_balance),
            "opening_balance_date": self.opening_balance_date.isoformat(),
            "petty_cash_fund": str(self.petty_cash_fund) if self.petty_cash_fund else None,
        }


@dataclass(kw_only=True)
class CashTransactionRequest:
    """Request DTO untuk transaksi kas (in/out)."""

    cash_book_id: UUID
    amount: Decimal
    transaction_type: str  # CASH_IN or CASH_OUT
    description: str
    reference_type: str  # RECEIPT, DISBURSEMENT, PETTY_CASH
    reference_id: UUID
    journal_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise ValueError(f"Transaction amount must be positive: {self.amount}")
        if self.transaction_type not in ["CASH_IN", "CASH_OUT"]:
            raise ValueError("transaction_type must be CASH_IN or CASH_OUT")
        if not self.description:
            raise ValueError("Description is required")
        if self.reference_type not in ["RECEIPT", "DISBURSEMENT", "PETTY_CASH"]:
            raise ValueError("reference_type must be RECEIPT, DISBURSEMENT, or PETTY_CASH")

    def to_dict(self) -> dict[str, Any]:
        return {
            "cash_book_id": str(self.cash_book_id),
            "amount": str(self.amount),
            "transaction_type": self.transaction_type,
            "description": self.description,
            "reference_type": self.reference_type,
            "reference_id": str(self.reference_id),
            "journal_id": str(self.journal_id) if self.journal_id else None,
        }


@dataclass(kw_only=True)
class PettyCashReplenishRequest:
    """Request DTO untuk mengisi ulang kas kecil (replenish)."""

    cash_book_id: UUID
    amount: Decimal
    description: str
    journal_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise ValueError(f"Replenish amount must be positive: {self.amount}")
        if not self.description:
            raise ValueError("Description is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "cash_book_id": str(self.cash_book_id),
            "amount": str(self.amount),
            "description": self.description,
            "journal_id": str(self.journal_id) if self.journal_id else None,
        }


@dataclass(kw_only=True)
class GetCashBalanceRequest:
    """Request DTO untuk mendapatkan saldo kas."""

    cash_book_id: UUID
    as_of_date: date | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "cash_book_id": str(self.cash_book_id),
            "as_of_date": self.as_of_date.isoformat() if self.as_of_date else None,
        }


# ============================================================================
# Query DTOs
# ============================================================================


@dataclass(kw_only=True)
class GetBankAccountBalanceRequest:
    """Request DTO untuk mendapatkan saldo rekening bank pada tanggal tertentu."""

    bank_account_id: UUID
    as_of_date: date

    def to_dict(self) -> dict[str, Any]:
        return {
            "bank_account_id": str(self.bank_account_id),
            "as_of_date": self.as_of_date.isoformat(),
        }


@dataclass(kw_only=True)
class ListBankTransactionsRequest:
    """Request DTO untuk daftar transaksi bank."""

    bank_account_id: UUID
    from_date: date | None = None
    to_date: date | None = None
    transaction_type: str | None = None
    is_reconciled: bool | None = None
    limit: int = 100
    offset: int = 0

    def __post_init__(self) -> None:
        if self.limit < 1 or self.limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        if self.offset < 0:
            raise ValueError("offset must be >= 0")
        if self.transaction_type and self.transaction_type not in VALID_TRANSACTION_TYPES:
            raise ValueError(f"Invalid transaction_type: {self.transaction_type}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "bank_account_id": str(self.bank_account_id),
            "from_date": self.from_date.isoformat() if self.from_date else None,
            "to_date": self.to_date.isoformat() if self.to_date else None,
            "transaction_type": self.transaction_type,
            "is_reconciled": self.is_reconciled,
            "limit": self.limit,
            "offset": self.offset,
        }


# ============================================================================
# Factory
# ============================================================================


class BankCashRequestFactory:
    """Factory untuk membuat Bank & Cash Request DTOs."""

    @staticmethod
    def create_bank_account(
        legal_entity_id: UUID,
        account_number: str,
        account_name: str,
        bank_name: str,
        bank_code: str,
        currency_code: str = "IDR",
        account_type: str = "checking",
        opening_balance: Decimal = Decimal(0),
    ) -> CreateBankAccountRequest:
        return CreateBankAccountRequest(
            legal_entity_id=legal_entity_id,
            account_number=account_number,
            account_name=account_name,
            bank_name=bank_name,
            bank_code=bank_code,
            currency_code=currency_code,
            account_type=account_type,
            opening_balance=opening_balance,
        )

    @staticmethod
    def create_deposit(
        bank_account_id: UUID,
        amount: Decimal,
        transaction_date: date,
        description: str,
        reference_number: str | None = None,
    ) -> DepositRequest:
        return DepositRequest(
            bank_account_id=bank_account_id,
            amount=amount,
            transaction_date=transaction_date,
            description=description,
            reference_number=reference_number,
        )

    @staticmethod
    def create_withdrawal(
        bank_account_id: UUID,
        amount: Decimal,
        transaction_date: date,
        description: str,
        reference_number: str | None = None,
    ) -> WithdrawalRequest:
        return WithdrawalRequest(
            bank_account_id=bank_account_id,
            amount=amount,
            transaction_date=transaction_date,
            description=description,
            reference_number=reference_number,
        )

    @staticmethod
    def create_transfer(
        from_account_id: UUID,
        to_account_id: UUID,
        amount: Decimal,
        transaction_date: date,
        description: str,
    ) -> TransferRequest:
        return TransferRequest(
            from_account_id=from_account_id,
            to_account_id=to_account_id,
            amount=amount,
            transaction_date=transaction_date,
            description=description,
        )

    @staticmethod
    def create_cash_book(
        legal_entity_id: UUID,
        cash_type: str = "MAIN_CASH",
        currency_code: str = "IDR",
        opening_balance: Decimal = Decimal(0),
        petty_cash_fund: Decimal | None = None,
    ) -> CreateCashBookRequest:
        return CreateCashBookRequest(
            legal_entity_id=legal_entity_id,
            currency_code=currency_code,
            cash_type=cash_type,
            opening_balance=opening_balance,
            petty_cash_fund=petty_cash_fund,
        )


# ============================================================================
# Compatibility Aliases
# ============================================================================

BankAccountRequest = CreateBankAccountRequest
BankAccountUpdateRequest = UpdateBankAccountRequest
BankDepositRequest = DepositRequest
BankWithdrawalRequest = WithdrawalRequest
BankTransferRequest = TransferRequest
BankReconciliationStartRequest = StartReconciliationRequest
BankReconciliationCompleteRequest = CompleteReconciliationRequest
BankReconciliationRequestDTO = StartReconciliationRequest
PettyCashRequest = PettyCashReplenishRequest


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    # Constants
    "VALID_BANK_ACCOUNT_TYPES",
    "VALID_CASH_TYPE",
    "VALID_CURRENCIES",
    "VALID_PAYMENT_METHODS",
    "VALID_RECONCILIATION_STATUS",
    "VALID_TRANSACTION_TYPES",
    "BankAccountRequest",
    "BankAccountUpdateRequest",
    # Factory
    "BankCashRequestFactory",
    "BankChargeRequest",
    "BankDepositRequest",
    "BankReconciliationCompleteRequest",
    "BankReconciliationRequestDTO",
    "BankReconciliationStartRequest",
    "BankTransferRequest",
    "BankWithdrawalRequest",
    "CashTransactionRequest",
    "CompleteReconciliationRequest",
    # Bank Account
    "CreateBankAccountRequest",
    # Cash Book
    "CreateCashBookRequest",
    # Transactions
    "DepositRequest",
    # Query
    "GetBankAccountBalanceRequest",
    "GetBankAccountRequest",
    "GetCashBalanceRequest",
    "GetReconciliationStatusRequest",
    "InterestRequest",
    "ListBankAccountsRequest",
    "ListBankTransactionsRequest",
    "PettyCashReplenishRequest",
    "PettyCashRequest",
    # Reconciliation
    "StartReconciliationRequest",
    "TransferRequest",
    "UpdateBankAccountRequest",
    "WithdrawalRequest",
]
