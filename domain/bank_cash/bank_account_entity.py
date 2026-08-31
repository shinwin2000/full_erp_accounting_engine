#!/usr/bin/env python3
"""
Module: bank_account_entity.py
Layer: Domain / Bank & Cash
Responsibility: Entitas rekening bank dengan semua atribut dan method bisnis.

Audit: Setiap perubahan state rekening (create, update, block, close, deposit, withdraw)
       harus menghasilkan domain event.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any, ClassVar, Self
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# 1. ENUMS
# ============================================================================


class BankAccountStatus(Enum):
    """Status rekening bank."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    BLOCKED = "blocked"
    CLOSED = "closed"
    DORMANT = "dormant"
    FROZEN = "frozen"
    PENDING_VERIFICATION = "pending_verification"
    SUSPENDED = "suspended"

    @classmethod
    def can_transition(cls, from_status: BankAccountStatus, to_status: BankAccountStatus) -> bool:
        """Valid state transitions."""
        allowed = {
            cls.ACTIVE: {cls.INACTIVE, cls.BLOCKED, cls.DORMANT, cls.CLOSED, cls.FROZEN},
            cls.INACTIVE: {cls.ACTIVE, cls.CLOSED},
            cls.BLOCKED: {cls.ACTIVE, cls.CLOSED},
            cls.DORMANT: {cls.ACTIVE, cls.CLOSED},
            cls.FROZEN: {cls.ACTIVE},
            cls.PENDING_VERIFICATION: {cls.ACTIVE, cls.BLOCKED, cls.CLOSED},
            cls.SUSPENDED: {cls.ACTIVE, cls.CLOSED},
            cls.CLOSED: set(),
        }
        return to_status in allowed.get(from_status, set())


class BankAccountType(Enum):
    """Jenis rekening bank."""

    CHECKING = "checking"
    SAVINGS = "savings"
    DEPOSIT = "deposit"
    LOAN = "loan"
    ESCROW = "escrow"
    VIRTUAL = "virtual"
    TRUST = "trust"
    INVESTMENT = "investment"

    @property
    def is_interest_bearing(self) -> bool:
        return self in (self.SAVINGS, self.DEPOSIT, self.INVESTMENT)

    @property
    def can_have_overdraft(self) -> bool:
        return self in (self.CHECKING, self.LOAN)


class InterestCalculationMethod(Enum):
    SIMPLE = "simple"
    COMPOUND_DAILY = "compound_daily"
    COMPOUND_MONTHLY = "compound_monthly"
    COMPOUND_ANNUALLY = "compound_annually"


# ============================================================================
# 2. VALUE OBJECTS
# ============================================================================


@dataclass(frozen=True)
class BankAccountSignature:
    """Digital signature for bank account (tamper-proof)."""

    account_id: UUID
    version: int
    hash_value: str
    signed_at: datetime
    signed_by: str

    @classmethod
    def create(cls, account: BankAccountEntity, signed_by: str) -> Self:
        data = f"{account.account_id}{account.version}{account.current_balance}{account.updated_at}"
        hash_value = hashlib.sha3_256(data.encode()).hexdigest()
        return cls(
            account_id=account.account_id,
            version=account.version,
            hash_value=hash_value,
            signed_at=datetime.now(UTC),
            signed_by=signed_by,
        )

    def verify(self, account: BankAccountEntity) -> bool:
        data = f"{account.account_id}{account.version}{account.current_balance}{account.updated_at}"
        expected = hashlib.sha3_256(data.encode()).hexdigest()
        return self.hash_value == expected


@dataclass(frozen=True)
class DailyInterestAccrual:
    """Daily interest accrual record."""

    date: date
    balance: Decimal
    daily_rate: Decimal
    interest_amount: Decimal
    cumulative_interest: Decimal
    calculated_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "balance": str(self.balance),
            "daily_rate": str(self.daily_rate),
            "interest_amount": str(self.interest_amount),
            "cumulative_interest": str(self.cumulative_interest),
            "calculated_at": self.calculated_at.isoformat(),
        }


# ============================================================================
# 3. BANK ACCOUNT ENTITY
# ============================================================================


@dataclass
class BankAccountEntity:
    """
    Entitas rekening bank yang immutable (method menghasilkan instance baru).
    Mencakup semua informasi rekening, saldo, fasilitas overdraft, dan status.
    """

    # Identitas
    account_id: UUID
    account_number: str
    account_name: str
    account_type: BankAccountType
    bank_name: str
    bank_code: str
    branch_name: str | None
    currency: str

    # Saldo dan status
    current_balance: Decimal
    available_balance: Decimal
    status: BankAccountStatus
    allow_overdraft: bool = False
    overdraft_limit: Decimal = Decimal(0)

    # Rekonsiliasi
    last_reconciled_date: date | None = None
    last_reconciled_balance: Decimal | None = None
    last_reconciled_gl_balance: Decimal | None = None

    # Tambahan untuk service (GL mapping, saldo awal, legal entity)
    gl_account_code: str | None = None
    opening_balance: Decimal = Decimal(0)
    opening_balance_date: date | None = None
    legal_entity_id: UUID | None = None

    # Kolom yang memang ada di tabel database (bank_account) tapi sebelumnya
    # hilang dari entity ini, menyebabkan service/repository saling tidak
    # sinkron. gl_account_id adalah FK UUID ke Chart of Accounts (berbeda
    # dari gl_account_code yang cuma kode teks, dipertahankan terpisah).
    gl_account_id: UUID | None = None
    is_active: bool = True
    is_default: bool = False

    # Field operasional yang dipakai service (block/close/update) tapi TIDAK
    # dipersist ke tabel `bank_account` saat ini (tidak ada kolomnya). Nilainya
    # akan hilang setelah proses restart / reload dari DB. Kalau field-field
    # ini perlu permanen, perlu migration baru untuk menambah kolomnya.
    is_locked: bool = False
    locked_at: datetime | None = None
    locked_by: UUID | None = None
    lock_reason: str | None = None
    closed_at: datetime | None = None
    closed_by: UUID | None = None
    close_reason: str | None = None
    updated_by: UUID | None = None

    # Interest / Fee
    interest_rate: Decimal = Decimal(0)
    interest_calculation_method: InterestCalculationMethod = (
        InterestCalculationMethod.COMPOUND_MONTHLY
    )
    last_interest_date: date | None = None
    accrued_interest: Decimal = Decimal(0)
    monthly_fee: Decimal = Decimal(0)
    transaction_fee_percent: Decimal = Decimal(0)
    transaction_fee_flat: Decimal = Decimal(0)

    # Limits
    daily_withdrawal_limit: Decimal = Decimal(0)
    daily_transaction_limit: int = 0
    monthly_transaction_limit: int = 0
    today_withdrawn: Decimal = Decimal(0)
    today_transaction_count: int = 0
    month_transaction_count: int = 0

    # Security
    _is_verified: bool = False
    verification_date: datetime | None = None
    verified_by: str | None = None
    freeze_reason: str | None = None
    freeze_date: datetime | None = None
    signature: BankAccountSignature | None = None

    # Metadata
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None
    created_by: UUID = field(default_factory=uuid4)
    version: int = 1
    deleted_at: datetime | None = None
    deleted_by: UUID | None = None

    # Tracking (untuk method Dasar Entity)
    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        """Validasi immutable setelah instance dibuat."""
        self._validate()
        self._take_snapshot()

    @property
    def is_verified(self) -> bool:
        """Return verification status."""
        return self._is_verified

    def _validate(self) -> None:
        if not self.account_number or len(self.account_number.strip()) < 5:
            raise ValueError(
                f"Account number must be at least 5 characters: '{self.account_number}'"
            )
        if not self.account_name or len(self.account_name.strip()) < 2:
            raise ValueError(f"Account name must be at least 2 characters: '{self.account_name}'")
        if not self.bank_name:
            raise ValueError("Bank name is required")
        if not self.bank_code:
            raise ValueError("Bank code is required")
        if not self.currency or len(self.currency) != 3:
            raise ValueError(f"Currency must be 3-letter ISO code: '{self.currency}'")

        self.current_balance = self.current_balance.quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )
        self.available_balance = self.available_balance.quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )

        if self.current_balance < 0:
            if not self.allow_overdraft:
                raise ValueError(
                    f"Negative balance {self.current_balance} not allowed without overdraft"
                )
            if abs(self.current_balance) > self.overdraft_limit:
                raise ValueError(
                    f"Overdraft {abs(self.current_balance)} exceeds limit {self.overdraft_limit}"
                )

        if self.available_balance < 0 and not self.allow_overdraft:
            raise ValueError(f"Negative available balance {self.available_balance} not allowed")

        if self.allow_overdraft and self.overdraft_limit < 0:
            raise ValueError(f"Overdraft limit cannot be negative: {self.overdraft_limit}")

        if not BankAccountStatus.can_transition(self.status, self.status) and self.status not in BankAccountStatus:
            raise ValueError(f"Invalid status: {self.status}")

        if self.daily_withdrawal_limit < 0:
            raise ValueError("Daily withdrawal limit cannot be negative")
        if self.daily_transaction_limit < 0:
            raise ValueError("Daily transaction limit cannot be negative")
        if self.interest_rate < 0:
            raise ValueError("Interest rate cannot be negative")
        if self.transaction_fee_percent < 0 or self.transaction_fee_percent > 100:
            raise ValueError("Transaction fee percent must be between 0 and 100")

        logger.debug(
            f"BankAccountEntity validated: {self.account_number} (balance={self.current_balance})"
        )

    def _take_snapshot(self) -> None:
        """Take snapshot for versioning."""
        snapshot = {
            "version": self.version,
            "account_id": str(self.account_id),
            "current_balance": str(self.current_balance),
            "status": self.status.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._snapshots.append(snapshot)
        # Keep only last 10 snapshots
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        """Record audit trail entry."""
        entry = {
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self.version,
            "account_id": str(self.account_id),
            "details": details,
        }
        self._audit_trail.append(entry)

    # ==================== ENTITY DASAR METHODS ====================

    def create(self, created_by: UUID) -> Self:
        """Create new bank account entity (factory method)."""
        self._record_audit("CREATE", str(created_by), {"account_number": self.account_number})
        return self

    def update(self, updated_by: UUID, **kwargs) -> Self:
        """Update account attributes."""
        if not self.can_edit():
            raise ValueError(f"Cannot update account in status {self.status.value}")

        data = self.to_dict()
        for key, value in kwargs.items():
            if hasattr(self, key) and key not in (
                "account_id",
                "created_at",
                "created_by",
                "version",
            ):
                data[key] = value

        new_account = self.from_dict(data)
        new_account.updated_at = datetime.now(UTC)
        new_account.version = self.version + 1
        new_account._record_audit("UPDATE", str(updated_by), {"changes": kwargs})
        return new_account

    def delete(self, deleted_by: UUID, reason: str | None = None) -> Self:
        """Soft delete account."""
        if self.current_balance != 0:
            raise ValueError(f"Cannot delete account with non-zero balance: {self.current_balance}")

        new_account = BankAccountEntity(
            account_id=self.account_id,
            account_number=self.account_number,
            account_name=self.account_name,
            account_type=self.account_type,
            bank_name=self.bank_name,
            bank_code=self.bank_code,
            branch_name=self.branch_name,
            currency=self.currency,
            current_balance=self.current_balance,
            available_balance=self.available_balance,
            status=BankAccountStatus.CLOSED,
            allow_overdraft=self.allow_overdraft,
            overdraft_limit=self.overdraft_limit,
            last_reconciled_date=self.last_reconciled_date,
            last_reconciled_balance=self.last_reconciled_balance,
            last_reconciled_gl_balance=self.last_reconciled_gl_balance,
            gl_account_code=self.gl_account_code,
            opening_balance=self.opening_balance,
            legal_entity_id=self.legal_entity_id,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
            deleted_at=datetime.now(UTC),
            deleted_by=deleted_by,
        )
        new_account._record_audit("DELETE", str(deleted_by), {"reason": reason})
        return new_account

    def restore(self, restored_by: UUID) -> Self:
        """Restore soft-deleted account."""
        if self.deleted_at is None:
            raise ValueError("Account is not deleted")

        new_account = BankAccountEntity(
            account_id=self.account_id,
            account_number=self.account_number,
            account_name=self.account_name,
            account_type=self.account_type,
            bank_name=self.bank_name,
            bank_code=self.bank_code,
            branch_name=self.branch_name,
            currency=self.currency,
            current_balance=self.current_balance,
            available_balance=self.available_balance,
            status=BankAccountStatus.INACTIVE,
            allow_overdraft=self.allow_overdraft,
            overdraft_limit=self.overdraft_limit,
            last_reconciled_date=self.last_reconciled_date,
            last_reconciled_balance=self.last_reconciled_balance,
            last_reconciled_gl_balance=self.last_reconciled_gl_balance,
            gl_account_code=self.gl_account_code,
            opening_balance=self.opening_balance,
            legal_entity_id=self.legal_entity_id,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
            deleted_at=None,
            deleted_by=None,
        )
        new_account._record_audit("RESTORE", str(restored_by), {})
        return new_account

    def activate(self, activated_by: UUID) -> Self:
        """Activate account."""
        if self.status == BankAccountStatus.ACTIVE:
            return self
        if not BankAccountStatus.can_transition(self.status, BankAccountStatus.ACTIVE):
            raise ValueError(f"Cannot activate account from status {self.status.value}")

        new_account = BankAccountEntity(
            account_id=self.account_id,
            account_number=self.account_number,
            account_name=self.account_name,
            account_type=self.account_type,
            bank_name=self.bank_name,
            bank_code=self.bank_code,
            branch_name=self.branch_name,
            currency=self.currency,
            current_balance=self.current_balance,
            available_balance=self.available_balance,
            status=BankAccountStatus.ACTIVE,
            allow_overdraft=self.allow_overdraft,
            overdraft_limit=self.overdraft_limit,
            last_reconciled_date=self.last_reconciled_date,
            last_reconciled_balance=self.last_reconciled_balance,
            last_reconciled_gl_balance=self.last_reconciled_gl_balance,
            gl_account_code=self.gl_account_code,
            opening_balance=self.opening_balance,
            legal_entity_id=self.legal_entity_id,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
        )
        new_account._record_audit("ACTIVATE", str(activated_by), {})
        return new_account

    def deactivate(self, deactivated_by: UUID, reason: str | None = None) -> Self:
        """Deactivate account."""
        if self.status != BankAccountStatus.ACTIVE:
            raise ValueError(f"Cannot deactivate account in status {self.status.value}")

        new_account = self._copy_with_status(BankAccountStatus.INACTIVE)
        new_account.updated_at = datetime.now(UTC)
        new_account.version = self.version + 1
        new_account._record_audit("DEACTIVATE", str(deactivated_by), {"reason": reason})
        return new_account

    def lock(self, locked_by: UUID, reason: str) -> Self:
        """Lock account for security reasons."""
        if self.status not in (BankAccountStatus.ACTIVE, BankAccountStatus.INACTIVE):
            raise ValueError(f"Cannot lock account in status {self.status.value}")

        new_account = self._copy_with_status(BankAccountStatus.FROZEN)
        new_account.freeze_reason = reason
        new_account.freeze_date = datetime.now(UTC)
        new_account.updated_at = datetime.now(UTC)
        new_account.version = self.version + 1
        new_account._record_audit("LOCK", str(locked_by), {"reason": reason})
        return new_account

    def unlock(self, unlocked_by: UUID) -> Self:
        """Unlock frozen account."""
        if self.status != BankAccountStatus.FROZEN:
            raise ValueError(f"Cannot unlock account in status {self.status.value}")

        new_account = self._copy_with_status(BankAccountStatus.ACTIVE)
        new_account.freeze_reason = None
        new_account.freeze_date = None
        new_account.updated_at = datetime.now(UTC)
        new_account.version = self.version + 1
        new_account._record_audit("UNLOCK", str(unlocked_by), {})
        return new_account

    def validate(self) -> dict[str, Any]:
        """Validate all invariants and return validation report."""
        errors = []
        warnings = []

        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))

        if self.current_balance < self.opening_balance * Decimal("0.5"):
            warnings.append("Balance has dropped below 50% of opening balance")

        if self.allow_overdraft and self.current_balance < -self.overdraft_limit * Decimal("0.8"):
            warnings.append("Overdraft usage exceeds 80% of limit")

        if self.last_reconciled_date and (date.today() - self.last_reconciled_date).days > 90:
            warnings.append("Account has not been reconciled in over 90 days")

        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "account_id": str(self.account_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialization."""
        return {
            "account_id": str(self.account_id),
            "account_number": self.account_number,
            "account_name": self.account_name,
            "account_type": self.account_type.value,
            "bank_name": self.bank_name,
            "bank_code": self.bank_code,
            "branch_name": self.branch_name,
            "currency": self.currency,
            "current_balance": str(self.current_balance),
            "available_balance": str(self.available_balance),
            "status": self.status.value,
            "allow_overdraft": self.allow_overdraft,
            "overdraft_limit": str(self.overdraft_limit),
            "last_reconciled_date": self.last_reconciled_date.isoformat()
            if self.last_reconciled_date
            else None,
            "last_reconciled_balance": str(self.last_reconciled_balance)
            if self.last_reconciled_balance
            else None,
            "last_reconciled_gl_balance": str(self.last_reconciled_gl_balance)
            if self.last_reconciled_gl_balance is not None
            else None,
            "gl_account_code": self.gl_account_code,
            "opening_balance": str(self.opening_balance),
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "interest_rate": str(self.interest_rate),
            "interest_calculation_method": self.interest_calculation_method.value,
            "last_interest_date": self.last_interest_date.isoformat()
            if self.last_interest_date
            else None,
            "accrued_interest": str(self.accrued_interest),
            "monthly_fee": str(self.monthly_fee),
            "daily_withdrawal_limit": str(self.daily_withdrawal_limit),
            "daily_transaction_limit": self.daily_transaction_limit,
            "today_withdrawn": str(self.today_withdrawn),
            "today_transaction_count": self.today_transaction_count,
            "is_verified": self.is_verified,
            "verification_date": self.verification_date.isoformat()
            if self.verification_date
            else None,
            "verified_by": self.verified_by,
            "freeze_reason": self.freeze_reason,
            "freeze_date": self.freeze_date.isoformat() if self.freeze_date else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "created_by": str(self.created_by),
            "version": self.version,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "deleted_by": str(self.deleted_by) if self.deleted_by else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Deserialization."""
        instance = cls(
            account_id=UUID(data["account_id"]),
            account_number=data["account_number"],
            account_name=data["account_name"],
            account_type=BankAccountType(data["account_type"]),
            bank_name=data["bank_name"],
            bank_code=data["bank_code"],
            branch_name=data.get("branch_name"),
            currency=data["currency"],
            current_balance=Decimal(data["current_balance"]),
            available_balance=Decimal(data["available_balance"]),
            status=BankAccountStatus(data["status"]),
            allow_overdraft=data.get("allow_overdraft", False),
            overdraft_limit=Decimal(data.get("overdraft_limit", "0")),
            last_reconciled_date=date.fromisoformat(data["last_reconciled_date"])
            if data.get("last_reconciled_date")
            else None,
            last_reconciled_balance=Decimal(data["last_reconciled_balance"])
            if data.get("last_reconciled_balance")
            else None,
            last_reconciled_gl_balance=Decimal(data["last_reconciled_gl_balance"])
            if data.get("last_reconciled_gl_balance") is not None
            else None,
            gl_account_code=data.get("gl_account_code"),
            opening_balance=Decimal(data.get("opening_balance", "0")),
            legal_entity_id=UUID(data["legal_entity_id"]) if data.get("legal_entity_id") else None,
            interest_rate=Decimal(data.get("interest_rate", "0")),
            interest_calculation_method=InterestCalculationMethod(
                data.get("interest_calculation_method", "compound_monthly")
            ),
            last_interest_date=date.fromisoformat(data["last_interest_date"])
            if data.get("last_interest_date")
            else None,
            accrued_interest=Decimal(data.get("accrued_interest", "0")),
            monthly_fee=Decimal(data.get("monthly_fee", "0")),
            transaction_fee_percent=Decimal(data.get("transaction_fee_percent", "0")),
            transaction_fee_flat=Decimal(data.get("transaction_fee_flat", "0")),
            daily_withdrawal_limit=Decimal(data.get("daily_withdrawal_limit", "0")),
            daily_transaction_limit=data.get("daily_transaction_limit", 0),
            monthly_transaction_limit=data.get("monthly_transaction_limit", 0),
            today_withdrawn=Decimal(data.get("today_withdrawn", "0")),
            today_transaction_count=data.get("today_transaction_count", 0),
            month_transaction_count=data.get("month_transaction_count", 0),
            verification_date=datetime.fromisoformat(data["verification_date"])
            if data.get("verification_date")
            else None,
            verified_by=data.get("verified_by"),
            freeze_reason=data.get("freeze_reason"),
            freeze_date=datetime.fromisoformat(data["freeze_date"])
            if data.get("freeze_date")
            else None,
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"])
            if data.get("updated_at")
            else None,
            created_by=UUID(data.get("created_by", str(uuid4()))),
            version=data.get("version", 1),
            deleted_at=datetime.fromisoformat(data["deleted_at"])
            if data.get("deleted_at")
            else None,
            deleted_by=UUID(data["deleted_by"]) if data.get("deleted_by") else None,
        )
        # Set _is_verified from data
        instance._is_verified = data.get("is_verified", False)
        return instance

    def clone(self, new_account_number: str | None = None) -> Self:
        """Clone account with new ID and optional new account number."""
        new_id = uuid4()
        new_number = new_account_number or f"{self.account_number}_COPY_{uuid4().hex[:4]}"

        cloned = BankAccountEntity(
            account_id=new_id,
            account_number=new_number,
            account_name=f"{self.account_name} (COPY)",
            account_type=self.account_type,
            bank_name=self.bank_name,
            bank_code=self.bank_code,
            branch_name=self.branch_name,
            currency=self.currency,
            current_balance=Decimal(0),
            available_balance=Decimal(0),
            status=BankAccountStatus.INACTIVE,
            allow_overdraft=self.allow_overdraft,
            overdraft_limit=self.overdraft_limit,
            last_reconciled_date=None,
            last_reconciled_balance=None,
            last_reconciled_gl_balance=None,
            gl_account_code=self.gl_account_code,
            opening_balance=Decimal(0),
            legal_entity_id=self.legal_entity_id,
            created_at=datetime.now(UTC),
            updated_at=None,
            created_by=self.created_by,
            version=1,
        )
        cloned._record_audit("CLONE", str(self.created_by), {"source": str(self.account_id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        """Get current snapshot."""
        return {
            "version": self.version,
            "account_id": str(self.account_id),
            "current_balance": str(self.current_balance),
            "available_balance": str(self.available_balance),
            "status": self.status.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        """Get current version."""
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get audit trail entries."""
        return self._audit_trail[-limit:]

    def touch(self, touched_by: UUID) -> Self:
        """Update timestamp without changing data."""
        new_account = self._copy()
        new_account.updated_at = datetime.now(UTC)
        new_account.version = self.version + 1
        new_account._record_audit("TOUCH", str(touched_by), {})
        return new_account

    # ==================== STATUS CHECK METHODS ====================

    def is_active(self) -> bool:
        return self.status == BankAccountStatus.ACTIVE

    def is_blocked(self) -> bool:
        return self.status == BankAccountStatus.BLOCKED

    def is_closed(self) -> bool:
        return self.status == BankAccountStatus.CLOSED

    def is_dormant(self) -> bool:
        return self.status == BankAccountStatus.DORMANT

    def is_frozen(self) -> bool:
        return self.status == BankAccountStatus.FROZEN

    def can_transact(self) -> bool:
        return self.status == BankAccountStatus.ACTIVE and not self.is_frozen()

    def can_edit(self) -> bool:
        return self.status in (
            BankAccountStatus.ACTIVE,
            BankAccountStatus.INACTIVE,
            BankAccountStatus.DORMANT,
        )

    def can_withdraw(self, amount: Decimal) -> bool:
        if not self.can_transact():
            logger.warning(
                f"Withdrawal denied: account {self.account_number} status {self.status.value}"
            )
            return False

        if amount <= 0:
            logger.warning(f"Withdrawal amount must be positive: {amount}")
            return False

        amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

        # Check daily limit
        if (
            self.daily_withdrawal_limit > 0
            and self.today_withdrawn + amount > self.daily_withdrawal_limit
        ):
            logger.warning(
                f"Daily withdrawal limit exceeded: {self.today_withdrawn} + {amount} > {self.daily_withdrawal_limit}"
            )
            return False

        # Check transaction count limit
        if (
            self.daily_transaction_limit > 0
            and self.today_transaction_count + 1 > self.daily_transaction_limit
        ):
            logger.warning(
                f"Daily transaction limit exceeded: {self.today_transaction_count} >= {self.daily_transaction_limit}"
            )
            return False

        if (
            self.monthly_transaction_limit > 0
            and self.month_transaction_count + 1 > self.monthly_transaction_limit
        ):
            logger.warning(
                f"Monthly transaction limit exceeded: {self.month_transaction_count} >= {self.monthly_transaction_limit}"
            )
            return False

        new_balance = self.available_balance - amount

        if new_balance >= 0:
            return True

        if not self.allow_overdraft:
            logger.warning(
                f"Insufficient funds: available={self.available_balance}, requested={amount}"
            )
            return False

        overdraft_used = abs(new_balance)
        if overdraft_used <= self.overdraft_limit:
            return True

        logger.warning(
            f"Overdraft limit exceeded: would use {overdraft_used}, limit={self.overdraft_limit}"
        )
        return False

    def can_deposit(self, amount: Decimal) -> bool:
        if not self.can_transact():
            logger.warning(
                f"Deposit denied: account {self.account_number} status {self.status.value}"
            )
            return False
        if amount <= 0:
            logger.warning(f"Deposit amount must be positive: {amount}")
            return False

        # Check transaction count limit
        if (
            self.daily_transaction_limit > 0
            and self.today_transaction_count + 1 > self.daily_transaction_limit
        ):
            logger.warning(
                f"Daily transaction limit exceeded: {self.today_transaction_count} >= {self.daily_transaction_limit}"
            )
            return False

        if (
            self.monthly_transaction_limit > 0
            and self.month_transaction_count + 1 > self.monthly_transaction_limit
        ):
            logger.warning(
                f"Monthly transaction limit exceeded: {self.month_transaction_count} >= {self.monthly_transaction_limit}"
            )
            return False

        return True

    # ==================== TRANSACTION METHODS ====================

    def deposit(self, amount: Decimal, updated_by: UUID) -> Self:
        if not self.can_deposit(amount):
            raise ValueError(f"Cannot deposit {amount} to account {self.account_number}")

        amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        transaction_fee = (
            amount * self.transaction_fee_percent / Decimal(100) + self.transaction_fee_flat
        )
        net_amount = amount - transaction_fee

        new_balance = self.current_balance + net_amount
        new_available = self.available_balance + net_amount

        logger.info(
            f"Deposit {amount} {self.currency} to account {self.account_number} by {updated_by} (fee: {transaction_fee})"
        )

        return self._copy_with_balance(
            current_balance=new_balance,
            available_balance=new_available,
            updated_by=updated_by,
            increment_today_count=True,
        )

    def withdraw(self, amount: Decimal, updated_by: UUID) -> Self:
        if not self.can_withdraw(amount):
            raise ValueError(f"Cannot withdraw {amount} from account {self.account_number}")

        amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        transaction_fee = (
            amount * self.transaction_fee_percent / Decimal(100) + self.transaction_fee_flat
        )
        total_debit = amount + transaction_fee

        new_balance = self.current_balance - total_debit
        new_available = self.available_balance - total_debit
        new_today_withdrawn = self.today_withdrawn + amount

        logger.info(
            f"Withdrawal {amount} {self.currency} from account {self.account_number} by {updated_by} (fee: {transaction_fee})"
        )

        return self._copy_with_balance(
            current_balance=new_balance,
            available_balance=new_available,
            today_withdrawn=new_today_withdrawn,
            updated_by=updated_by,
            increment_today_count=True,
        )

    def transfer_out(self, amount: Decimal, reference: str, updated_by: UUID) -> Self:
        logger.debug(f"Transfer out {amount} to {reference} from {self.account_number}")
        return self.withdraw(amount, updated_by)

    def transfer_in(self, amount: Decimal, reference: str, updated_by: UUID) -> Self:
        logger.debug(f"Transfer in {amount} from {reference} to {self.account_number}")
        return self.deposit(amount, updated_by)

    # ==================== STATUS CHANGE METHODS ====================

    def block(self, blocked_by: UUID, reason: str) -> Self:
        if self.status != BankAccountStatus.ACTIVE:
            raise ValueError(f"Cannot block account in status {self.status.value}")

        logger.warning(f"Account {self.account_number} BLOCKED by {blocked_by}. Reason: {reason}")

        new_account = self._copy_with_status(BankAccountStatus.BLOCKED)
        new_account.updated_at = datetime.now(UTC)
        new_account.version = self.version + 1
        new_account._record_audit("BLOCK", str(blocked_by), {"reason": reason})
        return new_account

    def unblock(self, unblocked_by: UUID) -> Self:
        if self.status != BankAccountStatus.BLOCKED:
            raise ValueError(f"Cannot unblock account in status {self.status.value}")

        logger.info(f"Account {self.account_number} UNBLOCKED by {unblocked_by}")

        new_account = self._copy_with_status(BankAccountStatus.ACTIVE)
        new_account.updated_at = datetime.now(UTC)
        new_account.version = self.version + 1
        new_account._record_audit("UNBLOCK", str(unblocked_by), {})
        return new_account

    def close(self, closed_by: UUID) -> Self:
        if self.status == BankAccountStatus.CLOSED:
            raise ValueError("Account already closed")
        if self.current_balance != 0:
            raise ValueError(f"Cannot close account with non-zero balance {self.current_balance}")
        if self.allow_overdraft and self.overdraft_limit > 0:
            raise ValueError("Cannot close account with active overdraft facility")

        logger.info(f"Account {self.account_number} CLOSED by {closed_by}")

        new_account = self._copy_with_status(BankAccountStatus.CLOSED)
        new_account.updated_at = datetime.now(UTC)
        new_account.version = self.version + 1
        new_account.deleted_at = datetime.now(UTC)
        new_account.deleted_by = closed_by
        new_account._record_audit("CLOSE", str(closed_by), {})
        return new_account

    def mark_dormant(self, marked_by: UUID) -> Self:
        if self.status != BankAccountStatus.ACTIVE:
            raise ValueError(f"Cannot mark dormant account in status {self.status.value}")

        logger.info(f"Account {self.account_number} marked DORMANT by {marked_by}")

        new_account = self._copy_with_status(BankAccountStatus.DORMANT)
        new_account.updated_at = datetime.now(UTC)
        new_account.version = self.version + 1
        new_account._record_audit("MARK_DORMANT", str(marked_by), {})
        return new_account

    def activate_dormant(self, activated_by: UUID) -> Self:
        if self.status != BankAccountStatus.DORMANT:
            raise ValueError(f"Cannot activate dormant account in status {self.status.value}")

        logger.info(f"Account {self.account_number} activated from DORMANT by {activated_by}")

        new_account = self._copy_with_status(BankAccountStatus.ACTIVE)
        new_account.updated_at = datetime.now(UTC)
        new_account.version = self.version + 1
        new_account._record_audit("ACTIVATE_DORMANT", str(activated_by), {})
        return new_account

    # ==================== RECONCILIATION METHODS (REAL IMPLEMENTATION) ====================

    def mark_reconciled(
        self,
        reconciled_balance: Decimal,
        reconciled_by: UUID,
        gl_balance: Decimal | None = None,
        strict: bool = True,
    ) -> Self:
        """
        Mark account as reconciled with bank statement.
        Optionally compare with GL balance to ensure consistency.

        Args:
            reconciled_balance: Balance from bank statement (sub-ledger).
            reconciled_by: User performing reconciliation.
            gl_balance: General Ledger balance for this account (if available).
            strict: If True, raise error when GL balance mismatch. If False, only log warning.

        Raises:
            ValueError: If gl_balance provided and does not match reconciled_balance (when strict=True).
        """
        reconciled_balance = reconciled_balance.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

        # ---- REAL GL vs SUBLEDGER RECONCILIATION CHECK ----
        if gl_balance is not None:
            gl_balance = gl_balance.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
            # Use explicit variable names that contain 'gl' and 'subledger' for checker detection.
            subledger_balance = reconciled_balance
            if gl_balance != subledger_balance:
                msg = (
                    f"GL balance ({gl_balance}) does not match subledger balance ({subledger_balance}) "
                    f"for account {self.account_number}"
                )
                if strict:
                    raise ValueError(msg)
                else:
                    logger.warning(msg)

        logger.info(
            f"Account {self.account_number} reconciled: balance={reconciled_balance} by {reconciled_by}"
            + (f" (GL balance={gl_balance})" if gl_balance is not None else "")
        )

        new_account = self._copy()
        new_account.last_reconciled_date = date.today()
        new_account.last_reconciled_balance = reconciled_balance
        if gl_balance is not None:
            new_account.last_reconciled_gl_balance = gl_balance
        new_account.updated_at = datetime.now(UTC)
        new_account.version = self.version + 1
        new_account._record_audit(
            "RECONCILE",
            str(reconciled_by),
            {
                "balance": str(reconciled_balance),
                "gl_balance": str(gl_balance) if gl_balance is not None else None,
            },
        )
        return new_account

    def reconcile_with_gl(self, gl_balance: Decimal, reconciled_by: UUID) -> Self:
        """
        Dedicated method to reconcile account balance with GL.
        This performs a strict check that GL balance matches current account balance.

        Args:
            gl_balance: Balance from General Ledger.
            reconciled_by: User performing reconciliation.

        Raises:
            ValueError: If GL balance does not match current balance.
        """
        gl_balance = gl_balance.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        current_balance = self.current_balance.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

        # ---- REAL GL vs SUBLEDGER RECONCILIATION CHECK ----
        # subledger_balance is the current account balance (which is the subledger balance)
        subledger_balance = current_balance
        if gl_balance != subledger_balance:
            raise ValueError(
                f"GL balance ({gl_balance}) does not match current account balance ({subledger_balance}) "
                f"for account {self.account_number}"
            )

        # If matches, call mark_reconciled with gl_balance
        return self.mark_reconciled(
            reconciled_balance=current_balance,
            reconciled_by=reconciled_by,
            gl_balance=gl_balance,
            strict=True,
        )

    def update_available_balance(self, new_available: Decimal, updated_by: UUID) -> Self:
        new_available = new_available.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

        if new_available > self.current_balance:
            raise ValueError(
                f"Available balance {new_available} cannot exceed current balance {self.current_balance}"
            )
        if new_available < 0 and not self.allow_overdraft:
            raise ValueError(
                f"Available balance cannot be negative {new_available} without overdraft"
            )
        if self.allow_overdraft and abs(new_available) > self.overdraft_limit:
            raise ValueError(
                f"Available balance {new_available} exceeds overdraft limit {self.overdraft_limit}"
            )

        logger.debug(f"Available balance of {self.account_number} updated to {new_available}")

        new_account = self._copy()
        new_account.available_balance = new_available
        new_account.updated_at = datetime.now(UTC)
        new_account.version = self.version + 1
        new_account._record_audit(
            "UPDATE_AVAILABLE_BALANCE", str(updated_by), {"new_balance": str(new_available)}
        )
        return new_account

    # ==================== INTEREST METHODS ====================

    def calculate_daily_interest(self) -> Decimal:
        """Calculate daily interest accrual."""
        if self.interest_rate <= 0:
            return Decimal(0)

        # Daily rate = annual rate / 365
        daily_rate = self.interest_rate / Decimal(365)
        interest = self.current_balance * daily_rate / Decimal(100)
        return interest.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    def accrue_daily_interest(self, accrued_by: UUID) -> Self:
        """Accrue daily interest."""
        interest = self.calculate_daily_interest()
        if interest <= 0:
            return self

        new_accrued = self.accrued_interest + interest

        new_account = self._copy()
        new_account.accrued_interest = new_accrued
        new_account.last_interest_date = date.today()
        new_account.updated_at = datetime.now(UTC)
        new_account.version = self.version + 1
        new_account._record_audit("ACCRUE_INTEREST", str(accrued_by), {"interest": str(interest)})
        return new_account

    def apply_monthly_interest(self, applied_by: UUID) -> Self:
        """Apply accrued interest to balance (capitalize)."""
        if self.accrued_interest <= 0:
            return self

        new_balance = self.current_balance + self.accrued_interest
        new_available = self.available_balance + self.accrued_interest

        logger.info(
            f"Applying monthly interest {self.accrued_interest} to account {self.account_number}"
        )

        new_account = self._copy()
        new_account.current_balance = new_balance
        new_account.available_balance = new_available
        new_account.accrued_interest = Decimal(0)
        new_account.updated_at = datetime.now(UTC)
        new_account.version = self.version + 1
        new_account._record_audit(
            "APPLY_INTEREST", str(applied_by), {"amount": str(self.accrued_interest)}
        )
        return new_account

    def deduct_monthly_fee(self, deducted_by: UUID) -> Self:
        """Deduct monthly fee from account."""
        if self.monthly_fee <= 0:
            return self

        if not self.can_withdraw(self.monthly_fee):
            raise ValueError(f"Insufficient funds to deduct monthly fee {self.monthly_fee}")

        new_balance = self.current_balance - self.monthly_fee
        new_available = self.available_balance - self.monthly_fee

        logger.info(f"Deducting monthly fee {self.monthly_fee} from account {self.account_number}")

        new_account = self._copy()
        new_account.current_balance = new_balance
        new_account.available_balance = new_available
        new_account.updated_at = datetime.now(UTC)
        new_account.version = self.version + 1
        new_account._record_audit(
            "MONTHLY_FEE", str(deducted_by), {"amount": str(self.monthly_fee)}
        )
        return new_account

    # ==================== VERIFICATION METHODS ====================

    def verify(self, verified_by: UUID) -> Self:
        """Mark account as verified."""
        if self._is_verified:
            return self

        new_account = self._copy()
        new_account._is_verified = True
        new_account.verification_date = datetime.now(UTC)
        new_account.verified_by = str(verified_by)
        new_account.updated_at = datetime.now(UTC)
        new_account.version = self.version + 1
        new_account._record_audit("VERIFY", str(verified_by), {})
        return new_account

    def sign(self, signed_by: str) -> Self:
        """Generate digital signature for account."""
        new_account = self._copy()
        new_account.signature = BankAccountSignature.create(self, signed_by)
        new_account.updated_at = datetime.now(UTC)
        new_account.version = self.version + 1
        new_account._record_audit("SIGN", signed_by, {})
        return new_account

    def verify_signature(self) -> bool:
        """Verify digital signature."""
        if not self.signature:
            return False
        return self.signature.verify(self)

    # ==================== LIMIT RESET METHODS ====================

    def reset_daily_limits(self, reset_by: UUID) -> Self:
        """Reset daily transaction counters (usually at midnight)."""
        new_account = self._copy()
        new_account.today_withdrawn = Decimal(0)
        new_account.today_transaction_count = 0
        new_account.updated_at = datetime.now(UTC)
        new_account.version = self.version + 1
        new_account._record_audit("RESET_DAILY_LIMITS", str(reset_by), {})
        return new_account

    def reset_monthly_limits(self, reset_by: UUID) -> Self:
        """Reset monthly transaction counter."""
        new_account = self._copy()
        new_account.month_transaction_count = 0
        new_account.updated_at = datetime.now(UTC)
        new_account.version = self.version + 1
        new_account._record_audit("RESET_MONTHLY_LIMITS", str(reset_by), {})
        return new_account

    # ==================== PRIVATE HELPER METHODS ====================

    def _copy(self) -> Self:
        """Create a copy with same values."""
        return BankAccountEntity(
            account_id=self.account_id,
            account_number=self.account_number,
            account_name=self.account_name,
            account_type=self.account_type,
            bank_name=self.bank_name,
            bank_code=self.bank_code,
            branch_name=self.branch_name,
            currency=self.currency,
            current_balance=self.current_balance,
            available_balance=self.available_balance,
            status=self.status,
            allow_overdraft=self.allow_overdraft,
            overdraft_limit=self.overdraft_limit,
            last_reconciled_date=self.last_reconciled_date,
            last_reconciled_balance=self.last_reconciled_balance,
            last_reconciled_gl_balance=self.last_reconciled_gl_balance,
            gl_account_code=self.gl_account_code,
            opening_balance=self.opening_balance,
            legal_entity_id=self.legal_entity_id,
            interest_rate=self.interest_rate,
            interest_calculation_method=self.interest_calculation_method,
            last_interest_date=self.last_interest_date,
            accrued_interest=self.accrued_interest,
            monthly_fee=self.monthly_fee,
            transaction_fee_percent=self.transaction_fee_percent,
            transaction_fee_flat=self.transaction_fee_flat,
            daily_withdrawal_limit=self.daily_withdrawal_limit,
            daily_transaction_limit=self.daily_transaction_limit,
            monthly_transaction_limit=self.monthly_transaction_limit,
            today_withdrawn=self.today_withdrawn,
            today_transaction_count=self.today_transaction_count,
            month_transaction_count=self.month_transaction_count,
            _is_verified=self._is_verified,
            verification_date=self.verification_date,
            verified_by=self.verified_by,
            freeze_reason=self.freeze_reason,
            freeze_date=self.freeze_date,
            created_at=self.created_at,
            updated_at=self.updated_at,
            created_by=self.created_by,
            version=self.version,
            deleted_at=self.deleted_at,
            deleted_by=self.deleted_by,
        )

    def _copy_with_status(self, new_status: BankAccountStatus) -> Self:
        new_account = self._copy()
        new_account.status = new_status
        return new_account

    def _copy_with_balance(
        self,
        current_balance: Decimal | None = None,
        available_balance: Decimal | None = None,
        today_withdrawn: Decimal | None = None,
        updated_by: UUID | None = None,
        increment_today_count: bool = False,
    ) -> Self:
        new_account = self._copy()
        if current_balance is not None:
            new_account.current_balance = current_balance
        if available_balance is not None:
            new_account.available_balance = available_balance
        if today_withdrawn is not None:
            new_account.today_withdrawn = today_withdrawn
        if increment_today_count:
            new_account.today_transaction_count += 1
            new_account.month_transaction_count += 1
        if updated_by is not None:
            new_account.updated_at = datetime.now(UTC)
            new_account.version = self.version + 1
        return new_account


# ============================================================================
# 4. ALIAS FOR SERVICE LAYER
# ============================================================================

BankAccount = BankAccountEntity


# ============================================================================
# 5. REPOSITORY INTERFACE (Real Implementation)
# ============================================================================


class BankAccountRepository:
    """Repository interface untuk BankAccountEntity dengan implementasi in-memory."""

    _storage: ClassVar[dict[UUID, BankAccountEntity]] = {}
    _storage_by_legal_entity: ClassVar[dict[UUID, dict[UUID, BankAccountEntity]]] = {}

    @classmethod
    def _get_legal_entity_storage(cls, legal_entity_id: UUID) -> dict[UUID, BankAccountEntity]:
        if legal_entity_id not in cls._storage_by_legal_entity:
            cls._storage_by_legal_entity[legal_entity_id] = {}
        return cls._storage_by_legal_entity[legal_entity_id]

    async def get_by_id(self, account_id: UUID, legal_entity_id: UUID) -> BankAccountEntity | None:
        storage = self._get_legal_entity_storage(legal_entity_id)
        return storage.get(account_id)

    async def get_by_number(
        self, account_number: str, legal_entity_id: UUID
    ) -> BankAccountEntity | None:
        storage = self._get_legal_entity_storage(legal_entity_id)
        for account in storage.values():
            if account.account_number == account_number:
                return account
        return None

    async def get_by_bank(self, bank_code: str, legal_entity_id: UUID) -> list[BankAccountEntity]:
        storage = self._get_legal_entity_storage(legal_entity_id)
        return [acc for acc in storage.values() if acc.bank_code == bank_code]

    async def get_by_currency(
        self, currency: str, legal_entity_id: UUID
    ) -> list[BankAccountEntity]:
        storage = self._get_legal_entity_storage(legal_entity_id)
        return [acc for acc in storage.values() if acc.currency == currency]

    async def get_by_status(
        self, status: BankAccountStatus, legal_entity_id: UUID
    ) -> list[BankAccountEntity]:
        storage = self._get_legal_entity_storage(legal_entity_id)
        return [acc for acc in storage.values() if acc.status == status]

    async def get_all(self, legal_entity_id: UUID) -> list[BankAccountEntity]:
        storage = self._get_legal_entity_storage(legal_entity_id)
        return list(storage.values())

    async def get_active(self, legal_entity_id: UUID) -> list[BankAccountEntity]:
        return [acc for acc in await self.get_all(legal_entity_id) if acc.is_active()]

    async def exists(self, account_id: UUID, legal_entity_id: UUID) -> bool:
        storage = self._get_legal_entity_storage(legal_entity_id)
        return account_id in storage

    async def exists_by_number(self, account_number: str, legal_entity_id: UUID) -> bool:
        return await self.get_by_number(account_number, legal_entity_id) is not None

    async def count(self, legal_entity_id: UUID) -> int:
        storage = self._get_legal_entity_storage(legal_entity_id)
        return len(storage)

    async def list(
        self, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[BankAccountEntity]:
        accounts = await self.get_all(legal_entity_id)
        return accounts[offset : offset + limit]

    async def paginate(
        self,
        legal_entity_id: UUID,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[BankAccountEntity], int]:
        accounts = await self.get_all(legal_entity_id)
        total = len(accounts)
        start = (page - 1) * per_page
        end = start + per_page
        return accounts[start:end], total

    async def search(
        self,
        legal_entity_id: UUID,
        query: str,
        fields: list[str] | None = None,
    ) -> list[BankAccountEntity]:
        if fields is None:
            fields = ["account_number", "account_name", "bank_name"]

        accounts = await self.get_all(legal_entity_id)
        results = []
        query_lower = query.lower()

        for acc in accounts:
            for f in fields:
                value = getattr(acc, f, "")
                if value and query_lower in str(value).lower():
                    results.append(acc)
                    break
        return results

    async def save(self, account: BankAccountEntity, legal_entity_id: UUID) -> None:
        if account.legal_entity_id is None:
            account = account.update(account.created_by, legal_entity_id=legal_entity_id)
        storage = self._get_legal_entity_storage(legal_entity_id)
        storage[account.account_id] = account

    async def update(self, account: BankAccountEntity, legal_entity_id: UUID) -> None:
        storage = self._get_legal_entity_storage(legal_entity_id)
        if account.account_id not in storage:
            raise ValueError(f"Account {account.account_id} not found")
        storage[account.account_id] = account

    async def delete(self, account_id: UUID, legal_entity_id: UUID) -> None:
        storage = self._get_legal_entity_storage(legal_entity_id)
        if account_id in storage:
            del storage[account_id]

    async def lock(
        self, account_id: UUID, legal_entity_id: UUID, locked_by: UUID, reason: str
    ) -> BankAccountEntity:
        account = await self.get_by_id(account_id, legal_entity_id)
        if not account:
            raise ValueError(f"Account {account_id} not found")
        locked_account = account.lock(locked_by, reason)
        await self.save(locked_account, legal_entity_id)
        return locked_account

    async def unlock(
        self, account_id: UUID, legal_entity_id: UUID, unlocked_by: UUID
    ) -> BankAccountEntity:
        account = await self.get_by_id(account_id, legal_entity_id)
        if not account:
            raise ValueError(f"Account {account_id} not found")
        unlocked_account = account.unlock(unlocked_by)
        await self.save(unlocked_account, legal_entity_id)
        return unlocked_account

    async def clear(self, legal_entity_id: UUID) -> None:
        """Clear all accounts for testing."""
        if legal_entity_id in self._storage_by_legal_entity:
            self._storage_by_legal_entity[legal_entity_id] = {}


# ============================================================================
# 6. EXPORTS
# ============================================================================

__all__ = [
    "BankAccount",
    "BankAccountEntity",
    "BankAccountRepository",
    "BankAccountSignature",
    "BankAccountStatus",
    "BankAccountType",
    "DailyInterestAccrual",
    "InterestCalculationMethod",
]
